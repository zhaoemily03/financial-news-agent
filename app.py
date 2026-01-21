from flask import Flask, render_template, request, jsonify, session
import os
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import openai

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default-secret-key')

# Configure OpenAI
openai.api_key = os.getenv('OPENAI_API_KEY')

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    """Handle user login"""
    username = request.json.get('username')
    password = request.json.get('password')

    # Store credentials in session
    session['username'] = username
    session['password'] = password

    return jsonify({'status': 'success', 'message': 'Logged in successfully'})

@app.route('/fetch-article', methods=['POST'])
def fetch_article():
    """Fetch article from URL with authentication"""
    url = request.json.get('url')

    # Create session with cookies
    web_session = requests.Session()

    # Add cookies from environment if available
    session_cookie = os.getenv('SESSION_COOKIE')
    if session_cookie:
        # Parse and add cookies
        web_session.cookies.set('session', session_cookie)

    # Add any stored credentials
    if 'username' in session and 'password' in session:
        # This is a placeholder - actual implementation depends on site's auth method
        auth = (session['username'], session['password'])
        response = web_session.get(url, auth=auth)
    else:
        response = web_session.get(url)

    if response.status_code == 200:
        # Parse HTML content
        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract text (customize based on actual site structure)
        article_text = soup.get_text()

        return jsonify({
            'status': 'success',
            'content': article_text[:5000]  # Limit initial content
        })
    else:
        return jsonify({
            'status': 'error',
            'message': f'Failed to fetch article: {response.status_code}'
        }), 400

@app.route('/summarize', methods=['POST'])
def summarize():
    """Summarize article content using OpenAI"""
    content = request.json.get('content')

    try:
        # Call OpenAI API for summarization
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a financial analyst assistant. Summarize the following financial news article, highlighting key points, financial figures, and market implications."},
                {"role": "user", "content": content}
            ],
            max_tokens=500,
            temperature=0.7
        )

        summary = response.choices[0].message.content

        return jsonify({
            'status': 'success',
            'summary': summary
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/batch-summarize', methods=['POST'])
def batch_summarize():
    """Summarize multiple articles"""
    urls = request.json.get('urls', [])
    summaries = []

    for url in urls:
        # Fetch and summarize each URL
        # This is a placeholder - implement actual logic
        summaries.append({
            'url': url,
            'summary': 'Summary placeholder'
        })

    return jsonify({
        'status': 'success',
        'summaries': summaries
    })

if __name__ == '__main__':
    app.run(debug=os.getenv('DEBUG', 'False') == 'True', host='127.0.0.1', port=5000)
