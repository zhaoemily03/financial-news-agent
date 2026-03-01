"""
Chunk classifier — route each chunk into one of four categories.

Uses a cheap LLM (GPT-3.5-turbo) for JSON-only output.
No summarization. No relevance scoring. Just categorize and tag.

Categories:
- tracked_ticker: Chunk is about a specific tracked ticker → tag with ticker(s)
- tmt_sector: Chunk is about TMT sector-level information → tag with sub-topic
- macro: Chunk has macro-relevant indicators (economic, geopolitical)
- irrelevant: Chunk is off-scope → discard from briefing and historical filing

Usage:
    from classifier import classify_chunk, classify_chunks

    classification = classify_chunk(chunk, doc)
    # or batch:
    classifications = classify_chunks(chunks, doc)
"""

import json
import os
from typing import List, Optional
from dataclasses import dataclass, field, asdict
from dotenv import load_dotenv

load_dotenv()

from schemas import Chunk, Document
import config
from llm_client import llm_complete, is_configured

# ------------------------------------------------------------------
# Category and sub-topic definitions
# ------------------------------------------------------------------

CATEGORIES = ['tracked_ticker', 'tmt_sector', 'macro', 'irrelevant']

TMT_SUBTOPICS = [
    'cloud_enterprise_software',      # Cloud computing, SaaS, enterprise apps
    'internet_digital_advertising',    # Digital ads, ad tech, social platforms
    'semiconductors_hardware',         # Chips, processors, GPU, data centers, devices
    'telecom_infrastructure',          # 5G, wireless, broadband, towers, fiber
    'consumer_internet_media',         # Streaming, gaming, e-commerce, consumer apps
]

CONTENT_TYPES = ['fact', 'interpretation', 'forecast', 'risk']
POLARITIES = ['positive', 'negative', 'neutral', 'mixed']

# Default ticker list (used when no per-user tickers are provided)
_DEFAULT_TICKER_LIST = ', '.join(sorted(set(config.ALL_TICKERS)))


# ------------------------------------------------------------------
# Classification Schema
# ------------------------------------------------------------------

@dataclass
class ChunkClassification:
    """Classification metadata for a chunk."""
    chunk_id: str = ""
    category: str = "irrelevant"              # tracked_ticker | tmt_sector | macro | irrelevant
    tickers: List[str] = field(default_factory=list)  # specific tickers (for tracked_ticker)
    tmt_subtopic: Optional[str] = None        # sub-topic (for tmt_sector)
    content_type: str = "fact"                # fact | interpretation | forecast | risk
    polarity: str = "neutral"                 # positive | negative | neutral | mixed

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ChunkClassification":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ------------------------------------------------------------------
# Classification Prompt (built dynamically per-call)
# ------------------------------------------------------------------

