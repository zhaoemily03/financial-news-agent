"""
Configuration file for analyst settings
Edit this file to customize tickers, themes, and other preferences
"""

# Analyst Coverage Configuration
TICKERS = [
    'NVDA',
    'AVGO',
    'TSM',
    'AMD',
    'INTC',
    # Add more tickers here
]

# Investment Themes/Theses Being Tracked
INVESTMENT_THEMES = [
    {
        'name': 'AI Infrastructure Buildout',
        'keywords': ['data center', 'GPU', 'inference', 'training', 'compute capacity', 'AI accelerator'],
        'priority': 'high'
    },
    {
        'name': 'Memory Chip Market Dynamics',
        'keywords': ['DRAM', 'NAND', 'HBM', 'memory shortage', 'memory pricing'],
        'priority': 'high'
    },
    {
        'name': 'China Semiconductor Policy',
        'keywords': ['export controls', 'SMIC', 'China fab', 'sanctions', 'domestic production'],
        'priority': 'medium'
    },
    # Add more themes here
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
    'jp_morgan': {
        'enabled': True,
        'portal_url': 'https://example.com',  # Update with actual URL
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

# Storage Configuration
STORAGE = {
    'processed_content_db': 'data/processed_content.db',
    'reports_directory': 'data/reports',
    'logs_directory': 'logs'
}
