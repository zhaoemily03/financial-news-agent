"""Main view routes — dashboard, settings, history."""

import os
import re
import glob
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Blueprint, render_template, request, session, redirect, url_for, flash
import user_db

bp = Blueprint('views', __name__)

# Display names for portals and podcasts shown in the UI
PORTAL_LABELS = {
    'jefferies': 'Jefferies',
    'morgan_stanley': 'Morgan Stanley',
    'goldman': 'Goldman Sachs',
    'bernstein': 'Bernstein',
    'arete': 'Arete',
    'ubs': 'UBS',
    'macquarie': 'Macquarie',
}
PODCAST_LABELS = {
    'all-in': 'All-In Podcast',
    'bg2': 'BG2 Pod',
    'acquired': 'Acquired',
    'a16z': 'a16z Podcast',
}
OTHER_LABELS = {
    'substack': 'Substack (Feishu Mail)',
    'macro_news': 'Macro News (RSS)',
}

# Portals that use email+password credentials (managed via Settings > Portal Credentials)
CREDENTIAL_PORTALS = {
    'goldman': {'label': 'Goldman Sachs', 'fields': ['email', 'password']},
    'bernstein': {'label': 'Bernstein', 'fields': ['email', 'password']},
    'arete': {'label': 'Arete', 'fields': ['email', 'password']},
    'ubs': {'label': 'UBS', 'fields': ['email', 'password']},
    'macquarie': {'label': 'Macquarie Insights', 'fields': ['refresh_token', 'csrf_token']},
}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def _current_user():
    return {
        'id': session['user_id'],
        'display_name': session.get('display_name', ''),
    }


def _validate_ticker_format(ticker: str) -> bool:
    """Accept 1-6 uppercase alphanumeric chars + optional .XX exchange suffix (e.g. 700.HK)."""
    return bool(re.match(r'^[A-Z0-9]{1,6}(\.[A-Z]{2})?$', ticker))


def _load_briefing_for_date(user_id: int, target_date: str):
    """Load morning + midday briefings. Falls back to markdown files from disk."""
    morning = user_db.get_briefing(user_id, target_date, 'morning')
    midday = user_db.get_briefing(user_id, target_date, 'midday')

    # Phase 1 fallback: render latest .md file from disk as HTML
    if not morning and not midday:
        morning = _load_md_fallback(target_date)

    return morning, midday


def _load_md_fallback(target_date: str):
    """Find a .md briefing file matching the date and render it as basic HTML."""
    try:
        import markdown as md_lib
        pattern = f'data/briefings/briefing_{target_date}*.md'
        files = sorted(glob.glob(pattern), reverse=True)
        if not files:
            # Fall back to most recent file regardless of date
            all_files = sorted(glob.glob('data/briefings/briefing_*.md'), reverse=True)
            if not all_files:
                return None
            files = [all_files[0]]
        with open(files[0], 'r') as f:
            raw = f.read()
        html = md_lib.markdown(raw, extensions=['tables'])
        return {'html': html, 'markdown': raw, 'word_count': len(raw.split()), 'from_file': True}
    except Exception:
        return None


@bp.route('/')
def index():
    if session.get('user_id'):
        return redirect(url_for('views.dashboard'))
    return redirect(url_for('auth.login'))


@bp.route('/dashboard')
@login_required
def dashboard():
    today = date.today().isoformat()
    return redirect(url_for('views.dashboard_date', target_date=today))


@bp.route('/dashboard/<target_date>')
@login_required
def dashboard_date(target_date):
    user = _current_user()
    try:
        dt = datetime.strptime(target_date, '%Y-%m-%d').date()
    except ValueError:
        return redirect(url_for('views.dashboard'))

    morning, midday = _load_briefing_for_date(user['id'], target_date)

    prev_date = (dt - timedelta(days=1)).isoformat()
    next_date = (dt + timedelta(days=1)).isoformat()
    today = date.today().isoformat()

    return render_template(
        'dashboard.html',
        user=user,
        briefing_date=target_date,
        morning=morning,
        midday=midday,
        prev_date=prev_date,
        next_date=next_date if target_date < today else None,
        today=today,
    )


