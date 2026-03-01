"""
Hardcoded AnalystConfig for user.
This is where the logic is that doesn't change from user to user.
Explicit relevance policy — intentionally lossy to enforce <5-page constraint.

This config defines:
- Category weights (tracked_ticker > tmt_sector > macro)
- Source credibility (acknowledging that sell-side has positive bias)
- Ticker priority (primary > watchlist) — loaded dynamically from config.TICKERS

Usage:
    from analyst_config_tmt import TMT_CONFIG, score_chunk, SOURCE_CREDIBILITY
"""

from typing import List, Tuple, Optional
from dataclasses import dataclass, field
from schemas import Chunk, AnalystConfig
from classifier import ChunkClassification

# ------------------------------------------------------------------
# Category Weights — higher = more relevant to briefing
# ------------------------------------------------------------------

CATEGORY_WEIGHTS = {
    'tracked_ticker': 1.0,     # Direct coverage — always highest priority
    'tmt_sector': 0.7,         # Sector-level context
    'macro': 0.5,              # Macro — important but lower priority for TMT analyst
    'irrelevant': 0.0,         # Should already be filtered out
}

# ------------------------------------------------------------------
# Source Credibility — analytical depth scores by source
# ------------------------------------------------------------------
# Scale: 0.0 (untrusted) to 1.0 (highly trusted)
# Used by tier2_synthesizer.py for Section 2 narrative.
#
# NOTE: Credibility here reflects analytical rigor and data access,
# NOT directional accuracy. Sell-side has structural positive bias
# (compensation tied to deal flow; ratings skew constructive).
# Independent sources (Substack) have no such structural constraint.

SOURCE_CREDIBILITY = {
    'jefferies': 0.8,          # High rigor; structural positive/buy-side bias
    'jpmorgan': 0.8,
    'morgan_stanley': 0.8,
    'goldman': 0.8,
    'bernstein': 0.8,
    'citi': 0.75,
    'ubs': 0.75,
    'barclays': 0.75,
    'arete': 0.75,
    'macquarie': 0.75,
    'substack': 0.75,          # Independent; no structural directional bias; quality varies by author
    'podcast': 0.65,           # Market commentary; informal but unconstrained
 #   'x': 0.4,                  # Social media, low signal
    'unknown': 0.3,
}

# ------------------------------------------------------------------
# High-Alert Event Types — always surface in Section 1, never filtered
# ------------------------------------------------------------------
# Claims with these event_type values are shown regardless of claim cap.
# Maps to the event_type field in ClaimOutput (see claim_extractor.py).

HIGH_ALERT_EVENT_TYPES = {
    'earnings',    # Quarterly results, beats/misses, restatements, write-downs
    'guidance',    # Guidance changes, preannouncements, mid-quarter revisions
    'org',         # M&A, CEO/CFO/board changes, restructurings, spin-offs, bankruptcy
    'regulation',  # Antitrust actions, litigation outcomes, regulatory approval/denial
}
# Operational metric events (subscriber misses/beats, churn, ARPU, major contract wins/losses)
# map to event_type='market' with is_descriptive_event=True — also treated as high-alert.

# Source type groupings — used by synthesizer to surface cross-type tension
SELL_SIDE_SOURCES = {
    'jefferies', 'jpmorgan', 'morgan_stanley', 'goldman', 'bernstein',
    'citi', 'ubs', 'barclays', 'arete', 'macquarie',
}
INDEPENDENT_SOURCES = {'substack', 'podcast', 'x'}

# Source bias notes — passed to LLM synthesis prompt
SOURCE_BIAS_NOTES = {
    'sell_side': (
        'High analytical depth and data access. '
        'Structural positive bias: compensation tied to deal flow and buy-side relationships; '
    ),
    'independent': (
        'Quality varies by author but views are unconstrained by deal relationships. '
        'When independent sources diverge from sell-side, treat as high-signal.'
    ),
}

# ------------------------------------------------------------------
# Content Type Weights — fact vs interpretation
# ------------------------------------------------------------------

CONTENT_TYPE_WEIGHTS = {
    'fact': 1.0,               # Hard data points
    'forecast': 0.9,           # Predictions (actionable)
    'risk': 0.85,              # Risk factors (important)
    'interpretation': 0.7,     # Analyst opinion
}

# ------------------------------------------------------------------
# Asset Priority — loaded dynamically from config.TICKERS
# ------------------------------------------------------------------
# Do not hardcode here — tickers are per-user and configured in config.py / user_db.
# Use get_primary_tickers() and get_watchlist_tickers() at runtime.

