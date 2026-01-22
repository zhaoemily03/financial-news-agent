from flask import Flask, render_template, request, jsonify, session
import os
import json
import uuid
from dotenv import load_dotenv
from briefing_generator import BriefingGenerator

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default-secret-key')

# Simple in-memory storage (will upgrade to database later)
# In production, this should be a proper database
USER_DATA_FILE = 'data/user_data.json'

def load_user_data():
    """Load user data from JSON file"""
    if os.path.exists(USER_DATA_FILE):
        with open(USER_DATA_FILE, 'r') as f:
            return json.load(f)
    return {
        'tickers': [],
        'sources': {'sellside': [], 'substack': []},
        'themes': [],
        'settings': {}
    }

def save_user_data(data):
    """Save user data to JSON file"""
    os.makedirs('data', exist_ok=True)
    with open(USER_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

# Authentication
@app.route('/api/login', methods=['POST'])
def api_login():
    """Handle analyst login"""
    username = request.json.get('username')
    password = request.json.get('password')

    # Simple authentication (in production, use proper auth)
    # For now, accept any username/password
    session['analyst_username'] = username
    session['logged_in'] = True

    return jsonify({'status': 'success', 'username': username})

# Ticker Management
@app.route('/api/tickers', methods=['POST'])
def add_ticker():
    """Add a ticker to coverage"""
    ticker = request.json.get('ticker')

    data = load_user_data()
    if ticker and ticker not in data['tickers']:
        data['tickers'].append(ticker)
        save_user_data(data)

    return jsonify({'status': 'success', 'ticker': ticker})

@app.route('/api/tickers/<ticker>', methods=['DELETE'])
def delete_ticker(ticker):
    """Remove a ticker from coverage"""
    data = load_user_data()
    if ticker in data['tickers']:
        data['tickers'].remove(ticker)
        save_user_data(data)

    return jsonify({'status': 'success'})

# Sell-Side Source Management
@app.route('/api/sources/sellside', methods=['POST'])
def add_sellside_source():
    """Add a sell-side research source"""
    source = request.json
    source['id'] = str(uuid.uuid4())

    data = load_user_data()
    data['sources']['sellside'].append(source)
    save_user_data(data)

    return jsonify({'status': 'success', 'id': source['id']})

@app.route('/api/sources/sellside/<source_id>', methods=['DELETE'])
def delete_sellside_source(source_id):
    """Remove a sell-side source"""
    data = load_user_data()
    data['sources']['sellside'] = [s for s in data['sources']['sellside'] if s['id'] != source_id]
    save_user_data(data)

    return jsonify({'status': 'success'})

# Substack Source Management
@app.route('/api/sources/substack', methods=['POST'])
def add_substack_source():
    """Add a Substack source"""
    source = request.json
    source['id'] = str(uuid.uuid4())

    data = load_user_data()
    data['sources']['substack'].append(source)
    save_user_data(data)

    return jsonify({'status': 'success', 'id': source['id']})

@app.route('/api/sources/substack/<source_id>', methods=['DELETE'])
def delete_substack_source(source_id):
    """Remove a Substack source"""
    data = load_user_data()
    data['sources']['substack'] = [s for s in data['sources']['substack'] if s['id'] != source_id]
    save_user_data(data)

    return jsonify({'status': 'success'})

# Theme Management
@app.route('/api/themes', methods=['POST'])
def add_theme():
    """Add an investment theme"""
    theme = request.json
    theme['id'] = str(uuid.uuid4())

    data = load_user_data()
    data['themes'].append(theme)
    save_user_data(data)

    return jsonify({'status': 'success', 'id': theme['id']})

@app.route('/api/themes/<theme_id>', methods=['DELETE'])
def delete_theme(theme_id):
    """Remove an investment theme"""
    data = load_user_data()
    data['themes'] = [t for t in data['themes'] if t['id'] != theme_id]
    save_user_data(data)

    return jsonify({'status': 'success'})

# Settings Management
@app.route('/api/settings', methods=['POST'])
def save_settings():
    """Save user settings"""
    settings = request.json

    data = load_user_data()
    data['settings'] = settings
    save_user_data(data)

    # Update .env file with OpenAI key if provided
    if settings.get('openaiKey'):
        update_env_variable('OPENAI_API_KEY', settings['openaiKey'])

    return jsonify({'status': 'success'})

def update_env_variable(key, value):
    """Update .env file with new value"""
    env_path = '.env'
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            lines = f.readlines()

        found = False
        for i, line in enumerate(lines):
            if line.startswith(f'{key}='):
                lines[i] = f'{key}={value}\n'
                found = True
                break

        if not found:
            lines.append(f'{key}={value}\n')

        with open(env_path, 'w') as f:
            f.writelines(lines)

# User Data
@app.route('/api/user-data', methods=['GET'])
def get_user_data():
    """Get all user configuration data"""
    data = load_user_data()
    return jsonify({'status': 'success', **data})

# Manual Actions
@app.route('/api/generate-briefing', methods=['POST'])
def generate_test_briefing():
    """Generate a test briefing"""
    try:
        data = load_user_data()

        # Sample content for testing
        sample_content = [{
            'title': 'Sample Financial Report',
            'source': 'Test Source',
            'date': '2026-01-21',
            'url': 'https://example.com',
            'content': 'Sample content for testing the briefing generator.'
        }]

        generator = BriefingGenerator()
        briefing = generator.generate_briefing(
            sample_content,
            data.get('tickers', []),
            [t['name'] for t in data.get('themes', [])]
        )

        return jsonify({'status': 'success', 'briefing': briefing})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/test-email', methods=['POST'])
def send_test_email():
    """Send a test email"""
    try:
        data = load_user_data()
        email = data.get('settings', {}).get('emailRecipient')

        if not email:
            return jsonify({'status': 'error', 'message': 'No email configured'}), 400

        # Email sending will be implemented in email module
        # For now, just return success
        return jsonify({
            'status': 'success',
            'message': f'Test email would be sent to {email}'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=os.getenv('DEBUG', 'True') == 'True', host='127.0.0.1', port=5000)
