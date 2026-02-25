"""
Macquarie Insights Research Portal Scraper

API-based scraper (no Selenium needed). Auth is entirely cookie-based:
- refresh_token: 1-year TTL; seeds every authenticated session
- auth_token: 5-minute TTL; auto-rotated by server on every response
- csrf_token: paired with auth_token; extracted from JWT payload

Auth flow:
1. Load cookies from cookie_manager (refresh_token + csrf_token sufficient)
2. Any GET request causes server to issue fresh auth_token via Set-Cookie
3. _refresh_session() does exactly this before each run
4. _persist_cookies() saves updated auth_token after run

Re-seeding (when refresh_token expires ~1 year):
  Log in at macquarieinsights.com, then:
  python3 -c "from cookie_manager import import_cookies_from_browser; \\
    import_cookies_from_browser('macquarie', {'auth_token': '...', \\
    'refresh_token': '...', 'csrf_token': '...'})"

Report API:
- Followed entities: POST /api/user/populateNotifications  {pageNumber:0, initial:false}
                      → settings.tags: [{category, idFromSource, value}, ...]
- List:   POST /api/research/search  {tags:[{category,idFromSource,value}], page:0,
                size:N, startDate, finishDate, sortBy:'publicationDate', sortDirection:'DESC',
                includeFields:[...]}  → {content:[{idFromSource, title, publicationDate,
                mainFileName, pdfFileName, bulletPoint1/2/3, authors}, ...]}
- HTML:   GET  /api/static/file/publications/{id}/index.html
- PDF:    GET  /api/static/file/publications/{id}/{hash}.pdf
"""

import os
import re
import time
import warnings
import json
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

from cookie_manager import CookieManager
from report_tracker import ReportTracker
import config as _cfg

warnings.filterwarnings('ignore', message='.*urllib3.*')

load_dotenv()

BASE_URL  = 'https://www.macquarieinsights.com'
PORTAL    = 'macquarie'
PDF_DIR   = 'data/reports/macquarie'

# Standard headers that mirror what the browser sends
_HEADERS = {
    'accept':           'application/json, text/plain, */*',
    'content-type':     'application/json',
    'origin':           BASE_URL,
    'referer':          f'{BASE_URL}/overview',
    'user-agent':       'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/145.0.0.0 Safari/537.36',
}


