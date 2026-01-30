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

**Pipeline:** Collect → Normalize → Chunk → Classify → Triage → Claims → Route → Synthesize → Render → Drill-down

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
| `tier_router.py` | Rule-based Tier 1/2/3 | No |
| `tier2_synthesizer.py` | Cross-claim synthesis | **Yes** |
| `implication_router.py` | Tier 3 indexing | No |
| `briefing_renderer.py` | <5 page output | No |
| `drilldown.py` | Claim provenance | No |

### Data Ingestion

| Module | Purpose |
|--------|---------|
| `jefferies_scraper.py` | Selenium-based PDF scraper |
| `cookie_manager.py` | Cookie persistence |
| `report_tracker.py` | SQLite deduplication |

---

## Configuration

| File | Purpose |
|------|---------|
| `config.py` | Tickers, analysts, themes, relevance threshold |
| `analyst_config_tmt.py` | TMT-specific topic weights and source credibility |
| `.env` | API keys (OPENAI_API_KEY) — gitignored |
| `data/cookies.json` | Jefferies session cookies — gitignored |

### Key Config Values

- **RELEVANCE_THRESHOLD**: 0.7 (chunks below this are triaged out)
- **BRIEFING_DAYS**: 5 (only process reports from last 5 days)
- **Primary tickers**: META, GOOGL, AMZN, AAPL, BABA, 700.HK, MSFT, CRWD, ZS, PANW, NET, DDOG, SNOW, MDB
- **Trusted analysts**: Brent Thill, Joseph Gallo (Jefferies)

---

## Jefferies Scraper Workflow

1. Login (cookies loaded from `data/cookies.json`)
2. Click ADV SEARCH
3. Type analyst name into the analyst input field
4. Click matching dropdown option
5. Click SEARCH button (below all filter panels)
6. Extract report links and dates from results
7. Navigate to report page, extract PDF URL from iframe `src`
8. Download PDF via requests session with synced Selenium cookies

**Technical note:** Jefferies portal is a Vue.js/Vuetify SPA requiring JavaScript rendering. Simple HTTP requests return empty HTML.

---

## Current Status

- [x] Jefferies portal scraping (Selenium + SSO cookies)
- [x] PDF text extraction (pdfplumber + PyPDF2 fallback)
- [x] Document normalization and chunking
- [x] LLM classification (topic, ticker, content type)
- [x] Analyst-configurable triage with deduplication
- [x] Claim extraction with judgment hooks
- [x] Rule-based tier routing (Tier 1/2/3)
- [x] Tier 2 synthesis (agreement/disagreement/deltas)
- [x] Tier 3 implication indexing
- [x] <5 page briefing renderer
- [x] Drill-down integrity (full claim provenance)
- [ ] End-to-end pipeline integration test
- [ ] Substack ingestion
- [ ] Email delivery
- [ ] Cron job scheduling (7 AM daily)
