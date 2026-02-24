# Financial News Agent

A belief-drift detection system for TMT portfolio analysts.

---

## System Purpose

A one-stop-shop for a secondaries hedge fund portfolio manager to see what broke on the tickers they are covering, what broke in the Technology, Media, & Telecommunications (TMT) sector, and to synthesize across multiple information streams. This tool helps the user anticipate how their TMT portfolio should be balanced according to the information streams ingested and incoming disruptions. Surfaces **belief change and sentiment drift** — the inputs that actually drive fundamental buy decisions — while keeping breaking news and structural events visible.

| System Does | Human Does |
|-------------|------------|
| Track claims and confidence over time | Form conviction |
| Detect when sentiment is shifting | Challenge claims |
| Surface disagreement between sources | Decide actions |
| Enforce brevity by design | Judge what matters |

The system does **not** aim to summarize "everything." Summaries exist to support judgment, not replace it. The core output is **change detection**, not information aggregation.

---

## Core Principles

Every design decision follows these principles:

> **Change > State.** Surface what *changed*, not what *is*.
> **Beliefs > Documents.** Track claims and confidence over time.
> **Judgment Lives With Humans.** AI surfaces pressure on beliefs, not conclusions.
> **Brevity Enables Thinking.** <5 pages, <15 minutes.

This means:

- **Sentiment drift is a first-class output.** When an analyst's confidence softens, you see it.
- **Contradictions are surfaced, not hidden.** If sources disagree, you see both sides.
- **Uncertainty is preserved.** "May", "could", "estimates" stay in the output.
- **Brevity is enforced by design.** <5 pages daily, "No Update" lines removed first if over budget.
- **No conviction imposed.** The system describes; you decide.

What the system will never do:
- Recommend buy/sell/hold
- Rank importance globally (only locally within tiers)
- Use words like "bullish", "bearish", "should"
- Hide disagreement to appear more confident
- Produce narrative summaries that increase verbosity

---

## High-Level Pipeline (V3)

```
Collect → Normalize → Pre-filter → Chunk → Classify+Filter → Claims+Sort → File Claims → Drift → Synthesize → Render
```

| Step | Module | AI? | Description |
|------|--------|-----|-------------|
| 1. **Collect** | `portal_registry.py` + `podcast_registry.py` + `macro_news.py` + `substack_feishu.py` | No | Fetch portals, podcasts, macro RSS, Substack |
| 2. **Normalize** | `normalizer.py` | No | Convert to structured `Document` objects |
| 2b. **Pre-filter** | `run_pipeline.py` | No | Drop non-TMT docs by ticker/keyword before LLM |
| 3. **Chunk** | `chunker.py` | No | Split into atomic units (~500 tokens) |
| 4. **Classify+Filter** | `classifier.py` | **Yes** | 4-category classification + `filter_irrelevant()`. Off-coverage `tracked_ticker` chunks downgrade to `tmt_sector`. |
| 5. **Claims+Sort** | `claim_extractor.py` | **Yes** | Extract atomic claims + `sort_claims_by_priority()` (no cap; high-alert always shown) |
| 5b. **File Claims** | `claim_tracker.py` | No | Store claims in SQLite for historical tracking |
| 5c. **Drift Detect** | `drift_detector.py` | No | Compare today's claims against history for belief shifts |
| 6. **Synthesize+Render** | `tier2_synthesizer.py` + `briefing_renderer.py` | **Yes** | Section 2 narrative + 4-section briefing output |

**Removed stages (V3):** Chunk scope (4b), Triage (5), Claim scope (6b), Tier routing (7), Tier 3 indexing (9). The classifier's `irrelevant` category replaces these. No hard claim cap — high-alert events always shown; `sort_claims_by_priority()` orders by breaking → contrarian first.

---

## Where AI Is Used (and Where It Is Not)

### AI Is Used For:

| Task | Why AI? |
|------|---------|
| **Classification** | Descriptive tagging (topic, ticker, content type). No relevance judgment. |
| **Claim Compression** | Extract 1-2 atomic bullets from prose. Preserve uncertainty language. |
| **Cross-Claim Synthesis** | Detect agreement/disagreement patterns across sources. |

### AI Is NOT Used For:

