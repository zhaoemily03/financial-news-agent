#!/usr/bin/env python3
"""
One-off re-render: load today's stored sell-side claims from DB,
re-collect Substack + podcasts + macro with updated classifier,
merge, and produce a new briefing.

Usage:
    venv/bin/python rerender_with_substack.py
"""

import os
import sys
from datetime import datetime, date
from typing import List
from dotenv import load_dotenv

load_dotenv()

from schemas import Document, Chunk
from normalizer import DocumentNormalizer
from chunker import chunk_document
from classifier import classify_chunks, filter_irrelevant
from claim_extractor import extract_claims, sort_claims_by_priority, ClaimOutput
from tier2_synthesizer import synthesize_section2
from briefing_renderer import render_briefing, count_words, count_pages
from claim_tracker import ClaimTracker
from drift_detector import detect_drift
from config import ALL_TICKERS, MACRO_NEWS, SOURCES, DRIFT_DETECTION
from openai import OpenAI

# Reuse pre-filter helpers from run_pipeline
from run_pipeline import (
    TMT_PREFILTER_KEYWORDS, PASSTHROUGH_SOURCES,
    stage_2b_prefilter, PipelineStats,
)

print("\n" + "=" * 60)
print("  RE-RENDER: Substack + Podcasts + Macro → merge with today's sellside")
print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

client = OpenAI()
stats = PipelineStats()

# ------------------------------------------------------------------
# Step 1: Load today's sell-side claims from claim_history.db
# ------------------------------------------------------------------
print("\n[1/5] Load today's stored sell-side claims from DB")

tracker = ClaimTracker()
today_str = date.today().strftime('%Y-%m-%d')
stored_historical = tracker.get_claims_by_date(today_str)
sellside_claims = [h.to_claim_output() for h in stored_historical]

print(f"  ✓ Loaded {len(sellside_claims)} sell-side claims from {today_str}")
for c in sellside_claims:
    src = c.source_citation[:60] if c.source_citation else "?"
    ticker = f"[{c.ticker}]" if c.ticker else "[sector/macro]"
    print(f"    {ticker} {c.bullets[0][:60] if c.bullets else '—'}... — {src}")

# ------------------------------------------------------------------
# Step 2: Collect Substack + Podcasts + Macro
# ------------------------------------------------------------------
print("\n[2/5] Collect Substack + Podcasts + Macro")

new_reports = []
source_failures = []

# Substack
substack_config = SOURCES.get('substack', {})
if substack_config.get('enabled', False):
    try:
        from substack_feishu import collect_substack
        articles = collect_substack(days=substack_config.get('days_lookback', 5))
        if articles:
            new_reports.extend(articles)
            print(f"  ✓ Substack: {len(articles)} articles")
        else:
            print("  ⚠ Substack: 0 articles")
    except Exception as e:
        print(f"  ⚠ Substack failed: {e}")
        source_failures.append(f"Substack ({str(e)[:50]})")

# Podcasts
podcasts_config = SOURCES.get('podcasts', {})
if podcasts_config.get('enabled', False):
    try:
        from podcast_registry import podcast_registry
        enabled_podcasts = podcast_registry.list_enabled()
        if enabled_podcasts:
            result = podcast_registry.collect_all(days=7, max_per_podcast=2)
            episodes = result.get('episodes', [])
            if episodes:
                new_reports.extend(episodes)
                print(f"  ✓ Podcasts: {len(episodes)} episodes from {enabled_podcasts}")
            else:
                print(f"  ⚠ Podcasts: 0 episodes (enabled: {enabled_podcasts})")
            source_failures.extend(result.get('failures', []))
    except Exception as e:
        print(f"  ⚠ Podcasts failed: {e}")
        source_failures.append(f"Podcasts ({str(e)[:50]})")

# Macro news
if MACRO_NEWS.get('enabled', False):
    try:
        from macro_news import collect_macro_news
        macro_reports = collect_macro_news(
            max_articles=MACRO_NEWS.get('max_articles', 6),
            days=MACRO_NEWS.get('days_lookback', 1),
        )
        if macro_reports:
            new_reports.extend(macro_reports)
            print(f"  ✓ Macro news: {len(macro_reports)} articles")
        else:
            print("  ⚠ Macro news: 0 articles")
    except Exception as e:
        print(f"  ⚠ Macro news failed: {e}")
        source_failures.append(f"Macro news ({str(e)[:50]})")

print(f"\n  {len(new_reports)} new documents to process")

if not new_reports:
    print("  Nothing new to add — briefing unchanged. Exiting.")
    sys.exit(0)