_PROMPT_STATIC = """You are a financial document classifier. Classify the given text chunk into exactly one category.
Use waterfall logic such that if a chunk is classified as tracked_ticker, you do not need to continue checking if it matches with the
latter three categories of tmt_sector, macro, or irrelevant.

Output ONLY valid JSON with these fields:

- category: one of (tracked_ticker, tmt_sector, macro, irrelevant)
  - tracked_ticker: Chunk discusses a specific stock being tracked. Tracked tickers: {ticker_list}
  - tmt_sector: Chunk discusses TMT sector-level trends, themes, or developments not tied to a single tracked ticker
  - macro: Chunk discusses geopolitical or regulatory factors with DIRECT technology/TMT implications, OR macro conditions that materially shift TMT sector assumptions.
    Qualify as macro ONLY if the chunk explicitly connects to technology, software, semiconductors, or digital platforms. Examples that qualify:
    US-China export controls or sanctions, semiconductor import tariffs, CFIUS reviews of tech deals, antitrust actions against big tech (DOJ/FTC/EU DMA), AI regulation,
    data privacy legislation, AI capex or hyperscaler spending trends, Taiwan geopolitics affecting chip supply.
    Examples that do NOT qualify as macro (classify as irrelevant instead): general inflation reports, unemployment data, GDP forecasts, Fed rate decisions, etc.
    — UNLESS the chunk explicitly discusses how these affect tech hardware margins, software multiples, or digital ad spending.
  - irrelevant: all else

- tickers: array of tracked stock tickers discussed (e.g. ["META", "GOOGL"]). Only include tickers from the tracked list above. Empty array if none.

- tmt_subtopic: if category is tmt_sector, one of (cloud_enterprise_software, internet_digital_advertising, semiconductors_hardware, telecom_infrastructure, consumer_internet_media). null otherwise.
  - cloud_enterprise_software: Cloud computing, SaaS, enterprise apps, developer tools, AI agents, LLMs, coding tools
  - internet_digital_advertising: Digital ads, ad tech, social media platforms, programmatic
  - semiconductors_hardware: Chips, processors, GPU, data centers, devices, AI inference hardware
  - telecom_infrastructure: 5G, wireless, broadband, towers, fiber, spectrum
  - consumer_internet_media: Streaming, gaming, e-commerce, consumer apps, content

- content_type: one of (fact, interpretation, forecast, risk)
  - fact: verifiable data points, metrics, historical events
  - interpretation: analyst opinions, assessments, explanations
  - forecast: predictions about future performance
  - risk: potential negative factors, concerns, warnings

- polarity: one of (positive, negative, neutral, mixed)

Rules:
1. Output ONLY the JSON object, no markdown, no explanation
2. A chunk about a tracked ticker should be tracked_ticker even if it also has sector implications
3. Extract actual tickers mentioned — only tag tickers from the tracked list
4. Boilerplate (disclosures, disclaimers, page headers/footers) → irrelevant
5. Non-TMT sectors (healthcare, energy, industrials, consumer staples, real estate, automotive dealers, auto parts suppliers) → irrelevant
6. NEVER classify as irrelevant if the chunk announces or describes ANY of the following for a named company:
   - Earnings results, revenue/EPS beats or misses, impairments, write-downs, restatements
   - Guidance changes, preannouncements, mid-quarter revisions, major contract wins/losses
   - M&A transactions, acquisitions, divestitures, take-privates, mergers, spin-offs
   - CEO, CFO, or key business-unit leadership changes; board changes; activist situations
   - Bankruptcy, distress events, capital structure changes, restructurings
   - Antitrust investigations or actions, major litigation outcomes, regulatory approval/denial
   - Major product launches, product recalls, significant pricing changes in SaaS/platform businesses
   - Subscriber/user growth beats or misses, churn spikes, ARPU inflections (for streaming/SaaS/social)
   These are HIGH-ALERT events and must be routed as tracked_ticker (if a tracked ticker is named)
   or tmt_sector (if sector-level). Only mark irrelevant if the chunk is pure boilerplate/disclaimer.
7. PRIMARY SUBJECT RULE: Only populate "tickers" and set category=tracked_ticker if a tracked ticker
   is the PRIMARY SUBJECT of the chunk — i.e., the chunk is meaningfully about what that specific company
   did, announced, reported, or plans. If a tracked ticker appears only in passing (as a comparison,
   benchmark, or peer reference), do NOT tag it. If the main subject is a company NOT in the tracked list
   (e.g., Arista Networks, Tuhu, Trip.com, Via Transportation, Autonation), classify as tmt_sector and
   leave "tickers" empty — do not assign a tracked ticker just because one is mentioned nearby.{themes_section}"""


