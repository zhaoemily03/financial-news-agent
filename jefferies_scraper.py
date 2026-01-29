"""
Jefferies Research Portal Scraper

Workflow (matches user's manual process):
1. Login (via cookies)
2. Navigate to Advanced Search > Analysts/Authors
3. Type analyst name in search box
4. Click matching analyst name from dropdown
5. Click SEARCH
6. Get list of reports (sorted by date, most recent first)
7. Click into each report → click "Print PDF" → download PDF
8. Filter: last 5 days only, skip previously processed reports
"""

import requests
from bs4 import BeautifulSoup
import PyPDF2
import pdfplumber
import io
import re
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from cookie_manager import CookieManager
from report_tracker import ReportTracker
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from dateutil import parser as dateparser


class JefferiesScraper:
    """Scraper for Jefferies research portal"""

    CONTENT_URL = "https://content.jefferies.com"

    def __init__(self, headless: bool = True):
        self.cookie_manager = CookieManager()
        self.report_tracker = ReportTracker()
        self.session = requests.Session()
        self.headless = headless
        self.driver = None

    # ------------------------------------------------------------------
    # Browser setup
    # ------------------------------------------------------------------

    def _init_driver(self):
        """Initialize Chrome WebDriver and load cookies"""
        if self.driver:
            return

        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')

        self.driver = webdriver.Chrome(options=chrome_options)
        print("✓ Initialized Chrome WebDriver")

        # Step 1: Load cookies into browser for authentication
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
                    pass  # Skip cookies that can't be set
            print("✓ Loaded cookies into browser (Step 1: Login)")

        self.driver.refresh()
        time.sleep(2)

    def close_driver(self):
        """Close the Selenium WebDriver"""
        if self.driver:
            self.driver.quit()
            self.driver = None
            print("✓ Closed WebDriver")

    # ------------------------------------------------------------------
    # Step 2-5: Advanced Search by Analyst
    # ------------------------------------------------------------------

    def search_by_analyst(self, analyst_name: str, max_results: int = 20) -> List[Dict]:
        """
        Steps 2-6: Navigate to Advanced Search, filter by analyst, get report list.

        Args:
            analyst_name: e.g. "Brent Thill"
            max_results: Max reports to return

        Returns:
            List of report metadata dicts (url, title, date, analyst)
        """
        print(f"\n{'='*50}")
        print(f"Searching for reports by: {analyst_name}")
        print(f"{'='*50}")

        self._init_driver()

        # Step 2: Navigate to Advanced Search
        self.driver.get(self.CONTENT_URL)
        time.sleep(3)

        adv_link = self._find_and_click_adv_search()
        if not adv_link:
            print("✗ Could not find Advanced Search link")
            return []
        time.sleep(3)

        # Step 3: Expand Analysts/Authors panel and type name
        if not self._enter_analyst_name(analyst_name):
            print("✗ Could not enter analyst name")
            return []

        # Step 4: Click matching option from dropdown (handled in _enter_analyst_name)

        # Step 5: Click SEARCH
        if not self._click_search_button():
            print("✗ Could not click SEARCH button")
            return []

        # Step 6: Extract report list from results
        reports = self._extract_report_list(analyst_name, max_results)
        print(f"✓ Found {len(reports)} reports by {analyst_name}")

        return reports

    def _find_and_click_adv_search(self) -> bool:
        """Step 2: Find and click ADV SEARCH link"""
        try:
            # Try exact match first
            links = self.driver.find_elements(By.LINK_TEXT, 'ADV SEARCH')
            if not links:
                links = self.driver.find_elements(By.PARTIAL_LINK_TEXT, 'ADV')
            if links:
                links[0].click()
                print("✓ Step 2: Navigated to Advanced Search")
                return True
        except Exception as e:
            print(f"  Error navigating to Advanced Search: {e}")
        return False

    def _enter_analyst_name(self, analyst_name: str) -> bool:
        """Steps 3-4: Expand panel, type name, click matching dropdown option"""
        try:
            # Find the Analysts/Authors expansion panel
            panels = self.driver.find_elements(By.CSS_SELECTOR, '.v-expansion-panel')
            analyst_panel = None
            for panel in panels:
                if 'Analysts/Authors' in panel.text:
                    analyst_panel = panel
                    break

            if not analyst_panel:
                print("  ✗ Could not find Analysts/Authors panel")
                return False

            # Click to expand the panel
            header = analyst_panel.find_element(By.CSS_SELECTOR, '.v-expansion-panel-title')
            self.driver.execute_script("arguments[0].click();", header)
            print("  ✓ Step 3: Expanded Analysts/Authors panel")
            time.sleep(2)

            # Find the text input inside the panel
            search_inputs = analyst_panel.find_elements(By.CSS_SELECTOR, 'input[type="text"]')
            if not search_inputs:
                # Try broader search for visible inputs
                search_inputs = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="text"]')
                search_inputs = [inp for inp in search_inputs if inp.is_displayed()]

            if not search_inputs:
                print("  ✗ Could not find analyst search input")
                return False

            # Type the analyst name
            input_field = search_inputs[-1]  # Usually the last visible input
            input_field.clear()
            input_field.send_keys(analyst_name)
            print(f"  ✓ Step 3: Typed '{analyst_name}' in search box")
            time.sleep(3)  # Wait for autocomplete dropdown

            # Step 4: Click on the matching dropdown option
            dropdown_options = self.driver.find_elements(By.CSS_SELECTOR,
                '.v-list-item, [role="option"], [role="listbox"] .v-list-item')

            for option in dropdown_options:
                if analyst_name.lower() in option.text.lower():
                    self.driver.execute_script("arguments[0].click();", option)
                    print(f"  ✓ Step 4: Selected analyst: {option.text.strip()[:60]}")
                    time.sleep(3)
                    return True

            # Fallback: press Enter if no dropdown match
            print("  ⚠ No dropdown match found, pressing Enter")
            input_field.send_keys(Keys.RETURN)
            time.sleep(1)
            return True

        except Exception as e:
            print(f"  ✗ Error entering analyst name: {e}")
            return False

    def _click_search_button(self) -> bool:
        """Step 5: Click the SEARCH button below all filter panels"""
        try:
            # Scroll to the bottom of the filter section to make SEARCH visible
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

            # The SEARCH button is outside/below all the filter panels.
            # It's alongside CLEAR ALL, PREVIOUS SEARCH, SAVE AS FILTER, SHARE FILTER.
            # Look for a group of buttons and find the one that says SEARCH.
            all_buttons = self.driver.find_elements(By.CSS_SELECTOR, 'button.v-btn, button')

            search_btn = None
            for btn in all_buttons:
                btn_text = btn.text.strip()
                if btn_text == 'SEARCH':
                    search_btn = btn
                    break

            if not search_btn:
                # Fallback: XPath
                candidates = self.driver.find_elements(By.XPATH,
                    "//button[normalize-space(.)='SEARCH']")
                if candidates:
                    search_btn = candidates[0]

            if search_btn:
                # Scroll into view and click
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", search_btn)
                time.sleep(0.5)
                self.driver.execute_script("arguments[0].click();", search_btn)
                print("  ✓ Step 5: Clicked SEARCH button (below filters)")
                time.sleep(5)  # Wait for filtered results to load
                return True
            else:
                print("  ✗ Could not find SEARCH button below filters")
                return False

        except Exception as e:
            print(f"  ✗ Error clicking SEARCH: {e}")
            return False

    def _extract_report_list(self, analyst_name: str, max_results: int) -> List[Dict]:
        """Step 6: Extract report links and dates from search results"""
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        reports = []

        # Find report links (format: /report/<uuid>)
        report_links = soup.find_all('a', href=re.compile(r'/report/'))

        for link in report_links[:max_results]:
            href = link.get('href', '')
            if not href or 'not-entitled' in href:
                continue  # Skip reports we can't access

            # Make URL absolute
            if not href.startswith('http'):
                href = self.CONTENT_URL + href

            # Get title text
            title = link.text.strip()
            if not title:
                title = link.get('title', 'Untitled')

            # Parse publication date from title/surrounding text
            pub_date = self._parse_date(title)

            reports.append({
                'title': title,
                'url': href,
                'analyst': analyst_name,
                'source': 'Jefferies',
                'date': pub_date.strftime('%Y-%m-%d') if pub_date else None,
            })

        return reports

    # ------------------------------------------------------------------
    # Step 7: Navigate to report page and get PDF
    # ------------------------------------------------------------------

    def get_pdf_url(self, report_url: str) -> Optional[str]:
        """
        Step 7: Navigate to report page and extract PDF URL from the iframe.
        The iframe src contains an authenticated /doc/html/ URL; we swap to /doc/pdf/
        to get the actual PDF binary.
        """
        if not self.driver:
            return None

        self.driver.get(report_url)
        time.sleep(8)

        # The report is rendered in an iframe with an authenticated links2 URL
        iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
        for iframe in iframes:
            src = iframe.get_attribute('src') or ''
            if 'links2' in src.lower():
                # iframe serves HTML; swap to /doc/pdf/ for the actual PDF
                pdf_src = src.replace('/doc/html/', '/doc/pdf/')
                print(f"    ✓ PDF URL: {pdf_src[:80]}")
                return pdf_src

        # Fallback: check page source for links2 URLs
        links2_urls = re.findall(r'(https?://[^\s"\']*links2/doc/[^\s"\']*)', self.driver.page_source)
        for url in links2_urls:
            pdf_url = url.replace('/doc/html/', '/doc/pdf/')
            print(f"    ✓ PDF URL (fallback): {pdf_url[:80]}")
            return pdf_url

        print("    ✗ Could not find PDF URL on report page")
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

    def filter_by_date(self, reports: List[Dict], days: int = 5) -> List[Dict]:
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
    # Main orchestration (Step 8: full pipeline)
    # ------------------------------------------------------------------

    def get_reports_by_analysts(self, analyst_names: List[str],
                                max_per_analyst: int = 10,
                                days: int = 5) -> List[Dict]:
        """
        Full pipeline: search analysts → filter by date → skip processed → extract PDFs.

        Args:
            analyst_names: List of analyst names to search
            max_per_analyst: Max reports per analyst to fetch
            days: Only include reports from last N days

        Returns:
            List of reports with extracted content
        """
        all_reports = []

        try:
            # Steps 2-6: Search for each analyst
            for analyst in analyst_names:
                reports = self.search_by_analyst(analyst, max_per_analyst)
                all_reports.extend(reports)

            print(f"\n{'='*50}")
            print(f"Total reports found: {len(all_reports)}")

            # Step 8a: Filter to last 5 days
            recent_reports = self.filter_by_date(all_reports, days=days)

            # Step 8b: Skip previously processed reports
            new_reports = self.report_tracker.filter_unprocessed(recent_reports)
            skipped = len(recent_reports) - len(new_reports)
            if skipped:
                print(f"  ✓ Skipped {skipped} previously processed reports")
            print(f"  → {len(new_reports)} new reports to process")

            if not new_reports:
                print("\n✓ No new reports to process")
                return []

            # Sync browser cookies to requests session for PDF downloads
            self._sync_cookies_from_driver()

            # Steps 6-7: Download and extract PDFs
            processed = []
            for i, report in enumerate(new_reports, 1):
                print(f"\n  [{i}/{len(new_reports)}] {report['title'][:60]}")

                # Step 7: Get PDF URL directly from report UUID
                pdf_url = self.get_pdf_url(report['url'])
                if not pdf_url:
                    continue

                # Download and extract text
                pdf_bytes = self.download_pdf(pdf_url)
                if not pdf_bytes:
                    continue

                text = self.extract_text_from_pdf(pdf_bytes)
                if text:
                    report['content'] = text
                    report['pdf_url'] = pdf_url
                    processed.append(report)
                    self.report_tracker.mark_as_processed(report)

            print(f"\n{'='*50}")
            print(f"✓ Successfully extracted {len(processed)} reports")
            return processed

        finally:
            self.close_driver()


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    from config import TRUSTED_ANALYSTS

    print("\nJefferies Scraper Test\n" + "=" * 50)

    scraper = JefferiesScraper(headless=False)  # headless=False to see browser

    analysts = TRUSTED_ANALYSTS.get('jefferies', [])
    print(f"Trusted analysts: {', '.join(analysts)}")
    print(f"Filter: last 5 days, skip previously processed\n")

    reports = scraper.get_reports_by_analysts(analysts, max_per_analyst=5, days=5)

    for i, report in enumerate(reports, 1):
        print(f"\n--- Report {i} ---")
        print(f"Title:   {report['title'][:80]}")
        print(f"Analyst: {report['analyst']}")
        print(f"Date:    {report.get('date', 'unknown')}")
        print(f"URL:     {report['url']}")
        if report.get('content'):
            print(f"Content: {report['content'][:200]}...")
