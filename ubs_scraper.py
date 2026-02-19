"""
UBS Neo Research Portal Scraper

Workflow:
1. Login with email/password (no 2FA, no cookies needed)
2. For each ticker: type company name in top nav shadow DOM search bar → Enter
3. Land on company page (/feed/stream/company/{RIC}/latest/company-research)
4. Extract article links (/article/research/{ID}), filter to today only (±1 day for timezone)
5. For each report: navigate to article URL → find PDF link → download

Inherits from BaseScraper for shared auth/PDF functionality.
"""

import os
import re
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from base_scraper import BaseScraper
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium import webdriver
from dateutil import parser as dateparser
import config

load_dotenv()

# Ticker → company name mapping for UBS search
# UBS search bar expects company names, not just ticker symbols
TICKER_COMPANY_NAMES = {
    'META': 'Meta Platforms',
    'GOOGL': 'Alphabet',
    'AMZN': 'Amazon',
    'AAPL': 'Apple',
    'BABA': 'Alibaba',
    '700.HK': 'Tencent',
    'MSFT': 'Microsoft',
    'CRWD': 'CrowdStrike',
    'ZS': 'Zscaler',
    'PANW': 'Palo Alto Networks',
    'NET': 'Cloudflare',
    'DDOG': 'Datadog',
    'SNOW': 'Snowflake',
    'MDB': 'MongoDB',
    'NFLX': 'Netflix',
    'SPOT': 'Spotify',
    'U': 'Unity Software',
    'APP': 'AppLovin',
    'RBLX': 'Roblox',
    'ORCL': 'Oracle',
    'PLTR': 'Palantir',
    'SHOP': 'Shopify',
}


