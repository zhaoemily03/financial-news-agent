"""
User database — multi-user support for web UI.

Tables:
  users               — credentials + display info
  user_config         — per-user key/value config (tickers, sources, investment_themes)
  briefings           — stored HTML/markdown briefings per user per day
  portal_auth_status  — tracks portal authentication state per user
  portal_credentials  — encrypted per-user portal login credentials

Pattern mirrors existing claim_tracker.py / report_tracker.py.
"""

import json
import sqlite3
import os
import hashlib
import base64
from datetime import datetime, date
from typing import Optional, List
from werkzeug.security import generate_password_hash as _gen_hash, check_password_hash

# Encryption key: prefer FLASK_SECRET_KEY (same as app.py), fall back to SECRET_KEY.
# Set FLASK_SECRET_KEY in .env for consistent credential encryption across restarts.
_SECRET_KEY = os.getenv('FLASK_SECRET_KEY') or os.getenv('SECRET_KEY', 'dev-key-change-in-prod')


def _get_fernet():
    """Return a Fernet instance keyed from SECRET_KEY."""
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(_SECRET_KEY.encode()).digest())
    return Fernet(key)


def _encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


def generate_password_hash(password: str) -> str:
    # Use pbkdf2:sha256 — compatible with Python builds that lack OpenSSL scrypt
    return _gen_hash(password, method='pbkdf2:sha256')

DB_PATH = 'data/users.db'

