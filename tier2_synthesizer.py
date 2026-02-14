"""
Section 2 Synthesis — Synthesis Across Sources.
Helps humans see where analysts agree and disagree, considering source credibility.

Synthesis answers ONLY:
- Where are sources agreeing?
- Where are they disagreeing?
- What source biases/credibility should the reader weigh?

Output: LLM-generated narrative prose (2-3 paragraphs, no bullets).

Constraints:
- No recommendations
- No thesis language (bullish, bearish, should, recommend)
- Cite sources by name
- If no disagreement exists, say so explicitly

Usage:
    from tier2_synthesizer import synthesize_section2, Section2Synthesis

    synthesis = synthesize_section2(claims)
    print(synthesis.narrative)
"""

import json
import os
from typing import List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

from claim_extractor import ClaimOutput
from analyst_config_tmt import SOURCE_CREDIBILITY

# ------------------------------------------------------------------
# Result Dataclasses
# ------------------------------------------------------------------

@dataclass
class AgreementCluster:
    """Claims that agree on a point."""
    topic: str                    # What they agree on (ticker or theme)
    claim_ids: List[str]          # Participating claim IDs
    summary: str                  # One-line description (no judgment)
    specifics: List[str] = field(default_factory=list)


@dataclass
class DisagreementCluster:
    """Claims that disagree on a point."""
    topic: str                    # What they disagree about
    side_a_ids: List[str]
    side_b_ids: List[str]
    side_a_position: str          # Brief position A
    side_b_position: str          # Brief position B
    side_a_specifics: List[str] = field(default_factory=list)
    side_b_specifics: List[str] = field(default_factory=list)


@dataclass
class Section2Synthesis:
    """Section 2 output: narrative + structured data."""
    narrative: str = ""           # LLM-generated prose (2-3 paragraphs)
    agreements: List[AgreementCluster] = field(default_factory=list)
    disagreements: List[DisagreementCluster] = field(default_factory=list)
    no_disagreement: bool = False

    def has_content(self) -> bool:
        return bool(self.narrative or self.agreements or self.disagreements)


# ------------------------------------------------------------------
# Agreement Detection (deterministic)
# ------------------------------------------------------------------

