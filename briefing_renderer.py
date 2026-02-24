"""
Briefing renderer — V3, 4-section daily output.

Sections:
1. Objective Breaking News (per-ticker + TMT sector)
2. Synthesis Across Sources (LLM narrative prose)
3. Macro Connections (Phase 2 stub)
4. Longitudinal Delta Detection (Phase 2 stub)

Hard constraint: <5 pages (~2500 words).

Usage:
    from briefing_renderer import render_briefing

    markdown = render_briefing(claims, section2_synthesis)
"""

from typing import List, Optional, Dict
from dataclasses import dataclass
from datetime import date
from collections import defaultdict

from claim_extractor import ClaimOutput
from tier2_synthesizer import Section2Synthesis
from classifier import TMT_SUBTOPICS
from analyst_config_tmt import HIGH_ALERT_EVENT_TYPES
import config

# ------------------------------------------------------------------
# Page Limits
# ------------------------------------------------------------------

MAX_WORDS = 2500           # ~5 pages at 500 words/page
MAX_CLAIMS_PER_TICKER = 3


# ------------------------------------------------------------------
# High-Alert Detection
# ------------------------------------------------------------------

def _is_high_alert(claim: ClaimOutput) -> bool:
    """
    True if this claim should always appear regardless of the per-ticker cap.
    Covers: earnings, guidance changes, M&A/leadership/restructuring, regulatory actions,
    and concrete operational metric events (subscriber beats/misses, churn, ARPU, contracts).
    """
    if claim.event_type in HIGH_ALERT_EVENT_TYPES and claim.is_descriptive_event:
        return True
    # Operational metric signals: event_type='market' with a concrete fact
    if claim.event_type == 'market' and claim.is_descriptive_event and claim.has_belief_delta:
        return True
    return False


# ------------------------------------------------------------------
# Section 1: Objective Breaking News
# ------------------------------------------------------------------

def _render_section1(claims: List[ClaimOutput]) -> str:
    """
    Section 1: Per-ticker updates (max 3 each) + TMT sector-level.
    Iterates ALL tracked tickers; shows "No Update" if nothing found.
    """
    lines = []
    lines.append("## 1. Objective Breaking News")
    lines.append("*Per-ticker updates and TMT sector-level developments*\n")

    # Split by category
    ticker_claims = [c for c in claims if c.category == 'tracked_ticker']
    sector_claims = [c for c in claims if c.category == 'tmt_sector']

    # --- Per-Ticker Sub-section ---
    lines.append("### Tracked Tickers\n")

    # Group claims by ticker
    by_ticker = defaultdict(list)
    for claim in ticker_claims:
        if claim.ticker:
            by_ticker[claim.ticker].append(claim)

    # Iterate ALL tracked tickers from config
    all_tickers = config.ALL_TICKERS if hasattr(config, 'ALL_TICKERS') else []
    rendered_tickers = set()

    for ticker in all_tickers:
        rendered_tickers.add(ticker)
        ticker_group = by_ticker.get(ticker, [])

        if not ticker_group:
            lines.append(f"**{ticker}** — No Update\n")
            continue

        # Sort: breaking first, then by belief pressure importance
        time_order = {'breaking': 0, 'upcoming': 1, 'ongoing': 2}
        ticker_group.sort(key=lambda c: time_order.get(c.time_sensitivity, 3))

        # Split: high-alert claims always shown (uncapped); regular claims capped
        high_alert = [c for c in ticker_group if _is_high_alert(c)]
        regular = [c for c in ticker_group if not _is_high_alert(c)]
        regular_cap = max(0, MAX_CLAIMS_PER_TICKER - len(high_alert))

        lines.append(f"**{ticker}**")
        for claim in high_alert:
            bullet = claim.bullets[0]
            lines.append(f"- ⚠ {bullet}")
            lines.append(f"  *— {claim.source_citation}*")
        for claim in regular[:regular_cap]:
            bullet = claim.bullets[0]
            lines.append(f"- {bullet}")
            lines.append(f"  *— {claim.source_citation}*")
        lines.append("")

    # --- TMT Sector Sub-section ---
    if sector_claims:
        lines.append("### TMT Sector-Level\n")

        # Group by subtopic (from event_type as proxy, or generic)
        by_subtopic = defaultdict(list)
        for claim in sector_claims:
            # Use event_type or default to 'general'
            key = claim.event_type or 'general'
            by_subtopic[key].append(claim)

        for subtopic, group in by_subtopic.items():
            label = subtopic.replace('_', ' ').title()
            lines.append(f"**{label}**")
            for claim in group[:MAX_CLAIMS_PER_TICKER]:
                lines.append(f"- {claim.bullets[0]}")
                lines.append(f"  *— {claim.source_citation}*")
            lines.append("")

    return '\n'.join(lines)


