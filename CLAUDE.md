# CLAUDE.md

# through consulting Chat-GPT for best design
Primary Product Constraint

The default daily analyst output must be:

Consumable in under 15 minutes

Under 5 pages of content

Without loss of material insight

Depth must be accessed via drill-down, never by default.
Any design choice that increases verbosity or hides uncertainty should be avoided.

## Project Overview

Financial news agent that ingests sell-side research from Jefferies (and eventually other sources), extracts PDF content, and generates structured 3-tier daily briefings for a portfolio analyst via GPT-4.

## Architecture

**Pipeline:** Scrape → Summarize → Synthesize → Output

1. **Scrape** (`jefferies_scraper.py`): Selenium-based scraper authenticates to Jefferies research portal using Shibboleth SSO cookies, searches by trusted analyst via Advanced Search, extracts PDF URLs from report page iframes, downloads PDFs, and extracts text with pdfplumber/PyPDF2.
2. **Summarize** (`briefing_generator.py`): GPT-4o extracts key data from each report individually (tickers, ratings, price targets, thesis, catalysts, risks).
3. **Synthesize** (`briefing_generator.py`): GPT-4o combines all summaries into a 3-tier briefing (Urgent / Signal / Reference).
4. **Orchestrate** (`daily_briefing.py`): Runs the full pipeline end-to-end, saves markdown + HTML output.

## Key Technical Decisions

- **Selenium over requests**: Jefferies portal is a Vue.js/Vuetify SPA that requires JavaScript rendering. Simple HTTP requests return empty HTML.
- **Two-pass GPT approach**: Individual report summarization first (handles large PDFs within context window), then synthesis across all summaries.
- **iframe PDF extraction**: PDF URLs require authentication query parameters (`firmId`, `id`). The scraper navigates to each report page and extracts the iframe `src` which contains the full authenticated URL.
- **Cookie-based auth**: Cookies are manually exported from a browser session to `data/cookies.json`. The scraper loads these into Selenium, then syncs them to a requests session for PDF downloads.
- **SQLite deduplication**: `report_tracker.py` tracks processed report URLs to avoid re-processing in subsequent runs.

## File Structure

```
financial-news-agent/
├── app.py                  # Flask web dashboard
├── briefing_generator.py   # GPT-4o two-pass summarize + synthesize
├── config.py               # Tickers, analysts, themes, source config
├── cookie_manager.py       # Cookie persistence and refresh
├── daily_briefing.py       # Pipeline orchestrator
├── jefferies_scraper.py    # Selenium-based Jefferies portal scraper
├── report_tracker.py       # SQLite deduplication tracker
├── requirements.txt        # Python dependencies
├── .env                    # API keys and credentials (gitignored)
├── data/                   # Runtime data (gitignored)
│   ├── cookies.json        # Jefferies session cookies
│   ├── processed_content.db # SQLite dedup database
│   └── briefings/          # Generated briefing output (md + html)
├── templates/              # Flask HTML templates
├── static/                 # CSS/JS for dashboard
└── venv/                   # Python virtual environment
```

## Coding Conventions

- Keep code clean and concise. Use pseudocode-style comments, not verbose documentation.
- When debugging, clean up dead code and failed approaches — no long trails of unused code.
- Avoid over-engineering. Only build what's needed now.
- OpenAI SDK v1.x: Use `OpenAI()` client, not the old `openai.ChatCompletion.create()` API.
- Print progress with checkmarks (`✓`) and step indicators (`[1/5]`) for pipeline visibility.

## Configuration (`config.py`)

- **Tickers**: Primary coverage (META, GOOGL, AMZN, AAPL, BABA, 700.HK, MSFT, CRWD, ZS, PANW, NET, DDOG, SNOW, MDB) plus watchlists.
- **Trusted Analysts**: Brent Thill, Joseph Gallo (Jefferies). Reports by these analysts may list co-authors.
- **Themes**: Digital Transformation, AI & Machine Learning, Cybersecurity.
- **BRIEFING_DAYS**: Only include reports from last 5 days.

## Jefferies Scraper Workflow (8 steps)

1. Login (cookies loaded from `data/cookies.json`)
2. Click ADV SEARCH
3. Type analyst name into the analyst input field
4. Click matching dropdown option
5. Click SEARCH button (below all filter panels)
6. Extract report links and dates from results
7. Navigate to report page, extract PDF URL from iframe `src`
8. Download PDF via requests session with synced Selenium cookies

## Current Status

- [x] Jefferies scraping (Selenium + Advanced Search)
- [x] PDF extraction (pdfplumber + PyPDF2 fallback)
- [x] Deduplication (SQLite)
- [x] GPT-4o briefing generator (two-pass)
- [x] Flask dashboard
- [ ] End-to-end pipeline test (PDF download in headless mode)
- [ ] Substack ingestion
- [ ] Email delivery
- [ ] Cron job scheduling (7 AM daily)