def _detect_agreements(claims: List[ClaimOutput]) -> List[AgreementCluster]:
    """
    Find claims that agree (same ticker/theme + same polarity direction).
    Agreement = multiple claims pointing same direction on same topic.
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
            specifics = [c.bullets[0] for c in confirms[:3]]
            agreements.append(AgreementCluster(
                topic=ticker,
                claim_ids=[c.chunk_id for c in confirms],
                summary=_extract_agreement_summary(confirms, ticker),
                specifics=specifics,
            ))

        if len(contradicts) >= 2:
            specifics = [c.bullets[0] for c in contradicts[:3]]
            agreements.append(AgreementCluster(
                topic=f"{ticker} (contrarian)",
                claim_ids=[c.chunk_id for c in contradicts],
                summary=_extract_agreement_summary(contradicts, ticker, contrarian=True),
                specifics=specifics,
            ))

    # Theme-based agreements
    theme_agreements = _detect_theme_agreements(claims)
    agreements.extend(theme_agreements)

    return agreements


def _extract_agreement_summary(claims: List[ClaimOutput], topic: str, contrarian: bool = False) -> str:
    """Extract a summary of what claims agree on, using actual content."""
    if not claims:
        return f"Multiple sources {'challenge' if contrarian else 'confirm'} view on {topic}"

    all_text = ' '.join(c.bullets[0].lower() for c in claims)

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

    first_bullet = claims[0].bullets[0][:80]
    if contrarian:
        return f"Sources challenge consensus: {first_bullet}"
    return f"Sources agree: {first_bullet}"


def _detect_theme_agreements(claims: List[ClaimOutput]) -> List[AgreementCluster]:
    """Detect agreement on themes/macro topics."""
    theme_agreements = []

    MACRO_THEMES = {
        'AI/ML': ['ai', 'artificial intelligence', 'machine learning', 'llm', 'gpu', 'inference'],
        'Cloud': ['cloud', 'aws', 'azure', 'gcp', 'iaas', 'paas', 'saas'],
        'Macro': ['gdp', 'inflation', 'interest rate', 'fed', 'economy', 'recession'],
        'Enterprise': ['enterprise', 'b2b', 'corporate', 'digital transformation'],
        'Cybersecurity': ['security', 'cyber', 'threat', 'breach', 'zero trust'],
        'Consumer': ['consumer', 'spending', 'retail', 'demand'],
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

        if len(confirms) >= 2:
            specifics = [c.bullets[0] for c in confirms[:3]]
            theme_agreements.append(AgreementCluster(
                topic=f"{theme} (theme)",
                claim_ids=[c.chunk_id for c in confirms],
                summary=f"Multiple reports aligned on {theme} outlook",
                specifics=specifics,
            ))

        if len(contradicts) >= 2:
            specifics = [c.bullets[0] for c in contradicts[:3]]
            theme_agreements.append(AgreementCluster(
                topic=f"{theme} concerns",
                claim_ids=[c.chunk_id for c in contradicts],
                summary=f"Multiple reports flag {theme} risks",
                specifics=specifics,
            ))

    return theme_agreements


# ------------------------------------------------------------------
# Disagreement Detection (deterministic)
# ------------------------------------------------------------------

def _detect_disagreements(claims: List[ClaimOutput]) -> Tuple[List[DisagreementCluster], bool]:
    """
    Find claims that disagree (same ticker/theme + opposite positions).
    Returns (disagreements, no_disagreement_flag).
    """
    disagreements = []
    found_any_potential = False

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

        if confirms and contradicts:
            side_a_specific = confirms[0].bullets[0] if confirms else ""
            side_b_specific = contradicts[0].bullets[0] if contradicts else ""

            disagreements.append(DisagreementCluster(
                topic=ticker,
                side_a_ids=[c.chunk_id for c in confirms],
                side_b_ids=[c.chunk_id for c in contradicts],
                side_a_position=f"Consensus view: {side_a_specific}",
                side_b_position=f"Contrarian view: {side_b_specific}",
                side_a_specifics=[c.bullets[0] for c in confirms[:2]],
                side_b_specifics=[c.bullets[0] for c in contradicts[:2]],
            ))

        # Forecast vs risk disagreement
        forecasts = [c for c in ticker_claims if c.claim_type == 'forecast']
        risks = [c for c in ticker_claims if c.claim_type == 'risk']

        if forecasts and risks:
            existing_topics = {d.topic for d in disagreements}
            if f"{ticker} outlook" not in existing_topics:
                forecast_text = forecasts[0].bullets[0] if forecasts else ""
                risk_text = risks[0].bullets[0] if risks else ""

                disagreements.append(DisagreementCluster(
                    topic=f"{ticker} outlook",
                    side_a_ids=[c.chunk_id for c in forecasts],
                    side_b_ids=[c.chunk_id for c in risks],
                    side_a_position=f"Positive outlook: {forecast_text}",
                    side_b_position=f"Risk factors: {risk_text}",
                    side_a_specifics=[c.bullets[0] for c in forecasts[:2]],
                    side_b_specifics=[c.bullets[0] for c in risks[:2]],
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
            side_a = confirms[0].bullets[0] if confirms else ""
            side_b = contradicts[0].bullets[0] if contradicts else ""

            theme_disagreements.append(DisagreementCluster(
                topic=f"{theme} (theme)",
                side_a_ids=[c.chunk_id for c in confirms],
                side_b_ids=[c.chunk_id for c in contradicts],
                side_a_position=f"Positive: {side_a}",
                side_b_position=f"Concerns: {side_b}",
                side_a_specifics=[c.bullets[0] for c in confirms[:2]],
                side_b_specifics=[c.bullets[0] for c in contradicts[:2]],
            ))

    return theme_disagreements


# ------------------------------------------------------------------
# LLM Narrative Generation (Section 2)
# ------------------------------------------------------------------

NARRATIVE_SYSTEM_PROMPT = """You are a hedge fund analyst reading across all materials for a daily TMT briefing.

Your job: Compare perspectives across sources — do NOT summarize sequentially.
Weight conflicting views by source credibility scores provided.

WHAT TO SURFACE:
- Strong conviction — sources expressing high confidence or doubling down
- Softening tone — language shifting from definitive to hedged ("may", "could", "risks")
- Hedging language — qualifiers that weaken prior positions
- Explicit disagreement — sources taking opposite sides on the same topic
- Emerging narratives — new themes appearing across multiple sources

SENTIMENT DRIFT:
- If a source's tone has shifted vs prior positioning, call it out
- If tone has NOT changed, state "No material drift" for that topic
- If nothing happened for a ticker, state "No Update"

