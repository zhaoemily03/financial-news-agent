"""
API blueprint — AJAX/htmx endpoints.

Phase 1: auth-status + theme keyword suggestion.
Phase 3: full reauth flow.
Phase 5: drilldown + manual pipeline trigger.
"""

import json
from flask import Blueprint, jsonify, session, render_template_string, request
from functools import wraps
import user_db

bp = Blueprint('api', __name__)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


@bp.route('/auth-status')
@login_required
def auth_status():
    """
    Returns HTML partial for the auth alert banner.
    Checked on page load and every 5 minutes via htmx.
    """
    user_id = session['user_id']
    statuses = user_db.get_auth_statuses(user_id)
    failed = [s for s in statuses if s['status'] == 'failed']

    if not failed:
        return ''  # Empty = no banner shown

    PORTAL_DISPLAY = {
        'jefferies': 'Jefferies',
        'morgan_stanley': 'Morgan Stanley',
        'jpmorgan': 'J.P. Morgan',
        'goldman': 'Goldman Sachs',
        'bernstein': 'Bernstein',
        'arete': 'Arete',
        'ubs': 'UBS',
        'macquarie': 'Macquarie',
        'wells_fargo': 'Wells Fargo',
    }

    # Tier 4 portals (2FA) — require interactive login, not just credential update
    TIER4_PORTALS = {'jefferies', 'morgan_stanley', 'jpmorgan', 'macquarie', 'wells_fargo'}

    return render_template_string('''
    {% for s in failed %}
    <div class="auth-alert">
      <strong>&#9888; {{ labels.get(s.portal, s.portal) }} authentication required</strong>
      {% if s.message %}<p>{{ s.message }}</p>{% endif %}
      {% if s.portal == "morgan_stanley" %}
        <p>Paste your Morgan Stanley email verification link:</p>
        <form method="post" action="/api/reauth/morgan_stanley/verify" style="display:flex;gap:8px;align-items:center">
          <input type="text" name="verify_link" placeholder="https://login.matrix.ms.com/..." style="flex:1;min-width:300px">
          <button type="submit">Submit</button>
        </form>
      {% elif s.portal in tier4 %}
        <p>This portal uses 2FA. Run the following command in your terminal to re-authenticate:</p>
        <code style="display:block;padding:6px 10px;background:#1a1a1a;border-radius:4px;margin:6px 0">
          python refresh_cookies.py --interactive {{ s.portal }}
        </code>
        <p>A browser window will open. Log in, and cookies will be saved automatically.</p>
      {% else %}
        <p>Update credentials in
           <a href="/settings#portal-credentials">Settings → Portal Credentials</a>.
           The scraper will pick up the new session on the next run.</p>
      {% endif %}
      {% if s.last_success %}<p class="muted">Last success: {{ s.last_success[:10] }}</p>{% endif %}
    </div>
    {% endfor %}
    ''', failed=failed, labels=PORTAL_DISPLAY, tier4=TIER4_PORTALS)


@bp.route('/reauth/<portal>/verify', methods=['POST'])
@login_required
def reauth_verify(portal):
    """Phase 3: Morgan Stanley verification link submission."""
    # Stub — full implementation in Phase 3
    return '<div class="flash">Re-auth flow coming in Phase 3.</div>'


@bp.route('/themes/suggest-keywords', methods=['POST'])
@login_required
def suggest_theme_keywords():
    """
    Use the synthesis LLM to suggest 3 relevant keywords for a given investment theme name.
    Body: {"theme_name": "..."}
    Returns: {"keywords": ["...", "...", "..."]}
    """
    data = request.get_json() or {}
    theme_name = data.get('theme_name', '').strip()
    if not theme_name:
        return jsonify({'error': 'theme_name is required'}), 400

    try:
        from llm_client import llm_complete, is_configured
        if not is_configured('synthesis'):
            return jsonify({'keywords': []}), 200

        prompt = (
            f'You are helping configure a financial research briefing tool for a professional investor.\n\n'
            f'Given the investment theme "{theme_name}", suggest exactly 3 short, specific keyword phrases '
            f'(2–4 words each) that a professional analyst would use when searching for content on this theme. '
            f'Return ONLY a JSON object with a "keywords" array of exactly 3 strings.\n\n'
            f'Example: {{"keywords": ["machine learning", "LLM inference", "AI data centers"]}}'
        )

        raw = llm_complete(
            'synthesis',
            [{'role': 'user', 'content': prompt}],
            max_tokens=100,
            temperature=0,
            json_mode=True,
        )
        result = json.loads(raw)
        keywords = result.get('keywords', [])[:3]
    except Exception:
        keywords = []

    return jsonify({'keywords': keywords})


@bp.route('/drilldown/<claim_id>')
@login_required
def drilldown(claim_id):
    """Phase 5: Returns claim provenance as an HTML partial."""
    return '<div class="drilldown-panel"><p>Drilldown coming in Phase 5.</p></div>'


@bp.route('/run-pipeline', methods=['POST'])
@login_required
def run_pipeline_manual():
    """Phase 5: Manual pipeline trigger."""
    return jsonify({'status': 'Manual trigger coming in Phase 5.'})
