"""
Jefferies Research Portal Scraper

Workflow:
1. Login (via cookies)
2. Navigate directly to /adv_search, click 'Expand All Filters'
3. Type each tracked ticker into the Ticker autocomplete, click exact match
4. Click 'Search' button
5. Parse Advanced Search Results (sorted newest-first) with BeautifulSoup
6. For each report: navigate → extract content (direct text or PDF fallback)
7. Stop when report date falls outside the `days` window (default 2)
8. Skip previously processed reports (ReportTracker)

Junk cookie poisoning fix:
- 'unauthorized-portal-user' and '_opensaml_req_ss*' cookies are stripped on
  both load (_init_driver) and save (_persist_cookies). These cookies are set
  by the portal on access-restricted pages and poison future auth attempts if
  persisted.

Inherits from BaseScraper for shared cookie/auth/PDF functionality.
"""

import hashlib
import io
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import PyPDF2
import pdfplumber
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from analyst_config_tmt import get_primary_tickers, get_watchlist_tickers
from base_scraper import BaseScraper
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


# Tickers not covered by Jefferies — skip entirely
_JEFFERIES_SKIP_TICKERS = frozenset({'MDB'})

# Jefferies autocomplete works best with full company names for some tickers.
# Keys not in this dict use the ticker symbol as-is.
_JEFFERIES_TICKER_SEARCH_NAMES = {
    'META': 'Meta Platforms, Inc',
    'BABA': 'Alibaba Group Holding Limited',
    '700.HK': 'Tencent Holdings Ltd.',
    'NET': 'Cloudflare, Inc.',
}

# All tickers to search — union of primary and watchlist, minus uncovered tickers
_SEARCH_TICKERS = sorted((get_primary_tickers() | get_watchlist_tickers()) - _JEFFERIES_SKIP_TICKERS)

# Cookies that poison auth — strip on every load and save
_JUNK_COOKIE_NAMES = frozenset({'unauthorized-portal-user', 'IFrame-Request'})
_JUNK_COOKIE_PREFIXES = ('_opensaml_req_ss',)

# Two-domain cookie strategy:
# shib_idp_sso_session and sid are scoped to the IdP domain (oneclient.jefferies.com).
# driver.get_cookies() from content.jefferies.com CANNOT see IdP-domain cookies.
# We must set them on oneclient.jefferies.com and collect them from there.
_IDP_URL = "https://oneclient.jefferies.com"
# shib_idp_sso_session lives on oneclient.jefferies.com (IdP domain).
# sid lives on content.jefferies.com — do NOT plant it on the IdP domain.
_IDP_COOKIE_NAMES = frozenset({'shib_idp_sso_session'})


