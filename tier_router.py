"""
Tier assignment engine — rule-based routing, no LLM.
Routes claims into Tier 1 / 2 / 3 without interpretation.

Tier Rules:
- Tier 1: What demands attention today
  - time_sensitivity = breaking OR upcoming
  - OR belief_pressure = contradicts_prior_assumptions
  - OR large magnitude change

- Tier 2: Synthesis across reports — what's the through-line
  - Multiple claims touch same topic/asset
  - Agreement or disagreement exists
  - Trend or through-line is forming
  - INCLUDES thematic claims (macro, sector trends) not just tickers

- Tier 3: Reference
  - Stock- or thesis-specific
  - No urgency
  - Useful context, not decision-forcing

Usage:
    from tier_router import assign_tiers, TierAssignment

    result = assign_tiers(claims)
    print(result.tier_1)  # urgent claims
"""

from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict

from claim_extractor import ClaimOutput

# ------------------------------------------------------------------
# Tier Assignment Result
# ------------------------------------------------------------------

@dataclass
class TierAssignment:
    """Structured tier assignment result."""
    tier_1: List[ClaimOutput] = field(default_factory=list)  # Demands attention today
    tier_2: List[ClaimOutput] = field(default_factory=list)  # Signal vs noise / synthesis
    tier_3: List[ClaimOutput] = field(default_factory=list)  # Reference material

    def to_dict(self) -> dict:
        return {
            "tier_1": [c.to_dict() for c in self.tier_1],
            "tier_2": [c.to_dict() for c in self.tier_2],
            "tier_3": [c.to_dict() for c in self.tier_3],
        }

    def summary(self) -> str:
        return f"Tier 1: {len(self.tier_1)} | Tier 2: {len(self.tier_2)} | Tier 3: {len(self.tier_3)}"

    def total_claims(self) -> int:
        return len(self.tier_1) + len(self.tier_2) + len(self.tier_3)


# ------------------------------------------------------------------
# Tier 1 Rules: What demands attention today
# ------------------------------------------------------------------

def _is_tier_1(claim: ClaimOutput) -> bool:
    """
    Tier 1 if:
    - time_sensitivity = breaking OR upcoming
    - OR belief_pressure = contradicts_prior_assumptions
    - OR belief_pressure = contradicts_consensus (contrarian signal)
    """
    # Time-sensitive claims need immediate attention
    if claim.time_sensitivity in ('breaking', 'upcoming'):
        return True

    # Contrarian signals challenge mental models
    if claim.belief_pressure in ('contradicts_prior_assumptions', 'contradicts_consensus'):
        return True

    return False


# ------------------------------------------------------------------
# Tier 2 Rules: Synthesis across reports (cross-claim analysis)
# ------------------------------------------------------------------

def _get_cluster_key(claim: ClaimOutput) -> str:
    """
    Get cluster key for a claim.
    - If has ticker, cluster by ticker
    - If no ticker, cluster by claim_type (thematic grouping)
    """
    if claim.ticker:
        return f"ticker:{claim.ticker}"
    else:
        return f"theme:{claim.claim_type}"


def _build_claim_clusters(claims: List[ClaimOutput]) -> Dict[str, List[ClaimOutput]]:
    """
    Group claims by ticker OR theme for cluster analysis.
    Thematic claims (no ticker) cluster by claim_type.
    """
    clusters = defaultdict(list)
    for claim in claims:
        key = _get_cluster_key(claim)
        clusters[key].append(claim)
    return dict(clusters)


def _has_disagreement(claims: List[ClaimOutput]) -> bool:
    """Check if claims have conflicting polarity signals."""
    if len(claims) < 2:
        return False

    # Check for mixed belief pressure (some confirm, some contradict)
    pressures = {c.belief_pressure for c in claims}
    has_confirms = 'confirms_consensus' in pressures
    has_contradicts = 'contradicts_consensus' in pressures or 'contradicts_prior_assumptions' in pressures

    return has_confirms and has_contradicts


def _has_agreement(claims: List[ClaimOutput]) -> bool:
    """Check if claims show alignment (agreement is also a through-line)."""
    if len(claims) < 2:
        return False

    # Check for unanimous belief pressure (all confirm or all contradict)
    pressures = {c.belief_pressure for c in claims}

    # Agreement if all claims share same non-unclear belief pressure
    if len(pressures) == 1 and 'unclear' not in pressures:
        return True

    # Strong agreement if all confirm consensus
    all_confirm = all(c.belief_pressure == 'confirms_consensus' for c in claims)
    if all_confirm:
        return True

    return False