def _build_system_prompt(
    ticker_list: str = "",
    investment_themes: Optional[List[dict]] = None,
) -> str:
    """Build the classification system prompt with dynamic ticker list and investment themes."""
    tl = ticker_list or _DEFAULT_TICKER_LIST

    themes_section = ""
    if investment_themes:
        lines = "\n".join(
            f"  - {t['name']}: {', '.join(t.get('keywords', []))}"
            for t in investment_themes
            if t.get('keywords')
        )
        if lines:
            themes_section = (
                "\n\nInvestment themes being tracked by this analyst "
                "(bias toward tmt_sector or tracked_ticker for content directly relevant to these themes):\n"
                + lines
            )

    return _PROMPT_STATIC.format(ticker_list=tl, themes_section=themes_section)


def _build_user_prompt(chunk: Chunk, doc: Optional[Document] = None) -> str:
    """Build user prompt with chunk text and optional document context."""
    parts = []

    if doc:
        parts.append(f"Document: {doc.title}")
        if doc.analyst:
            parts.append(f"Analyst: {doc.analyst}")
        if doc.date_published:
            parts.append(f"Date: {doc.date_published}")
        parts.append("")

    if chunk.metadata:
        section = chunk.metadata.get('section')
        seg_type = chunk.metadata.get('segment_type')
        if section:
            parts.append(f"Section: {section}")
        if seg_type:
            parts.append(f"Segment type: {seg_type}")
        parts.append("")

    parts.append("Text to classify:")
    parts.append(chunk.text)

    return '\n'.join(parts)


# ------------------------------------------------------------------
# Classification Functions
# ------------------------------------------------------------------

def classify_chunk(
    chunk: Chunk,
    doc: Optional[Document] = None,
    system_prompt: Optional[str] = None,
    tracked_tickers: Optional[List[str]] = None,
) -> ChunkClassification:
    """Classify a single chunk via the configured classification model.

    Args:
        system_prompt: Pre-built system prompt (built once per batch call for efficiency).
                       If None, a default prompt is built from config values.
        tracked_tickers: Ticker whitelist for validation. Falls back to config.ALL_TICKERS.
    """
    prompt = system_prompt or _build_system_prompt()
    ticker_whitelist = set(tracked_tickers) if tracked_tickers else set(config.ALL_TICKERS)

    raw = llm_complete(
        "classification",
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": _build_user_prompt(chunk, doc)},
        ],
        temperature=0,
        max_tokens=200,
        json_mode=True,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}

    # Validate category
    category = data.get('category', 'irrelevant')
    if category not in CATEGORIES:
        category = 'irrelevant'

    # Validate tickers — only keep tickers from the user's tracked list
    raw_tickers = data.get('tickers', [])
    tickers = [t for t in raw_tickers if t in ticker_whitelist] if isinstance(raw_tickers, list) else []

    # If tickers found but category wasn't tracked_ticker, fix it
    if tickers and category != 'tracked_ticker':
        category = 'tracked_ticker'

    # If claimed tracked_ticker but no covered tickers after filtering, downgrade to tmt_sector
    if category == 'tracked_ticker' and not tickers:
        category = 'tmt_sector'

    # Validate tmt_subtopic
    tmt_subtopic = data.get('tmt_subtopic')
    if category == 'tmt_sector':
        if tmt_subtopic not in TMT_SUBTOPICS:
            tmt_subtopic = 'consumer_internet_media'  # safe default for TMT
    else:
        tmt_subtopic = None

    # Validate content_type and polarity
    content_type = data.get('content_type', 'fact')
    if content_type not in CONTENT_TYPES:
        content_type = 'fact'

    polarity = data.get('polarity', 'neutral')
    if polarity not in POLARITIES:
        polarity = 'neutral'

    return ChunkClassification(
        chunk_id=chunk.chunk_id,
        category=category,
        tickers=tickers,
        tmt_subtopic=tmt_subtopic,
        content_type=content_type,
        polarity=polarity,
    )


