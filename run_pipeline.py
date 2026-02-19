#!/usr/bin/env python3
"""
End-to-End Pipeline Orchestrator (V3)
Collect → Normalize → Pre-filter → Chunk → Classify+Filter → Claims+Cap → File → Drift → Synthesize → Render

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
from normalizer import DocumentNormalizer
from chunker import chunk_document, estimate_tokens
from classifier import classify_chunks, filter_irrelevant, ChunkClassification
from claim_extractor import extract_claims, sort_claims_by_priority, ClaimOutput
from tier2_synthesizer import synthesize_section2, Section2Synthesis
from briefing_renderer import render_briefing, count_words, count_pages
from config import TRUSTED_ANALYSTS, ALL_TICKERS, MACRO_NEWS, SOURCES

# Sentiment Drift Detection
from claim_tracker import ClaimTracker
from drift_detector import detect_drift, DriftReport
from config import DRIFT_DETECTION

# Dedup trackers
from report_tracker import ReportTracker
from podcast_tracker import PodcastTracker

# ------------------------------------------------------------------
# Dedup Reset (ensures repeat runs reprocess all today's content)
# ------------------------------------------------------------------

def _reset_today_dedup():
    """
    Clear today's processed entries from report and podcast trackers.
    Ensures every pipeline run reprocesses all content within
    the BRIEFING_DAYS window.
    """
    today = datetime.now().strftime('%Y-%m-%d')
    cleared = 0

    # Reset report tracker
    try:
        import sqlite3
        db_path = 'data/processed_content.db'
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM processed_reports WHERE date(processed_date) = ?",
                (today,)
            )
            cleared += cursor.rowcount
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"  ⚠ Could not reset report tracker: {e}")

    # Reset podcast tracker
    try:
        import sqlite3
        db_path = 'data/podcasts.db'
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM processed_episodes WHERE date(processed_date) = ?",
                (today,)
            )
            cleared += cursor.rowcount
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"  ⚠ Could not reset podcast tracker: {e}")

    if cleared:
        print(f"  ✓ Cleared {cleared} dedup entries from today (will reprocess all content)")
    else:
        print(f"  ✓ No prior dedup entries for today")


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

def stage_1_collect(stats: PipelineStats) -> Tuple[List[Dict], List[str]]:
    """Stage 1: Collect reports from portals + podcasts (fallback to sample)."""
    print("\n" + "=" * 60)
    print("[1/7] COLLECT — Fetching Reports from Portals + Podcasts")
    print("=" * 60)

    reports = []
    source_failures = []

    # 1a: Collect from sell-side portals via registry
    try:
        from portal_registry import registry

        enabled = registry.list_enabled()
        print(f"  Enabled portals: {', '.join(enabled) if enabled else 'none'}")

        if enabled:
            result = registry.collect_all(days=2, max_per_portal=25, headless=True)
            reports = result.get('reports', [])
            source_failures = result.get('failures', [])

            if reports:
                print(f"  ✓ Collected {len(reports)} reports from {len(enabled)} portal(s)")

            auth_failures = [f for f in source_failures if 'auth' in f.lower()]
            other_failures = [f for f in source_failures if 'auth' not in f.lower()]

            if auth_failures:
                print("\n  " + "!" * 50)
                print("  AUTHENTICATION REQUIRED:")
                for f in auth_failures:
                    print(f"    - {f}")
                print("  Run the scraper manually to re-authenticate.")
                print("  " + "!" * 50)

            if other_failures:
                print(f"  ⚠ Other failures: {len(other_failures)}")
                for f in other_failures:
                    print(f"    - {f}")
        else:
            print("  ⚠ No portals enabled in config")

    except Exception as e:
        print(f"  ⚠ Portal collection failed: {e}")
        source_failures.append(f"Registry (error: {str(e)[:50]})")

    # 1b: Collect from podcasts via podcast registry
    try:
        from podcast_registry import podcast_registry

        enabled_podcasts = podcast_registry.list_enabled()
        if enabled_podcasts:
            print(f"\n  Enabled podcasts: {', '.join(enabled_podcasts)}")
            result = podcast_registry.collect_all(days=7, max_per_podcast=2)
            episodes = result.get('episodes', [])
            podcast_failures = result.get('failures', [])

            if episodes:
                reports.extend(episodes)
                print(f"  ✓ Collected {len(episodes)} episode(s) from {len(enabled_podcasts)} podcast(s)")
            if podcast_failures:
                source_failures.extend(podcast_failures)
                print(f"  ⚠ Podcast failures: {len(podcast_failures)}")
        else:
            print("  Podcasts: disabled in config")

    except ImportError:
        print("  Podcasts: module not available")
    except Exception as e:
        print(f"  ⚠ Podcast collection failed: {e}")
        source_failures.append(f"Podcasts (error: {str(e)[:50]})")

    # 1c: Collect macro news via RSS
    if MACRO_NEWS.get('enabled', False):
        try:
            from macro_news import collect_macro_news

            print(f"\n  Collecting macro news...")
            macro_reports = collect_macro_news(
                max_articles=MACRO_NEWS.get('max_articles', 6),
                days=MACRO_NEWS.get('days_lookback', 1),
            )
            if macro_reports:
                reports.extend(macro_reports)
                print(f"  ✓ Collected {len(macro_reports)} macro news article(s)")
            else:
                print("  ⚠ No macro news articles found")

        except ImportError:
            print("  Macro news: module not available")
        except Exception as e:
            print(f"  ⚠ Macro news collection failed: {e}")
            source_failures.append(f"Macro news (error: {str(e)[:50]})")
    else:
        print("  Macro news: disabled in config")

    # 1d: Collect from Substack via Feishu Mail
    substack_config = SOURCES.get('substack', {})
    if substack_config.get('enabled', False):
        try:
            from substack_feishu import collect_substack

            print(f"\n  Collecting Substack newsletters...")
            substack_reports = collect_substack(
                days=substack_config.get('days_lookback', 5),
            )
            if substack_reports:
                reports.extend(substack_reports)
                print(f"  ✓ Collected {len(substack_reports)} Substack article(s)")
            else:
                print("  ⚠ No Substack articles found")

        except ImportError:
            print("  Substack: module not available")
        except Exception as e:
            print(f"  ⚠ Substack collection failed: {e}")
            source_failures.append(f"Substack (error: {str(e)[:50]})")
    else:
        print("  Substack: disabled in config")

    # Summary
    print("\n  --- Collection Summary ---")
    if reports:
        by_source = {}
        for r in reports:
            src = r.get('source', 'Unknown')
            by_source[src] = by_source.get(src, 0) + 1
        for src, count in by_source.items():
            print(f"    {src}: {count} reports")
    else:
        print("    No reports collected from any source")

    if source_failures:
        print(f"    Failed sources: {len(source_failures)}")

    # Fallback to sample data
    if not reports:
        if source_failures:
            print("\n  ⚠ ALL DATA SOURCES FAILED - using sample data for demonstration")
        else:
            print("  → Using sample reports for pipeline demonstration")
        reports = SAMPLE_REPORTS

    stats.log("collect", len(reports), len(reports), f"{len(reports)} reports")
    return reports, source_failures


def stage_2_normalize(reports: List[Dict], stats: PipelineStats) -> List[Tuple[Document, List[Chunk]]]:
    """Stage 2: Normalize — raw content to Document + page-level Chunks."""
    print("\n" + "=" * 60)
    print("[2/7] NORMALIZE — PDF/Text → Documents + Page Chunks")
    print("=" * 60)

    normalizer = DocumentNormalizer()
    results = []
    total_pages = 0

    for i, report in enumerate(reports, 1):
        print(f"  [{i}/{len(reports)}] {report['title'][:50]}...")
        doc, chunks = normalizer.normalize_text(report['content'], report)
        results.append((doc, chunks))
        total_pages += len(chunks)
        print(f"       → {len(chunks)} page chunks")

    stats.log("normalize", len(reports), len(results), f"{total_pages} total page chunks")
    print(f"\n  ✓ Normalized {len(results)} documents into {total_pages} page chunks")
    return results


# ------------------------------------------------------------------
# TMT Pre-filter (deterministic, before LLM classification)
# ------------------------------------------------------------------

TMT_PREFILTER_KEYWORDS = [
    'AI', 'artificial intelligence', 'cloud', 'SaaS', 'cybersecurity',
    'ad revenue', 'advertising', 'streaming', 'semiconductor', 'LLM',
    'data center', 'machine learning', 'software', 'digital', 'tech',
    'internet', 'social media', 'e-commerce', 'ecommerce',
    'gaming', 'fintech', 'payments', 'zero trust', 'endpoint',
]

PASSTHROUGH_SOURCES = {'podcast', 'macro_news', 'substack'}


def stage_2b_prefilter(
    normalized: List[Tuple[Document, List[Chunk]]],
    stats: PipelineStats,
) -> List[Tuple[Document, List[Chunk]]]:
    """Stage 2b: Pre-filter — drop non-TMT docs before LLM classification."""
    print("\n" + "=" * 60)
    print("[2b] PRE-FILTER — Drop Non-TMT Documents (deterministic)")
    print("=" * 60)

    kept = []
    dropped = []
    ticker_set = {t.upper() for t in ALL_TICKERS}

    for doc, chunks in normalized:
        source_type = getattr(doc, 'source_type', '') or ''
        source = getattr(doc, 'source', '') or ''
        if source_type in PASSTHROUGH_SOURCES or source in PASSTHROUGH_SOURCES:
            kept.append((doc, chunks))
            continue

        text_to_scan = doc.title or ''
        for c in chunks[:2]:
            text_to_scan += ' ' + (c.text or '')[:500]
        text_to_scan_upper = text_to_scan.upper()
        text_to_scan_lower = text_to_scan.lower()

        has_ticker = any(f' {t} ' in f' {text_to_scan_upper} ' or
                         f'({t})' in text_to_scan_upper or
                         text_to_scan_upper.startswith(f'{t} ') or
                         text_to_scan_upper.startswith(f'{t}:')
                         for t in ticker_set)

        has_tmt_keyword = any(kw.lower() in text_to_scan_lower for kw in TMT_PREFILTER_KEYWORDS)

        if has_ticker or has_tmt_keyword:
            kept.append((doc, chunks))
        else:
            dropped.append(doc.title)
            print(f"  ✗ Dropped: {doc.title[:60]}")

    stats.log("prefilter", len(normalized), len(kept),
              f"dropped {len(dropped)} non-TMT docs")

    if dropped:
        print(f"\n  ✓ Pre-filtered: {len(normalized)} → {len(kept)} documents ({len(dropped)} dropped)")
    else:
        print(f"\n  ✓ All {len(kept)} documents pass TMT pre-filter")

    return kept


def stage_3_chunk(normalized: List[Tuple[Document, List[Chunk]]], stats: PipelineStats) -> List[Tuple[Document, List[Chunk]]]:
    """Stage 3: Chunk — page-level to atomic chunks (150-400 tokens)."""
    print("\n" + "=" * 60)
    print("[3/7] CHUNK — Page Chunks → Atomic Chunks (150-400 tok)")
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


def stage_4_classify_and_filter(
    chunked: List[Tuple[Document, List[Chunk]]],
    stats: PipelineStats,
) -> List[Tuple[Document, List[Chunk], List[ChunkClassification]]]:
    """Stage 4: Classify + Filter — LLM tagging then drop irrelevant."""
    print("\n" + "=" * 60)
    print("[4/7] CLASSIFY + FILTER — LLM Tagging → Drop Irrelevant")
    print("=" * 60)

    from openai import OpenAI
    client = OpenAI()

    results = []
    total_chunks = 0
    total_kept = 0
    total_discarded = 0

    for doc, chunks in chunked:
        print(f"  Classifying {len(chunks)} chunks from: {doc.title[:40]}...")
        classifications = classify_chunks(chunks, doc, client)

        # Filter irrelevant
        kept_chunks, kept_clfs, discarded = filter_irrelevant(chunks, classifications)
        total_chunks += len(chunks)
        total_kept += len(kept_chunks)
        total_discarded += discarded

        if discarded:
            print(f"    Filtered: {len(chunks)} → {len(kept_chunks)} ({discarded} irrelevant dropped)")

        if kept_chunks:
            results.append((doc, kept_chunks, kept_clfs))

    stats.log("classify+filter", total_chunks, total_kept,
              f"{total_discarded} irrelevant dropped")
    print(f"\n  ✓ Classified {total_chunks} chunks → {total_kept} relevant ({total_discarded} irrelevant)")
    return results


def stage_5_extract_claims(
    classified: List[Tuple[Document, List[Chunk], List[ChunkClassification]]],
    stats: PipelineStats,
) -> List[ClaimOutput]:
    """Stage 5: Extract claims + sort by priority (no cap)."""
    print("\n" + "=" * 60)
    print("[5/7] CLAIMS — Extract Atomic Claims + Sort by Priority")
    print("=" * 60)

    from openai import OpenAI
    client = OpenAI()

    all_claims = []

    for doc, chunks, clfs in classified:
        print(f"  Extracting claims from: {doc.title[:40]}...")
        doc_claims = extract_claims(chunks, clfs, doc, client)
        all_claims.extend(doc_claims)

    # Sort by priority within groups — no cap
    sorted_claims = sort_claims_by_priority(all_claims)

    total_bullets = sum(len(c.bullets) for c in sorted_claims)
    stats.log("claims", sum(len(c) for _, c, _ in classified), len(sorted_claims),
              f"{total_bullets} bullets, all claims kept")
    print(f"\n  ✓ Extracted {len(sorted_claims)} claims (all kept, sorted by priority)")
    return sorted_claims


def stage_5b_file_claims(
    claims: List[ClaimOutput],
    stats: PipelineStats,
) -> None:
    """Stage 5b: File claims in historical tracker for drift detection."""
    print("\n" + "=" * 60)
    print("[5b] FILE CLAIMS — Store for Drift Detection")
    print("=" * 60)

    tracker = ClaimTracker()
    stored = tracker.store_claims(claims)
    tracker_stats = tracker.get_stats()

    print(f"  ✓ Stored {stored} claims")
    print(f"    Total historical: {tracker_stats['total_claims']} across {tracker_stats['days_tracked']} days")

    stats.log("file_claims", len(claims), stored, "SQLite storage")


def stage_5c_drift_detection(
    claims: List[ClaimOutput],
    stats: PipelineStats,
) -> Optional[DriftReport]:
    """Stage 5c: Drift detection — compare today vs history (Phase 2 rendering)."""
    print("\n" + "=" * 60)
    print("[5c] DRIFT DETECTION — Belief Changes (rendering deferred to Phase 2)")
    print("=" * 60)

    if not DRIFT_DETECTION.get('enabled', False):
        print("  Drift detection disabled in config")
        return None

    tracker = ClaimTracker()
    lookback = DRIFT_DETECTION.get('lookback_days', 7)
    prior_claims = tracker.get_prior_claims(days=lookback)
    print(f"  Prior claims (last {lookback} days): {len(prior_claims)}")

    drift_report = None
    if prior_claims:
        print("  Detecting belief drift...")
        drift_report = detect_drift(claims, tracker, lookback_days=lookback)
        print(f"    {drift_report.summary()}")

        if drift_report.high_severity:
            print(f"    High severity signals: {len(drift_report.high_severity)}")
            for s in drift_report.high_severity[:3]:
                print(f"      - [{s.drift_type}] {s.description[:70]}")
    else:
        print("  No historical data yet — first run builds the baseline")

    signal_count = len(drift_report.signals) if drift_report else 0
    stats.log("drift", len(claims), signal_count, f"{len(prior_claims)} prior claims")

    return drift_report


def stage_6_synthesize_and_render(
    claims: List[ClaimOutput],
    stats: PipelineStats,
    source_failures: List[str] = None,
) -> str:
    """Stage 6: Synthesize Section 2 + Render 4-section briefing."""
    print("\n" + "=" * 60)
    print("[6/7] SYNTHESIZE + RENDER — V3 4-Section Briefing")
    print("=" * 60)

    # Section 2 synthesis (LLM narrative)
    print("  Synthesizing Section 2 (agreement/disagreement narrative)...")
    from openai import OpenAI
    try:
        client = OpenAI()
    except Exception:
        client = None

    section2 = synthesize_section2(claims, client=client)
    print(f"    Agreements: {len(section2.agreements)}")
    print(f"    Disagreements: {len(section2.disagreements)}")
    print(f"    Narrative: {len(section2.narrative)} chars")

    # Render briefing
    print("  Rendering 4-section briefing...")
    briefing = render_briefing(
        claims, section2,
        briefing_date=date.today(),
    )

    # Append source failure notice
    if source_failures:
        failure_notice = "\n---\n\n## Data Collection Notices\n\n"
        failure_notice += "*The following sources could not be retrieved:*\n\n"
        for failure in source_failures:
            failure_notice += f"- {failure}\n"
        failure_notice += "\n*Briefing may be incomplete. Check source availability.*\n"
        briefing += failure_notice
        print(f"  ⚠ Added {len(source_failures)} source failure notices")

    words = count_words(briefing)
    pages = count_pages(briefing)
    stats.log("render", len(claims), 1, f"{words} words, {pages:.1f} pages")

    print(f"\n  ✓ Briefing rendered: {words} words (~{pages:.1f} pages)")
    return briefing


# ------------------------------------------------------------------
# Main Pipeline
# ------------------------------------------------------------------

def run_pipeline():
    """Execute full end-to-end V3 pipeline."""
    print("\n" + "=" * 60)
    print("  FINANCIAL NEWS AGENT — V3 Pipeline")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    _reset_today_dedup()
    stats = PipelineStats()

    # Stage 1: Collect
    reports, source_failures = stage_1_collect(stats)
    if not reports:
        print("\n✗ No reports to process. Exiting.")
        return None

    # Stage 2: Normalize
    normalized = stage_2_normalize(reports, stats)

    # Stage 2b: Pre-filter (drop non-TMT docs before LLM classification)
    filtered = stage_2b_prefilter(normalized, stats)

    # Stage 3: Chunk
    chunked = stage_3_chunk(filtered, stats)

    # Stage 4: Classify + Filter irrelevant (replaces old classify → scope_chunks → triage)
    classified = stage_4_classify_and_filter(chunked, stats)

    if not classified:
        print("\n✗ All chunks classified as irrelevant. No content for briefing.")
        return None

    # Stage 5: Extract claims + per-group cap (max 3 per ticker/subtopic/macro)
    claims = stage_5_extract_claims(classified, stats)

    if not claims:
        print("\n✗ No claims extracted. No content for briefing.")
        return None

    # Stage 5b: File claims for historical tracking
    stage_5b_file_claims(claims, stats)

    # Stage 5c: Drift detection (runs + files, rendering deferred to Phase 2)
    drift_report = stage_5c_drift_detection(claims, stats)

    # Stage 6: Synthesize + Render
    briefing = stage_6_synthesize_and_render(claims, stats, source_failures)

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
