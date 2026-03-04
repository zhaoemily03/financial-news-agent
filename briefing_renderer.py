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
from section3_synthesizer import Section3Synthesis
from drift_detector import DriftReport
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
# Bullet Quality Filter
# ------------------------------------------------------------------

import re as _re

_STUB_BULLET_RE = _re.compile(
    r'^[\w\s.,&\'-]+\([A-Z0-9.]+\)\.\.\.$'   # "Company Name (TICK)..." — company header, no content
)

_STOP_WORDS = {
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'up', 'is', 'was', 'are', 'be', 'as', 'its',
    'that', 'this', 'it', 'has', 'had', 'have', 'not', 'also', 'than',
}

def _content_words(text: str) -> set:
    """Lowercase, punctuation-stripped token set minus stop words — for Jaccard dedup."""
    tokens = (w.strip('.,;:()[]"\'/').lower() for w in text.split())
    return {t for t in tokens if t and t not in _STOP_WORDS}

def _dedup_claims(claims: List[ClaimOutput], threshold: float = 0.50) -> List[ClaimOutput]:
    """
    Drop near-duplicate bullets within a ticker group using Jaccard word overlap.
    Same approach as macro_news.py cross-feed dedup (≥50% overlap = duplicate).
    Claims are assumed pre-sorted by priority so first occurrence wins.
    """
    kept: List[ClaimOutput] = []
    kept_words: List[set] = []
    for claim in claims:
        words = _content_words(claim.bullets[0])
        is_dup = any(
            len(words & seen) / len(words | seen) >= threshold
            for seen in kept_words
            if words | seen
        )
        if not is_dup:
            kept.append(claim)
            kept_words.append(words)
    return kept


def _is_junk_bullet(text: str) -> bool:
    """True if a bullet is a PDF artifact with no informational value."""
    stripped = text.strip()
    # Stub: company name + ticker + ellipsis, nothing else
    if _STUB_BULLET_RE.match(stripped):
        return True
    # Literal TICKER placeholder from PDF comparison tables (e.g. "referred to TICKER APP in Q4")
    if _re.search(r'\bTICKER\b', stripped):
        return True
    # Extremely short and uninformative (< 20 chars)
    if len(stripped) < 20:
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

        # Dedup near-identical bullets (e.g. same data point covered by two Goldman reports)
        ticker_group = _dedup_claims(ticker_group)

        # Split: high-alert claims always shown (uncapped); regular claims capped
        high_alert = [c for c in ticker_group if _is_high_alert(c)]
        regular = [c for c in ticker_group if not _is_high_alert(c)]
        regular_cap = max(0, MAX_CLAIMS_PER_TICKER - len(high_alert))

        rendered = []
        for claim in high_alert:
            bullet = claim.bullets[0]
            if not _is_junk_bullet(bullet):
                rendered.append(f"- ⚠ {bullet}\n  *— {claim.source_citation}*")
        for claim in regular[:regular_cap]:
            bullet = claim.bullets[0]
            if not _is_junk_bullet(bullet):
                rendered.append(f"- {bullet}\n  *— {claim.source_citation}*")

        if rendered:
            lines.append(f"**{ticker}**")
            lines.extend(rendered)
            lines.append("")
        else:
            lines.append(f"**{ticker}** — No Update\n")

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
# Section 3: Macro Connections
# ------------------------------------------------------------------

def _render_section3(
    macro_claims: List[ClaimOutput],
    synthesis: Optional[Section3Synthesis] = None,
) -> str:
    """
    Section 3: Deduplicated macro signals + LLM TMT linkage narrative.
    Claims are listed first; narrative adds portfolio-level connections.
    """
    lines = []
    lines.append("## 3. Macro Connections")
    lines.append("*Global macro signals and TMT portfolio linkages*\n")

    if not macro_claims:
        lines.append("*No macro signals collected today.*")
        return '\n'.join(lines)

    # List each macro claim with its existing sector_implication annotation
    # (sorting and capping already applied upstream in run_pipeline.py)
    for claim in macro_claims:
        lines.append(f"- **{claim.bullets[0]}**")
        if claim.sector_implication:
            lines.append(f"  *TMT: {claim.sector_implication}*")
        lines.append(f"  *— {claim.source_citation}*")
    lines.append("")

    # LLM narrative: portfolio-level linkages (flagged model-generated)
    if synthesis and synthesis.has_content():
        lines.append("### Portfolio Linkages")
        lines.append(
            "*Model-generated — challenge or discard as appropriate. Not a recommendation.*\n"
        )
        lines.append(synthesis.narrative)

    return '\n'.join(lines)


# ------------------------------------------------------------------
# Section 4: Longitudinal Delta Detection
# ------------------------------------------------------------------