| Task | Why Not AI? |
|------|-------------|
| **Relevance Filtering** | Classifier assigns `irrelevant` category; `filter_irrelevant()` drops deterministically. High-alert event types (earnings, guidance, org, regulation) are explicitly protected from `irrelevant` by classifier rule 8. |
| **Claim Capping** | Max 3 regular claims per ticker. High-alert claims (`_is_high_alert()`) bypass the cap entirely — always shown. Rule-based, auditable. |
| **Drift Detection** | `drift_detector.py` compares metadata over time. Deterministic. |
| **Output Formatting** | Template-driven rendering. Consistent every day. |
| **Conviction or Recommendations** | Humans decide. System describes. |

This separation ensures the system is **auditable** and **challengeable**. When an analyst asks "Why is this here?", the answer is always traceable to explicit rules or source text—never "the AI thought it was important."

---

## Briefing Output Structure (V3)

**Hard constraint:** <5 pages, consumable in <15 minutes.

The V3 briefing uses a **4-section purpose-driven layout**. Claims are routed by their `category` field from the classifier.

| # | Section | Content | Status |
|---|---------|---------|--------|
| 1 | Objective Breaking News | Per-ticker updates (max 3 each) + TMT sector-level | **Live** |
| 2 | Synthesis Across Sources | LLM narrative: agreement, disagreement, source credibility | **Live** |
| 3 | Macro Connections | Macro claims + explicit TMT linkage | **Phase 2 stub** |
| 4 | Longitudinal Delta Detection | Drift signals, belief shifts over time | **Phase 2 stub** |

### Section 1: Objective Breaking News
- **Tracked tickers**: Iterates ALL tickers from `config.ALL_TICKERS`. Shows "No Update" for tickers with nothing. Only tickers in `ALL_TICKERS` are rendered — off-coverage company reports are routed to TMT Sector-Level instead.
- **High-alert events are never missed**: Claims with `event_type` in `HIGH_ALERT_EVENT_TYPES` (earnings, guidance, org, regulation) and `is_descriptive_event=True` are always shown, uncapped, marked with `⚠`. This guarantees M&A, CEO changes, earnings beats/misses, guidance revisions, and regulatory actions are never dropped by the 3-claim cap.
- **Regular claims**: Capped at 3 per ticker (after high-alert claims are shown), sorted breaking > upcoming > ongoing, contrarian before confirming.
- **TMT sector**: Groups `tmt_sector` claims by event type. Receives off-coverage company-specific reports that were downgraded from `tracked_ticker` during classification.

### Section 2: Synthesis Across Sources
- LLM-generated narrative prose (not bullets), up to 750 words
- Each claim fed alongside the analyst's original prose excerpt — gives the LLM the reasoning chain, not just atomized bullets
- **Independent sources are not weighted lower than sell-side**: `SOURCE_CREDIBILITY` scores are equalized (sell-side 0.8, Substack 0.75). The synthesis prompt explicitly notes that sell-side has structural positive/buy-side bias and instructs the LLM to treat sell-side vs independent divergence as the highest-priority signal.
- **Priority order**: (1) sell-side vs independent source divergence first — high signal because independent sources have no deal-flow incentives; (2) sell-side internal disagreements; (3) full cross-source convergence — the strongest signal.
- No thesis language — describes patterns, doesn't recommend
- **⚑ Potential Implications subsection**: second-pass LLM call through a secondaries analyst lens — surfaces comp dynamics, liquidity timing, and information asymmetry signals. Explicitly flagged as model-generated interpretation.

### Section 3: Macro Connections (Phase 2)
- Stub: shows count of macro claims filed. Full rendering coming later.

### Section 4: Longitudinal Delta Detection (Phase 2)
- Stub: drift detection runs and files signals, but rendering deferred.

**Truncation rule:** If output exceeds ~5 pages, "No Update" lines are removed first.

---

## Claim Judgment Hooks

Every claim carries metadata to support human judgment:

| Field | Values | Purpose |
|-------|--------|---------|
| `confidence_level` | low / medium / high | How confident is the *source* (not the AI) |
| `time_sensitivity` | breaking / upcoming / ongoing | When does this matter |
| `belief_pressure` | confirms_consensus / contradicts_consensus / contradicts_prior_assumptions / unclear | How this relates to expectations |
| `event_type` | earnings / guidance / product / regulation / org / market / macro | Category of event (for MECE routing) |
| `is_descriptive_event` | true / false | Did something concrete happen? |
| `has_belief_delta` | true / false | Does this change prior expectations? |
| `sector_implication` | text / null | TMT linkage (macro claims only) |
| `source_text` | text / null | Original analyst prose from source chunk — preserved for synthesis context |

