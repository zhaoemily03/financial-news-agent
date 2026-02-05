# CLAUDE.md

Instructions for Claude when working on this codebase.

---

## Target User

**Professional TMT analyst** (internet + software focus)
- Time-constrained: <15 minutes to consume daily briefing
- Wants to **challenge ideas**, not read summaries
- Forms their own conviction; does not want AI opinions
- Covers: META, GOOGL, AMZN, AAPL, MSFT, CRWD, ZS, PANW, NET, DDOG, SNOW, MDB

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

### Claude Should Favor:

| Pattern | Why It's Right |
|---------|----------------|
| Structured outputs (dataclasses, typed dicts) | Auditable, testable |
| Explicit uncertainty ("may", "could", "estimates") | Preserved from source |
| Deterministic logic where possible | Reproducible, explainable |
| Rule-based routing over LLM judgment | "Why is this here?" must have a clear answer |
| Atomic, challengeable claims | Easy to agree, disagree, or ignore |
| Source citations on every claim | Traceability to PDF page |

### Where AI Is Allowed

Only these modules should use LLM calls:

1. `classifier.py` — Descriptive tagging (topic, ticker, content type)
2. `claim_extractor.py` — Compress prose to 1-2 atomic bullets
3. `tier2_synthesizer.py` — Detect agreement/disagreement patterns

All other modules must be deterministic.

---

## Architecture Overview

**Pipeline:** Collect → Normalize → Chunk → Classify → Triage → Claims → Scope Filter → Route → Synthesize → Render → Drill-down

See README.md for the full 11-step pipeline with AI/non-AI markers.

### Key Modules

| Module | Purpose | Uses AI? |
|--------|---------|----------|
| `schemas.py` | Document, Chunk, Claim dataclasses | No |
| `normalizer.py` | Raw content → Document | No |
| `chunker.py` | Document → Chunks (~500 tokens) | No |
| `classifier.py` | Chunk classification | **Yes** |
| `triage.py` | Analyst-configurable filtering | No |
| `claim_extractor.py` | Chunk → atomic claims | **Yes** |
| `scope_filter.py` | Sector/ticker/analyst scoping | No |
| `tier_router.py` | Rule-based Tier 1/2/3 | No |
| `tier2_synthesizer.py` | Cross-claim synthesis | **Yes** |
| `implication_router.py` | Tier 3 indexing | No |
| `briefing_renderer.py` | <5 page output | No |
| `drilldown.py` | Claim provenance | No |

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

---

## Configuration

| File | Purpose |
|------|---------|
| `config.py` | Tickers, analysts, themes, relevance threshold |
| `analyst_config_tmt.py` | TMT-specific topic weights and source credibility |
| `.env` | API keys (OPENAI_API_KEY), portal credentials (MS_EMAIL, MS_VERIFY_LINK) — gitignored |
| `data/cookies.json` | Portal session cookies (Jefferies, Morgan Stanley) — gitignored |

### Key Config Values

- **RELEVANCE_THRESHOLD**: 0.7 (chunks below this are triaged out)
- **BRIEFING_DAYS**: 5 (only process reports from last 5 days)
- **Primary tickers**: META, GOOGL, AMZN, AAPL, BABA, 700.HK, MSFT, CRWD, ZS, PANW, NET, DDOG, SNOW, MDB
- **Trusted analysts**: Brent Thill, Joseph Gallo (Jefferies)

---

## Scope Filtering

The `scope_filter.py` module ensures briefings stay within the analyst's sector focus. Applied **after claim extraction, before tier routing**.

### Purpose

Prevents non-TMT content from diluting TMT briefings. A utilities analyst's report scraped from the same portal won't pollute the internet/software briefing.

### Configuration

| Field | Effect |
|-------|--------|
| `primary_sector` | 'TMT' (default) or 'ALL' to skip filtering |
| `sub_sectors` | Limit to specific sub-sectors: technology, media, telecom |
| `ticker_whitelist` | Only include claims for listed tickers |
| `analyst_whitelist` | Only include claims from listed analysts |

### Built-in Scopes

- `DEFAULT_TMT_SCOPE` — All TMT content, no restrictions
- `INTERNET_SOFTWARE_SCOPE` — Technology + media, primary coverage tickers only

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

- [x] Jefferies portal scraping (Selenium + SSO cookies)
- [x] PDF text extraction (pdfplumber + PyPDF2 fallback)
- [x] Document normalization and chunking
- [x] LLM classification (topic, ticker, content type)
- [x] Analyst-configurable triage with deduplication
- [x] Claim extraction with judgment hooks
- [x] Sector-scoped claim filtering (ticker/analyst whitelists)
- [x] Rule-based tier routing (Tier 1/2/3)
- [x] Tier 2 synthesis (agreement/disagreement/deltas)
- [x] Tier 3 implication indexing
- [x] <5 page briefing renderer
- [x] Drill-down integrity (full claim provenance)
- [x] Podcast ingestion (All-In, BG2 Pod, Acquired)
- [ ] End-to-end pipeline integration test
- [ ] Substack ingestion
- [ ] Email delivery
- [ ] Cron job scheduling (7 AM daily)
