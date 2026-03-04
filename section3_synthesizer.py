"""
Section 3 Synthesizer — Macro Connections.

Takes deduplicated macro claims and generates a short LLM narrative
mapping each macro signal to its potential TMT portfolio implications at a thematic level,
focusing on potential to disrupt the sector.

Constraints:
- Input macro claims are already deduplicated at collection time (macro_news.py)
- Do NOT repeat headline text in the narrative — claims are listed above it
- Conditional language only: "if X, then Y could follow"
- No thesis language (bullish, bearish, buy, sell, recommend)
- Output under 150 words — the claims list carries the content

Usage:
    from section3_synthesizer import synthesize_section3, Section3Synthesis

    synthesis = synthesize_section3(macro_claims)
    print(synthesis.narrative)
"""

import json
import os
from typing import List, Optional
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

from claim_extractor import ClaimOutput
from llm_client import llm_complete, is_configured


# ------------------------------------------------------------------
# Result Dataclass
# ------------------------------------------------------------------

@dataclass
class Section3Synthesis:
    """Section 3 output: macro-to-TMT connection narrative."""
    narrative: str = ""     # LLM-generated TMT linkage prose (2-3 sentences)

    def has_content(self) -> bool:
        return bool(self.narrative)


# ------------------------------------------------------------------
# Macro Relevance Filter
# ------------------------------------------------------------------

MACRO_FILTER_SYSTEM_PROMPT = """You are a TMT portfolio analyst at a secondaries hedge fund, deciding which macro events have genuine potential to shift return assumptions or near-term positioning for this portfolio.

The organizing lens: US-China competition for technological and economic hegemony, and its downstream effects on global supply chains, capital flows, and market sentiment.

PORTFOLIO:
- Internet: META, GOOGL, AMZN, AAPL, BABA, 700.HK
- Software/Security: MSFT, CRWD, ZS, PANW, NET, DDOG, SNOW, MDB

INCLUDE a claim if it could materially affect:
- Supply chain access, hardware procurement, or manufacturing location for portfolio names
- Export controls, sanctions, or tariffs with direct technology or semiconductor exposure
- Geopolitical flashpoints that shift US-China risk perception or capital flows into/out of China tech
- Energy or commodity prices that affect data center costs or consumer spending on digital
- Dollar strength that shifts international revenue assumptions for GOOGL, META, AMZN, BABA
- Regulatory actions that reshape competitive dynamics for specific portfolio tickers
- AI infrastructure access, compute cost, model ecosystem constraints, or AI governance (including military AI use, government AI contracts, AI company regulatory exposure)
- Any geopolitical escalation with plausible knock-on effects on semiconductors, cloud, or digital infrastructure — even if tech is not explicitly named

EXCLUDE a claim if it is:
- Pure domestic economic data (GDP, jobs, CPI) with no explicit geopolitical or tech connection
- Equity market price moves or index levels with no causal explanation
- Credit/bond/rate dynamics that don't directly connect to software multiples or procurement
- Industrial, healthcare, or commodity news with no TMT supply chain link

Return ONLY a JSON object: {"relevant_indices": [0, 2, ...]} using 0-based indices from the list.
If nothing qualifies, return {"relevant_indices": []}."""


def filter_macro_claims_by_tmt_relevance(
    claims: List[ClaimOutput],
) -> List[ClaimOutput]:
    """
    LLM filter: one batch call returning only macro claims with genuine TMT-disruption potential.
    Falls back to returning all claims if LLM is unavailable.
    """
    if not claims or not is_configured("synthesis"):
        return claims

    lines = ["MACRO CLAIMS (0-indexed):"]
    for i, c in enumerate(claims):
        src = c.source_citation.split(',')[0].strip() if c.source_citation else 'Unknown'
        lines.append(f"[{i}] ({src}) {c.bullets[0]}")
    lines.append('\nReturn {"relevant_indices": [...]} — indices of claims with genuine TMT portfolio disruption potential.')

    response = llm_complete(
        "synthesis",
        [
            {"role": "system", "content": MACRO_FILTER_SYSTEM_PROMPT},
            {"role": "user", "content": '\n'.join(lines)},
        ],
        temperature=0.1,
        max_tokens=200,
        json_mode=True,
    )

    try:
        indices = json.loads(response).get("relevant_indices", [])
        kept = set(indices)
        for i, c in enumerate(claims):
            label = "KEEP" if i in kept else "DROP"
            bullet = c.bullets[0][:80] if c.bullets else "(no bullet)"
            print(f"    [{label}] [{i}] {bullet}")
        filtered = [claims[i] for i in indices if 0 <= i < len(claims)]
        return filtered if filtered else claims  # fallback: never return empty if input non-empty
    except (json.JSONDecodeError, KeyError, TypeError):
        return claims  # fallback: return all on parse failure


# ------------------------------------------------------------------
# System Prompt
# ------------------------------------------------------------------

