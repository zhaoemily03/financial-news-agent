#!/usr/bin/env python3
"""
End-to-End Pipeline Orchestrator
Runs: normalize → chunk → classify → triage → claim → tier → synthesis → briefing

Usage:
    python run_pipeline.py
"""

import os
import sys
import json
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional
from dotenv import load_dotenv

load_dotenv()

# Pipeline imports
from schemas import Document, Chunk, Claim
from jefferies_normalizer import JefferiesNormalizer
from chunker import chunk_document, estimate_tokens
from classifier import classify_chunks, ChunkClassification
from triage import triage_chunks, TriageResult
from claim_extractor import extract_claims, ClaimOutput
from tier_router import assign_tiers, TierAssignment
from tier2_synthesizer import synthesize_tier2, Tier2Synthesis
from implication_router import build_tier3_index, Tier3Index
from briefing_renderer import render_briefing, get_briefing_stats
from config import TRUSTED_ANALYSTS

# ------------------------------------------------------------------
# Pipeline Statistics Tracker
# ------------------------------------------------------------------

class PipelineStats:
    """Track reductions at each stage."""
    def __init__(self):
        self.stages = []
        self.start_time = datetime.now()

    def log(self, stage: str, input_count: int, output_count: int, details: str = ""):
        self.stages.append({
            "stage": stage,
            "input": input_count,
            "output": output_count,
            "reduction": f"{(1 - output_count/input_count)*100:.0f}%" if input_count > 0 else "N/A",
            "details": details,
        })

    def summary(self) -> str:
        lines = [
            "",
            "=" * 60,
            "PIPELINE REDUCTION SUMMARY",
            "=" * 60,
        ]
        for s in self.stages:
            reduction = s['reduction']
            details = f" ({s['details']})" if s['details'] else ""
            lines.append(f"  {s['stage']:<20} {s['input']:>4} → {s['output']:>4}  [{reduction}]{details}")

        elapsed = (datetime.now() - self.start_time).total_seconds()
        lines.append("")
        lines.append(f"  Total time: {elapsed:.1f}s")
        lines.append("=" * 60)
        return '\n'.join(lines)


# ------------------------------------------------------------------
# Sample Data (fallback if scraping fails)
# ------------------------------------------------------------------

