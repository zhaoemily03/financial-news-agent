"""Authentication blueprint — login/logout."""

from flask import Blueprint, render_template, request, session, redirect, url_for, flash
import user_db

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('views.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = user_db.authenticate(username, password)
        if user:
            session['user_id'] = user['id']
            session['display_name'] = user['display_name']
            user_db.update_last_login(user['id'])
            return redirect(url_for('views.dashboard'))
        flash('Invalid username or password.')

    return render_template('login.html')


@bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
