# CLAUDE.md

Instructions for Claude when working on this codebase.

---

## What This System Does

Surfaces **belief change and sentiment drift** — the inputs that drive fundamental buy decisions — while keeping breaking news visible. This is NOT a summarization tool.

The system helps analysts:
- Track belief evolution across sources over time
- Get early warning of softening conviction
- See disagreement clearly
- Spend less time reading

---

## Target User

**Professional TMT analyst** (internet + software focus)
- Time-constrained: <15 minutes to consume daily briefing
- Wants to **challenge ideas**, not read summaries
- Forms their own conviction; does not want AI opinions
- Covers: META, GOOGL, AMZN, AAPL, MSFT, CRWD, ZS, PANW, NET, DDOG, SNOW, MDB

---

## Core Design Principles (Non-Negotiable)

1. **Change > State** — Surface what *changed*, not what *is*
2. **Beliefs > Documents** — Track claims and confidence over time
3. **Judgment Lives With Humans** — AI surfaces pressure on beliefs, not conclusions
4. **Brevity Enables Thinking** — <5 pages, <15 minutes

---

## Primary Product Constraint

The default daily analyst output must be:

- **Consumable in under 15 minutes**
- **Under 5 pages of content**
- **Without loss of material insight**

Depth must be accessed via drill-down, never by default.

Any design choice that increases verbosity or hides uncertainty should be avoided.

---

## Development Rules

### Before Making Changes

1. **Always read README.md first** — it documents the full pipeline and where AI is/isn't used
2. **Do not refactor existing architecture** unless explicitly instructed
3. **Respect the <15 minute / <5 page constraint** at all times

### Code Style

- Keep code clean and concise
- Use pseudocode-style comments, not verbose documentation
- Clean up dead code and failed approaches — no long trails of unused code
- Avoid over-engineering; only build what's needed now
- OpenAI SDK v1.x: Use `OpenAI()` client, not the old `openai.ChatCompletion.create()` API
- Print progress with checkmarks (`✓`) and step indicators (`[1/5]`) for pipeline visibility

### Testing

- Each module should have a `if __name__ == "__main__":` test block
- Tests should include verification assertions with `✓` output
- No external test framework required; inline tests are preferred

---

## AI Usage Boundaries

### Claude Must NOT Introduce:

| Anti-Pattern | Why It's Wrong |
|--------------|----------------|
| Implicit relevance judgments | Relevance is analyst-configurable, not AI-decided |
| Narrative summaries that increase verbosity | Violates <5 page constraint |
| Conclusions or recommendations | System describes; humans decide |
| Words like "bullish", "bearish", "should", "recommend" | Thesis language is banned |
| Global importance rankings | Only local prioritization within tiers |
| Hidden disagreement | Contradictions are first-class outputs |
| Static descriptions that don't show change | Change > State |
| Background explanations or repeated company descriptions | Wastes page budget |

### Claude Should Favor:

| Pattern | Why It's Right |
|---------|----------------|
| Structured outputs (dataclasses, typed dicts) | Auditable, testable |
| Explicit uncertainty ("may", "could", "estimates") | Preserved from source |
| Deterministic logic where possible | Reproducible, explainable |
| Rule-based routing over LLM judgment | "Why is this here?" must have a clear answer |
| Atomic, challengeable claims | Easy to agree, disagree, or ignore |
| Source citations on every claim | Traceability to PDF page |
| Change-over-time signals | Drift detection is the core value |
| Belief pressure metadata | Enables cross-time comparison |

### Where AI Is Allowed

Only these modules should use LLM calls:

1. `classifier.py` — Descriptive tagging (topic, ticker, content type)
2. `claim_extractor.py` — Compress prose to 1-2 atomic bullets
3. `tier2_synthesizer.py` — Detect agreement/disagreement patterns

All other modules must be deterministic.

---

## Architecture Overview

**Pipeline (V3):** Collect → Normalize → Pre-filter → Chunk → Classify+Filter → Claims+Cap → File Claims → Drift → Synthesize → Render

See README.md for the full pipeline with AI/non-AI markers.

### Key Modules

| Module | Purpose | Uses AI? |
|--------|---------|----------|
| `schemas.py` | Document, Chunk, Claim dataclasses | No |
| `normalizer.py` | Raw content → Document | No |
| `macro_news.py` | RSS macro news collection (Reuters, CNBC) | No |
| `chunker.py` | Document → Chunks (~500 tokens) | No |
| `classifier.py` | 4-category chunk classification + `filter_irrelevant()` | **Yes** |
| `claim_extractor.py` | Chunk → atomic claims + `sort_claims_by_priority()` | **Yes** |
| `claim_tracker.py` | Historical claim storage (SQLite) | No |
| `drift_detector.py` | Cross-time belief shift detection | No |
| `tier2_synthesizer.py` | Section 2 narrative synthesis (agreement/disagreement) | **Yes** |
| `briefing_renderer.py` | V3 4-section <5 page output | No |
| `analyst_config_tmt.py` | Category/subtopic weights, source credibility | No |
| `scope_filter.py` | Sector/ticker/analyst scoping | No |
| `drilldown.py` | Claim provenance | No |

