"""
Claim Tracker — Historical claim storage for drift detection.

Stores claims with metadata for cross-time comparison:
- By ticker: "What did sources say about META last week?"
- By author: "How has Brent Thill's view changed?"
- By source: "Is Jefferies getting more cautious?"

Uses SQLite for persistence between runs.

Usage:
    from claim_tracker import ClaimTracker

    tracker = ClaimTracker()
    tracker.store_claims(claims)
    prior = tracker.get_claims_for_ticker('META', days=7)
"""

import os
import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

from claim_extractor import ClaimOutput


# ------------------------------------------------------------------
# Historical Claim Record
# ------------------------------------------------------------------

@dataclass
class HistoricalClaim:
    """Claim stored for historical comparison."""
    claim_id: str
    doc_id: str
    ticker: Optional[str]
    author: Optional[str]
    source: Optional[str]
    claim_type: str
    bullets: List[str]
    confidence_level: str
    belief_pressure: str
    time_sensitivity: str
    date_stored: str
    source_citation: str
    # Classification category
    category: Optional[str] = None         # tracked_ticker | tmt_sector | macro
    # MECE section routing fields
    event_type: Optional[str] = None
    is_descriptive_event: bool = False
    has_belief_delta: bool = False
    sector_implication: Optional[str] = None

    @classmethod
    def from_claim_output(cls, claim: ClaimOutput, author: str = None, source: str = None) -> 'HistoricalClaim':
        """Convert ClaimOutput to HistoricalClaim for storage."""
        return cls(
            claim_id=claim.chunk_id,
            doc_id=claim.doc_id,
            ticker=claim.ticker,
            author=author,
            source=source,
            claim_type=claim.claim_type,
            bullets=claim.bullets,
            confidence_level=claim.confidence_level,
            belief_pressure=claim.belief_pressure,
            time_sensitivity=claim.time_sensitivity,
            date_stored=datetime.now().strftime('%Y-%m-%d'),
            source_citation=claim.source_citation,
            category=getattr(claim, 'category', None),
            event_type=getattr(claim, 'event_type', None),
            is_descriptive_event=getattr(claim, 'is_descriptive_event', False),
            has_belief_delta=getattr(claim, 'has_belief_delta', False),
            sector_implication=getattr(claim, 'sector_implication', None),
        )

    def to_claim_output(self) -> ClaimOutput:
        """Convert back to ClaimOutput for comparison."""
        return ClaimOutput(
            chunk_id=self.claim_id,
            doc_id=self.doc_id,
            bullets=self.bullets,
            ticker=self.ticker,
            claim_type=self.claim_type,
            source_citation=self.source_citation,
            confidence_level=self.confidence_level,
            time_sensitivity=self.time_sensitivity,
            belief_pressure=self.belief_pressure,
            uncertainty_preserved=False,
            category=self.category,
            event_type=self.event_type,
            is_descriptive_event=self.is_descriptive_event,
            has_belief_delta=self.has_belief_delta,
            sector_implication=self.sector_implication,
        )


# ------------------------------------------------------------------
# Claim Tracker (SQLite-backed)
# ------------------------------------------------------------------