## TICKER Company Names Index (reference only)
## META = Meta Platforms, Inc.
## BABA = Alibaba Group Holding Limited
## 700.HK = Tencent Holdings Ltd.
## NET = Cloudflare, Inc.
## MDB = MongoDB


def get_primary_tickers() -> set:
    """Load primary tickers from config.TICKERS at runtime (not hardcoded)."""
    import config
    return set(
        config.TICKERS.get('primary_internet', []) +
        config.TICKERS.get('primary_software', [])
    )


def get_watchlist_tickers() -> set:
    """Load watchlist tickers from config.TICKERS at runtime (not hardcoded)."""
    import config
    return set(
        config.TICKERS.get('watchlist_internet', []) +
        config.TICKERS.get('watchlist_software', [])
    )


def get_ticker_weight(
    tickers: List[str],
    primary_set: Optional[set] = None,
    watchlist_set: Optional[set] = None,
) -> float:
    """Return highest priority weight for a list of tickers."""
    if not tickers:
        return 0.5  # No ticker = sector/macro content
    if primary_set is None:
        primary_set = get_primary_tickers()
    if watchlist_set is None:
        watchlist_set = get_watchlist_tickers()
    has_primary = any(t in primary_set for t in tickers)
    has_watchlist = any(t in watchlist_set for t in tickers)
    if has_primary:
        return 1.0
    elif has_watchlist:
        return 0.7
    else:
        return 0.4  # Off-coverage ticker


# ------------------------------------------------------------------
# Relevance score threshold
# ------------------------------------------------------------------

RELEVANCE_THRESHOLD = 0.7

# ------------------------------------------------------------------
# Scoring Function
# ------------------------------------------------------------------

def score_chunk(
    chunk: Chunk,
    classification: ChunkClassification,
    source: str = 'unknown',
) -> float:
    """
    Compute relevance score for a classified chunk.

    Score = category_weight × content_weight × ticker_weight × source_credibility

    Returns: float 0.0–1.0
    """
    # Category score
    category_score = CATEGORY_WEIGHTS.get(classification.category, 0.0)
    if category_score == 0.0:
        return 0.0  # Irrelevant — hard filter

    # Content type
    content_score = CONTENT_TYPE_WEIGHTS.get(classification.content_type, 0.7)

    # Ticker relevance
    ticker_score = get_ticker_weight(classification.tickers)

    # Source credibility
    source_score = SOURCE_CREDIBILITY.get(source.lower(), 0.3)

    # Weighted sum (category dominates; ticker and content drive secondary ranking)
    raw_score = (
        category_score * 0.45 +
        content_score  * 0.25 +
        ticker_score   * 0.20 +
        source_score   * 0.10
    )

    return round(raw_score, 3)


def filter_chunks(
    chunks: List[Chunk],
    classifications: List[ChunkClassification],
    source: str = 'unknown',
    max_chunks: Optional[int] = None,
) -> List[Tuple[Chunk, ChunkClassification, float]]:
    """
    Filter and rank chunks by relevance score.

    Returns:
        List of (chunk, classification, score) tuples, sorted by score desc
    """
    if max_chunks is None:
        max_chunks = 50  # generous limit; per-ticker cap handles brevity

    scored = []
    for chunk, clf in zip(chunks, classifications):
        score = score_chunk(chunk, clf, source)
        if score >= RELEVANCE_THRESHOLD:
            scored.append((chunk, clf, score))

    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:max_chunks]


# ------------------------------------------------------------------
# TMT_CONFIG — AnalystConfig instance for compatibility
# ------------------------------------------------------------------

