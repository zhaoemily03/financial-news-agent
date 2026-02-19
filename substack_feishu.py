#!/usr/bin/env python3
"""
Substack ingestion via Feishu Mail API.

Fetches forwarded Substack emails from a Feishu mailbox using an Internal App
tenant_access_token. Extracts article content and returns standardized report
dicts for the pipeline.

Feishu API endpoints used:
  POST /open-apis/auth/v3/tenant_access_token/internal  — get token
  GET  /open-apis/mail/v1/user_mailboxes/{id}/folders    — list folders
  GET  /open-apis/mail/v1/user_mailboxes/{id}/messages   — list message IDs
  GET  /open-apis/mail/v1/user_mailboxes/{id}/messages/{msg_id} — get message
"""

import os
import re
import base64
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from html.parser import HTMLParser

import requests
from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

FEISHU_APP_ID = os.getenv('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET', '')
FEISHU_MAILBOX = os.getenv('FEISHU_MAILBOX', 'emilyzhao@honycapital.com')
FEISHU_BASE = 'https://open.feishu.cn/open-apis'

# Token endpoint
TOKEN_URL = f'{FEISHU_BASE}/auth/v3/tenant_access_token/internal'

# Substack detection
SUBSTACK_SENDER_PATTERN = re.compile(r'[\w.-]+@substack\.com', re.IGNORECASE)
FORWARDED_SUBJECT_PREFIX = re.compile(r'^(转发|Fwd?|Fw)\s*[:：]\s*', re.IGNORECASE)


