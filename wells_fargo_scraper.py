"""
Wells Fargo Research Portal Scraper

Same BlueMatrix platform as Jefferies — uses identical Advanced Search workflow:
1. Login via cookies (SESSION + _shibsession_* from research.wellsfargosecurities.com)
2. Navigate directly to /adv_search, click 'Expand All Filters'
3. Type each tracked ticker into the Ticker autocomplete, click exact match
4. Click 'Search' button
5. Parse results with BeautifulSoup — /report/{uuid} links
6. For each report: navigate → extract PDF or page text
7. Stop when report date falls outside the `days` window

Login flow (first time / session expiry):
  Portal URL → click red 'Login' button → enter WF_EMAIL → click blue 'Verify'
  Device already analyst-verified — no code needed. After verify, navigate to CONTENT_URL.

Cookie filtering: _opensaml_req_ss* cookies are in-flight SAML state — strip on load/save.

Inherits from BaseScraper for cookie/auth/PDF functionality.
"""

import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from dateutil import parser as dateparser

from analyst_config_tmt import get_primary_tickers, get_watchlist_tickers
from base_scraper import BaseScraper

load_dotenv()

_DEFAULT_PORTAL_URL = "https://research.wellsfargosecurities.com"

# Cookies that are in-flight SAML state — strip on every load and save
_JUNK_COOKIE_PREFIXES = ('_opensaml_req_ss',)

# Tickers to search — same universe as Jefferies
_SEARCH_TICKERS = sorted(get_primary_tickers() | get_watchlist_tickers())

# Some tickers need full company name for autocomplete to return results
_WF_TICKER_SEARCH_NAMES = {
    'META': 'Meta Platforms, Inc',
    'BABA': 'Alibaba Group',
    '700.HK': 'Tencent Holdings',
    'NET': 'Cloudflare, Inc.',
}


