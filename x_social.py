"""
X (Twitter) Social Feed Handler

Fetches tweets from specified accounts (All-In podcast hosts) and filters
for TMT-relevant content. Designed for the free tier (500 posts/month).

Budget: ~12-16 posts/day across all hosts
Strategy:
- Fetch only original tweets (no retweets)
- Filter for TMT relevance before storing
- Prioritize by engagement (likes + retweets)
- Run once daily

Usage:
    from x_social import AllInHostsFeed

    feed = AllInHostsFeed()
    posts = feed.collect(days=1, max_posts=12)
"""

import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

# All-In Podcast hosts
ALLIN_HOSTS = {
    'chamath': {
        'username': 'chamath',
        'display_name': 'Chamath Palihapitiya',
        'user_id': '15aborma',  # Will be fetched if not set
    },
    'jason': {
        'username': 'Jason',
        'display_name': 'Jason Calacanis',
        'user_id': None,
    },
    'sacks': {
        'username': 'DavidSacks',
        'display_name': 'David Sacks',
        'user_id': None,
    },
    'friedberg': {
        'username': 'friedberg',
        'display_name': 'David Friedberg',
        'user_id': None,
    },
}

# TMT relevance keywords (case-insensitive)
TMT_KEYWORDS = [
    # Tickers (with $ prefix commonly used on X)
    r'\$META', r'\$GOOGL', r'\$GOOG', r'\$AMZN', r'\$AAPL', r'\$MSFT',
    r'\$NVDA', r'\$TSLA', r'\$NFLX', r'\$CRM', r'\$ORCL', r'\$ADBE',
    r'\$CRWD', r'\$ZS', r'\$PANW', r'\$NET', r'\$DDOG', r'\$SNOW', r'\$MDB',
    r'\$PLTR', r'\$UBER', r'\$ABNB', r'\$COIN', r'\$SQ', r'\$SHOP',
    # Company names
    r'\bMeta\b', r'\bGoogle\b', r'\bAmazon\b', r'\bApple\b', r'\bMicrosoft\b',
    r'\bNvidia\b', r'\bOpenAI\b', r'\bAnthropic\b', r'\bTesla\b',
    # Tech topics
    r'\bAI\b', r'\bartificial intelligence\b', r'\bLLM\b', r'\bGPT\b',
    r'\bcloud\b', r'\bSaaS\b', r'\bcybersecurity\b', r'\bad tech\b',
    r'\bdigital ads\b', r'\be-commerce\b', r'\bstreaming\b',
    r'\bVC\b', r'\bventure\b', r'\bstartup\b', r'\bIPO\b',
    r'\bearnings\b', r'\brevenue\b', r'\bgrowth\b', r'\bmargins\b',
    # Market/macro that affects TMT
    r'\bFed\b', r'\brates\b', r'\bvaluation\b', r'\bmultiples\b',
]

# Minimum engagement threshold (likes + retweets)
MIN_ENGAGEMENT = 100


# ------------------------------------------------------------------
# Tweet Tracker (SQLite deduplication)
# ------------------------------------------------------------------