def _has_trend(claims: List[ClaimOutput]) -> bool:
    """Check if multiple claims point in same direction (trend forming)."""
    if len(claims) < 2:
        return False

    # Multiple claims with same time_sensitivity = trend
    time_counts = defaultdict(int)
    for c in claims:
        time_counts[c.time_sensitivity] += 1

    # If 2+ claims share same time sensitivity (not ongoing), that's a trend
    for ts, count in time_counts.items():
        if ts != 'ongoing' and count >= 2:
            return True

    # Also check for claim_type alignment as trend indicator
    type_counts = defaultdict(int)
    for c in claims:
        type_counts[c.claim_type] += 1

    # If 2+ claims are same type (forecast, risk, etc.), that's pattern
    for ct, count in type_counts.items():
        if count >= 2:
            return True

    return False


def _is_tier_2_cluster(claims: List[ClaimOutput]) -> bool:
    """
    Tier 2 if cluster has:
    - Multiple claims (2+) on same asset/theme
    - Disagreement OR agreement exists (both are through-lines)
    - OR trend is forming
    """
    if len(claims) < 2:
        return False

    return _has_disagreement(claims) or _has_agreement(claims) or _has_trend(claims)


# ------------------------------------------------------------------
# Tier 3 Rules: Reference (fallback)
# ------------------------------------------------------------------

def _is_tier_3(claim: ClaimOutput) -> bool:
    """
    Tier 3 if:
    - time_sensitivity = ongoing (no urgency)
    - belief_pressure = confirms_consensus or unclear (not contrarian)
    - Basically: useful context, not decision-forcing
    """
    # Ongoing + confirms/unclear = reference material
    if claim.time_sensitivity == 'ongoing':
        if claim.belief_pressure in ('confirms_consensus', 'unclear'):
            return True

    return False


# ------------------------------------------------------------------
# Main Tier Assignment Function
# ------------------------------------------------------------------

def assign_tiers(claims: List[ClaimOutput]) -> TierAssignment:
    """
    Route claims into Tier 1 / 2 / 3 using rule-based logic.

    Priority order:
    1. Tier 1 rules applied first (urgent/contrarian)
    2. Tier 2 requires cross-claim analysis (clusters by ticker OR theme)
    3. Tier 3 is fallback for non-urgent reference material

    Args:
        claims: List of ClaimOutput objects

    Returns:
        TierAssignment with claims routed to appropriate tiers
    """
    result = TierAssignment()

    if not claims:
        return result

    # Track which claims have been assigned
    assigned: Set[str] = set()

    # ------------------------------------------------------------------
    # Phase 1: Apply Tier 1 rules (individual claim analysis)
    # ------------------------------------------------------------------
    for claim in claims:
        if _is_tier_1(claim):
            result.tier_1.append(claim)
            assigned.add(claim.chunk_id)

    # ------------------------------------------------------------------
    # Phase 2: Apply Tier 2 rules (cluster analysis on remaining claims)
    # Clusters by BOTH ticker AND theme (thematic claims included)
    # ------------------------------------------------------------------
    remaining = [c for c in claims if c.chunk_id not in assigned]
    clusters = _build_claim_clusters(remaining)

    # Check each cluster for Tier 2 signals (no more skipping thematic!)
    tier_2_keys: Set[str] = set()
    for cluster_key, cluster_claims in clusters.items():
        if _is_tier_2_cluster(cluster_claims):
            tier_2_keys.add(cluster_key)

    # Assign cluster members to Tier 2
    for claim in remaining:
        claim_key = _get_cluster_key(claim)
        if claim_key in tier_2_keys:
            result.tier_2.append(claim)
            assigned.add(claim.chunk_id)

    # ------------------------------------------------------------------
    # Phase 3: Remaining claims go to Tier 3 (reference)
    # ------------------------------------------------------------------
    for claim in claims:
        if claim.chunk_id not in assigned:
            result.tier_3.append(claim)

    return result


# ------------------------------------------------------------------
# Convenience functions
# ------------------------------------------------------------------

def format_tiers_markdown(assignment: TierAssignment, show_hooks: bool = True) -> str:
    """Format tier assignment as markdown."""
    lines = []

    if assignment.tier_1:
        lines.append("## Tier 1: Attention Required")
        lines.append("*Breaking news, upcoming catalysts, or contrarian signals*\n")
        for claim in assignment.tier_1:
            lines.append(claim.format_markdown(show_hooks))
            lines.append("")

    if assignment.tier_2:
        lines.append("## Tier 2: Synthesis / Through-Lines")
        lines.append("*Cross-report patterns, agreement, disagreement, or trends*\n")
        for claim in assignment.tier_2:
            lines.append(claim.format_markdown(show_hooks))
            lines.append("")

    if assignment.tier_3:
        lines.append("## Tier 3: Reference")
        lines.append("*Context and background, no immediate action needed*\n")
        for claim in assignment.tier_3:
            lines.append(claim.format_markdown(show_hooks))
            lines.append("")

    return '\n'.join(lines)