These hooks let you quickly filter for:
- Contrarian signals (`contradicts_*`)
- Time-sensitive items (`breaking`, `upcoming`)
- High-conviction sources (`confidence_level = high`)
- Factual events vs. interpretation (`is_descriptive_event`)
- Belief pressure (`has_belief_delta`)

---

## Drill-Down Integrity

Every claim links to:

1. **Original chunk text** — Verbatim source for verification
2. **PDF page reference** — `p.3` or `pp.3-5`
3. **Tier assignment reason** — Explicit rule that routed it here
4. **Related claims** — Same ticker, same document, same theme

When you ask **"Why is this here?"**, you get an instant answer:

```
Tier 1: time_sensitivity=breaking + belief_pressure=contradicts_consensus
```

---

## Scope Filtering (V3)

Scope filtering happens at two levels:

1. **Document pre-filter (2b)** — Drops entire documents with no TMT relevance before classification. Checks title + first chunks for covered tickers or TMT keywords. Podcasts, macro news, and Substack always pass through.
2. **Classify + Filter (4)** — Classifier assigns `irrelevant` category; `filter_irrelevant()` drops them. If the LLM classifies a chunk as `tracked_ticker` but no covered tickers survive the `ALL_TICKERS` filter, the category is downgraded to `tmt_sector` — ensuring off-coverage company reports route to the sector section, not the ticker list.

Old stages removed: chunk scope (4b), triage (5), claim scope (6b). The classifier's `irrelevant` category replaces all three.

### Thin Day Detection

When fewer than 3 claims pass the filter, the system marks it as a "thin day" rather than padding with irrelevant content.

---

## Supported Inputs

### Multi-Portal Framework

The system uses a **PortalRegistry** to manage multiple sell-side research portals. Each portal has its own scraper that inherits from `BaseScraper`, sharing common functionality:

- **Dynamic cookie refresh** — Authenticate once, cookies persist and auto-refresh
- **Notification-based discovery** — Pulls from "Followed Notifications" (analysts you follow in each portal)
- **Crash resilience** — One portal failure doesn't crash the entire collection
- **Unified result format** — All scrapers return the same structure

### Currently Implemented

| Source | Status | Notes |
|--------|--------|-------|
| **Morgan Stanley Matrix** | ✅ Working | Selenium scraper with email verification auth |
| **Goldman Sachs** | ✅ Working | Selenium scraper |
| **Bernstein** | ✅ Working | Selenium scraper; iterates configured industry verticals |
| **Arete** | ✅ Working | Selenium scraper; downloads watermarked PDFs from CloudFront |
| **UBS** | ✅ Working | Selenium scraper |
| **Substack** | ✅ Working | Via Feishu Mail API (forwarded emails) |
| **Jefferies Research** | ❌ Auth issues | SSO cookies expire frequently; needs manual re-auth |

### Planned Sell-Side Portals

| Source | Status | Notes |
|--------|--------|-------|
| JP Morgan | 🔲 Not yet implemented | Enable in `config.py`, implement `jpmorgan_scraper.py` |

### Adding a New Portal

1. Create `{portal}_scraper.py` inheriting from `BaseScraper`
2. Implement required methods: `_check_authentication()`, `_navigate_to_notifications()`, `_extract_notifications()`, etc.
3. Register in `portal_registry.py`
4. Enable in `config.py` SOURCES dict

See [base_scraper.py](base_scraper.py) for the abstract interface.

### Podcast Ingestion Framework

The system uses a **PodcastRegistry** to manage multiple podcast sources. Podcasts provide macro context, social sentiment, and market commentary that complements sell-side research.

| Podcast | Hosts | Platform | Transcript Source |
|---------|-------|----------|-------------------|
| **All-In Podcast** | Chamath, Jason, Sacks, Friedberg | YouTube | Auto-generated captions |
| **a16z Podcast** | Various a16z partners | RSS | Episode descriptions |
| **Acquired** | Ben Gilbert, David Rosenthal | RSS | Episode descriptions |
| **BG2 Pod** | Brad Gerstner, Bill Gurley | RSS | Episode descriptions |