class JefferiesScraper(BaseScraper):
    """Scraper for Jefferies — uses Adv Search filtered by ticker + last 24 hours."""

    PORTAL_NAME = "jefferies"
    CONTENT_URL = "https://content.jefferies.com"
    PDF_STORAGE_DIR = "data/reports/jefferies"

    def __init__(self, headless: bool = True):
        super().__init__(headless=headless)

    # ------------------------------------------------------------------
    # Junk cookie helper
    # ------------------------------------------------------------------

    def _is_junk_cookie(self, name: str) -> bool:
        return name in _JUNK_COOKIE_NAMES or any(name.startswith(p) for p in _JUNK_COOKIE_PREFIXES)

    # ------------------------------------------------------------------
    # Browser setup
    # ------------------------------------------------------------------

    def _init_driver(self) -> bool:
        if self.driver:
            return True

        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.set_page_load_timeout(30)
        print(f"[{self.PORTAL_NAME}] Initialized Chrome WebDriver")

        cookies = self.cookie_manager.get_cookies('jefferies') or {}

        if cookies:
            # Use CDP Network.setCookie to plant cookies on the correct domain WITHOUT
            # navigating there. oneclient.jefferies.com is not directly reachable, so
            # driver.add_cookie() (which requires being on the target domain) doesn't work.
            # CDP bypasses that restriction and writes directly into Chrome's cookie store.
            self.driver.get("about:blank")
            seeded = 0
            for name, value in cookies.items():
                if self._is_junk_cookie(name):
                    continue
                domain = 'oneclient.jefferies.com' if name in _IDP_COOKIE_NAMES else 'content.jefferies.com'
                try:
                    self.driver.execute_cdp_cmd('Network.setCookie', {
                        'name': name,
                        'value': value,
                        'domain': domain,
                        'path': '/',
                        'secure': True,
                    })
                    seeded += 1
                except Exception:
                    pass
            print(f"[{self.PORTAL_NAME}] ✓ Seeded {seeded} cookies via CDP (IdP + SP domains)")

        # Navigate to SP — if SP session expired, Shibboleth redirects to oneclient.jefferies.com,
        # finds our seeded shib_idp_sso_session + sid, and silently completes the SAML flow back.
        self.driver.get(self.CONTENT_URL)
        for _ in range(8):
            time.sleep(2)
            if 'content.jefferies.com' in self.driver.current_url.lower():
                break

        self.driver.refresh()
        time.sleep(3)

        if not self._check_authentication():
            print(f"[{self.PORTAL_NAME}] ✗ Authentication failed — manual login required")
            return False

        print(f"[{self.PORTAL_NAME}] ✓ Authenticated")
        return True

    def close_driver(self):
        if self.driver:
            self._persist_cookies()
            self.driver.quit()
            self.driver = None
            print(f"[{self.PORTAL_NAME}] ✓ Closed WebDriver")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _check_authentication(self) -> bool:
        try:
            self.driver.get(self.CONTENT_URL)

            for _ in range(3):
                time.sleep(2)
                current_url = self.driver.current_url.lower()
                for indicator in ['oneclient.jefferies.com', 'sso', 'saml', 'login', 'signin', 'shibboleth']:
                    if indicator in current_url:
                        print(f"[{self.PORTAL_NAME}] ✗ Auth check: redirected to login ({indicator})")
                        return False

            current_url = self.driver.current_url.lower()
            if 'content.jefferies.com' not in current_url:
                print(f"[{self.PORTAL_NAME}] ✗ Auth check: not on portal ({current_url[:60]})")
                return False

            page_title = self.driver.title.lower()
            if any(x in page_title for x in ['sign in', 'login', 'sso']):
                print(f"[{self.PORTAL_NAME}] ✗ Auth check: login page detected")
                return False

            page_source = self.driver.page_source.lower()
            if any(x in page_source for x in ['notification', 'followed', 'my research', 'logout', 'sign out', 'profile']):
                print(f"[{self.PORTAL_NAME}] ✓ Auth check: valid session")
                return True

            if sum(1 for m in ['equity research', 'analyst', 'report', 'coverage'] if m in page_source) >= 2:
                print(f"[{self.PORTAL_NAME}] ✓ Auth check: research content accessible")
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Auth check: on portal but no authenticated content")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Auth check error: {e}")
            return False

    def _persist_cookies(self):
        """
        Save updated cookies using CDP Network.getAllCookies to capture ALL domains.
        Standard driver.get_cookies() only returns cookies for the current domain —
        it would miss oneclient.jefferies.com cookies like shib_idp_sso_session and sid.
        CDP has no such restriction.
        """
        if not self.driver:
            return
        try:
            existing = self.cookie_manager.get_cookies('jefferies') or {}
            for name in list(existing.keys()):
                if self._is_junk_cookie(name):
                    del existing[name]

            # CDP: collect cookies from ALL domains in Chrome's store
            try:
                result = self.driver.execute_cdp_cmd('Network.getAllCookies', {})
                for c in result.get('cookies', []):
                    name = c.get('name', '')
                    if not self._is_junk_cookie(name):
                        existing[name] = c.get('value', '')
            except Exception:
                # Fallback to standard get_cookies() if CDP unavailable
                for c in self.driver.get_cookies():
                    if not self._is_junk_cookie(c['name']):
                        existing[c['name']] = c['value']

            self.cookie_manager.save_cookies('jefferies', existing)
            print(f"[{self.PORTAL_NAME}] ✓ Persisted cookies via CDP (all domains, junk filtered)")
        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ⚠ Failed to persist cookies: {e}")

    def _handle_auth_failure(self) -> Dict:
        self._write_auth_alert()
        return {
            'reports': [],
            'failures': ['Authentication required — manual login needed'],
            'auth_required': True,
        }

    # ------------------------------------------------------------------
    # BaseScraper abstract method stubs (not used — get_followed_reports overridden)
    # ------------------------------------------------------------------

    def _navigate_to_notifications(self) -> bool:
        return False

    def _extract_notifications(self) -> List[Dict]:
        return []

    # ------------------------------------------------------------------
    # Advanced Search — step 1: open the panel
    # ------------------------------------------------------------------

    def _navigate_to_adv_search(self) -> bool:
        """
        Navigate to the Adv Search page and wait for 'Expand All Filters' to appear.
        Uses direct URL navigation (reliable) rather than clicking nav elements.
        """
        try:
            adv_search_url = f"{self.CONTENT_URL}/adv_search"
            self.driver.get(adv_search_url)
            print(f"[{self.PORTAL_NAME}] ✓ Navigated to Adv Search")

            # Poll up to 10s for "Expand All Filters" button and click it
            for _ in range(10):
                time.sleep(1)
                for el in self.driver.find_elements(By.CSS_SELECTOR, 'a, button, span, [role="button"]'):
                    try:
                        if 'expand all' in (el.text or '').lower() and el.is_displayed():
                            self.driver.execute_script("arguments[0].click();", el)
                            time.sleep(1.5)
                            print(f"[{self.PORTAL_NAME}] ✓ Clicked 'Expand All Filters'")
                            return True
                    except Exception:
                        continue

            print(f"[{self.PORTAL_NAME}] ⚠ 'Expand All Filters' not found in 10s — proceeding anyway")
            return True

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Adv Search navigation error: {e}")
            return False

    # ------------------------------------------------------------------
    # Advanced Search — step 2: ticker filter
    # ------------------------------------------------------------------

    def _add_ticker_to_filter(self, ticker: str) -> bool:
        """
        Type a ticker into the Ticker autocomplete and click the matching option.
        Option text format: "Company Name\\nTICKER\\nEquity Research..." — match on any line.
        For tickers in _JEFFERIES_TICKER_SEARCH_NAMES: type the full company name (produces
        exactly 1 result) and click it. For all others: type the ticker symbol and match
        the option line-by-line.
        Finds the field container by XPath relative to the Ticker filter-panel-title —
        works even after chips are added (v-field container always visible).
        """
        _TICKER_ANCHOR = "//div[contains(@class,'filter-panel-title') and normalize-space()='Ticker']"
        try:
            # Step 1: Find the v-field container for the Ticker autocomplete
            # (the container is always visible; clicking it activates the hidden input)
            field_container = None
            for xpath in [
                f'{_TICKER_ANCHOR}/following::div[contains(@class,"v-field")][1]',
                f'{_TICKER_ANCHOR}/following::div[contains(@class,"v-input")][1]',
            ]:
                try:
                    field_container = self.driver.find_element(By.XPATH, xpath)
                    break
                except Exception:
                    continue

            if not field_container:
                # Fallback: find by placeholder
                for selector in ['input[placeholder*="Name or Ticker"]', 'input[placeholder*="Ticker"]']:
                    for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
                        field_container = el
                        break
                    if field_container:
                        break

            if not field_container:
                print(f"[{self.PORTAL_NAME}]   ✗ Ticker field container not found — visible inputs:")
                for el in self.driver.find_elements(By.CSS_SELECTOR, 'input'):
                    try:
                        ph = el.get_attribute('placeholder') or ''
                        print(f"    visible={el.is_displayed()} placeholder='{ph[:40]}'")
                    except Exception:
                        pass
                print(f"[{self.PORTAL_NAME}]   ✗ Skipping {ticker}")
                return False

            # Step 2: Click the container to activate Vuetify 3 hidden input
            self.driver.execute_script("arguments[0].click();", field_container)
            time.sleep(0.3)

            # Step 3: Find the <input> inside the container (now activated)
            ticker_input = None
            try:
                ticker_input = field_container.find_element(By.CSS_SELECTOR, 'input')
            except Exception:
                # Container IS the input (fallback path)
                if field_container.tag_name == 'input':
                    ticker_input = field_container

            if not ticker_input:
                # Broader search: any input with placeholder containing ticker keywords
                for selector in ['input[placeholder*="Name or Ticker"]', 'input[placeholder*="Ticker"]',
                                  'input[placeholder*="name"]']:
                    els = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if els:
                        ticker_input = els[0]
                        break

            if not ticker_input:
                print(f"[{self.PORTAL_NAME}]   ✗ Could not locate <input> for {ticker}")
                return False

            # Step 4: Determine search term — full company name or ticker symbol
            search_term = _JEFFERIES_TICKER_SEARCH_NAMES.get(ticker, ticker)
            use_full_name = search_term != ticker  # full-name entries produce exactly 1 result

            ticker_input.clear()
            ticker_input.send_keys(search_term)
            time.sleep(2)

            # Step 5: Find options in Vuetify 3 teleported overlay
            opts = self.driver.find_elements(By.CSS_SELECTOR,
                '.v-overlay__content [role="option"], '
                '.v-overlay__content .v-list-item, '
                '[role="listbox"] [role="option"], '
                '[role="option"]')

            # Option text format: "Company Name\nTICKER\nEquity Research..."
            # For full-name entries: click first non-empty result (exactly 1 expected).
            # For symbol entries: match ticker against any line of the option text.
            for el in opts:
                try:
                    text = (el.text or '').strip()
                    if not text:
                        continue
                    if use_full_name:
                        # Company name typed → one result → click it
                        self.driver.execute_script("arguments[0].click();", el)
                        time.sleep(0.5)
                        print(f"[{self.PORTAL_NAME}]   ✓ Added: {ticker} ({search_term[:30]})")
                        return True
                    else:
                        # Symbol typed → ticker appears on line 2: "Apple Inc.\nAAPL\nEquity..."
                        lines = [l.strip().upper() for l in text.split('\n')]
                        if ticker.upper() in lines:
                            self.driver.execute_script("arguments[0].click();", el)
                            time.sleep(0.5)
                            print(f"[{self.PORTAL_NAME}]   ✓ Added: {ticker}")
                            return True
                except Exception:
                    continue

            # No match — show what appeared
            if opts:
                visible_opts = [o.text.strip()[:30] for o in opts if o.text.strip()][:5]
                print(f"[{self.PORTAL_NAME}]   ⚠ No match for {ticker} (searched '{search_term[:25]}') — options: {visible_opts}")
            else:
                print(f"[{self.PORTAL_NAME}]   ⚠ No autocomplete options appeared for: {ticker}")
            try:
                ticker_input.clear()
            except Exception:
                pass
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}]   ✗ Ticker filter error for {ticker}: {e}")
            return False

    # ------------------------------------------------------------------
    # Advanced Search — step 4: submit
    # ------------------------------------------------------------------

    def _run_search(self) -> bool:
        """Find and click the blue 'Search' button inside the Adv Search panel."""
        try:
            # Do NOT scroll the main page — that moves focus away from the panel
            # and puts unrelated buttons (e.g. 'Load More') in view.
            # Instead, find the Search button and scroll IT into view within its container.
            search_btn = None
            for el in self.driver.find_elements(By.CSS_SELECTOR, 'button, input[type="submit"]'):
                try:
                    text = (el.text or '').strip().lower()
                    if text == 'search':
                        search_btn = el
                        break
                except Exception:
                    continue

            if search_btn:
                # Scroll the button into view within its own scroll container, then click
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'nearest'});", search_btn)
                time.sleep(0.5)
                self.driver.execute_script("arguments[0].click();", search_btn)
                print(f"[{self.PORTAL_NAME}] ✓ Search submitted — waiting for results...")
                time.sleep(5)
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Search button not found — all buttons (visible + hidden):")
            for el in self.driver.find_elements(By.CSS_SELECTOR, 'button'):
                try:
                    text = (el.text or '').strip()
                    if text:
                        print(f"    visible={el.is_displayed()} text='{text[:50]}'")
                except Exception:
                    pass
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Search submission error: {e}")
            return False

    # ------------------------------------------------------------------
    # Advanced Search — step 5: parse results
    # ------------------------------------------------------------------

    def _extract_search_results(self) -> List[Dict]:
        """
        Parse the Advanced Search Results page with BeautifulSoup.
        Returns list of report metadata dicts (url, title, analyst, date).
        """
        results = []
        seen_urls = set()

        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # All report links — Jefferies report URLs contain '/report/'
            report_links = soup.find_all('a', href=re.compile(r'/report/'))

            for link in report_links:
                href = link.get('href', '')
                if not href or 'not-entitled' in href:
                    continue

                if not href.startswith('http'):
                    href = self.CONTENT_URL + href

                if href in seen_urls:
                    continue
                seen_urls.add(href)

                title = link.text.strip()
                if not title:
                    title = link.get('title', 'Untitled')

                # Extract date and analyst from surrounding container
                parent = link.find_parent(['div', 'li', 'article', 'tr'])
                date_str = None
                analyst = None
                if parent:
                    parent_text = parent.get_text(' ', strip=True)
                    pub_date = self._extract_date_from_text(parent_text)
                    date_str = pub_date.strftime('%Y-%m-%d') if pub_date else None
                    analyst = self._extract_analyst_name_from_text(parent_text)

                results.append({
                    'title': title[:200],
                    'url': href,
                    'analyst': analyst,
                    'source': 'Jefferies',
                    'date': date_str,
                })

            print(f"[{self.PORTAL_NAME}] Found {len(results)} reports in search results")
            return results

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Error extracting search results: {e}")
            return []

    # ------------------------------------------------------------------
    # Report navigation and content extraction
    # ------------------------------------------------------------------

    def _navigate_to_report(self, report_url: str) -> bool:
        try:
            self.driver.get(report_url)
            time.sleep(5)
            return True
        except Exception as e:
            print(f"    ✗ Navigation error: {e}")
            return False

    def _extract_report_content(self, report: Dict = None) -> Optional[str]:
        # Try direct page text first
        text = self._extract_text_from_page()
        if text and len(text) > 500:
            print(f"    ✓ Extracted {len(text)} chars from page")
            return text

        # PDF fallback
        pdf_url = self._get_pdf_url()
        if pdf_url:
            self._sync_cookies_from_driver()
            pdf_bytes = self.download_pdf(pdf_url)
            if pdf_bytes:
                if report:
                    pdf_path = self._save_pdf(pdf_bytes, report)
                    if pdf_path:
                        report['pdf_path'] = pdf_path
                text = self.extract_text_from_pdf(pdf_bytes)
                if text:
                    return text
        return None

    def _extract_text_from_page(self) -> Optional[str]:
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            for el in soup(['script', 'style', 'nav', 'header', 'footer']):
                el.decompose()
            for selector in ['.report-content', '.document-content', '.article-content',
                              'article', 'main', '[role="main"]', '.v-main']:
                content = soup.select_one(selector)
                if content:
                    text = content.get_text(separator='\n', strip=True)
                    if len(text) > 500:
                        return text
            body = soup.find('body')
            if body:
                lines = [l for l in body.get_text(separator='\n', strip=True).split('\n') if len(l) > 50]
                return '\n'.join(lines) if lines else None
            return None
        except Exception:
            return None

    def _get_pdf_url(self) -> Optional[str]:
        try:
            # Check iframes for embedded PDF
            for iframe in self.driver.find_elements(By.TAG_NAME, 'iframe'):
                src = iframe.get_attribute('src') or ''
                if 'links2' in src.lower() and 'html' in src.lower():
                    return src.replace('/doc/html/', '/doc/pdf/')

            # Scan page source for links2 PDF URLs
            links2_urls = re.findall(r'(https?://[^\s"\']*links2/doc/[^\s"\']*)', self.driver.page_source)
            for url in links2_urls:
                return url.replace('/doc/html/', '/doc/pdf/')

            # Generic PDF link selectors
            for selector in ['a[href*=".pdf"]', '[aria-label*="PDF"]', '[title*="PDF"]']:
                for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    href = el.get_attribute('href') or ''
                    if '.pdf' in href.lower():
                        return href

            return None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Cookie sync, PDF download, PDF extraction, PDF save
    # ------------------------------------------------------------------

    def _sync_cookies_from_driver(self):
        if not self.driver:
            return
        for cookie in self.driver.get_cookies():
            self.session.cookies.set(cookie['name'], cookie['value'],
                                     domain=cookie.get('domain', ''))

    def download_pdf(self, url: str) -> Optional[bytes]:
        try:
            response = self.session.get(url, timeout=30)
            if response.status_code == 200 and len(response.content) > 1000:
                print(f"    ✓ Downloaded PDF ({len(response.content)} bytes)")
                return response.content
            print(f"    ✗ PDF download failed: HTTP {response.status_code}")
            return None
        except Exception as e:
            print(f"    ✗ PDF download error: {e}")
            return None

    def _save_pdf(self, pdf_content: bytes, report: Dict) -> Optional[str]:
        try:
            pub_date = report.get('date') or datetime.now().strftime('%Y-%m-%d')
            year_month = pub_date[:7]
            analyst = report.get('analyst') or 'unknown'
            analyst_folder = re.sub(r'[^\w\s-]', '', analyst).strip().replace(' ', '_').lower()
            dir_path = os.path.join(self.PDF_STORAGE_DIR, year_month, analyst_folder)
            os.makedirs(dir_path, exist_ok=True)
            url_hash = hashlib.md5(report.get('url', '').encode()).hexdigest()[:12]
            title_slug = re.sub(r'[^\w\s-]', '', report.get('title', '')[:30]).strip().replace(' ', '_').lower()
            filename = f"{pub_date}_{title_slug}_{url_hash}"
            pdf_path = os.path.join(dir_path, f"{filename}.pdf")
            with open(pdf_path, 'wb') as f:
                f.write(pdf_content)
            with open(os.path.join(dir_path, f"{filename}.json"), 'w') as f:
                json.dump({
                    'url': report.get('url'),
                    'title': report.get('title'),
                    'analyst': analyst,
                    'source': report.get('source'),
                    'publish_date': pub_date,
                    'scraped_at': datetime.now().isoformat(),
                    'pdf_size_bytes': len(pdf_content),
                    'pdf_path': pdf_path,
                }, f, indent=2)
            print(f"    ✓ Saved PDF: {pdf_path}")
            return pdf_path
        except Exception as e:
            print(f"    ⚠ Failed to save PDF: {e}")
            return None

    def extract_text_from_pdf(self, pdf_content: bytes) -> str:
        text = ""
        try:
            with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n\n"
            if text.strip():
                return text
        except Exception:
            pass
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
            for page in reader.pages:
                text += page.extract_text() + "\n\n"
            if text.strip():
                return text
        except Exception as e:
            print(f"    ✗ PDF extraction failed: {e}")
        return ""

    # ------------------------------------------------------------------
    # Text parsing helpers
    # ------------------------------------------------------------------

    def _extract_date_from_text(self, text: str) -> Optional[datetime]:
        for pattern in [
            r'(\d{1,2}-[A-Za-z]{3}-\d{4})',
            r'(\d{1,2}/\d{1,2}/\d{4})',
            r'(\d{4}-\d{2}-\d{2})',
            r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})',
            r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})',
            r'((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})',
        ]:
            m = re.search(pattern, text, re.I)
            if m:
                try:
                    return dateparser.parse(m.group(1))
                except Exception:
                    pass
        return None

    def _extract_analyst_name_from_text(self, text: str) -> Optional[str]:
        for pattern in [
            r'by\s+([A-Z][a-z]+\s+[A-Z][a-z]+)',
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s*[-–]',
            r'Author:\s*([A-Z][a-z]+\s+[A-Z][a-z]+)',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        return None

    # ------------------------------------------------------------------
    # Main orchestration
    # ------------------------------------------------------------------

    def get_followed_reports(self, max_reports: int = 20, days: int = 2, result_out: Dict = None) -> Dict:
        """
        Full pipeline: Adv Search → ticker filter → extract content.
        Results are sorted by most recent first. Stops when a report's date falls
        outside the `days` window (default 2 = today + yesterday).
        """
        failures = []
        processed = []

        print(f"\n{'='*50}")
        print(f"[{self.PORTAL_NAME}] Fetching reports via Advanced Search")
        print(f"[{self.PORTAL_NAME}] Tickers: {', '.join(_SEARCH_TICKERS)}")
        print(f"{'='*50}")

        try:
            if not self._init_driver():
                return self._handle_auth_failure()

            self.driver.get(self.CONTENT_URL)
            time.sleep(3)

            # Step 1: Open Advanced Search page
            if not self._navigate_to_adv_search():
                failures.append("Could not open Advanced Search")
                return {'reports': [], 'failures': failures}

            # Step 2: Add all tracked tickers to the Ticker filter
            added_count = 0
            for ticker in _SEARCH_TICKERS:
                if self._add_ticker_to_filter(ticker):
                    added_count += 1
            print(f"[{self.PORTAL_NAME}] Added {added_count}/{len(_SEARCH_TICKERS)} tickers to filter")

            # Step 3: Submit search
            if not self._run_search():
                failures.append("Could not submit search")
                return {'reports': [], 'failures': failures}

            # Step 4: Parse results
            report_metas = self._extract_search_results()

            if not report_metas:
                print(f"[{self.PORTAL_NAME}] No reports found for tracked tickers today")
                return {'reports': [], 'failures': failures}

            # Dedup against already-processed reports
            new_reports = self.report_tracker.filter_unprocessed(report_metas)
            skipped = len(report_metas) - len(new_reports)
            if skipped:
                print(f"[{self.PORTAL_NAME}] Skipped {skipped} already-processed reports")
            print(f"[{self.PORTAL_NAME}] → {len(new_reports)} new reports to process")

            if not new_reports:
                return {'reports': [], 'failures': failures}

            self._sync_cookies_from_driver()

            # Cutoff: results are sorted newest-first; stop when we pass the days window
            cutoff = date.today() - timedelta(days=days - 1)

            # Step 5: Extract content from each report
            for i, report in enumerate(new_reports[:max_reports], 1):
                if not self._is_browser_alive():
                    failures.append("Browser crashed")
                    break

                # Detect mid-run session expiry (login redirect) — surface to UI immediately
                if not self._is_session_valid():
                    print(f"[{self.PORTAL_NAME}] ✗ Session expired mid-run — writing auth alert")
                    self._write_auth_alert()
                    failures.append("Session expired — analyst must refresh Jefferies cookies")
                    break

                # Date gate — stop when we pass the days window (results sorted newest-first)
                report_date_str = report.get('date')
                if report_date_str:
                    try:
                        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
                        if report_date < cutoff:
                            print(f"[{self.PORTAL_NAME}] ✓ Reached reports older than {days} days — stopping")
                            break
                    except Exception:
                        pass  # unparseable date → keep processing

                print(f"\n  [{i}/{min(len(new_reports), max_reports)}] {report['title'][:60]}")

                try:
                    if not self._navigate_to_report(report['url']):
                        failures.append(f"Failed to navigate: {report['title'][:40]}")
                        continue

                    content = self._extract_report_content(report)
                    if content:
                        report['content'] = content
                        processed.append(report)
                        if result_out is not None:
                            result_out['reports'].append(report)
                        self.report_tracker.mark_as_processed(report)
                        print(f"    ✓ Extracted {len(content)} chars")
                    else:
                        failures.append(f"No content: {report['title'][:40]}")

                    if i % 5 == 0:
                        self._persist_cookies()

                except Exception as e:
                    failures.append(f"Error: {report.get('title', '')[:30]}: {e}")
                    print(f"    ⚠ Skipping: {e}")
                    continue

            print(f"\n{'='*50}")
            print(f"[{self.PORTAL_NAME}] ✓ Extracted {len(processed)} reports")
            if failures:
                print(f"[{self.PORTAL_NAME}] ⚠ {len(failures)} failures")
            return {'reports': processed, 'failures': failures}

        except Exception as e:
            failures.append(f"Scraper error: {e}")
            print(f"[{self.PORTAL_NAME}] Scraper error: {e}")
            return {'reports': processed, 'failures': failures}

        finally:
            self._persist_cookies()
            self.close_driver()


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("\nJefferies Scraper Test (Advanced Search)")
    print("=" * 50)
    print(f"Tickers to search ({len(_SEARCH_TICKERS)}): {', '.join(_SEARCH_TICKERS)}")

    # Test 1: Junk cookie filtering
    print("\n[1/2] Testing junk cookie filtering...")
    scraper = JefferiesScraper(headless=True)
    assert scraper._is_junk_cookie('unauthorized-portal-user'), "Should flag unauthorized-portal-user"
    assert scraper._is_junk_cookie('_opensaml_req_ss%3Amem%3A123'), "Should flag opensaml cookies"
    assert scraper._is_junk_cookie('IFrame-Request'), "Should flag IFrame-Request"
    assert not scraper._is_junk_cookie('sid'), "sid is a valid cookie"
    assert not scraper._is_junk_cookie('SESSION'), "SESSION is a valid cookie"
    assert not scraper._is_junk_cookie('_shibsession_abc'), "_shibsession is a valid SP cookie"
    print("✓ Junk cookie filter works correctly")

    # Test 2: Full pipeline
    print("\n[2/2] Running full pipeline (headless=False to observe browser)...")
    scraper2 = JefferiesScraper(headless=False)
    result = scraper2.get_followed_reports(max_reports=10, days=2)

    if result.get('auth_required'):
        print("\n⚠ Authentication required — refresh cookies in data/cookies.json")
        sys.exit(1)

    reports = result.get('reports', [])
    failures = result.get('failures', [])

    print(f"\n--- Results ---")
    print(f"Reports extracted: {len(reports)}")
    print(f"Failures: {len(failures)}")

    for i, r in enumerate(reports[:5], 1):
        print(f"\n  [{i}] {r['title'][:70]}")
        print(f"      Analyst: {r.get('analyst', 'unknown')}")
        print(f"      Date:    {r.get('date', 'unknown')}")
        print(f"      Content: {len(r.get('content', ''))} chars")

    if failures:
        print(f"\n--- Failures ---")
        for f in failures[:5]:
            print(f"  - {f}")

    print("\n✓ Jefferies Advanced Search scraper test complete")
