"""
Tier 2 Synthesis — signal vs noise, structure not conclusions.
Helps humans see patterns without deciding for them.

Synthesis answers ONLY:
- Where are analysts agreeing?
- Where are they disagreeing?
- What changed vs prior day?

Constraints:
- Bullet points only
- Cite claim IDs
- No recommendations
- No thesis language
- If no disagreement exists, say so explicitly

Usage:
    from tier2_synthesizer import synthesize_tier2, Tier2Synthesis

    synthesis = synthesize_tier2(claims, prior_claims=None)
    print(synthesis.format_markdown())
"""

from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from claim_extractor import ClaimOutput

# ------------------------------------------------------------------
# Synthesis Result
# ------------------------------------------------------------------

@dataclass
class AgreementCluster:
    """Claims that agree on a point."""
    topic: str                    # What they agree on (ticker or theme)
    claim_ids: List[str]          # Participating claim IDs
    summary: str                  # One-line description (no judgment)
    specifics: List[str] = field(default_factory=list)  # Actual claim content for detail


@dataclass
class DisagreementCluster:
    """Claims that disagree on a point."""
    topic: str                    # What they disagree about
    side_a_ids: List[str]         # Claim IDs on one side
    side_b_ids: List[str]         # Claim IDs on other side
    side_a_position: str          # Brief position A (with specifics)
    side_b_position: str          # Brief position B (with specifics)
    side_a_specifics: List[str] = field(default_factory=list)  # Actual claim content
    side_b_specifics: List[str] = field(default_factory=list)  # Actual claim content


@dataclass
class DeltaItem:
    """Something that changed vs prior day."""
    claim_id: str
    description: str              # What changed
    prior_state: Optional[str]    # What it was before (if known)


@dataclass
class Tier2Synthesis:
    """Structured synthesis of Tier 2 signals."""
    agreements: List[AgreementCluster] = field(default_factory=list)
    disagreements: List[DisagreementCluster] = field(default_factory=list)
    deltas: List[DeltaItem] = field(default_factory=list)
    no_disagreement: bool = False  # True if explicitly no disagreement found

    def format_markdown(self) -> str:
        """Format synthesis as markdown bullets with specific claim content."""
        lines = []

        # Agreements - show WHAT they agree on
        lines.append("### Where Analysts Agree")
        if self.agreements:
            for ag in self.agreements:
                lines.append(f"- **{ag.topic}**: {ag.summary}")
                # Show specifics so analyst knows exactly what's agreed
                for specific in ag.specifics[:2]:
                    lines.append(f"  - {specific}")
        else:
            lines.append("- *No clear agreement clusters detected.*")
        lines.append("")

        # Disagreements - show WHAT they disagree on
        lines.append("### Where Analysts Disagree")
        if self.disagreements:
            for dg in self.disagreements:
                lines.append(f"- **{dg.topic}**:")
                lines.append(f"  - {dg.side_a_position}")
                lines.append(f"  - {dg.side_b_position}")
        elif self.no_disagreement:
            lines.append("- *No disagreement detected across sources.*")
        else:
            lines.append("- *Insufficient overlap to detect disagreement.*")
        lines.append("")

        # Deltas
        lines.append("### What Changed vs Prior Day")
        if self.deltas:
            for delta in self.deltas:
                if delta.prior_state:
                    lines.append(f"- {delta.description} (was: {delta.prior_state})")
                else:
                    lines.append(f"- {delta.description}")
        else:
            lines.append("- *No prior day data available for comparison.*")

        return '\n'.join(lines)

    def has_content(self) -> bool:
        """Check if synthesis has meaningful content."""
        return bool(self.agreements or self.disagreements or self.deltas)


# ------------------------------------------------------------------
# Agreement Detection
# ------------------------------------------------------------------