class UBSScraper(BaseScraper):
    """Scraper for UBS Neo research portal — ticker-by-ticker search"""

    PORTAL_NAME = "ubs"
    CONTENT_URL = "https://neo.ubs.com/home"
    PDF_STORAGE_DIR = "data/reports/ubs"

    def __init__(self, headless: bool = True):
        super().__init__(headless=headless)
        self.email = os.getenv('UBS_EMAIL')
        self.password = os.getenv('UBS_PASSWORD')

    # ------------------------------------------------------------------
    # Browser setup with login
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

        # No cookies — always log in fresh (no 2FA on UBS Neo)
        self.driver.get(self.CONTENT_URL)
        time.sleep(5)

        if self.email and self.password:
            return self._perform_login()

        print(f"[{self.PORTAL_NAME}] ✗ No credentials available")
        return False

    def _perform_login(self) -> bool:
        """Login with UBS Neo 2-step flow: email → Next → password → Next"""
        try:
            print(f"[{self.PORTAL_NAME}] Attempting login...")
            print(f"[{self.PORTAL_NAME}]   Current URL: {self.driver.current_url[:80]}")
            time.sleep(3)

            # Step 1: Enter email — UBS uses id="email_input"
            email_field = None
            for selector in ['#email_input', 'input[type="text"]', 'input[type="email"]']:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if el.is_displayed():
                        email_field = el
                        break
                if email_field:
                    break

            if not email_field:
                print(f"[{self.PORTAL_NAME}] ✗ Could not find email field")
                return False

            email_field.clear()
            email_field.send_keys(self.email)
            print(f"[{self.PORTAL_NAME}]   Entered email")
            time.sleep(1)

            # Step 2: Click "Next" button — UBS uses type=button so Enter key doesn't work
            self._click_ubs_next()
            time.sleep(4)

            # Step 3: Enter password — name="password_input" becomes visible after Next
            password_field = None
            for attempt in range(4):
                for selector in ['input[name="password_input"]', 'input[type="password"]']:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        if el.is_displayed():
                            password_field = el
                            break
                    if password_field:
                        break
                if password_field:
                    break
                time.sleep(2)

            if not password_field:
                print(f"[{self.PORTAL_NAME}] ✗ Could not find password field after Next")
                return False

            password_field.clear()
            password_field.send_keys(self.password)
            print(f"[{self.PORTAL_NAME}]   Entered password")
            time.sleep(1)

            # Step 4: Click "Next" again to submit password
            self._click_ubs_next()
            time.sleep(6)

            self.driver.get(self.CONTENT_URL)
            time.sleep(5)

            if self._check_authentication():
                print(f"[{self.PORTAL_NAME}] ✓ Login successful")
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Login failed")
            print(f"[{self.PORTAL_NAME}]   Final URL: {self.driver.current_url[:80]}")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Login error: {e}")
            return False

    def _click_ubs_next(self) -> bool:
        """Click the visible 'Next' button on UBS login (exact text match, JS click)"""
        try:
            btns = self.driver.find_elements(By.XPATH, "//button[normalize-space(text())='Next']")
            for btn in btns:
                if btn.is_displayed():
                    self.driver.execute_script("arguments[0].click();", btn)
                    print(f"[{self.PORTAL_NAME}]   Clicked Next")
                    return True
        except Exception as e:
            print(f"[{self.PORTAL_NAME}]   Next click error: {e}")
        return False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _check_authentication(self) -> bool:
        try:
            current_url = self.driver.current_url.lower()
            page_source = self.driver.page_source.lower()

            # Negative: login redirects
            login_indicators = [
                'login', 'signin', 'sign-in', 'sso', 'saml',
                'oauth', 'authenticate', 'microsoftonline'
            ]
            for indicator in login_indicators:
                if indicator in current_url:
                    return False

            if 'sign in' in self.driver.title.lower() or 'login' in self.driver.title.lower():
                return False

            # Positive: UBS Neo content
            auth_indicators = [
                'research', 'logout', 'sign out', 'neo',
                'analyst', 'equity', 'coverage', 'search'
            ]
            for indicator in auth_indicators:
                if indicator in page_source:
                    print(f"[{self.PORTAL_NAME}] ✓ Auth check: valid session")
                    return True

            if 'neo.ubs.com' in current_url and 'login' not in current_url:
                print(f"[{self.PORTAL_NAME}] ✓ Auth check: on portal")
                return True

            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Auth check error: {e}")
            return False

    def close_driver(self):
        """Close WebDriver without saving cookies (UBS re-authenticates fresh each run)."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            print(f"[{self.PORTAL_NAME}] Closed WebDriver")

    def _restart_browser(self) -> bool:
        """Override to allow extra time for Chrome to fully release resources before relaunching."""
        print(f"[{self.PORTAL_NAME}] Restarting browser (batch boundary)...")
        self.close_driver()
        time.sleep(6)  # UBS SPA leaves heavy Chrome processes — wait for full OS cleanup
        if not self._init_driver():
            print(f"[{self.PORTAL_NAME}] ✗ Re-authentication failed after restart")
            self._write_auth_alert()
            return False
        print(f"[{self.PORTAL_NAME}] ✓ Browser restarted successfully")
        return True

    # ------------------------------------------------------------------
    # Navigate — no-op (ticker search happens in extract)
    # ------------------------------------------------------------------

    def _navigate_to_notifications(self) -> bool:
        """No-op — UBS uses ticker-by-ticker search instead of a feed"""
        print(f"[{self.PORTAL_NAME}] ✓ Using ticker search approach")
        return True

    # ------------------------------------------------------------------
    # Extract reports by searching each ticker
    # ------------------------------------------------------------------

    def _extract_notifications(self) -> List[Dict]:
        """Search each coverage ticker and extract analyst articles"""
        from analyst_config_tmt import PRIMARY_TICKERS, WATCHLIST_TICKERS
        all_reports = []
        seen_urls = set()

        # All covered tickers: primary + watchlist, deduplicated, sorted for consistency
        tickers_to_search = sorted(PRIMARY_TICKERS | WATCHLIST_TICKERS)

        print(f"[{self.PORTAL_NAME}] Searching {len(tickers_to_search)} tickers...")

        for i, ticker in enumerate(tickers_to_search, start=1):
            company_name = TICKER_COMPANY_NAMES.get(ticker, ticker)

            # Crash detection — restart if Chrome died mid-run
            if not self._is_browser_alive():
                print(f"[{self.PORTAL_NAME}] Browser crashed — restarting before {ticker}...")
                if not self._restart_browser():
                    print(f"[{self.PORTAL_NAME}] ✗ Re-auth failed after crash — stopping")
                    break

            print(f"[{self.PORTAL_NAME}]   [{i}/{len(tickers_to_search)}] Searching: {ticker} ({company_name})")

            reports = self._search_ticker(ticker, company_name, seen_urls)
            all_reports.extend(reports)

            if reports:
                print(f"[{self.PORTAL_NAME}]     → {len(reports)} new articles")

        print(f"[{self.PORTAL_NAME}] ✓ Total: {len(all_reports)} reports across {len(tickers_to_search)} tickers")
        return all_reports

    def _get_shadow_search_input(self):
        """Find the search input inside the FC-MASTHEAD-SEARCH shadow DOM component"""
        return self.driver.execute_script("""
            function findInputInShadow(root) {
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) {
                        const inp = el.shadowRoot.querySelector('input');
                        if (inp) return inp;
                        const nested = findInputInShadow(el.shadowRoot);
                        if (nested) return nested;
                    }
                }
                return null;
            }
            return findInputInShadow(document);
        """)

    def _search_ticker(self, ticker: str, company_name: str, seen_urls: set) -> List[Dict]:
        """Type company name in top nav search bar → land on company page → extract articles"""
        reports = []
        # Only collect articles published today (±1 day for timezone differences)
        cutoff = datetime.now() - timedelta(days=2)

        try:
            # Reuse the nav search bar from whatever page we're on — avoids a full home page load
            # Only fall back to home if we've somehow left the portal entirely
            if 'neo.ubs.com' not in self.driver.current_url:
                self.driver.get(self.CONTENT_URL)
                time.sleep(4)

            search_input = self._get_shadow_search_input()
            if not search_input:
                print(f"[{self.PORTAL_NAME}]     ✗ Could not find nav search input")
                return []

            self.driver.execute_script("arguments[0].click();", search_input)
            time.sleep(0.5)
            # Clear any leftover text from the previous search, then type new company name
            self.driver.execute_script("arguments[0].value = '';", search_input)
            search_input.send_keys(company_name)
            time.sleep(2)
            search_input.send_keys(Keys.RETURN)
            time.sleep(5)

            # If search landed on results page instead of company page, click first company result
            if '/feed/stream/company/' not in self.driver.current_url:
                if '/search?' in self.driver.current_url:
                    company_links = self.driver.find_elements(
                        By.XPATH, "//a[contains(@href, '/feed/stream/company/')]"
                    )
                    if company_links:
                        self.driver.execute_script("arguments[0].click();", company_links[0])
                        time.sleep(4)
                    else:
                        print(f"[{self.PORTAL_NAME}]     ✗ No company results for {ticker}")
                        return []
                if '/feed/stream/company/' not in self.driver.current_url:
                    print(f"[{self.PORTAL_NAME}]     ✗ Did not land on company page: {self.driver.current_url[:80]}")
                    return []

            # Scroll to load articles
            self.driver.execute_script("window.scrollTo(0, 800);")
            time.sleep(2)

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            article_re = re.compile(r'/article/research/\w+$')
            seen_ids = set()

            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                if not article_re.search(href):
                    continue

                article_id = href.split('/')[-1]
                if article_id in seen_ids:
                    continue
                seen_ids.add(article_id)

                full_url = 'https://neo.ubs.com' + href if not href.startswith('http') else href
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                title = link.get_text(strip=True)
                if not title or len(title) < 5:
                    continue

                parent = link.find_parent(['div', 'li', 'article', 'section'])
                analyst = self._extract_analyst_name(parent)
                pub_date = self._extract_date(parent)

                # Date filter: only today's articles (±1 day for timezone)
                if pub_date and pub_date < cutoff:
                    continue

                reports.append({
                    'title': title[:200],
                    'url': full_url,
                    'analyst': analyst,
                    'source': 'UBS',
                    'date': pub_date.strftime('%Y-%m-%d') if pub_date else None,
                    'ticker': ticker,
                })

        except Exception as e:
            print(f"[{self.PORTAL_NAME}]     Error searching {ticker}: {e}")

        return reports

    def _extract_analyst_name(self, element) -> Optional[str]:
        if not element:
            return None
        text = element.get_text(separator=' ')
        patterns = [
            r'by\s+([A-Z][a-z]+\s+[A-Z][a-z]+)',
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s+Research\s*[-–]',  # UBS: "Karl Keirstead Research -"
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s*[-–]',
            r'Author:\s*([A-Z][a-z]+\s+[A-Z][a-z]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def _extract_date(self, element) -> Optional[datetime]:
        if not element:
            return None
        text = element.get_text()
        date_patterns = [
            r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})',
            r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})',
            r'(\d{1,2}/\d{1,2}/\d{4})',
            r'(\d{4}-\d{2}-\d{2})',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text, re.I)
            if match:
                try:
                    return dateparser.parse(match.group(1))
                except:
                    pass
        return None

    # ------------------------------------------------------------------
    # Report navigation and content extraction
    # ------------------------------------------------------------------

    def _navigate_to_report(self, report_url: str) -> bool:
        try:
            self.driver.get(report_url)
            time.sleep(5)
            return True
        except Exception as e:
            print(f"    ✗ Error navigating to report: {e}")
            return False

    def _extract_report_content(self, report: Dict = None) -> Optional[str]:
        # Try PDF first
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

        # Fallback: page text
        text = self._extract_text_from_page()
        if text and len(text) > 500:
            return text

        return None

    def _get_pdf_url(self) -> Optional[str]:
        try:
            pdf_selectors = [
                'a[href*=".pdf"]',
                '[aria-label*="PDF"]',
                '[aria-label*="Download"]',
                '[title*="PDF"]',
                'button[class*="pdf"]',
                'a[class*="pdf"]',
                'a[class*="download"]',
            ]

            for selector in pdf_selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if el.is_displayed():
                        href = el.get_attribute('href')
                        if href and '.pdf' in href.lower():
                            print(f"    ✓ Found PDF link: {href[:60]}...")
                            return href
                        self.driver.execute_script("arguments[0].click();", el)
                        time.sleep(2)

            # Search page source
            pdf_urls = re.findall(
                r'(https?://[^\s"\']*\.pdf[^\s"\']*)', self.driver.page_source)
            if pdf_urls:
                print(f"    ✓ Found PDF URL in source: {pdf_urls[0][:60]}...")
                return pdf_urls[0]

            # Check iframes
            iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
            for iframe in iframes:
                src = iframe.get_attribute('src') or ''
                if '.pdf' in src.lower():
                    return src

            return None
        except Exception as e:
            print(f"    ⚠ Error getting PDF URL: {e}")
            return None

    def _extract_text_from_page(self) -> Optional[str]:
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            for element in soup(['script', 'style', 'nav', 'header', 'footer']):
                element.decompose()

            content_selectors = [
                '.report-content', '.article-content', '.document-content',
                '.research-content', 'article', 'main', '[role="main"]',
            ]
            for selector in content_selectors:
                content = soup.select_one(selector)
                if content:
                    text = content.get_text(separator='\n', strip=True)
                    if len(text) > 500:
                        return text

            body = soup.find('body')
            if body:
                lines = [l for l in body.get_text(separator='\n', strip=True).split('\n') if len(l) > 50]
                if lines:
                    return '\n'.join(lines)

            return None
        except Exception as e:
            print(f"    ⚠ Error extracting page text: {e}")
            return None


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("\nUBS Neo Scraper Test")
    print("=" * 50)

    email = os.getenv('UBS_EMAIL')
    password = os.getenv('UBS_PASSWORD')

    if not email or not password:
        print("✗ Missing UBS_EMAIL or UBS_PASSWORD in .env file")
        sys.exit(1)

    print(f"✓ Found credentials for: {email}")

    from analyst_config_tmt import PRIMARY_TICKERS, WATCHLIST_TICKERS
    all_tickers = sorted(PRIMARY_TICKERS | WATCHLIST_TICKERS)
    print(f"✓ Will search {len(all_tickers)} tickers: {', '.join(all_tickers)}")

    print("\n[1/2] Initializing scraper...")
    scraper = UBSScraper(headless=False)

    print("\n[2/2] Running full pipeline...")
    result = scraper.get_followed_reports(max_reports=30, days=2)

    if result.get('auth_required'):
        print("\n⚠ Authentication required - check credentials")
        sys.exit(1)

    reports = result.get('reports', [])
    failures = result.get('failures', [])

    print(f"\n--- Results ---")
    print(f"Reports extracted: {len(reports)}")
    print(f"Failures: {len(failures)}")

    # Group by ticker
    by_ticker = {}
    for r in reports:
        t = r.get('ticker', 'unknown')
        by_ticker.setdefault(t, []).append(r)

    for t, reps in by_ticker.items():
        print(f"\n  {t}: {len(reps)} articles")
        for r in reps[:2]:
            print(f"    - {r['title'][:60]}")

    if failures:
        print(f"\n--- Failures ---")
        for f in failures[:5]:
            print(f"  - {f}")

    print("\n✓ UBS scraper test complete")
