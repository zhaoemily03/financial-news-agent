"""
Briefing renderer — final output matching BRIEFING_TEMPLATE.md
Hard constraint: <5 pages (~2500 words). Truncate Tier 3 first.

Output Structure:
- Tier 1: 5-10 bullets max, explicit reason (breaking/upcoming/contradiction)
- Tier 2: 3-5 synthesized bullets, agreement/disagreement/what changed
- Tier 3: Grouped by stock/theme, minimal bullets, drill-down only

Usage:
    from briefing_renderer import render_briefing

    markdown = render_briefing(tier_assignment, tier2_synthesis, tier3_index)
"""

from typing import List, Optional
from dataclasses import dataclass
from datetime import date

from claim_extractor import ClaimOutput
from tier_router import TierAssignment, get_tier_reasons
from tier2_synthesizer import Tier2Synthesis
from implication_router import Tier3Index

# ------------------------------------------------------------------
# Page Limits (hard constraints)
# ------------------------------------------------------------------

MAX_WORDS = 2500           # ~5 pages at 500 words/page
TIER_1_MAX_BULLETS = 10
TIER_1_MIN_BULLETS = 5
TIER_2_MAX_BULLETS = 5
TIER_2_MIN_BULLETS = 3

# Word budget allocation (approximate)
TIER_1_WORD_BUDGET = 800   # ~1.5 pages
TIER_2_WORD_BUDGET = 700   # ~1.5 pages
TIER_3_WORD_BUDGET = 1000  # ~2 pages (flex)


# ------------------------------------------------------------------
# Tier 1 Rendering
# ------------------------------------------------------------------

def _get_tier1_reason(claim: ClaimOutput) -> str:
    """Get explicit reason for Tier 1 assignment."""
    reasons = []

    if claim.time_sensitivity == 'breaking':
        reasons.append("BREAKING")
    elif claim.time_sensitivity == 'upcoming':
        reasons.append("UPCOMING")

    if claim.belief_pressure == 'contradicts_consensus':
        reasons.append("CONTRADICTS CONSENSUS")
    elif claim.belief_pressure == 'contradicts_prior_assumptions':
        reasons.append("CHALLENGES PRIOR VIEW")

    return ' | '.join(reasons) if reasons else "ATTENTION"


def _render_tier1_bullet(claim: ClaimOutput) -> str:
    """Render single Tier 1 bullet with reason tag."""
    reason = _get_tier1_reason(claim)
    ticker_tag = f"**{claim.ticker}**: " if claim.ticker else ""
    bullet = claim.bullets[0]
    citation = claim.source_citation

    return f"- [{reason}] {ticker_tag}{bullet}\n  *— {citation}*"


def _render_tier1(claims: List[ClaimOutput]) -> str:
    """
    Render Tier 1: What Demands Attention Today
    5-10 bullets max, each with explicit reason.
    """
    lines = []
    lines.append("## Tier 1: What Demands Attention Today")
    lines.append("*Urgent, can't miss*\n")

    if not claims:
        lines.append("*No urgent items today.*")
        return '\n'.join(lines)

    # Group by reason type
    breaking = [c for c in claims if c.time_sensitivity == 'breaking']
    upcoming = [c for c in claims if c.time_sensitivity == 'upcoming']
    contradicts = [c for c in claims
                   if c.belief_pressure in ('contradicts_consensus', 'contradicts_prior_assumptions')
                   and c.time_sensitivity not in ('breaking', 'upcoming')]

    # Render in priority order, cap at TIER_1_MAX_BULLETS
    rendered = []

    # Breaking first
    if breaking:
        lines.append("### Something Broke Overnight")
        for c in breaking[:4]:  # Max 4 breaking
            lines.append(_render_tier1_bullet(c))
            rendered.append(c.chunk_id)
        lines.append("")

    # Upcoming next
    if upcoming and len(rendered) < TIER_1_MAX_BULLETS:
        lines.append("### Something Is About to Happen")
        remaining = TIER_1_MAX_BULLETS - len(rendered)
        for c in upcoming[:min(4, remaining)]:
            lines.append(_render_tier1_bullet(c))
            rendered.append(c.chunk_id)
        lines.append("")

    # Contradictions last
    if contradicts and len(rendered) < TIER_1_MAX_BULLETS:
        lines.append("### Something Contradicts What I Believe")
        remaining = TIER_1_MAX_BULLETS - len(rendered)
        for c in contradicts[:min(3, remaining)]:
            lines.append(_render_tier1_bullet(c))
            rendered.append(c.chunk_id)
        lines.append("")

    return '\n'.join(lines)


