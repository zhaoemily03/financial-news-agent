"""
Configuration file for analyst settings
Edit this file to customize tickers, themes, and other preferences
"""

# Analyst Coverage Configuration
TICKERS = {
    'primary_internet': ['META', 'GOOGL', 'AMZN', 'AAPL', 'BABA', '700.HK'],
    'watchlist_internet': ['NFLX', 'SPOT', 'U', 'APP', 'RBLX'],
    'primary_software': ['MSFT', 'CRWD', 'ZS', 'PANW', 'NET', 'DDOG', 'SNOW', 'MDB'],
    'watchlist_software': ['NET', 'ORCL', 'PLTR', 'SHOP'],
}

# Flat list for easy filtering
ALL_TICKERS = (
    TICKERS['primary_internet'] +
    TICKERS['watchlist_internet'] +
    TICKERS['primary_software'] +
    TICKERS['watchlist_software']
)

# Remove duplicates
ALL_TICKERS = list(set(ALL_TICKERS))

# Trusted Analysts by Firm
TRUSTED_ANALYSTS = {
    'jefferies': [
        'Brent Thill',
        'Joseph Gallo'
    ],
    # Add more firms and their analysts here
}

# Investment Themes/Theses Being Tracked
INVESTMENT_THEMES = [
    {
        'name': 'Digital Transformation',
        'keywords': ['digital transformation', 'cloud migration', 'SaaS adoption', 'enterprise software',
                     'digital infrastructure', 'platform shift', 'API economy', 'developer tools',
                     'cloud native', 'modernization'],
        'priority': 'high'
    },
    {
        'name': 'AI & Machine Learning',
        'keywords': ['artificial intelligence', 'machine learning', 'generative AI', 'LLM',
                     'AI infrastructure', 'ML ops', 'AI applications', 'copilot', 'AI assistant'],
        'priority': 'high'
    },
    {
        'name': 'Cybersecurity',
        'keywords': ['cybersecurity', 'zero trust', 'cloud security', 'endpoint protection',
                     'threat detection', 'data protection', 'identity management', 'SIEM', 'XDR'],
        'priority': 'high'
    },
]

# Substack Authors to Monitor
SUBSTACK_AUTHORS = [
    {
        'name': 'Author Name',
        'url': 'https://authorname.substack.com',
        'has_rss': True,
        'rss_url': 'https://authorname.substack.com/feed',
        'requires_login': False
    },
    # Add more authors here
]

# Email Configuration
EMAIL_CONFIG = {
    'recipients': ['analyst@example.com'],
    'cc': [],
    'subject_prefix': '[Daily Briefing]',
    'send_time': '07:00',  # 24-hour format
    'timezone': 'America/New_York'
}

# Content Source Configuration
SOURCES = {
    'jefferies': {
        'enabled': True,
        'portal_url': 'https://globalmarkets.jefferies.com',
        'login_required': True,
        'filter_by_analyst': True,  # Only include reports from TRUSTED_ANALYSTS
    },
    'jp_morgan': {
        'enabled': False,  # Not configured yet
        'portal_url': 'https://example.com',
        'login_required': True
    },
    'substack': {
        'enabled': True,
        'check_frequency_hours': 24
    },
    'youtube': {
        'enabled': False,  # Phase 2
    },
    'twitter': {
        'enabled': False,  # Phase 2
    },
    'podcasts': {
        'enabled': False,  # Phase 2
    }
}

# Filtering Configuration
RELEVANCE_THRESHOLD = 0.7  # 0-1 score for content relevance
MIN_CONTENT_LENGTH = 100  # Minimum words to process
MAX_BRIEFING_ITEMS_PER_TIER = 10  # Max items per tier to keep briefing concise

# Priority tiers for tickers (affects Tier 1 filtering)
TICKER_PRIORITY = {
    'high': TICKERS['primary_internet'] + TICKERS['primary_software'],
    'medium': TICKERS['watchlist_internet'] + TICKERS['watchlist_software'],
}

# Storage Configuration
STORAGE = {
    'processed_content_db': 'data/processed_content.db',
    'reports_directory': 'data/reports',
    'logs_directory': 'logs'
}
