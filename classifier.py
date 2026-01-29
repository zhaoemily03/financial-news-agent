"""
Lightweight chunk classification — describe, don't decide.
Uses GPT-3.5-turbo for cheap, JSON-only output.
No summarization. No relevance scoring.

Classification fields:
- topic: TMT-aware taxonomy
- asset_exposure: tickers mentioned
- content_type: fact | interpretation | forecast | risk
- time_horizon: near_term | medium_term | long_term | unspecified
- polarity: positive | negative | neutral | mixed
- novelty: new | incremental | rehash

Usage:
    from classifier import classify_chunk, classify_chunks

    classification = classify_chunk(chunk, doc)
    # or batch:
    classifications = classify_chunks(chunks, doc)
"""

import json
import os
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

from schemas import Chunk, Document

# ------------------------------------------------------------------
# TMT Topic Taxonomy
# ------------------------------------------------------------------

TMT_TOPICS = {
    'technology': [
        'ai_ml',           # AI, machine learning, LLMs, generative AI
        'cloud',           # Cloud computing, IaaS, PaaS
        'software',        # Enterprise software, SaaS, applications
        'infrastructure',  # Data centers, servers, networking
        'semiconductors',  # Chips, processors, GPU
        'hardware',        # Devices, consumer electronics
    ],
    'media': [
        'advertising',     # Digital ads, ad tech, programmatic
        'content',         # Streaming, video, music, publishing
        'gaming',          # Video games, esports, virtual worlds
        'social',          # Social networks, messaging, community
    ],
    'telecom': [
        'networks',        # 5G, wireless, broadband
        'telecom_infra',   # Towers, fiber, spectrum
    ],
    'other': [
        'ecommerce',       # Online retail, marketplaces
        'fintech',         # Payments, digital finance
        'cybersecurity',   # Security software, threat protection
        'general',         # Doesn't fit specific category
    ],
}

# Flat list for validation
ALL_TOPICS = [t for cats in TMT_TOPICS.values() for t in cats]

# ------------------------------------------------------------------
# Classification Schema
# ------------------------------------------------------------------

CONTENT_TYPES = ['fact', 'interpretation', 'forecast', 'risk']
TIME_HORIZONS = ['near_term', 'medium_term', 'long_term', 'unspecified']
POLARITIES = ['positive', 'negative', 'neutral', 'mixed']
NOVELTY_LEVELS = ['new', 'incremental', 'rehash']


@dataclass
class ChunkClassification:
    """Classification metadata for a chunk."""
    chunk_id: str = ""
    topic: str = "general"                    # from TMT_TOPICS
    topic_secondary: Optional[str] = None     # optional second topic
    asset_exposure: List[str] = field(default_factory=list)  # tickers mentioned
    content_type: str = "fact"                # fact|interpretation|forecast|risk
    time_horizon: str = "unspecified"         # near_term|medium_term|long_term|unspecified
    polarity: str = "neutral"                 # positive|negative|neutral|mixed
    novelty: str = "incremental"              # new|incremental|rehash

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ChunkClassification":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ------------------------------------------------------------------
# Classification Prompt
# ------------------------------------------------------------------

SYSTEM_PROMPT = """You are a financial document classifier. Classify the given text chunk.

Output ONLY valid JSON with these fields:
- topic: primary topic (one of: ai_ml, cloud, software, infrastructure, semiconductors, hardware, advertising, content, gaming, social, networks, telecom_infra, ecommerce, fintech, cybersecurity, general)
- topic_secondary: optional second topic if chunk spans two areas, else null
- asset_exposure: array of stock tickers mentioned (e.g., ["META", "GOOGL"]), empty if none
- content_type: one of (fact, interpretation, forecast, risk)
  - fact: verifiable data points, metrics, historical events
  - interpretation: analyst opinions, assessments, explanations
  - forecast: predictions about future performance
  - risk: potential negative factors, concerns, warnings
- time_horizon: one of (near_term, medium_term, long_term, unspecified)
  - near_term: <6 months or current quarter
  - medium_term: 6-18 months
  - long_term: >18 months
  - unspecified: no clear timeframe
- polarity: one of (positive, negative, neutral, mixed)
  - positive: bullish, upbeat, favorable
  - negative: bearish, concerning, unfavorable
  - neutral: balanced, factual without sentiment
  - mixed: contains both positive and negative elements
- novelty: one of (new, incremental, rehash)
  - new: introduces fresh information, thesis, or perspective
  - incremental: updates or extends known information
  - rehash: restates widely known information

Rules:
1. Output ONLY the JSON object, no markdown, no explanation
2. Do not summarize or interpret beyond classification
3. Extract actual tickers mentioned, don't infer related companies
4. Be conservative: when uncertain, use neutral/unspecified/general"""


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

    # Include section context from chunk metadata
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
    client: Optional[OpenAI] = None,
) -> ChunkClassification:
    """
    Classify a single chunk using GPT-3.5-turbo.

    Args:
        chunk: Chunk to classify
        doc: Optional parent Document for context
        client: Optional OpenAI client (creates one if not provided)

    Returns:
        ChunkClassification with all fields populated
    """
    if client is None:
        client = OpenAI()

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(chunk, doc)},
        ],
        temperature=0,  # deterministic
        max_tokens=200,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback to defaults on parse failure
        data = {}

    # Validate and normalize
    classification = ChunkClassification(
        chunk_id=chunk.chunk_id,
        topic=data.get('topic', 'general') if data.get('topic') in ALL_TOPICS else 'general',
        topic_secondary=data.get('topic_secondary') if data.get('topic_secondary') in ALL_TOPICS else None,
        asset_exposure=data.get('asset_exposure', []) if isinstance(data.get('asset_exposure'), list) else [],
        content_type=data.get('content_type', 'fact') if data.get('content_type') in CONTENT_TYPES else 'fact',
        time_horizon=data.get('time_horizon', 'unspecified') if data.get('time_horizon') in TIME_HORIZONS else 'unspecified',
        polarity=data.get('polarity', 'neutral') if data.get('polarity') in POLARITIES else 'neutral',
        novelty=data.get('novelty', 'incremental') if data.get('novelty') in NOVELTY_LEVELS else 'incremental',
    )

    return classification