@bp.route('/settings')
@login_required
def settings():
    user = _current_user()
    cfg = user_db.get_user_config(user['id'])
    investment_themes = user_db.get_investment_themes(user['id'])

    # Whether each credential portal has at least one saved credential
    portal_cred_status = {
        portal: bool(user_db.get_user_portal_credentials(user['id'], portal))
        for portal in CREDENTIAL_PORTALS
    }

    return render_template(
        'settings.html',
        user=user,
        tickers_primary=cfg.get('tickers_primary', []),
        tickers_watchlist=cfg.get('tickers_watchlist', []),
        sources_portals=cfg.get('sources_portals', {}),
        sources_podcasts=cfg.get('sources_podcasts', {}),
        sources_other=cfg.get('sources_other', {}),
        portal_labels=PORTAL_LABELS,
        podcast_labels=PODCAST_LABELS,
        other_labels=OTHER_LABELS,
        investment_themes=investment_themes,
        portal_cred_status=portal_cred_status,
        credential_portals=CREDENTIAL_PORTALS,
    )


@bp.route('/settings/tickers', methods=['POST'])
@login_required
def settings_tickers():
    user = _current_user()
    action = request.form.get('action')
    ticker = request.form.get('ticker', '').strip().upper()
    tier = request.form.get('tier', 'primary')

    if tier not in ('primary', 'watchlist'):
        flash('Invalid tier.')
        return redirect(url_for('views.settings'))

    if action == 'add' and ticker:
        if not _validate_ticker_format(ticker):
            flash(
                f'"{ticker}" does not look like a valid ticker symbol. '
                'Expected 1–6 uppercase letters/digits, optionally followed by .XX exchange suffix '
                '(e.g. NVDA, 700.HK, MSFT).'
            )
            return redirect(url_for('views.settings'))
        user_db.add_ticker(user['id'], ticker, tier)
    elif action == 'remove' and ticker:
        user_db.remove_ticker(user['id'], ticker, tier)

    return redirect(url_for('views.settings'))


@bp.route('/settings/sources', methods=['POST'])
@login_required
def settings_sources():
    user = _current_user()

    # Rebuild each source group from the submitted checkboxes
    for source_type, source_names in [
        ('portals', list(PORTAL_LABELS.keys())),
        ('podcasts', list(PODCAST_LABELS.keys())),
        ('other', list(OTHER_LABELS.keys())),
    ]:
        for name in source_names:
            enabled = f'{source_type}_{name}' in request.form
            user_db.toggle_source(user['id'], source_type, name, enabled)

    flash('Source settings saved.')
    return redirect(url_for('views.settings'))


@bp.route('/settings/themes/add', methods=['POST'])
@login_required
def settings_themes_add():
    user = _current_user()
    theme_name = request.form.get('theme_name', '').strip()
    keywords_raw = request.form.get('keywords', '').strip()
    keywords = [k.strip() for k in keywords_raw.split(',') if k.strip()] if keywords_raw else []

    if not theme_name:
        flash('Theme name is required.')
        return redirect(url_for('views.settings'))

    ok = user_db.add_theme(user['id'], theme_name, keywords)
    if not ok:
        existing = user_db.get_investment_themes(user['id'])
        if len(existing) >= 5:
            flash('Maximum 5 investment themes reached. Remove one before adding another.')
        else:
            flash(f'A theme named "{theme_name}" already exists.')

    return redirect(url_for('views.settings'))


@bp.route('/settings/themes/remove', methods=['POST'])
@login_required
def settings_themes_remove():
    user = _current_user()
    theme_name = request.form.get('theme_name', '').strip()
    if theme_name:
        user_db.remove_theme(user['id'], theme_name)
    return redirect(url_for('views.settings'))


@bp.route('/settings/credentials/<portal>', methods=['POST'])
@login_required
def settings_credentials(portal):
    user = _current_user()
    if portal not in CREDENTIAL_PORTALS:
        flash('Unknown portal.')
        return redirect(url_for('views.settings'))

    fields = CREDENTIAL_PORTALS[portal]['fields']
    saved = 0
    for field in fields:
        value = request.form.get(field, '').strip()
        if value:
            user_db.store_portal_credential(user['id'], portal, field, value)
            saved += 1

    if saved:
        label = CREDENTIAL_PORTALS[portal]['label']
        flash(f'Credentials updated for {label}.')
    else:
        flash('No credentials provided — nothing saved.')

    return redirect(url_for('views.settings'))


@bp.route('/history')
@login_required
def history():
    user = _current_user()
    briefings = user_db.get_briefings_list(user['id'], limit=60)
    return render_template('history.html', user=user, briefings=briefings)