class TweetTracker:
    """Track processed tweets to avoid duplicates."""

    def __init__(self, db_path: str = 'data/tweet_tracker.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_tweets (
                tweet_id TEXT PRIMARY KEY,
                username TEXT,
                processed_at TEXT,
                text_preview TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def is_processed(self, tweet_id: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM processed_tweets WHERE tweet_id = ?', (tweet_id,))
        result = cursor.fetchone() is not None
        conn.close()
        return result

    def mark_processed(self, tweet_id: str, username: str, text_preview: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO processed_tweets (tweet_id, username, processed_at, text_preview)
            VALUES (?, ?, ?, ?)
        ''', (tweet_id, username, datetime.now().isoformat(), text_preview[:100]))
        conn.commit()
        conn.close()

    def get_stats(self) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM processed_tweets')
        total = cursor.fetchone()[0]
        cursor.execute('''
            SELECT COUNT(*) FROM processed_tweets
            WHERE processed_at >= date('now', '-30 days')
        ''')
        last_30_days = cursor.fetchone()[0]
        conn.close()
        return {'total': total, 'last_30_days': last_30_days}


# ------------------------------------------------------------------
# X API Client
# ------------------------------------------------------------------

@dataclass
class Tweet:
    """Parsed tweet data."""
    id: str
    text: str
    author_username: str
    author_name: str
    created_at: datetime
    likes: int
    retweets: int
    replies: int
    url: str
    is_retweet: bool
    is_reply: bool

    @property
    def engagement(self) -> int:
        return self.likes + self.retweets

    def is_tmt_relevant(self) -> bool:
        """Check if tweet contains TMT-relevant content."""
        for pattern in TMT_KEYWORDS:
            if re.search(pattern, self.text, re.IGNORECASE):
                return True
        return False


class XClient:
    """Simple X API v2 client."""

    BASE_URL = 'https://api.twitter.com/2'

    def __init__(self, bearer_token: str = None):
        self.bearer_token = bearer_token or os.getenv('X_BEARER_TOKEN')
        if not self.bearer_token:
            raise ValueError("X_BEARER_TOKEN not found in environment")

        self.headers = {
            'Authorization': f'Bearer {self.bearer_token}',
            'Content-Type': 'application/json',
        }
        self._user_id_cache = {}

    def get_user_id(self, username: str) -> Optional[str]:
        """Get user ID from username (cached)."""
        if username in self._user_id_cache:
            return self._user_id_cache[username]

        url = f'{self.BASE_URL}/users/by/username/{username}'
        response = requests.get(url, headers=self.headers)

        if response.status_code != 200:
            print(f"  Failed to get user ID for @{username}: {response.status_code}")
            return None

        data = response.json()
        if 'data' in data:
            user_id = data['data']['id']
            self._user_id_cache[username] = user_id
            return user_id

        return None

    def get_user_tweets(
        self,
        user_id: str,
        username: str,
        max_results: int = 10,
        since_hours: int = 24,
    ) -> List[Tweet]:
        """
        Fetch recent tweets from a user.

        Args:
            user_id: X user ID
            username: Username for display
            max_results: Max tweets to fetch (5-100)
            since_hours: Only tweets from last N hours
        """
        url = f'{self.BASE_URL}/users/{user_id}/tweets'

        # Calculate start_time
        start_time = (datetime.utcnow() - timedelta(hours=since_hours)).strftime('%Y-%m-%dT%H:%M:%SZ')

        params = {
            'max_results': min(max_results, 100),
            'start_time': start_time,
            'tweet.fields': 'created_at,public_metrics,referenced_tweets',
            'expansions': 'author_id',
            'user.fields': 'name,username',
            'exclude': 'retweets',  # Exclude retweets to save quota
        }

        response = requests.get(url, headers=self.headers, params=params)

        if response.status_code != 200:
            print(f"  Failed to get tweets for @{username}: {response.status_code}")
            if response.status_code == 429:
                print("  Rate limited - try again later")
            return []

        data = response.json()
        tweets = []

        if 'data' not in data:
            return []

        # Get author info from includes
        author_name = username
        if 'includes' in data and 'users' in data['includes']:
            for user in data['includes']['users']:
                if user['id'] == user_id:
                    author_name = user.get('name', username)
                    break

        for tweet_data in data['data']:
            # Check if it's a reply (to someone other than self)
            is_reply = False
            if 'referenced_tweets' in tweet_data:
                for ref in tweet_data['referenced_tweets']:
                    if ref['type'] == 'replied_to':
                        is_reply = True
                        break

            metrics = tweet_data.get('public_metrics', {})

            tweet = Tweet(
                id=tweet_data['id'],
                text=tweet_data['text'],
                author_username=username,
                author_name=author_name,
                created_at=datetime.strptime(
                    tweet_data['created_at'], '%Y-%m-%dT%H:%M:%S.%fZ'
                ),
                likes=metrics.get('like_count', 0),
                retweets=metrics.get('retweet_count', 0),
                replies=metrics.get('reply_count', 0),
                url=f'https://x.com/{username}/status/{tweet_data["id"]}',
                is_retweet=False,  # Excluded via API param
                is_reply=is_reply,
            )
            tweets.append(tweet)

        return tweets


# ------------------------------------------------------------------
# All-In Hosts Feed
# ------------------------------------------------------------------

class AllInHostsFeed:
    """
    Fetch and filter tweets from All-In podcast hosts.

    Budget-conscious: designed for 500 posts/month free tier.
    """

    FEED_NAME = "All-In Hosts (X)"
    HOSTS = ALLIN_HOSTS

    def __init__(self):
        if not HAS_REQUESTS:
            raise ImportError("requests library required: pip install requests")

        self.client = XClient()
        self.tracker = TweetTracker()

    def collect(
        self,
        days: int = 1,
        max_posts: int = 12,
        min_engagement: int = MIN_ENGAGEMENT,
        include_replies: bool = False,
    ) -> List[Dict]:
        """
        Collect TMT-relevant tweets from All-In hosts.

        Args:
            days: Look back N days (default 1 for daily runs)
            max_posts: Maximum posts to return (budget control)
            min_engagement: Minimum likes+retweets threshold
            include_replies: Include reply tweets

        Returns:
            List of post dicts matching pipeline format
        """
        print(f"\n[{self.FEED_NAME}] Collecting tweets from last {days} day(s)...")
        print(f"  Budget: {max_posts} posts max, {min_engagement}+ engagement")

        all_tweets = []
        hours = days * 24

        # Fetch tweets from each host
        for host_key, host_info in self.HOSTS.items():
            username = host_info['username']
            print(f"\n  @{username}...")

            # Get user ID
            user_id = host_info.get('user_id')
            if not user_id:
                user_id = self.client.get_user_id(username)
                if not user_id:
                    print(f"    Could not resolve user ID - skipping")
                    continue

            # Fetch tweets
            tweets = self.client.get_user_tweets(
                user_id=user_id,
                username=username,
                max_results=20,  # Fetch more, filter down
                since_hours=hours,
            )

            print(f"    Fetched {len(tweets)} tweets")

            # Filter
            for tweet in tweets:
                # Skip already processed
                if self.tracker.is_processed(tweet.id):
                    continue

                # Skip replies unless enabled
                if tweet.is_reply and not include_replies:
                    continue

                # Skip low engagement
                if tweet.engagement < min_engagement:
                    continue

                # Skip non-TMT content
                if not tweet.is_tmt_relevant():
                    continue

                all_tweets.append(tweet)

        print(f"\n  Found {len(all_tweets)} relevant tweets (after filters)")

        if not all_tweets:
            return []

        # Sort by engagement and take top N
        all_tweets.sort(key=lambda t: t.engagement, reverse=True)
        selected = all_tweets[:max_posts]

        # Convert to pipeline format
        results = []
        for tweet in selected:
            result = {
                'title': f"@{tweet.author_username}: {tweet.text[:60]}...",
                'url': tweet.url,
                'analyst': tweet.author_name,
                'source': 'X',
                'source_type': 'social',
                'date': tweet.created_at.strftime('%Y-%m-%d'),
                'content': tweet.text,
                'engagement': tweet.engagement,
            }
            results.append(result)

            # Mark as processed
            self.tracker.mark_processed(tweet.id, tweet.author_username, tweet.text)

            print(f"    [{tweet.engagement:,} eng] @{tweet.author_username}: {tweet.text[:50]}...")

        # Show budget status
        stats = self.tracker.get_stats()
        print(f"\n  Budget used this month: {stats['last_30_days']}/500 posts")

        return results


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("\nX Social Feed Handler Tests")
    print("=" * 50)

    # Check dependencies
    print("\n[1/3] Checking dependencies...")
    if not HAS_REQUESTS:
        print("  requests: NOT INSTALLED")
        print("  Run: pip install requests")
        exit(1)
    print("  requests: OK")

    bearer_token = os.getenv('X_BEARER_TOKEN')
    if not bearer_token:
        print("  X_BEARER_TOKEN: NOT SET")
        print("  Add to .env: X_BEARER_TOKEN=your_token")
        exit(1)
    print("  X_BEARER_TOKEN: OK (set)")

    # Test user ID lookup
    print("\n[2/3] Testing user ID lookup...")
    try:
        client = XClient()
        for host_key, host_info in list(ALLIN_HOSTS.items())[:1]:  # Test one
            username = host_info['username']
            user_id = client.get_user_id(username)
            if user_id:
                print(f"  @{username} -> {user_id}")
            else:
                print(f"  @{username} -> FAILED")
    except Exception as e:
        print(f"  Error: {e}")
        exit(1)

    # Test full collection (conservative)
    print("\n[3/3] Testing tweet collection (1 post max for test)...")
    try:
        feed = AllInHostsFeed()
        posts = feed.collect(days=1, max_posts=1, min_engagement=50)
        print(f"\n  Collected {len(posts)} post(s)")

        if posts:
            post = posts[0]
            print(f"\n  Sample post:")
            print(f"    Author: {post['analyst']}")
            print(f"    Date: {post['date']}")
            print(f"    Engagement: {post['engagement']}")
            print(f"    Content: {post['content'][:100]}...")
    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

    print("\n X social feed handler ready")
