"""
Report Tracking System
Tracks which reports have been processed to avoid duplicates in daily briefings
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional


class ReportTracker:
    """Tracks processed reports to avoid duplicates"""

    def __init__(self, db_path='data/processed_content.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database with reports table"""
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create reports table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_url TEXT UNIQUE NOT NULL,
                report_title TEXT,
                analyst TEXT,
                source TEXT,
                publish_date TEXT,
                processed_date TEXT NOT NULL,
                included_in_briefing INTEGER DEFAULT 1,
                content_hash TEXT,
                pdf_path TEXT,
                tickers TEXT
            )
        ''')

        # Add columns if they don't exist (for existing DBs)
        try:
            cursor.execute('ALTER TABLE processed_reports ADD COLUMN pdf_path TEXT')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE processed_reports ADD COLUMN tickers TEXT')
        except:
            pass

        conn.commit()
        conn.close()

    def is_processed(self, report_url: str) -> bool:
        """
        Check if a report has already been processed

        Args:
            report_url: URL of the report

        Returns:
            True if already processed, False otherwise
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            'SELECT COUNT(*) FROM processed_reports WHERE report_url = ?',
            (report_url,)
        )
        count = cursor.fetchone()[0]

        conn.close()
        return count > 0

    def mark_as_processed(self, report: Dict):
        """
        Mark a report as processed

        Args:
            report: Report dict with url, title, analyst, source, date, pdf_path, tickers, etc.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Convert tickers list to comma-separated string
        tickers = report.get('tickers', [])
        if isinstance(tickers, list):
            tickers = ','.join(tickers)

        try:
            cursor.execute('''
                INSERT OR IGNORE INTO processed_reports
                (report_url, report_title, analyst, source, publish_date, processed_date, pdf_path, tickers)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                report.get('url'),
                report.get('title'),
                report.get('analyst'),
                report.get('source'),
                report.get('date'),
                datetime.now().isoformat(),
                report.get('pdf_path'),
                tickers
            ))

            conn.commit()
        except Exception as e:
            print(f"Error marking report as processed: {e}")
        finally:
            conn.close()

    def filter_unprocessed(self, reports: List[Dict]) -> List[Dict]:
        """
        Filter out reports that have already been processed

        Args:
            reports: List of report dicts

        Returns:
            List of reports that haven't been processed yet
        """
        unprocessed = []
        for report in reports:
            if not self.is_processed(report.get('url')):
                unprocessed.append(report)

        return unprocessed

    def get_processed_count(self, days: int = 7) -> int:
        """
        Get count of reports processed in the last N days

        Args:
            days: Number of days to look back

        Returns:
            Count of processed reports
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT COUNT(*) FROM processed_reports
            WHERE datetime(processed_date) >= datetime('now', '-' || ? || ' days')
        ''', (days,))

        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_recent_reports(self, days: int = 7, limit: int = 100) -> List[Dict]:
        """
        Get recently processed reports

        Args:
            days: Number of days to look back
            limit: Maximum number of reports to return

        Returns:
            List of report dicts
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT report_url, report_title, analyst, source, publish_date, processed_date
            FROM processed_reports
            WHERE datetime(processed_date) >= datetime('now', '-' || ? || ' days')
            ORDER BY processed_date DESC
            LIMIT ?
        ''', (days, limit))

        rows = cursor.fetchall()
        conn.close()

        reports = []
        for row in rows:
            reports.append({
                'url': row[0],
                'title': row[1],
                'analyst': row[2],
                'source': row[3],
                'date': row[4],
                'processed_date': row[5]
            })

        return reports

    # ------------------------------------------------------------------
    # Historical Pattern Analysis Methods
    # ------------------------------------------------------------------

    def get_reports_by_analyst(self, analyst: str, days: int = 30) -> List[Dict]:
        """Get all reports by a specific analyst within N days"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT report_url, report_title, analyst, source, publish_date, processed_date, pdf_path, tickers
            FROM processed_reports
            WHERE analyst LIKE ?
            AND datetime(processed_date) >= datetime('now', '-' || ? || ' days')
            ORDER BY publish_date DESC
        ''', (f'%{analyst}%', days))

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def get_reports_by_ticker(self, ticker: str, days: int = 30) -> List[Dict]:
        """Get all reports mentioning a specific ticker within N days"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT report_url, report_title, analyst, source, publish_date, processed_date, pdf_path, tickers
            FROM processed_reports
            WHERE tickers LIKE ?
            AND datetime(processed_date) >= datetime('now', '-' || ? || ' days')
            ORDER BY publish_date DESC
        ''', (f'%{ticker}%', days))

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def get_reports_by_source(self, source: str, days: int = 30) -> List[Dict]:
        """Get all reports from a specific source within N days"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT report_url, report_title, analyst, source, publish_date, processed_date, pdf_path, tickers
            FROM processed_reports
            WHERE source = ?
            AND datetime(processed_date) >= datetime('now', '-' || ? || ' days')
            ORDER BY publish_date DESC
        ''', (source, days))

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def get_analyst_coverage_stats(self, days: int = 30) -> Dict:
        """Get statistics on analyst coverage (report counts by analyst)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT analyst, COUNT(*) as report_count
            FROM processed_reports
            WHERE datetime(processed_date) >= datetime('now', '-' || ? || ' days')
            AND analyst IS NOT NULL
            GROUP BY analyst
            ORDER BY report_count DESC
        ''', (days,))

        rows = cursor.fetchall()
        conn.close()

        return {row[0]: row[1] for row in rows}

    def get_ticker_coverage_stats(self, days: int = 30) -> Dict:
        """Get statistics on ticker coverage (report counts by ticker)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT tickers FROM processed_reports
            WHERE datetime(processed_date) >= datetime('now', '-' || ? || ' days')
            AND tickers IS NOT NULL AND tickers != ''
        ''', (days,))

        rows = cursor.fetchall()
        conn.close()

        # Count ticker occurrences
        ticker_counts = {}
        for row in rows:
            tickers = row[0].split(',') if row[0] else []
            for ticker in tickers:
                ticker = ticker.strip().upper()
                if ticker:
                    ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1

        return dict(sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True))

    def get_report_with_pdf(self, report_url: str) -> Optional[Dict]:
        """Get a specific report including its PDF path"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT report_url, report_title, analyst, source, publish_date, processed_date, pdf_path, tickers
            FROM processed_reports
            WHERE report_url = ?
        ''', (report_url,))

        row = cursor.fetchone()
        conn.close()

        return self._row_to_dict(row) if row else None

    def _row_to_dict(self, row) -> Dict:
        """Convert a database row to a report dictionary"""
        return {
            'url': row[0],
            'title': row[1],
            'analyst': row[2],
            'source': row[3],
            'date': row[4],
            'processed_date': row[5],
            'pdf_path': row[6],
            'tickers': row[7].split(',') if row[7] else []
        }
