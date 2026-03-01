"""
Arete Research Portal Scraper

Workflow:
1. Login with username/password (no 2FA — no cookie storage needed)
2. Navigate to home page
3. Scrape "My Ressearch" articles from home page
4. For each article: extract direct PDF URL from the red Adobe icon next to the title
5. Download PDF, extract text
6. Filter: last N days only, skip previously processed

Inherits from BaseScraper for shared PDF/auth functionality.
"""

import os
import re
import time
from datetime import datetime
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from base_scraper import BaseScraper
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium import webdriver
from dateutil import parser as dateparser

load_dotenv()


class AreteScraper(BaseScraper):
    """Scraper for Arete research portal — My Ressearch section on home page"""

    PORTAL_NAME = "arete"
    CONTENT_URL = "https://portal.arete.net/"
    PDF_STORAGE_DIR = "data/reports/arete"

    def __init__(self, headless: bool = True):
        super().__init__(headless=headless)
        self.username = os.getenv('ARETE_USERNAME')
        self.password = os.getenv('ARETE_PASSWORD')

    # ------------------------------------------------------------------
    # Cookie persistence: no-op (Arete logs in fresh each run, no 2FA)
    # ------------------------------------------------------------------

    def _persist_cookies(self):
        pass  # Fresh login every run — no cookie storage needed

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

        self.driver.get(self.CONTENT_URL)
        time.sleep(3)

        if self.username and self.password:
            return self._perform_login()

        print(f"[{self.PORTAL_NAME}] ✗ No credentials available")
        return False

    def _perform_login(self) -> bool:
        """Login: username and password are on the same page — fill both then Sign In"""
        try:
            print(f"[{self.PORTAL_NAME}] Attempting login...")

            # Step 1: Fill username
            username_field = self._find_visible_input([
                'input[type="text"]', 'input[type="email"]',
                'input[name="username"]', 'input[name="user"]',
                'input[name="email"]', 'input[id="username"]',
                'input[placeholder*="user" i]', 'input[placeholder*="email" i]',
            ])
            if not username_field:
                print(f"[{self.PORTAL_NAME}] ✗ Username field not found")
                return False

            username_field.clear()
            username_field.send_keys(self.username)
            time.sleep(0.5)

            # Step 2: Fill password (both fields visible on same page)
            password_field = self._find_visible_input([
                'input[type="password"]', 'input[name="password"]', 'input[name="passwd"]',
            ])
            if not password_field:
                print(f"[{self.PORTAL_NAME}] ✗ Password field not found")
                return False

            password_field.clear()
            password_field.send_keys(self.password)
            time.sleep(0.5)

            # Step 3: Click Sign In
            if not self._click_submit_button(['sign', 'log', 'submit']):
                password_field.send_keys(Keys.RETURN)
            time.sleep(5)

            if self._check_authentication():
                print(f"[{self.PORTAL_NAME}] ✓ Login successful")
                # PDFs redirect through research.arete.net — establish a session there first
                print(f"[{self.PORTAL_NAME}] Establishing session on research.arete.net...")
                self.driver.get('https://research.arete.net/')
                time.sleep(5)  # Let the session fully initialize before first PDF request
                self.driver.get(self.CONTENT_URL)
                time.sleep(2)
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Login failed — URL: {self.driver.current_url[:80]}")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Login error: {e}")
            return False

    def _find_visible_input(self, selectors: List[str]):
        """Return the first visible input matching any of the given CSS selectors."""
        for selector in selectors:
            for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
                if el.is_displayed():
                    return el
        return None

    def _click_submit_button(self, text_keywords: List[str]) -> bool:
        """Click the first visible submit/button matching any of the text keywords."""
        for selector in ['input[type="submit"]', 'button[type="submit"]', '.btn-primary', 'button']:
            for btn in self.driver.find_elements(By.CSS_SELECTOR, selector):
                if not btn.is_displayed():
                    continue
                txt = (btn.text or '').lower()
                btype = (btn.get_attribute('type') or '').lower()
                if btype == 'submit' or any(w in txt for w in text_keywords):
                    btn.click()
                    return True
        return False

    # ------------------------------------------------------------------
    # Authentication check
    # ------------------------------------------------------------------

    def _check_authentication(self) -> bool:
        try:
            url = self.driver.current_url.lower()
            if any(x in url for x in ['login', 'signin', 'sign-in', 'authenticate']):
                return False
            if any(f.is_displayed()
                   for f in self.driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')):
                return False

            page = self.driver.page_source.lower()
            if any(x in page for x in ['ressearch', 'my research', 'logout', 'sign out', 'research', 'report']):
                print(f"[{self.PORTAL_NAME}] ✓ Auth check: valid session")
                return True

            if 'portal.arete.net' in url and 'login' not in url:
                print(f"[{self.PORTAL_NAME}] ✓ Auth check: on portal")
                return True

            return False
        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Auth check error: {e}")
            return False

    # ------------------------------------------------------------------
    # Navigate to My Ressearch section on home page
    # ------------------------------------------------------------------

    def _navigate_to_notifications(self) -> bool:
        """Navigate to home page and confirm My Ressearch section is visible."""
        try:
            self.driver.get(self.CONTENT_URL)
            time.sleep(4)

            page = self.driver.page_source.lower()
            if 'ressearch' in page or 'my research' in page or 'your research' in page:
                print(f"[{self.PORTAL_NAME}] ✓ My Ressearch section visible")
                return True

            # Try scrolling to trigger lazy-load
            self.driver.execute_script("window.scrollTo(0, 500)")
            time.sleep(2)
            page = self.driver.page_source.lower()
            if 'research' in page or 'report' in page:
                print(f"[{self.PORTAL_NAME}] ✓ Research content found on home page")
                return True

            print(f"[{self.PORTAL_NAME}] ✗ My Ressearch section not found")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Navigation error: {e}")
            return False

    # ------------------------------------------------------------------
    # Extract articles + PDF links from My Ressearch section
    # ------------------------------------------------------------------

    def _extract_notifications(self) -> List[Dict]:
        """
        Find articles in the My Ressearch section on the home page.
        The article title link and the red Adobe icon both point to the same PDF URL,
        so we simply collect all <a href="*.pdf"> links with meaningful title text.
        """
        notifications = []
        seen_titles = set()

        # Scroll to load all content
        for i in range(5):
            self.driver.execute_script(f"window.scrollTo(0, {i * 800})")
            time.sleep(1.5)

        soup = BeautifulSoup(self.driver.page_source, 'html.parser')

        # Every article title is a direct .pdf link — collect them all
        for a in soup.find_all('a', href=lambda h: h and '.pdf' in h.lower()):
            title = a.get_text(strip=True)
            if len(title) < 10:
                continue  # Skip icon-only links (no meaningful text)
            if title in seen_titles:
                continue
            seen_titles.add(title)

            pdf_url = a.get('href', '')
            if not pdf_url.startswith('http'):
                pdf_url = 'https://portal.arete.net' + pdf_url

            parent = a.find_parent('tr') or a.find_parent(['li', 'article', 'div'])
            pub_date = self._extract_date(parent)
            analyst = self._extract_analyst_name(parent)

            notifications.append({
                'title': title[:200],
                'url': self.CONTENT_URL,   # Don't navigate away from home in base pipeline
                'pdf_link': pdf_url,       # Used directly in _extract_report_content
                'analyst': analyst,
                'source': 'Arete',
                'date': pub_date.strftime('%Y-%m-%d') if pub_date else None,
            })

        print(f"[{self.PORTAL_NAME}] ✓ Found {len(notifications)} articles")
        return notifications

    def _extract_analyst_name(self, element) -> Optional[str]:
        if not element:
            return None
        # Table row: cells[1] = "FirstName LastName" (two hidden sub-cells joined with space)
        if element.name == 'tr':
            cells = element.find_all('td')
            if len(cells) >= 2:
                parts = cells[1].get_text(separator=' ', strip=True).split()
                name = ' '.join(p for p in parts if p)
                if 3 <= len(name) <= 50:
                    return name
        # Fallback: person name pattern in element text
        text = element.get_text()
        match = re.search(r'([A-Z][a-z]+\s+[A-Z][a-z]+)', text)
        return match.group(1) if match else None

    def _extract_date(self, element) -> Optional[datetime]:
        if not element:
            return None
        # Table row: cells[2] = "ISO_TIMESTAMP|DD Mon YY" — prefer ISO (most reliable)
        if element.name == 'tr':
            cells = element.find_all('td')
            if len(cells) >= 3:
                date_text = cells[2].get_text(separator='|', strip=True)
                iso_match = re.search(r'(\d{4}-\d{2}-\d{2})T', date_text)
                if iso_match:
                    try:
                        return dateparser.parse(iso_match.group(1))
                    except Exception:
                        pass
                # Fallback: parse the display portion
                try:
                    return dateparser.parse(date_text.split('|')[0])
                except Exception:
                    pass
        # Last resort: scan text for date patterns
        text = element.get_text()
        for pattern in [
            r'(\d{4}-\d{2}-\d{2})',
            r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})',
        ]:
            match = re.search(pattern, text, re.I)
            if match:
                try:
                    return dateparser.parse(match.group(1))
                except Exception:
                    pass
        return None

    # ------------------------------------------------------------------
    # Report navigation and content extraction
    # ------------------------------------------------------------------

    def _navigate_to_report(self, report_url: str) -> bool:
        """No navigation needed — PDF URL is stored in report['pdf_link']."""
        return True

    def _extract_report_content(self, report: Dict = None) -> Optional[str]:
        """Download PDF using the direct URL stored in report['pdf_link']."""
        pdf_url = report.get('pdf_link') if report else None

        if not pdf_url:
            print(f"    ✗ No PDF found for: {(report or {}).get('title', '')[:50]}")
            return None

        print(f"    Downloading PDF: {pdf_url[:80]}")

        pdf_bytes = self._download_pdf_via_browser(pdf_url)
        if not pdf_bytes:
            return None

        if report:
            pdf_path = self._save_pdf(pdf_bytes, report)
            if pdf_path:
                report['pdf_path'] = pdf_path

        return self.extract_text_from_pdf(pdf_bytes) or None

    def _download_pdf_via_browser(self, pdf_url: str) -> Optional[bytes]:
        """
        Navigate to the portal PDF link → follow redirect through research.arete.net
        → land on CloudFront viewer → extract pre-signed S3 URL from viewer URL params
        → download directly from S3 (no auth needed for pre-signed URLs).
        """
        import requests as _requests
        from urllib.parse import urlparse, parse_qs, unquote

        # Navigate to portal PDF link — will redirect through research.arete.net
        # to the CloudFront viewer at d321bl9io865gk.cloudfront.net/view?s3Url=...
        try:
            self.driver.get(pdf_url)
            time.sleep(4)
        except Exception:
            time.sleep(2)

        current_url = self.driver.current_url
        print(f"    Redirected to: {current_url[:100]}")

        try:
            parsed = urlparse(current_url)
            params = parse_qs(parsed.query)

            # Primary: pre-signed S3 URL (no auth required)
            s3_encoded = params.get('s3Url', [None])[0]
            if s3_encoded:
                s3_url = unquote(s3_encoded)
                print(f"    Fetching from S3: {s3_url[:80]}")
                resp = _requests.get(s3_url, timeout=30)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    print(f"    Downloaded {len(resp.content)} bytes from S3")
                    self.driver.get(self.CONTENT_URL)
                    time.sleep(2)
                    return resp.content
                print(f"    ✗ S3 fetch failed: HTTP {resp.status_code}")

            # Fallback: watermarked src URL (auth token embedded in URL params)
            src_encoded = params.get('src', [None])[0]
            if src_encoded:
                src_url = unquote(src_encoded)
                print(f"    Trying watermarked src: {src_url[:80]}")
                resp = _requests.get(src_url, timeout=30)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    print(f"    Downloaded {len(resp.content)} bytes (watermarked)")
                    self.driver.get(self.CONTENT_URL)
                    time.sleep(2)
                    return resp.content
                print(f"    ✗ Watermarked src failed: HTTP {resp.status_code}")

        except Exception as e:
            print(f"    ✗ Download error: {e}")

        # Navigate back so _is_session_valid() sees the portal home next iteration
        try:
            self.driver.get(self.CONTENT_URL)
            time.sleep(2)
        except Exception:
            pass

        return None



# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("\nArete Research Scraper Test")
    print("=" * 50)

    username = os.getenv('ARETE_USERNAME')
    password = os.getenv('ARETE_PASSWORD')

    if not username or not password:
        print("✗ Missing ARETE_USERNAME or ARETE_PASSWORD in .env file")
        sys.exit(1)

    print(f"✓ Found credentials for: {username}")

    print("\n[1/2] Initializing scraper (headless=False for debugging)...")
    scraper = AreteScraper(headless=False)

    print("\n[2/2] Testing full pipeline...")
    result = scraper.get_followed_reports(max_reports=10, days=2)

    if result.get('auth_required'):
        print("\n⚠ Authentication required — check credentials")
        sys.exit(1)

    reports = result.get('reports', [])
    failures = result.get('failures', [])

    print(f"\n--- Results ---")
    print(f"Reports extracted: {len(reports)}")
    print(f"Failures: {len(failures)}")

    for i, report in enumerate(reports[:3], 1):
        print(f"\n  Report {i}:")
        print(f"    Title:   {report['title'][:70]}")
        print(f"    Analyst: {report.get('analyst', 'unknown')}")
        print(f"    Date:    {report.get('date', 'unknown')}")
        print(f"    PDF:     {report.get('pdf_path', 'not saved')}")
        print(f"    Content: {len(report.get('content', ''))} chars")

    if failures:
        print(f"\n--- Failures ---")
        for f in failures[:5]:
            print(f"  - {f}")

    print("\n✓ Arete scraper test complete")
