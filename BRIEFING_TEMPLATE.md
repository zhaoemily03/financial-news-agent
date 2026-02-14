# One-Stop Shop Financial Digest — Logic & Design

**Objective Function:** A one-stop-shop to test, challenge, and formulate convictions for maximizing financial return in secondaries trading portfolio

**Purpose:** Comprehensive TMT and ticker digest from sell-side, podcast, blog, social media

**Maximum Length:** 5 pages | **Target Read Time:** <15 minutes

---

## Information Stream Tiers (easiest → hardest access)

1. Open access
2. Member (free)
3. Member (paid)
4. Member with two-factor authentication

---

## Briefing Layout

### Section 1: Objective Breaking News

- **Per-ticker updates:** Explicit update on each ticker being tracked and in the watchlist. If no updates, say "No Update"
- **TMT sector-level update:** Sector-wide developments affecting coverage universe

### Section 2: Synthesis Across Sources

- Look at *all* claims surfaced and ask LLM: where do perspectives agree and where do they diverge, considering the biases and credibility of each source
- **Written in narrative style** (not bullet points)

### Section 3: Macro Connections

- Collect global news using keywords that have implications on stock performance
- Economic and geopolitical news: unemployment, US election cycles and federal policy, consumer confidence, trade relations and tariffs

### Section 4: Longitudinal Delta Detection

- **Sentiment drift** against previously logged and filed claims by this tool
- Check the synthesis of each day for the past month, or the same time in the previous couple earning cycles, to see if language or sentiment has changed (confidence, belief, importance)
- Later: check each ticker longitudinally, each thesis longitudinally

---

## Pipeline

Scrape → Normalize → Chunk → Classify (ticker, TMT, macro, or discard as irrelevant) → Atomize classified chunks into claims for Section 1 → File and organize claims under their respective classification with date stamp and source → Synthesize using LLM for Section 2

---

## Development Phases

| Phase | Focus |
|-------|-------|
| **Phase 1** | Core pipeline (current) |
| **Phase 2** | Macro Connections section → Longitudinal Delta Detection section |
| **Phase 3** | Thesis stress-testing: comparing "house views" to current day news to "historical experience" |

---

## Format Guidelines

- **Source attribution** — Brief citation (e.g., "JPM, 1/21" or "Substack: Author Name")
- **Per-ticker completeness** — Every tracked ticker gets a line, even if "No Update"
- **Section 2 is narrative** — Prose, not bullets
- **Prioritization** — Most critical items first within each section
- **Visual hierarchy** — Bold for key terms, tickers, catalysts