SAMPLE_REPORTS = [
    {
        'title': 'META Platforms: AI Monetization Inflection — Raising PT to $750',
        'url': 'https://content.jefferies.com/report/sample-1',
        'pdf_url': 'https://links2.jefferies.com/doc/pdf/sample-1',
        'analyst': 'Brent Thill',
        'source': 'Jefferies',
        'date': date.today().strftime('%Y-%m-%d'),
        'content': """Brent Thill
Equity Analyst
""" + date.today().strftime('%B %d, %Y') + """

META PLATFORMS INC
Buy | Price Target: $750 (from $680)

INVESTMENT SUMMARY
We are raising our price target on META to $750 from $680 based on
accelerating AI monetization across the ad platform. Revenue growth
is tracking ahead of consensus with Reels monetization inflecting.

The company continues to benefit from improvements in ad targeting
powered by large language models, which have driven meaningful gains
in advertiser return on ad spend across both Facebook and Instagram.

Key Takeaways
- Ad revenue grew 28% YoY driven by improved Reels engagement
- AI-driven ad targeting improvements yielded 15% better ROAS
- Reality Labs losses narrowing faster than expected ($3.7B vs $4.1B expected)
- Threads MAU surpassed 300M, creating new ad inventory
- Management guided Q1 revenue above Street consensus

VALUATION
Our $750 PT is based on 28x our CY27 EPS estimate of $26.78,
roughly in line with the 5-year average forward P/E for large-cap
internet names. We see upside to our estimates if AI-driven
monetization continues to accelerate.

Revenue Model
We model total revenue of $210B in CY26, up from $170B in CY25.
Ad revenue comprises 97% of total, with Family of Apps margins
expanding to 52%.

RISK FACTORS
Key risks include:
- Regulatory headwinds in the EU (DSA compliance costs)
- Potential TikTok resurgence if ban reversed
- Slower-than-expected AI capex returns
- Apple privacy changes could further impact measurement

DISCLOSURES
Jefferies LLC is a registered broker-dealer.
""",
    },
    {
        'title': 'CRWD: Cybersecurity Leader Faces Emerging MSFT Threat',
        'url': 'https://content.jefferies.com/report/sample-2',
        'pdf_url': 'https://links2.jefferies.com/doc/pdf/sample-2',
        'analyst': 'Joseph Gallo',
        'source': 'Jefferies',
        'date': date.today().strftime('%Y-%m-%d'),
        'content': """Joseph Gallo
Equity Analyst
""" + date.today().strftime('%B %d, %Y') + """

CROWDSTRIKE HOLDINGS INC
Hold | Price Target: $380

CYBERSECURITY SECTOR UPDATE

INVESTMENT SUMMARY
Maintaining Hold rating on CRWD with $380 PT. While endpoint leadership
remains strong, we see emerging competitive pressure from Microsoft
Defender that may impact win rates in enterprise segment.

Breaking: Our channel checks indicate MSFT Defender gaining traction
in Fortune 500 accounts previously dominated by CRWD. This represents
a meaningful shift in competitive dynamics.

Key Observations
- CRWD maintaining 58% endpoint market share (down from 61% in Q3)
- MSFT Defender XDR bundle pricing 40% below CRWD Falcon
- Enterprise renewal rates stable at 97% but new logo wins slowing
- Zero trust architecture demand remains robust
- SIEM consolidation creating platform bundling pressure

FINANCIAL OUTLOOK
We forecast ARR growth of 25% in FY26, down from 33% in FY25.
Gross margins expected to remain above 75% on operating leverage.

CRWD continues to invest heavily in platform expansion:
- Falcon SIEM GA expected Q2
- Identity protection suite gaining traction
- Cloud security workloads growing 45% YoY

RISK FACTORS
- Microsoft bundling may accelerate share loss
- Macroeconomic slowdown could delay enterprise IT spending
- Execution risk on SIEM integration

Cybersecurity spending outlook remains positive:
- Zero trust adoption accelerating post-breach incidents
- Regulatory requirements (SEC cyber disclosure) driving demand
- AI-powered threat detection becoming table stakes

DISCLOSURES
Jefferies LLC is a registered broker-dealer.
""",
    },
    {
        'title': 'GOOGL: Cloud Momentum Continues — AI Workloads Driving Growth',
        'url': 'https://content.jefferies.com/report/sample-3',
        'pdf_url': 'https://links2.jefferies.com/doc/pdf/sample-3',
        'analyst': 'Brent Thill',
        'source': 'Jefferies',
        'date': date.today().strftime('%Y-%m-%d'),
        'content': """Brent Thill
Equity Analyst
""" + date.today().strftime('%B %d, %Y') + """

ALPHABET INC
Buy | Price Target: $210

GOOGLE CLOUD PLATFORM UPDATE

INVESTMENT SUMMARY
Reiterating Buy on GOOGL with $210 PT. Google Cloud continues to
outperform, driven by enterprise AI workload migration and Gemini
adoption. Search remains resilient despite AI overhang concerns.

Key Points
- Cloud revenue grew 28% YoY to $11.4B in Q4
- GCP now represents 11% of total revenue (up from 9% YoY)
- AI/ML workloads represent 35% of new cloud deals (up from 20%)
- YouTube Premium subscribers crossed 100M milestone
- Search advertising showing resilience: +14% YoY

Upcoming Catalyst: Earnings February 4
We expect Q4 results to beat consensus on cloud strength:
- Consensus cloud revenue: $10.8B; our estimate: $11.4B
- Potential for operating margin expansion guidance

AI INFRASTRUCTURE
GOOGL continues aggressive AI infrastructure buildout:
- TPU v5p availability expanded to additional regions
- Gemini 2.0 API adoption exceeding internal projections
- Enterprise AI search integrations launching Q1

VALUATION
Trading at 22x CY26 EPS of $9.50. We see multiple expansion
potential if cloud margins improve and AI monetization scales.

RISKS
- Regulatory overhang (DOJ antitrust remedies)
- AI search disruption if ChatGPT/Perplexity gain share
- Cloud pricing pressure from AWS/Azure

DISCLOSURES
Jefferies LLC is a registered broker-dealer.
""",
    },
]


