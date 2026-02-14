#!/usr/bin/env python3
"""
Claim Viewer — Inspect stored claims for transparency.

Shows what the system has tracked so the analyst can see:
- What claims exist per ticker/author/date
- Confidence levels and belief pressure
- What's feeding drift detection

Usage:
    python view_claims.py                    # All claims from last 7 days
    python view_claims.py --days 30          # Last 30 days
    python view_claims.py --ticker META      # Filter by ticker
    python view_claims.py --author "Brent"   # Filter by author
    python view_claims.py --date 2026-02-05  # Specific date
    python view_claims.py --stats            # Summary statistics only
"""

import argparse
import sqlite3
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict


DB_PATH = 'data/claim_history.db'


def get_claims(days=7, ticker=None, author=None, date_str=None):
    """Query claims from the database."""
    if not os.path.exists(DB_PATH):
        print(f"No claim database found at {DB_PATH}")
        print("Run the pipeline at least once to build the claim history.")
        return []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    conditions = []
    params = []

    if date_str:
        conditions.append("date_stored = ?")
        params.append(date_str)
    else:
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        conditions.append("date_stored >= ?")
        params.append(cutoff)

    if ticker:
        conditions.append("ticker = ?")
        params.append(ticker.upper())

    if author:
        conditions.append("author LIKE ?")
        params.append(f"%{author}%")

    where = " AND ".join(conditions) if conditions else "1=1"

    cursor.execute(f'''
        SELECT claim_id, doc_id, ticker, author, source, claim_type,
               bullets, confidence_level, belief_pressure, time_sensitivity,
               date_stored, source_citation
        FROM claims
        WHERE {where}
        ORDER BY date_stored DESC, ticker, source
    ''', params)

    rows = cursor.fetchall()
    conn.close()
    return rows


def print_claims(rows):
    """Print claims grouped by date, then ticker."""
    if not rows:
        print("\nNo claims found matching your filters.")
        return

    # Group by date
    by_date = defaultdict(list)
    for row in rows:
        by_date[row[10]].append(row)

    for date_str in sorted(by_date.keys(), reverse=True):
        claims = by_date[date_str]
        print(f"\n{'='*60}")
        print(f"  {date_str}  ({len(claims)} claims)")
        print(f"{'='*60}")

        # Group by ticker within date
        by_ticker = defaultdict(list)
        no_ticker = []
        for row in claims:
            if row[2]:  # ticker
                by_ticker[row[2]].append(row)
            else:
                no_ticker.append(row)

        for ticker in sorted(by_ticker.keys()):
            ticker_claims = by_ticker[ticker]
            print(f"\n  {ticker} ({len(ticker_claims)} claims)")
            print(f"  {'-'*40}")
            for row in ticker_claims:
                _print_claim(row)

        if no_ticker:
            print(f"\n  [No ticker] ({len(no_ticker)} claims)")
            print(f"  {'-'*40}")
            for row in no_ticker:
                _print_claim(row)


def _print_claim(row):
    """Print a single claim row."""
    claim_id, doc_id, ticker, author, source, claim_type, \
        bullets_json, confidence, pressure, sensitivity, \
        date_stored, citation = row

    bullets = json.loads(bullets_json) if bullets_json else []

    # Confidence indicator
    conf_icon = {'high': '+', 'medium': '~', 'low': '-'}.get(confidence, '?')

    # Belief pressure indicator
    pressure_icon = {
        'confirms_consensus': '=',
        'contradicts_consensus': '!',
        'contradicts_prior_assumptions': '!',
        'unclear': '?',
    }.get(pressure, ' ')

    for bullet in bullets:
        print(f"    [{conf_icon}{pressure_icon}] {bullet}")

    # Metadata line
    meta_parts = []
    if source:
        meta_parts.append(source)
    if author:
        meta_parts.append(author)
    meta_parts.append(f"confidence={confidence}")
    meta_parts.append(f"pressure={pressure}")
    if sensitivity != 'ongoing':
        meta_parts.append(f"time={sensitivity}")

    print(f"        {', '.join(meta_parts)}")


def print_stats():
    """Print summary statistics."""
    if not os.path.exists(DB_PATH):
        print(f"No claim database found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Total claims
    cursor.execute('SELECT COUNT(*) FROM claims')
    total = cursor.fetchone()[0]

    # Claims by date
    cursor.execute('''
        SELECT date_stored, COUNT(*) FROM claims
        GROUP BY date_stored ORDER BY date_stored DESC
    ''')
    by_date = cursor.fetchall()

    # Claims by ticker
    cursor.execute('''
        SELECT ticker, COUNT(*) FROM claims
        WHERE ticker IS NOT NULL
        GROUP BY ticker ORDER BY COUNT(*) DESC
    ''')
    by_ticker = cursor.fetchall()

    # Claims by source
    cursor.execute('''
        SELECT source, COUNT(*) FROM claims
        WHERE source IS NOT NULL
        GROUP BY source ORDER BY COUNT(*) DESC
    ''')
    by_source = cursor.fetchall()

    # Claims by belief pressure
    cursor.execute('''
        SELECT belief_pressure, COUNT(*) FROM claims
        GROUP BY belief_pressure ORDER BY COUNT(*) DESC
    ''')
    by_pressure = cursor.fetchall()

    # Claims by confidence
    cursor.execute('''
        SELECT confidence_level, COUNT(*) FROM claims
        GROUP BY confidence_level ORDER BY COUNT(*) DESC
    ''')
    by_confidence = cursor.fetchall()

    conn.close()

    print(f"\n{'='*60}")
    print(f"  CLAIM HISTORY — Summary")
    print(f"{'='*60}")
    print(f"\n  Total claims: {total}")
    print(f"  Days tracked: {len(by_date)}")

    print(f"\n  By date:")
    for date_str, count in by_date[:10]:
        print(f"    {date_str}: {count} claims")

    print(f"\n  By ticker:")
    for ticker, count in by_ticker[:15]:
        print(f"    {ticker}: {count}")

    print(f"\n  By source:")
    for source, count in by_source[:10]:
        print(f"    {source}: {count}")

    print(f"\n  By belief pressure:")
    for pressure, count in by_pressure:
        print(f"    {pressure}: {count}")

    print(f"\n  By confidence:")
    for conf, count in by_confidence:
        print(f"    {conf}: {count}")

    # Legend
    print(f"\n  Legend:")
    print(f"    [+=] high confidence, confirms consensus")
    print(f"    [~!] medium confidence, contradicts consensus")
    print(f"    [-?] low confidence, unclear pressure")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="View stored claims")
    parser.add_argument('--days', type=int, default=7, help='Days to look back (default: 7)')
    parser.add_argument('--ticker', type=str, help='Filter by ticker (e.g., META)')
    parser.add_argument('--author', type=str, help='Filter by author name')
    parser.add_argument('--date', type=str, help='Filter by specific date (YYYY-MM-DD)')
    parser.add_argument('--stats', action='store_true', help='Show summary statistics only')
    args = parser.parse_args()

    if args.stats:
        print_stats()
    else:
        rows = get_claims(
            days=args.days,
            ticker=args.ticker,
            author=args.author,
            date_str=args.date,
        )
        print_claims(rows)
        print(f"\n  {len(rows)} claims shown")
        print(f"  Use --stats for summary, --ticker META to filter")