TMT_CONFIG = AnalystConfig(
    tickers={
        'primary_internet': ['META', 'GOOGL', 'AMZN', 'AAPL', 'BABA', '700.HK'],
        'primary_software': ['MSFT', 'CRWD', 'ZS', 'PANW', 'NET', 'DDOG', 'SNOW', 'MDB'],
        'watchlist_internet': ['NFLX', 'SPOT', 'U', 'APP', 'RBLX'],
        'watchlist_software': ['NET', 'ORCL', 'PLTR', 'SHOP'],
    },
    ticker_priority={
        'high': ['META', 'GOOGL', 'AMZN', 'AAPL', 'BABA', '700.HK',
                 'MSFT', 'CRWD', 'ZS', 'PANW', 'NET', 'DDOG', 'SNOW', 'MDB'],
        'medium': ['NFLX', 'SPOT', 'U', 'APP', 'RBLX', 'ORCL', 'PLTR', 'SHOP'],
    },
    trusted_analysts={
        'jefferies': ['Brent Thill', 'Joseph Gallo'],
    },
    themes=[
        {'name': 'AI Infrastructure', 'keywords': ['AI', 'LLM', 'GPU', 'inference', 'training'], 'priority': 'critical'},
        {'name': 'Cloud & SaaS', 'keywords': ['cloud', 'SaaS', 'ARR', 'NRR', 'consumption'], 'priority': 'high'},
        {'name': 'Cybersecurity', 'keywords': ['zero trust', 'XDR', 'SIEM', 'endpoint'], 'priority': 'high'},
        {'name': 'Digital Advertising', 'keywords': ['ad revenue', 'ROAS', 'programmatic'], 'priority': 'medium'},
    ],
    sources={
        'jefferies': {'enabled': True, 'credibility': 1.0},
        'substack': {'enabled': True, 'credibility': 0.6},
    },
    briefing_days=2,
    relevance_threshold=RELEVANCE_THRESHOLD,
)


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("TMT AnalystConfig — Relevance Policy Test")
    print("=" * 60)

    test_cases = [
        # High relevance: tracked ticker, primary coverage
        ChunkClassification(
            chunk_id="1",
            category="tracked_ticker",
            tickers=["META"],
            content_type="forecast",
            polarity="positive",
        ),
        # Medium relevance: TMT sector
        ChunkClassification(
            chunk_id="2",
            category="tmt_sector",
            content_type="fact",
            polarity="neutral",
        ),
        # Lower relevance: macro
        ChunkClassification(
            chunk_id="3",
            category="macro",
            tickers=[],
            content_type="fact",
            polarity="neutral",
        ),
        # Irrelevant — should score 0
        ChunkClassification(
            chunk_id="4",
            category="irrelevant",
            tickers=[],
            content_type="interpretation",
            polarity="neutral",
        ),
        # Tracked ticker, watchlist
        ChunkClassification(
            chunk_id="5",
            category="tracked_ticker",
            tickers=["NFLX"],
            content_type="risk",
            polarity="negative",
        ),
    ]

    dummy_chunks = [
        Chunk(chunk_id=clf.chunk_id, doc_id="test", text=f"Test chunk {clf.chunk_id}")
        for clf in test_cases
    ]

    print(f"\n{'ID':<4} {'Category':<16} {'Ticker':<8} {'Type':<14} {'Score':<6}")
    print("-" * 60)

    for clf in test_cases:
        score = score_chunk(Chunk(chunk_id=clf.chunk_id), clf)
        ticker = clf.tickers[0] if clf.tickers else "—"
        print(f"{clf.chunk_id:<4} {clf.category:<16} {ticker:<8} {clf.content_type:<14} {score:<6}")

    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    # Irrelevant should score 0
    irr_score = score_chunk(Chunk(chunk_id="x"), test_cases[3])
    assert irr_score == 0.0, f"Irrelevant should score 0, got {irr_score}"
    print("✓ Irrelevant content filtered (score=0)")

    # Tracked ticker should score higher than macro
    ticker_score = score_chunk(Chunk(chunk_id="x"), test_cases[0])
    macro_score = score_chunk(Chunk(chunk_id="x"), test_cases[2])
    assert ticker_score > macro_score, "Tracked ticker should score higher than macro"
    print("✓ tracked_ticker > macro (category weights)")

    # Primary tickers should score higher than watchlist
    primary_score = score_chunk(Chunk(chunk_id="x"), test_cases[0])
    watchlist_score = score_chunk(Chunk(chunk_id="x"), test_cases[4])
    assert primary_score > watchlist_score, "Primary ticker should score higher"
    print("✓ Primary tickers prioritized over watchlist")

    # Source credibility check
    assert SOURCE_CREDIBILITY['jefferies'] > SOURCE_CREDIBILITY['unknown']
    print("✓ Source credibility: sell-side > unknown")

    # Ticker getters should return non-empty sets
    primary = get_primary_tickers()
    watchlist = get_watchlist_tickers()
    assert len(primary) > 0, "Primary tickers should not be empty"
    assert len(watchlist) > 0, "Watchlist tickers should not be empty"
    print(f"✓ Primary tickers loaded from config: {len(primary)} tickers")
    print(f"✓ Watchlist tickers loaded from config: {len(watchlist)} tickers")

    print("\nConfig ready for V3 briefing pipeline.")