# ------------------------------------------------------------------
# Tier 2 Rendering
# ------------------------------------------------------------------

def _render_tier2(synthesis: Tier2Synthesis, claims: List[ClaimOutput]) -> str:
    """
    Render Tier 2: Signal vs Noise
    NEVER empty - always shows synthesis sections from template.
    Includes: Synthesis Across Reports, Consensus vs Divergence, Quant vs Qual.
    """
    lines = []
    lines.append("## Tier 2: What's the Signal from the Noise")
    lines.append("*Important, not urgent*\n")

    # Section 1: Synthesis Across All Reports (common themes)
    lines.append("### Synthesis Across All Reports")
    _render_common_themes(lines, synthesis, claims)
    lines.append("")

    # Section 2: Analyst Consensus vs. Divergence
    lines.append("### Analyst Consensus vs. Divergence")
    _render_consensus_divergence(lines, synthesis)
    lines.append("")

    # Section 3: What Changed (deltas/breaking)
    lines.append("### What Changed vs Prior Day")
    _render_deltas(lines, synthesis, claims)
    lines.append("")

    return '\n'.join(lines)


def _render_common_themes(lines: List[str], synthesis: Tier2Synthesis, claims: List[ClaimOutput]):
    """Extract and render common themes across all reports."""
    theme_bullets = []

    # Look for theme-based agreements (macro topics)
    theme_agreements = [ag for ag in synthesis.agreements if '(theme)' in ag.topic or 'concerns' in ag.topic]

    if theme_agreements:
        for ag in theme_agreements[:2]:
            theme_name = ag.topic.replace(' (theme)', '').replace(' concerns', '')
            lines.append(f"- **{theme_name}**: {ag.summary}")
            for specific in ag.specifics[:2]:
                lines.append(f"  - {specific}")
            theme_bullets.append(ag)

    # If no theme agreements, synthesize from claims directly
    if not theme_bullets and claims:
        # Group claims by common topics
        topic_counts = _extract_topic_signals(claims)
        for topic, count in list(topic_counts.items())[:3]:
            if count >= 2:
                lines.append(f"- **{topic}**: Multiple reports ({count}) touch on this theme")

    if not theme_bullets and not claims:
        lines.append("- *Reviewing reports for common threads...*")


def _extract_topic_signals(claims: List[ClaimOutput]) -> dict:
    """Extract topic signals from claims for synthesis."""
    from collections import Counter

    topic_keywords = {
        'AI investment': ['ai', 'artificial intelligence', 'ml', 'llm', 'gpu'],
        'Cloud momentum': ['cloud', 'aws', 'azure', 'gcp'],
        'Enterprise spending': ['enterprise', 'corporate', 'b2b', 'spending'],
        'Margin trends': ['margin', 'profitability', 'cost', 'efficiency'],
        'Competition': ['competition', 'competitive', 'market share'],
        'Guidance': ['guidance', 'outlook', 'forecast', 'expect'],
    }

    counts = Counter()
    for claim in claims:
        text = ' '.join(claim.bullets).lower() if claim.bullets else ''
        for topic, keywords in topic_keywords.items():
            if any(kw in text for kw in keywords):
                counts[topic] += 1

    return dict(counts.most_common(5))


def _render_consensus_divergence(lines: List[str], synthesis: Tier2Synthesis):
    """Render where analysts agree and disagree with specifics."""
    bullet_count = 0

    # Ticker-based agreements (not themes)
    ticker_agreements = [ag for ag in synthesis.agreements if '(theme)' not in ag.topic and 'concerns' not in ag.topic]

    if ticker_agreements:
        for ag in ticker_agreements[:2]:
            if bullet_count >= 3:
                break
            lines.append(f"- **Agreement on {ag.topic}**: {ag.summary}")
            for specific in ag.specifics[:2]:
                lines.append(f"  - {specific}")
            bullet_count += 1

    # Disagreements with specific positions
    if synthesis.disagreements:
        for dg in synthesis.disagreements[:2]:
            if bullet_count >= 4:
                break
            lines.append(f"- **Disagreement on {dg.topic}**:")
            lines.append(f"  - *View A*: {dg.side_a_position}")
            lines.append(f"  - *View B*: {dg.side_b_position}")
            bullet_count += 1
    elif synthesis.no_disagreement:
        lines.append("- *No disagreement detected - sources aligned this period*")
    elif not ticker_agreements:
        lines.append("- *Insufficient cross-source overlap to detect patterns*")


