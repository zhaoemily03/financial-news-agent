"""
Macro News Collector — RSS-based financial/macro headline ingestion.

Fetches top macro headlines from Reuters and CNBC, filters by keyword,
and formats as report dicts for pipeline ingestion.

Macro claims flow through the pipeline and get assigned to Section 3
(Macro Context) with TMT sector implications.

Usage:
    from macro_news import collect_macro_news

    reports = collect_macro_news(max_articles=6)
    # Returns list of report dicts compatible with pipeline
"""

import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ------------------------------------------------------------------
# RSS Feed Configuration
# ------------------------------------------------------------------

MACRO_RSS_FEEDS = [
    {
        'name': 'Reuters Business',
        'url': 'https://www.rss.reuters.com/news/businessNews',
        'source': 'Reuters',
    },
    {
        'name': 'CNBC Top News',
        'url': 'https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114',
        'source': 'CNBC',
    },
]

# Keywords that indicate macro-relevant content
MACRO_KEYWORDS = [
    'fed', 'federal reserve', 'interest rate', 'rate cut', 'rate hike',
    'inflation', 'cpi', 'pce', 'gdp', 'gross domestic',
    'jobs', 'unemployment', 'nonfarm', 'payroll', 'labor market',
    'tariff', 'trade war', 'trade deal', 'sanctions',
    'treasury', 'bond yield', 'yield curve',
    'regulation', 'antitrust', 'doj', 'ftc', 'eu regulation', 'sec ',
    'china', 'geopolitical', 'war', 'conflict',
    'recession', 'monetary policy', 'fiscal policy',
    'oil price', 'commodity', 'supply chain',
    'earnings season', 'market crash', 'volatility', 'vix',
]


# ------------------------------------------------------------------
# RSS Parsing
# ------------------------------------------------------------------

def _matches_macro_keywords(text: str) -> bool:
    """Check if text contains any macro keyword (case-insensitive)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in MACRO_KEYWORDS)


def _clean_html(text: str) -> str:
    """Strip HTML tags from RSS descriptions."""
    return re.sub(r'<[^>]+>', '', text).strip()


def _fetch_feed(feed_config: Dict, days: int = 1, max_articles: int = 10) -> List[Dict]:
    """
    Fetch and parse a single RSS feed.

    Returns list of report dicts matching pipeline format.
    """
    if not HAS_FEEDPARSER:
        print(f"  feedparser not available — skipping {feed_config['name']}")
        return []

    try:
        feed = feedparser.parse(feed_config['url'])
    except Exception as e:
        print(f"  Failed to parse {feed_config['name']}: {e}")
        return []

    if not feed.entries:
        print(f"  No entries in {feed_config['name']}")
        return []

    articles = []
    cutoff = datetime.now() - timedelta(days=days)
    today = datetime.now().strftime('%Y-%m-%d')

    for entry in feed.entries:
        # Parse date
        try:
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6])
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                pub_date = datetime(*entry.updated_parsed[:6])
            else:
                pub_date = datetime.now()  # Assume recent if no date
        except Exception:
            pub_date = datetime.now()

        if pub_date < cutoff:
            continue

        title = entry.get('title', '').strip()
        summary = _clean_html(entry.get('summary', entry.get('description', '')))
        link = entry.get('link', '')

        # Skip empty entries
        if not title:
            continue

        # Macro keyword filter
        combined = f"{title} {summary}"
        if not _matches_macro_keywords(combined):
            continue

        articles.append({
            'title': title,
            'url': link,
            'pdf_url': '',
            'analyst': feed_config['source'],
            'source': 'macro_news',
            'date': pub_date.strftime('%Y-%m-%d'),
            'content': f"{title}\n\n{summary}\n\n[Source: {feed_config['source']}]",
        })

        if len(articles) >= max_articles:
            break

    return articles


# ------------------------------------------------------------------
# Main Collection Function
# ------------------------------------------------------------------

def collect_macro_news(
    max_articles: int = 6,
    days: int = 1,
    feeds: Optional[List[Dict]] = None,
) -> List[Dict]:
    """
    Collect macro news from RSS feeds.

    Args:
        max_articles: Max total articles to return
        days: Only include articles from last N days
        feeds: Optional custom feed list (defaults to MACRO_RSS_FEEDS)

    Returns:
        List of report dicts compatible with pipeline ingestion
    """
    if feeds is None:
        feeds = MACRO_RSS_FEEDS

    all_articles = []

    for feed_config in feeds:
        per_feed_max = max(2, max_articles // len(feeds))
        articles = _fetch_feed(feed_config, days=days, max_articles=per_feed_max)
        all_articles.extend(articles)
        if articles:
            print(f"  ✓ {feed_config['name']}: {len(articles)} macro articles")
        else:
            print(f"  ⚠ {feed_config['name']}: no macro articles found")

    # Cap total
    if len(all_articles) > max_articles:
        all_articles = all_articles[:max_articles]

    return all_articles


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Macro News Collector Test")
    print("=" * 60)

    articles = collect_macro_news(max_articles=6, days=2)

    print(f"\n{'=' * 60}")
    print(f"Collected {len(articles)} macro articles")
    print(f"{'=' * 60}")

    for i, article in enumerate(articles, 1):
        print(f"\n[{i}] {article['title'][:70]}")
        print(f"    Source: {article['analyst']} | Date: {article['date']}")
        print(f"    URL: {article['url'][:60]}...")
        content_preview = article['content'].replace('\n', ' ')[:100]
        print(f"    Content: {content_preview}...")

    # Verification
    print(f"\n{'=' * 60}")
    print("Verification")
    print(f"{'=' * 60}")

    # Check format compatibility
    for article in articles:
        assert 'title' in article, "Missing title"
        assert 'source' in article and article['source'] == 'macro_news', "Source must be 'macro_news'"
        assert 'content' in article and len(article['content']) > 0, "Content must not be empty"
        assert 'date' in article, "Missing date"
        assert 'analyst' in article, "Missing analyst (source name)"

    if articles:
        print(f"✓ {len(articles)} articles pass format validation")
        print("✓ All articles have required pipeline fields")
    else:
        print("⚠ No articles collected — RSS feeds may be unavailable")
        print("  Pipeline will still work (falls back to portal + podcast content)")

    print(f"\n✓ Macro news collector ready")
