"""
Sector-Scoped Briefing Filter — filter claims by sector/analyst/ticker scope.

Prevents non-TMT content from diluting TMT briefings.
Applied BEFORE tiering (ingest → filter → tier → synthesize).

Usage:
    from scope_filter import BriefingScope, apply_scope_filter

    scope = BriefingScope(primary_sector='TMT')
    filtered_claims, scope_meta = apply_scope_filter(claims, scope)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
import re

from claim_extractor import ClaimOutput
from classifier import TMT_TOPICS


# ------------------------------------------------------------------
# Scope Configuration
# ------------------------------------------------------------------

@dataclass
class BriefingScope:
    """
    Internal config for sector-scoped briefing filtering.

    Fields:
        primary_sector: Sector umbrella (default 'TMT').
                        Use 'ALL' to skip sector filtering.
        sub_sectors: Optional list of sub-sectors to include.
                     e.g., ['technology', 'media'] to exclude 'telecom'.
                     If None, all sub-sectors of primary_sector are included.
        analyst_whitelist: Optional list of analyst names to include.
                           Claims from other analysts are filtered out.
        ticker_whitelist: Optional list of tickers to include.
                          If set, only claims with these tickers pass.
                          Ticker-less claims are kept if they match sector.
    """
    primary_sector: str = 'TMT'
    sub_sectors: Optional[List[str]] = None
    analyst_whitelist: Optional[List[str]] = None
    ticker_whitelist: Optional[List[str]] = None

    def to_dict(self) -> dict:
        return {
            'primary_sector': self.primary_sector,
            'sub_sectors': self.sub_sectors,
            'analyst_whitelist': self.analyst_whitelist,
            'ticker_whitelist': self.ticker_whitelist,
        }


@dataclass
class ScopeFilterResult:
    """Result of scope filtering with metadata."""
    claims: List[ClaimOutput]
    original_count: int
    filtered_count: int
    is_thin_day: bool
    thin_day_reason: Optional[str] = None
    scope_applied: Optional[BriefingScope] = None

    @property
    def drop_rate(self) -> float:
        if self.original_count == 0:
            return 0.0
        return 1.0 - (self.filtered_count / self.original_count)

    def summary(self) -> str:
        lines = [f"Scope filter: {self.original_count} → {self.filtered_count} claims"]
        if self.is_thin_day:
            lines.append(f"  ⚠ Thin day: {self.thin_day_reason}")
        return '\n'.join(lines)


# ------------------------------------------------------------------
# TMT Sector Mapping
# ------------------------------------------------------------------

# Topics that belong to TMT sector (from classifier.py)
TMT_SECTOR_TOPICS = set()
for category, topics in TMT_TOPICS.items():
    TMT_SECTOR_TOPICS.update(topics)

# Mapping from sub-sector to topics
SUBSECTOR_TOPICS = {
    'technology': {'ai_ml', 'cloud', 'software', 'infrastructure', 'semiconductors', 'hardware'},
    'media': {'advertising', 'content', 'gaming', 'social'},
    'telecom': {'networks', 'telecom_infra'},
    'other': {'ecommerce', 'fintech', 'cybersecurity', 'general'},
}

# Thin-day threshold: if fewer than this many claims, mark as thin
THIN_DAY_THRESHOLD = 3


# ------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------

def _extract_analyst_from_citation(citation: str) -> Optional[str]:
    """
    Extract analyst name from source citation.
    Citation format: "Jefferies, Brent Thill, p.2, 2026-01-25"
    """
    parts = [p.strip() for p in citation.split(',')]
    # Analyst is typically the second part (after firm)
    if len(parts) >= 2:
        candidate = parts[1]
        # Skip if it looks like a page number or date
        if not candidate.startswith('p.') and not re.match(r'\d{4}-', candidate):
            return candidate
    return None


def _get_claim_topic(claim: ClaimOutput) -> Optional[str]:
    """
    Infer topic from claim. Since ClaimOutput doesn't store topic directly,
    we pass it through from classification during filtering.
    Returns None if topic unknown.
    """
    # Topic is stored in claim_type (fact/forecast/risk/interpretation)
    # which is different from the topic taxonomy.
    # We need to rely on ticker mapping or text analysis.
    return None


def _ticker_in_scope(ticker: Optional[str], ticker_whitelist: Optional[List[str]]) -> bool:
    """Check if ticker is in whitelist (or whitelist is None)."""
    if ticker_whitelist is None:
        return True
    if ticker is None:
        # Ticker-less claims: keep them (they may be macro/thematic)
        return True
    return ticker.upper() in [t.upper() for t in ticker_whitelist]


def _analyst_in_scope(citation: str, analyst_whitelist: Optional[List[str]]) -> bool:
    """Check if analyst is in whitelist (or whitelist is None)."""
    if analyst_whitelist is None:
        return True
    analyst = _extract_analyst_from_citation(citation)
    if analyst is None:
        return True  # Can't determine, keep it
    # Case-insensitive partial match
    analyst_lower = analyst.lower()
    return any(a.lower() in analyst_lower or analyst_lower in a.lower()
               for a in analyst_whitelist)


# ------------------------------------------------------------------
# Main Filter Function
# ------------------------------------------------------------------

def apply_scope_filter(
    claims: List[ClaimOutput],
    scope: Optional[BriefingScope] = None,
    topic_map: Optional[Dict[str, str]] = None,
) -> ScopeFilterResult:
    """
    Filter claims by sector scope.

    Args:
        claims: List of ClaimOutput from claim extraction
        scope: BriefingScope config (defaults to TMT-all if None)
        topic_map: Optional mapping from chunk_id to topic
                   (for sector filtering when topics available)

    Returns:
        ScopeFilterResult with filtered claims and metadata
    """
    if scope is None:
        scope = BriefingScope()

    original_count = len(claims)

    # Skip filtering if sector is 'ALL'
    if scope.primary_sector.upper() == 'ALL':
        return ScopeFilterResult(
            claims=claims,
            original_count=original_count,
            filtered_count=original_count,
            is_thin_day=original_count < THIN_DAY_THRESHOLD,
            thin_day_reason="Low volume" if original_count < THIN_DAY_THRESHOLD else None,
            scope_applied=scope,
        )

    filtered = []

    for claim in claims:
        # Check ticker whitelist
        if not _ticker_in_scope(claim.ticker, scope.ticker_whitelist):
            continue

        # Check analyst whitelist
        if not _analyst_in_scope(claim.source_citation, scope.analyst_whitelist):
            continue

        # Topic filtering (if topic_map provided)
        if topic_map and scope.sub_sectors:
            topic = topic_map.get(claim.chunk_id, 'general')
            allowed_topics = set()
            for subsec in scope.sub_sectors:
                allowed_topics.update(SUBSECTOR_TOPICS.get(subsec, set()))
            if topic not in allowed_topics and topic != 'general':
                continue

        # Passed all filters
        filtered.append(claim)

    filtered_count = len(filtered)
    is_thin_day = filtered_count < THIN_DAY_THRESHOLD

    # Determine thin day reason
    thin_day_reason = None
    if is_thin_day:
        if original_count == 0:
            thin_day_reason = "No source data available"
        elif filtered_count == 0:
            thin_day_reason = "No claims within scope"
        else:
            thin_day_reason = "Low volume within scope"

    return ScopeFilterResult(
        claims=filtered,
        original_count=original_count,
        filtered_count=filtered_count,
        is_thin_day=is_thin_day,
        thin_day_reason=thin_day_reason,
        scope_applied=scope,
    )


def get_thin_day_label(result: ScopeFilterResult) -> str:
    """Generate thin-day label for briefing rendering."""
    if not result.is_thin_day:
        return ""

    reason = result.thin_day_reason or "Limited data"
    return f"*Note: {reason}. No cross-report confirmation within scope.*"


# ------------------------------------------------------------------
# Default Scopes
# ------------------------------------------------------------------

# Default TMT scope (all TMT sub-sectors, no whitelist restrictions)
DEFAULT_TMT_SCOPE = BriefingScope(
    primary_sector='TMT',
    sub_sectors=None,  # All TMT sub-sectors
    analyst_whitelist=None,
    ticker_whitelist=None,
)

# Internet + Software focus (from config.py)
INTERNET_SOFTWARE_SCOPE = BriefingScope(
    primary_sector='TMT',
    sub_sectors=['technology', 'media'],
    analyst_whitelist=None,
    ticker_whitelist=[
        # Primary coverage
        'META', 'GOOGL', 'AMZN', 'AAPL', 'BABA', 'MSFT',
        'CRWD', 'ZS', 'PANW', 'NET', 'DDOG', 'SNOW', 'MDB',
        # Watchlist
        'NFLX', 'SPOT', 'U', 'APP', 'RBLX', 'ORCL', 'PLTR', 'SHOP',
    ],
)


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Sector-Scoped Briefing Filter")
    print("=" * 60)

    # Create sample claims
    sample_claims = [
        ClaimOutput(
            chunk_id="chunk-1",
            doc_id="doc-1",
            bullets=["META ad revenue grew 28% YoY"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, Brent Thill, p.1, 2026-01-30",
            confidence_level="high",
            time_sensitivity="breaking",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="chunk-2",
            doc_id="doc-2",
            bullets=["CMS Energy ROE at 8.2%"],
            ticker="CMS",
            claim_type="fact",
            source_citation="Jefferies, Paul Lee, p.2, 2026-01-30",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="unclear",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="chunk-3",
            doc_id="doc-3",
            bullets=["AI capex driving cloud growth"],
            ticker=None,
            claim_type="interpretation",
            source_citation="Jefferies, Brent Thill, p.3, 2026-01-30",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="chunk-4",
            doc_id="doc-4",
            bullets=["CRWD endpoint share at 58%"],
            ticker="CRWD",
            claim_type="fact",
            source_citation="Jefferies, Joseph Gallo, p.1, 2026-01-30",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="contradicts_consensus",
            uncertainty_preserved=False,
        ),
    ]

    print(f"\nInput: {len(sample_claims)} claims")
    for c in sample_claims:
        ticker = c.ticker or "(no ticker)"
        print(f"  - {ticker}: {c.bullets[0][:50]}...")

    # Test 1: Default TMT scope (no filtering)
    print("\n" + "-" * 60)
    print("Test 1: Default TMT scope")
    print("-" * 60)
    result = apply_scope_filter(sample_claims, DEFAULT_TMT_SCOPE)
    print(result.summary())
    print(f"  Kept: {[c.ticker or '(macro)' for c in result.claims]}")

    # Test 2: Internet/Software scope with ticker whitelist
    print("\n" + "-" * 60)
    print("Test 2: Internet/Software scope (ticker whitelist)")
    print("-" * 60)
    result = apply_scope_filter(sample_claims, INTERNET_SOFTWARE_SCOPE)
    print(result.summary())
    print(f"  Kept: {[c.ticker or '(macro)' for c in result.claims]}")
    # CMS should be filtered out

    # Test 3: Analyst whitelist
    print("\n" + "-" * 60)
    print("Test 3: Analyst whitelist (Brent Thill only)")
    print("-" * 60)
    scope = BriefingScope(analyst_whitelist=['Brent Thill'])
    result = apply_scope_filter(sample_claims, scope)
    print(result.summary())
    print(f"  Kept: {[c.ticker or '(macro)' for c in result.claims]}")

    # Test 4: Empty result (thin day)
    print("\n" + "-" * 60)
    print("Test 4: Thin day scenario")
    print("-" * 60)
    scope = BriefingScope(ticker_whitelist=['XYZ'])  # Non-existent ticker
    result = apply_scope_filter(sample_claims, scope)
    print(result.summary())
    if result.is_thin_day:
        print(f"  Label: {get_thin_day_label(result)}")

    # Verification
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    # Test default scope keeps all claims
    result = apply_scope_filter(sample_claims, DEFAULT_TMT_SCOPE)
    assert result.filtered_count == 4, "Default scope should keep all TMT claims"
    print("✓ Default scope preserves all claims")

    # Test ticker whitelist filters non-matching
    result = apply_scope_filter(sample_claims, INTERNET_SOFTWARE_SCOPE)
    assert result.filtered_count == 3, "CMS should be filtered out"
    assert all(c.ticker != 'CMS' for c in result.claims), "CMS claim should not be in result"
    print("✓ Ticker whitelist filters non-TMT stocks")

    # Test analyst whitelist
    scope = BriefingScope(analyst_whitelist=['Brent Thill'])
    result = apply_scope_filter(sample_claims, scope)
    assert result.filtered_count == 2, "Only Brent Thill claims should remain"
    print("✓ Analyst whitelist filters correctly")

    # Test thin day detection
    scope = BriefingScope(ticker_whitelist=['NONEXISTENT'])
    result = apply_scope_filter(sample_claims, scope)
    # Macro claims (no ticker) are kept even with ticker whitelist
    assert result.is_thin_day, "Should detect thin day"
    print("✓ Thin day detection works")

    print("\n✓ All scope filter tests passed")