**Key Features:**
- **YouTube podcasts**: Uses `youtube-transcript-api` for auto-generated transcripts (no API key needed)
- **RSS podcasts**: Discovers episodes via RSS feed, uses descriptions as content
- **Episode deduplication**: SQLite-based tracking prevents reprocessing
- **Pipeline integration**: Episodes flow through same claim extraction as sell-side reports

**Adding a New Podcast:**

1. For YouTube-based podcasts, create class extending `YouTubePodcast` with `CHANNEL_ID`
2. For RSS-based podcasts, create class extending `RSSPodcast` with `RSS_URL`
3. Register in `podcast_registry.py`
4. Enable in `config.py` SOURCES['podcasts']['sources']

### Substack Ingestion

Substack newsletters are forwarded to a Feishu mailbox. `substack_feishu.py` uses a tenant_access_token from an Internal App ("Substack_Ingestion_Agent") to read the inbox, filter for Substack emails, and extract article content. Any forwarded Substack email is auto-ingested — no manual author config needed.

### Other Sources

| Source | Status | Notes |
|--------|--------|-------|
| X (Twitter) | 🔲 Module ready | Requires X API Basic tier ($100/mo) for read access. Free tier is write-only. |

---

## Running Locally

### Prerequisites

- Python 3.9+
- Chrome browser (for Selenium)
- OpenAI API key

### Setup

```bash
# Clone and enter directory
git clone <repo-url>
cd financial-news-agent

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env  # Then edit with your OPENAI_API_KEY
```

### Configuration

| File | Purpose |
|------|---------|
| `config.py` | Tickers, trusted analysts, investment themes, relevance threshold, source toggles |
| `analyst_config_tmt.py` | TMT-specific topic weights and source credibility |
| `.env` | API keys (`OPENAI_API_KEY`, `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_MAILBOX`) — not tracked in git |
| `data/cookies.json` | Portal session cookies — not tracked in git |

### Cookie Setup

After logging into a portal in your browser, export your session cookies to `data/cookies.json` (keyed by portal name). The scrapers use persisted cookies to authenticate. For Morgan Stanley, set `MS_VERIFY_LINK` in `.env` with the email verification URL on first auth.

---

## Usage

```bash
# Run the full pipeline (generates daily briefing)
python run_pipeline.py

# Refresh portal cookies (runs automatically via launchd)
python refresh_cookies.py

# Test individual components
python classifier.py
python claim_extractor.py
python tier2_synthesizer.py
python briefing_renderer.py
```

### Automated Scheduling

The system uses **launchd** (macOS) for automation:

- **Cookie refresh**: Runs at login + every 6 hours to keep portal sessions alive
- **Daily briefing**: Runs at 7 AM or when Mac wakes from sleep

Plist files are installed in `~/Library/LaunchAgents/`.

---

## Project Structure