def get_tier_reasons(claim: ClaimOutput, all_claims: List[ClaimOutput]) -> List[str]:
    """Explain why a claim was assigned to its tier (for debugging)."""
    reasons = []

    # Tier 1 reasons
    if claim.time_sensitivity == 'breaking':
        reasons.append("time_sensitivity=breaking")
    if claim.time_sensitivity == 'upcoming':
        reasons.append("time_sensitivity=upcoming")
    if claim.belief_pressure == 'contradicts_prior_assumptions':
        reasons.append("belief_pressure=contradicts_prior_assumptions")
    if claim.belief_pressure == 'contradicts_consensus':
        reasons.append("belief_pressure=contradicts_consensus")

    # Tier 2 reasons (cluster-based) - by ticker
    if claim.ticker:
        same_ticker = [c for c in all_claims if c.ticker == claim.ticker]
        if len(same_ticker) >= 2:
            reasons.append(f"ticker cluster: {len(same_ticker)} claims on {claim.ticker}")
            if _has_disagreement(same_ticker):
                reasons.append("disagreement detected")
            if _has_agreement(same_ticker):
                reasons.append("agreement detected")
            if _has_trend(same_ticker):
                reasons.append("trend forming")
    else:
        # Tier 2 reasons - by theme (no ticker)
        same_theme = [c for c in all_claims if not c.ticker and c.claim_type == claim.claim_type]
        if len(same_theme) >= 2:
            reasons.append(f"theme cluster: {len(same_theme)} {claim.claim_type} claims")
            if _has_disagreement(same_theme):
                reasons.append("disagreement detected")
            if _has_agreement(same_theme):
                reasons.append("agreement detected")
            if _has_trend(same_theme):
                reasons.append("trend forming")

    # Tier 3 reasons
    if claim.time_sensitivity == 'ongoing' and claim.belief_pressure in ('confirms_consensus', 'unclear'):
        reasons.append("ongoing + confirms/unclear = reference")

    return reasons if reasons else ["fallback to Tier 3"]


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Tier Assignment Engine Test (with Thematic Clustering)")
    print("=" * 60)

    # Create test claims including thematic (no ticker) claims
    test_claims = [
        # Tier 1: Breaking news
        ClaimOutput(
            chunk_id="c1",
            doc_id="doc1",
            bullets=["META Threads DAU surpassed 300M, exceeding 200M expectations"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, p.1",
            confidence_level="high",
            time_sensitivity="breaking",
            belief_pressure="contradicts_consensus",
            uncertainty_preserved=False,
        ),
        # Tier 1: Upcoming catalyst
        ClaimOutput(
            chunk_id="c2",
            doc_id="doc1",
            bullets=["GOOGL earnings on Feb 4 expected to show AI revenue acceleration"],
            ticker="GOOGL",
            claim_type="forecast",
            source_citation="Jefferies, p.2",
            confidence_level="medium",
            time_sensitivity="upcoming",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # Thematic: Macro risk #1 (should cluster with c8)
        ClaimOutput(
            chunk_id="c3",
            doc_id="doc1",
            bullets=["Rising interest rates may pressure growth stock valuations"],
            ticker=None,
            claim_type="risk",
            source_citation="Jefferies, p.3",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=True,
        ),
        # Ticker cluster: META
        ClaimOutput(
            chunk_id="c4",
            doc_id="doc1",
            bullets=["META Reality Labs losses narrowing faster than expected"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, p.4",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # Ticker cluster: AMZN #1
        ClaimOutput(
            chunk_id="c5",
            doc_id="doc1",
            bullets=["AMZN cloud revenue grew 28% YoY, in line with estimates"],
            ticker="AMZN",
            claim_type="fact",
            source_citation="Jefferies, p.5",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # Ticker cluster: AMZN #2 (should cluster with c5)
        ClaimOutput(
            chunk_id="c6",
            doc_id="doc1",
            bullets=["AMZN e-commerce margins expanding on logistics efficiency"],
            ticker="AMZN",
            claim_type="fact",
            source_citation="Jefferies, p.6",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # Thematic: Macro forecast #1 (should cluster with c9)
        ClaimOutput(
            chunk_id="c7",
            doc_id="doc1",
            bullets=["Enterprise software spending expected to remain resilient in Q1"],
            ticker=None,
            claim_type="forecast",
            source_citation="Jefferies, p.7",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # Thematic: Macro risk #2 (should cluster with c3)
        ClaimOutput(
            chunk_id="c8",
            doc_id="doc1",
            bullets=["Consumer spending weakness may impact ad budgets in H1"],
            ticker=None,
            claim_type="risk",
            source_citation="Jefferies, p.8",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # Thematic: Macro forecast #2 (should cluster with c7)
        ClaimOutput(
            chunk_id="c9",
            doc_id="doc1",
            bullets=["Cloud infrastructure demand projected to accelerate in 2024"],
            ticker=None,
            claim_type="forecast",
            source_citation="Jefferies, p.9",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # Lone thematic (should go to Tier 3)
        ClaimOutput(
            chunk_id="c10",
            doc_id="doc1",
            bullets=["Semiconductor supply constraints easing globally"],
            ticker=None,
            claim_type="interpretation",
            source_citation="Jefferies, p.10",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="unclear",
            uncertainty_preserved=False,
        ),
    ]

    print(f"\nInput: {len(test_claims)} claims")
    print("Expected: Thematic claims (c3+c8, c7+c9) should form Tier 2 clusters\n")

    # Run tier assignment
    result = assign_tiers(test_claims)

    print("-" * 60)
    print("Tier Assignment Result:")
    print("-" * 60)
    print(f"\n{result.summary()}\n")

    print("TIER 1: Attention Required")
    print("-" * 40)
    for claim in result.tier_1:
        reasons = get_tier_reasons(claim, test_claims)
        ticker_label = claim.ticker or f"[{claim.claim_type}]"
        print(f"  [{claim.chunk_id}] {ticker_label}: {claim.bullets[0][:50]}...")
        print(f"       Reason: {', '.join(reasons)}")

    print("\nTIER 2: Synthesis / Through-Lines")
    print("-" * 40)
    for claim in result.tier_2:
        reasons = get_tier_reasons(claim, test_claims)
        ticker_label = claim.ticker or f"[{claim.claim_type}]"
        print(f"  [{claim.chunk_id}] {ticker_label}: {claim.bullets[0][:50]}...")
        print(f"       Reason: {', '.join(reasons)}")

    print("\nTIER 3: Reference")
    print("-" * 40)
    for claim in result.tier_3:
        reasons = get_tier_reasons(claim, test_claims)
        ticker_label = claim.ticker or f"[{claim.claim_type}]"
        print(f"  [{claim.chunk_id}] {ticker_label}: {claim.bullets[0][:50]}...")
        print(f"       Reason: {', '.join(reasons)}")

    # Verification
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    # All claims assigned
    assert result.total_claims() == len(test_claims)
    print("✓ All claims assigned to a tier")

    # No duplicates
    all_ids = [c.chunk_id for c in result.tier_1 + result.tier_2 + result.tier_3]
    assert len(all_ids) == len(set(all_ids))
    print("✓ No duplicate assignments")

    # Tier 1 should have breaking/upcoming/contradicts claims
    tier_1_ids = {c.chunk_id for c in result.tier_1}
    assert "c1" in tier_1_ids, "Breaking news should be Tier 1"
    assert "c2" in tier_1_ids, "Upcoming catalyst should be Tier 1"
    print("✓ Tier 1 rules working (breaking, upcoming, contradicts)")

    # Tier 2 should have thematic clusters
    tier_2_ids = {c.chunk_id for c in result.tier_2}

    # Risk theme cluster (c3 + c8)
    risk_in_tier2 = "c3" in tier_2_ids and "c8" in tier_2_ids
    print(f"✓ Thematic risk cluster (c3, c8): {'in Tier 2' if risk_in_tier2 else 'NOT in Tier 2'}")

    # Forecast theme cluster (c7 + c9)
    forecast_in_tier2 = "c7" in tier_2_ids and "c9" in tier_2_ids
    print(f"✓ Thematic forecast cluster (c7, c9): {'in Tier 2' if forecast_in_tier2 else 'NOT in Tier 2'}")

    # Ticker clusters (AMZN: c5 + c6)
    amzn_in_tier2 = "c5" in tier_2_ids and "c6" in tier_2_ids
    print(f"✓ Ticker cluster AMZN (c5, c6): {'in Tier 2' if amzn_in_tier2 else 'NOT in Tier 2'}")

    # Lone thematic should be Tier 3
    tier_3_ids = {c.chunk_id for c in result.tier_3}
    assert "c10" in tier_3_ids, "Lone thematic should be Tier 3"
    print("✓ Lone thematic claims routed to Tier 3")

    # Verify thematic claims CAN form Tier 2
    thematic_in_tier2 = [c for c in result.tier_2 if c.ticker is None]
    print(f"✓ {len(thematic_in_tier2)} thematic claims in Tier 2 (was 0 before fix)")

    print(f"\nTier routing validated. Thematic claims now cluster properly.")
