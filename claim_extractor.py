"""
Claim extraction with judgment hooks — atomic claims annotated for decision-making.
Each chunk → 1-2 challengeable bullet points + judgment metadata.

Output per claim:
- assertion (1-2 bullets, explicit)
- confidence_level (low / medium / high)
- source_citation (PDF + page)
- time_sensitivity (breaking / upcoming / ongoing)
- belief_pressure (confirms_consensus / contradicts_consensus / contradicts_prior_assumptions / unclear)

Rules:
- Do NOT decide conviction
- Do NOT rank importance globally
- Preserve uncertainty explicitly
- Claims must be easy to: agree with, disagree with, ignore consciously

Usage:
    from claim_extractor import extract_claims, ClaimOutput

    claims = extract_claims(chunks, classifications, doc)
"""

import json
import os
from typing import List, Optional, Literal
from dataclasses import dataclass, field, asdict
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

from schemas import Chunk, Document, Claim
from classifier import ChunkClassification

# ------------------------------------------------------------------
# Enums for judgment hooks
# ------------------------------------------------------------------

CONFIDENCE_LEVELS = ['low', 'medium', 'high']
TIME_SENSITIVITIES = ['breaking', 'upcoming', 'ongoing']
BELIEF_PRESSURES = [
    'confirms_consensus',
    'contradicts_consensus',
    'contradicts_prior_assumptions',
    'unclear',
]
EVENT_TYPES = ['earnings', 'guidance', 'product', 'regulation', 'org', 'market', 'macro']

# ------------------------------------------------------------------
# Claim Output Schema
# ------------------------------------------------------------------

@dataclass
class ClaimOutput:
    """Extracted claim with judgment hooks."""
    chunk_id: str
    doc_id: str

    # Core assertion
    bullets: List[str]                # 1-2 explicit bullet points
    ticker: Optional[str]             # Primary ticker if any
    claim_type: str                   # fact / forecast / risk / interpretation

    # Source traceability
    source_citation: str              # "Jefferies, Brent Thill, p.2, 2026-01-25"

    # Judgment hooks (reader decides conviction, not us)
    confidence_level: str             # low / medium / high
    time_sensitivity: str             # breaking / upcoming / ongoing
    belief_pressure: str              # confirms_consensus / contradicts_consensus / contradicts_prior_assumptions / unclear

    # Uncertainty tracking
    uncertainty_preserved: bool       # True if "may", "could", etc. kept

    # Classification category (from classifier.py)
    category: Optional[str] = None          # tracked_ticker | tmt_sector | macro

    # MECE section routing fields
    event_type: Optional[str] = None        # earnings/guidance/product/regulation/org/market/macro
    is_descriptive_event: bool = False       # True = objective fact about what occurred
    has_belief_delta: bool = False           # True = changes/pressures prior expectations
    sector_implication: Optional[str] = None # For macro claims: one-sentence TMT linkage
    section_id: Optional[int] = None        # assigned during briefing routing

    # Source context — original analyst prose preserved for synthesis quality
    source_text: Optional[str] = None       # Raw chunk text (for Section 2 synthesis context)

    def to_dict(self) -> dict:
        return asdict(self)

    def format_markdown(self, show_hooks: bool = True) -> str:
        """Format claim as markdown with judgment hooks."""
        lines = []

        # Bullets
        for bullet in self.bullets:
            lines.append(f"- {bullet}")

        # Judgment hooks as compact tags
        if show_hooks:
            tags = []
            # Confidence
            conf_icon = {'low': '○', 'medium': '◐', 'high': '●'}.get(self.confidence_level, '?')
            tags.append(f"{conf_icon} {self.confidence_level}")
            # Time sensitivity
            time_icon = {'breaking': '⚡', 'upcoming': '📅', 'ongoing': '↻'}.get(self.time_sensitivity, '?')
            tags.append(f"{time_icon} {self.time_sensitivity}")
            # Belief pressure
            if self.belief_pressure == 'confirms_consensus':
                tags.append("✓ confirms")
            elif self.belief_pressure == 'contradicts_consensus':
                tags.append("✗ contradicts")
            elif self.belief_pressure == 'contradicts_prior_assumptions':
                tags.append("⚠ challenges prior")
            # Don't show 'unclear' - that's the default/neutral case

            lines.append(f"  `{' | '.join(tags)}`")

        # Citation
        lines.append(f"  *— {self.source_citation}*")

        return '\n'.join(lines)

    def judgment_summary(self) -> str:
        """One-line judgment summary for sorting/filtering."""
        return f"{self.confidence_level}/{self.time_sensitivity}/{self.belief_pressure}"