def _detect_agreements(claims: List[ClaimOutput]) -> List[AgreementCluster]:
    """
    Find claims that agree (same ticker/theme + same polarity direction).
    Agreement = multiple claims pointing same direction on same topic.
    Now includes theme-based and macro topics, not just tickers.
    """
    agreements = []

    # Group by ticker
    by_ticker = defaultdict(list)
    for claim in claims:
        if claim.ticker:
            by_ticker[claim.ticker].append(claim)

    for ticker, ticker_claims in by_ticker.items():
        if len(ticker_claims) < 2:
            continue

        confirms = [c for c in ticker_claims if c.belief_pressure == 'confirms_consensus']
        contradicts = [c for c in ticker_claims
                       if c.belief_pressure in ('contradicts_consensus', 'contradicts_prior_assumptions')]

        if len(confirms) >= 2:
            # Extract specifics from actual claim content
            specifics = [c.bullets[0][:100] for c in confirms[:3]]
            agreements.append(AgreementCluster(
                topic=ticker,
                claim_ids=[c.chunk_id for c in confirms],
                summary=_extract_agreement_summary(confirms, ticker),
                specifics=specifics,
            ))

        if len(contradicts) >= 2:
            specifics = [c.bullets[0][:100] for c in contradicts[:3]]
            agreements.append(AgreementCluster(
                topic=f"{ticker} (contrarian)",
                claim_ids=[c.chunk_id for c in contradicts],
                summary=_extract_agreement_summary(contradicts, ticker, contrarian=True),
                specifics=specifics,
            ))

    # Group by theme/topic keywords (macro, sector, etc.)
    theme_agreements = _detect_theme_agreements(claims)
    agreements.extend(theme_agreements)

    return agreements


def _extract_agreement_summary(claims: List[ClaimOutput], topic: str, contrarian: bool = False) -> str:
    """Extract a specific summary of what claims agree on, using actual content."""
    if not claims:
        return f"Multiple sources {'challenge' if contrarian else 'confirm'} view on {topic}"

    # Find common keywords/phrases in the claims
    all_text = ' '.join(c.bullets[0].lower() for c in claims)

    # Look for specific metrics or concepts
    keywords = []
    if 'revenue' in all_text or 'growth' in all_text:
        keywords.append('revenue trajectory')
    if 'margin' in all_text:
        keywords.append('margin trends')
    if 'ai' in all_text or 'artificial intelligence' in all_text:
        keywords.append('AI impact')
    if 'cloud' in all_text:
        keywords.append('cloud performance')
    if 'competition' in all_text or 'competitive' in all_text:
        keywords.append('competitive position')

    if keywords:
        focus = ', '.join(keywords[:2])
        if contrarian:
            return f"Multiple sources raise concerns about {topic} {focus}"
        return f"Multiple sources aligned on {topic} {focus}"

    # Default to first claim's content as summary
    first_bullet = claims[0].bullets[0][:80]
    if contrarian:
        return f"Sources challenge consensus: {first_bullet}"
    return f"Sources agree: {first_bullet}"


def _detect_theme_agreements(claims: List[ClaimOutput]) -> List[AgreementCluster]:
    """Detect agreement on themes/macro topics (not tied to specific tickers)."""
    theme_agreements = []

    # Theme keywords to look for
    MACRO_THEMES = {
        'AI/ML': ['ai', 'artificial intelligence', 'machine learning', 'llm', 'gpu', 'inference'],
        'Cloud': ['cloud', 'aws', 'azure', 'gcp', 'iaas', 'paas', 'saas'],
        'Macro': ['gdp', 'inflation', 'interest rate', 'fed', 'economy', 'recession'],
        'Enterprise': ['enterprise', 'b2b', 'corporate', 'digital transformation'],
        'Cybersecurity': ['security', 'cyber', 'threat', 'breach', 'zero trust'],
        'Consumer': ['consumer', 'spending', 'retail', 'demand'],
    }

    # Group claims by detected theme
    by_theme = defaultdict(list)
    for claim in claims:
        text = claim.bullets[0].lower() if claim.bullets else ''
        for theme, keywords in MACRO_THEMES.items():
            if any(kw in text for kw in keywords):
                by_theme[theme].append(claim)

    for theme, theme_claims in by_theme.items():
        if len(theme_claims) < 2:
            continue

        # Check for alignment
        confirms = [c for c in theme_claims if c.belief_pressure == 'confirms_consensus']
        contradicts = [c for c in theme_claims
                       if c.belief_pressure in ('contradicts_consensus', 'contradicts_prior_assumptions')]

        if len(confirms) >= 2:
            specifics = [c.bullets[0][:100] for c in confirms[:3]]
            theme_agreements.append(AgreementCluster(
                topic=f"{theme} (theme)",
                claim_ids=[c.chunk_id for c in confirms],
                summary=f"Multiple reports aligned on {theme} outlook",
                specifics=specifics,
            ))

        if len(contradicts) >= 2:
            specifics = [c.bullets[0][:100] for c in contradicts[:3]]
            theme_agreements.append(AgreementCluster(
                topic=f"{theme} concerns",
                claim_ids=[c.chunk_id for c in contradicts],
                summary=f"Multiple reports flag {theme} risks",
                specifics=specifics,
            ))

    return theme_agreements