SECTION3_SYSTEM_PROMPT = """You are a TMT portfolio analyst at a secondaries hedge fund mapping geopolitical macro signals to portfolio implications.

The macro signals are already listed above your narrative — do NOT repeat or summarize them.
Your job: write 2-3 sentences connecting these signals to portfolio risk, viewed through the lens of US-China competition for technological and economic hegemony.

CONSIDER where relevant:
- Which portfolio names are most exposed via China/Asia revenue, hardware supply chains, or semiconductor dependencies
- How geopolitical escalation or reshoring shifts fundamental cost or revenue assumptions
- Near-term secondaries positioning implications: does this shift risk appetite or sector rotation pressure

PORTFOLIO REFERENCE:
Internet: META, GOOGL, AMZN, AAPL, BABA, 700.HK
Software/Security: MSFT, CRWD, ZS, PANW, NET, DDOG, SNOW, MDB

RULES:
- Conditional language only: "if X, then Y could follow" — not "X will happen"
- Do NOT use thesis language: no "bullish", "bearish", "buy", "sell", "recommend"
- Do NOT repeat or paraphrase the headline text above
- Cite specific tickers where the linkage is clear
- Under 150 words — this is a bridge paragraph, not a summary
- This output will be flagged as model-generated; the analyst applies their own judgment"""


# ------------------------------------------------------------------
# Main Synthesis Function
# ------------------------------------------------------------------

def synthesize_section3(
    macro_claims: List[ClaimOutput],
) -> Section3Synthesis:
    """
    Generate TMT linkage narrative for Section 3.

    Args:
        macro_claims: Macro-category claims (deduplicated at collection time)

    Returns:
        Section3Synthesis with narrative prose.
        Returns empty synthesis if no macro claims or no API key.
    """
    if not macro_claims or not is_configured("synthesis"):
        return Section3Synthesis()

    # Build prompt — list signals once, ask for linkage narrative
    lines = []
    lines.append("MACRO SIGNALS TODAY (already listed in the briefing above your narrative):")
    for c in macro_claims:
        source = c.source_citation.split(',')[0].strip() if c.source_citation else 'Unknown'
        lines.append(f"- {c.bullets[0]} ({source})")
        if c.sector_implication:
            lines.append(f"  [Existing linkage note: {c.sector_implication}]")
    lines.append("")
    lines.append(
        "Write 2-3 sentences connecting these macro signals to specific portfolio names. "
        "Do not repeat the headlines. Conditional language only."
    )

    narrative = llm_complete(
        "synthesis",
        [
            {"role": "system", "content": SECTION3_SYSTEM_PROMPT},
            {"role": "user", "content": '\n'.join(lines)},
        ],
        temperature=0.3,
        max_tokens=200,
    )

    # Hard-enforce 150-word ceiling in case the LLM drifts over
    words = narrative.split()
    if len(words) > 150:
        narrative = ' '.join(words[:150]) + '...'

    return Section3Synthesis(narrative=narrative)


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Section 3 Synthesizer Test")
    print("=" * 60)

    test_claims = [
        ClaimOutput(
            chunk_id="m1", doc_id="macro1",
            bullets=["Fed held rates at 5.25-5.50% citing persistent core inflation"],
            ticker=None, claim_type="fact",
            source_citation="Reuters, 2026-02-25",
            confidence_level="high", time_sensitivity="breaking",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False, category="macro",
            event_type="macro",
            sector_implication="Higher rates extend multiple compression on unprofitable software",
        ),
        ClaimOutput(
            chunk_id="m2", doc_id="macro2",
            bullets=["US tariffs on Chinese semiconductor imports raised to 50%"],
            ticker=None, claim_type="fact",
            source_citation="CNBC, 2026-02-25",
            confidence_level="high", time_sensitivity="breaking",
            belief_pressure="contradicts_prior_assumptions",
            uncertainty_preserved=False, category="macro",
            event_type="macro",
            sector_implication="Supply chain risk for AAPL; could benefit domestic chip names",
        ),
    ]

    print(f"\nInput: {len(test_claims)} macro claims")

    synthesis = synthesize_section3(test_claims)

    print("\n" + "-" * 60)
    print("Section 3 Narrative:")
    print("-" * 60)
    if synthesis.has_content():
        print(synthesis.narrative)
    else:
        print("(empty — no API key)")

    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    assert hasattr(synthesis, 'narrative'), "Should have narrative field"
    print("✓ Section3Synthesis structure valid")

    if synthesis.has_content():
        thesis_words = ['bullish', 'bearish', 'buy', 'sell', 'recommend', 'should']
        has_thesis = any(w in synthesis.narrative.lower() for w in thesis_words)
        if has_thesis:
            print("⚠ Warning: Thesis language detected")
        else:
            print("✓ No thesis language")
        print(f"✓ Narrative: {len(synthesis.narrative.split())} words")
    else:
        print("✓ Empty synthesis (no API key) handled correctly")

    print("\n✓ Section 3 synthesizer ready")
