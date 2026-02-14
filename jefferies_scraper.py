"""
Jefferies Research Portal Scraper

Workflow (Followed Notifications approach):
1. Login (via cookies)
2. Click "Followed Notifications" bell icon
3. Get list of report notifications from followed analysts
4. Click each notification → go directly to report page
5. Extract content (direct text or PDF fallback)
6. Filter: last 7 days only, skip previously processed reports

Inherits from BaseScraper for shared cookie/auth/PDF functionality.
"""

import requests
from bs4 import BeautifulSoup
import PyPDF2
import pdfplumber
import io
import os
import re
import time
import hashlib
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from cookie_manager import CookieManager
from report_tracker import ReportTracker
from base_scraper import BaseScraper
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dateutil import parser as dateparser


class JefferiesScraper(BaseScraper):
    """Scraper for Jefferies research portal using Followed Notifications"""

    # Required by BaseScraper
    PORTAL_NAME = "jefferies"
    CONTENT_URL = "https://content.jefferies.com"
    PDF_STORAGE_DIR = "data/reports/jefferies"

    def __init__(self, headless: bool = True):
        super().__init__(headless=headless)

    # ------------------------------------------------------------------
    # Browser setup
    # ------------------------------------------------------------------

    def _init_driver(self) -> bool:
        """
        Initialize Chrome WebDriver, load cookies, and verify authentication.

        Returns:
            True if driver initialized and authenticated, False if auth failed
        """
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
        print("✓ Initialized Chrome WebDriver")

        # Load cookies for authentication
        self.driver.get(self.CONTENT_URL)
        time.sleep(2)

        cookies = self.cookie_manager.get_cookies('jefferies')
        if cookies:
            for name, value in cookies.items():
                try:
                    self.driver.add_cookie({
                        'name': name,
                        'value': value,
                        'domain': '.jefferies.com'
                    })
                except Exception:
                    pass
            print("✓ Loaded cookies into browser")

        self.driver.refresh()
        time.sleep(2)

        # Preflight authentication check
        if not self._check_authentication():
            print("✗ Authentication failed - manual login required")
            return False

        return True

    def close_driver(self):
        """Close the Selenium WebDriver"""
        if self.driver:
            # Persist cookies before closing
            self._persist_cookies()
            self.driver.quit()
            self.driver = None
            print("✓ Closed WebDriver")

    # ------------------------------------------------------------------
    # Authentication & Session Management
    # ------------------------------------------------------------------

    def _check_authentication(self) -> bool:
        """
        Preflight authentication check.
        Validates access by checking URL and page content.
        Waits for potential redirects to complete before checking.

        Returns:
            True if authenticated, False if reauthentication needed
        """
        try:
            self.driver.get(self.CONTENT_URL)

            # Wait longer for redirects to complete (SSO can be slow)
            # Check URL multiple times to catch delayed redirects
            login_url_indicators = [
                'oneclient.jefferies.com',  # SSO redirect
                'sso', 'saml', 'login', 'signin', 'authenticate',
                'idp', 'shibboleth'  # Additional SSO indicators
            ]

            for wait_round in range(3):  # Check 3 times over 6 seconds
                time.sleep(2)
                current_url = self.driver.current_url.lower()

                for indicator in login_url_indicators:
                    if indicator in current_url:
                        print(f"✗ Authentication check: redirected to login ({indicator} in URL)")
                        print(f"  Session cookies expired - manual re-authentication required")
                        return False

            # Final URL check
            current_url = self.driver.current_url.lower()
            page_title = self.driver.title.lower()

            # Check page title for login indicators
            if 'sign in' in page_title or 'login' in page_title or 'sso' in page_title:
                print(f"✗ Authentication check: login page detected (title: {page_title})")
                print(f"  Session cookies expired - manual re-authentication required")
                return False

            # Must be on content.jefferies.com to be authenticated
            if 'content.jefferies.com' not in current_url:
                print(f"✗ Authentication check: not on portal (URL: {current_url[:60]})")
                return False

            # Check page content for definitive auth indicators
            page_source = self.driver.page_source.lower()

            # Signs of being authenticated - look for UI elements only visible when logged in
            auth_indicators = [
                'notification', 'followed', 'my research',
                'profile', 'logout', 'sign out'
            ]
            for indicator in auth_indicators:
                if indicator in page_source:
                    print("✓ Authentication check: valid session")
                    return True

            # Check for actual research content markers
            research_markers = ['equity research', 'analyst', 'report', 'coverage']
            found_markers = sum(1 for m in research_markers if m in page_source)
            if found_markers >= 2:
                print("✓ Authentication check: research content accessible")
                return True

            # On portal but no auth indicators = session likely invalid
            # Don't assume we're authenticated just because URL looks right
            print(f"✗ Authentication check: on portal but no authenticated content found")
            print(f"  This usually means cookies are expired - manual re-authentication required")
            return False

        except Exception as e:
            print(f"✗ Authentication check error: {e}")
            return False

    def _persist_cookies(self):
        """
        Save updated cookies from browser session.
        Called after scraping operations to persist dynamic updates.
        """
        if not self.driver:
            return

        try:
            driver_cookies = self.driver.get_cookies()
            if driver_cookies:
                self.cookie_manager.update_cookies_from_driver('jefferies', driver_cookies)
                print("✓ Persisted updated session cookies")
        except Exception as e:
            print(f"⚠ Failed to persist cookies: {e}")

    def _handle_auth_failure(self) -> Dict:
        """
        Handle authentication failure gracefully.

        Returns:
            Dict with empty reports and auth failure message
        """
        return {
            'reports': [],
            'failures': ['Authentication required - manual login needed'],
            'auth_required': True
        }

    # ------------------------------------------------------------------
    # Step 2: Click Followed Notifications (bell icon)
    # ------------------------------------------------------------------

    def _click_notifications_bell(self) -> bool:
        """Click the Followed Notifications bell icon in top right"""
        try:
            # Look for bell icon - common selectors
            bell_selectors = [
                '[aria-label*="notification"]',
                '[aria-label*="Notification"]',
                '[title*="notification"]',
                '[title*="Notification"]',
                '[title*="Followed"]',
                '.notification-bell',
                '.v-badge',  # Vuetify badge (often wraps notification icons)
                'button[class*="notification"]',
                # Icon-based (mdi = Material Design Icons, common in Vuetify)
                '.mdi-bell',
                '[class*="bell"]',
            ]

            for selector in bell_selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if el.is_displayed():
                        self.driver.execute_script("arguments[0].click();", el)
                        print("✓ Clicked Followed Notifications bell")
                        time.sleep(3)
                        return True

            # Fallback: look for any clickable element with "notification" or "followed" text
            all_clickable = self.driver.find_elements(By.CSS_SELECTOR, 'button, a, [role="button"]')
            for el in all_clickable:
                try:
                    text = el.get_attribute('aria-label') or el.get_attribute('title') or el.text or ''
                    if 'notif' in text.lower() or 'followed' in text.lower() or 'bell' in text.lower():
                        if el.is_displayed():
                            self.driver.execute_script("arguments[0].click();", el)
                            print(f"✓ Clicked notifications element: {text[:40]}")
                            time.sleep(3)
                            return True
                except:
                    continue

            print("✗ Could not find notifications bell icon")
            return False

        except Exception as e:
            print(f"✗ Error clicking notifications: {e}")
            return False

    def _navigate_to_notifications(self) -> bool:
        """
        Navigate to notifications section.
        Required by BaseScraper interface - delegates to _click_notifications_bell.
        """
        return self._click_notifications_bell()

    # ------------------------------------------------------------------
    # Step 3: Extract notification items (reports from followed analysts)
    # ------------------------------------------------------------------

    def _extract_notifications(self) -> List[Dict]:
        """Extract ALL report notifications from the notifications panel"""
        notifications = []
        seen_urls = set()

        try:
            # Scroll within notifications panel to load all items
            # Try multiple scroll attempts to get everything
            for scroll_attempt in range(5):
                time.sleep(2)

                # Get page source and parse
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')

                # Find all report links
                report_links = soup.find_all('a', href=re.compile(r'/report/'))

                for link in report_links:
                    href = link.get('href', '')
                    if not href or 'not-entitled' in href:
                        continue

                    # Make URL absolute
                    if not href.startswith('http'):
                        href = self.CONTENT_URL + href

                    # Skip duplicates
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)

                    # Extract title and metadata
                    title = link.text.strip()
                    if not title:
                        title = link.get('title', 'Untitled')

                    # Try to find analyst name from surrounding context
                    parent = link.find_parent(['div', 'li', 'article'])
                    analyst = self._extract_analyst_from_element(parent) if parent else None

                    # Parse date
                    pub_date = self._parse_date(title)
                    if not pub_date and parent:
                        pub_date = self._parse_date(parent.text)

                    notifications.append({
                        'title': title[:200],
                        'url': href,
                        'analyst': analyst,
                        'source': 'Jefferies',
                        'date': pub_date.strftime('%Y-%m-%d') if pub_date else None,
                    })

                # Scroll down in the notifications panel to load more
                try:
                    self.driver.execute_script(
                        "document.querySelector('.v-navigation-drawer__content, .v-list, [role=\"list\"]')?.scrollBy(0, 500)"
                    )
                except:
                    self.driver.execute_script("window.scrollBy(0, 300)")

            print(f"✓ Found {len(notifications)} notifications (all loaded)")
            return notifications

        except Exception as e:
            print(f"✗ Error extracting notifications: {e}")
            return []

    def _extract_analyst_from_element(self, element) -> Optional[str]:
        """Try to extract analyst name from a notification element"""
        if not element:
            return None

        text = element.text
        # Common patterns: "by Analyst Name" or "Analyst Name - Topic"
        patterns = [
            r'by\s+([A-Z][a-z]+\s+[A-Z][a-z]+)',
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s*[-–]\s*\w+',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    # ------------------------------------------------------------------
    # Step 4-5: Navigate to report and extract content
    # ------------------------------------------------------------------

    def _navigate_to_report(self, report_url: str) -> bool:
        """Navigate to a specific report page"""
        try:
            self.driver.get(report_url)
            time.sleep(5)  # Wait for page to load
            return True
        except Exception as e:
            print(f"    ✗ Error navigating to report: {e}")
            return False

    def _extract_report_content(self, report: Dict = None) -> Optional[str]:
        """Extract content from current report page (direct text or PDF)"""

        # Method 1: Try to extract text directly from the page
        text = self._extract_text_from_page()
        if text and len(text) > 500:
            print(f"    ✓ Extracted {len(text)} chars directly from page")
            return text

        # Method 2: Get PDF URL and download
        pdf_url = self._get_pdf_url()
        if pdf_url:
            self._sync_cookies_from_driver()
            pdf_bytes = self.download_pdf(pdf_url)
            if pdf_bytes:
                # Save PDF to disk for historical access
                if report:
                    pdf_path = self._save_pdf(pdf_bytes, report)
                    if pdf_path:
                        report['pdf_path'] = pdf_path

                text = self.extract_text_from_pdf(pdf_bytes)
                if text:
                    return text

        return None

    def _extract_text_from_page(self) -> Optional[str]:
        """Try to extract report text directly from the page"""
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # Remove script/style elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer']):
                element.decompose()

            # Look for main content container
            content_selectors = [
                '.report-content',
                '.document-content',
                '.article-content',
                'article',
                'main',
                '[role="main"]',
                '.v-main',
            ]

            for selector in content_selectors:
                content = soup.select_one(selector)
                if content:
                    text = content.get_text(separator='\n', strip=True)
                    if len(text) > 500:
                        return text

            # Fallback: get all text from body
            body = soup.find('body')
            if body:
                text = body.get_text(separator='\n', strip=True)
                # Filter out likely navigation/UI text
                lines = [l for l in text.split('\n') if len(l) > 50]
                if lines:
                    return '\n'.join(lines)

            return None

        except Exception as e:
            print(f"    ⚠ Error extracting page text: {e}")
            return None

    def _get_pdf_url(self) -> Optional[str]:
        """Get PDF URL from the report page (iframe src or Print PDF button)"""
        try:
            # Check iframes for PDF link
            iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
            for iframe in iframes:
                src = iframe.get_attribute('src') or ''
                if 'links2' in src.lower() or 'doc' in src.lower():
                    pdf_src = src.replace('/doc/html/', '/doc/pdf/')
                    print(f"    ✓ PDF URL from iframe: {pdf_src[:60]}...")
                    return pdf_src

            # Look for Print PDF button
            pdf_buttons = self.driver.find_elements(By.XPATH,
                "//*[contains(text(), 'Print PDF') or contains(text(), 'PDF') or contains(@aria-label, 'PDF')]")
            for btn in pdf_buttons:
                if btn.is_displayed():
                    # Click and capture the PDF URL
                    self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(2)
                    # Check for new window/tab or download link
                    # For now, just look for links2 URLs in page source
                    break

            # Fallback: search page source for PDF URLs
            links2_urls = re.findall(r'(https?://[^\s"\']*links2/doc/[^\s"\']*)', self.driver.page_source)
            for url in links2_urls:
                pdf_url = url.replace('/doc/html/', '/doc/pdf/')
                print(f"    ✓ PDF URL from source: {pdf_url[:60]}...")
                return pdf_url

            return None

        except Exception as e:
            print(f"    ⚠ Error getting PDF URL: {e}")
            return None

    # ------------------------------------------------------------------
    # PDF download and text extraction
    # ------------------------------------------------------------------

    def _sync_cookies_from_driver(self):
        """Copy cookies from Selenium driver into requests session"""
        if not self.driver:
            return
        for cookie in self.driver.get_cookies():
            self.session.cookies.set(cookie['name'], cookie['value'],
                                     domain=cookie.get('domain', ''))

    def download_pdf(self, url: str) -> Optional[bytes]:
        """Download PDF content from URL using authenticated session"""
        try:
            response = self.session.get(url, timeout=30)
            if response.status_code == 200 and len(response.content) > 1000:
                print(f"    ✓ Downloaded PDF ({len(response.content)} bytes)")
                return response.content
            else:
                print(f"    ✗ Failed to download PDF: HTTP {response.status_code}")
                return None
        except Exception as e:
            print(f"    ✗ Error downloading PDF: {e}")
            return None

    def _save_pdf(self, pdf_content: bytes, report: Dict) -> Optional[str]:
        """
        Save PDF to disk with categorized file structure.

        Structure: data/reports/jefferies/YYYY-MM/analyst_name/report_hash.pdf
        Also saves metadata JSON alongside each PDF.

        Returns: Path to saved PDF or None if failed
        """
        try:
            # Get date for folder structure
            pub_date = report.get('date') or datetime.now().strftime('%Y-%m-%d')
            year_month = pub_date[:7]  # YYYY-MM

            # Sanitize analyst name for folder
            analyst = report.get('analyst') or 'unknown'
            analyst_folder = re.sub(r'[^\w\s-]', '', analyst).strip().replace(' ', '_').lower()

            # Create directory structure
            dir_path = os.path.join(self.PDF_STORAGE_DIR, year_month, analyst_folder)
            os.makedirs(dir_path, exist_ok=True)

            # Generate filename from URL hash (ensures uniqueness)
            url_hash = hashlib.md5(report.get('url', '').encode()).hexdigest()[:12]
            title_slug = re.sub(r'[^\w\s-]', '', report.get('title', '')[:30]).strip().replace(' ', '_').lower()
            filename = f"{pub_date}_{title_slug}_{url_hash}"

            pdf_path = os.path.join(dir_path, f"{filename}.pdf")
            meta_path = os.path.join(dir_path, f"{filename}.json")

            # Save PDF
            with open(pdf_path, 'wb') as f:
                f.write(pdf_content)

            # Save metadata
            metadata = {
                'url': report.get('url'),
                'title': report.get('title'),
                'analyst': analyst,
                'source': report.get('source'),
                'publish_date': pub_date,
                'scraped_at': datetime.now().isoformat(),
                'pdf_size_bytes': len(pdf_content),
                'pdf_path': pdf_path,
            }
            with open(meta_path, 'w') as f:
                json.dump(metadata, f, indent=2)

            print(f"    ✓ Saved PDF: {pdf_path}")
            return pdf_path

        except Exception as e:
            print(f"    ⚠ Failed to save PDF: {e}")
            return None

    def extract_text_from_pdf(self, pdf_content: bytes) -> str:
        """Extract text from PDF bytes using pdfplumber (primary) or PyPDF2 (fallback)"""
        text = ""

        # Try pdfplumber first
        try:
            with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n\n"
            if text.strip():
                print(f"    ✓ Extracted {len(text)} chars from PDF")
                return text
        except Exception as e:
            print(f"    ⚠ pdfplumber failed: {e}")

        # Fallback to PyPDF2
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
            for page in reader.pages:
                text += page.extract_text() + "\n\n"
            if text.strip():
                print(f"    ✓ Extracted {len(text)} chars from PDF (PyPDF2)")
                return text
        except Exception as e:
            print(f"    ✗ PDF extraction failed: {e}")

        return ""

    # ------------------------------------------------------------------
    # Date parsing and filtering
    # ------------------------------------------------------------------

    def _parse_date(self, text: str) -> Optional[datetime]:
        """Extract date from text like 'January 23, 2026'"""
        try:
            match = re.search(
                r'((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})',
                text
            )
            if match:
                return dateparser.parse(match.group(1))
        except:
            pass
        return None

    def filter_by_date(self, reports: List[Dict], days: int = 7) -> List[Dict]:
        """Keep only reports published within the last N days"""
        cutoff = datetime.now() - timedelta(days=days)
        recent = []

        for report in reports:
            if not report.get('date'):
                recent.append(report)  # Include if date unknown
                continue
            try:
                report_date = datetime.strptime(report['date'], '%Y-%m-%d')
                if report_date >= cutoff:
                    recent.append(report)
            except:
                recent.append(report)

        print(f"  ✓ Date filter: {len(recent)} of {len(reports)} reports from last {days} days")
        return recent

    # ------------------------------------------------------------------
    # Main orchestration
    # ------------------------------------------------------------------

    def get_followed_reports(self, max_reports: int = 20, days: int = 7) -> Dict:
        """
        Full pipeline: notifications → filter → extract content.

        Args:
            max_reports: Max reports to fetch
            days: Only include reports from last N days

        Returns:
            Dict with 'reports' (list), 'failures' (list of error messages),
            and optionally 'auth_required' (bool) if reauthentication needed
        """
        failures = []

        print(f"\n{'='*50}")
        print("Fetching reports from Followed Notifications")
        print(f"{'='*50}")

        try:
            # Initialize driver with authentication check
            if not self._init_driver():
                return self._handle_auth_failure()

            # Navigate to main page
            try:
                self.driver.get(self.CONTENT_URL)
                time.sleep(3)
            except Exception as e:
                failures.append(f"Failed to navigate to portal: {e}")
                return {'reports': [], 'failures': failures}

            # Step 2: Click notifications bell
            if not self._click_notifications_bell():
                failures.append("Could not access Followed Notifications")
                # Persist cookies even on failure
                self._persist_cookies()
                return {'reports': [], 'failures': failures}

            # Step 3: Extract ALL notification items (no limit)
            try:
                notifications = self._extract_notifications()
            except Exception as e:
                failures.append(f"Failed to extract notifications: {e}")
                notifications = []

            if not notifications:
                failures.append("No notifications found (check followed analysts)")
                self._persist_cookies()
                return {'reports': [], 'failures': failures}

            print(f"\n{'='*50}")
            print(f"Found {len(notifications)} notifications")

            # Filter by date
            recent = self.filter_by_date(notifications, days=days)

            # Filter out already processed
            new_reports = self.report_tracker.filter_unprocessed(recent)
            skipped = len(recent) - len(new_reports)
            if skipped:
                print(f"  ✓ Skipped {skipped} previously processed reports")
            print(f"  → {len(new_reports)} new reports to process")

            if not new_reports:
                print("\n✓ No new reports to process")
                self._persist_cookies()
                return {'reports': [], 'failures': failures}

            # Sync cookies for PDF downloads
            self._sync_cookies_from_driver()

            # Step 4-5: Process each report with isolated error handling
            processed = []
            for i, report in enumerate(new_reports, 1):
                try:
                    print(f"\n  [{i}/{len(new_reports)}] {report['title'][:60]}")

                    if not self._navigate_to_report(report['url']):
                        failures.append(f"Failed to navigate: {report['title'][:40]}")
                        continue

                    content = self._extract_report_content(report)
                    if content:
                        report['content'] = content
                        processed.append(report)
                        self.report_tracker.mark_as_processed(report)
                    else:
                        failures.append(f"Failed to extract: {report['title'][:40]}")

                except Exception as e:
                    # Isolate failure - don't crash the entire run
                    failures.append(f"Error processing {report.get('title', 'unknown')[:30]}: {e}")
                    print(f"    ⚠ Skipping report due to error: {e}")
                    continue

                # Persist cookies periodically (every 5 reports)
                if i % 5 == 0:
                    self._persist_cookies()

            print(f"\n{'='*50}")
            print(f"✓ Successfully extracted {len(processed)} reports")
            if failures:
                print(f"⚠ {len(failures)} failures")
            return {'reports': processed, 'failures': failures}

        except Exception as e:
            # Top-level crash resilience
            failures.append(f"Scraper error: {e}")
            print(f"✗ Scraper error: {e}")
            return {'reports': [], 'failures': failures}

        finally:
            self.close_driver()

    # ------------------------------------------------------------------
    # Legacy method for backward compatibility
    # ------------------------------------------------------------------

    def get_reports_by_analysts(self, analyst_names: List[str] = None,
                                max_per_analyst: int = 10,
                                days: int = 7) -> Dict:
        """
        Backward-compatible wrapper. Now uses Followed Notifications.
        analyst_names parameter is ignored - follows are determined by user's portal settings.
        """
        print("  ℹ Using Followed Notifications (analyst_names param ignored)")
        return self.get_followed_reports(max_reports=max_per_analyst * 2, days=days)


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("\nJefferies Scraper Test (Followed Notifications)")
    print("=" * 50)

    # Test 1: CookieManager Selenium integration
    print("\n[1/3] Testing CookieManager.update_cookies_from_driver...")
    cm = CookieManager()
    test_driver_cookies = [
        {'name': 'test_session', 'value': 'abc123'},
        {'name': 'test_csrf', 'value': 'xyz789'}
    ]
    cm.update_cookies_from_driver('test_portal', test_driver_cookies)
    saved = cm.get_cookies('test_portal')
    assert saved is not None, "Cookies should be saved"
    assert saved.get('test_session') == 'abc123', "Session cookie should match"
    assert saved.get('test_csrf') == 'xyz789', "CSRF cookie should match"
    cm.delete_cookies('test_portal')  # Cleanup
    print("✓ CookieManager.update_cookies_from_driver works")

    # Test 2: Scraper initialization
    print("\n[2/3] Testing scraper session management...")
    scraper = JefferiesScraper(headless=False)  # headless=False to see browser
    assert scraper.cookie_manager is not None, "Cookie manager should be initialized"
    assert scraper.report_tracker is not None, "Report tracker should be initialized"
    print("✓ Scraper session management initialized")

    # Test 3: Full pipeline with auth check
    print("\n[3/3] Testing full pipeline...")
    print("Using Followed Notifications to get reports")
    print("Filter: last 7 days, skip previously processed\n")

    result = scraper.get_followed_reports(max_reports=10, days=7)

    # Validate result structure
    assert 'reports' in result, "Result should have 'reports' key"
    assert 'failures' in result, "Result should have 'failures' key"
    assert isinstance(result['reports'], list), "Reports should be a list"
    assert isinstance(result['failures'], list), "Failures should be a list"
    print("✓ Result structure validated")

    # Check for auth_required flag
    if result.get('auth_required'):
        print("\n⚠ Authentication required - manual login needed")
        print("  Run browser manually, login, then re-export cookies")
        sys.exit(1)

    reports = result.get('reports', [])
    failures = result.get('failures', [])

    print(f"\n--- Results ---")
    print(f"Reports extracted: {len(reports)}")
    print(f"Failures: {len(failures)}")

    for i, report in enumerate(reports, 1):
        print(f"\n--- Report {i} ---")
        print(f"Title:   {report['title'][:80]}")
        print(f"Analyst: {report.get('analyst', 'unknown')}")
        print(f"Date:    {report.get('date', 'unknown')}")
        print(f"URL:     {report['url']}")
        if report.get('content'):
            print(f"Content: {report['content'][:200]}...")

    if failures:
        print(f"\n--- Failures ---")
        for f in failures:
            print(f"  - {f}")

    print("\n✓ All tests passed")