# ------------------------------------------------------------------
# Disagreement Detection
# ------------------------------------------------------------------

def _detect_disagreements(claims: List[ClaimOutput]) -> Tuple[List[DisagreementCluster], bool]:
    """
    Find claims that disagree (same ticker/theme + opposite positions).
    Returns (disagreements, no_disagreement_flag).
    Now includes specific claim content for clarity.
    """
    disagreements = []
    found_any_potential = False

    # Group by ticker
    by_ticker = defaultdict(list)
    for claim in claims:
        if claim.ticker:
            by_ticker[claim.ticker].append(claim)

    for ticker, ticker_claims in by_ticker.items():
        if len(ticker_claims) < 2:
            continue

        found_any_potential = True

        confirms = [c for c in ticker_claims if c.belief_pressure == 'confirms_consensus']
        contradicts = [c for c in ticker_claims
                       if c.belief_pressure in ('contradicts_consensus', 'contradicts_prior_assumptions')]

        # Disagreement = some confirm, some contradict
        if confirms and contradicts:
            # Extract specific positions from actual claims
            side_a_specific = confirms[0].bullets[0][:100] if confirms else ""
            side_b_specific = contradicts[0].bullets[0][:100] if contradicts else ""

            disagreements.append(DisagreementCluster(
                topic=ticker,
                side_a_ids=[c.chunk_id for c in confirms],
                side_b_ids=[c.chunk_id for c in contradicts],
                side_a_position=f"Bullish: {side_a_specific}",
                side_b_position=f"Cautious: {side_b_specific}",
                side_a_specifics=[c.bullets[0][:80] for c in confirms[:2]],
                side_b_specifics=[c.bullets[0][:80] for c in contradicts[:2]],
            ))

        # Also check for content_type disagreement (forecast vs risk)
        forecasts = [c for c in ticker_claims if c.claim_type == 'forecast']
        risks = [c for c in ticker_claims if c.claim_type == 'risk']

        if forecasts and risks:
            existing_topics = {d.topic for d in disagreements}
            if f"{ticker} outlook" not in existing_topics:
                forecast_text = forecasts[0].bullets[0][:80] if forecasts else ""
                risk_text = risks[0].bullets[0][:80] if risks else ""

                disagreements.append(DisagreementCluster(
                    topic=f"{ticker} outlook",
                    side_a_ids=[c.chunk_id for c in forecasts],
                    side_b_ids=[c.chunk_id for c in risks],
                    side_a_position=f"Positive outlook: {forecast_text}",
                    side_b_position=f"Risk factors: {risk_text}",
                    side_a_specifics=[c.bullets[0][:80] for c in forecasts[:2]],
                    side_b_specifics=[c.bullets[0][:80] for c in risks[:2]],
                ))

    # Theme-based disagreements
    theme_disagreements = _detect_theme_disagreements(claims)
    disagreements.extend(theme_disagreements)
    if theme_disagreements:
        found_any_potential = True

    no_disagreement = found_any_potential and len(disagreements) == 0

    return disagreements, no_disagreement