def classify_chunks(
    chunks: List[Chunk],
    doc: Optional[Document] = None,
    tracked_tickers: Optional[List[str]] = None,
    investment_themes: Optional[List[dict]] = None,
) -> List[ChunkClassification]:
    """Classify multiple chunks sequentially.

    Args:
        tracked_tickers: User's ticker list. Falls back to config.ALL_TICKERS if None.
        investment_themes: User's investment themes (name + keywords). Falls back to
                           config.INVESTMENT_THEMES if None. Injected into classifier prompt.
    """
    # Build prompt once per batch — includes user's tickers and themes
    tickers = tracked_tickers or list(config.ALL_TICKERS)
    themes = investment_themes or config.INVESTMENT_THEMES
    ticker_list_str = ', '.join(sorted(set(tickers)))
    system_prompt = _build_system_prompt(ticker_list_str, themes)

    results = []
    for i, chunk in enumerate(chunks):
        print(f"  Classifying chunk {i+1}/{len(chunks)}...", end='\r')
        classification = classify_chunk(chunk, doc, system_prompt=system_prompt, tracked_tickers=tickers)
        results.append(classification)

    print(f"  Classified {len(chunks)} chunks" + " " * 20)
    return results


def apply_classifications(
    chunks: List[Chunk],
    classifications: List[ChunkClassification],
) -> List[Chunk]:
    """Apply classifications to chunk metadata. Modifies in place."""
    for chunk, clf in zip(chunks, classifications):
        if chunk.metadata is None:
            chunk.metadata = {}
        chunk.metadata['classification'] = clf.to_dict()
    return chunks


