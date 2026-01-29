"""
Daily Briefing Orchestrator
Runs the full pipeline: scrape → summarize → synthesize → output briefing
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from config import TRUSTED_ANALYSTS, ALL_TICKERS, INVESTMENT_THEMES
from jefferies_scraper import JefferiesScraper
from briefing_generator import BriefingGenerator, generate_email_html

load_dotenv()

BRIEFING_DAYS = 5  # Only include reports from last N days


def run_daily_briefing():
    """Full pipeline: scrape reports → summarize → generate 3-tier briefing."""
    print(f"\n{'='*60}")
    print(f"  Daily Briefing — {datetime.now().strftime('%B %d, %Y')}")
    print(f"{'='*60}\n")

    # --- Step 1: Scrape reports from Jefferies ---
    print("STEP 1: Fetching reports from Jefferies...\n")
    scraper = JefferiesScraper(headless=True)
    analysts = TRUSTED_ANALYSTS.get('jefferies', [])
    reports = scraper.get_reports_by_analysts(analysts, max_per_analyst=10, days=BRIEFING_DAYS)

    if not reports:
        print("\nNo new reports found. Briefing not generated.")
        return None

    print(f"\n{'='*60}")
    print(f"STEP 2: Summarizing {len(reports)} reports with GPT-4...\n")

    # --- Step 2: Summarize each report ---
    generator = BriefingGenerator()
    summaries = []
    for i, report in enumerate(reports, 1):
        print(f"  [{i}/{len(reports)}] Summarizing: {report['title'][:60]}...")
        summary = generator.summarize_report(report)
        summaries.append(summary)
        print(f"  ✓ Done")

    # --- Step 3: Generate 3-tier briefing ---
    print(f"\n{'='*60}")
    print("STEP 3: Generating 3-tier briefing...\n")

    theme_names = [t['name'] for t in INVESTMENT_THEMES]
    briefing = generator.generate_briefing(summaries, ALL_TICKERS, theme_names)

    # --- Step 4: Save output ---
    date_stamp = datetime.now().strftime('%Y-%m-%d')
    os.makedirs('data/briefings', exist_ok=True)

    # Save markdown
    md_path = f'data/briefings/briefing_{date_stamp}.md'
    with open(md_path, 'w') as f:
        f.write(briefing)
    print(f"✓ Saved markdown: {md_path}")

    # Save HTML
    html_path = f'data/briefings/briefing_{date_stamp}.html'
    with open(html_path, 'w') as f:
        f.write(generate_email_html(briefing))
    print(f"✓ Saved HTML:     {html_path}")

    # Print briefing
    print(f"\n{'='*60}")
    print(briefing)
    print(f"{'='*60}\n")

    return briefing


if __name__ == "__main__":
    run_daily_briefing()