def _detect_theme_disagreements(claims: List[ClaimOutput]) -> List[DisagreementCluster]:
    """Detect disagreements on themes/macro topics."""
    theme_disagreements = []

    MACRO_THEMES = {
        'AI/ML': ['ai', 'artificial intelligence', 'machine learning', 'llm', 'gpu'],
        'Cloud': ['cloud', 'aws', 'azure', 'gcp', 'iaas', 'saas'],
        'Macro': ['gdp', 'inflation', 'interest rate', 'fed', 'economy'],
        'Enterprise': ['enterprise', 'b2b', 'corporate', 'digital transformation'],
    }

    by_theme = defaultdict(list)
    for claim in claims:
        text = claim.bullets[0].lower() if claim.bullets else ''
        for theme, keywords in MACRO_THEMES.items():
            if any(kw in text for kw in keywords):
                by_theme[theme].append(claim)

    for theme, theme_claims in by_theme.items():
        if len(theme_claims) < 2:
            continue

        confirms = [c for c in theme_claims if c.belief_pressure == 'confirms_consensus']
        contradicts = [c for c in theme_claims
                       if c.belief_pressure in ('contradicts_consensus', 'contradicts_prior_assumptions')]

        if confirms and contradicts:
            side_a = confirms[0].bullets[0][:80] if confirms else ""
            side_b = contradicts[0].bullets[0][:80] if contradicts else ""

            theme_disagreements.append(DisagreementCluster(
                topic=f"{theme} (theme)",
                side_a_ids=[c.chunk_id for c in confirms],
                side_b_ids=[c.chunk_id for c in contradicts],
                side_a_position=f"Positive: {side_a}",
                side_b_position=f"Concerns: {side_b}",
                side_a_specifics=[c.bullets[0][:80] for c in confirms[:2]],
                side_b_specifics=[c.bullets[0][:80] for c in contradicts[:2]],
            ))

    return theme_disagreements


# ------------------------------------------------------------------
# Delta Detection (vs prior day)
# ------------------------------------------------------------------

def _detect_deltas(
    claims: List[ClaimOutput],
    prior_claims: Optional[List[ClaimOutput]] = None,
) -> List[DeltaItem]:
    """
    Find what changed vs prior day.
    If no prior_claims provided, detect "breaking" as proxy for change.
    """
    deltas = []

    if prior_claims:
        # Compare current vs prior by ticker
        prior_by_ticker = defaultdict(list)
        for c in prior_claims:
            if c.ticker:
                prior_by_ticker[c.ticker].append(c)

        current_by_ticker = defaultdict(list)
        for c in claims:
            if c.ticker:
                current_by_ticker[c.ticker].append(c)

        # Find tickers with changed stance
        for ticker in current_by_ticker:
            current = current_by_ticker[ticker]
            prior = prior_by_ticker.get(ticker, [])

            if not prior:
                # New ticker coverage
                for c in current:
                    deltas.append(DeltaItem(
                        claim_id=c.chunk_id,
                        description=f"New coverage on {ticker}",
                        prior_state=None,
                    ))
            else:
                # Check for belief_pressure changes
                prior_pressures = {c.belief_pressure for c in prior}
                for c in current:
                    if c.belief_pressure not in prior_pressures:
                        deltas.append(DeltaItem(
                            claim_id=c.chunk_id,
                            description=f"Stance change on {ticker}: now {c.belief_pressure}",
                            prior_state=f"was {', '.join(prior_pressures)}",
                        ))

    else:
        # No prior data: use time_sensitivity=breaking as proxy for "new"
        for claim in claims:
            if claim.time_sensitivity == 'breaking':
                deltas.append(DeltaItem(
                    claim_id=claim.chunk_id,
                    description=f"Breaking: {claim.bullets[0][:60]}...",
                    prior_state=None,
                ))

    return deltas


# ------------------------------------------------------------------
# Main Synthesis Function
# ------------------------------------------------------------------

def synthesize_tier2(
    claims: List[ClaimOutput],
    prior_claims: Optional[List[ClaimOutput]] = None,
) -> Tier2Synthesis:
    """
    Synthesize Tier 2 signals into structured bullets.

    Answers ONLY:
    - Where are analysts agreeing?
    - Where are they disagreeing?
    - What changed vs prior day?

    Args:
        claims: Current day's claims (typically Tier 2 from tier_router)
        prior_claims: Optional prior day's claims for delta detection

    Returns:
        Tier2Synthesis with agreements, disagreements, and deltas
    """
    if not claims:
        return Tier2Synthesis(no_disagreement=True)

    # Detect patterns
    agreements = _detect_agreements(claims)
    disagreements, no_disagreement = _detect_disagreements(claims)
    deltas = _detect_deltas(claims, prior_claims)

    return Tier2Synthesis(
        agreements=agreements,
        disagreements=disagreements,
        deltas=deltas,
        no_disagreement=no_disagreement,
    )


# ------------------------------------------------------------------
# Convenience: Synthesize all tiers (not just Tier 2)
# ------------------------------------------------------------------