# ------------------------------------------------------------------
# Extraction Prompt
# ------------------------------------------------------------------

SYSTEM_PROMPT = """You are a research analyst extracting atomic claims from sell-side research.
Your task: Convert the text into 1-2 challengeable bullet points with judgment annotations.

CRITICAL: You are DESCRIBING claims, not DECIDING importance. The reader will form their own conviction.

Output format (JSON):
{
  "bullets": ["First explicit assertion...", "Second assertion (optional)..."],
  "primary_ticker": "META" or null,
  "has_uncertainty": true/false,
  "confidence_level": "low" | "medium" | "high",
  "time_sensitivity": "breaking" | "upcoming" | "ongoing",
  "belief_pressure": "confirms_consensus" | "contradicts_consensus" | "contradicts_prior_assumptions" | "unclear",
  "event_type": "earnings" | "guidance" | "product" | "regulation" | "org" | "market" | "macro" | null,
  "is_descriptive_event": true | false,
  "has_belief_delta": true | false,
  "sector_implication": "One sentence TMT linkage" | null
}

FIELD DEFINITIONS:

1. bullets (1-2 max)
   - Must be EXPLICIT ASSERTIONS that can be verified or challenged
   - Good: "META ad revenue grew 28% YoY in Q4"
   - Bad: "META had strong performance" (too vague)
   - PRESERVE uncertainty language exactly: "may", "could", "estimates", "expects"
   - Include specific data: numbers, percentages, dates, price targets

2. confidence_level (how confident is the SOURCE, not you)
   - "high": Analyst states with conviction, uses definitive language
   - "medium": Analyst hedges somewhat, uses "likely", "probably"
   - "low": Analyst explicitly uncertain, uses "may", "could", "unclear"

3. time_sensitivity (when does this matter)
   - "breaking": New information, just announced, immediate relevance
   - "upcoming": Forward-looking catalyst, earnings date, product launch
   - "ongoing": Structural trend, long-term thesis, not time-bound

4. belief_pressure (how this relates to market expectations)
   - "confirms_consensus": Supports what Street already believes
   - "contradicts_consensus": Goes against prevailing view
   - "contradicts_prior_assumptions": Challenges the reader's likely mental model
   - "unclear": Not enough context to determine

5. event_type (what category of event is this)
   - "earnings": Earnings results, revenue/EPS beats or misses, quarterly reports
   - "guidance": Management guidance, outlook changes, forward estimates
   - "product": Product launches, feature announcements, user milestones
   - "regulation": Regulatory actions, legal rulings, compliance changes
   - "org": Organizational changes, hiring, layoffs, M&A, leadership
   - "market": Market data, pricing, index moves, competitive dynamics
   - "macro": Macroeconomic events — GDP, interest rates, inflation, tariffs, fiscal policy
   - null: Not an identifiable event (analysis, commentary, background)

6. is_descriptive_event (did something concrete HAPPEN)
   - true: A concrete event, action, or announcement occurred
   - false: Analysis, interpretation, ongoing background, or thesis

7. has_belief_delta (does this change prior expectations)
   - true: This contradicts, revises, or materially updates what was previously expected
   - false: This confirms or is consistent with prior expectations

8. sector_implication (macro claims ONLY)
   - For macro/regulatory events: one sentence on how this connects to or influences the TMT sector
   - For company-specific claims: null
   - Example: "Higher rates extend pressure on unprofitable software multiples"

RULES:
- Do NOT rank importance (that's the reader's job)
- Do NOT summarize across multiple sources
- Do NOT add narrative or connecting language
- Do NOT strengthen or weaken the original assertion"""


