# Financial News Agent

A judgment-first research system for portfolio analysts.

---

## System Purpose

This tool exists to **minimize research burden** and **maximize human judgment**.

| AI Does | Human Does |
|---------|------------|
| Organize and compress information | Form conviction |
| Surface patterns and contradictions | Challenge claims |
| Enforce brevity by design | Decide actions |

The system is explicitly **not** designed to tell you what to think. It surfaces what might matter and lets you decide.

---

## Judgment-First Philosophy

Every design decision follows this principle:

> **Claims must be easy to agree with, disagree with, or ignore consciously.**

This means:

- **Contradictions are first-class outputs.** If analysts disagree, you see both sides.
- **Uncertainty is preserved, not hidden.** "May", "could", "estimates" stay in the output.
- **Brevity is enforced by design.** <5 pages daily, truncate Tier 3 first.
- **No conviction imposed.** The system describes; you decide.

What the system will never do:
- Recommend buy/sell/hold
- Rank importance globally (only locally within tiers)
- Use words like "bullish", "bearish", "should"
- Hide disagreement to appear more confident

---

## High-Level Pipeline (End-to-End)

```
Source PDFs → Normalize → Chunk → Classify → Triage → Claims → Route → Synthesize → Render → Drill-down
```

| Step | Module | AI? | Description |
|------|--------|-----|-------------|
| 1. **Collect** | `jefferies_scraper.py` | No | Fetch PDFs from trusted sources |
| 2. **Normalize** | `normalizer.py` | No | Convert to structured `Document` objects |
| 3. **Chunk** | `chunker.py` | No | Split into atomic units (~500 tokens) |
| 4. **Classify** | `classifier.py` | **Yes** | Tag topic, ticker, content type (descriptive only) |
| 5. **Triage** | `triage.py` | No | Apply analyst relevance rules, deduplicate |
| 6. **Extract Claims** | `claim_extractor.py` | **Yes** | Convert chunks to atomic, challengeable claims |
| 7. **Route Tiers** | `tier_router.py` | No | Assign Tier 1/2/3 using deterministic rules |
| 8. **Synthesize** | `tier2_synthesizer.py` | **Yes** | Surface agreement, disagreement, deltas |
| 9. **Index Tier 3** | `implication_router.py` | No | Map claims to coverage (index, not analysis) |
| 10. **Render** | `briefing_renderer.py` | No | Fixed-format <5 page daily briefing |
| 11. **Drill-down** | `drilldown.py` | No | Link claims to source text, PDF page, related claims |

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
| **Relevance Decisions** | Analyst-configurable rules in `triage.py`. Deterministic, auditable. |
| **Prioritization Logic** | Tier routing is rule-based in `tier_router.py`. No LLM black box. |
| **Output Formatting** | Template-driven rendering. Consistent every day. |
| **Conviction or Recommendations** | Humans decide. System describes. |

This separation ensures the system is **auditable** and **challengeable**. When an analyst asks "Why is this here?", the answer is always traceable to explicit rules or source text—never "the AI thought it was important."

---

## Briefing Output Structure

**Hard constraint:** <5 pages, consumable in <15 minutes.

### Tier 1: What Demands Attention Today
*5-10 bullets max*

- **Something Broke Overnight** — Breaking news, earnings misses/beats
- **Something Is About to Happen** — Upcoming catalysts, earnings dates
- **Something Contradicts What I Believe** — Contrarian signals, challenges to thesis

Each bullet has an explicit reason tag: `[BREAKING]`, `[UPCOMING]`, `[CONTRADICTS CONSENSUS]`

### Tier 2: What's the Signal from the Noise
*3-5 synthesized bullets*

- Where analysts are **agreeing**
- Where analysts are **disagreeing**
- What **changed** vs prior day

### Tier 3: How Does This Affect My Work
*Grouped by stock/theme, minimal bullets*

- Implications for covered stocks
- Implications for investment theses
- Drill-down links only (depth on demand)

**Truncation rule:** If output exceeds ~5 pages, Tier 3 is truncated first.

---

## Claim Judgment Hooks

Every claim carries metadata to support human judgment:

| Field | Values | Purpose |
|-------|--------|---------|
| `confidence_level` | low / medium / high | How confident is the *source* (not the AI) |
| `time_sensitivity` | breaking / upcoming / ongoing | When does this matter |
| `belief_pressure` | confirms_consensus / contradicts_consensus / contradicts_prior_assumptions / unclear | How this relates to expectations |

These hooks let you quickly filter for:
- Contrarian signals (`contradicts_*`)
- Time-sensitive items (`breaking`, `upcoming`)
- High-conviction sources (`confidence_level = high`)

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

## Supported Inputs

### Currently Implemented

| Source | Status | Notes |
|--------|--------|-------|
| **Jefferies Research** | ✅ Working | Selenium scraper with SSO cookie auth |

### Planned (Not Yet Implemented)

| Source | Status | Notes |
|--------|--------|-------|
| Substack | 🔲 Placeholder | RSS-based ingestion planned |
| X (Twitter) | 🔲 Placeholder | API integration planned |
| YouTube | 🔲 Placeholder | Transcript extraction planned |
| Podcasts | 🔲 Placeholder | Audio transcription planned |
| Other sell-side (JPM, etc.) | 🔲 Placeholder | Portal-specific scrapers needed |

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
# Run the full pipeline
python daily_briefing.py

# Run the Flask dashboard
python app.py

# Test individual components
python claim_extractor.py
python tier_router.py
python briefing_renderer.py
python drilldown.py
```

---

## Project Structure

```
financial-news-agent/
├── app.py                   # Flask web dashboard
├── daily_briefing.py        # Pipeline orchestrator
│
├── # Document Processing
├── schemas.py               # Document, Chunk, Claim dataclasses
├── normalizer.py            # Raw content → Document
├── chunker.py               # Document → Chunks (~500 tokens)
├── classifier.py            # Chunk classification (LLM)
│
├── # Relevance & Claims
├── triage.py                # Analyst-configurable filtering (no LLM)
├── claim_extractor.py       # Chunk → atomic claims with judgment hooks (LLM)
│
├── # Tier Routing & Synthesis
├── tier_router.py           # Rule-based Tier 1/2/3 assignment (no LLM)
├── tier2_synthesizer.py     # Cross-claim synthesis (LLM)
├── implication_router.py    # Tier 3 indexing to coverage
│
├── # Output
├── briefing_renderer.py     # <5 page daily briefing renderer
├── drilldown.py             # Claim traceability and provenance
│
├── # Configuration
├── config.py                # Tickers, analysts, themes
├── analyst_config_tmt.py    # TMT analyst-specific config
│
├── # Data Ingestion
├── jefferies_scraper.py     # Selenium-based PDF scraper
├── cookie_manager.py        # Cookie persistence
├── report_tracker.py        # SQLite deduplication
│
├── requirements.txt
├── .env                     # API keys (gitignored)
└── data/                    # Runtime data (gitignored)
    ├── cookies.json
    └── processed_content.db
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