_WINDOW_LABELS = {7: "past week", 30: "past month", 90: "past quarter"}
_BELIEF_DIR = {
    'confirms_consensus': 'consensus-aligned',
    'contradicts_consensus': 'contrarian',
    'contradicts_prior_assumptions': 'challenging prior assumptions',
}
_CONF_ORDER = {'low': 0, 'medium': 1, 'high': 2}


def _drift_narrative(signal) -> str:
    """Convert a DriftSignal to a readable natural-language sentence."""
    ticker = signal.ticker or "TMT sector"
    window = _WINDOW_LABELS.get(signal.window_days, f"past {signal.window_days}d")

    def clip(text, n=90):
        if not text:
            return ""
        text = text.strip()
        return text[:n].rstrip('.,; ') + ("…" if len(text) > n else "")

    if signal.drift_type == 'confidence_shift':
        today_n = _CONF_ORDER.get(signal.today_confidence or '', 1)
        prior_n = _CONF_ORDER.get(signal.prior_confidence or '', 1)
        direction = "softened" if today_n < prior_n else "hardened"
        sentence = f"**{ticker}**: Over the {window}, conviction has {direction}"
        if signal.prior_claim:
            sentence += f" — previously: \"{clip(signal.prior_claim)}\""
        if signal.today_claim:
            sentence += f"; now: \"{clip(signal.today_claim)}\""
        if signal.cross_window_context:
            sentence += f" ({signal.cross_window_context})"
        return sentence

    if signal.drift_type == 'belief_flip':
        prior_dir = _BELIEF_DIR.get(signal.prior_belief_pressure or '', 'unclear stance')
        today_dir = _BELIEF_DIR.get(signal.today_belief_pressure or '', 'unclear stance')
        sentence = f"**{ticker}**: Over the {window}, direction reversed — sources shifted from {prior_dir} to {today_dir}"
        if signal.prior_claim:
            sentence += f" (previously: \"{clip(signal.prior_claim, 75)}\""
        if signal.today_claim:
            sentence += f"; now: \"{clip(signal.today_claim, 75)}\")"
        return sentence

    if signal.drift_type == 'new_disagreement':
        return f"**{ticker}**: Sources now split — {signal.today_claim}"

    # Fallback for any future signal types
    return f"**{ticker}**: {signal.description}"


def _render_section4(drift_report: Optional[DriftReport] = None) -> str:
    """
    Section 4: Sentiment drift signals written as natural-language bullets.
    No LLM — deterministic metadata comparison from drift_detector.py.
    Tracks conviction softening/hardening, belief flips, and new source disagreement.
    Does NOT report publication frequency (not a reliable sentiment signal).
    """
    lines = []
    lines.append("## 4. Longitudinal Delta Detection")
    lines.append("*Sentiment drift vs prior periods — deterministic, no AI*\n")

    if drift_report is None:
        lines.append("*No historical data yet — baseline builds after the first run.*")
        return '\n'.join(lines)

    if not drift_report.has_signals():
        lines.append("*No sentiment drift detected vs prior periods.*")
        return '\n'.join(lines)

    for signal in drift_report.signals:
        lines.append(f"- {_drift_narrative(signal)}")

    return '\n'.join(lines)


# ------------------------------------------------------------------
# Main Renderer
# ------------------------------------------------------------------

def render_briefing(
    claims: List[ClaimOutput],
    section2_synthesis: Section2Synthesis,
    briefing_date: Optional[date] = None,
    section3_synthesis: Optional[Section3Synthesis] = None,
    drift_report: Optional[DriftReport] = None,
    macro_claims: Optional[List[ClaimOutput]] = None,
) -> str:
    """
    Render V3 4-section briefing.

    Args:
        claims: All claims (any category)
        section2_synthesis: Section2Synthesis from tier2_synthesizer
        briefing_date: Date for header (defaults to today)
        section3_synthesis: Section3Synthesis from section3_synthesizer (optional)
        drift_report: DriftReport from drift_detector (optional)
        macro_claims: Pre-sorted, pre-capped macro claim list for Section 3.
            If provided, used directly. If None, extracted from claims (fallback).

    Returns:
        Markdown string (<5 pages)
    """
    if briefing_date is None:
        briefing_date = date.today()

    # Split claims by category for routing
    section1_claims = [c for c in claims if c.category in ('tracked_ticker', 'tmt_sector')]
    # Use pre-capped macro_claims if provided (pipeline ensures synthesis + display are coherent)
    if macro_claims is None:
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

    # Section 3: Macro Connections
    output_sections.append(_render_section3(macro_claims, section3_synthesis))
    output_sections.append("---\n")

    # Section 4: Longitudinal Delta Detection
    output_sections.append(_render_section4(drift_report))

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
