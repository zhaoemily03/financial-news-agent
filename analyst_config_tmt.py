"""
Hardcoded AnalystConfig for TMT (Technology, Media, Telecom) analyst.
Explicit relevance policy — intentionally lossy to enforce <5-page constraint.

This config defines:
- Topic weights (AI infra > consumer internet)
- Source credibility (Jefferies high)
- Minimum novelty threshold
- Target daily claim count (20-30)

Usage:
    from analyst_config_tmt import TMT_CONFIG, score_chunk, filter_chunks

    scored = [(chunk, score_chunk(chunk, clf)) for chunk, clf in zip(chunks, classifications)]
    filtered = filter_chunks(chunks, classifications)
"""

from typing import List, Tuple, Optional
from dataclasses import dataclass, field
from schemas import Chunk, AnalystConfig
from classifier import ChunkClassification

# ------------------------------------------------------------------
# Topic Weights — higher = more relevant to TMT analyst
# ------------------------------------------------------------------
# Scale: 0.0 (ignore) to 1.0 (critical)
# AI/infra prioritized over consumer internet per spec

TOPIC_WEIGHTS = {
    # Technology — highest priority
    'ai_ml': 1.0,              # AI infrastructure, LLMs, ML
    'cloud': 0.9,              # Cloud computing, IaaS, PaaS
    'infrastructure': 0.85,    # Data centers, servers
    'semiconductors': 0.8,     # Chips, GPUs (AI enablers)
    'software': 0.75,          # Enterprise software, SaaS
    'cybersecurity': 0.7,      # Security (adjacent to infra)

    # Media — moderate priority
    'advertising': 0.6,        # Digital ads (META, GOOGL revenue)
    'social': 0.55,            # Social networks
    'content': 0.5,            # Streaming, video
    'gaming': 0.45,            # Games, virtual worlds

    # Telecom — lower priority for TMT software focus
    'networks': 0.4,           # 5G, wireless
    'telecom_infra': 0.35,     # Towers, fiber

    # Other
    'ecommerce': 0.5,          # Online retail (AMZN, BABA)
    'fintech': 0.4,            # Payments
    'hardware': 0.45,          # Consumer devices
    'general': 0.3,            # Catch-all, low priority
}

# ------------------------------------------------------------------
# Source Credibility — trust scores by source
# ------------------------------------------------------------------
# Scale: 0.0 (untrusted) to 1.0 (highly trusted)