def _build_user_prompt(
    chunk: Chunk,
    classification: ChunkClassification,
    doc: Document,
) -> str:
    """Build extraction prompt with context."""
    parts = []

    # Document context
    parts.append(f"Source: {doc.source.title() if doc.source else 'Unknown'}")
    parts.append(f"Analyst: {doc.analyst or 'Unknown'}")
    parts.append(f"Date: {doc.date_published or 'Unknown'}")
    if chunk.page_start:
        parts.append(f"Page: {chunk.page_start}")
    parts.append("")

    # Classification context
    parts.append(f"Content type: {classification.content_type}")
    parts.append(f"Category: {classification.category}")
    if classification.tmt_subtopic:
        parts.append(f"TMT sub-topic: {classification.tmt_subtopic}")
    if classification.tickers:
        parts.append(f"Tickers: {', '.join(classification.tickers)}")
    parts.append("")

    # The actual text
    parts.append("Text to extract claims from:")
    parts.append(chunk.text.strip())

    return '\n'.join(parts)


def _build_citation(doc: Document, chunk: Chunk) -> str:
    """Build source citation string."""
    parts = []

    # Source firm
    source = doc.source.title() if doc.source else "Unknown"
    parts.append(source)

    # Analyst name
    if doc.analyst:
        parts.append(doc.analyst)

    # Page number
    if chunk.page_start:
        if chunk.page_end and chunk.page_end != chunk.page_start:
            parts.append(f"pp.{chunk.page_start}-{chunk.page_end}")
        else:
            parts.append(f"p.{chunk.page_start}")

    # Date
    if doc.date_published:
        parts.append(doc.date_published)

    return ', '.join(parts)


# ------------------------------------------------------------------
# Main Extraction Function
# ------------------------------------------------------------------

def extract_claim(
    chunk: Chunk,
    classification: ChunkClassification,
    doc: Document,
    client: Optional[OpenAI] = None,
) -> ClaimOutput:
    """
    Extract atomic claim(s) with judgment hooks from a single chunk.

    Args:
        chunk: Source chunk
        classification: Chunk classification
        doc: Parent document (for citation)
        client: Optional OpenAI client

    Returns:
        ClaimOutput with bullets + judgment annotations
    """
    if client is None:
        client = OpenAI()

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(chunk, classification, doc)},
        ],
        temperature=0,
        max_tokens=400,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}

    # Validate and extract fields
    bullets = data.get("bullets", [])
    if not bullets or not isinstance(bullets, list):
        bullets = [chunk.text.strip()[:200] + "..."]
    bullets = bullets[:2]

    # Validate enums with defaults
    confidence = data.get("confidence_level", "medium")
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "medium"

    time_sens = data.get("time_sensitivity", "ongoing")
    if time_sens not in TIME_SENSITIVITIES:
        time_sens = "ongoing"

    belief = data.get("belief_pressure", "unclear")
    if belief not in BELIEF_PRESSURES:
        belief = "unclear"

    # Ticker
    ticker = data.get("primary_ticker")
    if not ticker and classification.tickers:
        ticker = classification.tickers[0]

    # Event type
    event_type = data.get("event_type")
    if event_type and event_type not in EVENT_TYPES:
        event_type = None

    # Descriptive event flag (with fallback derivation)
    is_descriptive_event = data.get("is_descriptive_event", False)
    if not is_descriptive_event and event_type and event_type != 'macro':
        is_descriptive_event = (
            classification.content_type == 'fact'
            and time_sens in ('breaking', 'upcoming')
        )

    # Belief delta flag (with fallback derivation)
    has_belief_delta = data.get("has_belief_delta", False)
    if not has_belief_delta:
        has_belief_delta = belief in ('contradicts_consensus', 'contradicts_prior_assumptions')

    # Sector implication (macro claims only)
    sector_implication = data.get("sector_implication")
    if sector_implication and event_type != 'macro':
        sector_implication = None  # Only valid for macro claims

    return ClaimOutput(
        chunk_id=chunk.chunk_id,
        doc_id=doc.doc_id,
        bullets=bullets,
        ticker=ticker,
        claim_type=classification.content_type,
        source_citation=_build_citation(doc, chunk),
        confidence_level=confidence,
        time_sensitivity=time_sens,
        belief_pressure=belief,
        uncertainty_preserved=data.get("has_uncertainty", False),
        category=classification.category,
        event_type=event_type,
        is_descriptive_event=is_descriptive_event,
        has_belief_delta=has_belief_delta,
        sector_implication=sector_implication,
        source_text=chunk.text.strip(),
    )


