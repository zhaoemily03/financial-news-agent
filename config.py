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
# DEPRECATED: Now uses portal's "Followed Notifications" feature.
# Analysts you follow in the portal ARE your trusted analysts.
# This dict is kept for backward compatibility but is ignored by the scraper.
TRUSTED_ANALYSTS = {
    'jefferies': ['(dynamic - uses portal follows)'],
    # Follow analysts directly in each portal - scraper pulls from your followed list
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
# Sell-side portals use the PortalRegistry for unified scraping
SOURCES = {
    # Sell-side research portals (use PortalRegistry)
    'jefferies': {
        'enabled': True,
        'portal_url': 'https://content.jefferies.com',
        'login_required': True,
        'uses_followed_notifications': True,
        'max_reports': 20,  # Max reports to fetch per run
        'scraper_class': 'JefferiesScraper',  # From jefferies_scraper.py
    },
    'morgan_stanley': {
        'enabled': True,
        'portal_url': 'https://ny.matrix.ms.com/eqr/research/ui/#/home',
        'login_required': True,
        'uses_followed_notifications': True,
        'max_reports': 25,  # Collect more to capture thematic content
        'scraper_class': 'MorganStanleyScraper',
    },
    'goldman': {
        'enabled': False,  # Not implemented yet
        'portal_url': 'https://marquee.gs.com',
        'login_required': True,
        'uses_followed_notifications': True,
        'max_reports': 20,
        'scraper_class': 'GoldmanScraper',  # Future: goldman_scraper.py
    },
    'jpmorgan': {
        'enabled': False,  # Not implemented yet
        'portal_url': 'https://ny.matrix.ms.com',
        'login_required': True,
        'uses_followed_notifications': True,
        'max_reports': 20,
        'scraper_class': 'jpmorganscraper',  # Future: morgan_stanley_scraper.py
    },
    # Non-portal sources (separate ingestion pipeline)
    'substack': {
        'enabled': False,  # Not implemented yet
        'check_frequency_hours': 24
    },
    'youtube': {
        'enabled': False,  # Phase 2
    },
    'x_social': {
        'enabled': False,  # Requires X API Basic tier ($100/mo) for read access
        'check_frequency_hours': 24,
        'max_posts_per_day': 12,  # Budget: ~360/month of 500 limit
        'min_engagement': 100,  # Likes + retweets threshold
        'days_lookback': 1,
        'include_replies': False,
        'hosts': {
            # All-In Podcast hosts
            'chamath': {'username': 'chamath', 'display_name': 'Chamath Palihapitiya'},
            'jason': {'username': 'Jason', 'display_name': 'Jason Calacanis'},
            'sacks': {'username': 'DavidSacks', 'display_name': 'David Sacks'},
            'friedberg': {'username': 'friedberg', 'display_name': 'David Friedberg'},
        },
    },
    'podcasts': {
        'enabled': True,
        'check_frequency_hours': 24,
        'max_episodes_per_podcast': 3,
        'days_lookback': 7,
        'sources': {
            'all-in': {
                'enabled': True,
                'name': 'All-In Podcast',
                'type': 'youtube',
                'channel_id': 'UCESLZhusAkFfsNsApnjF_Cg',
                'max_episodes': 2,
            },
            'bg2': {
                'enabled': False,  # Uploads infrequently
                'name': 'BG2 Pod',
                'type': 'rss',
                'rss_url': 'https://anchor.fm/s/f06c2370/podcast/rss',
                'max_episodes': 2,
            },
            'acquired': {
                'enabled': True,
                'name': 'Acquired',
                'type': 'rss',
                'rss_url': 'https://feeds.transistor.fm/acquired',
                'max_episodes': 1,  # Long episodes, limit to 1
            },
        },
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