# ------------------------------------------------------------------
# Step 3: Normalize → Pre-filter → Chunk → Classify → Extract claims
# ------------------------------------------------------------------
print("\n[3/5] Process new documents through pipeline")

normalizer = DocumentNormalizer()
normalized = []
for r in new_reports:
    doc, chunks = normalizer.normalize_text(r['content'], r)
    normalized.append((doc, chunks))

print(f"  Normalized {len(normalized)} documents")

# Pre-filter
filtered = stage_2b_prefilter(normalized, stats)

# Chunk
chunked = []
for doc, page_chunks in filtered:
    atomic = chunk_document(doc, page_chunks)
    chunked.append((doc, atomic))

total_chunks = sum(len(c) for _, c in chunked)
print(f"  Chunked: {total_chunks} atomic chunks")

# Classify + filter irrelevant
classified = []
total_kept = 0
for doc, chunks in chunked:
    print(f"  Classifying {len(chunks)} chunks from: {doc.title[:45]}...")
    clfs = classify_chunks(chunks, doc, client)
    kept_chunks, kept_clfs, dropped = filter_irrelevant(chunks, clfs)
    total_kept += len(kept_chunks)
    if dropped:
        print(f"    {len(chunks)} → {len(kept_chunks)} ({dropped} irrelevant dropped)")
    if kept_chunks:
        classified.append((doc, kept_chunks, kept_clfs))

print(f"  ✓ {total_chunks} chunks → {total_kept} relevant")

# Extract claims
new_claims = []
for doc, chunks, clfs in classified:
    print(f"  Extracting claims from: {doc.title[:45]}...")
    doc_claims = extract_claims(chunks, clfs, doc, client)
    new_claims.extend(doc_claims)

print(f"  ✓ Extracted {len(new_claims)} new claims from Substack/podcasts/macro")

# ------------------------------------------------------------------
# Step 4: Merge with sell-side claims, cap, file new ones
# ------------------------------------------------------------------
print("\n[4/5] Merge + cap + file new claims")

# Deduplicate by chunk_id (avoid double-filing anything already in DB)
existing_ids = {h.claim_id for h in stored_historical}
truly_new = [c for c in new_claims if c.chunk_id not in existing_ids]

print(f"  Sell-side (from DB): {len(sellside_claims)}")
print(f"  New (Substack/podcasts/macro): {len(truly_new)}")

# File only the new ones
if truly_new:
    filed = tracker.store_claims(truly_new)
    print(f"  ✓ Filed {filed} new claims")

# Merge and sort by priority (no cap)
all_claims = sellside_claims + truly_new
capped = sort_claims_by_priority(all_claims)
print(f"  ✓ Merged {len(all_claims)} claims, sorted by priority")

# ------------------------------------------------------------------
# Step 5: Drift + Synthesize + Render
# ------------------------------------------------------------------
print("\n[5/5] Synthesize + Render")

# Drift
drift_report = None
if DRIFT_DETECTION.get('enabled', False):
    lookback = DRIFT_DETECTION.get('lookback_days', 7)
    prior_claims = tracker.get_prior_claims(days=lookback)
    if prior_claims:
        drift_report = detect_drift(capped, tracker, lookback_days=lookback)
        print(f"  Drift signals: {len(drift_report.signals) if drift_report else 0}")

# Section 2 synthesis
section2 = synthesize_section2(capped, client=client)
print(f"  Agreements: {len(section2.agreements)}, Disagreements: {len(section2.disagreements)}")

# Render
briefing = render_briefing(capped, section2, briefing_date=date.today())

# Source failure notice
if source_failures:
    briefing += "\n---\n\n## Data Collection Notices\n\n"
    briefing += "*The following sources could not be retrieved:*\n\n"
    for f in source_failures:
        briefing += f"- {f}\n"
    briefing += "\n*Briefing may be incomplete.*\n"

# Save
os.makedirs('data/briefings', exist_ok=True)
stamp = datetime.now().strftime('%Y-%m-%d_%H%M')
path = f'data/briefings/briefing_{stamp}.md'
with open(path, 'w') as f:
    f.write(briefing)

words = count_words(briefing)
pages = count_pages(briefing)
print(f"\n✓ Briefing saved: {path}")
print(f"  {words} words (~{pages:.1f} pages)")
print(f"  Sell-side claims: {len(sellside_claims)} | New: {len(truly_new)} | After cap: {len(capped)}")

print("\n" + "=" * 60)
print("BRIEFING OUTPUT")
print("=" * 60)
print(briefing)
