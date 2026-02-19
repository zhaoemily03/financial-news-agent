"""
Goldman Sachs Marquee Research Portal Scraper

Workflow:
1. Login with cookies or email/password
2. Navigate to "My Content" section
3. Extract research report links
4. For each report: navigate, extract content (text or PDF)
5. Filter: last N days only, skip previously processed

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


class GoldmanScraper(BaseScraper):
    """Scraper for Goldman Sachs Marquee research portal"""

    PORTAL_NAME = "goldman"
    CONTENT_URL = "https://marquee.gs.com/content/research/themes/homepage-default.html"
    PDF_STORAGE_DIR = "data/reports/goldman"

    def __init__(self, headless: bool = True):
        super().__init__(headless=headless)
        self.email = os.getenv('GS_EMAIL')
        self.password = os.getenv('GS_PASSWORD')

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

        # No cookies — always log in fresh (no 2FA on Goldman Marquee)
        self.driver.get(self.CONTENT_URL)
        time.sleep(5)

        if self.email and self.password:
            return self._perform_login()

        print(f"[{self.PORTAL_NAME}] ✗ No authentication method available")
        return False

    def _perform_login(self) -> bool:
        """Login with email and password — 2-step flow at portal URL"""
        try:
            print(f"[{self.PORTAL_NAME}] Attempting login...")

            # Login happens at the portal URL itself (redirects to login if unauthenticated)
            # Current page should already be showing the login form
            current_url = self.driver.current_url
            print(f"[{self.PORTAL_NAME}]   Current URL: {current_url[:80]}")
            time.sleep(3)

            # Step 1: Find and fill username/email field
            email_selectors = [
                'input[type="email"]',
                'input[type="text"]',
                'input[name="email"]',
                'input[name="username"]',
                'input[name="loginfmt"]',
                'input[id="username"]',
                'input[id="email"]',
                'input[id="i0116"]',
                'input[placeholder*="email" i]',
                'input[placeholder*="user" i]',
                'input[placeholder*="login" i]',
                'input:not([type="hidden"]):not([type="password"])',
            ]

            email_field = None
            for selector in email_selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if el.is_displayed():
                        email_field = el
                        break
                if email_field:
                    break

            if not email_field:
                # Debug: dump all visible inputs
                all_inputs = self.driver.find_elements(By.TAG_NAME, 'input')
                print(f"[{self.PORTAL_NAME}]   DEBUG: {len(all_inputs)} input elements found:")
                for inp in all_inputs:
                    print(f"[{self.PORTAL_NAME}]     type={inp.get_attribute('type')} name={inp.get_attribute('name')} id={inp.get_attribute('id')} visible={inp.is_displayed()}")
                print(f"[{self.PORTAL_NAME}] ✗ Could not find email/username field")
                return False

            email_field.clear()
            email_field.send_keys(self.email)
            print(f"[{self.PORTAL_NAME}]   Entered username")
            time.sleep(1)

            # Step 2: Click "Next" button
            next_selectors = [
                'input[type="submit"]', 'button[type="submit"]',
                '#idSIButton9',  # Microsoft login
                'button[class*="next"]', 'button[class*="login"]',
                'button[class*="submit"]', 'button[class*="continue"]',
                '.btn-primary', '.next-button',
                'button',  # Fallback: any button
            ]
            clicked_next = False
            for selector in next_selectors:
                buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for btn in buttons:
                    if btn.is_displayed():
                        text = (btn.text or '').lower()
                        btn_type = (btn.get_attribute('type') or '').lower()
                        # Click submit-type buttons or buttons with relevant text
                        if btn_type == 'submit' or any(w in text for w in ['next', 'continue', 'log', 'sign', 'submit']):
                            btn.click()
                            clicked_next = True
                            print(f"[{self.PORTAL_NAME}]   Clicked Next/Submit")
                            time.sleep(3)
                            break
                if clicked_next:
                    break

            if not clicked_next:
                # Try pressing Enter on the email field
                from selenium.webdriver.common.keys import Keys
                email_field.send_keys(Keys.RETURN)
                print(f"[{self.PORTAL_NAME}]   Pressed Enter")
                time.sleep(3)

            # Step 3: Find and fill password field
            password_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                'input[name="passwd"]',
                'input[id="i0118"]',
            ]

            password_field = None
            for attempt in range(3):  # Retry — password page may take time to load
                for selector in password_selectors:
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
                print(f"[{self.PORTAL_NAME}] ✗ Could not find password field after username step")
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
                password_field.send_keys(Keys.RETURN)
                time.sleep(5)

            # Handle "Stay signed in?" prompt if present
            try:
                stay_buttons = self.driver.find_elements(By.CSS_SELECTOR,
                    '#idBtn_Back, #idSIButton9')
                for btn in stay_buttons:
                    if btn.is_displayed():
                        btn.click()
                        time.sleep(2)
                        break
            except:
                pass

            # Navigate to research portal
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

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _check_authentication(self) -> bool:
        try:
            current_url = self.driver.current_url.lower()
            page_title = self.driver.title.lower()
            page_source = self.driver.page_source.lower()

            # Negative: login redirects
            login_indicators = [
                'login', 'signin', 'sign-in', 'sso', 'saml',
                'oauth', 'authenticate', 'welcome/login'
            ]
            for indicator in login_indicators:
                if indicator in current_url:
                    return False

            if 'sign in' in page_title or 'login' in page_title:
                return False

            # Positive: research portal content
            auth_indicators = [
                'my content', 'research', 'marquee', 'logout',
                'sign out', 'portfolio', 'saved', 'preferences'
            ]
            for indicator in auth_indicators:
                if indicator in page_source:
                    print(f"[{self.PORTAL_NAME}] ✓ Auth check: valid session")
                    return True

            if 'marquee.gs.com' in current_url and '/content/' in current_url:
                print(f"[{self.PORTAL_NAME}] ✓ Auth check: on research portal")
                return True

            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Auth check error: {e}")
            return False

    # ------------------------------------------------------------------
    # Navigate to "My Content"
    # ------------------------------------------------------------------

    def _navigate_to_notifications(self) -> bool:
        """Navigate to My Content > Following section on Marquee"""
        try:
            time.sleep(3)

            # Step 1: Click "My Content" nav link
            my_content_selectors = [
                'a[href*="my-content"]',
                'a[href*="mycontent"]',
                'a[href*="my_content"]',
                '[data-testid*="my-content"]',
            ]

            clicked = False
            for selector in my_content_selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if el.is_displayed():
                        self.driver.execute_script("arguments[0].click();", el)
                        print(f"[{self.PORTAL_NAME}] ✓ Clicked My Content (selector)")
                        clicked = True
                        time.sleep(3)
                        break
                if clicked:
                    break

            if not clicked:
                # Fallback: find by text content
                all_clickable = self.driver.find_elements(
                    By.CSS_SELECTOR, 'a, button, [role="button"], [role="tab"], li')
                for el in all_clickable:
                    try:
                        text = (el.text or '').strip().lower()
                        if 'my content' in text and el.is_displayed():
                            self.driver.execute_script("arguments[0].click();", el)
                            print(f"[{self.PORTAL_NAME}] ✓ Clicked My Content (text match)")
                            clicked = True
                            time.sleep(3)
                            break
                    except:
                        continue

            if not clicked:
                print(f"[{self.PORTAL_NAME}] ✗ Could not find My Content link")
                return False

            # Step 2: Click "Following" tab/banner within My Content
            time.sleep(2)
            all_clickable = self.driver.find_elements(
                By.CSS_SELECTOR, 'a, button, [role="tab"], span, div[class*="tab"]')
            for el in all_clickable:
                try:
                    text = (el.text or '').strip().lower()
                    if text == 'following' and el.is_displayed():
                        self.driver.execute_script("arguments[0].click();", el)
                        print(f"[{self.PORTAL_NAME}] ✓ Clicked Following tab")
                        time.sleep(3)
                        return True
                except:
                    continue

            # If no explicit "Following" tab, check if we're already there
            page_source = self.driver.page_source.lower()
            if 'following' in page_source:
                print(f"[{self.PORTAL_NAME}] ✓ On My Content page (Following visible)")
                return True

            print(f"[{self.PORTAL_NAME}] ✓ On My Content page")
            return True

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Error navigating to My Content: {e}")
            return False

    # ------------------------------------------------------------------
    # Extract reports from My Content
    # ------------------------------------------------------------------

    def _extract_notifications(self) -> List[Dict]:
        """Extract research reports from the My Content > Following section only"""
        notifications = []
        seen_urls = set()

        # Navigation/UI link patterns to skip
        nav_skip = [
            '/themes/', '/homepage', '/my-content', '/manage', '/events',
            '/settings', '/preferences', '/market-intelligence', '/insights',
            '/welcome', '/login', '/signin', 'cvent.com', 'goldmansachs.com/disclosures',
            '/webinar', '/reminder',
        ]

        try:
            for scroll_idx in range(5):
                time.sleep(2)
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')

                # Only look for links that point to actual research reports
                # GS Marquee report URLs contain /reports/ with a date path
                report_links = soup.find_all('a', href=lambda h: h and '/reports/' in h)

                for link in report_links:
                    href = link.get('href', '')

                    # Skip non-report links
                    if any(skip in href.lower() for skip in nav_skip):
                        continue

                    if not href.startswith('http'):
                        href = 'https://marquee.gs.com' + href

                    if href in seen_urls:
                        continue
                    seen_urls.add(href)

                    title = link.get_text(strip=True)
                    if not title or len(title) < 10:
                        title = link.get('title', '')
                    if not title or len(title) < 10:
                        continue

                    # Skip titles that are clearly nav elements
                    title_lower = title.lower()
                    if title_lower in ['events', 'my content', 'manage', 'following',
                                       'market intelligence', 'insights']:
                        continue

                    parent = link.find_parent(['div', 'li', 'article', 'section'])
                    analyst = self._extract_analyst_name(parent)
                    pub_date = self._extract_date(parent)

                    notifications.append({
                        'title': title[:200],
                        'url': href,
                        'analyst': analyst,
                        'source': 'Goldman Sachs',
                        'date': pub_date.strftime('%Y-%m-%d') if pub_date else None,
                    })

                # Scroll for more content in the Following section
                self.driver.execute_script("window.scrollBy(0, 800)")

            print(f"[{self.PORTAL_NAME}] ✓ Found {len(notifications)} reports in Following")
            return notifications

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Error extracting notifications: {e}")
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
        # Try page text first (GS often renders content inline)
        text = self._extract_text_from_page()
        if text and len(text) > 500:
            print(f"    ✓ Extracted {len(text)} chars from page")
            return text

        # Try PDF — sync all browser cookies to requests session
        pdf_url = self._get_pdf_url()
        if pdf_url:
            self._sync_cookies_from_driver()
            # Also copy any auth headers the browser may use
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
            # Look for PDF buttons/links
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
                        # Click to reveal PDF
                        self.driver.execute_script("arguments[0].click();", el)
                        time.sleep(2)

            # Search page source for PDF URLs
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
                    print(f"    ✓ Found PDF in iframe: {src[:60]}...")
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

    print("\nGoldman Sachs Marquee Scraper Test")
    print("=" * 50)

    email = os.getenv('GS_EMAIL')
    password = os.getenv('GS_PASSWORD')

    if not email or not password:
        print("✗ Missing GS_EMAIL or GS_PASSWORD in .env file")
        sys.exit(1)

    print(f"✓ Found credentials for: {email}")

    print("\n[1/2] Initializing scraper...")
    scraper = GoldmanScraper(headless=False)

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

    print("\n✓ Goldman Sachs scraper test complete")
