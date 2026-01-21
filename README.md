# Financial News Agent

An automated intelligence system that ingests sell-side research, Substack articles, and other financial content sources, then generates a structured daily briefing for analysts.

## Overview

This tool automatically:
1. Monitors multiple content sources (sell-side research portals, Substack, etc.)
2. Extracts content relevant to tracked tickers and investment themes
3. Synthesizes insights across sources
4. Generates a structured 3-tier daily briefing (max 5 pages)
5. Delivers via email on a scheduled basis

## Briefing Structure

**Tier 1: What Demands Attention Today** (Urgent, can't miss)
- Something broke overnight
- Something is about to happen
- Something contradicts what I believe

**Tier 2: What's the Signal from the Noise** (Important, not urgent)
- Synthesis across all reports
- Where analysts agree/disagree
- Quantitative vs qualitative divergences

**Tier 3: How Does This Affect My Work** (Reference)
- Implications for covered stocks
- Implications for investment theses
- New areas worth exploring

## Setup Instructions

### 1. Install Dependencies
```bash
# Activate virtual environment
source venv/bin/activate

# Dependencies already installed if you followed initial setup
pip install -r requirements.txt
```

### 2. Configure Your Coverage
Edit `config.py` to set:
- `TICKERS`: List of stocks you cover
- `INVESTMENT_THEMES`: Themes/theses you're tracking
- `SUBSTACK_AUTHORS`: Authors to monitor
- `EMAIL_CONFIG`: Email delivery settings

### 3. Configure Authentication
Edit `.env` file with:
- `OPENAI_API_KEY`: Your OpenAI API key (already set)
- Portal credentials for JP Morgan and other research sources
- Substack login credentials (if needed)
- Email SMTP settings

### 4. Gather Analyst Requirements
Review `ANALYST_REQUIREMENTS.md` for complete checklist of information needed from analysts.

## Current Status

**Phase 1 (In Progress):**
- ✅ Basic Flask web interface
- ✅ OpenAI integration
- ✅ Briefing template structure
- ✅ Configuration framework
- ⏳ PDF extraction for sell-side reports
- ⏳ Substack RSS/scraping
- ⏳ Automated login flows (Selenium/Playwright)
- ⏳ Email delivery system
- ⏳ Content deduplication and storage
- ⏳ Scheduled cron job

**Phase 2 (Future):**
- YouTube video transcripts
- Twitter/X posts
- Podcast transcripts

## Project Structure

```
financial-news-agent/
├── app.py                      # Flask web interface
├── briefing_generator.py       # 3-tier briefing logic
├── config.py                   # Analyst configuration (EDIT THIS)
├── .env                        # API keys and credentials (EDIT THIS)
├── requirements.txt            # Python dependencies
├── ANALYST_REQUIREMENTS.md     # Requirements gathering checklist
├── BRIEFING_TEMPLATE.md        # Briefing format specification
├── static/                     # Frontend assets
├── templates/                  # HTML templates
└── data/                       # Reports and processed content (to be created)
```

## Running the Application

### Manual Web Interface (Current)
```bash
source venv/bin/activate
python app.py
```
Open browser to `http://127.0.0.1:5000`

### Automated Daily Briefing (Coming Soon)
```bash
python daily_briefing.py  # Manual trigger for testing
```

Configure cron job for automatic daily execution:
```bash
# Edit crontab
crontab -e

# Add line to run at 7:00 AM daily
0 7 * * * cd /path/to/financial-news-agent && /path/to/venv/bin/python daily_briefing.py
```

## Next Steps

1. Complete `ANALYST_REQUIREMENTS.md` checklist
2. Build content ingestion modules (PDF, Substack, portal scrapers)
3. Implement email delivery
4. Test with real data sources
5. Deploy automated scheduling