def synthesize_all_claims(
    claims: List[ClaimOutput],
    prior_claims: Optional[List[ClaimOutput]] = None,
) -> Tier2Synthesis:
    """
    Run synthesis on all claims (can be used for full briefing analysis).
    Same logic as synthesize_tier2 but named for clarity.
    """
    return synthesize_tier2(claims, prior_claims)


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Tier 2 Synthesis Test")
    print("=" * 60)

    # Test claims with intentional agreement/disagreement patterns
    test_claims = [
        # META: Agreement cluster (2 confirming)
        ClaimOutput(
            chunk_id="c1",
            doc_id="doc1",
            bullets=["META ad revenue growth remains strong at 28% YoY"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, p.1",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="c2",
            doc_id="doc1",
            bullets=["META Reels monetization on track per management guidance"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, p.2",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # META: Disagreement (contrarian vs confirms)
        ClaimOutput(
            chunk_id="c3",
            doc_id="doc1",
            bullets=["META AI capex returns may disappoint near-term"],
            ticker="META",
            claim_type="risk",
            source_citation="Jefferies, p.3",
            confidence_level="medium",
            time_sensitivity="upcoming",
            belief_pressure="contradicts_consensus",
            uncertainty_preserved=True,
        ),
        # GOOGL: Breaking news (delta)
        ClaimOutput(
            chunk_id="c4",
            doc_id="doc1",
            bullets=["GOOGL Cloud revenue beat expectations by 5%"],
            ticker="GOOGL",
            claim_type="fact",
            source_citation="Jefferies, p.4",
            confidence_level="high",
            time_sensitivity="breaking",
            belief_pressure="contradicts_consensus",
            uncertainty_preserved=False,
        ),
        # CRWD: Forecast vs Risk disagreement
        ClaimOutput(
            chunk_id="c5",
            doc_id="doc1",
            bullets=["CRWD expected to beat Q4 estimates on strong pipeline"],
            ticker="CRWD",
            claim_type="forecast",
            source_citation="Jefferies, p.5",
            confidence_level="medium",
            time_sensitivity="upcoming",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="c6",
            doc_id="doc1",
            bullets=["CRWD faces competitive pressure from MSFT Defender"],
            ticker="CRWD",
            claim_type="risk",
            source_citation="Jefferies, p.6",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="contradicts_prior_assumptions",
            uncertainty_preserved=False,
        ),
    ]

    print(f"\nInput: {len(test_claims)} claims")
    print("Expected: META agreement + disagreement, GOOGL delta, CRWD outlook disagreement\n")

    # Run synthesis
    synthesis = synthesize_tier2(test_claims)

    print("-" * 60)
    print("Synthesis Output:")
    print("-" * 60)
    print(synthesis.format_markdown())

    # Verification
    print("=" * 60)
    print("Verification")
    print("=" * 60)

    # Should have agreements
    assert len(synthesis.agreements) >= 1, "Should detect META agreement"
    meta_agreement = [a for a in synthesis.agreements if 'META' in a.topic]
    assert len(meta_agreement) >= 1, "META claims should show agreement"
    print("✓ Agreement detection working")

    # Should have disagreements
    assert len(synthesis.disagreements) >= 1, "Should detect disagreements"
    print(f"✓ Found {len(synthesis.disagreements)} disagreement clusters")

    # Should have deltas (breaking news)
    assert len(synthesis.deltas) >= 1, "Should detect breaking news as delta"
    googl_delta = [d for d in synthesis.deltas if 'GOOGL' in d.description]
    assert len(googl_delta) >= 1, "GOOGL breaking news should be a delta"
    print("✓ Delta detection working")

    # All claim IDs should be cited
    all_cited_ids = set()
    for ag in synthesis.agreements:
        all_cited_ids.update(ag.claim_ids)
    for dg in synthesis.disagreements:
        all_cited_ids.update(dg.side_a_ids)
        all_cited_ids.update(dg.side_b_ids)
    for delta in synthesis.deltas:
        all_cited_ids.add(delta.claim_id)

    print(f"✓ Claims cited: {sorted(all_cited_ids)}")

    # No thesis language check (manual)
    md = synthesis.format_markdown()
    thesis_words = ['recommend', 'should', 'must', 'bullish', 'bearish', 'buy', 'sell']
    has_thesis = any(w in md.lower() for w in thesis_words)
    if has_thesis:
        print("⚠ Warning: Thesis language detected in output")
    else:
        print("✓ No thesis/recommendation language")

    print("\nSynthesis validated. Structure without conclusions.")
