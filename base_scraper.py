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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEW PORTAL INTEGRATION PLAYBOOK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RULE: Never guess API endpoints. Always ask the user to share network
calls from the browser. This is always faster than trial-and-error.

STEP 0 — CLASSIFY THE PORTAL
─────────────────────────────
Ask: "Open DevTools (F12) → Network tab → load the portal homepage.
      Do you see Fetch/XHR calls with JSON responses, or mostly HTML
      page loads and JS bundle requests?"

  JSON API responses  →  API-based scraper (see macquarie_scraper.py)
  Mostly page/JS loads →  Selenium scraper   (extends BaseScraper)

Also ask: "What does the login page look like — email+password,
  SSO/SAML redirect, or does it just load with your session already?"

  SSO/SAML redirect  →  Cookie seeding only (no automated login)
  Email+password     →  May automate, but check for CAPTCHA first
  Already logged in  →  Cookie seeding only


STEP 1 — AUTH: WHAT COOKIES/TOKENS ARE NEEDED
───────────────────────────────────────────────
Ask: "While logged in, open DevTools → Application tab → Cookies →
      click the portal domain. Share the Name and (rough) Expiry of
      each cookie. Don't share the Values yet."

Look for:
  - Session token (short TTL, e.g. 5–60 min) → auto-rotated by server
  - Refresh token (long TTL, e.g. 1 year)     → seeds the session
  - CSRF token (paired with session token)    → must be sent in header

Ask: "When you make any request (e.g. clicking around), does a new
      auth_token/session cookie appear in Set-Cookie response headers?"
  Yes → server auto-rotates; call any GET on init to get fresh token
  No  → static session cookie; just load and reuse until expiry

For 2FA portals: "Does the 2FA send a link or a code?"
  Link → can automate via MS_VERIFY_LINK pattern (see morgan_stanley_scraper.py)
  Code → cannot automate; use cookie seeding only


STEP 2 — FOLLOWED ENTITIES: HOW DOES THE PORTAL KNOW WHAT TO SHOW YOU
────────────────────────────────────────────────────────────────────────
Ask: "Clear the Network tab (🚫), then click on your
      Notifications / Preferences / Watchlist / My Feed section.
      Share the first Fetch/XHR request that returns a list of
      analysts or companies: URL + Method + Payload + Response (20 lines)."

What to look for in the response:
  - An array of followed entities with IDs → use as input to listing endpoint
  - A pre-built feed of recent items       → this IS the listing endpoint (go to Step 4)
  - A list of report IDs only              → need a separate detail endpoint


STEP 3 — LISTING: HOW TO GET RECENT REPORTS
─────────────────────────────────────────────
Ask: "Clear the Network tab, then navigate to your main reports feed
      or recent publications page. Share the Fetch/XHR request that
      returns a list of reports with titles and dates:
      URL + Method + Payload + Response (20 lines)."

If no single listing endpoint exists (like Macquarie):
  Ask: "Click on one followed analyst to see their publications.
        Share the Fetch/XHR request that loaded 'Publications by [Name]':
        URL + Method + Payload + Response (20 lines)."
  → Then iterate that endpoint per followed entity from Step 2.

Key fields to confirm in the response:
  - Report ID (to build detail/content URLs)
  - Publication date (for date filtering)
  - Title
  - Analyst name(s)
  - Any direct HTML or PDF paths (may skip Step 4 entirely)