# ------------------------------------------------------------------
# Pipeline Stages
# ------------------------------------------------------------------

def stage_1_collect(stats: PipelineStats) -> List[Dict]:
    """Stage 1: Collect reports (try scraping, fallback to sample)."""
    print("\n" + "=" * 60)
    print("[1/8] COLLECT — Fetching Jefferies Reports")
    print("=" * 60)

    reports = []

    # Try live scraping first
    try:
        from jefferies_scraper import JefferiesScraper
        scraper = JefferiesScraper(headless=True)
        analysts = TRUSTED_ANALYSTS.get('jefferies', [])

        print(f"  Attempting to scrape reports from: {', '.join(analysts)}")
        reports = scraper.get_reports_by_analysts(analysts, max_per_analyst=5, days=5)

        if reports:
            print(f"  ✓ Scraped {len(reports)} reports from Jefferies")
    except Exception as e:
        print(f"  ⚠ Scraping failed: {e}")

    # Fallback to sample data
    if not reports:
        print("  → Using sample reports for pipeline demonstration")
        reports = SAMPLE_REPORTS

    stats.log("collect", len(reports), len(reports), f"{len(reports)} reports")
    return reports


def stage_2_normalize(reports: List[Dict], stats: PipelineStats) -> List[Tuple[Document, List[Chunk]]]:
    """Stage 2: Normalize — raw content to Document + page-level Chunks."""
    print("\n" + "=" * 60)
    print("[2/8] NORMALIZE — PDF/Text → Documents + Page Chunks")
    print("=" * 60)

    normalizer = JefferiesNormalizer()
    results = []
    total_pages = 0

    for i, report in enumerate(reports, 1):
        print(f"  [{i}/{len(reports)}] {report['title'][:50]}...")

        # Use text content (sample data) or would use PDF bytes for real PDFs
        doc, chunks = normalizer.normalize_text(report['content'], report)
        results.append((doc, chunks))
        total_pages += len(chunks)
        print(f"       → {len(chunks)} page chunks")

    stats.log("normalize", len(reports), len(results), f"{total_pages} total page chunks")
    print(f"\n  ✓ Normalized {len(results)} documents into {total_pages} page chunks")
    return results


def stage_3_chunk(normalized: List[Tuple[Document, List[Chunk]]], stats: PipelineStats) -> List[Tuple[Document, List[Chunk]]]:
    """Stage 3: Chunk — page-level to atomic chunks (150-400 tokens)."""
    print("\n" + "=" * 60)
    print("[3/8] CHUNK — Page Chunks → Atomic Chunks (150-400 tok)")
    print("=" * 60)

    results = []
    total_input = sum(len(chunks) for _, chunks in normalized)
    total_output = 0

    for doc, page_chunks in normalized:
        atomic_chunks = chunk_document(doc, page_chunks)
        results.append((doc, atomic_chunks))
        total_output += len(atomic_chunks)
        print(f"  {doc.title[:40]}... → {len(page_chunks)} pages → {len(atomic_chunks)} chunks")

    stats.log("chunk", total_input, total_output, "atomic segmentation")
    print(f"\n  ✓ Split into {total_output} atomic chunks")
    return results