def classify_chunks(
    chunks: List[Chunk],
    doc: Optional[Document] = None,
    client: Optional[OpenAI] = None,
) -> List[ChunkClassification]:
    """
    Classify multiple chunks sequentially.

    Args:
        chunks: List of Chunks to classify
        doc: Optional parent Document for context
        client: Optional OpenAI client (reused across calls)

    Returns:
        List of ChunkClassification objects, same order as input
    """
    if client is None:
        client = OpenAI()

    results = []
    for i, chunk in enumerate(chunks):
        print(f"  Classifying chunk {i+1}/{len(chunks)}...", end='\r')
        classification = classify_chunk(chunk, doc, client)
        results.append(classification)

    print(f"  Classified {len(chunks)} chunks" + " " * 20)
    return results


def apply_classifications(
    chunks: List[Chunk],
    classifications: List[ChunkClassification],
) -> List[Chunk]:
    """
    Apply classifications to chunk metadata.

    Modifies chunks in place and returns them for chaining.
    """
    for chunk, clf in zip(chunks, classifications):
        if chunk.metadata is None:
            chunk.metadata = {}
        chunk.metadata['classification'] = clf.to_dict()
    return chunks


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    # Test with sample chunks (no API call in dry-run mode)

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
            text="""Key Takeaways
- Ad revenue grew 28% YoY driven by improved Reels engagement
- AI-driven ad targeting improvements yielded 15% better ROAS
- Reality Labs losses narrowing faster than expected
- Threads MAU surpassed 300M, creating new ad inventory""",
            page_start=1,
            page_end=1,
            metadata={'section': 'Key Takeaways', 'segment_type': 'bullet'},
        ),
        Chunk(
            chunk_id="test-3",
            doc_id="doc-1",
            chunk_index=2,
            text="""RISK FACTORS
Key risks include regulatory headwinds in the EU, potential TikTok
resurgence, and slower-than-expected AI capex returns. Additionally,
Apple's privacy changes could further impact ad measurement, though
META has largely adapted its systems.""",
            page_start=2,
            page_end=2,
            metadata={'section': 'RISK FACTORS', 'segment_type': 'paragraph'},
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
    print("Chunk Classification Test")
    print("=" * 60)

    # Check if we have API key
    if os.getenv('OPENAI_API_KEY'):
        print("\nRunning live classification with GPT-3.5-turbo...\n")

        classifications = classify_chunks(sample_chunks, sample_doc)

        for chunk, clf in zip(sample_chunks, classifications):
            print(f"\n[Chunk {chunk.chunk_index}] {chunk.metadata.get('section', '—')}")
            print(f"  Topic: {clf.topic}" + (f" / {clf.topic_secondary}" if clf.topic_secondary else ""))
            print(f"  Assets: {clf.asset_exposure}")
            print(f"  Type: {clf.content_type} | Horizon: {clf.time_horizon}")
            print(f"  Polarity: {clf.polarity} | Novelty: {clf.novelty}")

        # Apply to chunks and verify
        apply_classifications(sample_chunks, classifications)
        print("\n" + "=" * 60)
        print("Verification")
        print("=" * 60)

        assert all('classification' in c.metadata for c in sample_chunks)
        print("✓ Classifications applied to chunk metadata")

        assert all(clf.chunk_id == chunk.chunk_id for clf, chunk in zip(classifications, sample_chunks))
        print("✓ Chunk IDs match")

        # Check expected classifications
        assert classifications[0].topic in ['advertising', 'social', 'ai_ml']
        assert 'META' in classifications[0].asset_exposure
        print("✓ Topic and asset detection working")

        assert classifications[2].content_type == 'risk'
        print("✓ Risk content type detected correctly")

    else:
        print("\nNo OPENAI_API_KEY found. Showing sample output structure:\n")

        sample_clf = ChunkClassification(
            chunk_id="test-1",
            topic="advertising",
            topic_secondary="ai_ml",
            asset_exposure=["META"],
            content_type="forecast",
            time_horizon="medium_term",
            polarity="positive",
            novelty="new",
        )

        print("Sample classification output:")
        print(json.dumps(sample_clf.to_dict(), indent=2))

        print("\nTMT Topic Taxonomy:")
        for category, topics in TMT_TOPICS.items():
            print(f"  {category}: {', '.join(topics)}")