class ClaimTracker:
    """
    Persistent claim storage for drift detection.
    Enables cross-time comparison of claims.
    """

    def __init__(self, db_path: str = 'data/claim_history.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                ticker TEXT,
                author TEXT,
                source TEXT,
                claim_type TEXT,
                bullets TEXT,
                confidence_level TEXT,
                belief_pressure TEXT,
                time_sensitivity TEXT,
                date_stored TEXT,
                source_citation TEXT,
                UNIQUE(claim_id, date_stored)
            )
        ''')

        # Schema migration: add columns if missing
        for col, col_type in [
            ('category', 'TEXT'),
            ('event_type', 'TEXT'),
            ('is_descriptive_event', 'INTEGER DEFAULT 0'),
            ('has_belief_delta', 'INTEGER DEFAULT 0'),
            ('sector_implication', 'TEXT'),
        ]:
            try:
                cursor.execute(f'ALTER TABLE claims ADD COLUMN {col} {col_type}')
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Indexes for fast lookup
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ticker ON claims(ticker)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_author ON claims(author)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_source ON claims(source)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_date ON claims(date_stored)')

        conn.commit()
        conn.close()

    def store_claims(
        self,
        claims: List[ClaimOutput],
        author: str = None,
        source: str = None,
    ) -> int:
        """
        Store claims for historical tracking.

        Args:
            claims: List of ClaimOutput objects
            author: Default author if not in citation
            source: Default source if not in citation

        Returns:
            Number of claims stored
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        stored = 0

        for claim in claims:
            # Extract author/source from citation if available
            claim_author = author
            claim_source = source
            if claim.source_citation:
                parts = claim.source_citation.split(',')
                if len(parts) >= 1:
                    claim_source = claim_source or parts[0].strip()
                if len(parts) >= 2:
                    claim_author = claim_author or parts[1].strip()

            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO claims
                    (claim_id, doc_id, ticker, author, source, claim_type, bullets,
                     confidence_level, belief_pressure, time_sensitivity, date_stored, source_citation,
                     category, event_type, is_descriptive_event, has_belief_delta, sector_implication)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    claim.chunk_id,
                    claim.doc_id,
                    claim.ticker,
                    claim_author,
                    claim_source,
                    claim.claim_type,
                    json.dumps(claim.bullets),
                    claim.confidence_level,
                    claim.belief_pressure,
                    claim.time_sensitivity,
                    datetime.now().strftime('%Y-%m-%d'),
                    claim.source_citation,
                    getattr(claim, 'category', None),
                    getattr(claim, 'event_type', None),
                    1 if getattr(claim, 'is_descriptive_event', False) else 0,
                    1 if getattr(claim, 'has_belief_delta', False) else 0,
                    getattr(claim, 'sector_implication', None),
                ))
                stored += 1
            except sqlite3.IntegrityError:
                pass  # Already stored today

        conn.commit()
        conn.close()
        return stored

    def get_claims_for_ticker(
        self,
        ticker: str,
        days: int = 30,
        exclude_today: bool = True,
    ) -> List[HistoricalClaim]:
        """Get historical claims for a ticker."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')

        if exclude_today:
            cursor.execute('''
                SELECT * FROM claims
                WHERE ticker = ? AND date_stored >= ? AND date_stored < ?
                ORDER BY date_stored DESC
            ''', (ticker, cutoff, today))
        else:
            cursor.execute('''
                SELECT * FROM claims
                WHERE ticker = ? AND date_stored >= ?
                ORDER BY date_stored DESC
            ''', (ticker, cutoff))

        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_claim(row) for row in rows]

    def get_claims_for_author(
        self,
        author: str,
        days: int = 30,
        ticker: str = None,
    ) -> List[HistoricalClaim]:
        """Get historical claims by a specific author."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        if ticker:
            cursor.execute('''
                SELECT * FROM claims
                WHERE author LIKE ? AND ticker = ? AND date_stored >= ?
                ORDER BY date_stored DESC
            ''', (f'%{author}%', ticker, cutoff))
        else:
            cursor.execute('''
                SELECT * FROM claims
                WHERE author LIKE ? AND date_stored >= ?
                ORDER BY date_stored DESC
            ''', (f'%{author}%', cutoff))

        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_claim(row) for row in rows]

    def get_prior_claims(
        self,
        days: int = 7,
    ) -> List[ClaimOutput]:
        """Get all claims from the prior period (for tier2 synthesis)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        today = datetime.now().strftime('%Y-%m-%d')
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        cursor.execute('''
            SELECT * FROM claims
            WHERE date_stored >= ? AND date_stored < ?
            ORDER BY date_stored DESC
        ''', (cutoff, today))

        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_claim(row).to_claim_output() for row in rows]

    def get_claims_by_date(
        self,
        date_str: str,
    ) -> List[HistoricalClaim]:
        """Get all claims from a specific date."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM claims WHERE date_stored = ?
        ''', (date_str,))

        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_claim(row) for row in rows]

    def get_stats(self) -> Dict:
        """Get storage statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM claims')
        total = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(DISTINCT ticker) FROM claims WHERE ticker IS NOT NULL')
        tickers = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(DISTINCT author) FROM claims WHERE author IS NOT NULL')
        authors = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(DISTINCT date_stored) FROM claims')
        days = cursor.fetchone()[0]

        conn.close()
        return {
            'total_claims': total,
            'unique_tickers': tickers,
            'unique_authors': authors,
            'days_tracked': days,
        }

    def _row_to_claim(self, row) -> HistoricalClaim:
        """Convert database row to HistoricalClaim (safe for old/new schema).

        Column order (after migrations):
        0=id, 1=claim_id, 2=doc_id, 3=ticker, 4=author, 5=source,
        6=claim_type, 7=bullets, 8=confidence_level, 9=belief_pressure,
        10=time_sensitivity, 11=date_stored, 12=source_citation,
        13=category, 14=event_type, 15=is_descriptive_event,
        16=has_belief_delta, 17=sector_implication
        """
        return HistoricalClaim(
            claim_id=row[1],
            doc_id=row[2],
            ticker=row[3],
            author=row[4],
            source=row[5],
            claim_type=row[6],
            bullets=json.loads(row[7]) if row[7] else [],
            confidence_level=row[8],
            belief_pressure=row[9],
            time_sensitivity=row[10],
            date_stored=row[11],
            source_citation=row[12],
            category=row[13] if len(row) > 13 else None,
            event_type=row[14] if len(row) > 14 else None,
            is_descriptive_event=bool(row[15]) if len(row) > 15 else False,
            has_belief_delta=bool(row[16]) if len(row) > 16 else False,
            sector_implication=row[17] if len(row) > 17 else None,
        )


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    import os

    print("=" * 60)
    print("Claim Tracker Test")
    print("=" * 60)

    # Use test database
    test_db = 'data/claim_history_test.db'
    tracker = ClaimTracker(db_path=test_db)

    # Create test claims (with MECE routing fields)
    test_claims = [
        ClaimOutput(
            chunk_id="test_1",
            doc_id="doc1",
            bullets=["META ad revenue grew 28% YoY"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, Brent Thill, p.1, 2026-02-04",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
            category="tracked_ticker",
            event_type="earnings",
            is_descriptive_event=True,
            has_belief_delta=False,
        ),
        ClaimOutput(
            chunk_id="test_2",
            doc_id="doc1",
            bullets=["CRWD facing competitive pressure from MSFT"],
            ticker="CRWD",
            claim_type="risk",
            source_citation="Jefferies, Joseph Gallo, p.2, 2026-02-04",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="contradicts_prior_assumptions",
            uncertainty_preserved=False,
            category="tracked_ticker",
            event_type="market",
            is_descriptive_event=False,
            has_belief_delta=True,
        ),
        ClaimOutput(
            chunk_id="test_3",
            doc_id="doc1",
            bullets=["Fed held rates steady at 5.25%"],
            ticker=None,
            claim_type="fact",
            source_citation="Macro, 2026-02-04",
            confidence_level="high",
            time_sensitivity="breaking",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
            category="macro",
            event_type="macro",
            is_descriptive_event=True,
            has_belief_delta=False,
            sector_implication="Higher rates extend pressure on unprofitable software multiples",
        ),
    ]

    print("\n[1] Storing test claims...")
    stored = tracker.store_claims(test_claims)
    print(f"    Stored {stored} claims")

    print("\n[2] Retrieving claims for META...")
    meta_claims = tracker.get_claims_for_ticker('META', days=30, exclude_today=False)
    print(f"    Found {len(meta_claims)} claims")
    for c in meta_claims:
        print(f"      - {c.bullets[0][:50]}... ({c.confidence_level})")

    print("\n[3] Retrieving claims by author 'Brent Thill'...")
    author_claims = tracker.get_claims_for_author('Brent Thill', days=30)
    print(f"    Found {len(author_claims)} claims")

    print("\n[4] Storage stats...")
    stats = tracker.get_stats()
    for k, v in stats.items():
        print(f"    {k}: {v}")

    print("\n[5] Verify MECE field round-trip...")
    meta_claims = tracker.get_claims_for_ticker('META', days=30, exclude_today=False)
    if meta_claims:
        mc = meta_claims[0]
        assert mc.category == 'tracked_ticker', f"Expected 'tracked_ticker', got {mc.category}"
        assert mc.event_type == 'earnings', f"Expected 'earnings', got {mc.event_type}"
        assert mc.is_descriptive_event is True, f"Expected True, got {mc.is_descriptive_event}"
        assert mc.has_belief_delta is False, f"Expected False, got {mc.has_belief_delta}"
        print("    ✓ META claim: category, event_type, is_descriptive_event, has_belief_delta round-tripped")

    # Check macro claim round-trip
    all_today = tracker.get_claims_by_date(datetime.now().strftime('%Y-%m-%d'))
    macro_claims = [c for c in all_today if c.event_type == 'macro']
    if macro_claims:
        mc = macro_claims[0]
        assert mc.sector_implication is not None, "Macro claim lost sector_implication"
        print(f"    ✓ Macro claim: sector_implication = {mc.sector_implication[:50]}...")

    # Verify to_claim_output preserves new fields
    if meta_claims:
        co = meta_claims[0].to_claim_output()
        assert co.event_type == 'earnings'
        assert co.is_descriptive_event is True
        print("    ✓ to_claim_output() preserves MECE fields")

    print("\n[6] Cleanup test database...")
    os.remove(test_db)
    print("    Removed test database")

    print("\n✓ Claim tracker working correctly (with MECE fields)")