def stage_4_classify(chunked: List[Tuple[Document, List[Chunk]]], stats: PipelineStats) -> List[Tuple[Document, List[Chunk], List[ChunkClassification]]]:
    """Stage 4: Classify — tag each chunk with topic, ticker, content type."""
    print("\n" + "=" * 60)
    print("[4/8] CLASSIFY — LLM Tagging (topic, ticker, type)")
    print("=" * 60)

    from openai import OpenAI
    client = OpenAI()

    results = []
    total_chunks = sum(len(chunks) for _, chunks in chunked)

    for doc, chunks in chunked:
        print(f"  Classifying {len(chunks)} chunks from: {doc.title[:40]}...")
        classifications = classify_chunks(chunks, doc, client)
        results.append((doc, chunks, classifications))

    stats.log("classify", total_chunks, total_chunks, "LLM classification")
    print(f"\n  ✓ Classified {total_chunks} chunks")
    return results


def stage_5_triage(classified: List[Tuple[Document, List[Chunk], List[ChunkClassification]]], stats: PipelineStats) -> Tuple[List[Chunk], List[ChunkClassification], List[Document]]:
    """Stage 5: Triage — aggressive filtering for <5 page constraint."""
    print("\n" + "=" * 60)
    print("[5/8] TRIAGE — Aggressive Filtering (relevance, novelty, dedup)")
    print("=" * 60)

    # Flatten all chunks and classifications
    all_chunks = []
    all_classifications = []
    all_docs = []

    for doc, chunks, clfs in classified:
        all_chunks.extend(chunks)
        all_classifications.extend(clfs)
        all_docs.extend([doc] * len(chunks))

    total_input = len(all_chunks)
    print(f"  Input: {total_input} chunks")

    # Run triage
    result = triage_chunks(all_chunks, all_classifications, source='jefferies')

    print(f"\n{result.summary()}")

    # Extract surviving chunks and classifications
    kept_chunks = [c for c, _, _ in result.kept]
    kept_clfs = [clf for _, clf, _ in result.kept]

    # Map chunks back to their documents
    chunk_to_doc = {c.chunk_id: d for c, d in zip(all_chunks, all_docs)}
    kept_docs = [chunk_to_doc.get(c.chunk_id, all_docs[0]) for c in kept_chunks]

    stats.log("triage", total_input, len(kept_chunks),
              f"dropped {len(result.dropped)} ({result.drop_rate:.0%})")
    print(f"\n  ✓ Triaged: {total_input} → {len(kept_chunks)} chunks")
    return kept_chunks, kept_clfs, kept_docs


def stage_6_claims(chunks: List[Chunk], classifications: List[ChunkClassification], docs: List[Document], stats: PipelineStats) -> List[ClaimOutput]:
    """Stage 6: Claim Extraction — atomic claims with judgment hooks."""
    print("\n" + "=" * 60)
    print("[6/8] CLAIMS — Extract Atomic Claims + Judgment Hooks")
    print("=" * 60)

    from openai import OpenAI
    client = OpenAI()

    claims = []

    # Group chunks by doc for proper citation
    doc_chunks = {}
    for chunk, clf, doc in zip(chunks, classifications, docs):
        if doc.doc_id not in doc_chunks:
            doc_chunks[doc.doc_id] = {"doc": doc, "chunks": [], "clfs": []}
        doc_chunks[doc.doc_id]["chunks"].append(chunk)
        doc_chunks[doc.doc_id]["clfs"].append(clf)

    for doc_id, data in doc_chunks.items():
        print(f"  Extracting claims from: {data['doc'].title[:40]}...")
        doc_claims = extract_claims(data["chunks"], data["clfs"], data["doc"], client)
        claims.extend(doc_claims)

    total_bullets = sum(len(c.bullets) for c in claims)
    stats.log("claims", len(chunks), len(claims), f"{total_bullets} total bullets")
    print(f"\n  ✓ Extracted {len(claims)} claims ({total_bullets} bullets)")
    return claims


