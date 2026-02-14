# Financial News Agent

A belief-drift detection system for TMT portfolio analysts.

---

## System Purpose

This tool exists to **surface belief changes and sentiment drift** — the inputs that actually drive fundamental buy decisions — while keeping breaking news and structural events visible.

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
- **Brevity is enforced by design.** <5 pages daily, truncate Tier 3 first.
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
Collect → Normalize → Pre-filter → Chunk → Classify+Filter → Claims+Cap → File Claims → Drift → Synthesize → Render
```

| Step | Module | AI? | Description |
|------|--------|-----|-------------|
| 1. **Collect** | `portal_registry.py` + `macro_news.py` | No | Fetch portals + podcasts + macro RSS |
| 2. **Normalize** | `normalizer.py` | No | Convert to structured `Document` objects |
| 2b. **Pre-filter** | `run_pipeline.py` | No | Drop non-TMT docs by ticker/keyword before LLM |
| 3. **Chunk** | `chunker.py` | No | Split into atomic units (~500 tokens) |
| 4. **Classify+Filter** | `classifier.py` | **Yes** | 4-category classification + `filter_irrelevant()` |
| 5. **Claims+Cap** | `claim_extractor.py` | **Yes** | Extract atomic claims, cap at 3 per ticker/group |
| 5b. **File Claims** | `claim_tracker.py` | No | Store claims in SQLite for historical tracking |
| 5c. **Drift Detect** | `drift_detector.py` | No | Compare today's claims against history for belief shifts |
| 6. **Synthesize+Render** | `tier2_synthesizer.py` + `briefing_renderer.py` | **Yes** | Section 2 narrative + 4-section briefing output |

**Removed stages (V3):** Chunk scope (4b), Triage (5), Claim scope (6b), Tier routing (7), Tier 3 indexing (9). The classifier's `irrelevant` category + per-ticker claim cap replace these.

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
| **Relevance Filtering** | Classifier assigns `irrelevant` category; `filter_irrelevant()` drops deterministically. |
| **Claim Capping** | `cap_claims_per_group()` keeps max 3 per ticker/group. Rule-based priority sort. |
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
- **Tracked tickers**: Iterates ALL tickers from `config.ALL_TICKERS`. Max 3 claims per ticker, sorted by time sensitivity then belief pressure. Shows "No Update" for tickers with nothing.
- **TMT sector**: Groups `tmt_sector` claims by event type.

### Section 2: Synthesis Across Sources
- LLM-generated narrative prose (not bullets)
- Considers source credibility from `analyst_config_tmt.SOURCE_CREDIBILITY`
- Surfaces where sources agree and disagree
- No thesis language — describes patterns, doesn't recommend

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

Scope filtering is simplified in V3 to two levels:

1. **Document pre-filter (2b)** — Drops entire documents with no TMT relevance before classification
2. **Classify + Filter (4)** — Classifier assigns `irrelevant` category; `filter_irrelevant()` drops them. Per-ticker claim cap (max 3) enforces brevity.

Old stages removed: chunk scope (4b), triage (5), claim scope (6b). The classifier's `irrelevant` category replaces all three.

### Thin Day Detection

When fewer than 3 claims pass the filter, the system marks it as a "thin day" rather than padding with irrelevant content.

---

## Supported Inputs

### Multi-Portal Framework

The system uses a **PortalRegistry** to manage multiple sell-side research portals. Each portal has its own scraper that inherits from `BaseScraper`, sharing common functionality:

- **Dynamic cookie refresh** — Authenticate once, cookies persist and auto-refresh
- **Notification-based discovery** — Pulls from "Followed Notifications" (analysts you follow)
- **Crash resilience** — One portal failure doesn't crash the entire collection
- **Unified result format** — All scrapers return the same structure

### Currently Implemented

| Source | Status | Notes |
|--------|--------|-------|
| **Jefferies Research** | 👎 Not working | continues needing manual reauthentication
| **Morgan Stanley Matrix** | ✅ Working | Selenium scraper with email verification auth |

### Planned Sell-Side Portals

| Source | Status | Notes |
|--------|--------|-------|
| JP Morgan | 🔲 Template ready | Enable in `config.py`, implement `jpmorgan_scraper.py` |
| Goldman Sachs | 🔲 Template ready | Enable in `config.py`, implement `goldman_scraper.py` |

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
| **BG2 Pod** | Brad Gerstner, Bill Gurley | Apple/Spotify | Episode descriptions |
| **Acquired** | Ben Gilbert, David Rosenthal | acquired.fm | Episode descriptions |

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

### Other Sources (Planned)

| Source | Status | Notes |
|--------|--------|-------|
| Substack | 🔲 Placeholder | RSS-based ingestion planned |
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
| `config.py` | Tickers, trusted analysts, investment themes, relevance threshold |
| `analyst_config_tmt.py` | TMT-specific topic weights and source credibility |
| `.env` | API keys (OPENAI_API_KEY) — not tracked in git |
| `data/cookies.json` | Jefferies session cookies — not tracked in git |

### Cookie Setup

After logging into Jefferies in your browser, export your session cookies to `data/cookies.json`. The scraper uses Shibboleth SSO cookies to authenticate.

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
├── run_pipeline.py          # V3 pipeline orchestrator (7 stages)
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
├── claim_extractor.py       # Chunk → atomic claims + cap_claims_per_group() (LLM)
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
├── cookie_manager.py        # Cookie persistence per portal
├── report_tracker.py        # SQLite deduplication
│
├── # Podcast Ingestion Framework
├── base_podcast.py          # Abstract base class for podcast handlers
├── podcast_registry.py      # Registry for managing multiple podcasts
├── youtube_podcast.py       # YouTube-based podcasts (All-In)
├── rss_podcast.py           # RSS-based podcasts (BG2, Acquired)
├── podcast_tracker.py       # SQLite episode deduplication
│
├── # Deprecated (kept on disk, removed from pipeline)
├── tier_router.py           # Replaced by classifier category routing
├── implication_router.py    # No Tier 3 section in V3
├── triage.py                # Replaced by filter_irrelevant() + claim cap
│
├── # Social Media (Future)
├── x_social.py              # X/Twitter feed handler (requires paid API)
│
├── requirements.txt
├── .env                     # API keys (gitignored)
├── data/                    # Runtime data (gitignored)
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
- Brent Thill (Jefferies, Internet/Software)
- Joseph Gallo (Jefferies, Software/Security)

**Investment Themes:**
- Digital Transformation
- AI & Machine Learning
- Cybersecurity

---

## Current Status

- [x] V3 4-section briefing pipeline (Sections 1+2 live, 3+4 stubbed)
- [x] 4-category classifier (tracked_ticker, tmt_sector, macro, irrelevant)
- [x] Per-ticker claim cap (max 3 most important per group)
- [x] Section 2 LLM narrative synthesis with source credibility
- [x] Jefferies portal scraping (Selenium + SSO cookies)
- [x] Morgan Stanley Matrix scraping (Selenium + email verification)
- [x] PDF text extraction (pdfplumber + PyPDF2 fallback)
- [x] Document normalization and chunking
- [x] Podcast ingestion (All-In, BG2 Pod, Acquired)
- [x] Historical claim tracking (SQLite-backed)
- [x] Sentiment drift detection (confidence shifts, belief flips, new disagreement)
- [x] Automated cookie refresh (launchd - runs at login + every 6 hours)
- [x] Daily briefing automation (launchd - 7 AM daily)
- [x] Macro news collection (Reuters, CNBC via RSS)
- [x] Document-level pre-filter (save LLM calls on non-TMT docs)
- [ ] Section 3: Macro Connections (Phase 2)
- [ ] Section 4: Longitudinal Delta Detection rendering (Phase 2)
- [ ] X (Twitter) ingestion (module ready, requires paid API tier)
- [ ] Substack ingestion
- [ ] Email delivery