RULES:
- Write in clear, direct prose (no bullet points, no headers)
- Cite sources by name (e.g., "Jefferies notes...", "Morgan Stanley argues...")
- Do NOT use thesis language: no "bullish", "bearish", "should", "recommend", "buy", "sell"
- Do NOT add your own opinion or judgment
- Do NOT repeat claims verbatim — synthesize across them
- Keep total output under 200 words
- Write for a professional analyst who has already read Section 1"""


def _build_narrative_prompt(
    claims: List[ClaimOutput],
    agreements: List[AgreementCluster],
    disagreements: List[DisagreementCluster],
    no_disagreement: bool,
) -> str:
    """Build the user prompt for narrative generation."""
    parts = []

    # Source credibility context
    sources_seen = set()
    for c in claims:
        if c.source_citation:
            source = c.source_citation.split(',')[0].strip()
            sources_seen.add(source)

    if sources_seen:
        cred_lines = []
        for s in sorted(sources_seen):
            score = SOURCE_CREDIBILITY.get(s.lower(), 0.3)
            cred_lines.append(f"  {s}: credibility {score}")
        parts.append("Source credibility scores:")
        parts.extend(cred_lines)
        parts.append("")

    # ALL claims — primary input for the LLM to read across
    parts.append("TODAY'S CLAIMS (read all, find your own connections):")
    for c in claims:
        source = c.source_citation.split(',')[0].strip() if c.source_citation else 'Unknown'
        ticker_tag = f"[{c.ticker}]" if c.ticker else "[Sector/Macro]"
        conf = c.confidence_level
        pressure = c.belief_pressure
        parts.append(f"- {ticker_tag} {c.bullets[0]} ({source}, confidence={conf}, pressure={pressure})")
    parts.append("")

    # Deterministic hints — scaffolding, not constraints
    parts.append("DETECTED PATTERNS (hints — you may find additional connections):")
    parts.append("")
    parts.append("Agreement clusters:")
    if agreements:
        for ag in agreements:
            parts.append(f"- {ag.topic}: {ag.summary}")
    else:
        parts.append("- None detected deterministically")

    parts.append("")
    parts.append("Disagreement clusters:")
    if disagreements:
        for dg in disagreements:
            parts.append(f"- {dg.topic}: {dg.side_a_position} vs. {dg.side_b_position}")
    elif no_disagreement:
        parts.append("- No disagreement detected across sources today")
    else:
        parts.append("- Insufficient overlap to detect disagreement")
    parts.append("")

    parts.append("Write a 2-3 paragraph synthesis. Compare perspectives — don't summarize source by source.")
    parts.append("You are NOT limited to the detected patterns above. Find any connections, tensions, or emerging themes across the full claim set.")
    parts.append("Flag conviction strength, softening tone, hedging, and emerging narratives.")
    parts.append("State 'No material drift' where tone is unchanged. Weigh conflicting views by source credibility.")

    return '\n'.join(parts)


def generate_section2_narrative(
    claims: List[ClaimOutput],
    agreements: List[AgreementCluster],
    disagreements: List[DisagreementCluster],
    no_disagreement: bool = False,
    client: Optional[OpenAI] = None,
) -> str:
    """
    Generate narrative prose for Section 2 via LLM.

    Returns: 2-3 paragraph markdown string.
    Falls back to structured bullets if no API key.
    """
    if client is None:
        if not os.getenv("OPENAI_API_KEY"):
            return _fallback_narrative(agreements, disagreements, no_disagreement)
        client = OpenAI()

    prompt = _build_narrative_prompt(claims, agreements, disagreements, no_disagreement)

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": NARRATIVE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=500,
    )

    return response.choices[0].message.content.strip()


def _fallback_narrative(
    agreements: List[AgreementCluster],
    disagreements: List[DisagreementCluster],
    no_disagreement: bool,
) -> str:
    """Structured fallback when no API key available."""
    lines = []

    if agreements:
        lines.append("**Where sources agree:**")
        for ag in agreements:
            lines.append(f"- {ag.topic}: {ag.summary}")
    else:
        lines.append("No clear agreement clusters detected across sources.")

    lines.append("")

    if disagreements:
        lines.append("**Where sources disagree:**")
        for dg in disagreements:
            lines.append(f"- {dg.topic}: {dg.side_a_position} vs. {dg.side_b_position}")
    elif no_disagreement:
        lines.append("No disagreement detected across sources today.")
    else:
        lines.append("Insufficient source overlap to detect disagreement.")

    return '\n'.join(lines)


# ------------------------------------------------------------------
# Main Synthesis Function
# ------------------------------------------------------------------

def synthesize_section2(
    claims: List[ClaimOutput],
    client: Optional[OpenAI] = None,
) -> Section2Synthesis:
    """
    Synthesize Section 2: detect patterns deterministically,
    then generate narrative prose via LLM.

    Args:
        claims: All claims for the day (any category)
        client: Optional OpenAI client

    Returns:
        Section2Synthesis with narrative + structured data
    """
    if not claims:
        return Section2Synthesis(
            narrative="No claims available for synthesis.",
            no_disagreement=True,
        )

    # Deterministic pattern detection
    agreements = _detect_agreements(claims)
    disagreements, no_disagreement = _detect_disagreements(claims)

    # LLM narrative generation
    narrative = generate_section2_narrative(
        claims, agreements, disagreements, no_disagreement, client
    )

    return Section2Synthesis(
        narrative=narrative,
        agreements=agreements,
        disagreements=disagreements,
        no_disagreement=no_disagreement,
    )


# Keep backward compat alias
synthesize_tier2 = synthesize_section2


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Section 2 Synthesis Test")
    print("=" * 60)

    test_claims = [
        # META: Agreement cluster (2 confirming)
        ClaimOutput(
            chunk_id="c1", doc_id="doc1",
            bullets=["META ad revenue growth remains strong at 28% YoY"],
            ticker="META", claim_type="fact",
            source_citation="Jefferies, Brent Thill, p.1",
            confidence_level="high", time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False, category="tracked_ticker",
        ),
        ClaimOutput(
            chunk_id="c2", doc_id="doc2",
            bullets=["META Reels monetization on track per management guidance"],
            ticker="META", claim_type="fact",
            source_citation="Morgan Stanley, p.2",
            confidence_level="high", time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False, category="tracked_ticker",
        ),
        # META: Disagreement (contrarian vs confirms)
        ClaimOutput(
            chunk_id="c3", doc_id="doc3",
            bullets=["META AI capex returns may disappoint near-term"],
            ticker="META", claim_type="risk",
            source_citation="Substack, Independent Analyst, 2026-02-10",
            confidence_level="medium", time_sensitivity="upcoming",
            belief_pressure="contradicts_consensus",
            uncertainty_preserved=True, category="tracked_ticker",
        ),
        # CRWD: Forecast vs Risk
        ClaimOutput(
            chunk_id="c5", doc_id="doc4",
            bullets=["CRWD expected to beat Q4 estimates on strong pipeline"],
            ticker="CRWD", claim_type="forecast",
            source_citation="Jefferies, Joseph Gallo, p.5",
            confidence_level="medium", time_sensitivity="upcoming",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False, category="tracked_ticker",
        ),
        ClaimOutput(
            chunk_id="c6", doc_id="doc5",
            bullets=["CRWD faces competitive pressure from MSFT Defender"],
            ticker="CRWD", claim_type="risk",
            source_citation="Morgan Stanley, p.6",
            confidence_level="medium", time_sensitivity="ongoing",
            belief_pressure="contradicts_prior_assumptions",
            uncertainty_preserved=False, category="tracked_ticker",
        ),
    ]

    print(f"\nInput: {len(test_claims)} claims")
    print("Expected: META agreement + disagreement, CRWD outlook disagreement\n")

    synthesis = synthesize_section2(test_claims)

    print("-" * 60)
    print("Section 2 Narrative:")
    print("-" * 60)
    print(synthesis.narrative)

    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    assert len(synthesis.agreements) >= 1, "Should detect META agreement"
    meta_ag = [a for a in synthesis.agreements if 'META' in a.topic]
    assert len(meta_ag) >= 1, "META claims should show agreement"
    print("✓ Agreement detection working")

    assert len(synthesis.disagreements) >= 1, "Should detect disagreements"
    print(f"✓ Found {len(synthesis.disagreements)} disagreement clusters")

    assert synthesis.narrative, "Should have narrative content"
    print("✓ Narrative generated")

    # No thesis language
    thesis_words = ['recommend', 'should', 'must', 'bullish', 'bearish', 'buy', 'sell']
    has_thesis = any(w in synthesis.narrative.lower() for w in thesis_words)
    if has_thesis:
        print("⚠ Warning: Thesis language detected in narrative")
    else:
        print("✓ No thesis/recommendation language")

    print("\n✓ Section 2 synthesis validated")