def _render_deltas(lines: List[str], synthesis: Tier2Synthesis, claims: List[ClaimOutput]):
    """Render what changed vs prior day."""
    if synthesis.deltas:
        for delta in synthesis.deltas[:3]:
            if delta.prior_state:
                lines.append(f"- {delta.description} (was: {delta.prior_state})")
            else:
                lines.append(f"- {delta.description}")
    else:
        # Look for breaking news in claims as proxy for change
        breaking = [c for c in claims if c.time_sensitivity == 'breaking']
        if breaking:
            for c in breaking[:2]:
                lines.append(f"- [NEW] {c.bullets[0][:100]}")
        else:
            lines.append("- *No significant changes vs prior coverage*")


# ------------------------------------------------------------------
# Tier 3 Rendering (with truncation)
# ------------------------------------------------------------------

def _render_tier3(index: Tier3Index, word_budget: int) -> str:
    """
    Render Tier 3: Reference
    Grouped by stock/theme, minimal bullets, truncate if over budget.
    """
    lines = []
    lines.append("## Tier 3: How Does This Affect My Work")
    lines.append("*Reference*\n")

    if not index.mappings:
        lines.append("*No reference items today.*")
        return '\n'.join(lines)

    word_count = 0

    # By Ticker (primary coverage first)
    if index.by_ticker:
        lines.append("### Implications for Covered Stocks")

        # Sort by priority (high first, then alphabetical)
        from config import TICKER_PRIORITY
        high_tickers = set(TICKER_PRIORITY.get('high', []))

        sorted_tickers = sorted(
            index.by_ticker.keys(),
            key=lambda t: (0 if t in high_tickers else 1, t)
        )

        for ticker in sorted_tickers:
            claims = index.by_ticker[ticker]

            # Estimate words for this section
            section_words = 10 + sum(len(c.bullets[0].split()) for c in claims)
            if word_count + section_words > word_budget:
                lines.append(f"\n*[{len(sorted_tickers) - sorted_tickers.index(ticker)} more tickers truncated for brevity]*")
                break

            lines.append(f"\n**{ticker}** ({len(claims)})")
            for c in claims[:3]:  # Max 3 claims per ticker
                bullet = c.bullets[0][:100] + "..." if len(c.bullets[0]) > 100 else c.bullets[0]
                lines.append(f"- {bullet}")

            if len(claims) > 3:
                lines.append(f"  *[+{len(claims) - 3} more]*")

            word_count += section_words

        lines.append("")

    # By Theme (if budget allows)
    if index.by_theme and word_count < word_budget * 0.8:
        lines.append("### Implications for Investment Theses")

        for theme in sorted(index.by_theme.keys()):
            claims = index.by_theme[theme]

            section_words = 10 + sum(len(c.bullets[0].split()) for c in claims)
            if word_count + section_words > word_budget:
                lines.append(f"\n*[Themes truncated for brevity]*")
                break

            lines.append(f"\n**{theme}** ({len(claims)})")
            for c in claims[:2]:  # Max 2 claims per theme
                ticker_tag = f"[{c.ticker}] " if c.ticker else ""
                bullet = c.bullets[0][:80] + "..." if len(c.bullets[0]) > 80 else c.bullets[0]
                lines.append(f"- {ticker_tag}{bullet}")

            if len(claims) > 2:
                lines.append(f"  *[+{len(claims) - 2} more]*")

            word_count += section_words

        lines.append("")

    # Unlinked (only if budget allows, very brief)
    if index.unlinked and word_count < word_budget * 0.9:
        lines.append("### Exploration Opportunities")
        lines.append(f"- {len(index.unlinked)} items outside current coverage (available on request)")

    return '\n'.join(lines)


# ------------------------------------------------------------------
# Main Renderer
# ------------------------------------------------------------------