### Deprecated Modules (kept on disk, removed from pipeline)

| Module | Replaced By |
|--------|-------------|
| `tier_router.py` | Classifier `category` field routes directly |
| `implication_router.py` | No Tier 3 section in V3 |
| `triage.py` | `filter_irrelevant()` |

### Drift Detection (Deterministic, No AI)

The `drift_detector.py` module compares today's claims against historical claims stored in `claim_tracker.py`. It detects:
- **Confidence shifts** — Source was high-conviction, now hedging
- **Belief flips** — Source confirmed consensus, now contradicts
- **New disagreement** — Sources that were aligned are now split
- **Resurgence** — Topic reappearing after silence
- **Attention decay** — Topic that was active has gone quiet

This is deterministic — no LLM calls. It compares `confidence_level` and `belief_pressure` metadata across time.

### Briefing Output (V3, 4 Sections)

| # | Section | Content | Status |
|---|---------|---------|--------|
| 1 | Objective Breaking News | Per-ticker updates (all non-redundant claims, "No Update" if nothing) + TMT sector-level | **Live** |
| 2 | Synthesis Across Sources | LLM narrative: where sources agree/disagree, considering credibility | **Live** |
| 3 | Macro Connections | Macro claims + TMT linkage | **Phase 2 stub** |
| 4 | Longitudinal Delta Detection | Drift signals, belief shifts over time | **Phase 2 stub** |

Section 1 routes claims by `category`: `tracked_ticker` → per-ticker groups, `tmt_sector` → sector sub-section. Section 2 uses `tier2_synthesizer.py` with source credibility from `analyst_config_tmt.SOURCE_CREDIBILITY`. All non-redundant relevant claims are kept; `sort_claims_by_priority()` in `claim_extractor.py` orders them (breaking > contrarian first) with no cap.

### Data Ingestion (Multi-Portal Framework)

| Module | Purpose |
|--------|---------|
| `base_scraper.py` | Abstract base class for portal scrapers |
| `portal_registry.py` | Registry for managing multiple portals |
| `jefferies_scraper.py` | Jefferies portal (extends BaseScraper) |
| `morgan_stanley_scraper.py` | Morgan Stanley Matrix portal (extends BaseScraper) |
| `cookie_manager.py` | Cookie persistence per portal |
| `report_tracker.py` | SQLite deduplication |

### Podcast Ingestion Framework

| Module | Purpose |
|--------|---------|
| `base_podcast.py` | Abstract base class for podcast handlers |
| `podcast_registry.py` | Registry for managing multiple podcasts |
| `youtube_podcast.py` | YouTube-based podcasts (All-In Podcast) |
| `rss_podcast.py` | RSS-based podcasts (BG2 Pod, Acquired) |
| `podcast_tracker.py` | SQLite episode deduplication |

### Substack Ingestion (via Feishu Mail)

| Module | Purpose |
|--------|---------|
| `substack_feishu.py` | Fetch forwarded Substack emails from Feishu Mail API |

Substack newsletters are forwarded to a Feishu mailbox. The module uses a tenant_access_token from an Internal App ("Substack_Ingestion_Agent") to read the inbox, filter for Substack emails, and extract article content. No manual author config needed — any forwarded Substack email is auto-ingested.

---

## Configuration

| File | Purpose |
|------|---------|
| `config.py` | Tickers, analysts, themes, relevance threshold |
| `analyst_config_tmt.py` | TMT-specific topic weights and source credibility |
| `.env` | API keys (OPENAI_API_KEY), portal credentials (MS_EMAIL, MS_VERIFY_LINK), Feishu credentials (FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_MAILBOX) — gitignored |
| `data/cookies.json` | Portal session cookies (Jefferies, Morgan Stanley) — gitignored |

### Key Config Values

- **BRIEFING_DAYS**: 5 (only process reports from last 5 days)
- **Primary tickers**: META, GOOGL, AMZN, AAPL, BABA, 700.HK, MSFT, CRWD, ZS, PANW, NET, DDOG, SNOW, MDB
- **Trusted analysts**: Brent Thill, Joseph Gallo (Jefferies)
- **Categories**: tracked_ticker, tmt_sector, macro, irrelevant

---

## Scope Filtering

Scope filtering happens at **two levels** in the V3 pipeline:

1. **Stage 2b — Document pre-filter** (deterministic): Drops entire documents with no TMT relevance before classification. Checks title + first chunks for covered tickers or TMT keywords. Podcasts and macro news always pass.
2. **Stage 4 — Classify + Filter** (LLM + deterministic): Classifier assigns 4 categories. `filter_irrelevant()` drops `irrelevant` chunks before claim extraction. All non-redundant claims are kept.