```
financial-news-agent/
├── run_pipeline.py          # V3 pipeline orchestrator
├── refresh_cookies.py       # Automated cookie refresh (launchd)
│
├── # Document Processing
├── schemas.py               # Document, Chunk, Claim dataclasses
├── normalizer.py            # Raw content → Document (all sources)
├── chunker.py               # Document → Chunks (~500 tokens)
├── classifier.py            # 4-category classification + filter_irrelevant() (LLM)
├── macro_news.py            # RSS macro news collection (Reuters, CNBC)
│
├── # Claims & Drift
├── claim_extractor.py       # Chunk → atomic claims + sort_claims_by_priority() (LLM)
├── claim_tracker.py         # Historical claim storage (SQLite)
├── drift_detector.py        # Cross-time belief shift detection (no LLM)
│
├── # Synthesis & Output
├── tier2_synthesizer.py     # Section 2 narrative synthesis (LLM)
├── briefing_renderer.py     # V3 4-section <5 page briefing
├── drilldown.py             # Claim traceability and provenance
│
├── # Configuration
├── config.py                # Tickers, analysts, themes, source toggles
├── analyst_config_tmt.py    # Category/subtopic weights, source credibility
├── scope_filter.py          # Sector/ticker/analyst scoping (no LLM)
│
├── # Data Ingestion (Multi-Portal Framework)
├── base_scraper.py          # Abstract base class for portal scrapers
├── portal_registry.py       # Registry for managing multiple portals
├── jefferies_scraper.py     # Jefferies portal scraper
├── morgan_stanley_scraper.py # Morgan Stanley Matrix scraper
├── goldman_scraper.py       # Goldman Sachs scraper
├── bernstein_scraper.py     # Bernstein Research scraper
├── ubs_scraper.py           # UBS scraper
├── arete_scraper.py         # Arete Research scraper
├── cookie_manager.py        # Cookie persistence per portal
├── report_tracker.py        # SQLite deduplication
│
├── # Podcast Ingestion Framework
├── base_podcast.py          # Abstract base class for podcast handlers
├── podcast_registry.py      # Registry for managing multiple podcasts
├── youtube_podcast.py       # YouTube-based podcasts (All-In)
├── rss_podcast.py           # RSS-based podcasts (a16z, BG2, Acquired)
├── podcast_tracker.py       # SQLite episode deduplication
│
├── # Substack Ingestion
├── substack_feishu.py       # Feishu Mail API → Substack article extraction
│
├── # Deprecated (kept on disk, removed from pipeline)
├── tier_router.py           # Replaced by classifier category routing
├── implication_router.py    # No Tier 3 section in V3
├── triage.py                # Replaced by filter_irrelevant()
│
├── # Social Media (Future)
├── x_social.py              # X/Twitter feed handler (requires paid API)
│
├── requirements.txt
├── .env                     # API keys (gitignored)
├── data/                    # Runtime data (gitignored)
│   ├── briefings/           # Generated daily briefings (.md)
│   ├── reports/             # Downloaded PDFs by portal/date
│   └── cookies/             # Portal session cookies
└── logs/                    # Pipeline logs (gitignored)
```

---

## Coverage

**Primary Tickers (High Priority):**
META, GOOGL, AMZN, AAPL, BABA, 700.HK, MSFT, CRWD, ZS, PANW, NET, DDOG, SNOW, MDB

**Watchlist Tickers (Medium Priority):**
NFLX, SPOT, U, APP, RBLX, ORCL, PLTR, SHOP

**Trusted Analysts:**
Dynamically determined by who you follow in each portal ("Followed Notifications"). No manual config needed — follow analysts directly in each portal's UI.

**Investment Themes:**
- Digital Transformation
- AI & Machine Learning
- Cybersecurity

---

## Current Status

- [x] V3 4-section briefing pipeline (Sections 1+2 live, 3+4 stubbed)
- [x] 4-category classifier (tracked_ticker, tmt_sector, macro, irrelevant)
- [x] Off-coverage tickers route to TMT Sector-Level, not Tracked Tickers (classifier downgrade + renderer fix)
- [x] Claims sorted by priority (breaking > contrarian first, no hard cap)
- [x] High-alert events always shown uncapped in Section 1 (earnings, guidance, M&A, regulatory, leadership, operational metrics)
- [x] Section 2 LLM narrative synthesis with source credibility, analyst prose context, and secondaries implications subsection
- [x] Independent sources (Substack, podcast) weighted equally to sell-side in synthesis
- [x] Sell-side structural positive bias surfaced explicitly in Section 2 prompt
- [x] Morgan Stanley Matrix scraping (Selenium + email verification)
- [x] Goldman Sachs scraping (Selenium)
- [x] Bernstein scraping (Selenium)
- [x] Arete scraping (Selenium + CloudFront PDF download)
- [x] UBS scraping (Selenium)
- [x] Substack ingestion (Feishu Mail API)
- [x] PDF text extraction (pdfplumber + PyPDF2 fallback)
- [x] Document normalization and chunking
- [x] Podcast ingestion (All-In, a16z, BG2 Pod, Acquired)
- [x] Historical claim tracking (SQLite-backed)
- [x] Sentiment drift detection (confidence shifts, belief flips, new disagreement)
- [x] Automated cookie refresh (launchd - runs at login + every 6 hours)
- [x] Daily briefing automation (launchd - 7 AM daily)
- [x] Macro news collection (Reuters, CNBC via RSS)
- [x] Document-level pre-filter (save LLM calls on non-TMT docs)
- [ ] Jefferies scraping (auth issues — SSO cookies expire frequently)
- [ ] Section 3: Macro Connections (Phase 2)
- [ ] Section 4: Longitudinal Delta Detection rendering (Phase 2)
- [ ] X (Twitter) ingestion (module ready, requires paid API tier)
- [ ] Email delivery
