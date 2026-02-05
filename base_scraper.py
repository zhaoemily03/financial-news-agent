"""
Base Scraper for Sell-Side Research Portals

Abstract base class providing shared functionality for authenticated
portal scraping with dynamic cookie refresh.

Subclasses must implement portal-specific methods:
- _check_authentication() - Verify session is valid
- _navigate_to_notifications() - Find notifications/alerts UI
- _extract_notifications() - Parse notification items
- _navigate_to_report(url) - Go to report page
- _extract_report_content(report) - Extract text/PDF content
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
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from cookie_manager import CookieManager
from report_tracker import ReportTracker
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dateutil import parser as dateparser


class BaseScraper(ABC):
    """
    Abstract base class for sell-side research portal scrapers.

    Provides common functionality:
    - Cookie management (load, persist, sync to requests session)
    - Chrome WebDriver lifecycle
    - Authentication preflight checks
    - PDF download and text extraction
    - Date parsing and filtering
    - Error handling with crash resilience

    Subclasses must define:
    - PORTAL_NAME: str (e.g., "jefferies", "jpmorgan")
    - CONTENT_URL: str (portal base URL)
    - PDF_STORAGE_DIR: str (where to save PDFs)
    """

    # Subclasses MUST override these
    PORTAL_NAME: str = None
    CONTENT_URL: str = None
    PDF_STORAGE_DIR: str = None

    def __init__(self, headless: bool = True):
        if self.PORTAL_NAME is None:
            raise NotImplementedError("Subclass must define PORTAL_NAME")
        if self.CONTENT_URL is None:
            raise NotImplementedError("Subclass must define CONTENT_URL")
        if self.PDF_STORAGE_DIR is None:
            raise NotImplementedError("Subclass must define PDF_STORAGE_DIR")

        self.cookie_manager = CookieManager()
        self.report_tracker = ReportTracker()
        self.session = requests.Session()
        self.headless = headless
        self.driver = None
        # Ensure PDF storage directory exists
        os.makedirs(self.PDF_STORAGE_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Browser Lifecycle (shared)
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
        print(f"[{self.PORTAL_NAME}] Initialized Chrome WebDriver")

        # Load cookies for authentication
        self.driver.get(self.CONTENT_URL)
        time.sleep(2)

        cookies = self.cookie_manager.get_cookies(self.PORTAL_NAME)
        if cookies:
            # Get domain from CONTENT_URL
            from urllib.parse import urlparse
            parsed = urlparse(self.CONTENT_URL)
            domain = '.' + parsed.netloc.split('.')[-2] + '.' + parsed.netloc.split('.')[-1]

            for name, value in cookies.items():
                try:
                    self.driver.add_cookie({
                        'name': name,
                        'value': value,
                        'domain': domain
                    })
                except Exception:
                    pass
            print(f"[{self.PORTAL_NAME}] Loaded cookies into browser")

        self.driver.refresh()
        time.sleep(2)

        # Preflight authentication check
        if not self._check_authentication():
            print(f"[{self.PORTAL_NAME}] Authentication failed - manual login required")
            return False

        return True

    def close_driver(self):
        """Close the Selenium WebDriver and persist cookies."""
        if self.driver:
            self._persist_cookies()
            self.driver.quit()
            self.driver = None
            print(f"[{self.PORTAL_NAME}] Closed WebDriver")

    def _persist_cookies(self):
        """Save updated cookies from browser session."""
        if not self.driver:
            return

        try:
            driver_cookies = self.driver.get_cookies()
            if driver_cookies:
                self.cookie_manager.update_cookies_from_driver(self.PORTAL_NAME, driver_cookies)
                print(f"[{self.PORTAL_NAME}] Persisted updated session cookies")
        except Exception as e:
            print(f"[{self.PORTAL_NAME}] Failed to persist cookies: {e}")

    def _sync_cookies_from_driver(self):
        """Copy cookies from Selenium driver into requests session."""
        if not self.driver:
            return
        for cookie in self.driver.get_cookies():
            self.session.cookies.set(cookie['name'], cookie['value'],
                                     domain=cookie.get('domain', ''))

    def _handle_auth_failure(self) -> Dict:
        """Return structured response for auth failure."""
        return {
            'reports': [],
            'failures': [f'{self.PORTAL_NAME}: Authentication required - manual login needed'],
            'auth_required': True
        }

    # ------------------------------------------------------------------
    # Abstract Methods (portal-specific, must override)
    # ------------------------------------------------------------------

    @abstractmethod
    def _check_authentication(self) -> bool:
        """
        Verify the session is authenticated.

        Returns:
            True if authenticated, False if login required
        """
        pass

    @abstractmethod
    def _navigate_to_notifications(self) -> bool:
        """
        Navigate to notifications/alerts section.

        Returns:
            True if successfully navigated, False otherwise
        """
        pass

    @abstractmethod
    def _extract_notifications(self) -> List[Dict]:
        """
        Extract notification items from the current page.

        Returns:
            List of dicts with keys: title, url, analyst, source, date
        """
        pass

    @abstractmethod
    def _navigate_to_report(self, report_url: str) -> bool:
        """
        Navigate to a specific report page.

        Returns:
            True if successfully navigated, False otherwise
        """
        pass

    @abstractmethod
    def _extract_report_content(self, report: Dict) -> Optional[str]:
        """
        Extract content from the current report page.

        Args:
            report: Report dict (may be updated with pdf_path)

        Returns:
            Extracted text content, or None if extraction failed
        """
        pass

    # ------------------------------------------------------------------
    # PDF Handling (shared)
    # ------------------------------------------------------------------

    def download_pdf(self, url: str) -> Optional[bytes]:
        """Download PDF content from URL using authenticated session."""
        try:
            response = self.session.get(url, timeout=30)
            if response.status_code == 200 and len(response.content) > 1000:
                print(f"    Downloaded PDF ({len(response.content)} bytes)")
                return response.content
            else:
                print(f"    Failed to download PDF: HTTP {response.status_code}")
                return None
        except Exception as e:
            print(f"    Error downloading PDF: {e}")
            return None

    def extract_text_from_pdf(self, pdf_content: bytes) -> str:
        """Extract text from PDF bytes using pdfplumber (primary) or PyPDF2 (fallback)."""
        text = ""

        # Try pdfplumber first
        try:
            with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n\n"
            if text.strip():
                print(f"    Extracted {len(text)} chars from PDF")
                return text
        except Exception as e:
            print(f"    pdfplumber failed: {e}")

        # Fallback to PyPDF2
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
            for page in reader.pages:
                text += page.extract_text() + "\n\n"
            if text.strip():
                print(f"    Extracted {len(text)} chars from PDF (PyPDF2)")
                return text
        except Exception as e:
            print(f"    PDF extraction failed: {e}")

        return ""

    def _save_pdf(self, pdf_content: bytes, report: Dict) -> Optional[str]:
        """
        Save PDF to disk with categorized file structure.

        Structure: PDF_STORAGE_DIR/YYYY-MM/analyst_name/report_hash.pdf

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

            # Generate filename from URL hash
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

            print(f"    Saved PDF: {pdf_path}")
            return pdf_path

        except Exception as e:
            print(f"    Failed to save PDF: {e}")
            return None

    # ------------------------------------------------------------------
    # Date Handling (shared)
    # ------------------------------------------------------------------

    def _parse_date(self, text: str) -> Optional[datetime]:
        """Extract date from text like 'January 23, 2026'."""
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
        """Keep only reports published within the last N days."""
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

        print(f"  Date filter: {len(recent)} of {len(reports)} reports from last {days} days")
        return recent

    # ------------------------------------------------------------------
    # Main Entry Point (can be overridden if needed)
    # ------------------------------------------------------------------

    def get_followed_reports(self, max_reports: int = 20, days: int = 7) -> Dict:
        """
        Full pipeline: notifications -> filter -> extract content.

        Args:
            max_reports: Max reports to fetch
            days: Only include reports from last N days

        Returns:
            Dict with 'reports' (list), 'failures' (list of error messages),
            and optionally 'auth_required' (bool) if reauthentication needed
        """
        failures = []

        print(f"\n{'='*50}")
        print(f"[{self.PORTAL_NAME}] Fetching reports from notifications")
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

            # Navigate to notifications
            if not self._navigate_to_notifications():
                failures.append("Could not access notifications")
                self._persist_cookies()
                return {'reports': [], 'failures': failures}

            # Extract notification items
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
                print(f"  Skipped {skipped} previously processed reports")
            print(f"  -> {len(new_reports)} new reports to process")

            if not new_reports:
                print("\n No new reports to process")
                self._persist_cookies()
                return {'reports': [], 'failures': failures}

            # Limit to max_reports
            if len(new_reports) > max_reports:
                new_reports = new_reports[:max_reports]
                print(f"  Limited to {max_reports} reports")

            # Sync cookies for PDF downloads
            self._sync_cookies_from_driver()

            # Process each report with isolated error handling
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
                    failures.append(f"Error processing {report.get('title', 'unknown')[:30]}: {e}")
                    print(f"    Skipping report due to error: {e}")
                    continue

                # Persist cookies periodically
                if i % 5 == 0:
                    self._persist_cookies()

            print(f"\n{'='*50}")
            print(f"[{self.PORTAL_NAME}] Successfully extracted {len(processed)} reports")
            if failures:
                print(f"  {len(failures)} failures")
            return {'reports': processed, 'failures': failures}

        except Exception as e:
            failures.append(f"Scraper error: {e}")
            print(f"[{self.PORTAL_NAME}] Scraper error: {e}")
            return {'reports': [], 'failures': failures}

        finally:
            self.close_driver()


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("\nBaseScraper - Abstract Base Class")
    print("=" * 50)
    print("This is an abstract class and cannot be instantiated directly.")
    print("Subclasses must implement:")
    print("  - PORTAL_NAME, CONTENT_URL, PDF_STORAGE_DIR")
    print("  - _check_authentication()")
    print("  - _navigate_to_notifications()")
    print("  - _extract_notifications()")
    print("  - _navigate_to_report(url)")
    print("  - _extract_report_content(report)")
    print("\nSee JefferiesScraper for a concrete implementation.")