SOURCE_CREDIBILITY = {
    'jefferies': 1.0,          # Primary trusted source
    'jpmorgan': 0.9,           # Tier 1 bank (when enabled)
    'morgan_stanley': 0.9,
    'goldman': 0.9,
    'bofa': 0.85,
    'citi': 0.85,
    'ubs': 0.8,
    'barclays': 0.8,
    'substack': 0.6,           # Independent, variable quality
    'x': 0.4,                  # Social media, low signal
    'unknown': 0.3,
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
# Novelty Thresholds
# ------------------------------------------------------------------
# Filter out stale/rehashed content

NOVELTY_WEIGHTS = {
    'new': 1.0,                # Fresh information
    'incremental': 0.6,        # Updates to known info
    'rehash': 0.2,             # Already known, low value
}

MINIMUM_NOVELTY_THRESHOLD = 0.3  # Effectively filters out 'rehash'

# ------------------------------------------------------------------
# Polarity Weights — slight bias toward actionable signals
# ------------------------------------------------------------------

POLARITY_WEIGHTS = {
    'positive': 1.0,           # Bullish signals
    'negative': 1.0,           # Risk signals (equally important)
    'mixed': 0.8,              # Nuanced, still valuable
    'neutral': 0.6,            # Less actionable
}

# ------------------------------------------------------------------
# Asset Priority — primary vs watchlist tickers
# ------------------------------------------------------------------

PRIMARY_TICKERS = {
    'META', 'GOOGL', 'AMZN', 'AAPL', 'BABA', '700.HK',  # Internet
    'MSFT', 'CRWD', 'ZS', 'PANW', 'NET', 'DDOG', 'SNOW', 'MDB',  # Software
}

WATCHLIST_TICKERS = {
    'NFLX', 'SPOT', 'U', 'APP', 'RBLX',  # Internet watchlist
    'NET', 'ORCL', 'PLTR', 'SHOP',  # Software watchlist (NET in both primary and watchlist per config.py)
}

def get_ticker_weight(tickers: List[str]) -> float:
    """Return highest priority weight for a list of tickers."""
    if not tickers:
        return 0.5  # No ticker = generic content

    has_primary = any(t in PRIMARY_TICKERS for t in tickers)
    has_watchlist = any(t in WATCHLIST_TICKERS for t in tickers)

    if has_primary:
        return 1.0
    elif has_watchlist:
        return 0.7
    else:
        return 0.4  # Off-coverage ticker

# ------------------------------------------------------------------
# Daily Output Constraints
# ------------------------------------------------------------------

TARGET_CLAIM_COUNT = 25        # Target 20-30 claims per day
MIN_CLAIM_COUNT = 20
MAX_CLAIM_COUNT = 30

# Relevance score threshold — chunks below this are dropped
# Matches config.py RELEVANCE_THRESHOLD
RELEVANCE_THRESHOLD = 0.7

# ------------------------------------------------------------------
# Scoring Function
# ------------------------------------------------------------------

def score_chunk(
    chunk: Chunk,
    classification: ChunkClassification,
    source: str = 'jefferies',
) -> float:
    """
    Compute relevance score for a classified chunk.

    Score = topic_weight × content_weight × novelty_weight × polarity_weight
            × ticker_weight × source_credibility

    Returns: float 0.0–1.0
    """
    # Topic score (use primary, boost if secondary also relevant)
    topic_score = TOPIC_WEIGHTS.get(classification.topic, 0.3)
    if classification.topic_secondary:
        secondary = TOPIC_WEIGHTS.get(classification.topic_secondary, 0.3)
        topic_score = min(1.0, topic_score + secondary * 0.2)

    # Content type
    content_score = CONTENT_TYPE_WEIGHTS.get(classification.content_type, 0.7)

    # Novelty (hard filter + weight)
    novelty_score = NOVELTY_WEIGHTS.get(classification.novelty, 0.5)
    if novelty_score < MINIMUM_NOVELTY_THRESHOLD:
        return 0.0  # Hard filter for rehash

    # Polarity
    polarity_score = POLARITY_WEIGHTS.get(classification.polarity, 0.6)

    # Ticker relevance
    ticker_score = get_ticker_weight(classification.asset_exposure)

    # Source credibility
    source_score = SOURCE_CREDIBILITY.get(source.lower(), 0.3)

    # Weighted product (geometric mean-ish)
    raw_score = (
        topic_score * 0.30 +
        content_score * 0.15 +
        novelty_score * 0.20 +
        polarity_score * 0.10 +
        ticker_score * 0.15 +
        source_score * 0.10
    )

    return round(raw_score, 3)


def filter_chunks(
    chunks: List[Chunk],
    classifications: List[ChunkClassification],
    source: str = 'jefferies',
    max_chunks: Optional[int] = None,
) -> List[Tuple[Chunk, ChunkClassification, float]]:
    """
    Filter and rank chunks by relevance score.

    Args:
        chunks: List of Chunk objects
        classifications: Corresponding ChunkClassification objects
        source: Source name for credibility lookup
        max_chunks: Optional limit (defaults to MAX_CLAIM_COUNT)

    Returns:
        List of (chunk, classification, score) tuples, sorted by score desc
    """
    if max_chunks is None:
        max_chunks = MAX_CLAIM_COUNT

    # Score all chunks
    scored = []
    for chunk, clf in zip(chunks, classifications):
        score = score_chunk(chunk, clf, source)
        if score >= RELEVANCE_THRESHOLD:
            scored.append((chunk, clf, score))

    # Sort by score descending
    scored.sort(key=lambda x: x[2], reverse=True)

    # Enforce max limit (lossy by design)
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
    briefing_days=5,
    relevance_threshold=RELEVANCE_THRESHOLD,
)


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    from classifier import ChunkClassification

    print("=" * 60)
    print("TMT AnalystConfig — Relevance Policy Test")
    print("=" * 60)

    # Sample classifications to test scoring
    test_cases = [
        # High relevance: AI topic, new info, primary ticker
        ChunkClassification(
            chunk_id="1",
            topic="ai_ml",
            asset_exposure=["META"],
            content_type="forecast",
            polarity="positive",
            novelty="new",
        ),
        # Medium relevance: advertising, incremental
        ChunkClassification(
            chunk_id="2",
            topic="advertising",
            asset_exposure=["GOOGL"],
            content_type="fact",
            polarity="neutral",
            novelty="incremental",
        ),
        # Low relevance: general topic, rehash
        ChunkClassification(
            chunk_id="3",
            topic="general",
            asset_exposure=[],
            content_type="interpretation",
            polarity="neutral",
            novelty="rehash",
        ),
        # Risk signal: cybersecurity, negative
        ChunkClassification(
            chunk_id="4",
            topic="cybersecurity",
            asset_exposure=["CRWD"],
            content_type="risk",
            polarity="negative",
            novelty="new",
        ),
        # Off-coverage ticker
        ChunkClassification(
            chunk_id="5",
            topic="fintech",
            asset_exposure=["SQ"],
            content_type="fact",
            polarity="positive",
            novelty="new",
        ),
    ]

    # Create dummy chunks for testing
    dummy_chunks = [
        Chunk(chunk_id=clf.chunk_id, doc_id="test", text=f"Test chunk {clf.chunk_id}")
        for clf in test_cases
    ]

    print("\nScoring individual classifications:\n")
    print(f"{'ID':<4} {'Topic':<15} {'Ticker':<8} {'Type':<12} {'Novelty':<10} {'Score':<6}")
    print("-" * 60)

    for clf in test_cases:
        score = score_chunk(Chunk(chunk_id=clf.chunk_id), clf, 'jefferies')
        ticker = clf.asset_exposure[0] if clf.asset_exposure else "—"
        print(f"{clf.chunk_id:<4} {clf.topic:<15} {ticker:<8} {clf.content_type:<12} {clf.novelty:<10} {score:<6}")

    print("\n" + "=" * 60)
    print("Filter Test (threshold={}, max={})".format(RELEVANCE_THRESHOLD, MAX_CLAIM_COUNT))
    print("=" * 60)

    filtered = filter_chunks(dummy_chunks, test_cases)
    print(f"\nInput: {len(test_cases)} chunks → Output: {len(filtered)} chunks")
    print("\nPassed filter:")
    for chunk, clf, score in filtered:
        print(f"  [{clf.chunk_id}] {clf.topic:<15} score={score}")

    # Verify lossy behavior
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    # Rehash should be filtered out
    rehash_scores = [score_chunk(Chunk(chunk_id="x"), clf) for clf in test_cases if clf.novelty == 'rehash']
    assert all(s == 0.0 for s in rehash_scores), "Rehash should score 0"
    print("✓ Rehash content filtered (score=0)")

    # AI/ML should score higher than general
    ai_score = score_chunk(Chunk(chunk_id="x"), test_cases[0])
    ad_score = score_chunk(Chunk(chunk_id="x"), test_cases[1])
    assert ai_score > ad_score, "AI should score higher than advertising"
    print("✓ AI infra > consumer internet (topic weights)")

    # Primary tickers should score higher than off-coverage
    primary_score = score_chunk(Chunk(chunk_id="x"), test_cases[0])
    off_coverage_score = score_chunk(Chunk(chunk_id="x"), test_cases[4])
    assert primary_score > off_coverage_score, "Primary ticker should score higher"
    print("✓ Primary tickers prioritized over off-coverage")

    # Filter enforces max limit
    assert len(filtered) <= MAX_CLAIM_COUNT
    print(f"✓ Output capped at {MAX_CLAIM_COUNT} claims (lossy by design)")

    print(f"\nTarget daily claim count: {MIN_CLAIM_COUNT}–{MAX_CLAIM_COUNT}")
    print("Config ready for <5-page briefing constraint.")