# Default source config keys seeded from config.py on user creation
_PORTAL_NAMES = ['jefferies', 'morgan_stanley', 'goldman', 'bernstein', 'arete', 'ubs', 'macquarie']
_PODCAST_NAMES = ['all-in', 'bg2', 'acquired', 'a16z']


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def _init_db():
    conn = _conn()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        username     TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        created_at   TEXT NOT NULL,
        last_login   TEXT
    )''')

    # Key-value config per user. Values are JSON-serialized.
    # config_key in: tickers_primary, tickers_watchlist,
    #                sources_portals, sources_podcasts, sources_other
    c.execute('''CREATE TABLE IF NOT EXISTS user_config (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL REFERENCES users(id),
        config_key   TEXT NOT NULL,
        config_value TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        UNIQUE(user_id, config_key)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS briefings (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id          INTEGER NOT NULL REFERENCES users(id),
        briefing_date    TEXT NOT NULL,
        run_type         TEXT NOT NULL,
        html_content     TEXT NOT NULL,
        markdown_content TEXT NOT NULL,
        claim_ids        TEXT,
        word_count       INTEGER,
        created_at       TEXT NOT NULL,
        UNIQUE(user_id, briefing_date, run_type)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS portal_auth_status (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL REFERENCES users(id),
        portal_name     TEXT NOT NULL,
        auth_status     TEXT NOT NULL,
        last_checked    TEXT,
        last_success    TEXT,
        failure_message TEXT,
        UNIQUE(user_id, portal_name)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS portal_credentials (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL REFERENCES users(id),
        portal          TEXT NOT NULL,
        cred_type       TEXT NOT NULL,
        encrypted_value TEXT NOT NULL,
        updated_at      TEXT NOT NULL,
        UNIQUE(user_id, portal, cred_type)
    )''')

    c.execute('CREATE INDEX IF NOT EXISTS idx_briefings_user_date ON briefings(user_id, briefing_date)')
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# User management
# ------------------------------------------------------------------

def create_user(username: str, display_name: str, password: str) -> int:
    """Create a new user, seed default config. Returns user_id."""
    _init_db()
    conn = _conn()
    c = conn.cursor()
    try:
        c.execute(
            'INSERT INTO users (username, display_name, password_hash, created_at) VALUES (?,?,?,?)',
            (username, display_name, generate_password_hash(password), datetime.now().isoformat())
        )
        user_id = c.lastrowid
        conn.commit()
    finally:
        conn.close()

    seed_default_config(user_id)
    print(f"  ✓ Created user '{username}' (id={user_id})")
    return user_id


def authenticate(username: str, password: str) -> Optional[dict]:
    """Check credentials. Returns user dict or None."""
    conn = _conn()
    c = conn.cursor()
    c.execute('SELECT id, username, display_name, password_hash FROM users WHERE username=?', (username,))
    row = c.fetchone()
    conn.close()
    if row and check_password_hash(row[3], password):
        return {'id': row[0], 'username': row[1], 'display_name': row[2]}
    return None


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = _conn()
    c = conn.cursor()
    c.execute('SELECT id, username, display_name FROM users WHERE id=?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'username': row[1], 'display_name': row[2]}
    return None


def update_last_login(user_id: int):
    conn = _conn()
    conn.execute('UPDATE users SET last_login=? WHERE id=?', (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()


def get_all_users() -> list:
    conn = _conn()
    c = conn.cursor()
    c.execute('SELECT id, username, display_name FROM users')
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'username': r[1], 'display_name': r[2]} for r in rows]


# ------------------------------------------------------------------
# User config
# ------------------------------------------------------------------

def seed_default_config(user_id: int):
    """Seed per-user config from global config.py defaults."""
    import config

    primary = (
        config.TICKERS.get('primary_internet', []) +
        config.TICKERS.get('primary_software', [])
    )
    watchlist = (
        config.TICKERS.get('watchlist_internet', []) +
        config.TICKERS.get('watchlist_software', [])
    )

    portals = {
        name: {'enabled': config.SOURCES.get(name, {}).get('enabled', False)}
        for name in _PORTAL_NAMES
    }
    podcasts = {
        name: {'enabled': config.SOURCES.get('podcasts', {}).get('sources', {}).get(name, {}).get('enabled', False)}
        for name in _PODCAST_NAMES
    }
    other = {
        'substack': {'enabled': config.SOURCES.get('substack', {}).get('enabled', False)},
        'macro_news': {'enabled': config.MACRO_NEWS.get('enabled', True)},
    }

    # Seed investment themes from global config (user can add/edit/remove up to 5 via Settings)
    default_themes = [
        {'name': t['name'], 'keywords': t.get('keywords', [])}
        for t in config.INVESTMENT_THEMES
    ]

    for key, val in [
        ('tickers_primary', list(dict.fromkeys(primary))),  # deduplicated, order-preserving
        ('tickers_watchlist', list(dict.fromkeys(watchlist))),
        ('sources_portals', portals),
        ('sources_podcasts', podcasts),
        ('sources_other', other),
        ('investment_themes', default_themes),
    ]:
        _set_config(user_id, key, val)


def _set_config(user_id: int, key: str, value):
    conn = _conn()
    conn.execute(
        'INSERT OR REPLACE INTO user_config (user_id, config_key, config_value, updated_at) VALUES (?,?,?,?)',
        (user_id, key, json.dumps(value), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_user_config(user_id: int) -> dict:
    """Return full config dict for a user."""
    conn = _conn()
    c = conn.cursor()
    c.execute('SELECT config_key, config_value FROM user_config WHERE user_id=?', (user_id,))
    rows = c.fetchall()
    conn.close()
    return {row[0]: json.loads(row[1]) for row in rows}


def add_ticker(user_id: int, ticker: str, tier: str = 'primary'):
    """tier: 'primary' or 'watchlist'"""
    key = f'tickers_{tier}'
    cfg = get_user_config(user_id)
    tickers = cfg.get(key, [])
    ticker = ticker.upper().strip()
    if ticker and ticker not in tickers:
        tickers.append(ticker)
        _set_config(user_id, key, tickers)


def remove_ticker(user_id: int, ticker: str, tier: str = 'primary'):
    key = f'tickers_{tier}'
    cfg = get_user_config(user_id)
    tickers = [t for t in cfg.get(key, []) if t != ticker.upper()]
    _set_config(user_id, key, tickers)


def toggle_source(user_id: int, source_type: str, source_name: str, enabled: bool):
    """source_type: 'portals' | 'podcasts' | 'other'"""
    key = f'sources_{source_type}'
    cfg = get_user_config(user_id)
    sources = cfg.get(key, {})
    if source_name in sources:
        sources[source_name]['enabled'] = enabled
        _set_config(user_id, key, sources)


# ------------------------------------------------------------------
# Investment themes
# ------------------------------------------------------------------

def get_investment_themes(user_id: int) -> List[dict]:
    """Return list of {name, keywords} dicts for the user (max 5)."""
    cfg = get_user_config(user_id)
    return cfg.get('investment_themes', [])


def set_investment_themes(user_id: int, themes: List[dict]):
    """Replace all investment themes for the user."""
    _set_config(user_id, 'investment_themes', themes[:5])


def add_theme(user_id: int, name: str, keywords: List[str]) -> bool:
    """Add an investment theme. Returns False if already at 5 themes or name already exists."""
    themes = get_investment_themes(user_id)
    if len(themes) >= 5:
        return False
    # Prevent duplicate names (case-insensitive)
    if any(t['name'].lower() == name.lower() for t in themes):
        return False
    themes.append({'name': name, 'keywords': keywords})
    _set_config(user_id, 'investment_themes', themes)
    return True


def remove_theme(user_id: int, name: str):
    """Remove a theme by name (case-insensitive match)."""
    themes = [t for t in get_investment_themes(user_id) if t['name'].lower() != name.lower()]
    _set_config(user_id, 'investment_themes', themes)


def update_theme_keywords(user_id: int, name: str, keywords: List[str]):
    """Update the keywords for an existing theme."""
    themes = get_investment_themes(user_id)
    for t in themes:
        if t['name'].lower() == name.lower():
            t['keywords'] = keywords
            break
    _set_config(user_id, 'investment_themes', themes)


# ------------------------------------------------------------------
# Portal credentials (encrypted per-user)
# ------------------------------------------------------------------

def store_portal_credential(user_id: int, portal: str, cred_type: str, value: str):
    """Encrypt and store a credential. cred_type: 'email', 'password', 'refresh_token', 'csrf_token'."""
    encrypted = _encrypt(value)
    conn = _conn()
    conn.execute(
        '''INSERT OR REPLACE INTO portal_credentials
           (user_id, portal, cred_type, encrypted_value, updated_at)
           VALUES (?,?,?,?,?)''',
        (user_id, portal, cred_type, encrypted, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_portal_credential(user_id: int, portal: str, cred_type: str) -> Optional[str]:
    """Decrypt and return a single credential value, or None if not set."""
    conn = _conn()
    c = conn.cursor()
    c.execute(
        'SELECT encrypted_value FROM portal_credentials WHERE user_id=? AND portal=? AND cred_type=?',
        (user_id, portal, cred_type)
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    try:
        return _decrypt(row[0])
    except Exception:
        return None


def get_user_portal_credentials(user_id: int, portal: str) -> dict:
    """Return all credential types for a portal as a dict (decrypted). Empty dict if none saved."""
    conn = _conn()
    c = conn.cursor()
    c.execute(
        'SELECT cred_type, encrypted_value FROM portal_credentials WHERE user_id=? AND portal=?',
        (user_id, portal)
    )
    rows = c.fetchall()
    conn.close()
    result = {}
    for cred_type, encrypted_value in rows:
        try:
            result[cred_type] = _decrypt(encrypted_value)
        except Exception:
            pass  # Corrupted entry — skip silently
    return result


# ------------------------------------------------------------------
# Briefings
# ------------------------------------------------------------------

def store_briefing(user_id: int, briefing_date: str, run_type: str,
                   html_content: str, markdown_content: str,
                   claim_ids: list = None, word_count: int = None):
    conn = _conn()
    conn.execute(
        '''INSERT OR REPLACE INTO briefings
           (user_id, briefing_date, run_type, html_content, markdown_content,
            claim_ids, word_count, created_at)
           VALUES (?,?,?,?,?,?,?,?)''',
        (user_id, briefing_date, run_type, html_content, markdown_content,
         json.dumps(claim_ids or []), word_count, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_briefing(user_id: int, briefing_date: str, run_type: str = 'morning') -> Optional[dict]:
    conn = _conn()
    c = conn.cursor()
    c.execute(
        '''SELECT html_content, markdown_content, claim_ids, word_count, created_at
           FROM briefings WHERE user_id=? AND briefing_date=? AND run_type=?''',
        (user_id, briefing_date, run_type)
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        'html': row[0], 'markdown': row[1],
        'claim_ids': json.loads(row[2] or '[]'),
        'word_count': row[3], 'created_at': row[4],
    }


def get_briefings_list(user_id: int, limit: int = 30) -> list:
    conn = _conn()
    c = conn.cursor()
    c.execute(
        '''SELECT briefing_date, run_type, word_count, created_at
           FROM briefings WHERE user_id=?
           ORDER BY briefing_date DESC, run_type ASC LIMIT ?''',
        (user_id, limit)
    )
    rows = c.fetchall()
    conn.close()
    return [{'date': r[0], 'run_type': r[1], 'word_count': r[2], 'created_at': r[3]} for r in rows]


# ------------------------------------------------------------------
# Portal auth status
# ------------------------------------------------------------------

def update_auth_status(user_id: int, portal_name: str, status: str,
                       message: str = None, success: bool = False):
    now = datetime.now().isoformat()
    conn = _conn()
    if success:
        conn.execute(
            '''INSERT OR REPLACE INTO portal_auth_status
               (user_id, portal_name, auth_status, last_checked, last_success, failure_message)
               VALUES (?,?,?,?,?,NULL)''',
            (user_id, portal_name, 'authenticated', now, now)
        )
    else:
        conn.execute(
            '''INSERT OR REPLACE INTO portal_auth_status
               (user_id, portal_name, auth_status, last_checked, failure_message)
               VALUES (?,?,?,?,?)''',
            (user_id, portal_name, status, now, message)
        )
    conn.commit()
    conn.close()


def get_auth_statuses(user_id: int) -> list:
    conn = _conn()
    c = conn.cursor()
    c.execute(
        '''SELECT portal_name, auth_status, last_checked, last_success, failure_message
           FROM portal_auth_status WHERE user_id=?''',
        (user_id,)
    )
    rows = c.fetchall()
    conn.close()
    return [
        {'portal': r[0], 'status': r[1], 'last_checked': r[2],
         'last_success': r[3], 'message': r[4]}
        for r in rows
    ]


# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------

if __name__ == '__main__':
    import getpass
    _init_db()
    print("\n=== Financial News Agent — User Setup ===\n")
    username = input("Username: ").strip()
    display_name = input("Display name: ").strip()
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("✗ Passwords do not match.")
    else:
        user_id = create_user(username, display_name, password)
        print(f"✓ User created. Log in at http://localhost:5000/login")