def extract_claims(
    chunks: List[Chunk],
    classifications: List[ChunkClassification],
    doc: Document,
    client: Optional[OpenAI] = None,
) -> List[ClaimOutput]:
    """
    Extract claims with judgment hooks from multiple chunks.

    Args:
        chunks: List of chunks (post-classification, irrelevant already filtered)
        classifications: Corresponding classifications
        doc: Parent document
        client: Optional OpenAI client (reused)

    Returns:
        List of ClaimOutput objects
    """
    if client is None:
        client = OpenAI()

    results = []
    for i, (chunk, clf) in enumerate(zip(chunks, classifications)):
        print(f"  Extracting claims {i+1}/{len(chunks)}...", end='\r')
        claim = extract_claim(chunk, clf, doc, client)
        results.append(claim)

    print(f"  Extracted {len(results)} claims" + " " * 20)
    return results


# ------------------------------------------------------------------
# Per-group claim sorting (breaking + contrarian first, no cap)
# ------------------------------------------------------------------

# Priority ordering: most signal-dense claims surface first
_TIME_PRIORITY = {'breaking': 0, 'upcoming': 1, 'ongoing': 2}
_BELIEF_PRIORITY = {
    'contradicts_consensus': 0,
    'contradicts_prior_assumptions': 1,
    'unclear': 2,
    'confirms_consensus': 3,
}


def _claim_sort_key(claim: ClaimOutput) -> tuple:
    """Sort key: breaking + contrarian claims first."""
    return (
        _TIME_PRIORITY.get(claim.time_sensitivity, 9),
        _BELIEF_PRIORITY.get(claim.belief_pressure, 9),
    )


def sort_claims_by_priority(claims: List[ClaimOutput]) -> List[ClaimOutput]:
    """
    Sort claims within each routing group by priority — no cap applied.

    Groups:
    - tracked_ticker claims: grouped by ticker
    - tmt_sector claims: grouped by tmt_subtopic
    - macro claims: one group

    Within each group: breaking > upcoming > ongoing, contrarian > confirming.
    All relevant claims are kept; redundancy is prevented upstream by the
    claim extractor's atomic-claim prompt.
    """
    from collections import defaultdict

    groups = defaultdict(list)
    for claim in claims:
        if claim.category == 'tracked_ticker' and claim.ticker:
            groups[('ticker', claim.ticker)].append(claim)
        elif claim.category == 'tmt_sector':
            key = claim.event_type or 'general'
            groups[('tmt', key)].append(claim)
        elif claim.category == 'macro':
            groups[('macro', 'macro')].append(claim)
        else:
            groups[('other', 'other')].append(claim)

    sorted_claims = []
    for key, group in groups.items():
        group.sort(key=_claim_sort_key)
        sorted_claims.extend(group)

    print(f"  Sorted {len(sorted_claims)} claims by priority (no cap)")
    return sorted_claims


# ------------------------------------------------------------------
# Formatting for different views
# ------------------------------------------------------------------

def format_claims_markdown(
    claims: List[ClaimOutput],
    group_by_ticker: bool = True,
    show_hooks: bool = True,
) -> str:
    """
    Format claims as markdown for briefing output.

    Args:
        claims: List of ClaimOutput objects
        group_by_ticker: If True, group claims by ticker
        show_hooks: If True, include judgment hook tags

    Returns:
        Markdown string
    """
    if not claims:
        return "*No claims extracted.*"

    if not group_by_ticker:
        return '\n\n'.join(c.format_markdown(show_hooks) for c in claims)

    # Group by ticker
    from collections import defaultdict
    by_ticker = defaultdict(list)
    no_ticker = []

    for claim in claims:
        if claim.ticker:
            by_ticker[claim.ticker].append(claim)
        else:
            no_ticker.append(claim)

    lines = []
    for ticker in sorted(by_ticker.keys()):
        lines.append(f"### {ticker}")
        for claim in by_ticker[ticker]:
            lines.append(claim.format_markdown(show_hooks))
        lines.append("")

    if no_ticker:
        lines.append("### General")
        for claim in no_ticker:
            lines.append(claim.format_markdown(show_hooks))

    return '\n'.join(lines)