# ------------------------------------------------------------------
# HTML → plain text
# ------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML to text converter."""
    def __init__(self):
        super().__init__()
        self.parts: List[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script'):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ('style', 'script'):
            self._skip = False
        if tag in ('p', 'div', 'br', 'h1', 'h2', 'h3', 'h4', 'li', 'tr', 'td'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def get_text(self) -> str:
        raw = ''.join(self.parts)
        # Collapse invisible spacing chars Substack injects
        raw = re.sub(r'[\u034f\u00ad\u200b\u200c\u200d\ufeff]+', '', raw)
        # Collapse multiple blank lines
        raw = re.sub(r'\n{3,}', '\n\n', raw)
        return raw.strip()


def html_to_text(html: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


# ------------------------------------------------------------------
# Base64url decoding (Feishu uses URL-safe base64)
# ------------------------------------------------------------------

def decode_b64url(data: str) -> str:
    """Decode Feishu's base64url-encoded content."""
    if not data:
        return ''
    std = data.replace('-', '+').replace('_', '/')
    padding = 4 - len(std) % 4
    if padding != 4:
        std += '=' * padding
    return base64.b64decode(std).decode('utf-8', errors='replace')


# ------------------------------------------------------------------
# Feishu API client
# ------------------------------------------------------------------

class FeishuMailClient:
    """Thin wrapper around Feishu Mail API."""

    def __init__(self):
        self._token: Optional[str] = None
        self._token_expiry: float = 0
        self._session = requests.Session()

    def _get_token(self) -> str:
        """Get or refresh tenant_access_token."""
        now = time.time()
        if self._token and now < self._token_expiry:
            return self._token

        resp = self._session.post(TOKEN_URL, json={
            'app_id': FEISHU_APP_ID,
            'app_secret': FEISHU_APP_SECRET,
        })
        data = resp.json()
        if data.get('code') != 0:
            raise RuntimeError(f"Feishu token error: {data.get('msg')}")

        self._token = data['tenant_access_token']
        self._token_expiry = now + data.get('expire', 7200) - 60  # 1min buffer
        return self._token

    def _headers(self) -> dict:
        return {'Authorization': f'Bearer {self._get_token()}'}

    def _mailbox_url(self, path: str) -> str:
        # Manually encode @ since Feishu requires it in the path segment
        # Use a pre-encoded URL to avoid requests double-encoding
        encoded = FEISHU_MAILBOX.replace('@', '%40')
        return f'{FEISHU_BASE}/mail/v1/user_mailboxes/{encoded}/{path}'

    def _get(self, url: str, params: dict = None) -> dict:
        """GET request that avoids re-encoding the pre-encoded URL."""
        if params:
            qs = '&'.join(f'{k}={v}' for k, v in params.items())
            full_url = f'{url}?{qs}'
        else:
            full_url = url
        resp = self._session.get(full_url, headers=self._headers())
        return resp.json()

    def list_message_ids(self, folder_id: str = 'INBOX', page_size: int = 20) -> List[str]:
        """List message IDs in a folder. Returns all pages."""
        ids: List[str] = []
        page_token = None

        while True:
            params = {'folder_id': folder_id, 'page_size': min(page_size, 20)}
            if page_token:
                params['page_token'] = page_token

            data = self._get(self._mailbox_url('messages'), params)
            if data.get('code') != 0:
                raise RuntimeError(f"Feishu list messages error: {data.get('msg')}")

            items = data.get('data', {}).get('items', [])
            ids.extend(items)

            if not data['data'].get('has_more'):
                break
            page_token = data['data'].get('page_token')

        return ids

    def get_message(self, message_id: str) -> dict:
        """Get full message details."""
        data = self._get(self._mailbox_url(f'messages/{message_id}'))
        if data.get('code') != 0:
            raise RuntimeError(f"Feishu get message error: {data.get('msg')}")
        return data['data']['message']


# ------------------------------------------------------------------
# Substack email parsing
# ------------------------------------------------------------------

def _extract_original_sender(text: str) -> Optional[str]:
    """Extract original Substack sender from forwarded email body."""
    match = SUBSTACK_SENDER_PATTERN.search(text)
    if match:
        return match.group(0)
    return None


def _extract_author_name(text: str) -> str:
    """Extract author display name from forwarded header."""
    # Pattern: "发件人: Author Name <email>" or "From: Author Name <email>"
    m = re.search(r'(?:发件人|From)\s*[:：]\s*(.+?)\s*<', text)
    if m:
        name = m.group(1).strip()
        # Clean common suffixes like "from Author's Substack"
        name = re.sub(r'\s+from\s+.*$', '', name, flags=re.IGNORECASE)
        return name
    return 'Unknown'


def _extract_substack_url(html: str) -> str:
    """Extract the main Substack post URL from email HTML."""
    # Direct post links: authorname.substack.com/p/post-slug
    direct = re.findall(r'href="(https://[\w.-]+\.substack\.com/p/[\w-]+)', html)
    if direct:
        return direct[0]

    # Substack redirect links encode the real URL in base64 JWT
    # Try to decode the destination from redirect URLs
    redirects = re.findall(r'href="(https://substack\.com/redirect/2/[^"]+)"', html)
    for redirect_url in redirects:
        try:
            # JWT payload is the second segment
            token = redirect_url.split('/redirect/2/')[1].split('?')[0]
            # Decode JWT payload (second part)
            parts = token.split('.')
            if len(parts) >= 2:
                payload_b64 = parts[0]
                payload_b64 = payload_b64.replace('-', '+').replace('_', '/')
                padding = 4 - len(payload_b64) % 4
                if padding != 4:
                    payload_b64 += '=' * padding
                import base64, json as _json
                payload = _json.loads(base64.b64decode(payload_b64))
                target = payload.get('e', '')
                if '.substack.com/p/' in target:
                    return target.split('?')[0]
                # Also check subscribe links that embed the post path
                if '.substack.com/subscribe' in target and 'next=' in target:
                    import urllib.parse
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(target).query)
                    next_url = parsed.get('next', [''])[0]
                    if '/p/' in next_url:
                        return next_url.split('?')[0]
        except Exception:
            continue

    return ''


ARTICLE_FETCH_TIMEOUT = 5          # seconds per URL request
ARTICLE_FETCH_MAX_CHARS = 1500     # chars of body text to keep (enough for classifier)
ARTICLE_FETCH_MIN_BODY = 500       # only fetch URL if email body is shorter than this


def _fetch_article_body(url: str) -> str:
    """
    Fetch the first ARTICLE_FETCH_MAX_CHARS chars of a Substack article body.
    Used when the forwarded email only contains a teaser.
    Returns '' on any failure (network error, paywall, timeout).
    """
    if not url:
        return ''
    try:
        resp = requests.get(
            url,
            timeout=ARTICLE_FETCH_TIMEOUT,
            headers={'User-Agent': 'Mozilla/5.0'},
        )
        if resp.status_code != 200:
            return ''
        # Extract text from Substack article HTML
        extractor = _HTMLTextExtractor()
        extractor.feed(resp.text)
        body = extractor.get_text()
        # Strip boilerplate navigation/header text that appears before the article
        # Substack pages have the article after a consistent pattern
        for marker in ['Subscribe', 'Share', 'Listen to this episode']:
            idx = body.find(marker)
            if idx > 0 and idx < 400:
                body = body[idx + len(marker):]
        return body[:ARTICLE_FETCH_MAX_CHARS].strip()
    except Exception:
        return ''


def _clean_subject(subject: str) -> str:
    """Remove forwarding prefixes from subject."""
    return FORWARDED_SUBJECT_PREFIX.sub('', subject).strip()


def _is_substack_email(subject: str, body_text: str) -> bool:
    """Check if an email is a forwarded Substack newsletter."""
    if SUBSTACK_SENDER_PATTERN.search(body_text):
        return True
    if 'substack.com' in body_text.lower():
        return True
    return False


def _extract_article_content(body_text: str) -> str:
    """Extract the article content, stripping forwarded headers and footers."""
    lines = body_text.split('\n')
    content_lines = []
    in_content = False
    skip_header = True

    for line in lines:
        stripped = line.strip()

        # Skip forwarded email header block
        if skip_header:
            if any(stripped.startswith(p) for p in ['发件人:', 'From:', '已发送:', 'Sent:',
                                                     '收件人:', 'To:', '主题:', 'Subject:']):
                continue
            if stripped == '' and not in_content:
                continue
            skip_header = False
            in_content = True

        # Stop at Substack footer
        if any(marker in stripped for marker in [
            'Forwarded this email?',
            'Subscribe here for more',
            'Unsubscribe',
            '© 20',
            'You received this email',
            'Get the app',
        ]):
            break

        if in_content:
            content_lines.append(line)

    return '\n'.join(content_lines).strip()


# ------------------------------------------------------------------
# Main collection function
# ------------------------------------------------------------------

def collect_substack(days: int = 5) -> List[Dict]:
    """
    Collect ALL forwarded Substack emails from Feishu Mail within the
    lookback window. No cap on article count.

    If more than 50 articles are found, narrows to today only as a
    safeguard against runaway ingestion.

    Returns list of standardized report dicts for the pipeline.
    """
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        print("  ⚠ Feishu credentials not configured")
        return []

    client = FeishuMailClient()
    cutoff_ms = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
    today_str = datetime.now().strftime('%Y-%m-%d')

    # List all message IDs in inbox
    print(f"  Fetching inbox messages...")
    message_ids = client.list_message_ids(folder_id='INBOX')
    print(f"  Found {len(message_ids)} messages in inbox")

    reports = []

    for msg_id in message_ids:
        try:
            msg = client.get_message(msg_id)
        except Exception as e:
            print(f"  ⚠ Failed to fetch message {msg_id[:20]}...: {e}")
            continue

        # Date filter
        internal_date = msg.get('internal_date')
        if internal_date and int(internal_date) < cutoff_ms:
            continue

        subject = msg.get('subject', '')

        # Decode body
        body_html_raw = decode_b64url(msg.get('body_html', ''))
        body_text = html_to_text(body_html_raw) if body_html_raw else decode_b64url(msg.get('body_plain_text', ''))

        # Check if this is a Substack email (look for @substack.com sender)
        if not _is_substack_email(subject, body_text):
            continue

        # Parse metadata
        clean_title = _clean_subject(subject)
        author = _extract_author_name(body_text)
        post_url = _extract_substack_url(body_html_raw)
        content = _extract_article_content(body_text)

        # If email is a teaser, try fetching more body from the article URL
        if len(content) < ARTICLE_FETCH_MIN_BODY and post_url:
            fetched = _fetch_article_body(post_url)
            if fetched and len(fetched) > len(content):
                content = fetched

        # Convert internal_date (ms) to YYYY-MM-DD
        if internal_date:
            dt = datetime.fromtimestamp(int(internal_date) / 1000)
            date_str = dt.strftime('%Y-%m-%d')
        else:
            date_str = today_str

        if not content or len(content) < 50:
            print(f"  ⚠ Skipped (content too short: {len(content or '')} chars): {clean_title[:50]}")
            continue

        reports.append({
            'title': clean_title,
            'url': post_url,
            'pdf_url': '',
            'analyst': author,
            'source': 'substack',
            'source_type': 'substack',
            'date': date_str,
            'content': content,
        })

        print(f"  ✓ {clean_title[:60]}... ({author})")

    # Safeguard: if >50 articles, narrow to today only
    if len(reports) > 50:
        print(f"  ⚠ {len(reports)} articles found — narrowing to today only")
        reports = [r for r in reports if r['date'] == today_str]
        print(f"  → {len(reports)} articles from today")

    return reports


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Substack Ingestion via Feishu Mail — Test")
    print("=" * 60)

    articles = collect_substack(days=7)

    print(f"\n{'=' * 60}")
    print(f"Results: {len(articles)} Substack articles found")
    print("=" * 60)

    for i, a in enumerate(articles, 1):
        print(f"\n--- Article {i} ---")
        print(f"  Title:   {a['title']}")
        print(f"  Author:  {a['analyst']}")
        print(f"  Date:    {a['date']}")
        print(f"  URL:     {a['url']}")
        print(f"  Content: {len(a['content'])} chars")
        print(f"  Preview: {a['content'][:200]}...")

    # Verification
    print(f"\n{'=' * 60}")
    print("Verification")
    print("=" * 60)

    if articles:
        for a in articles:
            assert a['source'] == 'substack', "Source should be 'substack'"
            assert a['title'], "Title should not be empty"
            assert a['content'], "Content should not be empty"
            assert a['date'], "Date should not be empty"
        print(f"✓ All {len(articles)} articles pass validation")
    else:
        print("⚠ No articles found — check Feishu mailbox has forwarded Substack emails")

    print("\nSubstack ingestion module ready for pipeline integration.")
