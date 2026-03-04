"""
UBS Neo Research Portal Scraper

Workflow:
1. Selenium login: email → Next → password → Next (no 2FA, no cookies needed)
2. driver.get("https://neo.ubs.com/feed/all") → All Follows feed
3. Parse article cards from DOM: title, date, analyst, href (actual article URL)
4. filter_by_date: today + tomorrow PST (Chinese-timezone analysts publish "tomorrow" PST)
5. For each article: driver.get(href) → scroll → click "Access document" → PDF tab → extract

Pure Selenium after login — no requests session needed for content.
"""

import os
import time
from datetime import datetime
from typing import List, Dict, Optional

from base_scraper import BaseScraper, is_model_document
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium import webdriver
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

_FEED_URL = "https://neo.ubs.com/feed/all"


class UBSScraper(BaseScraper):
    """Scraper for UBS Neo — API-based follows feed, Selenium for login + content"""

    PORTAL_NAME    = "ubs"
    CONTENT_URL    = "https://neo.ubs.com/home"
    PDF_STORAGE_DIR = "data/reports/ubs"

    def __init__(self, headless: bool = True):
        super().__init__(headless=headless)
        self.email    = os.getenv('UBS_EMAIL')
        self.password = os.getenv('UBS_PASSWORD')
        self._fetched_articles: List[Dict] = []

    # ------------------------------------------------------------------
    # Cookie persistence: no-op (fresh login each run, no 2FA)
    # ------------------------------------------------------------------

    def _persist_cookies(self):
        pass

    # ------------------------------------------------------------------
    # Browser init + login
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

        self.driver.get(self.CONTENT_URL)
        time.sleep(5)

        if self.email and self.password:
            return self._perform_login()

        print(f"[{self.PORTAL_NAME}] ✗ No credentials available")
        return False

    def _perform_login(self) -> bool:
        """2-step login: email → Next → password → Next"""
        try:
            print(f"[{self.PORTAL_NAME}] Attempting login...")
            time.sleep(3)

            # Step 1: email field
            email_field = None
            for selector in ['#email_input', 'input[type="text"]', 'input[type="email"]']:
                for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    if el.is_displayed():
                        email_field = el
                        break
                if email_field:
                    break

            if not email_field:
                print(f"[{self.PORTAL_NAME}] ✗ Email field not found")
                return False

            email_field.clear()
            email_field.send_keys(self.email)
            print(f"[{self.PORTAL_NAME}]   Entered email")
            time.sleep(1)
            self._click_ubs_next()
            time.sleep(4)

            # Step 2: password field (appears after Next)
            password_field = None
            for _ in range(4):
                for selector in ['input[name="password_input"]', 'input[type="password"]']:
                    for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
                        if el.is_displayed():
                            password_field = el
                            break
                    if password_field:
                        break
                if password_field:
                    break
                time.sleep(2)

            if not password_field:
                print(f"[{self.PORTAL_NAME}] ✗ Password field not found")
                return False

            password_field.clear()
            password_field.send_keys(self.password)
            print(f"[{self.PORTAL_NAME}]   Entered password")
            time.sleep(1)
            self._click_ubs_next()
            time.sleep(6)

            self.driver.get(self.CONTENT_URL)
            time.sleep(5)

            if self._check_authentication():
                print(f"[{self.PORTAL_NAME}] ✓ Login successful")
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Login failed — URL: {self.driver.current_url[:80]}")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Login error: {e}")
            return False

    def _click_ubs_next(self) -> bool:
        """Click the visible 'Next' button (JS click — UBS uses type=button, not submit)"""
        try:
            for btn in self.driver.find_elements(By.XPATH, "//button[normalize-space(text())='Next']"):
                if btn.is_displayed():
                    self.driver.execute_script("arguments[0].click();", btn)
                    print(f"[{self.PORTAL_NAME}]   Clicked Next")
                    return True
        except Exception as e:
            print(f"[{self.PORTAL_NAME}]   Next click error: {e}")
        return False

    # ------------------------------------------------------------------
    # Authentication check
    # ------------------------------------------------------------------

    def _check_authentication(self) -> bool:
        try:
            url = self.driver.current_url.lower()
            if any(x in url for x in ['login', 'signin', 'sign-in', 'sso', 'saml', 'oauth', 'authenticate', 'microsoftonline']):
                return False
            if any(x in self.driver.title.lower() for x in ['sign in', 'login']):
                return False
            page = self.driver.page_source.lower()
            if any(x in page for x in ['research', 'logout', 'sign out', 'neo', 'analyst', 'equity', 'coverage']):
                print(f"[{self.PORTAL_NAME}] ✓ Auth check: valid session")
                return True
            if 'neo.ubs.com' in url and 'login' not in url:
                print(f"[{self.PORTAL_NAME}] ✓ Auth check: on portal")
                return True
            return False
        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Auth check error: {e}")
            return False

    def close_driver(self):
        """Close WebDriver — no cookie persistence (fresh login each run)."""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            print(f"[{self.PORTAL_NAME}] Closed WebDriver")

    def _restart_browser(self) -> bool:
        print(f"[{self.PORTAL_NAME}] Restarting browser...")
        self.close_driver()
        time.sleep(6)
        if not self._init_driver():
            print(f"[{self.PORTAL_NAME}] ✗ Re-authentication failed after restart")
            self._write_auth_alert()
            return False
        print(f"[{self.PORTAL_NAME}] ✓ Browser restarted")
        return True

    # ------------------------------------------------------------------
    # Feed scraping: pure Selenium, no API calls
    # ------------------------------------------------------------------

    def _navigate_to_notifications(self) -> bool:
        """Navigate to All Follows feed and scrape article list from DOM."""
        print(f"[{self.PORTAL_NAME}] Navigating to All Follows feed...")
        try:
            self.driver.get(_FEED_URL)
            time.sleep(15)  # React SPA: wait for feed cards to render
        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Feed navigation/load error: {e}")
            return False

        self._fetched_articles = self._scrape_feed_articles()
        print(f"[{self.PORTAL_NAME}] ✓ Feed scraped: {len(self._fetched_articles)} articles found")
        return True

    def _scrape_feed_articles(self) -> List[Dict]:
        """
        Feed card structure (from page source inspection):
          - Article links have href matching /research/ or /article/ patterns
          - Title is the <a> text itself
          - Date and analyst are in sibling/parent container elements

        Uses BeautifulSoup on page_source (more reliable than Selenium find_elements
        for React SPAs where is_displayed() can be inconsistent).
        """
        import re
        from dateutil import parser as dateparser
        from bs4 import BeautifulSoup

        DATE_RE = re.compile(
            r'\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*'
            r'\s+20\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*'
            r'\s+\d{1,2},?\s+20\d{2})\b', re.I
        )

        articles = []
        seen_hrefs = set()

        soup = BeautifulSoup(self.driver.page_source, 'html.parser')

        all_links = soup.find_all('a', href=True)

        # Article URLs on UBS Neo: /feed/all/article/research/{id}
        # Skip: company filter pages (/articles?), author profiles (/profile/),
        #        nav links (/feed/discover, /feed/stream, /feed/all exact)
        ARTICLE_PATTERNS = ['/article/research/']
        SKIP_PATTERNS = ['/feed/discover', '/feed/stream', '/feed/all/stream',
                         '/articles?', '/profile/', '/home', '/login', '/settings',
                         '#', 'javascript:']

        for a_tag in all_links:
            try:
                href = a_tag.get('href', '')
                if not href:
                    continue

                # Build absolute URL
                if href.startswith('http'):
                    url = href
                elif href.startswith('/'):
                    url = 'https://neo.ubs.com' + href
                else:
                    continue

                if url in seen_hrefs:
                    continue
                if any(p in href for p in SKIP_PATTERNS):
                    continue
                if not any(p in href for p in ARTICLE_PATTERNS):
                    continue

                title = a_tag.get_text(strip=True)
                if not title or len(title) < 5:
                    continue

                # Skip financial model spreadsheets — not narrative research
                if is_model_document(title):
                    continue

                # Walk up to find card container with date + analyst
                parent = a_tag.find_parent(['div', 'li', 'article', 'section'])
                container_text = parent.get_text(separator='\n', strip=True) if parent else ''

                # Extract date from container
                pub_date = None
                date_m = DATE_RE.search(container_text)
                if date_m:
                    try:
                        pub_date = dateparser.parse(date_m.group(1), fuzzy=True)
                    except Exception:
                        pass

                # Extract analyst: line after the date line in container text
                analyst = ''
                if date_m:
                    lines = [l.strip() for l in container_text.split('\n') if l.strip()]
                    for idx, line in enumerate(lines):
                        if DATE_RE.search(line):
                            if idx + 1 < len(lines):
                                candidate = lines[idx + 1]
                                # Analyst name: not a date, not a region, not "Research..."
                                if (not DATE_RE.search(candidate)
                                        and 'Research' not in candidate
                                        and len(candidate.split()) <= 4):
                                    analyst = candidate
                            break

                seen_hrefs.add(url)
                articles.append({
                    'title':   title[:200],
                    'url':     url,
                    'date':    pub_date.strftime('%Y-%m-%d') if pub_date else None,
                    'analyst': analyst,
                    'source':  'UBS',
                })
            except Exception:
                continue

        if articles:
            print(f"[{self.PORTAL_NAME}]   Found {len(articles)} articles: "
                  f"{[a['title'][:50] for a in articles[:5]]}")
        else:
            try:
                body_text = self.driver.find_element(By.TAG_NAME, 'body').text
                import re as _re
                m = _re.search(r'20\d{2}', body_text)
                if m:
                    idx = m.start()
                    snippet = body_text[max(0, idx-60):idx+100]
                else:
                    snippet = body_text[:400]
                print(f"[{self.PORTAL_NAME}] ⚠ No articles found after URL pattern filter.")
                print(f"  Page snippet: {repr(snippet)}")
            except Exception:
                pass

        return articles

    def _extract_notifications(self) -> List[Dict]:
        return self._fetched_articles

    # ------------------------------------------------------------------
    # Date filter override: today + tomorrow PST (not yesterday)
    # ------------------------------------------------------------------

    def filter_by_date(self, reports: List[Dict], days: int = 2) -> List[Dict]:
        """
        Keep reports dated today or later in PST.
        'days' param ignored — UBS uses today-midnight PST as cutoff so that
        Chinese-timezone analyst reports dated 'tomorrow' PST are included.
        """
        # today midnight in local time (system is PST)
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        recent = []
        for report in reports:
            if not report.get('date'):
                recent.append(report)
                continue
            try:
                report_date = datetime.strptime(report['date'], '%Y-%m-%d')
                if report_date >= cutoff:
                    recent.append(report)
            except Exception:
                recent.append(report)
        print(f"  Date filter: {len(recent)} of {len(reports)} reports from today+ (PST)")
        return recent

    # ------------------------------------------------------------------
    # Content extraction: Selenium navigate → click "Access document" → PDF
    # ------------------------------------------------------------------

    def _navigate_to_report(self, report_url: str) -> bool:
        """Navigate to the article page (URL comes from feed DOM — always correct)."""
        if not report_url:
            return False
        try:
            self.driver.get(report_url)
            time.sleep(8)  # React SPA render time
            return True
        except Exception as e:
            print(f"    ✗ Navigation error: {e}")
            return False

    def _click_access_document(self) -> Optional[str]:
        """
        Click the 'Access document' button on the article page.
        The button opens the PDF in a new tab; captures and returns the PDF URL.
        """
        try:
            # Scroll down a bit to reveal the "Access document" button
            self.driver.execute_script("window.scrollBy(0, 400);")
            time.sleep(1)

            btn = None
            for text in ['Access document', 'Access Document', 'Download PDF', 'View PDF']:
                candidates = self.driver.find_elements(
                    By.XPATH,
                    f"//button[contains(., '{text}')] | //a[contains(., '{text}')]"
                )
                for el in candidates:
                    if el.is_displayed():
                        btn = el
                        break
                if btn:
                    break

            if not btn:
                # Debug: print visible buttons and links to find the right text
                all_btns = self.driver.find_elements(By.XPATH, "//button | //a")
                visible_texts = [el.text.strip() for el in all_btns if el.is_displayed() and el.text.strip()][:20]
                print(f"    ⚠ 'Access document' button not found. Visible buttons/links: {visible_texts}")
                return None

            original_handles = set(self.driver.window_handles)
            self.driver.execute_script("arguments[0].click();", btn)
            print(f"    → Clicked 'Access document'")
            time.sleep(4)

            # Check for new tab
            new_handles = set(self.driver.window_handles) - original_handles
            if new_handles:
                new_tab = new_handles.pop()
                self.driver.switch_to.window(new_tab)
                pdf_url = self.driver.current_url
                self.driver.close()
                self.driver.switch_to.window(list(original_handles)[0])
                print(f"    ✓ PDF tab: {pdf_url[:70]}...")
                return pdf_url

            # Check if PDF embedded in iframe/object on current page
            for iframe in self.driver.find_elements(By.TAG_NAME, 'iframe'):
                src = iframe.get_attribute('src') or ''
                if '.pdf' in src.lower() or 'download' in src.lower():
                    return src

            # Check if current URL itself is the PDF
            current = self.driver.current_url
            if '.pdf' in current.lower():
                return current

            return None

        except Exception as e:
            print(f"    ✗ Access document error: {e}")
            return None

    def _extract_report_content(self, report: Dict = None) -> Optional[str]:
        """Navigate to article → click 'Access document' → download and parse PDF."""
        pdf_url = self._click_access_document()
        if pdf_url:
            self._sync_cookies_from_driver()
            pdf_bytes = self.download_pdf(pdf_url)
            if pdf_bytes:
                if report:
                    pdf_path = self._save_pdf(pdf_bytes, report)
                    if pdf_path:
                        report['pdf_path'] = pdf_path
                text = self.extract_text_from_pdf(pdf_bytes)
                if text and len(text) > 200:
                    return text
        return None


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("\nUBS Neo Scraper Test")
    print("=" * 50)

    email    = os.getenv('UBS_EMAIL')
    password = os.getenv('UBS_PASSWORD')

    if not email or not password:
        print("✗ Missing UBS_EMAIL or UBS_PASSWORD in .env")
        sys.exit(1)

    print(f"✓ Credentials: {email}")

    print("\n[1/2] Initializing scraper (headless=False for debugging)...")
    scraper = UBSScraper(headless=False)

    print("\n[2/2] Running full pipeline...")
    result = scraper.get_followed_reports(max_reports=20, days=2)

    if result.get('auth_required'):
        print("\n⚠ Authentication required — check credentials")
        sys.exit(1)

    reports  = result.get('reports', [])
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

    print("\n✓ UBS scraper test complete")