def filter_by_belief_pressure(
    claims: List[ClaimOutput],
    include: List[str],
) -> List[ClaimOutput]:
    """Filter claims by belief pressure (for focused review)."""
    return [c for c in claims if c.belief_pressure in include]


def filter_by_time_sensitivity(
    claims: List[ClaimOutput],
    include: List[str],
) -> List[ClaimOutput]:
    """Filter claims by time sensitivity."""
    return [c for c in claims if c.time_sensitivity in include]


# ------------------------------------------------------------------
# Bridge to schemas.Claim
# ------------------------------------------------------------------

def to_schema_claims(claims: List[ClaimOutput]) -> List[Claim]:
    """Convert ClaimOutput to schemas.Claim for persistence."""
    result = []
    for co in claims:
        for bullet in co.bullets:
            result.append(Claim(
                doc_id=co.doc_id,
                chunk_id=co.chunk_id,
                claim_type=co.claim_type,
                ticker=co.ticker,
                content=bullet,
                confidence=1.0 if co.confidence_level == 'high' else 0.7 if co.confidence_level == 'medium' else 0.4,
            ))
    return result


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Claim Extraction with Judgment Hooks")
    print("=" * 60)

    # Sample data
    sample_doc = Document(
        doc_id="doc-1",
        source="jefferies",
        title="META Platforms: AI Monetization Inflection",
        analyst="Brent Thill",
        date_published="2026-01-25",
    )

    sample_chunks = [
        Chunk(
            chunk_id="chunk-1",
            doc_id="doc-1",
            text="""We are raising our price target on META to $750 from $680 based on
accelerating AI monetization across the ad platform. Revenue growth
is tracking ahead of consensus with Reels monetization inflecting.
AI-driven ad targeting improvements yielded 15% better ROAS.""",
            page_start=1,
        ),
        Chunk(
            chunk_id="chunk-2",
            doc_id="doc-1",
            text="""Key risks include regulatory headwinds in the EU, potential TikTok
resurgence, and slower-than-expected AI capex returns. Additionally,
Apple's privacy changes could further impact ad measurement, though
META has largely adapted its systems.""",
            page_start=3,
        ),
        Chunk(
            chunk_id="chunk-3",
            doc_id="doc-1",
            text="""Breaking: META announced this morning that Threads daily active users
surpassed 300M, far exceeding analyst expectations of 200M. This
represents a significant acceleration from 150M DAU reported last quarter.""",
            page_start=2,
        ),
        Chunk(
            chunk_id="chunk-4",
            doc_id="doc-1",
            text="""The Federal Reserve held interest rates steady at 5.25% in its latest
meeting, signaling patience on rate cuts. Chair Powell noted inflation
remains above target. Markets now expect the first cut in September.""",
            page_start=4,
        ),
    ]

    sample_classifications = [
        ChunkClassification(
            chunk_id="chunk-1",
            category="tracked_ticker",
            tickers=["META"],
            content_type="forecast",
            polarity="positive",
        ),
        ChunkClassification(
            chunk_id="chunk-2",
            category="tracked_ticker",
            tickers=["META", "AAPL"],
            content_type="risk",
            polarity="negative",
        ),
        ChunkClassification(
            chunk_id="chunk-3",
            category="tracked_ticker",
            tickers=["META"],
            content_type="fact",
            polarity="positive",
        ),
        ChunkClassification(
            chunk_id="chunk-4",
            category="macro",
            tickers=[],
            content_type="fact",
            polarity="neutral",
        ),
    ]

    # Check for API key
    if os.getenv("OPENAI_API_KEY"):
        print("\nRunning live claim extraction...\n")

        claims = extract_claims(sample_chunks, sample_classifications, sample_doc)

        print("\n" + "-" * 60)
        print("Extracted Claims with Judgment Hooks:")
        print("-" * 60)

        for claim in claims:
            print(f"\n[{claim.chunk_id}] {claim.claim_type.upper()}")
            print(claim.format_markdown())
            print(f"  Judgment: {claim.judgment_summary()}")

        print("\n" + "-" * 60)
        print("Grouped Markdown Output:")
        print("-" * 60)
        print(format_claims_markdown(claims))

        # Verification
        print("\n" + "=" * 60)
        print("Verification")
        print("=" * 60)

        assert len(claims) == len(sample_chunks)
        print("✓ One ClaimOutput per chunk")

        assert all(len(c.bullets) <= 2 for c in claims)
        print("✓ Max 2 bullets per claim")

        assert all(c.source_citation for c in claims)
        print("✓ All claims have source citation")

        assert all(c.confidence_level in CONFIDENCE_LEVELS for c in claims)
        print("✓ All claims have valid confidence_level")

        assert all(c.time_sensitivity in TIME_SENSITIVITIES for c in claims)
        print("✓ All claims have valid time_sensitivity")

        assert all(c.belief_pressure in BELIEF_PRESSURES for c in claims)
        print("✓ All claims have valid belief_pressure")

        # Check for breaking news detection
        breaking_claims = filter_by_time_sensitivity(claims, ['breaking'])
        print(f"✓ Found {len(breaking_claims)} breaking claims")

        # Check for contrarian signals
        contrarian = filter_by_belief_pressure(claims, ['contradicts_consensus', 'contradicts_prior_assumptions'])
        print(f"✓ Found {len(contrarian)} contrarian claims")

        # MECE section routing fields
        assert all(hasattr(c, 'event_type') for c in claims)
        print("✓ All claims have event_type field")

        assert all(hasattr(c, 'is_descriptive_event') for c in claims)
        print("✓ All claims have is_descriptive_event field")

        assert all(hasattr(c, 'has_belief_delta') for c in claims)
        print("✓ All claims have has_belief_delta field")

        # Check macro claim gets sector_implication
        macro_claims = [c for c in claims if c.event_type == 'macro']
        print(f"✓ Found {len(macro_claims)} macro claims")
        for mc in macro_claims:
            print(f"  sector_implication: {mc.sector_implication}")

        # Check descriptive events
        descriptive = [c for c in claims if c.is_descriptive_event]
        print(f"✓ Found {len(descriptive)} descriptive events")

        # Check belief deltas
        deltas = [c for c in claims if c.has_belief_delta]
        print(f"✓ Found {len(deltas)} claims with belief delta")

    else:
        print("\nNo OPENAI_API_KEY found. Showing sample output structure:\n")

        sample_claim = ClaimOutput(
            chunk_id="chunk-1",
            doc_id="doc-1",
            bullets=[
                "META price target raised to $750 (from $680) on AI monetization acceleration",
                "AI-driven ad targeting improvements yielded 15% better ROAS",
            ],
            ticker="META",
            claim_type="forecast",
            source_citation="Jefferies, Brent Thill, p.1, 2026-01-25",
            confidence_level="high",
            time_sensitivity="breaking",
            belief_pressure="contradicts_consensus",
            uncertainty_preserved=False,
            category="tracked_ticker",
            event_type="guidance",
            is_descriptive_event=True,
            has_belief_delta=True,
        )

        macro_claim = ClaimOutput(
            chunk_id="chunk-4",
            doc_id="doc-1",
            bullets=["Fed held rates steady at 5.25%, signaling patience on cuts"],
            ticker=None,
            claim_type="fact",
            source_citation="Macro, 2026-01-25",
            confidence_level="high",
            time_sensitivity="breaking",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
            category="macro",
            event_type="macro",
            is_descriptive_event=True,
            has_belief_delta=False,
            sector_implication="Higher rates extend pressure on unprofitable software multiples",
        )

        print("Sample ClaimOutput:")
        print(json.dumps(sample_claim.to_dict(), indent=2))

        print("\nMacro ClaimOutput:")
        print(json.dumps(macro_claim.to_dict(), indent=2))

        print("\nFormatted markdown:")
        print(sample_claim.format_markdown())

        print("\nJudgment summary:", sample_claim.judgment_summary())

        # Verify new fields exist
        assert sample_claim.event_type == "guidance"
        assert sample_claim.is_descriptive_event is True
        assert sample_claim.has_belief_delta is True
        assert macro_claim.event_type == "macro"
        assert macro_claim.sector_implication is not None
        print("\n✓ All MECE routing fields validated")