def filter_irrelevant(
    chunks: List[Chunk],
    classifications: List[ChunkClassification],
) -> tuple:
    """
    Separate relevant from irrelevant chunks.

    Returns:
        (relevant_chunks, relevant_classifications, discarded_count)
    """
    relevant_chunks = []
    relevant_clfs = []
    discarded = 0

    for chunk, clf in zip(chunks, classifications):
        if clf.category == 'irrelevant':
            discarded += 1
        else:
            relevant_chunks.append(chunk)
            relevant_clfs.append(clf)

    return relevant_chunks, relevant_clfs, discarded


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    sample_chunks = [
        Chunk(
            chunk_id="test-1",
            doc_id="doc-1",
            chunk_index=0,
            text="""META PLATFORMS INC
Buy | Price Target: $750

INVESTMENT SUMMARY
We are raising our price target on META to $750 from $680 based on
accelerating AI monetization across the ad platform. Revenue growth
is tracking ahead of consensus with Reels monetization inflecting.""",
            page_start=1,
            page_end=1,
            metadata={'section': 'INVESTMENT SUMMARY', 'segment_type': 'paragraph'},
        ),
        Chunk(
            chunk_id="test-2",
            doc_id="doc-1",
            chunk_index=1,
            text="""Cloud infrastructure spending accelerated across all major hyperscalers
in Q4, with combined capex up 35% YoY. AWS, Azure, and GCP all reported
above-consensus growth, suggesting enterprise cloud migration is
re-accelerating after a digestion period.""",
            page_start=1,
            page_end=1,
            metadata={'section': 'Industry Trends', 'segment_type': 'paragraph'},
        ),
        Chunk(
            chunk_id="test-3",
            doc_id="doc-1",
            chunk_index=2,
            text="""The Federal Reserve held interest rates steady at 5.25-5.50% citing
persistent inflation concerns. New tariffs on Chinese semiconductor
imports could raise costs for US hardware OEMs. Consumer confidence
index fell to 98.7, the lowest since March 2024.""",
            page_start=2,
            page_end=2,
            metadata={'section': 'Macro Environment', 'segment_type': 'paragraph'},
        ),
        Chunk(
            chunk_id="test-4",
            doc_id="doc-1",
            chunk_index=3,
            text="""RISK FACTORS
Key risks include regulatory headwinds in the EU, potential TikTok
resurgence, and slower-than-expected AI capex returns. Additionally,
Apple's privacy changes could further impact ad measurement, though
META has largely adapted its systems.""",
            page_start=2,
            page_end=2,
            metadata={'section': 'RISK FACTORS', 'segment_type': 'paragraph'},
        ),
        Chunk(
            chunk_id="test-5",
            doc_id="doc-1",
            chunk_index=4,
            text="""DISCLOSURES
Jefferies LLC is a registered broker-dealer. This research report
is for informational purposes only. Past performance is not indicative
of future results.""",
            page_start=3,
            page_end=3,
            metadata={'section': 'DISCLOSURES', 'segment_type': 'paragraph'},
        ),
    ]

    sample_doc = Document(
        doc_id="doc-1",
        title="META Platforms: AI Monetization Inflection",
        analyst="Brent Thill",
        date_published="2026-01-25",
        source="jefferies",
    )

    print("=" * 60)
    print("Chunk Classification Test (4-Category System)")
    print("=" * 60)

    if is_configured('classification'):
        print("\nRunning live classification...\n")

        classifications = classify_chunks(sample_chunks, sample_doc)

        for chunk, clf in zip(sample_chunks, classifications):
            section = chunk.metadata.get('section', '—')
            print(f"\n[Chunk {chunk.chunk_index}] {section}")
            print(f"  Category: {clf.category}")
            if clf.tickers:
                print(f"  Tickers: {clf.tickers}")
            if clf.tmt_subtopic:
                print(f"  TMT Sub-topic: {clf.tmt_subtopic}")
            print(f"  Content: {clf.content_type} | Polarity: {clf.polarity}")

        # Apply and filter
        apply_classifications(sample_chunks, classifications)
        relevant, relevant_clfs, discarded = filter_irrelevant(sample_chunks, classifications)

        print("\n" + "=" * 60)
        print("Verification")
        print("=" * 60)

        assert all('classification' in c.metadata for c in sample_chunks)
        print("✓ Classifications applied to chunk metadata")

        # Check: META chunk should be tracked_ticker with META in tickers
        assert classifications[0].category == 'tracked_ticker'
        assert 'META' in classifications[0].tickers
        print("✓ META chunk → tracked_ticker with ticker tag")

        # Check: Cloud trends should be tmt_sector
        assert classifications[1].category == 'tmt_sector'
        assert classifications[1].tmt_subtopic in TMT_SUBTOPICS
        print(f"✓ Cloud chunk → tmt_sector / {classifications[1].tmt_subtopic}")

        # Check: Fed/tariffs chunk should be macro
        assert classifications[2].category == 'macro'
        print("✓ Fed/tariffs chunk → macro")

        # Check: Disclosures should be irrelevant
        assert classifications[4].category == 'irrelevant'
        print("✓ Disclosures → irrelevant")

        # Check: filter_irrelevant works
        assert discarded >= 1
        print(f"✓ Filtered out {discarded} irrelevant chunk(s), {len(relevant)} remaining")

    else:
        print("\nNo OPENAI_API_KEY found. Showing sample output structure:\n")

        samples = [
            ChunkClassification(
                chunk_id="test-1",
                category="tracked_ticker",
                tickers=["META"],
                content_type="forecast",
                polarity="positive",
            ),
            ChunkClassification(
                chunk_id="test-2",
                category="tmt_sector",
                tmt_subtopic="cloud_enterprise_software",
                content_type="fact",
                polarity="positive",
            ),
            ChunkClassification(
                chunk_id="test-3",
                category="macro",
                content_type="fact",
                polarity="negative",
            ),
            ChunkClassification(
                chunk_id="test-5",
                category="irrelevant",
                content_type="fact",
                polarity="neutral",
            ),
        ]

        for s in samples:
            print(json.dumps(s.to_dict(), indent=2))
            print()

        print("TMT Sub-topics:")
        for st in TMT_SUBTOPICS:
            print(f"  - {st}")

        print(f"\nTracked tickers ({len(config.ALL_TICKERS)}):")
        print(f"  {_DEFAULT_TICKER_LIST}")
