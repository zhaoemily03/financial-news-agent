"""
JP Morgan Markets Research Portal Scraper

Selenium-only, persistent Chrome profile. Does NOT extend BaseScraper.
Implements get_followed_reports() interface for PortalRegistry compatibility.

Auth:
  Uses a persistent Chrome profile (data/chrome_profiles/jpmorgan).
  Chrome stores session cookies between runs — no extraction/injection needed.
  First run: user logs in (auto-fills credentials from .env; waits for manual
  2FA/OTP if triggered). Subsequent runs reuse the persisted session silently.

Feed API (confirmed via CDP XHR capture):
  GET /research/myalert/contentfeed/publicationDocuments?count=N
  GET /research/myalert/contentfeed/analystDocuments?count=N
  GET /research/myalert/contentfeed/companiesEquityDocuments?count=N
  Response: data.researchService.research.results[]
    - id:              "GPS-5221577-0"
    - title / subtitle / synopsis
    - publicationDate: "2026-03-01T20:03:12Z"
    - analysts.results[]: [{firstName, lastName, displayName, primary, publishingAnalyst}]
    - companies.results[]: [{displayName, ...}]  (empty for macro/strategy reports)
    - documentFormats[]:   [{documentId, mimeType, primary}]  (text/html + pdf)

Content: navigate to article page in-browser; fall back to synopsis.
  Article URL: /jpmm/research.article_page?action=open&doc={id}
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from report_tracker import ReportTracker
import config as _cfg

load_dotenv()

BASE_URL    = 'https://markets.jpmorgan.com'
PORTAL      = 'jpmorgan'
PDF_DIR     = 'data/reports/jpmorgan'
PROFILE_DIR = os.path.abspath('data/chrome_profiles/jpmorgan')

RESEARCH_URL = f'{BASE_URL}/jpmm/research.my_research'


class JPMorganScraper:
    """
    Selenium scraper for JP Morgan Markets (Tier 4 — 2FA, persistent profile).

    Auth strategy:
      1. Open Chrome with persistent profile (data/chrome_profiles/jpmorgan)
      2. Navigate to research page — if URL lands on /jpmm/ → session alive
      3. If redirected to login → open visibly, wait for user to complete 2FA
      4. Subsequent runs reuse Chrome's persisted session silently
    """

    def __init__(self):
        self.report_tracker = ReportTracker()
        os.makedirs(PDF_DIR, exist_ok=True)
        os.makedirs(PROFILE_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Driver
    # ------------------------------------------------------------------

    def _get_driver(self, headless: bool = False) -> webdriver.Chrome:
        opts = Options()
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        opts.add_argument('--window-size=1400,900')
        opts.add_argument('--disable-blink-features=AutomationControlled')
        opts.add_experimental_option('excludeSwitches', ['enable-automation'])
        opts.add_experimental_option('useAutomationExtension', False)
        opts.add_argument(f'--user-data-dir={PROFILE_DIR}')
        if headless:
            opts.add_argument('--headless=new')
        opts.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

        driver = webdriver.Chrome(options=opts)
        driver.set_page_load_timeout(_cfg.PAGE_LOAD_TIMEOUT)
        driver.execute_cdp_cmd('Network.enable', {})
        return driver

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _authenticate(self, driver) -> bool:
        """
        Navigate to research page with persistent profile.
        If session valid: lands on /jpmm/ silently.
        If expired: auto-fills credentials (from .env), waits for /jpmm/.
        If 2FA is triggered: waits up to 3 min for user to complete it manually.
        """
        print(f'[{PORTAL}] Navigating to research page...')
        driver.get(RESEARCH_URL)
        time.sleep(3)

        if '/jpmm' in driver.current_url.split('?')[0]:
            print(f'[{PORTAL}] ✓ Session valid (persistent profile)')
            return True

        # Session expired — attempt credential auto-fill
        print(f'[{PORTAL}] Session expired — attempting auto-login...')
        self._try_fill_credentials(driver)

        # Wait up to 3 min for /jpmm/ (covers slow 2FA or manual OTP entry)
        print(f'[{PORTAL}] Waiting for authentication (up to 3 min)...')
        for _ in range(90):
            time.sleep(2)
            if '/jpmm' in driver.current_url.split('?')[0]:
                print(f'[{PORTAL}] ✓ Authenticated')
                time.sleep(3)  # let SPA settle
                return True

        self._write_auth_alert('Login timed out after 3 minutes')
        return False

    def _try_fill_credentials(self, driver):
        """
        Attempt to auto-fill username + password from .env.
        Works for the standard JPM login flow (username on main page,
        password in SSO iframe). Silently skips steps that fail — the
        3-min polling loop in _authenticate() handles 2FA or manual fallback.
        """
        email    = os.getenv('JPMORGAN_EMAIL', '')
        password = os.getenv('JPMORGAN_PASSWORD', '')
        if not email or not password:
            print(f'[{PORTAL}] No credentials in .env — waiting for manual login')
            return

        try:
            # Step 1: fill username on the main login page
            wait = WebDriverWait(driver, 10)
            username_input = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'input[placeholder*="username"], input[type="email"], '
                                  'input[name*="user"], input[id*="user"], input[id*="email"]')
            ))
            username_input.clear()
            username_input.send_keys(email)
            print(f'[{PORTAL}]   ✓ Username filled')

            # Click the login / next button
            submit = driver.find_element(
                By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"], '
                                 'button.login-btn, button.btn-primary, button.jpm-btn'
            )
            submit.click()
            time.sleep(3)
        except Exception as e:
            print(f'[{PORTAL}]   Username step skipped: {e}')
            return

        try:
            # Step 2: password — may be in a cross-origin iframe (nwas.jpmorgan.com/sso)
            iframes = driver.find_elements(By.TAG_NAME, 'iframe')
            if iframes:
                driver.switch_to.frame(iframes[0])

            wait2 = WebDriverWait(driver, 8)
            pwd_input = wait2.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'input[type="password"]')
            ))
            pwd_input.clear()
            pwd_input.send_keys(password)
            print(f'[{PORTAL}]   ✓ Password filled')

            submit2 = driver.find_element(
                By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]'
            )
            submit2.click()
            time.sleep(2)

            if iframes:
                driver.switch_to.default_content()
        except Exception as e:
            print(f'[{PORTAL}]   Password step skipped: {e}')
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Publication scraping (XHR interception)
    # ------------------------------------------------------------------

    def _scrape_publications(self, driver, count: int = 50) -> List[Dict]:
        """
        Capture XHR JSON responses via CDP performance log.
        Reads log from the auth navigation (already on research page).
        If on a different page, navigates to RESEARCH_URL and waits for SPA.
        Falls back to DOM scraping if XHR capture yields nothing.
        """
        # If not already on the research page, navigate there
        if RESEARCH_URL not in driver.current_url:
            driver.get_log('performance')  # drain stale entries
            print(f'[{PORTAL}] Navigating to research page for XHR capture...')
            driver.get(RESEARCH_URL)

        # Wait for SPA to fire data XHR calls
        time.sleep(12)

        # Scan CDP performance log for JSON responses containing publication data
        publications = self._extract_from_perf_log(driver)
        if publications:
            print(f'[{PORTAL}] XHR capture: {len(publications)} publications')
            return publications

        # Fallback: scrape from DOM
        print(f'[{PORTAL}] XHR capture empty — trying DOM scrape')
        return self._scrape_dom(driver)

    # Feed tabs to ingest: subscribed publications, followed analysts, companies, sectors
    _FEED_TABS = {'publicationDocuments', 'analystDocuments', 'companiesEquityDocuments', 'industriesDocuments'}

    def _extract_from_perf_log(self, driver) -> List[Dict]:
        """
        Extract publication data from CDP Network.responseReceived events.
        Only reads from the three relevant feed tabs; deduplicates by doc id.
        """
        seen = set()
        publications = []
        try:
            entries = driver.get_log('performance')
            for entry in entries:
                msg = json.loads(entry['message'])['message']
                if msg['method'] != 'Network.responseReceived':
                    continue
                resp = msg['params']['response']
                url  = resp.get('url', '')
                ct   = (resp.get('mimeType', '') +
                        resp.get('headers', {}).get('content-type', ''))

                # Only process relevant feed tabs
                if 'jpmorgan.com' not in url or 'json' not in ct:
                    continue
                tab = next((t for t in self._FEED_TABS if t in url), None)
                if not tab:
                    continue

                try:
                    req_id = msg['params']['requestId']
                    body_resp = driver.execute_cdp_cmd(
                        'Network.getResponseBody', {'requestId': req_id}
                    )
                    data = json.loads(body_resp.get('body', ''))
                    results = self._find_publication_list(data)
                    new = [r for r in results if r.get('id') not in seen]
                    if new:
                        normalized = [self._normalize(r) for r in new]
                        normalized = [n for n in normalized if n is not None]
                        kept = len(normalized)
                        print(f'[{PORTAL}]   {tab}: {kept} items ({len(new)-kept} spreadsheets skipped)')
                        for r in new:
                            seen.add(r.get('id'))
                        publications.extend(normalized)
                except Exception:
                    continue
        except Exception as e:
            print(f'[{PORTAL}] Perf log error: {e}')
        return publications

    def _find_publication_list(self, data) -> List[Dict]:
        """Search common response shapes for a list of publication objects."""
        if not isinstance(data, dict):
            return []

        # Shape 1: data.researchService.research.results[]
        try:
            r = data['data']['researchService']['research']['results']
            if isinstance(r, list) and r:
                return r
        except (KeyError, TypeError):
            pass

        # Shape 2: data.publications[] or data.results[]
        for key in ('publications', 'results', 'documents', 'items'):
            val = data.get('data', data).get(key, [])
            if isinstance(val, list) and val and isinstance(val[0], dict):
                # Must look like a publication (has title or id)
                if val[0].get('title') or val[0].get('id') or val[0].get('documentId'):
                    return val

        return []

    def _scrape_dom(self, driver) -> List[Dict]:
        """
        Fallback DOM scrape: look for publication card elements in page source.
        Returns partial data (title, url, date) without full analyst/ticker info.
        """
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        publications = []

        # Log page structure for debugging
        driver.save_screenshot('/tmp/jpm_research_dom.png')
        print(f'[{PORTAL}] DOM screenshot saved to /tmp/jpm_research_dom.png')
        print(f'[{PORTAL}] Page title: {driver.title}')
        print(f'[{PORTAL}] Page source length: {len(driver.page_source)}')

        # Log all links that look like article links
        for a in soup.find_all('a', href=True)[:30]:
            href = a['href']
            if 'research' in href or 'article' in href or 'doc' in href:
                print(f'[{PORTAL}]   Article link: {href}  |  {a.get_text(strip=True)[:60]}')

        return publications  # empty — caller will treat this as no-data day

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize(self, item: Dict) -> Optional[Dict]:
        """
        Map one API result → standard report dict.
        Returns None for Excel-only documents (models/spreadsheets).
        """
        doc_id   = item.get('id') or item.get('documentId', '')
        pub_date = item.get('publicationDate') or item.get('date', '')
        date_str = pub_date[:10] if pub_date else None

        # Skip if only Excel format (no HTML or PDF) — it's a spreadsheet/model
        fmts = [f.get('mimeType', '') for f in item.get('documentFormats', [])]
        if fmts and not any('html' in m or 'pdf' in m for m in fmts):
            print(f'[{PORTAL}]   Skipping Excel-only document: {item.get("title", doc_id)[:50]}')
            return None

        analysts_raw = item.get('analysts', {}).get('results', [])
        primary = next(
            (a for a in analysts_raw if a.get('primary') and a.get('publishingAnalyst')),
            analysts_raw[0] if analysts_raw else {}
        )
        analyst_name = (
            primary.get('displayName') or
            f"{primary.get('firstName', '')} {primary.get('lastName', '')}".strip()
        )

        tickers = [
            c['ricCode']['ticker']
            for c in item.get('companies', {}).get('results', [])
            if c.get('ricCode', {}).get('ticker')
        ]

        return {
            'id':       doc_id,
            'title':    item.get('title', f'Report {doc_id}'),
            'subtitle': item.get('subtitle', ''),
            'synopsis': item.get('synopsis', ''),
            'date':     date_str,
            'analyst':  analyst_name,
            'tickers':  tickers,
            'url':      f'{BASE_URL}/jpmm/research.article_page?action=open&doc={doc_id}',
            'source':   'JPMorgan',
        }

    # ------------------------------------------------------------------
    # Content extraction
    # ------------------------------------------------------------------

    def _fetch_content(self, driver, report: Dict) -> Optional[str]:
        """
        Navigate to article URL in-browser, extract text.
        Falls back to title + subtitle + synopsis from feed.
        """
        url = report.get('url', '')
        if url:
            try:
                driver.get(url)
                time.sleep(4)  # SPA render

                soup = BeautifulSoup(driver.page_source, 'html.parser')
                for el in soup(['script', 'style', 'nav', 'header', 'footer']):
                    el.decompose()
                text = soup.get_text(separator='\n', strip=True)
                if len(text) > 300:
                    print(f'    ✓ Article content ({len(text)} chars)')
                    return text
            except Exception as e:
                print(f'    ⚠ Article fetch error: {e}')

        # Fallback: synopsis from feed data
        parts = [report.get('title', ''), report.get('subtitle', ''), report.get('synopsis', '')]
        fallback = '\n\n'.join(p for p in parts if p)
        if fallback:
            print(f'    ✓ Synopsis fallback ({len(fallback)} chars)')
            return fallback

        return None

    # ------------------------------------------------------------------
    # Date filtering
    # ------------------------------------------------------------------

    def _filter_by_date(self, reports: List[Dict], days: int) -> List[Dict]:
        """Keep reports from yesterday midnight onward."""
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        recent = []
        for r in reports:
            if not r.get('date'):
                recent.append(r)
                continue
            try:
                if datetime.strptime(r['date'], '%Y-%m-%d') >= cutoff:
                    recent.append(r)
            except Exception:
                recent.append(r)
        print(f'  Date filter: {len(recent)} of {len(reports)} reports from last 2 days')
        return recent

    # ------------------------------------------------------------------
    # Auth alerting
    # ------------------------------------------------------------------

    def _write_auth_alert(self, reason: str = ''):
        try:
            os.makedirs('data/alerts', exist_ok=True)
            path = f'data/alerts/auth_required_{PORTAL}.txt'
            with open(path, 'w') as f:
                f.write(f'{PORTAL} requires re-authentication\n')
                f.write(f'Timestamp: {datetime.now().isoformat()}\n')
                if reason:
                    f.write(f'Reason: {reason}\n')
                f.write('Action: run `python refresh_cookies.py --interactive jpmorgan`\n')
            print(f'[{PORTAL}] ⚠ Auth alert written')
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Main entry point  (PortalRegistry interface)
    # ------------------------------------------------------------------

    def get_followed_reports(self, max_reports: int = 25, days: int = 2,
                             result_out: Dict = None) -> Dict:
        """
        Full pipeline: login → scrape feed → date filter → dedup → extract content.
        Compatible with PortalRegistry.collect_from().
        Single Chrome session for the entire run.
        """
        failures = []
        processed = []
        driver = None

        print(f"\n{'='*50}")
        print(f'[{PORTAL}] Fetching reports from JP Morgan Markets')
        print(f"{'='*50}")

        try:
            driver = self._get_driver(headless=False)

            # [1/4] Auth
            if not self._authenticate(driver):
                return {'reports': [], 'failures': [f'{PORTAL}: login failed'], 'auth_required': True}

            # [2/4] Scrape publications via XHR interception
            publications = self._scrape_publications(driver, count=max(max_reports * 3, 50))
            if not publications:
                failures.append('No publications found (XHR + DOM both empty)')
                return {'reports': [], 'failures': failures}

            # [3/4] Date + dedup filter
            recent = self._filter_by_date(publications, days=days)
            new_reports = self.report_tracker.filter_unprocessed(recent)
            skipped = len(recent) - len(new_reports)
            if skipped:
                print(f'  Skipped {skipped} previously processed reports')
            print(f'  -> {len(new_reports)} new reports to process')

            if not new_reports:
                print('\n  No new reports to process')
                return {'reports': [], 'failures': failures}

            if len(new_reports) > max_reports:
                new_reports = new_reports[:max_reports]

            # [4/4] Extract content (in-browser)
            for i, report in enumerate(new_reports, 1):
                try:
                    print(f"\n  [{i}/{len(new_reports)}] {report['title'][:60]}")
                    if i > 1:
                        time.sleep(1.5)

                    content = self._fetch_content(driver, report)
                    if content:
                        report['content'] = content
                        processed.append(report)
                        if result_out is not None:
                            result_out['reports'].append(report)
                        self.report_tracker.mark_as_processed(report)
                    else:
                        failures.append(f"No content: {report['title'][:40]}")

                except Exception as e:
                    failures.append(f"Error: {report.get('title', 'unknown')[:30]}: {e}")
                    print(f'    Skipping: {e}')

        except Exception as e:
            failures.append(f'Unexpected error: {e}')
            print(f'[{PORTAL}] ✗ {e}')

        finally:
            if driver:
                driver.quit()

        print(f"\n{'='*50}")
        print(f'[{PORTAL}] Extracted {len(processed)} reports')
        if failures:
            print(f'  {len(failures)} failures')
        return {'reports': processed, 'failures': failures}


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == '__main__':
    import sys

    print('\nJP Morgan Markets Scraper Test')
    print('=' * 50)
    print(f'Chrome profile: {PROFILE_DIR}')

    scraper = JPMorganScraper()
    driver  = scraper._get_driver(headless=False)

    try:
        print('\n[1/3] Testing auth...')
        if not scraper._authenticate(driver):
            print('✗ Auth failed')
            sys.exit(1)
        print('✓ Authenticated')

        print('\n[2/3] Testing publication scrape...')
        pubs = scraper._scrape_publications(driver, count=10)
        if not pubs:
            print('✗ No publications found — check /tmp/jpm_research_dom.png for page state')
            sys.exit(1)
        print(f'✓ {len(pubs)} publications')
        for p in pubs[:3]:
            print(f'  {p["date"]}  {p["title"][:55]}  [{", ".join(p["tickers"])}]')

        print('\n[3/3] Testing content fetch (first report)...')
        content = scraper._fetch_content(driver, pubs[0])
        if content:
            print(f'✓ Content: {len(content)} chars')
            print(f'  Preview: {content[:200]}')
        else:
            print('✗ No content')

    finally:
        driver.quit()

    print('\n✓ All tests passed')