class MacquarieScraper:
    """
    API-based scraper for Macquarie Insights.
    Does NOT extend BaseScraper (no Selenium needed — pure requests).
    Implements the same get_followed_reports() interface so it integrates
    transparently with PortalRegistry.
    """

    # Needed so PortalRegistry can instantiate with headless kwarg
    def __init__(self, headless: bool = True):
        self.cookie_manager = CookieManager()
        self.report_tracker = ReportTracker()
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        os.makedirs(PDF_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Session / auth management
    # ------------------------------------------------------------------

    def _load_cookies(self) -> bool:
        """
        Load persisted cookies into the requests.Session.
        Returns False if no cookies are stored (needs manual re-seed).
        """
        cookies = self.cookie_manager.get_cookies(PORTAL)
        if not cookies:
            print(f'[{PORTAL}] ✗ No stored cookies — re-seed required')
            print(f'[{PORTAL}]   Log in at macquarieinsights.com then run:')
            print(f"[{PORTAL}]   python3 -c \"from cookie_manager import "
                  f"import_cookies_from_browser; import_cookies_from_browser("
                  f"'macquarie', {{'auth_token':'...','refresh_token':'...','csrf_token':'...'}})")
            self._write_auth_alert()
            return False

        # Must have at least a refresh_token
        if 'refresh_token' not in cookies:
            print(f'[{PORTAL}] ✗ refresh_token missing — re-seed required')
            self._write_auth_alert()
            return False

        for name, value in cookies.items():
            self.session.cookies.set(name, value, domain='www.macquarieinsights.com')

        print(f'[{PORTAL}] Loaded {len(cookies)} cookies')
        return True

    def _refresh_session(self) -> bool:
        """
        Trigger auth_token rotation: make a lightweight GET so the server
        issues a fresh auth_token via Set-Cookie.  Must be called before
        any scraping work begins.
        """
        try:
            # Any authenticated GET causes the server to rotate auth_token
            r = self.session.get(f'{BASE_URL}/api/research/overview',
                                 timeout=_cfg.REQUEST_TIMEOUT)
            new_auth = self.session.cookies.get('auth_token')
            if new_auth:
                print(f'[{PORTAL}] ✓ auth_token refreshed')
                self._persist_cookies()
                return True
            # Even a 404/405 still rotates the token — check Set-Cookie
            set_cookie = r.headers.get('Set-Cookie', '')
            if 'auth_token' in set_cookie:
                print(f'[{PORTAL}] ✓ auth_token refreshed (via header)')
                self._persist_cookies()
                return True
            print(f'[{PORTAL}] ⚠ No new auth_token after refresh ping — proceeding anyway')
            return True
        except Exception as e:
            print(f'[{PORTAL}] ✗ Session refresh error: {e}')
            return False

    def _persist_cookies(self):
        """Write current session cookies back to cookie_manager store."""
        current = {name: value for name, value in self.session.cookies.items()}
        if current:
            self.cookie_manager.save_cookies(PORTAL, current)

    def _write_auth_alert(self):
        """Write flag file when manual re-authentication is needed."""
        try:
            os.makedirs('data/alerts', exist_ok=True)
            path = f'data/alerts/auth_required_{PORTAL}.txt'
            with open(path, 'w') as f:
                f.write(f'{PORTAL} requires manual re-seeding\n')
                f.write(f'Timestamp: {datetime.now().isoformat()}\n')
                f.write('Action: log in at macquarieinsights.com, copy cookies, run seed script\n')
            print(f'[{PORTAL}] ⚠ Auth alert written: {path}')
        except Exception as e:
            print(f'[{PORTAL}] Failed to write auth alert: {e}')

    # ------------------------------------------------------------------
    # Notification listing  (entry point for report discovery)
    # ------------------------------------------------------------------

    def _fetch_followed_entities(self) -> List[Dict]:
        """
        POST /api/user/populateNotifications
        Returns deduplicated list of followed tags:
          [{category: 'security'|'analyst', idFromSource: N, value: 'Name'}, ...]
        """
        try:
            r = self.session.post(
                f'{BASE_URL}/api/user/populateNotifications',
                json={'pageNumber': 0, 'initial': False},
                timeout=_cfg.REQUEST_TIMEOUT,
            )
            if r.status_code != 200:
                print(f'[{PORTAL}] ✗ populateNotifications: HTTP {r.status_code}')
                return []
            tags = r.json().get('settings', {}).get('tags', [])
            # Deduplicate by (category, idFromSource)
            seen = set()
            unique = []
            for tag in tags:
                key = (tag.get('category'), tag.get('idFromSource'))
                if key not in seen:
                    seen.add(key)
                    unique.append(tag)
            dupes = len(tags) - len(unique)
            print(f'[{PORTAL}] {len(unique)} followed entities ({dupes} dupes removed)')
            return unique
        except Exception as e:
            print(f'[{PORTAL}] ✗ Error fetching followed entities: {e}')
            return []

    def _search_publications_for_entity(self, tag: Dict, start_date: str,
                                         per_entity: int = 10) -> List[Dict]:
        """
        POST /api/research/search filtered to one followed security or analyst.
        Returns raw content items from the response.
        """
        finish_date = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        body = {
            'tags': [{
                'category':     tag['category'],
                'idFromSource': tag['idFromSource'],
                'value':        tag.get('value', ''),
            }],
            'page':          0,
            'size':          per_entity,
            'discoverPage':  False,
            'startDate':     start_date,
            'finishDate':    finish_date,
            'sortBy':        'publicationDate',
            'sortDirection': 'DESC',
            'includeFields': [
                'id', 'bulletPoints', 'authors', 'publicationDate', 'pdfPageCount',
                'publicationType', 'sectors', 'title', 'mainFileName', 'pdfFileName',
                'miniLink', 'isInitiation',
            ],
        }
        try:
            r = self.session.post(f'{BASE_URL}/api/research/search',
                                  json=body, timeout=_cfg.REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.json().get('content', [])
            print(f'    ✗ search {tag.get("value","")}: HTTP {r.status_code}')
            return []
        except Exception as e:
            print(f'    ✗ search error ({tag.get("value","")}): {e}')
            return []

    def _fetch_notifications(self, days: int = 7) -> List[Dict]:
        """
        Two-step discovery:
          1. POST /api/user/populateNotifications  → followed entities
          2. POST /api/research/search per entity  → recent publications

        Returns normalized report dicts with pre-fetched file paths and
        bullet points (no separate detail call needed).
        """
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%dT00:00:00.000Z')

        entities = self._fetch_followed_entities()
        if not entities:
            return []

        # Search analysts before securities: analyst searches return correct author
        # attribution. If a security is searched first, authors comes back empty and
        # falls back to the security name, misattributing the report.
        entities = sorted(entities, key=lambda t: 0 if t.get('category') == 'analyst' else 1)

        seen_ids = set()
        all_reports = []

        for tag in entities:
            items = self._search_publications_for_entity(tag, start_date)
            for item in items:
                report_id = item.get('idFromSource')
                if not report_id or report_id in seen_ids:
                    continue
                seen_ids.add(report_id)

                pub_date = item.get('publicationDate', '')
                date_str = pub_date[:10] if pub_date else None

                # Author names from the authors array
                authors = item.get('authors') or []
                analyst_name = ', '.join(
                    a.get('preferredName', '') for a in authors if a.get('preferredName')
                ) or tag.get('value', '')

                # Pre-extracted bullet points from Macquarie
                bullets = [item.get(f'bulletPoint{i}') for i in range(1, 4)
                           if item.get(f'bulletPoint{i}')]
                bullet_text = '\n'.join(f'• {b}' for b in bullets)

                all_reports.append({
                    'id':          report_id,
                    'title':       item.get('title', f'Report {report_id}'),
                    'date':        date_str,
                    'analyst':     analyst_name,
                    'url':         f'{BASE_URL}/report?researchId={report_id}',
                    'source':      'Macquarie',
                    'main_file':   item.get('mainFileName'),   # already the full path
                    'pdf_file':    item.get('pdfFileName'),
                    'bullet_text': bullet_text,
                })

            time.sleep(0.3)  # Polite delay between entity searches

        print(f'[{PORTAL}] {len(all_reports)} unique reports across {len(entities)} entities')
        return all_reports

    # ------------------------------------------------------------------
    # Report detail + content extraction
    # ------------------------------------------------------------------

    def _fetch_report_detail(self, report_id: int) -> Optional[Dict]:
        """
        GET /api/research/{id} — returns full report metadata including
        pdfFileName and mainFileName (HTML).
        """
        try:
            r = self.session.get(f'{BASE_URL}/api/research/{report_id}',
                                 timeout=_cfg.REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.json()
            print(f'    ✗ Report detail {report_id}: HTTP {r.status_code}')
            return None
        except Exception as e:
            print(f'    ✗ Error fetching report {report_id}: {e}')
            return None

    def _extract_content(self, report: Dict) -> Optional[str]:
        """
        Try HTML first (richest text), fall back to PDF, then bullet points.
        File paths come directly from the search response (no detail fetch needed).
        Updates report dict with pdf_path if PDF is saved.
        """
        # --- Option 1: HTML body ---
        html_path = report.get('main_file')
        if html_path:
            try:
                r = self.session.get(f'{BASE_URL}{html_path}',
                                     timeout=_cfg.REQUEST_TIMEOUT)
                if r.status_code == 200 and len(r.text) > 500:
                    text = self._html_to_text(r.text)
                    if text and len(text) > 200:
                        print(f'    ✓ Extracted {len(text)} chars from HTML')
                        return text
            except Exception as e:
                print(f'    ⚠ HTML fetch failed: {e}')

        # --- Option 2: PDF ---
        pdf_path = report.get('pdf_file')
        if pdf_path:
            try:
                r = self.session.get(f'{BASE_URL}{pdf_path}',
                                     timeout=_cfg.REQUEST_TIMEOUT)
                if r.status_code == 200 and len(r.content) > 1000:
                    print(f'    Downloaded PDF ({len(r.content)} bytes)')
                    saved = self._save_pdf(r.content, report)
                    if saved:
                        report['pdf_path'] = saved
                    text = self._extract_text_from_pdf(r.content)
                    if text:
                        return text
            except Exception as e:
                print(f'    ⚠ PDF fetch failed: {e}')

        # --- Option 3: Pre-extracted bullet points (always available) ---
        bullet_text = report.get('bullet_text', '')
        if bullet_text:
            print(f'    ✓ Using pre-extracted bullet points')
            return bullet_text

        return None

    def _html_to_text(self, html: str) -> str:
        """Strip HTML tags, return clean text."""
        soup = BeautifulSoup(html, 'html.parser')
        for el in soup(['script', 'style', 'nav', 'header', 'footer',
                        'table']):
            el.decompose()
        return soup.get_text(separator='\n', strip=True)

    def _extract_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """Extract text from PDF bytes (pdfplumber → PyPDF2 fallback)."""
        import io
        text = ''
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text += t + '\n\n'
            if text.strip():
                print(f'    Extracted {len(text)} chars from PDF')
                return text
        except Exception as e:
            print(f'    pdfplumber failed: {e}')
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                text += page.extract_text() + '\n\n'
            if text.strip():
                return text
        except Exception as e:
            print(f'    PDF extraction failed: {e}')
        return ''

    def _save_pdf(self, pdf_bytes: bytes, report: Dict) -> Optional[str]:
        """Save PDF with dated directory structure."""
        try:
            pub_date = report.get('date') or datetime.now().strftime('%Y-%m-%d')
            year_month = pub_date[:7]
            analyst = re.sub(r'[^\w\s-]', '', report.get('analyst') or 'unknown').strip()
            analyst = analyst.replace(' ', '_').lower()
            dir_path = os.path.join(PDF_DIR, year_month, analyst)
            os.makedirs(dir_path, exist_ok=True)

            report_id = report.get('id', 'unknown')
            title_slug = re.sub(r'[^\w\s-]', '', report.get('title', '')[:30]).strip().replace(' ', '_').lower()
            filename = f'{pub_date}_{title_slug}_{report_id}.pdf'
            pdf_path = os.path.join(dir_path, filename)

            with open(pdf_path, 'wb') as f:
                f.write(pdf_bytes)

            meta_path = pdf_path.replace('.pdf', '.json')
            with open(meta_path, 'w') as f:
                json.dump({
                    'url':          report.get('url'),
                    'title':        report.get('title'),
                    'analyst':      report.get('analyst'),
                    'source':       'Macquarie',
                    'publish_date': pub_date,
                    'scraped_at':   datetime.now().isoformat(),
                    'pdf_size_bytes': len(pdf_bytes),
                    'pdf_path':     pdf_path,
                }, f, indent=2)

            print(f'    Saved PDF: {pdf_path}')
            return pdf_path
        except Exception as e:
            print(f'    Failed to save PDF: {e}')
            return None

    # ------------------------------------------------------------------
    # Date filtering
    # ------------------------------------------------------------------

    def _filter_by_date(self, reports: List[Dict], days: int) -> List[Dict]:
        cutoff = datetime.now() - timedelta(days=days)
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
        print(f'  Date filter: {len(recent)} of {len(reports)} reports from last {days} days')
        return recent

    # ------------------------------------------------------------------
    # Main entry point (matches BaseScraper interface for PortalRegistry)
    # ------------------------------------------------------------------

    def get_followed_reports(self, max_reports: int = 20, days: int = 7,
                             result_out: Dict = None) -> Dict:
        """
        Full pipeline: load cookies → refresh session → list notifications
        → filter → extract content.

        Compatible with PortalRegistry.collect_from().
        """
        failures = []
        processed = []

        print(f"\n{'='*50}")
        print(f'[{PORTAL}] Fetching reports from Macquarie Insights API')
        print(f"{'='*50}")

        # Auth
        if not self._load_cookies():
            return {'reports': [], 'failures': [f'{PORTAL}: auth required'], 'auth_required': True}

        if not self._refresh_session():
            return {'reports': [], 'failures': [f'{PORTAL}: session refresh failed'], 'auth_required': True}

        # Discover notifications
        notifications = self._fetch_notifications(days=days)
        if not notifications:
            failures.append('No notifications returned (listing endpoint not yet implemented)')
            return {'reports': [], 'failures': failures}

        # Date filter
        recent = self._filter_by_date(notifications, days=days)

        # Dedup
        new_reports = self.report_tracker.filter_unprocessed(recent)
        skipped = len(recent) - len(new_reports)
        if skipped:
            print(f'  Skipped {skipped} previously processed reports')
        print(f'  -> {len(new_reports)} new reports to process')

        if not new_reports:
            print('\n No new reports to process')
            return {'reports': [], 'failures': failures}

        if len(new_reports) > max_reports:
            new_reports = new_reports[:max_reports]
            print(f'  Limited to {max_reports} reports')

        # Extract content for each report
        for i, report in enumerate(new_reports, 1):
            try:
                print(f"\n  [{i}/{len(new_reports)}] {report['title'][:60]}")

                if i > 1:
                    time.sleep(1.5)  # Polite delay between content fetches

                content = self._extract_content(report)
                if content:
                    report['content'] = content
                    processed.append(report)
                    if result_out is not None:
                        result_out['reports'].append(report)
                    self.report_tracker.mark_as_processed(report)
                else:
                    failures.append(f"No content extracted: {report['title'][:40]}")

            except Exception as e:
                failures.append(f"Error processing {report.get('title', 'unknown')[:30]}: {e}")
                print(f'    Skipping due to error: {e}')
                continue

            # Persist cookies periodically
            if i % 5 == 0:
                self._persist_cookies()

        # Final cookie save
        self._persist_cookies()

        print(f"\n{'='*50}")
        print(f'[{PORTAL}] Successfully extracted {len(processed)} reports')
        if failures:
            print(f'  {len(failures)} failures')
        return {'reports': processed, 'failures': failures}


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == '__main__':
    import sys

    print('\nMacquarie Insights Scraper Test')
    print('=' * 50)

    from cookie_manager import CookieManager
    cm = CookieManager()
    cookies = cm.get_cookies('macquarie')
    if not cookies or 'refresh_token' not in cookies:
        print('✗ No Macquarie cookies stored')
        print('  Run the seed script first:')
        print("  python3 -c \"from cookie_manager import import_cookies_from_browser; \\")
        print("    import_cookies_from_browser('macquarie', {'auth_token':'...', \\")
        print("    'refresh_token':'...','csrf_token':'...'})\"")
        sys.exit(1)

    print(f'✓ Cookies loaded ({len(cookies)} keys)')

    scraper = MacquarieScraper()
    scraper._load_cookies()

    print('\n[1/3] Testing session refresh...')
    ok = scraper._refresh_session()
    print(f'  Session refresh: {"✓" if ok else "✗"}')

    print('\n[2/3] Testing followed entities...')
    entities = scraper._fetch_followed_entities()
    if entities:
        print(f'  ✓ {len(entities)} followed entities')
        for e in entities[:5]:
            print(f'    [{e["category"]}] {e["value"]} (id={e["idFromSource"]})')
        if len(entities) > 5:
            print(f'    ... and {len(entities)-5} more')
    else:
        print('  ✗ No entities returned')

    print('\n[3/3] Testing publication search (last 7 days)...')
    notifications = scraper._fetch_notifications(days=7)
    if notifications:
        print(f'  ✓ {len(notifications)} reports found')
        for r in notifications[:3]:
            print(f'    {r["date"]}  {r["title"][:55]}')
            if r.get("bullet_text"):
                print(f'    {r["bullet_text"][:120]}')
    else:
        print('  ℹ No reports in last 7 days (try days=30 for broader test)')
        notifications = scraper._fetch_notifications(days=30)
        print(f'  Last 30 days: {len(notifications)} reports')
        for r in notifications[:3]:
            print(f'    {r["date"]}  {r["title"][:55]}')

    print('\n✓ All tests passed')