def stage_7_tier_route(claims: List[ClaimOutput], stats: PipelineStats) -> TierAssignment:
    """Stage 7: Tier Routing — rule-based assignment to Tier 1/2/3."""
    print("\n" + "=" * 60)
    print("[7/8] TIER ROUTING — Rule-Based (Tier 1/2/3)")
    print("=" * 60)

    assignment = assign_tiers(claims)

    print(f"  Tier 1 (Attention): {len(assignment.tier_1)} claims")
    print(f"  Tier 2 (Synthesis): {len(assignment.tier_2)} claims")
    print(f"  Tier 3 (Reference): {len(assignment.tier_3)} claims")

    stats.log("tier_route", len(claims), len(claims), assignment.summary())
    print(f"\n  ✓ Routed: {assignment.summary()}")
    return assignment


def stage_8_synthesize_and_render(assignment: TierAssignment, stats: PipelineStats) -> str:
    """Stage 8: Synthesis + Briefing Render — final <5 page output."""
    print("\n" + "=" * 60)
    print("[8/8] SYNTHESIS + RENDER — <5 Page Briefing")
    print("=" * 60)

    # Tier 2 Synthesis
    print("  Synthesizing Tier 2 patterns...")
    tier2_synthesis = synthesize_tier2(assignment.tier_2)
    print(f"    Agreements: {len(tier2_synthesis.agreements)}")
    print(f"    Disagreements: {len(tier2_synthesis.disagreements)}")
    print(f"    Deltas: {len(tier2_synthesis.deltas)}")

    # Tier 3 Index
    print("  Building Tier 3 index...")
    tier3_index = build_tier3_index(assignment.tier_3)
    print(f"    Tickers indexed: {len(tier3_index.by_ticker)}")
    print(f"    Themes indexed: {len(tier3_index.by_theme)}")

    # Render briefing
    print("  Rendering final briefing...")
    briefing = render_briefing(
        assignment,
        tier2_synthesis,
        tier3_index,
        briefing_date=date.today(),
    )

    # Stats
    briefing_stats = get_briefing_stats(briefing, assignment, tier3_index)

    stats.log("render", assignment.total_claims(), 1,
              f"{briefing_stats.word_count} words, {briefing_stats.page_estimate} pages")

    print(f"\n  ✓ Briefing rendered: {briefing_stats.word_count} words (~{briefing_stats.page_estimate} pages)")
    if briefing_stats.truncated:
        print("    ⚠ Some content truncated to meet <5 page constraint")

    return briefing


# ------------------------------------------------------------------
# Main Pipeline
# ------------------------------------------------------------------

def run_pipeline():
    """Execute full end-to-end pipeline."""
    print("\n" + "=" * 60)
    print("  FINANCIAL NEWS AGENT — End-to-End Pipeline")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    stats = PipelineStats()

    # Stage 1: Collect
    reports = stage_1_collect(stats)
    if not reports:
        print("\n✗ No reports to process. Exiting.")
        return None

    # Stage 2: Normalize
    normalized = stage_2_normalize(reports, stats)

    # Stage 3: Chunk
    chunked = stage_3_chunk(normalized, stats)

    # Stage 4: Classify
    classified = stage_4_classify(chunked, stats)

    # Stage 5: Triage
    kept_chunks, kept_clfs, kept_docs = stage_5_triage(classified, stats)

    if not kept_chunks:
        print("\n✗ All chunks triaged out. No content for briefing.")
        return None

    # Stage 6: Claims
    claims = stage_6_claims(kept_chunks, kept_clfs, kept_docs, stats)

    # Stage 7: Tier Routing
    assignment = stage_7_tier_route(claims, stats)

    # Stage 8: Synthesis + Render
    briefing = stage_8_synthesize_and_render(assignment, stats)

    # Print summary
    print(stats.summary())

    # Save briefing
    os.makedirs('data/briefings', exist_ok=True)
    date_stamp = datetime.now().strftime('%Y-%m-%d_%H%M')

    md_path = f'data/briefings/briefing_{date_stamp}.md'
    with open(md_path, 'w') as f:
        f.write(briefing)
    print(f"\n✓ Briefing saved: {md_path}")

    # Print briefing
    print("\n" + "=" * 60)
    print("DAILY BRIEFING OUTPUT")
    print("=" * 60)
    print(briefing)

    return briefing


if __name__ == "__main__":
    run_pipeline()
