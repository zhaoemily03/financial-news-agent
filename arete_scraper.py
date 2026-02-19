"""
Arete Research Portal Scraper

Workflow:
1. Login with cookies or username/password
2. Navigate to home page
3. Scrape "My Research" articles from home page
4. For each report: navigate, extract content (text or PDF)
5. Filter: last N days only, skip previously processed

Note: Arete uses a username (di.wu), not an email address.

Inherits from BaseScraper for shared cookie/auth/PDF functionality.
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
from selenium import webdriver
from dateutil import parser as dateparser

load_dotenv()


class AreteScraper(BaseScraper):
    """Scraper for Arete research portal — My Research from home page"""

    PORTAL_NAME = "arete"
    CONTENT_URL = "https://portal.arete.net/"
    PDF_STORAGE_DIR = "data/reports/arete"

    def __init__(self, headless: bool = True):
        super().__init__(headless=headless)
        self.username = os.getenv('ARETE_USERNAME')
        self.password = os.getenv('ARETE_PASSWORD')

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
        print(f"[{self.PORTAL_NAME}] Initialized Chrome WebDriver")

        # No cookies — always log in fresh (no 2FA on Arete)
        self.driver.get(self.CONTENT_URL)
        time.sleep(3)

        if self.username and self.password:
            return self._perform_login()

        print(f"[{self.PORTAL_NAME}] ✗ No authentication method available")
        return False

    def _perform_login(self) -> bool:
        """Login with username and password — 2-step flow (username → Next → password)"""
        try:
            print(f"[{self.PORTAL_NAME}] Attempting login...")
            current_url = self.driver.current_url
            print(f"[{self.PORTAL_NAME}]   Current URL: {current_url[:80]}")
            time.sleep(3)

            # Step 1: Find and fill username field
            username_selectors = [
                'input[type="text"]', 'input[type="email"]',
                'input[name="username"]', 'input[name="user"]',
                'input[name="email"]', 'input[name="login"]',
                'input[id="username"]', 'input[id="user"]',
                'input[placeholder*="user" i]', 'input[placeholder*="email" i]',
                'input:not([type="hidden"]):not([type="password"])',
            ]
            username_field = None
            for selector in username_selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if el.is_displayed():
                        username_field = el
                        break
                if username_field:
                    break

            if not username_field:
                all_inputs = self.driver.find_elements(By.TAG_NAME, 'input')
                print(f"[{self.PORTAL_NAME}]   DEBUG: {len(all_inputs)} inputs:")
                for inp in all_inputs:
                    print(f"    type={inp.get_attribute('type')} name={inp.get_attribute('name')} visible={inp.is_displayed()}")
                print(f"[{self.PORTAL_NAME}] ✗ Could not find username field")
                return False

            username_field.clear()
            username_field.send_keys(self.username)
            print(f"[{self.PORTAL_NAME}]   Entered username")
            time.sleep(1)

            # Step 2: Click "Next"
            next_selectors = [
                'input[type="submit"]', 'button[type="submit"]',
                'button[class*="next"]', 'button[class*="login"]',
                'button[class*="submit"]', 'button[class*="continue"]',
                '.btn-primary', 'button',
            ]
            clicked_next = False
            for selector in next_selectors:
                buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for btn in buttons:
                    if btn.is_displayed():
                        text = (btn.text or '').lower()
                        btn_type = (btn.get_attribute('type') or '').lower()
                        if btn_type == 'submit' or any(w in text for w in ['next', 'continue', 'log', 'sign', 'submit']):
                            btn.click()
                            clicked_next = True
                            print(f"[{self.PORTAL_NAME}]   Clicked Next/Submit")
                            time.sleep(3)
                            break
                if clicked_next:
                    break
            if not clicked_next:
                from selenium.webdriver.common.keys import Keys
                username_field.send_keys(Keys.RETURN)
                time.sleep(3)

            # Step 3: Find and fill password field (with retry)
            password_field = None
            for attempt in range(3):
                for selector in ['input[type="password"]', 'input[name="password"]', 'input[name="passwd"]']:
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
                print(f"[{self.PORTAL_NAME}] ✗ Could not find password field")
                return False

            password_field.clear()
            password_field.send_keys(self.password)
            print(f"[{self.PORTAL_NAME}]   Entered password")
            time.sleep(1)

            # Step 4: Click sign in
            clicked_submit = False
            for selector in next_selectors:
                buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for btn in buttons:
                    if btn.is_displayed():
                        text = (btn.text or '').lower()
                        btn_type = (btn.get_attribute('type') or '').lower()
                        if btn_type == 'submit' or any(w in text for w in ['sign', 'log', 'submit', 'continue']):
                            btn.click()
                            clicked_submit = True
                            print(f"[{self.PORTAL_NAME}]   Clicked Sign In")
                            time.sleep(5)
                            break
                if clicked_submit:
                    break
            if not clicked_submit:
                from selenium.webdriver.common.keys import Keys
                password_field.send_keys(Keys.RETURN)
                time.sleep(5)

            # Handle "Stay signed in?" prompt
            try:
                for btn in self.driver.find_elements(By.CSS_SELECTOR, '#idBtn_Back, #idSIButton9'):
                    if btn.is_displayed():
                        btn.click()
                        time.sleep(2)
                        break
            except:
                pass

            if self._check_authentication():
                print(f"[{self.PORTAL_NAME}] ✓ Login successful")
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Login failed")
            print(f"[{self.PORTAL_NAME}]   Final URL: {self.driver.current_url[:80]}")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Login error: {e}")
            return False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _check_authentication(self) -> bool:
        try:
            current_url = self.driver.current_url.lower()
            page_source = self.driver.page_source.lower()

            # Negative: login page
            login_indicators = ['login', 'signin', 'sign-in', 'authenticate']
            for indicator in login_indicators:
                if indicator in current_url:
                    return False

            # Check for visible login form
            password_fields = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')
            visible_password = [f for f in password_fields if f.is_displayed()]
            if visible_password:
                return False

            # Positive: research content
            auth_indicators = [
                'my research', 'my ressearch',  # Note: typo in spreadsheet, check both
                'logout', 'sign out', 'research', 'report',
                'analyst', 'coverage', 'dashboard'
            ]
            for indicator in auth_indicators:
                if indicator in page_source:
                    print(f"[{self.PORTAL_NAME}] ✓ Auth check: valid session")
                    return True

            if 'portal.arete.net' in current_url and 'login' not in current_url:
                print(f"[{self.PORTAL_NAME}] ✓ Auth check: on portal")
                return True

            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Auth check error: {e}")
            return False

    # ------------------------------------------------------------------
    # Navigate to My Research (home page)
    # ------------------------------------------------------------------

    def _navigate_to_notifications(self) -> bool:
        """My Research is on the home page — find and focus that section"""
        try:
            time.sleep(3)

            # Check if we're already on the home page with My Research visible
            page_source = self.driver.page_source.lower()
            if 'my research' in page_source or 'my ressearch' in page_source:
                print(f"[{self.PORTAL_NAME}] ✓ My Research section visible on home page")
                return True

            # Try clicking "My Research" link/tab if it exists
            all_clickable = self.driver.find_elements(
                By.CSS_SELECTOR, 'a, button, [role="tab"], li, span, div[class*="tab"]')
            for el in all_clickable:
                try:
                    text = (el.text or '').strip().lower()
                    if 'my research' in text or 'my ressearch' in text:
                        if el.is_displayed():
                            self.driver.execute_script("arguments[0].click();", el)
                            print(f"[{self.PORTAL_NAME}] ✓ Clicked My Research")
                            time.sleep(3)
                            return True
                except:
                    continue

            # Navigate to home page explicitly
            self.driver.get(self.CONTENT_URL)
            time.sleep(3)

            page_source = self.driver.page_source.lower()
            if 'research' in page_source or 'report' in page_source:
                print(f"[{self.PORTAL_NAME}] ✓ On home page with research content")
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Could not find My Research section")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Error navigating to My Research: {e}")
            return False

    # ------------------------------------------------------------------
    # Extract research articles
    # ------------------------------------------------------------------

    def _extract_notifications(self) -> List[Dict]:
        notifications = []
        seen_urls = set()

        try:
            for scroll_idx in range(5):
                time.sleep(2)
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')

                # Find article/report links
                all_links = soup.find_all('a', href=True)
                for link in all_links:
                    href = link.get('href', '')

                    # Filter for research-type links
                    if not any(x in href.lower() for x in [
                        '/research/', '/report/', '/article/', '/document/',
                        '/view/', '/note/', '/insight/'
                    ]):
                        # Also accept links that are clearly not navigation
                        if href.startswith('#') or href == '/' or '/login' in href:
                            continue
                        # Check if the link text suggests a report title
                        title_text = link.get_text(strip=True)
                        if not title_text or len(title_text) < 10:
                            continue
                        # Skip obvious nav links
                        if title_text.lower() in ['home', 'about', 'contact', 'login', 'logout', 'my research']:
                            continue

                    if not href.startswith('http'):
                        href = 'https://portal.arete.net' + href

                    if href in seen_urls:
                        continue
                    seen_urls.add(href)

                    title = link.get_text(strip=True)
                    if not title or len(title) < 5:
                        title = link.get('title', 'Untitled')
                    if not title or len(title) < 5:
                        continue

                    parent = link.find_parent(['div', 'li', 'article', 'tr', 'section'])
                    analyst = self._extract_analyst_name(parent)
                    pub_date = self._extract_date(parent)

                    notifications.append({
                        'title': title[:200],
                        'url': href,
                        'analyst': analyst,
                        'source': 'Arete',
                        'date': pub_date.strftime('%Y-%m-%d') if pub_date else None,
                    })

                # Scroll for more
                self.driver.execute_script("window.scrollBy(0, 600)")

            print(f"[{self.PORTAL_NAME}] ✓ Found {len(notifications)} articles")
            return notifications

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Error extracting articles: {e}")
            return []

    def _extract_analyst_name(self, element) -> Optional[str]:
        if not element:
            return None
        text = element.get_text()
        patterns = [
            r'by\s+([A-Z][a-z]+\s+[A-Z][a-z]+)',
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
        # Try page text first (Arete may render content inline)
        text = self._extract_text_from_page()
        if text and len(text) > 500:
            print(f"    ✓ Extracted {len(text)} chars from page")
            return text

        # Try PDF
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

    def _get_pdf_url(self) -> Optional[str]:
        try:
            pdf_selectors = [
                'a[href*=".pdf"]',
                '[aria-label*="PDF"]',
                '[title*="PDF"]',
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
                '.research-content', '.note-content', '.insight-content',
                'article', 'main', '[role="main"]',
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

    print("\nArete Research Scraper Test")
    print("=" * 50)

    username = os.getenv('ARETE_USERNAME')
    password = os.getenv('ARETE_PASSWORD')

    if not username or not password:
        print("✗ Missing ARETE_USERNAME or ARETE_PASSWORD in .env file")
        sys.exit(1)

    print(f"✓ Found credentials for: {username}")

    print("\n[1/2] Initializing scraper...")
    scraper = AreteScraper(headless=False)

    print("\n[2/2] Testing full pipeline...")
    result = scraper.get_followed_reports(max_reports=10, days=7)

    if result.get('auth_required'):
        print("\n⚠ Authentication required - check credentials")
        sys.exit(1)

    reports = result.get('reports', [])
    failures = result.get('failures', [])

    print(f"\n--- Results ---")
    print(f"Reports extracted: {len(reports)}")
    print(f"Failures: {len(failures)}")

    for i, report in enumerate(reports[:3], 1):
        print(f"\n  Report {i}:")
        print(f"    Title: {report['title'][:60]}")
        print(f"    Analyst: {report.get('analyst', 'unknown')}")
        print(f"    Date: {report.get('date', 'unknown')}")

    if failures:
        print(f"\n--- Failures ---")
        for f in failures[:5]:
            print(f"  - {f}")

    print("\n✓ Arete scraper test complete")
