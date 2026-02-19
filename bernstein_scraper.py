"""
Bernstein Research Portal Scraper

Workflow:
1. Login with cookies or email/password
2. Click "Research" tab
3. Filter by "Industry" dropdown for TMT sector topics one at a time
4. Extract report links from each filtered view
5. Aggregate and deduplicate across all industry filters
6. For each report: navigate, extract content (text or PDF)

TMT Industry Filters:
- Asia Semiconductors and Equipment & Global Memory
- Asia Tech Hardware
- China Internet
- China Semiconductors
- U.S. Internet
- U.S. IT Hardware
- U.S. Semiconductors
- U.S. SMID-Cap Software
- US Emerging Internet
- US Media & Telecom

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
import config as _cfg

load_dotenv()

# TMT-relevant industry filters from the Bernstein portal
TMT_INDUSTRIES = [
    "Asia Semiconductors and Equipment & Global Memory",
    "Asia Tech Hardware",
    "China Internet",
    "China Semiconductors",
    "U.S. Internet",
    "U.S. IT Hardware",
    "U.S. Semiconductors",
    "U.S. SMID-Cap Software",
    "US Emerging Internet",
    "US Media & Telecom",
]


class BernsteinScraper(BaseScraper):
    """Scraper for Bernstein research portal with Industry dropdown filtering"""

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
        print(f"[{self.PORTAL_NAME}] Initialized Chrome WebDriver")

        # Start on the public homepage (not the app URL — that redirects to Login.aspx)
        self.driver.get("https://www.bernsteinresearch.com")
        time.sleep(3)

        # Dismiss cookie consent on the homepage
        self._accept_cookie_consent()
        time.sleep(1)

        # No cookies — always log in fresh (no 2FA on Bernstein)
        if self.email and self.password:
            return self._perform_login()

        print(f"[{self.PORTAL_NAME}] ✗ No authentication method available")
        return False

    def _accept_cookie_consent(self) -> None:
        """Click 'Allow All' on cookie consent popup if present"""
        try:
            consent_selectors = [
                'button[id*="accept" i]', 'button[class*="accept" i]',
                'button[id*="allow" i]', 'button[class*="allow" i]',
                'a[id*="accept" i]', 'a[class*="accept" i]',
            ]
            for selector in consent_selectors:
                for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    text = (el.text or '').strip().lower()
                    if el.is_displayed() and any(w in text for w in ['allow all', 'accept all', 'allow', 'accept']):
                        self.driver.execute_script("arguments[0].click();", el)
                        print(f"[{self.PORTAL_NAME}] ✓ Dismissed cookie consent ('{el.text.strip()}')")
                        time.sleep(2)
                        return

            # Fallback: scan all buttons/links for consent text
            for el in self.driver.find_elements(By.CSS_SELECTOR, 'button, a'):
                try:
                    text = (el.text or '').strip().lower()
                    if el.is_displayed() and any(p in text for p in ['allow all', 'accept all', 'allow cookies', 'accept cookies']):
                        self.driver.execute_script("arguments[0].click();", el)
                        print(f"[{self.PORTAL_NAME}] ✓ Dismissed cookie consent (fallback: '{el.text.strip()}')")
                        time.sleep(2)
                        return
                except:
                    continue

            # No popup found — that's fine
        except Exception as e:
            print(f"[{self.PORTAL_NAME}]   ⚠ Cookie consent check error: {e}")

    def _perform_login(self) -> bool:
        """Login: expand form on Login.aspx → username + password → click Login"""
        try:
            print(f"[{self.PORTAL_NAME}] Attempting login...")
            print(f"[{self.PORTAL_NAME}]   URL: {self.driver.current_url[:80]}")

            # Step 1: Click the Login button (top-right) with native click to trigger modal JS
            print(f"[{self.PORTAL_NAME}]   On: {self.driver.current_url[:80]}")
            clicked = False
            for el in self.driver.find_elements(By.CSS_SELECTOR, 'a, button, span, li, div'):
                try:
                    text = (el.text or '').strip().lower()
                    if text in ('login', 'log in') and el.is_displayed():
                        el.click()  # native click — required to fire JS modal event
                        print(f"[{self.PORTAL_NAME}]   ✓ Clicked Login button — waiting for modal")
                        clicked = True
                        break
                except:
                    continue
            if not clicked:
                print(f"[{self.PORTAL_NAME}]   ✗ Login button not found")
                # Debug: show all visible elements
                for el in self.driver.find_elements(By.CSS_SELECTOR, 'a, button'):
                    try:
                        t = (el.text or '').strip()
                        if t and el.is_displayed():
                            print(f"    visible: '{t[:50]}'")
                    except:
                        continue
                return False
            time.sleep(4)

            # Verify modal opened by checking if username field is now visible
            modal_open = any(
                el.is_displayed()
                for el in self.driver.find_elements(By.CSS_SELECTOR, 'input[type="text"], input[type="email"]')
            )
            if not modal_open:
                print(f"[{self.PORTAL_NAME}]   ✗ Modal did not open — no visible text input after Login click")
                return False
            print(f"[{self.PORTAL_NAME}]   ✓ Modal opened")

            # Step 2: Fill username — try visible first, fall back to any matching element
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
                print(f"[{self.PORTAL_NAME}]   ✗ Username field not found")
                return False

            try:
                username_field.clear()
                username_field.send_keys(self.email)
            except Exception:
                self.driver.execute_script("arguments[0].value = arguments[1];", username_field, self.email)
            print(f"[{self.PORTAL_NAME}]   Entered username")
            time.sleep(0.5)

            # Step 3: Fill password — same pattern
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
                print(f"[{self.PORTAL_NAME}]   ✗ Password field not found")
                return False

            try:
                password_field.clear()
                password_field.send_keys(self.password)
            except Exception:
                self.driver.execute_script("arguments[0].value = arguments[1];", password_field, self.password)
            print(f"[{self.PORTAL_NAME}]   Entered password")
            time.sleep(0.5)

            # Step 4: Click Login submit — native click first, JS fallback
            from selenium.webdriver.common.keys import Keys
            submit_clicked = False
            for selector in [
                'input[name="ctl00$BRContentPlaceHolder$btnLogin"]',
                'input[type="submit"]', 'button[type="submit"]',
            ]:
                for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    try:
                        el.click()
                        print(f"[{self.PORTAL_NAME}]   ✓ Clicked Login submit (native)")
                        submit_clicked = True
                        break
                    except Exception:
                        try:
                            self.driver.execute_script("arguments[0].click();", el)
                            print(f"[{self.PORTAL_NAME}]   ✓ Clicked Login submit (JS)")
                            submit_clicked = True
                            break
                        except:
                            continue
                if submit_clicked:
                    break
            if not submit_clicked:
                password_field.send_keys(Keys.RETURN)
                print(f"[{self.PORTAL_NAME}]   Pressed Enter to submit")

            time.sleep(6)

            # Login success = landed on Home.aspx, not back on Login.aspx
            current = self.driver.current_url.lower()
            if 'login' not in current and 'home' in current:
                print(f"[{self.PORTAL_NAME}] ✓ Login successful — on {self.driver.current_url[:60]}")
                return True

            # Try navigating to app URL as fallback check
            self.driver.get(self.CONTENT_URL)
            time.sleep(5)
            if 'login' not in self.driver.current_url.lower():
                print(f"[{self.PORTAL_NAME}] ✓ Login successful")
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Login failed — URL: {self.driver.current_url[:80]}")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Login error: {e}")
            return False

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _check_authentication(self) -> bool:
        try:
            url = self.driver.current_url.lower()

            # On Home.aspx and NOT on login page = authenticated
            if 'home' in url and 'login' not in url and 'bernsteinresearch' in url:
                print(f"[{self.PORTAL_NAME}] ✓ Auth check: on Home.aspx — valid session")
                return True

            # Definitive negative: on Login.aspx or visible password/login button
            if 'login' in url:
                return False
            if any(f.is_displayed() for f in self.driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')):
                return False

            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Auth check error: {e}")
            return False

    # ------------------------------------------------------------------
    # Navigate to Research tab
    # ------------------------------------------------------------------

    def _navigate_to_notifications(self) -> bool:
        """Click the Research nav tab and wait for the Industry filter to confirm page loaded."""
        try:
            time.sleep(2)

            # Dismiss cookie consent if it's blocking the nav bar
            self._accept_cookie_consent()
            time.sleep(1)

            # Find RESEARCH in the nav bar using specific nav selectors
            clicked = False
            nav_selectors = [
                'nav a', 'header a', '[role="navigation"] a',
                'ul li a', '.nav a', '.navbar a', '.menu a',
            ]
            research_el = None
            for selector in nav_selectors:
                for el in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    try:
                        if (el.text or '').strip().upper() == 'RESEARCH':
                            research_el = el
                            break
                    except Exception:
                        continue
                if research_el:
                    break

            if research_el:
                try:
                    research_el.click()
                    clicked = True
                except Exception:
                    # Fallback: JS click
                    self.driver.execute_script("arguments[0].click();", research_el)
                    clicked = True
                print(f"[{self.PORTAL_NAME}] ✓ Clicked Research tab")
            else:
                # Last resort: JS querySelector
                self.driver.execute_script("""
                    var links = document.querySelectorAll('a');
                    for (var i = 0; i < links.length; i++) {
                        if (links[i].textContent.trim().toUpperCase() === 'RESEARCH') {
                            links[i].click();
                            break;
                        }
                    }
                """)
                clicked = True
                print(f"[{self.PORTAL_NAME}] ✓ Clicked Research tab (JS querySelector)")

            if not clicked:
                print(f"[{self.PORTAL_NAME}] ✗ Research tab not found")
                return False

            # Wait until the Industry filter <select> appears — confirms Research page loaded
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'select'))
                )
                print(f"[{self.PORTAL_NAME}] ✓ Research filter page loaded (select found)")
                return True
            except Exception:
                # Fallback: check for the filter area by text
                if 'industry' in self.driver.page_source.lower():
                    print(f"[{self.PORTAL_NAME}] ✓ Research filter page loaded (industry text found)")
                    return True

            print(f"[{self.PORTAL_NAME}] ✗ Research page did not load (no filter elements)")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Error navigating to Research: {e}")
            return False

    # ------------------------------------------------------------------
    # Main pipeline override (click-based, not URL-based)
    # ------------------------------------------------------------------

    def get_followed_reports(self, max_reports: int = 20, days: int = 7, result_out: Dict = None) -> Dict:
        """
        Bernstein-specific override: the DataTables rows use JS onclick, not real hrefs.
        We click each link directly, extract content, then navigate back and re-apply filter.
        """
        failures = []

        print(f"\n{'='*50}")
        print(f"[{self.PORTAL_NAME}] Fetching reports from notifications")
        print(f"{'='*50}")

        try:
            if not self._init_driver():
                return self._handle_auth_failure()

            self.driver.get(self.CONTENT_URL)
            time.sleep(3)

            if not self._navigate_to_notifications():
                failures.append("Could not access Research tab")
                return {'reports': [], 'failures': failures}

            today = datetime.now().strftime('%Y-%m-%d')
            processed = []
            seen_titles = set()
            self._sync_cookies_from_driver()

            # Give the Research page SPA time to fully render before first filter
            time.sleep(5)

            for industry_idx, industry in enumerate(TMT_INDUSTRIES):
                print(f"\n[{self.PORTAL_NAME}]   Industry: {industry}")

                # Periodic browser restart between industries to clear memory
                # (Bernstein crashes after PDF extraction accumulates Chrome state)
                if industry_idx > 0 and industry_idx % _cfg.BROWSER_RESTART_AFTER_DOWNLOADS == 0:
                    if not self._restart_browser():
                        failures.append("Re-auth failed after browser restart")
                        break
                    self.driver.get(self.CONTENT_URL)
                    time.sleep(3)
                    if not self._navigate_to_notifications():
                        failures.append("Could not re-navigate to Research after restart")
                        break
                    time.sleep(3)

                if not self._select_industry_filter(industry):
                    failures.append(f"Could not select filter: {industry}")
                    continue

                # Wait for the documents table to render (AJAX loads after filter)
                # Look for the "N documents" count text as the trigger
                try:
                    WebDriverWait(self.driver, 15).until(
                        lambda d: any(
                            'document' in (el.text or '').lower()
                            for el in d.find_elements(By.XPATH, '//*[contains(text(),"document")]')
                        )
                    )
                    time.sleep(2)  # let table fully render after count appears
                except Exception:
                    time.sleep(6)

                # Collect today's report metadata from the table (title + link element)
                metas = self._collect_today_report_metas(today)
                print(f"[{self.PORTAL_NAME}]     {len(metas)} today's reports found")

                for meta in metas:
                    # Fix C: detect browser crash — stop all loops, return partial
                    if not self._is_browser_alive():
                        print(f"[{self.PORTAL_NAME}] ✗ Browser crashed — returning {len(processed)} partial results")
                        failures.append(f"Browser crashed during {industry}")
                        return {'reports': processed, 'failures': failures}

                    if meta['title'] in seen_titles:
                        continue
                    if len(processed) >= max_reports:
                        break

                    print(f"\n  [{len(processed)+1}] {meta['title'][:60]}")
                    try:
                        # Re-find the link fresh each attempt — DataTable re-renders can
                        # stale element refs between find and click
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

                        if not link_el:
                            failures.append(f"Link not found: {meta['title'][:40]}")
                            continue
                        if not clicked:
                            failures.append(f"Link stale after 3 attempts: {meta['title'][:40]}")
                            print(f"    ✗ Stale element — skipping")
                            continue

                        time.sleep(5)

                        report = {
                            'title': meta['title'],
                            'url': self.driver.current_url,
                            'analyst': meta.get('analyst'),
                            'source': 'Bernstein',
                            'date': today,
                            'industry': industry,
                        }

                        # Check deduplication
                        if not self.report_tracker.filter_unprocessed([report]):
                            print(f"    Already processed — skipping")
                            seen_titles.add(meta['title'])
                            self.driver.back()
                            time.sleep(3)
                            self._select_industry_filter(industry)
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
                            continue

                        content = self._extract_report_content(report)
                        if content:
                            report['content'] = content
                            processed.append(report)
                            # Fix A: live-write so partial results survive a timeout
                            if result_out is not None:
                                result_out['reports'].append(report)
                            self.report_tracker.mark_as_processed(report)
                            seen_titles.add(meta['title'])
                            print(f"    ✓ Extracted {len(content)} chars")
                        else:
                            failures.append(f"No content: {meta['title'][:40]}")

                        # Back to filtered list — re-apply filter so table reloads fresh
                        self.driver.back()
                        time.sleep(3)
                        self._select_industry_filter(industry)
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

                    except Exception as e:
                        failures.append(f"Error: {meta['title'][:40]}: {e}")
                        print(f"    ✗ {e}")
                        continue

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

    def _collect_today_report_metas(self, today: str) -> list:
        """Scan the current filtered table for today's reports. Returns title+date only (no element refs)."""
        metas = []
        rows = self._find_reports_table_rows()

        for row in rows:
            try:
                row_text = row.text
                pub_date = self._extract_date_from_text(row_text)
                date_str = pub_date.strftime('%Y-%m-%d') if pub_date else None
                if date_str != today:
                    continue

                # Get title from longest link text in the row
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
                    'date': date_str,
                })
            except Exception:
                continue

        return metas

    def _find_link_by_title(self, title: str):
        """Re-fetch the link element for a report by title from the current table (avoids stale refs)."""
        rows = self._find_reports_table_rows()
        for row in rows:
            try:
                for lnk in row.find_elements(By.CSS_SELECTOR, 'a'):
                    if title.lower()[:30] in (lnk.text or '').strip().lower():
                        return lnk
            except Exception:
                continue
        return None

    # Stubs required by BaseScraper abstract interface
    def _extract_notifications(self) -> List[Dict]:
        return []  # Not used — get_followed_reports is fully overridden

    def _find_reports_table_rows(self) -> list:
        """
        Find the main research results DataTable by locating the table whose
        <thead> contains both 'Date' and 'Title' columns. Returns only <tbody> rows
        (never header rows). All searches are scoped to the confirmed table element.

        DataTables note: the library clones header rows into separate floating
        tables — we must check <thead> specifically, not the first <tr>.
        """
        # Confirm table is not inside an iframe; switch context if needed
        in_iframe = False
        iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
        for iframe in iframes:
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

        all_tables = self.driver.find_elements(By.CSS_SELECTOR, 'table')

        for table in all_tables:
            try:
                # Check <thead> cells first (DataTables standard), then first <tr>
                header_cells = table.find_elements(By.CSS_SELECTOR, 'thead th, thead td')
                if not header_cells:
                    header_cells = table.find_elements(By.CSS_SELECTOR, 'tr:first-child th, tr:first-child td')

                # Try .text first, then textContent attribute (for child-rendered text)
                col_texts = []
                for c in header_cells:
                    t = (c.text or '').strip().lower()
                    if not t:
                        t = (c.get_attribute('textContent') or '').strip().lower()
                    if not t:
                        t = (self.driver.execute_script("return arguments[0].innerText;", c) or '').strip().lower()
                    col_texts.append(t)

                has_date  = any('date'  in t for t in col_texts)
                has_title = any('title' in t for t in col_texts)

                if not (has_date and has_title):
                    continue

                # Get tbody data rows only (DataTables clones the header into a floating
                # table with no tbody — skip those by requiring at least 1 row)
                tbody_rows = table.find_elements(By.CSS_SELECTOR, 'tbody tr')
                if not tbody_rows:
                    continue  # DataTables clone header — no data rows

                print(f"[{self.PORTAL_NAME}]     ✓ Reports table found ({len(tbody_rows)} rows)")
                return tbody_rows

            except Exception:
                continue

        print(f"[{self.PORTAL_NAME}]     ✗ No table with Date+Title headers found")
        return []

    def _extract_date_from_text(self, text: str) -> Optional[datetime]:
        """Extract a date from arbitrary row text."""
        date_patterns = [
            r'(\d{1,2}-[A-Za-z]{3}-\d{4})',           # 18-Feb-2026  ← Bernstein format
            r'(\d{1,2}/\d{1,2}/\d{4})',                # 02/18/2026
            r'(\d{4}-\d{2}-\d{2})',                    # 2026-02-18
            r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})',
            r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text, re.I)
            if match:
                try:
                    return dateparser.parse(match.group(1))
                except Exception:
                    pass
        return None

    def _extract_analyst_name_from_text(self, text: str) -> Optional[str]:
        """Extract analyst name from row text."""
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

    def _select_industry_filter(self, industry_name: str) -> bool:
        """Select a specific industry from the Industry dropdown"""
        try:
            # Find the Industry dropdown
            dropdown_selectors = [
                'select[name*="industry" i]',
                'select[id*="industry" i]',
                'select[class*="industry" i]',
                '[data-filter="industry"]',
            ]

            # Try <select> element first
            for selector in dropdown_selectors:
                selects = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for select_el in selects:
                    if select_el.is_displayed():
                        from selenium.webdriver.support.ui import Select
                        select = Select(select_el)
                        for option in select.options:
                            if industry_name.lower() in option.text.lower():
                                select.select_by_visible_text(option.text)
                                return True

            # Try custom dropdown (div-based)
            all_clickable = self.driver.find_elements(
                By.CSS_SELECTOR, 'button, div[class*="dropdown"], div[class*="select"], span[class*="dropdown"]')

            for el in all_clickable:
                try:
                    text = (el.text or '').strip().lower()
                    aria = (el.get_attribute('aria-label') or '').lower()
                    placeholder = (el.get_attribute('placeholder') or '').lower()

                    if 'industry' in text or 'industry' in aria or 'industry' in placeholder:
                        if el.is_displayed():
                            self.driver.execute_script("arguments[0].click();", el)
                            time.sleep(1)
                            return self._click_dropdown_option(industry_name)
                except:
                    continue

            # Fallback: look for any dropdown/filter that contains industry names
            all_buttons = self.driver.find_elements(By.CSS_SELECTOR,
                'button, [role="listbox"], [role="combobox"], .dropdown-toggle')
            for btn in all_buttons:
                try:
                    text = (btn.text or '').strip()
                    if any(ind.lower() in text.lower() for ind in TMT_INDUSTRIES[:3]):
                        self.driver.execute_script("arguments[0].click();", btn)
                        time.sleep(1)
                        return self._click_dropdown_option(industry_name)
                except:
                    continue

            # Debug: show current URL and all select elements
            print(f"[{self.PORTAL_NAME}]     ✗ No Industry dropdown found. URL: {self.driver.current_url[:80]}")
            all_selects = self.driver.find_elements(By.CSS_SELECTOR, 'select')
            print(f"[{self.PORTAL_NAME}]     {len(all_selects)} <select> elements on page:")
            for si, sel in enumerate(all_selects[:8]):
                opts = [o.text for o in sel.find_elements(By.TAG_NAME, 'option')[:4]]
                print(f"      select[{si}] id='{sel.get_attribute('id')}' name='{sel.get_attribute('name')}' visible={sel.is_displayed()} opts={opts}")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}]     Error selecting industry: {e}")
            return False

    def _click_dropdown_option(self, option_text: str) -> bool:
        """Click a specific option in an open dropdown"""
        try:
            time.sleep(1)
            # Look for option elements
            option_selectors = [
                'li', 'option', '[role="option"]', 'div[class*="option"]',
                'a[class*="dropdown-item"]', 'span[class*="option"]',
            ]

            for selector in option_selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    try:
                        text = (el.text or '').strip()
                        if option_text.lower() in text.lower() and el.is_displayed():
                            self.driver.execute_script("arguments[0].click();", el)
                            time.sleep(2)
                            return True
                    except:
                        continue

            return False
        except:
            return False


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
            # Look for PDF links/buttons
            pdf_selectors = [
                'a[href*=".pdf"]',
                '[aria-label*="PDF"]',
                '[title*="PDF"]',
                'a[class*="pdf"]',
                'a[class*="download"]',
                'button[class*="pdf"]',
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

    print("\nBernstein Research Scraper Test")
    print("=" * 50)

    email = os.getenv('BERNSTEIN_EMAIL')
    password = os.getenv('BERNSTEIN_PASSWORD')

    if not email or not password:
        print("✗ Missing BERNSTEIN_EMAIL or BERNSTEIN_PASSWORD in .env file")
        sys.exit(1)

    print(f"✓ Found credentials for: {email}")
    print(f"✓ TMT industries to scan: {len(TMT_INDUSTRIES)}")
    for ind in TMT_INDUSTRIES:
        print(f"    - {ind}")

    print("\n[1/2] Initializing scraper...")
    scraper = BernsteinScraper(headless=False)

    print("\n[2/2] Testing full pipeline...")
    result = scraper.get_followed_reports(max_reports=20, days=7)

    if result.get('auth_required'):
        print("\n⚠ Authentication required - check credentials")
        sys.exit(1)

    reports = result.get('reports', [])
    failures = result.get('failures', [])

    print(f"\n--- Results ---")
    print(f"Reports extracted: {len(reports)}")
    print(f"Failures: {len(failures)}")

    # Group by industry
    by_industry = {}
    for r in reports:
        ind = r.get('industry', 'unknown')
        by_industry.setdefault(ind, []).append(r)

    for ind, reps in by_industry.items():
        print(f"\n  {ind}: {len(reps)} reports")
        for r in reps[:2]:
            print(f"    - {r['title'][:60]}")

    if failures:
        print(f"\n--- Failures ---")
        for f in failures[:5]:
            print(f"  - {f}")

    print("\n✓ Bernstein scraper test complete")