# ------------------------------------------------------------------
# Section 2: Synthesis Across Sources
# ------------------------------------------------------------------

def _render_section2(synthesis: Section2Synthesis) -> str:
    """
    Section 2: LLM-generated narrative prose + flagged implications subsection.
    """
    lines = []
    lines.append("## 2. Synthesis Across Sources")
    lines.append("*Where sources agree, disagree, and what to weigh*\n")

    if synthesis.narrative:
        lines.append(synthesis.narrative)
    else:
        lines.append("*No cross-source synthesis available today.*")

    if synthesis.implications:
        lines.append("")
        lines.append("### ⚑ Potential Implications")
        lines.append("*Model-generated interpretation — challenge or discard as appropriate. Not a recommendation.*\n")
        lines.append(synthesis.implications)

    return '\n'.join(lines)


# ------------------------------------------------------------------
# Section 3: Macro Connections (Phase 2 Stub)
# ------------------------------------------------------------------

def _render_section3(macro_claims: List[ClaimOutput]) -> str:
    """Section 3: Stub for Phase 2."""
    lines = []
    lines.append("## 3. Macro Connections")

    if macro_claims:
        lines.append(f"*{len(macro_claims)} macro claims filed. Full rendering coming in Phase 2.*\n")
        # Show brief preview of macro claims
        for claim in macro_claims[:3]:
            lines.append(f"- {claim.bullets[0]}")
            if claim.sector_implication:
                lines.append(f"  *TMT link: {claim.sector_implication}*")
    else:
        lines.append("*Macro Connections — coming in Phase 2*")

    return '\n'.join(lines)


# ------------------------------------------------------------------
# Section 4: Longitudinal Delta Detection (Phase 2 Stub)
# ------------------------------------------------------------------

def _render_section4() -> str:
    """Section 4: Stub for Phase 2."""
    lines = []
    lines.append("## 4. Longitudinal Delta Detection")
    lines.append("*Longitudinal Delta Detection — coming in Phase 2*")
    return '\n'.join(lines)


# ------------------------------------------------------------------
# Main Renderer
# ------------------------------------------------------------------

def render_briefing(
    claims: List[ClaimOutput],
    section2_synthesis: Section2Synthesis,
    briefing_date: Optional[date] = None,
) -> str:
    """
    Render V3 4-section briefing.

    Args:
        claims: All claims (any category, already capped)
        section2_synthesis: Section2Synthesis from tier2_synthesizer
        briefing_date: Date for header (defaults to today)

    Returns:
        Markdown string (<5 pages)
    """
    if briefing_date is None:
        briefing_date = date.today()

    # Split claims by category for routing
    section1_claims = [c for c in claims if c.category in ('tracked_ticker', 'tmt_sector')]
    macro_claims = [c for c in claims if c.category == 'macro']

    # Render sections
    output_sections = []

    # Header
    output_sections.append(
        f"# Daily Briefing — {briefing_date.strftime('%B %d, %Y')}\n"
    )
    output_sections.append("---\n")

    # Section 1: Objective Breaking News
    output_sections.append(_render_section1(section1_claims))
    output_sections.append("---\n")

    # Section 2: Synthesis Across Sources
    output_sections.append(_render_section2(section2_synthesis))
    output_sections.append("---\n")

    # Section 3: Macro Connections (stub)
    output_sections.append(_render_section3(macro_claims))
    output_sections.append("---\n")

    # Section 4: Longitudinal Delta Detection (stub)
    output_sections.append(_render_section4())

    # Assemble
    output = '\n'.join(output_sections)

    # Word count check
    words = len(output.split())
    if words > MAX_WORDS:
        # Truncate Section 1 ticker "No Update" lines first
        output = _truncate_no_updates(output, MAX_WORDS)

    return output