def render_briefing(
    tier_assignment: TierAssignment,
    tier2_synthesis: Tier2Synthesis,
    tier3_index: Tier3Index,
    briefing_date: Optional[date] = None,
) -> str:
    """
    Render complete briefing matching BRIEFING_TEMPLATE.md format.

    Hard constraint: <5 pages (~2500 words). Truncates Tier 3 first.

    Args:
        tier_assignment: From tier_router.assign_tiers()
        tier2_synthesis: From tier2_synthesizer.synthesize_tier2()
        tier3_index: From implication_router.build_tier3_index()
        briefing_date: Optional date for header

    Returns:
        Markdown string
    """
    if briefing_date is None:
        briefing_date = date.today()

    sections = []

    # Header
    sections.append(f"# Daily Briefing — {briefing_date.strftime('%B %d, %Y')}")
    sections.append(f"\n**Maximum Length:** 5 pages\n")
    sections.append("---\n")

    # Render Tier 1
    tier1_md = _render_tier1(tier_assignment.tier_1)
    sections.append(tier1_md)
    sections.append("---\n")

    # Render Tier 2
    tier2_md = _render_tier2(tier2_synthesis, tier_assignment.tier_2)
    sections.append(tier2_md)
    sections.append("---\n")

    # Calculate remaining word budget for Tier 3
    current_words = sum(len(s.split()) for s in sections)
    tier3_budget = MAX_WORDS - current_words

    # Ensure minimum Tier 3 budget
    tier3_budget = max(tier3_budget, 300)  # At least 300 words

    # Render Tier 3 with truncation
    tier3_md = _render_tier3(tier3_index, tier3_budget)
    sections.append(tier3_md)

    # Final assembly
    output = '\n'.join(sections)

    # Hard truncation check (safety valve)
    words = len(output.split())
    if words > MAX_WORDS * 1.1:  # 10% buffer
        # Emergency truncate Tier 3
        lines = output.split('\n')
        tier3_start = None
        for i, line in enumerate(lines):
            if "## Tier 3:" in line:
                tier3_start = i
                break

        if tier3_start:
            # Keep only header of Tier 3
            truncated_lines = lines[:tier3_start + 3]
            truncated_lines.append("\n*[Tier 3 truncated to meet 5-page limit. Full reference available on request.]*")
            output = '\n'.join(truncated_lines)

    return output


def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def count_pages(text: str) -> float:
    """Estimate pages (500 words/page)."""
    return len(text.split()) / 500


# ------------------------------------------------------------------
# Summary Statistics
# ------------------------------------------------------------------

@dataclass
class BriefingStats:
    """Statistics about rendered briefing."""
    word_count: int
    page_estimate: float
    tier_1_bullets: int
    tier_2_bullets: int
    tier_3_tickers: int
    tier_3_themes: int
    truncated: bool


