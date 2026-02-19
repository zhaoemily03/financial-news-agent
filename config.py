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

# Substack Authors (auto-discovered from forwarded Feishu emails)
# No manual config needed — any Substack email forwarded to the
# Feishu mailbox (FEISHU_MAILBOX in .env) is automatically ingested.
SUBSTACK_AUTHORS = []

# Browser reliability settings
BROWSER_RESTART_AFTER_DOWNLOADS = 20   # restart Chrome every N reports (prevents memory leaks + session decay)
PAGE_LOAD_TIMEOUT = 30                  # seconds before Selenium navigation times out
MAX_NAV_RETRIES = 3                     # max retries on failed report navigation
NAV_RETRY_BACKOFF_BASE = 2              # exponential backoff: wait 2^attempt seconds between retries
REQUEST_TIMEOUT = 30                    # seconds for requests.Session PDF downloads
REQUEST_DELAY_MIN = 1.5                 # minimum seconds between report navigations (human-like timing)
REQUEST_DELAY_MAX = 3.5                 # maximum seconds between report navigations

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
        'enabled': False,  # Temporarily disabled — 0 notifications + hangs pipeline
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
        'max_reports': 25,  # Should I allow it to intake more, like 50+?
        'scraper_class': 'MorganStanleyScraper',
    },
    'goldman': {
        'enabled': True,
        'portal_url': 'https://marquee.gs.com/content/research/themes/homepage-default.html',
        'login_required': True,
        'uses_followed_notifications': False,  # Uses "My Content" section
        'max_reports': 20,
        'timeout': 480,  # 8 min — Goldman is slow (PDF downloads + 20 reports)
        'scraper_class': 'GoldmanScraper',
    },
    'bernstein': {
        'enabled': True,
        'portal_url': 'https://www.bernsteinresearch.com/brweb/Home.aspx#/',
        'login_required': True,
        'uses_followed_notifications': False,  # Uses Research tab + Industry filter
        'max_reports': 25,
        'scraper_class': 'BernsteinScraper',
    },
    'arete': {
        'enabled': False,  # Not yet tested
        'portal_url': 'https://portal.arete.net/',
        'login_required': True,
        'uses_followed_notifications': False,  # Uses "My Research" on home page
        'max_reports': 20,
        'scraper_class': 'AreteScraper',
    },
    'ubs': {
        'enabled': False,  # Not yet tested
        'portal_url': 'https://neo.ubs.com/home',
        'login_required': True,
        'uses_followed_notifications': False,  # Uses per-ticker search
        'max_reports': 30,
        'scraper_class': 'UBSScraper',
    },
    # Non-portal sources (separate ingestion pipeline)
    'substack': {
        'enabled': True,
        'check_frequency_hours': 24,
        'days_lookback': 5,
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
            'a16z': {
                'enabled': True,
                'name': 'a16z',
                'type': 'youtube',
                'channel_id': 'UC9cn0TuPq4dnbTY-CBsm8XA',
                'max_episodes': 2,
            },
        },
    }
}

# Filtering Configuration
RELEVANCE_THRESHOLD = 0.7  # 0-1 score for content relevance
MIN_CONTENT_LENGTH = 100  # Minimum words to process

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

# ------------------------------------------------------------------
# Macro News Collection (RSS)
# ------------------------------------------------------------------
# Fetches macro headlines from financial news RSS feeds.
# Claims get event_type='macro' and flow to Section 3 of briefing.

MACRO_NEWS = {
    'enabled': True,
    'max_articles': 6,              # Max macro articles per run
    'days_lookback': 1,             # Only today's articles
    'keyword_filter': True,         # Filter by macro keywords
}

# ------------------------------------------------------------------
# Macro-Micro Connection Synthesis (DEPRECATED)
# ------------------------------------------------------------------
# Disabled in favor of sentiment drift detection.
# Keeping config for backward compatibility but not used.

CONNECTION_SYNTHESIS = {
    'enabled': False,  # Disabled - use DRIFT_DETECTION instead
    'max_connections': 10,
    'min_pitch_prompts': 3,
    'max_pitch_prompts': 5,
    'historical_days': 30,
    'include_watchlist': True,
    'require_clear_counter': True,
}

# ------------------------------------------------------------------
# Sentiment Drift Detection
# ------------------------------------------------------------------
# Surfaces belief changes and confidence shifts over time.
# This is the core value proposition: detect when sentiment is moving.

DRIFT_DETECTION = {
    'enabled': True,
    'lookback_days': 30,            # How far back to compare
    'min_claims_for_drift': 2,      # Minimum claims on same topic to detect drift
    'confidence_shift_threshold': 1, # Levels of confidence change to flag (low→high = 2)
    'track_by': ['ticker', 'author', 'source'],  # Dimensions to track
}