class WellsFargoScraper(BaseScraper):
    """Scraper for Wells Fargo Research — BlueMatrix portal, Advanced Search by ticker."""

    PORTAL_NAME = "wells_fargo"
    PDF_STORAGE_DIR = "data/reports/wells_fargo"
    CONTENT_URL = _DEFAULT_PORTAL_URL

    def __init__(self, headless: bool = True):
        super().__init__(headless=headless)
        self.email = os.getenv('WF_EMAIL')
        base = os.getenv('WF_PORTAL_URL', _DEFAULT_PORTAL_URL)
        # Strip query string — adv_search needs a clean base
        self.CONTENT_URL = base.split('?')[0].rstrip('/')
        self.LOGIN_URL = self.CONTENT_URL

    # ------------------------------------------------------------------
    # Cookie helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_junk_cookie(name: str) -> bool:
        return any(name.startswith(p) for p in _JUNK_COOKIE_PREFIXES)

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

        # Seed saved cookies, then navigate to verify session
        domain = self.CONTENT_URL.replace('https://', '').replace('http://', '').split('/')[0]
        self.driver.get(self.CONTENT_URL)
        time.sleep(3)

        cookies = self.cookie_manager.get_cookies(self.PORTAL_NAME)
        if cookies:
            loaded = 0
            for name, value in cookies.items():
                if self._is_junk_cookie(name):
                    continue
                for cookie_domain in [domain, '.' + domain]:
                    try:
                        self.driver.add_cookie({
                            'name': name, 'value': value,
                            'domain': cookie_domain, 'path': '/',
                        })
                        loaded += 1
                        break
                    except Exception:
                        pass
            print(f"[{self.PORTAL_NAME}] Loaded {loaded} cookies — refreshing...")
            self.driver.get(self.CONTENT_URL)
            time.sleep(5)

        if self._check_authentication():
            print(f"[{self.PORTAL_NAME}] ✓ Authenticated via cookies")
            return True

        if self.email:
            return self._perform_login()

        print(f"[{self.PORTAL_NAME}] ✗ No auth — set WF_EMAIL in .env")
        return False

    def _perform_login(self) -> bool:
        """Red Login button → email → blue Verify → navigate to portal."""
        try:
            print(f"[{self.PORTAL_NAME}] Attempting login via email verification...")
            self.driver.get(self.LOGIN_URL)
            time.sleep(5)

            # Click red Login button
            clicked = self.driver.execute_script("""
                var texts = ['login', 'log in', 'sign in'];
                var all = document.querySelectorAll('button, a, [role="button"], input[type="submit"]');
                for (var i = 0; i < all.length; i++) {
                    var t = (all[i].textContent || all[i].value || '').trim().toLowerCase();
                    if (texts.indexOf(t) >= 0) {
                        var r = all[i].getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) { all[i].click(); return true; }
                    }
                }
                return false;
            """)
            if not clicked:
                print(f"[{self.PORTAL_NAME}] ✗ Could not find Login button")
                return False
            time.sleep(4)

            # Enter email
            for sel in ['input[type="email"]', 'input[type="text"]', 'input[name="email"]',
                        'input[placeholder*="email" i]']:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    if el.is_displayed():
                        el.clear()
                        el.send_keys(self.email)
                        print(f"[{self.PORTAL_NAME}]   Entered email: {self.email}")
                        break
                else:
                    continue
                break

            # Click blue Verify button
            self.driver.execute_script("""
                var texts = ['verify', 'continue', 'submit', 'next'];
                var all = document.querySelectorAll('button, a, [role="button"], input[type="submit"]');
                for (var i = 0; i < all.length; i++) {
                    var t = (all[i].textContent || all[i].value || '').trim().toLowerCase();
                    if (texts.indexOf(t) >= 0) {
                        var r = all[i].getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) { all[i].click(); return true; }
                    }
                }
            """)
            time.sleep(6)

            self.driver.get(self.CONTENT_URL)
            time.sleep(5)

            if self._check_authentication():
                print(f"[{self.PORTAL_NAME}] ✓ Login successful")
                self._persist_cookies()
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Login did not authenticate")
            self.driver.save_screenshot('/tmp/wf_login_fail.png')
            self._write_auth_alert('Email verification did not complete. Device may need re-verification.')
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Login error: {e}")
            return False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _check_authentication(self) -> bool:
        try:
            page_source = self.driver.page_source.lower()
            page_title = self.driver.title.lower()
            current_url = self.driver.current_url.lower()

            if any(x in page_title for x in ['login', 'sign in', 'verify']):
                return False
            if 'login' in current_url or 'signin' in current_url:
                return False

            auth_signals = ['logout', 'sign out', 'my feed', 'notifications',
                            'followed', 'research', 'publications', 'settings']
            return any(s in page_source for s in auth_signals)
        except Exception:
            return False

    def _is_session_valid(self) -> bool:
        """WF routes through sso.bluematrix.com — don't flag 'sso' in URL."""
        try:
            url = self.driver.current_url.lower()
            title = self.driver.title.lower()
            if 'sign in' in title or 'login' in title:
                return False
            if 'login' in url or 'authenticate' in url:
                return False
            return True
        except Exception:
            return False

    def _write_auth_alert(self, reason: str = ''):
        try:
            os.makedirs('data/alerts', exist_ok=True)
            path = f'data/alerts/auth_required_{self.PORTAL_NAME}.txt'
            with open(path, 'w') as f:
                f.write(f'{self.PORTAL_NAME} requires re-authentication\n')
                f.write(f'Timestamp: {datetime.now().isoformat()}\n')
                if reason:
                    f.write(f'Reason: {reason}\n')
                f.write('Action: Update cookies from research.wellsfargosecurities.com DevTools\n')
            print(f"[{self.PORTAL_NAME}] ⚠ Auth alert written: {path}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # BaseScraper abstract stubs (replaced by get_followed_reports override)
    # ------------------------------------------------------------------

    def _navigate_to_notifications(self) -> bool:
        return False

    def _extract_notifications(self) -> List[Dict]:
        return []

    # ------------------------------------------------------------------
    # Advanced Search — step 1: open and expand filters
    # ------------------------------------------------------------------

    def _navigate_to_adv_search(self) -> bool:
        """
        WF BlueMatrix portal hides Advanced Search behind an overflow arrow in the top nav tabs.
        Workflow:
          1. Start at home page
          2. Click the grey ">" overflow arrow at the right end of the top banner tabs
             (this reveals hidden tab options including "Advanced Search")
          3. Click "Advanced Search" from the revealed dropdown
          4. Wait for filter panel, click 'Expand All Filters'
        """
        try:
            # Ensure we're on the home page
            if '/adv_search' not in self.driver.current_url:
                self.driver.get(self.CONTENT_URL)
                time.sleep(4)

            # Step 1: Click the grey overflow/next arrow in the top nav banner
            clicked_arrow = self.driver.execute_script("""
                // Grey arrow is typically a v-btn or button with a mdi-chevron-right icon
                // positioned at the right side of the tab bar (top 80px, x > 600)
                var candidates = document.querySelectorAll(
                    'button, [role="button"], .v-btn, .v-tab__slider, .v-slide-group__next'
                );
                for (var i = 0; i < candidates.length; i++) {
                    var el = candidates[i];
                    var r = el.getBoundingClientRect();
                    // Must be in top banner area and right side of screen
                    if (r.top < 100 && r.left > 600 && r.width > 0 && r.height > 0) {
                        var cls = (el.className || '').toLowerCase();
                        var inner = el.innerHTML.toLowerCase();
                        // Matches: chevron icon, "next", arrow classes, or small icon-only buttons
                        if (cls.includes('next') || cls.includes('chevron') || cls.includes('arrow') ||
                            inner.includes('chevron') || inner.includes('arrow') || inner.includes('mdi-chevron') ||
                            (r.width < 50 && r.height < 50)) {
                            el.click();
                            return el.className || 'clicked';
                        }
                    }
                }
                return null;
            """)

            if clicked_arrow:
                print(f"[{self.PORTAL_NAME}]   Clicked overflow arrow ({str(clicked_arrow)[:40]})")
                time.sleep(1.5)
            else:
                print(f"[{self.PORTAL_NAME}]   ⚠ No overflow arrow found — trying direct nav")

            # Step 2: Find and click "Advanced Search" tab/option
            adv_clicked = self.driver.execute_script("""
                var all = document.querySelectorAll('a, button, [role="tab"], [role="option"], .v-list-item');
                for (var i = 0; i < all.length; i++) {
                    var t = (all[i].textContent || '').trim().toLowerCase();
                    if (t === 'advanced search' || t === 'adv search' || t === 'advanced') {
                        var r = all[i].getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            all[i].click();
                            return all[i].textContent.trim();
                        }
                    }
                }
                return null;
            """)

            if adv_clicked:
                print(f"[{self.PORTAL_NAME}] ✓ Clicked '{adv_clicked}'")
                time.sleep(3)
            else:
                # Fallback: direct URL navigation (WF uses /advanced_search)
                print(f"[{self.PORTAL_NAME}]   Falling back to direct /advanced_search URL")
                self.driver.get(f"{self.CONTENT_URL}/advanced_search")
                time.sleep(4)

            print(f"[{self.PORTAL_NAME}] ✓ On Adv Search: {self.driver.current_url}")

            # Step 3: Click 'Expand All Filters' to reveal the ticker autocomplete
            for _ in range(10):
                time.sleep(1)
                for el in self.driver.find_elements(By.CSS_SELECTOR,
                        'a, button, span, [role="button"]'):
                    try:
                        if 'expand all' in (el.text or '').lower() and el.is_displayed():
                            self.driver.execute_script("arguments[0].click();", el)
                            time.sleep(1.5)
                            print(f"[{self.PORTAL_NAME}] ✓ Clicked 'Expand All Filters'")
                            return True
                    except Exception:
                        continue

            print(f"[{self.PORTAL_NAME}] ⚠ 'Expand All Filters' not found — proceeding anyway")
            return True

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Adv Search navigation error: {e}")
            return False

    # ------------------------------------------------------------------
    # Advanced Search — step 2: add tickers (identical to Jefferies)
    # ------------------------------------------------------------------

    def _find_ticker_input(self):
        """
        Find the ticker autocomplete input. Called once before the ticker loop.
        After each chip selection the input stays active — reuse the same element.
        """
        _TICKER_ANCHOR = "//div[contains(@class,'filter-panel-title') and normalize-space()='Ticker']"
        try:
            el = self.driver.find_element(
                By.XPATH, f'{_TICKER_ANCHOR}/following::input[1]')
            if el:
                return el
        except Exception:
            pass
        for sel in ['input[placeholder*="Name or Ticker"]', 'input[placeholder*="Ticker"]',
                    'input[aria-autocomplete]']:
            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                try:
                    if el.is_displayed():
                        return el
                except Exception:
                    pass
        return None

    def _add_ticker_to_filter(self, ticker: str, ticker_input=None) -> bool:
        """
        Type ticker into the already-found autocomplete input and click the exact match.
        After selecting a chip the input stays focused — caller reuses the same element.
        Vuetify 3 options appear in .v-overlay__content.
        """
        try:
            if not ticker_input:
                print(f"[{self.PORTAL_NAME}]   ✗ No ticker input — skipping {ticker}")
                return False

            search_term = _WF_TICKER_SEARCH_NAMES.get(ticker, ticker)
            use_full_name = search_term != ticker

            ticker_input.clear()
            ticker_input.send_keys(search_term)
            time.sleep(2)

            # Options appear in Vuetify 3 teleported overlay
            opts = self.driver.find_elements(By.CSS_SELECTOR,
                '.v-overlay__content [role="option"], '
                '.v-overlay__content .v-list-item, '
                '[role="listbox"] [role="option"], '
                '[role="option"]')

            for el in opts:
                try:
                    text = (el.text or '').strip()
                    if not text:
                        continue
                    if use_full_name:
                        self.driver.execute_script("arguments[0].click();", el)
                        time.sleep(0.5)
                        print(f"[{self.PORTAL_NAME}]   ✓ Added: {ticker} ({search_term})")
                        return True
                    else:
                        lines = [l.strip().upper() for l in text.split('\n')]
                        if ticker.upper() in lines:
                            self.driver.execute_script("arguments[0].click();", el)
                            time.sleep(0.5)
                            print(f"[{self.PORTAL_NAME}]   ✓ Added: {ticker}")
                            return True
                except Exception:
                    continue

            if opts:
                visible = [o.text.strip()[:30] for o in opts if o.text.strip()][:3]
                print(f"[{self.PORTAL_NAME}]   ⚠ No match for {ticker} — options: {visible}")
            else:
                print(f"[{self.PORTAL_NAME}]   ⚠ No autocomplete options for: {ticker}")
            try:
                ticker_input.clear()
            except Exception:
                pass
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}]   ✗ Ticker filter error for {ticker}: {e}")
            return False

    # ------------------------------------------------------------------
    # Advanced Search — step 3: submit
    # ------------------------------------------------------------------

    def _run_search(self) -> bool:
        try:
            for el in self.driver.find_elements(By.CSS_SELECTOR, 'button, input[type="submit"]'):
                try:
                    if (el.text or '').strip().lower() == 'search':
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block:'nearest'});", el)
                        time.sleep(0.3)
                        self.driver.execute_script("arguments[0].click();", el)
                        print(f"[{self.PORTAL_NAME}] ✓ Search submitted — waiting for results...")
                        time.sleep(5)
                        return True
                except Exception:
                    continue

            print(f"[{self.PORTAL_NAME}] ✗ Search button not found")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Search error: {e}")
            return False

    # ------------------------------------------------------------------
    # Advanced Search — step 4: parse results (identical to Jefferies)
    # ------------------------------------------------------------------

    def _extract_search_results(self) -> List[Dict]:
        """BeautifulSoup on page_source — find all /report/{uuid} links."""
        results = []
        seen_urls = set()

        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
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

                # Card text: "Analyst  Date  Company  Title  Read X min"
                # link.text wraps the whole card — parse out the meaningful parts
                card_text = link.get_text(' ', strip=True)

                parent = link.find_parent(['div', 'li', 'article', 'tr'])
                parent_text = parent.get_text(' ', strip=True) if parent else card_text

                pub_date = self._parse_date(card_text)
                date_str = pub_date.strftime('%Y-%m-%d') if pub_date else None
                analyst = self._parse_analyst(card_text)

                # Title = everything after the date stamp, minus trailing "Read X min"
                title = card_text
                if pub_date:
                    date_pat = re.search(
                        r'(?:January|February|March|April|May|June|July|August|September|'
                        r'October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|'
                        r'Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}', card_text, re.I)
                    if date_pat:
                        title = card_text[date_pat.end():].strip()
                # Strip trailing "Read X min" / "Read > X min"
                title = re.sub(r'\s*Read\s*>?\s*\d+\s*min.*$', '', title, flags=re.I).strip()

                results.append({
                    'title': title[:200],
                    'url': href,
                    'analyst': analyst,
                    'source': 'Wells Fargo',
                    'date': date_str,
                })

            print(f"[{self.PORTAL_NAME}] Found {len(results)} reports in search results")
            return results

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Error parsing results: {e}")
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
            for sel in ['.report-content', '.document-content', '.article-content',
                        'article', 'main', '[role="main"]', '.v-main']:
                content = soup.select_one(sel)
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
        """Same BlueMatrix platform as Jefferies — look for links2 PDF URLs."""
        try:
            # Check iframes for embedded PDF (BlueMatrix links2 pattern)
            for iframe in self.driver.find_elements(By.TAG_NAME, 'iframe'):
                src = iframe.get_attribute('src') or ''
                if 'links2' in src.lower() and 'html' in src.lower():
                    return src.replace('/doc/html/', '/doc/pdf/')

            # Scan page source for links2 PDF URLs
            links2_urls = re.findall(r'(https?://[^\s"\']*links2/doc/[^\s"\']*)', self.driver.page_source)
            for url in links2_urls:
                return url.replace('/doc/html/', '/doc/pdf/')

            # Generic PDF link selectors
            for sel in ['a[href*=".pdf"]', '[aria-label*="PDF"]', '[title*="PDF"]']:
                for el in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    href = el.get_attribute('href') or ''
                    if '.pdf' in href.lower():
                        return href

            return None
        except Exception:
            return None

    def _sync_cookies_from_driver(self):
        if not self.driver:
            return
        for cookie in self.driver.get_cookies():
            self.session.cookies.set(cookie['name'], cookie['value'],
                                     domain=cookie.get('domain', ''))

    # ------------------------------------------------------------------
    # Text parsing helpers
    # ------------------------------------------------------------------

    def _parse_date(self, text: str) -> Optional[datetime]:
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

    def _parse_analyst(self, text: str) -> Optional[str]:
        for pattern in [
            # WF card format: "Analyst Name  Date  Company..." — name at start before month
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)',
            r'by\s+([A-Z][a-z]+\s+[A-Z][a-z]+)',
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s*[-–]',
            r'Author:\s*([A-Z][a-z]+\s+[A-Z][a-z]+)',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        return None

    # ------------------------------------------------------------------
    # Main orchestration (mirrors jefferies_scraper.get_followed_reports)
    # ------------------------------------------------------------------

    def get_followed_reports(self, max_reports: int = 25, days: int = 2,
                             result_out: Dict = None) -> Dict:
        """
        Full pipeline: Adv Search → ticker filter → extract content.
        Mirrors jefferies_scraper.get_followed_reports() exactly.
        """
        failures = []
        processed = []

        print(f"\n{'='*50}")
        print(f"[{self.PORTAL_NAME}] Fetching reports via Advanced Search")
        print(f"[{self.PORTAL_NAME}] Tickers: {', '.join(_SEARCH_TICKERS)}")
        print(f"{'='*50}")

        try:
            if not self._init_driver():
                self._write_auth_alert()
                return {'reports': [], 'failures': ['Authentication required'], 'auth_required': True}

            self.driver.get(self.CONTENT_URL)
            time.sleep(3)

            # Step 1: Open Advanced Search
            if not self._navigate_to_adv_search():
                failures.append("Could not open Advanced Search")
                return {'reports': [], 'failures': failures}

            # Step 2: Find the ticker input once, then add all tickers reusing it
            ticker_input = self._find_ticker_input()
            if not ticker_input:
                failures.append("Could not find ticker autocomplete input")
                return {'reports': [], 'failures': failures}

            added = 0
            for ticker in _SEARCH_TICKERS:
                if self._add_ticker_to_filter(ticker, ticker_input=ticker_input):
                    added += 1
            print(f"[{self.PORTAL_NAME}] Added {added}/{len(_SEARCH_TICKERS)} tickers")

            # Step 3: Submit search
            if not self._run_search():
                failures.append("Could not submit search")
                return {'reports': [], 'failures': failures}

            # Step 4: Parse results
            report_metas = self._extract_search_results()
            if not report_metas:
                print(f"[{self.PORTAL_NAME}] No reports found for tracked tickers today")
                return {'reports': [], 'failures': failures}

            # Dedup
            new_reports = self.report_tracker.filter_unprocessed(report_metas)
            skipped = len(report_metas) - len(new_reports)
            if skipped:
                print(f"[{self.PORTAL_NAME}] Skipped {skipped} already-processed reports")
            print(f"[{self.PORTAL_NAME}] → {len(new_reports)} new reports to process")

            if not new_reports:
                return {'reports': [], 'failures': failures}

            self._sync_cookies_from_driver()
            cutoff = date.today() - timedelta(days=days - 1)

            # Step 5: Extract content
            for i, report in enumerate(new_reports[:max_reports], 1):
                if not self._is_browser_alive():
                    failures.append("Browser crashed")
                    break

                if not self._is_session_valid():
                    print(f"[{self.PORTAL_NAME}] ✗ Session expired mid-run")
                    self._write_auth_alert()
                    failures.append("Session expired")
                    break

                # Date gate — results sorted newest-first
                report_date_str = report.get('date')
                if report_date_str:
                    try:
                        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
                        if report_date < cutoff:
                            print(f"[{self.PORTAL_NAME}] ✓ Reached reports older than {days}d — stopping")
                            break
                    except Exception:
                        pass

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