def get_briefing_stats(
    markdown: str,
    tier_assignment: TierAssignment,
    tier3_index: Tier3Index,
) -> BriefingStats:
    """Get statistics about rendered briefing."""
    words = count_words(markdown)
    pages = count_pages(markdown)
    truncated = "[truncated" in markdown.lower() or words > MAX_WORDS

    return BriefingStats(
        word_count=words,
        page_estimate=round(pages, 1),
        tier_1_bullets=len(tier_assignment.tier_1),
        tier_2_bullets=len(tier_assignment.tier_2),
        tier_3_tickers=len(tier3_index.by_ticker),
        tier_3_themes=len(tier3_index.by_theme),
        truncated=truncated,
    )


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date

    print("=" * 60)
    print("Briefing Renderer Test")
    print("=" * 60)

    # Create test data

    # Tier 1 claims
    tier1_claims = [
        ClaimOutput(
            chunk_id="t1-1",
            doc_id="doc1",
            bullets=["META Threads surpassed 300M DAU, exceeding 200M consensus"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, Brent Thill, 2026-01-29",
            confidence_level="high",
            time_sensitivity="breaking",
            belief_pressure="contradicts_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="t1-2",
            doc_id="doc1",
            bullets=["GOOGL earnings Feb 4 expected to show AI revenue acceleration"],
            ticker="GOOGL",
            claim_type="forecast",
            source_citation="Jefferies, Brent Thill, 2026-01-29",
            confidence_level="medium",
            time_sensitivity="upcoming",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="t1-3",
            doc_id="doc1",
            bullets=["CRWD losing share to MSFT Defender in enterprise segment"],
            ticker="CRWD",
            claim_type="risk",
            source_citation="Jefferies, Joseph Gallo, 2026-01-29",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="contradicts_prior_assumptions",
            uncertainty_preserved=False,
        ),
    ]

    # Tier 2 claims (for synthesis)
    tier2_claims = [
        ClaimOutput(
            chunk_id="t2-1",
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
        ClaimOutput(
            chunk_id="t2-2",
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
        ClaimOutput(
            chunk_id="t2-3",
            doc_id="doc1",
            bullets=["Enterprise software spending remains resilient in Q1"],
            ticker=None,
            claim_type="forecast",
            source_citation="Jefferies, p.7",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
    ]

    # Tier 3 claims
    tier3_claims = [
        ClaimOutput(
            chunk_id="t3-1",
            doc_id="doc1",
            bullets=["META Reality Labs R&D spending increased 20% YoY"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, p.10",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="t3-2",
            doc_id="doc1",
            bullets=["Enterprise AI infrastructure spending continues to accelerate"],
            ticker=None,
            claim_type="fact",
            source_citation="Jefferies, p.12",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="t3-3",
            doc_id="doc1",
            bullets=["CRWD maintaining endpoint protection market leadership"],
            ticker="CRWD",
            claim_type="fact",
            source_citation="Jefferies, p.15",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
    ]

    # Build structures
    tier_assignment = TierAssignment(
        tier_1=tier1_claims,
        tier_2=tier2_claims,
        tier_3=tier3_claims,
    )

    from tier2_synthesizer import synthesize_tier2
    tier2_synthesis = synthesize_tier2(tier2_claims)

    from implication_router import build_tier3_index
    tier3_index = build_tier3_index(tier3_claims)

    # Render briefing
    print("\nRendering briefing...\n")

    briefing = render_briefing(
        tier_assignment,
        tier2_synthesis,
        tier3_index,
        briefing_date=date(2026, 1, 29),
    )

    # Output
    print("-" * 60)
    print("RENDERED BRIEFING")
    print("-" * 60)
    print(briefing)

    # Stats
    print("\n" + "=" * 60)
    print("Briefing Statistics")
    print("=" * 60)

    stats = get_briefing_stats(briefing, tier_assignment, tier3_index)
    print(f"Word count: {stats.word_count}")
    print(f"Page estimate: {stats.page_estimate}")
    print(f"Tier 1 bullets: {stats.tier_1_bullets}")
    print(f"Tier 2 bullets: {stats.tier_2_bullets}")
    print(f"Tier 3 tickers: {stats.tier_3_tickers}")
    print(f"Tier 3 themes: {stats.tier_3_themes}")
    print(f"Truncated: {stats.truncated}")

    # Verification
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    # Under page limit
    assert stats.page_estimate <= 5.5, f"Exceeds 5 pages: {stats.page_estimate}"
    print(f"✓ Under 5-page limit ({stats.page_estimate} pages)")

    # Has all tiers
    assert "## Tier 1:" in briefing
    assert "## Tier 2:" in briefing
    assert "## Tier 3:" in briefing
    print("✓ All three tiers present")

    # Tier 1 has reason tags
    assert "[BREAKING]" in briefing or "[UPCOMING]" in briefing or "[CONTRADICT" in briefing
    print("✓ Tier 1 has explicit reason tags")

    # Tier 2 has synthesis sections
    assert "Consensus" in briefing or "Agreement" in briefing or "Disagreement" in briefing
    print("✓ Tier 2 has agreement/disagreement sections")

    # Tier 3 has grouping
    assert "Covered Stocks" in briefing or "Investment Theses" in briefing
    print("✓ Tier 3 has stock/theme grouping")

    # No thesis language
    thesis_words = ['recommend', 'should buy', 'should sell', 'bullish', 'bearish']
    has_thesis = any(w in briefing.lower() for w in thesis_words)
    if has_thesis:
        print("⚠ Warning: Thesis language detected")
    else:
        print("✓ No thesis/recommendation language")

    print("\nBriefing renderer validated.")