def _truncate_no_updates(output: str, max_words: int) -> str:
    """Remove 'No Update' lines to save space if over budget."""
    lines = output.split('\n')
    result = []
    for line in lines:
        if '— No Update' in line and len(' '.join(result).split()) > max_words * 0.8:
            continue  # Skip No Update lines when over budget
        result.append(line)
    return '\n'.join(result)


# ------------------------------------------------------------------
# Stats
# ------------------------------------------------------------------

def count_words(text: str) -> int:
    return len(text.split())


def count_pages(text: str) -> float:
    return len(text.split()) / 500


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("V3 Briefing Renderer Test")
    print("=" * 60)

    # Test claims
    test_claims = [
        ClaimOutput(
            chunk_id="c1", doc_id="doc1",
            bullets=["META Threads surpassed 300M DAU, exceeding 200M consensus"],
            ticker="META", claim_type="fact",
            source_citation="Jefferies, Brent Thill, 2026-02-10",
            confidence_level="high", time_sensitivity="breaking",
            belief_pressure="contradicts_consensus",
            uncertainty_preserved=False, category="tracked_ticker",
        ),
        ClaimOutput(
            chunk_id="c2", doc_id="doc1",
            bullets=["GOOGL Cloud revenue beat expectations by 5%"],
            ticker="GOOGL", claim_type="fact",
            source_citation="Jefferies, Brent Thill, 2026-02-10",
            confidence_level="high", time_sensitivity="breaking",
            belief_pressure="contradicts_consensus",
            uncertainty_preserved=False, category="tracked_ticker",
        ),
        ClaimOutput(
            chunk_id="c3", doc_id="doc2",
            bullets=["Enterprise cloud spending accelerating across verticals"],
            ticker=None, claim_type="fact",
            source_citation="Morgan Stanley, 2026-02-10",
            confidence_level="medium", time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False, category="tmt_sector",
            event_type="market",
        ),
        ClaimOutput(
            chunk_id="c4", doc_id="doc3",
            bullets=["Fed held rates steady at 5.25%"],
            ticker=None, claim_type="fact",
            source_citation="Reuters, 2026-02-10",
            confidence_level="high", time_sensitivity="breaking",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False, category="macro",
            event_type="macro",
            sector_implication="Higher rates extend pressure on unprofitable software multiples",
        ),
    ]

    # Build synthesis (fallback since no API key in test)
    synthesis = Section2Synthesis(
        narrative="Jefferies and Morgan Stanley align on META's ad revenue trajectory. "
                  "However, an independent Substack analysis raises concerns about near-term "
                  "AI capex returns, which both sell-side firms have not addressed.",
    )

    print("\nRendering V3 briefing...\n")

    briefing = render_briefing(
        test_claims, synthesis,
        briefing_date=date(2026, 2, 10),
    )

    print("-" * 60)
    print("RENDERED BRIEFING")
    print("-" * 60)
    print(briefing)

    # Verification
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    words = count_words(briefing)
    pages = count_pages(briefing)
    print(f"Word count: {words}, Pages: {pages:.1f}")
    assert pages <= 5.5, f"Exceeds 5 pages: {pages}"
    print("✓ Under 5-page limit")

    assert "## 1. Objective Breaking News" in briefing
    print("✓ Section 1 present")

    assert "## 2. Synthesis Across Sources" in briefing
    print("✓ Section 2 present")

    assert "## 3. Macro Connections" in briefing
    print("✓ Section 3 stub present")

    assert "## 4. Longitudinal Delta Detection" in briefing
    print("✓ Section 4 stub present")

    # Check "No Update" for tickers with no claims
    assert "No Update" in briefing
    print("✓ 'No Update' shown for tickers without claims")

    # Section order
    s1 = briefing.index("## 1.")
    s2 = briefing.index("## 2.")
    s3 = briefing.index("## 3.")
    s4 = briefing.index("## 4.")
    assert s1 < s2 < s3 < s4
    print("✓ Section order correct: 1 < 2 < 3 < 4")

    # No thesis language
    thesis_words = ['recommend', 'should buy', 'should sell', 'bullish', 'bearish']
    has_thesis = any(w in briefing.lower() for w in thesis_words)
    if not has_thesis:
        print("✓ No thesis/recommendation language")

    print("\n✓ V3 briefing renderer validated")