if __name__ == '__main__':
    import sys

    print('\nWells Fargo Research Scraper Test (Advanced Search)')
    print('=' * 50)

    portal_url = os.getenv('WF_PORTAL_URL', _DEFAULT_PORTAL_URL)
    email = os.getenv('WF_EMAIL')
    print(f'Portal URL: {portal_url}')
    print(f'Email: {email}')
    print(f'Tickers ({len(_SEARCH_TICKERS)}): {", ".join(_SEARCH_TICKERS)}')

    print('\n[1/2] Junk cookie filter check...')
    s = WellsFargoScraper(headless=True)
    assert s._is_junk_cookie('_opensaml_req_ss%3Amem%3A123')
    assert not s._is_junk_cookie('SESSION')
    assert not s._is_junk_cookie('_shibsession_abc')
    print('✓ Junk cookie filter works')

    print('\n[2/2] Running full pipeline (headless=False)...')
    scraper = WellsFargoScraper(headless=False)
    result = scraper.get_followed_reports(max_reports=5, days=2)

    if result.get('auth_required'):
        print('\n⚠ Authentication required — check WF_EMAIL or update cookies')
        sys.exit(1)

    reports = result.get('reports', [])
    failures = result.get('failures', [])

    print(f'\n--- Results ---')
    print(f'Reports extracted: {len(reports)}')
    print(f'Failures: {len(failures)}')

    for i, r in enumerate(reports[:3], 1):
        print(f'\n  [{i}] {r["title"][:70]}')
        print(f'      Analyst: {r.get("analyst", "unknown")}')
        print(f'      Date:    {r.get("date", "unknown")}')
        print(f'      Content: {len(r.get("content", ""))} chars')

    if failures:
        print('\n--- Failures ---')
        for f in failures[:5]:
            print(f'  - {f}')

    print('\n✓ Wells Fargo Advanced Search scraper test complete')
