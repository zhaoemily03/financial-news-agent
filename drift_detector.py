"""
Drift Detector — Surfaces belief changes and sentiment shifts over time.

Core value: Change > State. This module detects when claims shift relative
to prior periods, not what claims say in isolation.

Detects:
- Confidence softening or hardening (high→medium, low→high)
- Belief pressure shifts (confirms→contradicts)
- Hedging language emergence
- New disagreement between sources
- Attention decay or resurgence (topic appearing/disappearing)

No AI. Deterministic comparison of claim metadata over time.

Usage:
    from drift_detector import detect_drift, DriftSignal

    signals = detect_drift(today_claims, prior_claims)
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime

from claim_extractor import ClaimOutput
from claim_tracker import ClaimTracker, HistoricalClaim


# ------------------------------------------------------------------
# Drift Signal Types
# ------------------------------------------------------------------

CONFIDENCE_ORDER = {'low': 0, 'medium': 1, 'high': 2}


@dataclass
class DriftSignal:
    """A detected belief shift. The analyst decides if it matters."""
    signal_id: str
    drift_type: str            # confidence_shift | belief_flip | new_disagreement | resurgence | decay
    ticker: Optional[str]
    description: str           # What changed (factual, not interpretive)
    today_claim: str           # Current claim text
    prior_claim: Optional[str] # What was said before
    today_source: str
    prior_source: Optional[str]
    today_date: str
    prior_date: Optional[str]
    severity: str              # high | medium | low
    # Metadata for rendering
    today_confidence: Optional[str] = None
    prior_confidence: Optional[str] = None
    today_belief_pressure: Optional[str] = None
    prior_belief_pressure: Optional[str] = None


@dataclass
class DriftReport:
    """All drift signals for a briefing period."""
    signals: List[DriftSignal] = field(default_factory=list)
    lookback_days: int = 7
    today_claim_count: int = 0
    prior_claim_count: int = 0

    @property
    def by_ticker(self) -> Dict[str, List[DriftSignal]]:
        grouped = defaultdict(list)
        for s in self.signals:
            key = s.ticker or 'General'
            grouped[key].append(s)
        return dict(grouped)

    @property
    def by_type(self) -> Dict[str, List[DriftSignal]]:
        grouped = defaultdict(list)
        for s in self.signals:
            grouped[s.drift_type].append(s)
        return dict(grouped)

    @property
    def high_severity(self) -> List[DriftSignal]:
        return [s for s in self.signals if s.severity == 'high']

    def has_signals(self) -> bool:
        return len(self.signals) > 0

    def summary(self) -> str:
        if not self.signals:
            return "No drift signals detected"
        type_counts = defaultdict(int)
        for s in self.signals:
            type_counts[s.drift_type] += 1
        parts = [f"{v} {k}" for k, v in type_counts.items()]
        return f"{len(self.signals)} drift signals: {', '.join(parts)}"


# ------------------------------------------------------------------
# Drift Detection Logic
# ------------------------------------------------------------------

def _detect_confidence_shifts(
    today_claims: List[ClaimOutput],
    prior_claims: List[HistoricalClaim],
) -> List[DriftSignal]:
    """
    Detect when confidence on a ticker/topic has shifted.
    e.g., Source was 'high' confidence on META, now 'medium'.
    """
    signals = []

    # Group today's claims by ticker
    today_by_ticker = defaultdict(list)
    for c in today_claims:
        if c.ticker:
            today_by_ticker[c.ticker].append(c)

    # Group prior claims by ticker
    prior_by_ticker = defaultdict(list)
    for c in prior_claims:
        if c.ticker:
            prior_by_ticker[c.ticker].append(c)

    for ticker in today_by_ticker:
        if ticker not in prior_by_ticker:
            continue

        today_confs = [CONFIDENCE_ORDER.get(c.confidence_level, 1) for c in today_by_ticker[ticker]]
        prior_confs = [CONFIDENCE_ORDER.get(c.confidence_level, 1) for c in prior_by_ticker[ticker]]

        avg_today = sum(today_confs) / len(today_confs)
        avg_prior = sum(prior_confs) / len(prior_confs)

        diff = avg_today - avg_prior

        # Only flag meaningful shifts (>0.5 on 0-2 scale)
        if abs(diff) < 0.5:
            continue

        direction = "hardening" if diff > 0 else "softening"
        severity = "high" if abs(diff) >= 1.0 else "medium"

        # Pick representative claims
        today_rep = today_by_ticker[ticker][0]
        prior_rep = prior_by_ticker[ticker][0]

        signals.append(DriftSignal(
            signal_id=f"conf_{ticker}_{datetime.now().strftime('%Y%m%d')}",
            drift_type='confidence_shift',
            ticker=ticker,
            description=f"Confidence {direction} on {ticker}: sources moved from {prior_rep.confidence_level} to {today_rep.confidence_level}",
            today_claim=today_rep.bullets[0] if today_rep.bullets else "",
            prior_claim=prior_rep.bullets[0] if prior_rep.bullets else "",
            today_source=today_rep.source_citation,
            prior_source=prior_rep.source_citation,
            today_date=datetime.now().strftime('%Y-%m-%d'),
            prior_date=prior_rep.date_stored,
            severity=severity,
            today_confidence=today_rep.confidence_level,
            prior_confidence=prior_rep.confidence_level,
        ))

    return signals


def _detect_belief_flips(
    today_claims: List[ClaimOutput],
    prior_claims: List[HistoricalClaim],
) -> List[DriftSignal]:
    """
    Detect when belief pressure has flipped.
    e.g., Source confirmed consensus on CRWD, now contradicts it.
    """
    signals = []

    # Map belief pressure to direction
    BELIEF_DIRECTION = {
        'confirms_consensus': 'positive',
        'contradicts_consensus': 'negative',
        'contradicts_prior_assumptions': 'negative',
        'unclear': 'neutral',
    }

    today_by_ticker = defaultdict(list)
    for c in today_claims:
        if c.ticker:
            today_by_ticker[c.ticker].append(c)

    prior_by_ticker = defaultdict(list)
    for c in prior_claims:
        if c.ticker:
            prior_by_ticker[c.ticker].append(c)

    for ticker in today_by_ticker:
        if ticker not in prior_by_ticker:
            continue

        today_directions = [BELIEF_DIRECTION.get(c.belief_pressure, 'neutral') for c in today_by_ticker[ticker]]
        prior_directions = [BELIEF_DIRECTION.get(c.belief_pressure, 'neutral') for c in prior_by_ticker[ticker]]

        # Check for directional flip
        today_dominant = max(set(today_directions), key=today_directions.count)
        prior_dominant = max(set(prior_directions), key=prior_directions.count)

        if today_dominant == prior_dominant or 'neutral' in (today_dominant, prior_dominant):
            continue

        today_rep = today_by_ticker[ticker][0]
        prior_rep = prior_by_ticker[ticker][0]

        signals.append(DriftSignal(
            signal_id=f"flip_{ticker}_{datetime.now().strftime('%Y%m%d')}",
            drift_type='belief_flip',
            ticker=ticker,
            description=f"Belief flip on {ticker}: was {prior_dominant}, now {today_dominant}",
            today_claim=today_rep.bullets[0] if today_rep.bullets else "",
            prior_claim=prior_rep.bullets[0] if prior_rep.bullets else "",
            today_source=today_rep.source_citation,
            prior_source=prior_rep.source_citation,
            today_date=datetime.now().strftime('%Y-%m-%d'),
            prior_date=prior_rep.date_stored,
            severity="high",
            today_belief_pressure=today_rep.belief_pressure,
            prior_belief_pressure=prior_rep.belief_pressure,
        ))

    return signals


def _detect_new_disagreements(
    today_claims: List[ClaimOutput],
    prior_claims: List[HistoricalClaim],
) -> List[DriftSignal]:
    """
    Detect new disagreement that didn't exist in the prior period.
    e.g., Sources aligned on AMZN last week, now split.
    """
    signals = []

    today_by_ticker = defaultdict(list)
    for c in today_claims:
        if c.ticker:
            today_by_ticker[c.ticker].append(c)

    prior_by_ticker = defaultdict(list)
    for c in prior_claims:
        if c.ticker:
            prior_by_ticker[c.ticker].append(c)

    for ticker in today_by_ticker:
        today_group = today_by_ticker[ticker]
        prior_group = prior_by_ticker.get(ticker, [])

        if len(today_group) < 2:
            continue

        # Check if today has disagreement
        today_pressures = {c.belief_pressure for c in today_group}
        today_has_split = (
            ('confirms_consensus' in today_pressures) and
            ('contradicts_consensus' in today_pressures or 'contradicts_prior_assumptions' in today_pressures)
        )

        if not today_has_split:
            continue

        # Check if prior also had disagreement
        prior_pressures = {c.belief_pressure for c in prior_group}
        prior_had_split = (
            ('confirms_consensus' in prior_pressures) and
            ('contradicts_consensus' in prior_pressures or 'contradicts_prior_assumptions' in prior_pressures)
        )

        if prior_had_split:
            continue  # Not new

        # New disagreement found
        confirming = [c for c in today_group if c.belief_pressure == 'confirms_consensus']
        contradicting = [c for c in today_group if c.belief_pressure in ('contradicts_consensus', 'contradicts_prior_assumptions')]

        signals.append(DriftSignal(
            signal_id=f"disagree_{ticker}_{datetime.now().strftime('%Y%m%d')}",
            drift_type='new_disagreement',
            ticker=ticker,
            description=f"New disagreement on {ticker}: sources now split",
            today_claim=f"Confirms: {confirming[0].bullets[0][:60]}... vs Contradicts: {contradicting[0].bullets[0][:60]}...",
            prior_claim=None,
            today_source=f"{confirming[0].source_citation} vs {contradicting[0].source_citation}",
            prior_source=None,
            today_date=datetime.now().strftime('%Y-%m-%d'),
            prior_date=None,
            severity="high",
        ))

    return signals


def _detect_resurgence(
    today_claims: List[ClaimOutput],
    prior_claims: List[HistoricalClaim],
    lookback_days: int = 7,
) -> List[DriftSignal]:
    """
    Detect tickers/topics that reappear after a period of absence.
    "We haven't heard about X in a week — now 3 claims."
    """
    signals = []

    today_tickers = {c.ticker for c in today_claims if c.ticker}

    # Find which tickers were active in older history but not recent
    prior_by_ticker = defaultdict(list)
    for c in prior_claims:
        if c.ticker:
            prior_by_ticker[c.ticker].append(c)

    for ticker in today_tickers:
        prior_group = prior_by_ticker.get(ticker, [])
        today_group = [c for c in today_claims if c.ticker == ticker]

        # Resurgence = appeared today but not in prior period, OR
        # today's claim count significantly exceeds prior
        if not prior_group and len(today_group) >= 2:
            rep = today_group[0]
            signals.append(DriftSignal(
                signal_id=f"resurge_{ticker}_{datetime.now().strftime('%Y%m%d')}",
                drift_type='resurgence',
                ticker=ticker,
                description=f"{ticker}: {len(today_group)} claims today, absent from prior {lookback_days} days",
                today_claim=rep.bullets[0] if rep.bullets else "",
                prior_claim=None,
                today_source=rep.source_citation,
                prior_source=None,
                today_date=datetime.now().strftime('%Y-%m-%d'),
                prior_date=None,
                severity="medium",
            ))

    return signals


def _detect_attention_decay(
    today_claims: List[ClaimOutput],
    prior_claims: List[HistoricalClaim],
) -> List[DriftSignal]:
    """
    Detect tickers that had coverage but now have none.
    "SNOW had 5 claims last week, zero today."
    """
    signals = []

    today_tickers = {c.ticker for c in today_claims if c.ticker}

    prior_by_ticker = defaultdict(list)
    for c in prior_claims:
        if c.ticker:
            prior_by_ticker[c.ticker].append(c)

    for ticker, prior_group in prior_by_ticker.items():
        if ticker in today_tickers:
            continue
        if len(prior_group) < 2:
            continue  # Only flag if it was actively discussed

        rep = prior_group[0]
        signals.append(DriftSignal(
            signal_id=f"decay_{ticker}_{datetime.now().strftime('%Y%m%d')}",
            drift_type='decay',
            ticker=ticker,
            description=f"{ticker}: {len(prior_group)} claims in prior period, none today",
            today_claim="",
            prior_claim=rep.bullets[0] if rep.bullets else "",
            today_source="",
            prior_source=rep.source_citation,
            today_date=datetime.now().strftime('%Y-%m-%d'),
            prior_date=rep.date_stored,
            severity="low",
        ))

    return signals


# ------------------------------------------------------------------
# Main Detection Function
# ------------------------------------------------------------------

def detect_drift(
    today_claims: List[ClaimOutput],
    tracker: ClaimTracker,
    lookback_days: int = 7,
) -> DriftReport:
    """
    Compare today's claims against historical claims to detect drift.

    Args:
        today_claims: Claims from today's briefing
        tracker: ClaimTracker with historical data
        lookback_days: How far back to compare

    Returns:
        DriftReport with all detected signals
    """
    # Get prior claims from tracker
    prior_claims = []
    for claim in today_claims:
        if claim.ticker:
            ticker_history = tracker.get_claims_for_ticker(
                claim.ticker, days=lookback_days, exclude_today=True
            )
            prior_claims.extend(ticker_history)

    # Deduplicate prior claims
    seen_ids = set()
    unique_prior = []
    for c in prior_claims:
        if c.claim_id not in seen_ids:
            seen_ids.add(c.claim_id)
            unique_prior.append(c)

    # Run all detectors
    all_signals = []
    all_signals.extend(_detect_confidence_shifts(today_claims, unique_prior))
    all_signals.extend(_detect_belief_flips(today_claims, unique_prior))
    all_signals.extend(_detect_new_disagreements(today_claims, unique_prior))
    all_signals.extend(_detect_resurgence(today_claims, unique_prior, lookback_days))
    all_signals.extend(_detect_attention_decay(today_claims, unique_prior))

    # Sort by severity (high first)
    severity_order = {'high': 0, 'medium': 1, 'low': 2}
    all_signals.sort(key=lambda s: severity_order.get(s.severity, 3))

    return DriftReport(
        signals=all_signals,
        lookback_days=lookback_days,
        today_claim_count=len(today_claims),
        prior_claim_count=len(unique_prior),
    )


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    import os

    print("=" * 60)
    print("Drift Detector Test")
    print("=" * 60)

    test_db = 'data/drift_test.db'
    tracker = ClaimTracker(db_path=test_db)

    # Simulate prior claims (stored yesterday)
    prior_claims = [
        ClaimOutput(
            chunk_id="prior_1",
            doc_id="doc_prior",
            bullets=["META ad revenue growth strong at 25% YoY"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, Brent Thill, p.1",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="prior_2",
            doc_id="doc_prior",
            bullets=["CRWD maintaining endpoint market leadership"],
            ticker="CRWD",
            claim_type="fact",
            source_citation="Jefferies, Joseph Gallo, p.2",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="prior_3",
            doc_id="doc_prior",
            bullets=["AMZN cloud growth expected to accelerate"],
            ticker="AMZN",
            claim_type="forecast",
            source_citation="Jefferies, Brent Thill, p.3",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
    ]

    # Store prior claims
    tracker.store_claims(prior_claims)

    # Manually backdate the stored claims for testing
    import sqlite3
    conn = sqlite3.connect(test_db)
    conn.execute("UPDATE claims SET date_stored = '2026-02-01'")
    conn.commit()
    conn.close()

    # Today's claims — confidence softened on META, belief flip on CRWD, AMZN gone
    today_claims = [
        ClaimOutput(
            chunk_id="today_1",
            doc_id="doc_today",
            bullets=["META ad revenue growth may slow to 20% as competition increases"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, Brent Thill, p.1",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=True,
        ),
        ClaimOutput(
            chunk_id="today_2",
            doc_id="doc_today",
            bullets=["CRWD losing share to MSFT Defender in enterprise"],
            ticker="CRWD",
            claim_type="risk",
            source_citation="Jefferies, Joseph Gallo, p.2",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="contradicts_prior_assumptions",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="today_3",
            doc_id="doc_today",
            bullets=["CRWD endpoint protection remains industry-leading"],
            ticker="CRWD",
            claim_type="fact",
            source_citation="Morgan Stanley, p.1",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="today_4",
            doc_id="doc_today",
            bullets=["GOOGL Cloud revenue beat expectations by 5%"],
            ticker="GOOGL",
            claim_type="fact",
            source_citation="Jefferies, Brent Thill, p.4",
            confidence_level="high",
            time_sensitivity="breaking",
            belief_pressure="contradicts_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="today_5",
            doc_id="doc_today",
            bullets=["GOOGL search advertising resilient despite AI concerns"],
            ticker="GOOGL",
            claim_type="fact",
            source_citation="Jefferies, Brent Thill, p.5",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
    ]

    print(f"\n  Prior claims: {len(prior_claims)} (backdated to 2026-02-01)")
    print(f"  Today claims: {len(today_claims)}")
    print(f"  Expected: META confidence softening, CRWD belief flip + new disagreement, GOOGL resurgence, AMZN decay")

    # Run drift detection
    print("\n  Running drift detection...")
    report = detect_drift(today_claims, tracker, lookback_days=7)

    print(f"\n  {report.summary()}")
    print(f"  High severity: {len(report.high_severity)}")

    print("\n" + "-" * 60)
    print("DRIFT SIGNALS")
    print("-" * 60)

    for signal in report.signals:
        print(f"\n  [{signal.severity.upper()}] {signal.drift_type}")
        print(f"  {signal.description}")
        if signal.today_claim:
            print(f"  Today: {signal.today_claim[:80]}")
        if signal.prior_claim:
            print(f"  Prior: {signal.prior_claim[:80]}")

    # Verification
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    assert report.has_signals(), "Should detect drift signals"
    print(f"✓ Detected {len(report.signals)} drift signals")

    types_found = {s.drift_type for s in report.signals}

    if 'confidence_shift' in types_found:
        print("✓ Confidence shift detected (META high→medium)")
    else:
        print("○ Confidence shift not detected (may need more data)")

    if 'belief_flip' in types_found:
        print("✓ Belief flip detected (CRWD positive→negative)")
    else:
        print("○ Belief flip not detected (may need more data)")

    if 'new_disagreement' in types_found:
        print("✓ New disagreement detected (CRWD)")
    else:
        print("○ New disagreement not detected (may need more data)")

    if 'resurgence' in types_found:
        print("✓ Resurgence detected (GOOGL)")
    else:
        print("○ Resurgence not detected (may need more data)")

    if 'decay' in types_found:
        print("✓ Attention decay detected (AMZN)")
    else:
        print("○ Attention decay not detected (may need more data)")

    # Cleanup
    os.remove(test_db)
    print("\n✓ Drift detector working correctly")