STEP 4 — CONTENT: HOW TO GET REPORT TEXT
──────────────────────────────────────────
Ask: "Click on one report to open it. In the Network tab, share:
      (a) Any request whose response is HTML report content
          (URL + first 5 lines of response)
      (b) Any request that downloads a PDF
          (URL only — don't share the PDF bytes)"

Common patterns:
  Direct HTML:  GET /api/static/file/publications/{id}/index.html
  PDF download: GET /api/static/file/publications/{id}/{hash}.pdf
  PDF via JS:   Selenium scroll-to-reveal then intercept download URL

If the listing response (Step 3) already includes mainFileName/pdfFileName
fields → no separate content request needed.


STEP 5 — PAGINATION (IF NEEDED)
─────────────────────────────────
Ask: "Scroll down on the feed to load more reports. Does a new
      network request appear? If so, share its URL + Payload."

Typical patterns:
  page=0, page=1, ... → offset pagination
  cursor/token field  → cursor pagination
  No new request      → all results loaded upfront (use size= param)


IMPLEMENTATION CHECKLIST
──────────────────────────
API-based (no Selenium):
  [ ] Create {portal}_scraper.py (do NOT extend BaseScraper)
  [ ] Implement _load_cookies(), _refresh_session(), _persist_cookies()
  [ ] Implement _fetch_followed_entities()  (Step 2 endpoint)
  [ ] Implement _search_publications_for_entity()  (Step 3 endpoint)
  [ ] Implement _fetch_notifications()  (orchestrates 2+3)
  [ ] Implement _extract_content()  (Step 4, with bullet fallback)
  [ ] Register in portal_registry.py
  [ ] Add to config.py SOURCES (enabled: False until tested)
  [ ] Seed cookies, run standalone test, then enable

Selenium-based (extends BaseScraper):
  [ ] Create {portal}_scraper.py extending BaseScraper
  [ ] Define PORTAL_NAME, CONTENT_URL, PDF_STORAGE_DIR
  [ ] Implement _check_authentication()
  [ ] Implement _navigate_to_notifications()
  [ ] Implement _extract_notifications()
  [ ] Implement _navigate_to_report(url)
  [ ] Implement _extract_report_content(report)
  [ ] Register in portal_registry.py
  [ ] Add to config.py SOURCES

Reference implementations:
  API-based:      macquarie_scraper.py
  Selenium-based: morgan_stanley_scraper.py, bernstein_scraper.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import requests
from bs4 import BeautifulSoup
import PyPDF2
import pdfplumber
import io
import os
import re
import time
import random
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
import config as _cfg


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
        self.driver.set_page_load_timeout(_cfg.PAGE_LOAD_TIMEOUT)
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

    def _is_browser_alive(self) -> bool:
        """Check if the Chrome session is still alive (crash detection)."""
        try:
            _ = self.driver.current_url
            return True
        except Exception:
            return False

    def _is_session_valid(self) -> bool:
        """
        Check if the current page is a login redirect (session expiry mid-run).
        Distinct from _is_browser_alive — browser is alive but unauthenticated.
        """
        try:
            url = self.driver.current_url.lower()
            login_signals = ['login', 'signin', 'sign-in', 'sso', 'saml', 'oauth', 'authenticate']
            if any(s in url for s in login_signals):
                return False
            title = self.driver.title.lower()
            if 'sign in' in title or 'login' in title:
                return False
            return True
        except Exception:
            return False  # dead browser → treat as invalid

    def _write_auth_alert(self):
        """Write a flag file when manual re-authentication is needed."""
        try:
            os.makedirs('data/alerts', exist_ok=True)
            alert_path = f'data/alerts/auth_required_{self.PORTAL_NAME}.txt'
            with open(alert_path, 'w') as f:
                f.write(f"{self.PORTAL_NAME} requires manual authentication\n")
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(f"Action: re-run cookie refresh or set new verify link in .env\n")
            print(f"[{self.PORTAL_NAME}] ⚠ Auth alert: {alert_path}")
        except Exception as e:
            print(f"[{self.PORTAL_NAME}] Failed to write auth alert: {e}")

    def _restart_browser(self) -> bool:
        """
        Close and restart Chrome to clear memory / prevent session decay.
        Returns False if re-authentication fails after restart.
        """
        print(f"[{self.PORTAL_NAME}] Restarting browser (batch boundary)...")
        self.close_driver()
        time.sleep(2)
        if not self._init_driver():
            print(f"[{self.PORTAL_NAME}] ✗ Re-authentication failed after restart")
            self._write_auth_alert()
            return False
        self._sync_cookies_from_driver()
        print(f"[{self.PORTAL_NAME}] ✓ Browser restarted successfully")
        return True

    def _request_delay(self):
        """Human-like random delay between report navigations (avoids rate limiting)."""
        delay = random.uniform(_cfg.REQUEST_DELAY_MIN, _cfg.REQUEST_DELAY_MAX)
        time.sleep(delay)

    def _navigate_to_report_with_retry(self, url: str) -> bool:
        """
        Navigate to a report URL with bounded retries + exponential backoff.
        Prevents infinite loops: max MAX_NAV_RETRIES attempts total.
        """
        for attempt in range(_cfg.MAX_NAV_RETRIES):
            try:
                if self._navigate_to_report(url):
                    # Verify we didn't land on a login page
                    if not self._is_session_valid():
                        print(f"    ✗ Session expired during navigation")
                        self._write_auth_alert()
                        return False
                    return True
            except Exception as e:
                print(f"    ✗ Navigation attempt {attempt + 1}/{_cfg.MAX_NAV_RETRIES} failed: {e}")

            if attempt < _cfg.MAX_NAV_RETRIES - 1:
                wait = _cfg.NAV_RETRY_BACKOFF_BASE ** attempt  # 1s, 2s, 4s
                print(f"    Retrying in {wait:.0f}s...")
                time.sleep(wait)

        return False

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
        """
        Download PDF via requests with retries, exponential backoff, and 429 handling.
        Bounded to MAX_NAV_RETRIES attempts — no infinite loops.
        """
        for attempt in range(_cfg.MAX_NAV_RETRIES):
            try:
                response = self.session.get(url, timeout=_cfg.REQUEST_TIMEOUT)

                if response.status_code == 200 and len(response.content) > 1000:
                    print(f"    Downloaded PDF ({len(response.content)} bytes)")
                    return response.content

                elif response.status_code == 429:
                    # Respect Retry-After header; cap at 5 minutes
                    retry_after = int(response.headers.get('Retry-After', 60))
                    wait = min(retry_after, 300)
                    print(f"    Rate limited (429) — waiting {wait}s")
                    time.sleep(wait)
                    continue  # retry after wait

                else:
                    print(f"    Failed to download PDF: HTTP {response.status_code}")
                    return None

            except Exception as e:
                print(f"    PDF download attempt {attempt + 1} failed: {e}")
                if attempt < _cfg.MAX_NAV_RETRIES - 1:
                    time.sleep(_cfg.NAV_RETRY_BACKOFF_BASE ** attempt)

        print(f"    Failed to download PDF after {_cfg.MAX_NAV_RETRIES} attempts")
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

    def get_followed_reports(self, max_reports: int = 20, days: int = 7, result_out: Dict = None) -> Dict:
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
                # Crash detection: stop immediately, return what we have
                if not self._is_browser_alive():
                    print(f"[{self.PORTAL_NAME}] ✗ Browser crashed — returning {len(processed)} partial results")
                    failures.append(f"Browser crashed at report {i}/{len(new_reports)}")
                    break

                # Session decay detection: login-page redirect mid-run
                if not self._is_session_valid():
                    print(f"[{self.PORTAL_NAME}] ✗ Session expired — stopping")
                    self._write_auth_alert()
                    failures.append(f"Session expired at report {i}/{len(new_reports)}")
                    break

                # Periodic browser restart to prevent memory leaks + session decay
                if i > 1 and (i - 1) % _cfg.BROWSER_RESTART_AFTER_DOWNLOADS == 0:
                    if not self._restart_browser():
                        failures.append("Re-auth failed after browser restart")
                        break
                    # Re-sync cookies after restart
                    self._sync_cookies_from_driver()

                try:
                    print(f"\n  [{i}/{len(new_reports)}] {report['title'][:60]}")

                    # Human-like delay between navigations
                    if i > 1:
                        self._request_delay()

                    # Bounded retry with exponential backoff — no infinite loops
                    if not self._navigate_to_report_with_retry(report['url']):
                        failures.append(f"Failed to navigate: {report['title'][:40]}")
                        continue

                    content = self._extract_report_content(report)
                    if content:
                        report['content'] = content
                        processed.append(report)
                        # Live-write so partial results survive a timeout
                        if result_out is not None:
                            result_out['reports'].append(report)
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
            # Fix B: return partial results even on unexpected exception
            return {'reports': processed if 'processed' in dir() else [], 'failures': failures}

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
