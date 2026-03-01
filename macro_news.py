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

# Keywords split into priority tiers.
# HIGH: US-China/geopolitics, TMT regulation, TMT blind spots — directly
#       destabilizing for TMT portfolio assumptions; filled first.
# LOWER: General macro backdrop — relevant context, fills remaining slots.
# collect_macro_news fills HIGH quota first, then pads with LOWER.

HIGH_PRIORITY_KEYWORDS = [
    # US-China / TMT Geopolitics
    'us-china', 'china tech', 'taiwan', 'chips act', 'entity list',
    'semiconductor ban', 'decoupling', 'sanctions', 'cfius',
    'tiktok', 'huawei', 'export control',

    # Tariffs / Trade War (hits hardware margins and supply chains directly)
    'tariff', 'trade war', 'trade restriction',

    # TMT-Specific Regulation & Disruption
    'antitrust', 'doj', 'ftc', 'sec ', 'ai regulation',
    'data privacy', 'big tech', 'eu ai act', 'digital markets act',

    # TMT Blind Spots Worth Tracking
    'spectrum auction', 'cloud spending', 'ad spending',
    'capex guidance', 'ai capex', 'hyperscaler', 'data center',
    'nvidia', 'openai', 'anthropic', 'gemini',
]

LOWER_PRIORITY_KEYWORDS = [
    # Fed / Monetary Policy
    'fed', 'federal reserve', 'interest rate', 'rate cut', 'rate hike',
    'fomc', 'jerome powell', 'monetary policy',

    # Consumer Strength
    'consumer spending', 'consumer confidence', 'retail sales',

    # US Political Risk
    'executive order', 'government shutdown', 'debt ceiling', 'election',

    # Supply Chain
    'supply chain', 'reshoring', 'domestic manufacturing',

    # Macro Backdrop
    'inflation', 'cpi', 'gdp', 'recession', 'unemployment',
    'treasury', 'bond yield', 'vix', 'volatility',
]

# Combined for single-list lookups (e.g. in tests)
MACRO_KEYWORDS = HIGH_PRIORITY_KEYWORDS + LOWER_PRIORITY_KEYWORDS


# ------------------------------------------------------------------
# RSS Parsing
# ------------------------------------------------------------------

def _matches_macro_keywords(text: str) -> bool:
    """True if text contains any macro keyword (case-insensitive)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in MACRO_KEYWORDS)


def _priority_score(text: str) -> int:
    """
    Return 1 for high-priority (TMT-direct: geopolitics, regulation, blind spots),
    0 for lower-priority (general macro backdrop).
    Used to fill high-priority quota first when capping collected articles.
    """
    text_lower = text.lower()
    return 1 if any(kw in text_lower for kw in HIGH_PRIORITY_KEYWORDS) else 0


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

        combined = f"{title} {summary}"

        # Macro keyword filter
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
            '_priority': _priority_score(combined),  # stripped before pipeline ingestion
        })

        if len(articles) >= max_articles:
            break

    return articles


# ------------------------------------------------------------------
# Deduplication (cross-feed same-story removal)
# ------------------------------------------------------------------

def _deduplicate_articles(articles: List[Dict]) -> List[Dict]:
    """
    Remove near-duplicate articles across feeds.
    Reuters and CNBC often cover the same story; deduplicate by title word overlap.
    Two articles are considered duplicates if ≥50% of significant title words overlap.
    """
    STOP_WORDS = {
        'the', 'a', 'an', 'of', 'in', 'on', 'at', 'to', 'for', 'is', 'are',
        'was', 'were', 'be', 'by', 'as', 'its', 'it', 'from', 'with', 'that',
        'this', 'than', 'but', 'and', 'or', 'not', 'says', 'said', 'new',
    }

    def sig(title: str) -> frozenset:
        words = re.sub(r'[^\w\s]', '', title.lower()).split()
        return frozenset(w for w in words if w not in STOP_WORDS and len(w) > 3)

    seen_sigs = []
    unique = []
    for article in articles:
        s = sig(article['title'])
        if not s:
            unique.append(article)
            continue
        is_dup = any(
            len(s & prior) / max(len(s | prior), 1) >= 0.5
            for prior in seen_sigs
        )
        if not is_dup:
            seen_sigs.append(s)
            unique.append(article)
        else:
            print(f"  ✗ Dedup: {article['title'][:60]} ({article['analyst']})")
    return unique


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

    # Deduplicate cross-feed same-story coverage before capping
    before_dedup = len(all_articles)
    all_articles = _deduplicate_articles(all_articles)
    if len(all_articles) < before_dedup:
        print(f"  ✓ Dedup: {before_dedup} → {len(all_articles)} articles ({before_dedup - len(all_articles)} removed)")

    # Sort HIGH-priority articles to the front, then cap total
    all_articles.sort(key=lambda a: -a.get('_priority', 0))
    if len(all_articles) > max_articles:
        all_articles = all_articles[:max_articles]

    # Strip internal priority tag before pipeline ingestion
    for a in all_articles:
        a.pop('_priority', None)

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
