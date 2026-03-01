"""
Bernstein Research Portal Scraper

Workflow:
1. Login with email/password (modal on homepage)
2. Navigate directly to "Mid-Cap Latest Research" feed URL
3. Scrape today's reports from the DataTable
4. For each report: click link → extract PDF/text → navigate back
5. Filter to last N days only, skip previously processed

Replaces the old per-industry filter loop (10 industries × table scan → timeout).
The feed URL shows ~5 daily publications across all TMT sectors in one view.

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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from dateutil import parser as dateparser

load_dotenv()

# Direct URL for the "Mid-Cap Latest Research" feed (all sectors, no filter needed)
_RESEARCH_URL = "https://www.bernsteinresearch.com/brweb/DisplayGroup.aspx?cid=50752&secid=all_sectors#/"


class BernsteinScraper(BaseScraper):
    """Scraper for Bernstein — navigates directly to the research feed URL."""

    PORTAL_NAME = "bernstein"
    CONTENT_URL = "https://www.bernsteinresearch.com/brweb/Home.aspx#/"
    PDF_STORAGE_DIR = "data/reports/bernstein"

    def __init__(self, headless: bool = True):
        super().__init__(headless=headless)
        self.email = os.getenv('BERNSTEIN_EMAIL')
        self.password = os.getenv('BERNSTEIN_PASSWORD')

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

        self.driver.get("https://www.bernsteinresearch.com")
        time.sleep(3)
        self._accept_cookie_consent()

        if self.email and self.password:
            return self._perform_login()

        print(f"[{self.PORTAL_NAME}] ✗ No credentials available")
        return False

    def _accept_cookie_consent(self) -> None:
        try:
            for el in self.driver.find_elements(By.CSS_SELECTOR, 'button, a'):
                text = (el.text or '').strip().lower()
                if el.is_displayed() and any(p in text for p in ['allow all', 'accept all', 'allow cookies', 'accept cookies']):
                    self.driver.execute_script("arguments[0].click();", el)
                    print(f"[{self.PORTAL_NAME}] ✓ Dismissed cookie consent")
                    time.sleep(2)
                    return
        except Exception:
            pass

    def _perform_login(self) -> bool:
        """Click Login button → fill modal → submit. Skips if already authenticated."""
        try:
            # If already logged in (e.g. valid cookies from previous run), skip
            page = self.driver.page_source.lower()
            if ('logout' in page or 'sign out' in page or 'my account' in page
                    or 'welcome' in page) and 'login' not in self.driver.current_url.lower():
                print(f"[{self.PORTAL_NAME}] ✓ Already authenticated — skipping login")
                return True

            print(f"[{self.PORTAL_NAME}] Attempting login...")

            # Click Login button (fires JS modal)
            clicked = False
            for el in self.driver.find_elements(By.CSS_SELECTOR, 'a, button, span, li, div'):
                try:
                    if (el.text or '').strip().lower() in ('login', 'log in') and el.is_displayed():
                        el.click()
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                print(f"[{self.PORTAL_NAME}] ✗ Login button not found")
                return False
            time.sleep(4)

            # Username field
            username_field = None
            for check_visible in (True, False):
                for selector in [
                    'input[name="ctl00$BRContentPlaceHolder$txtUserName"]',
                    'input[type="text"]', 'input[type="email"]',
                ]:
                    for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
                        if not check_visible or el.is_displayed():
                            username_field = el
                            break
                    if username_field:
                        break
                if username_field:
                    break
            if not username_field:
                print(f"[{self.PORTAL_NAME}] ✗ Username field not found")
                return False
            try:
                username_field.clear()
                username_field.send_keys(self.email)
            except Exception:
                self.driver.execute_script("arguments[0].value = arguments[1];", username_field, self.email)
            print(f"[{self.PORTAL_NAME}]   Entered username")

            # Password field
            password_field = None
            for check_visible in (True, False):
                for selector in [
                    'input[name="ctl00$BRContentPlaceHolder$txtPassword"]',
                    'input[type="password"]',
                ]:
                    for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
                        if not check_visible or el.is_displayed():
                            password_field = el
                            break
                    if password_field:
                        break
                if password_field:
                    break
            if not password_field:
                print(f"[{self.PORTAL_NAME}] ✗ Password field not found")
                return False
            try:
                password_field.clear()
                password_field.send_keys(self.password)
            except Exception:
                self.driver.execute_script("arguments[0].value = arguments[1];", password_field, self.password)
            print(f"[{self.PORTAL_NAME}]   Entered password")

            # Submit
            from selenium.webdriver.common.keys import Keys
            submitted = False
            for selector in [
                'input[name="ctl00$BRContentPlaceHolder$btnLogin"]',
                'input[type="submit"]', 'button[type="submit"]',
            ]:
                for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    try:
                        el.click()
                        submitted = True
                        break
                    except Exception:
                        try:
                            self.driver.execute_script("arguments[0].click();", el)
                            submitted = True
                            break
                        except Exception:
                            continue
                if submitted:
                    break
            if not submitted:
                password_field.send_keys(Keys.RETURN)
            time.sleep(6)

            current = self.driver.current_url.lower()
            if 'login' not in current and 'home' in current:
                print(f"[{self.PORTAL_NAME}] ✓ Login successful")
                return True
            self.driver.get(self.CONTENT_URL)
            time.sleep(5)
            if 'login' not in self.driver.current_url.lower():
                print(f"[{self.PORTAL_NAME}] ✓ Login successful")
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Login failed — {self.driver.current_url[:80]}")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Login error: {e}")
            return False

    # ------------------------------------------------------------------
    # Authentication check
    # ------------------------------------------------------------------

    def _check_authentication(self) -> bool:
        try:
            url = self.driver.current_url.lower()
            if 'login' in url:
                return False
            if any(f.is_displayed() for f in self.driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')):
                return False
            # Positive: page contains logout/account links (only present when logged in)
            page = self.driver.page_source.lower()
            if any(x in page for x in ['logout', 'sign out', 'my account', 'home.aspx', 'displaygroup']):
                return True
            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Navigate to research feed
    # ------------------------------------------------------------------

    def _navigate_to_notifications(self) -> bool:
        """Navigate directly to the Mid-Cap Latest Research feed URL."""
        print(f"[{self.PORTAL_NAME}] Navigating to research feed...")
        try:
            self.driver.get(_RESEARCH_URL)
            # Wait for the DataTable to load (look for "document" count text or table rows)
            try:
                WebDriverWait(self.driver, 20).until(
                    lambda d: any(
                        'document' in (el.text or '').lower()
                        for el in d.find_elements(By.XPATH, '//*[contains(text(),"document")]')
                    )
                )
                time.sleep(2)
            except Exception:
                time.sleep(8)  # fallback wait

            if 'login' in self.driver.current_url.lower():
                print(f"[{self.PORTAL_NAME}] ✗ Redirected to login — session expired")
                return False

            print(f"[{self.PORTAL_NAME}] ✓ Research feed loaded")
            return True
        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Feed navigation error: {e}")
            return False

    # Stub required by BaseScraper abstract interface (not used — get_followed_reports overridden)
    def _extract_notifications(self) -> List[Dict]:
        return []

    # ------------------------------------------------------------------
    # Main pipeline override
    # ------------------------------------------------------------------

    def get_followed_reports(self, max_reports: int = 20, days: int = 2, result_out: Dict = None) -> Dict:
        """
        Navigate to feed URL once → scrape DataTable → click each report.
        No industry filter loop needed — feed shows all recent TMT publications.
        """
        failures = []
        processed = []

        print(f"\n{'='*50}")
        print(f"[{self.PORTAL_NAME}] Fetching reports from feed")
        print(f"{'='*50}")

        try:
            if not self._init_driver():
                return self._handle_auth_failure()

            if not self._navigate_to_notifications():
                failures.append("Could not load research feed")
                return {'reports': [], 'failures': failures}

            self._sync_cookies_from_driver()

            cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            seen_meta_titles = set()
            metas = []

            # Two passes: Technology + Media & Telecom (single-select dropdown)
            for sector_kw in ['Technology', 'Media']:
                self._apply_sector_filter([sector_kw])
                # Wait for table to reload after filter change
                try:
                    WebDriverWait(self.driver, 10).until(
                        lambda d: any(
                            'document' in (el.text or '').lower()
                            for el in d.find_elements(By.XPATH, '//*[contains(text(),"document")]')
                        )
                    )
                    time.sleep(2)
                except Exception:
                    time.sleep(4)
                for m in self._collect_recent_report_metas(cutoff, days):
                    if m['title'] not in seen_meta_titles:
                        seen_meta_titles.add(m['title'])
                        metas.append(m)

            print(f"[{self.PORTAL_NAME}] {len(metas)} TMT reports in date window (last {days}d)")

            seen_titles = set()

            for meta in metas:
                if not self._is_browser_alive():
                    print(f"[{self.PORTAL_NAME}] ✗ Browser crashed — returning {len(processed)} partial results")
                    failures.append("Browser crashed")
                    break

                if meta['title'] in seen_titles or len(processed) >= max_reports:
                    continue

                print(f"\n  [{len(processed)+1}] {meta['title'][:60]}")

                # Check deduplication before clicking
                candidate = {
                    'title': meta['title'],
                    'url': _RESEARCH_URL,
                    'source': 'Bernstein',
                    'date': meta['date'],
                }
                if not self.report_tracker.filter_unprocessed([candidate]):
                    print(f"    Already processed — skipping")
                    seen_titles.add(meta['title'])
                    continue

                # Click the report link (DataTable uses JS onclick, not real hrefs)
                clicked = False
                for attempt in range(3):
                    link_el = self._find_link_by_title(meta['title'])
                    if not link_el:
                        break
                    try:
                        self.driver.execute_script("arguments[0].click();", link_el)
                        clicked = True
                        break
                    except Exception:
                        time.sleep(1)

                if not clicked:
                    failures.append(f"Link not found/stale: {meta['title'][:40]}")
                    continue

                time.sleep(5)

                report = {
                    'title': meta['title'],
                    'url': self.driver.current_url,
                    'analyst': meta.get('analyst'),
                    'source': 'Bernstein',
                    'date': meta['date'],
                }

                content = self._extract_report_content(report)
                if content:
                    report['content'] = content
                    processed.append(report)
                    if result_out is not None:
                        result_out['reports'].append(report)
                    self.report_tracker.mark_as_processed(report)
                    seen_titles.add(meta['title'])
                    print(f"    ✓ Extracted {len(content)} chars")
                else:
                    failures.append(f"No content: {meta['title'][:40]}")

                # Back to feed — no filter to re-apply
                self.driver.back()
                time.sleep(4)

            print(f"\n{'='*50}")
            print(f"[{self.PORTAL_NAME}] Successfully extracted {len(processed)} reports")
            return {'reports': processed, 'failures': failures}

        except Exception as e:
            failures.append(f"Scraper error: {e}")
            print(f"[{self.PORTAL_NAME}] Scraper error: {e}")
            return {'reports': processed, 'failures': failures}

        finally:
            self.close_driver()

    # ------------------------------------------------------------------
    # Table helpers
    # ------------------------------------------------------------------

    def _apply_sector_filter(self, sector_keywords: list) -> None:
        """
        Select TMT sectors in the sectorDD dropdown (ctl00$BRContentPlaceHolder$sectorDD).
        sector_keywords: list of substrings to match against option text (case-insensitive).
        Switches into iframe first since the table/filters live there.
        """
        from selenium.webdriver.support.ui import Select

        # Switch into iframe (Bernstein renders filters + table inside an iframe)
        switched = False
        for iframe in self.driver.find_elements(By.TAG_NAME, 'iframe'):
            try:
                self.driver.switch_to.frame(iframe)
                if self.driver.find_elements(By.CSS_SELECTOR, 'select'):
                    switched = True
                    break
                self.driver.switch_to.default_content()
            except Exception:
                self.driver.switch_to.default_content()
        if not switched:
            self.driver.switch_to.default_content()

        try:
            sel_el = self.driver.find_element(By.CSS_SELECTOR,
                'select[name$="sectorDD"], select[id$="sectorDD"]')
            s = Select(sel_el)

            # Print available options on first use to confirm labels
            options = [o.text for o in s.options]
            print(f"[{self.PORTAL_NAME}]   Sector filter options: {options}")

            # Select all options whose text matches any keyword
            matched = []
            for opt in s.options:
                if any(kw.lower() in opt.text.lower() for kw in sector_keywords):
                    matched.append(opt.text)

            if not matched:
                print(f"[{self.PORTAL_NAME}]   ⚠ No matching sectors found — using unfiltered feed")
                self.driver.switch_to.default_content()
                return

            # Select first match (single-select dropdown triggers table reload)
            s.select_by_visible_text(matched[0])
            time.sleep(3)
            print(f"[{self.PORTAL_NAME}]   ✓ Sector filter applied: {matched[0]}")

            # If multi-select and more than one match, log the remainder
            if len(matched) > 1:
                print(f"[{self.PORTAL_NAME}]   ℹ Additional sectors not selectable in single-select: {matched[1:]}")

        except Exception as e:
            print(f"[{self.PORTAL_NAME}]   ⚠ Sector filter error: {e}")
        finally:
            self.driver.switch_to.default_content()

    def _collect_recent_report_metas(self, cutoff: datetime, days: int) -> list:
        """Collect report metadata from the DataTable for the last N days."""
        metas = []
        rows = self._find_reports_table_rows()

        for row in rows:
            try:
                row_text = row.text
                pub_date = self._extract_date_from_text(row_text)
                if not pub_date:
                    continue

                # Keep reports from cutoff (today midnight) back N days
                days_old = (cutoff - pub_date.replace(hour=0, minute=0, second=0, microsecond=0)).days
                if days_old < 0 or days_old >= days:
                    continue

                title = ''
                for lnk in row.find_elements(By.CSS_SELECTOR, 'a'):
                    t = lnk.text.strip()
                    if len(t) > len(title):
                        title = t
                if not title or len(title) < 5:
                    continue

                metas.append({
                    'title': title[:200],
                    'analyst': self._extract_analyst_name_from_text(row_text),
                    'date': pub_date.strftime('%Y-%m-%d'),
                })
            except Exception:
                continue

        return metas

    def _find_link_by_title(self, title: str):
        """Re-fetch the link element by title to avoid stale refs after navigation."""
        for row in self._find_reports_table_rows():
            try:
                for lnk in row.find_elements(By.CSS_SELECTOR, 'a'):
                    if title.lower()[:30] in (lnk.text or '').strip().lower():
                        return lnk
            except Exception:
                continue
        return None

    def _find_reports_table_rows(self) -> list:
        """
        Find the research DataTable by <thead> containing 'Date' + 'Title' columns.
        Returns only <tbody> rows. Checks iframes first (Bernstein uses ASP.NET frames).
        """
        in_iframe = False
        for iframe in self.driver.find_elements(By.TAG_NAME, 'iframe'):
            try:
                self.driver.switch_to.frame(iframe)
                if self.driver.find_elements(By.CSS_SELECTOR, 'table'):
                    in_iframe = True
                    break
                self.driver.switch_to.default_content()
            except Exception:
                self.driver.switch_to.default_content()
        if not in_iframe:
            self.driver.switch_to.default_content()

        for table in self.driver.find_elements(By.CSS_SELECTOR, 'table'):
            try:
                header_cells = table.find_elements(By.CSS_SELECTOR, 'thead th, thead td')
                if not header_cells:
                    header_cells = table.find_elements(By.CSS_SELECTOR, 'tr:first-child th, tr:first-child td')

                col_texts = []
                for c in header_cells:
                    t = (c.text or '').strip().lower()
                    if not t:
                        t = self.driver.execute_script("return arguments[0].innerText;", c).strip().lower()
                    col_texts.append(t)

                if not (any('date' in t for t in col_texts) and any('title' in t for t in col_texts)):
                    continue

                tbody_rows = table.find_elements(By.CSS_SELECTOR, 'tbody tr')
                if not tbody_rows:
                    continue

                print(f"[{self.PORTAL_NAME}]   Table found ({len(tbody_rows)} rows)")
                return tbody_rows
            except Exception:
                continue

        print(f"[{self.PORTAL_NAME}]   ✗ No table with Date+Title headers found")
        return []

    def _extract_date_from_text(self, text: str) -> Optional[datetime]:
        for pattern in [
            r'(\d{1,2}-[A-Za-z]{3}-\d{4})',           # 18-Feb-2026 (Bernstein format)
            r'(\d{1,2}/\d{1,2}/\d{4})',
            r'(\d{4}-\d{2}-\d{2})',
            r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})',
            r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})',
        ]:
            m = re.search(pattern, text, re.I)
            if m:
                try:
                    return dateparser.parse(m.group(1))
                except Exception:
                    pass
        return None

    def _extract_analyst_name_from_text(self, text: str) -> Optional[str]:
        for pattern in [
            r'by\s+([A-Z][a-z]+\s+[A-Z][a-z]+)',
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s*[-–]',
            r'Author:\s*([A-Z][a-z]+\s+[A-Z][a-z]+)',
        ]:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        return None

    # ------------------------------------------------------------------
    # Report content extraction
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

        text = self._extract_text_from_page()
        if text and len(text) > 500:
            return text
        return None

    def _get_pdf_url(self) -> Optional[str]:
        try:
            for selector in ['a[href*=".pdf"]', '[aria-label*="PDF"]', '[title*="PDF"]',
                             'a[class*="pdf"]', 'a[class*="download"]', 'button[class*="pdf"]']:
                for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    if el.is_displayed():
                        href = el.get_attribute('href')
                        if href and '.pdf' in href.lower():
                            print(f"    ✓ Found PDF link")
                            return href
                        self.driver.execute_script("arguments[0].click();", el)
                        time.sleep(2)

            pdf_urls = re.findall(r'(https?://[^\s"\']*\.pdf[^\s"\']*)', self.driver.page_source)
            if pdf_urls:
                return pdf_urls[0]

            for iframe in self.driver.find_elements(By.TAG_NAME, 'iframe'):
                src = iframe.get_attribute('src') or ''
                if '.pdf' in src.lower():
                    return src

            return None
        except Exception as e:
            print(f"    ⚠ PDF URL error: {e}")
            return None

    def _extract_text_from_page(self) -> Optional[str]:
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            for el in soup(['script', 'style', 'nav', 'header', 'footer']):
                el.decompose()
            for selector in ['.report-content', '.article-content', 'article', 'main', '[role="main"]']:
                content = soup.select_one(selector)
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


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("\nBernstein Research Scraper Test")
    print("=" * 50)

    if not os.getenv('BERNSTEIN_EMAIL') or not os.getenv('BERNSTEIN_PASSWORD'):
        print("✗ Missing BERNSTEIN_EMAIL or BERNSTEIN_PASSWORD in .env")
        sys.exit(1)

    print(f"✓ Credentials: {os.getenv('BERNSTEIN_EMAIL')}")
    print(f"✓ Feed URL: {_RESEARCH_URL}")

    scraper = BernsteinScraper(headless=False)
    result = scraper.get_followed_reports(max_reports=20, days=2)

    if result.get('auth_required'):
        print("\n⚠ Authentication required")
        sys.exit(1)

    reports = result.get('reports', [])
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

    print("\n✓ Bernstein scraper test complete")
