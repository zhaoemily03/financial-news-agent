"""
Financial News Agent — Flask web application.

Run:
    python3 app.py

First-time setup (create users):
    python3 user_db.py
"""

import os
from flask import Flask
from dotenv import load_dotenv

load_dotenv()


def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(32).hex())

    from web.auth import bp as auth_bp
    from web.views import bp as views_bp
    from web.api import bp as api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix='/api')

    # Phase 4: scheduler init goes here
    # from scheduler import init_scheduler
    # init_scheduler(app)

    return app


if __name__ == '__main__':
    app = create_app()
    port = int(os.getenv('PORT', 8080))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    print(f"\n  Financial News Agent running on http://localhost:{port}")
    print(f"  First time? Run: python user_db.py\n")
    app.run(host='0.0.0.0', port=port, debug=debug)