Old stages removed: chunk-level scope (4b), triage (5), claim-level scope (6b). The classifier `irrelevant` category replaces all three.

### Thin Day Handling

When fewer than 3 claims pass the filter, the system marks it as a "thin day" rather than padding with irrelevant content. This respects the <5 page constraint.

---

## Multi-Portal Scraper Framework

The system uses a `PortalRegistry` to manage multiple sell-side research portals. All scrapers inherit from `BaseScraper` which provides:

- **Cookie management** — Load, persist, sync between Selenium and requests
- **Authentication check** — Preflight validation, graceful auth failure handling
- **PDF extraction** — pdfplumber + PyPDF2 fallback
- **Error isolation** — One report failure doesn't crash the run

### Adding a New Portal

1. Create `{portal}_scraper.py` extending `BaseScraper`
2. Define: `PORTAL_NAME`, `CONTENT_URL`, `PDF_STORAGE_DIR`
3. Implement abstract methods:
   - `_check_authentication()` — Portal-specific auth indicators
   - `_navigate_to_notifications()` — Find notifications UI
   - `_extract_notifications()` — Parse notification items
   - `_navigate_to_report(url)` — Go to report page
   - `_extract_report_content(report)` — Extract text/PDF
4. Register in `portal_registry.py`
5. Enable in `config.py` SOURCES dict

### Jefferies Scraper (Reference Implementation)

1. Login (cookies loaded from `data/cookies.json`)
2. Click "Followed Notifications" bell icon
3. Extract report notifications from panel
4. For each report: navigate, extract content (direct or PDF)
5. Persist updated cookies after run

**Technical note:** Jefferies portal is a Vue.js/Vuetify SPA requiring JavaScript rendering.

### Morgan Stanley Scraper

1. Authenticate via email verification link (one-time device auth) or cookies
2. Navigate to home page, find "My Feed" button (right of search bar)
3. Extract report notifications from feed
4. For each report: navigate, scroll to reveal PDF button, download PDF
5. Persist updated cookies after run

**Authentication:** MS uses email verification links for device auth. Set `MS_VERIFY_LINK` in `.env` with the verification URL from your analyst's email. After first successful auth, cookies are persisted and reused.

**Technical note:** Morgan Stanley Matrix portal is a React SPA at `ny.matrix.ms.com`.

---

## Podcast Ingestion Framework

The system uses a `PodcastRegistry` to manage multiple podcast sources. Podcasts provide macro context and social sentiment.

### Supported Podcasts

| Podcast | Hosts | Type | Transcript Source |
|---------|-------|------|-------------------|
| All-In Podcast | Chamath, Jason, Sacks, Friedberg | YouTube | Auto-captions |
| BG2 Pod | Brad Gerstner, Bill Gurley | RSS | Episode descriptions |
| Acquired | Ben Gilbert, David Rosenthal | RSS | Episode descriptions |

### Adding a New Podcast

1. **YouTube-based:** Create class extending `YouTubePodcast` with `CHANNEL_ID`
2. **RSS-based:** Create class extending `RSSPodcast` with `RSS_URL`
3. Register in `podcast_registry.py`
4. Enable in `config.py` SOURCES['podcasts']['sources']

### How Podcasts Flow Through Pipeline

1. `podcast_registry.collect_all()` discovers new episodes
2. Transcripts extracted (YouTube auto-captions or RSS descriptions)
3. Episodes returned in same format as sell-side reports
4. Normalized → Chunked → Classified → Claims → Tiered → Rendered

**Key difference:** Podcast claims use `source_type: "podcast"` and cite hosts as analysts.

---

## Current Status

- [x] V3 4-section briefing pipeline (Sections 1+2 live, 3+4 stubbed)
- [x] 4-category classifier (tracked_ticker, tmt_sector, macro, irrelevant)
- [x] Claims sorted by priority within groups (breaking > contrarian first, no cap)
- [x] Section 2 LLM narrative synthesis with source credibility
- [x] Jefferies portal scraping (Selenium + SSO cookies)
- [x] PDF text extraction (pdfplumber + PyPDF2 fallback)
- [x] Document normalization and chunking
- [x] Podcast ingestion (All-In, BG2 Pod, Acquired)
- [x] Historical claim tracking (SQLite-backed)
- [x] Sentiment drift detection (confidence shifts, belief flips, disagreement)
- [x] Automated cookie refresh (launchd)
- [x] Macro news collection (Reuters, CNBC via RSS)
- [x] Document-level pre-filter (save LLM calls on non-TMT docs)
- [ ] Section 3: Macro Connections (Phase 2)
- [ ] Section 4: Longitudinal Delta Detection rendering (Phase 2)
- [ ] End-to-end pipeline integration test
- [x] Substack ingestion (Feishu Mail API)
- [ ] Email delivery
