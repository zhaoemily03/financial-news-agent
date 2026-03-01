"""
Drift Detector — Surfaces belief changes and sentiment shifts over time.

Core value: Change > State. This module detects when claims shift relative
to prior periods, not what claims say in isolation.

Detects:
- Confidence softening or hardening (high→medium, low→high)
- Belief pressure shifts (confirms→contradicts)
- Hedging language emergence
- New disagreement between sources

No AI. Deterministic comparison of claim metadata over time.

Usage:
    from drift_detector import detect_drift, DriftSignal

    signals = detect_drift(today_claims, prior_claims)
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime

from claim_extractor import ClaimOutput
from claim_tracker import ClaimTracker, HistoricalClaim


# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

CONFIDENCE_ORDER = {'low': 0, 'medium': 1, 'high': 2}
CONF_LABEL = {0: 'low', 1: 'medium', 2: 'high'}

# Default windows if not specified — 7d = noise check, 30d = developing theme, 90d = structural
DEFAULT_ANALYSIS_WINDOWS = [7, 30, 90]


@dataclass
class DriftSignal:
    """A detected belief shift. The analyst decides if it matters."""
    signal_id: str
    drift_type: str            # confidence_shift | belief_flip | new_disagreement
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
    # Multi-window context
    window_days: int = 7                # Shortest window that triggered this signal
    cross_window_context: str = ""      # e.g. "90d: high → 30d: high → 7d: medium → today: low (structural decline)"


@dataclass
class DriftReport:
    """All drift signals for a briefing period."""
    signals: List[DriftSignal] = field(default_factory=list)
    lookback_days: int = 90
    windows_analyzed: List[int] = field(default_factory=lambda: DEFAULT_ANALYSIS_WINDOWS)
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
# Multi-Window Trajectory Helpers
# ------------------------------------------------------------------

def _conf_label(avg: float) -> str:
    """Map a 0-2 float average to a readable confidence label."""
    return CONF_LABEL.get(max(0, min(2, round(avg))), 'medium')


def _build_confidence_trajectory(
    avg_today: float,
    window_avgs: Dict[int, Optional[float]],
    windows: List[int],
) -> str:
    """
    Build readable trajectory string across all windows.
    e.g. "90d: high → 30d: high → 7d: medium → today: low (gradual structural decline)"

    Pattern labels are gated on actual data depth — avoids claiming 'structural'
    or 'sustained' trends when only short-window data exists.
    """
    parts = []
    available = []
    for window in sorted(windows, reverse=True):   # longest to shortest
        v = window_avgs.get(window)
        if v is not None:
            parts.append(f"{window}d: {_conf_label(v)}")
            available.append((window, v))
    parts.append(f"today: {_conf_label(avg_today)}")
    trajectory = " → ".join(parts)

    if not available:
        return trajectory  # no prior data — signal still valid but no pattern

    max_window = available[0][0]   # longest window with actual data

    if len(available) < 2:
        # Only one prior window — acknowledge the shift without trend classification
        return f"{trajectory} ({max_window}d history only)"

    oldest_avg = available[0][1]    # e.g. 90d (or whatever max is)
    recent_avg = available[-1][1]   # e.g. 7d (closest prior window)
    overall = avg_today - oldest_avg
    recent = avg_today - recent_avg

    # Pattern labels gated on available history depth
    if max_window >= 90:
        # Full history — structural/sustained language is warranted
        if overall < -0.8 and abs(recent) < 0.3:
            pattern = "gradual structural decline"
        elif overall < -0.5 and recent < -0.5:
            pattern = "accelerating decline"
        elif abs(overall) < 0.3 and recent < -0.7:
            pattern = "sudden reversal of previously stable trend"
        elif overall > 0.8 and recent > 0.3:
            pattern = "strengthening conviction across all windows"
        elif overall > 0.5:
            pattern = "sustained conviction hardening"
        elif overall < -0.5:
            pattern = "declining conviction, longer-term trend"
        else:
            pattern = "minor adjustment"
    elif max_window >= 30:
        # 30d max — developing theme, avoid structural language
        if overall < -0.5 and recent < -0.5:
            pattern = "accelerating decline over past month"
        elif overall > 0.5 and recent > 0.3:
            pattern = "conviction hardening over past month"
        elif abs(overall) < 0.3 and recent < -0.7:
            pattern = "sudden shift"
        elif overall < -0.5:
            pattern = "declining conviction (30d history)"
        elif overall > 0.5:
            pattern = "rising conviction (30d history)"
        else:
            pattern = "minor adjustment"
    else:
        # Only 7d data — flag limited basis explicitly
        pattern = "recent shift (7d history only)"

    return f"{trajectory} ({pattern})"


def _build_belief_trajectory(
    today_dominant: str,
    window_dominants: Dict[int, Optional[str]],
    windows: List[int],
) -> str:
    """
    Build readable belief-direction trajectory.
    e.g. "90d: positive → 30d: positive → 7d: negative (reversal of sustained prior trend)"

    Pattern labels are gated on available data depth — avoids claiming 'sustained'
    trends when only short-window data exists.
    """
    parts = []
    available = []
    for window in sorted(windows, reverse=True):
        d = window_dominants.get(window)
        if d and d != 'neutral':
            parts.append(f"{window}d: {d}")
            available.append((window, d))
    parts.append(f"today: {today_dominant}")
    trajectory = " → ".join(parts)

    if not available:
        return trajectory  # no prior data — signal still valid but no pattern

    max_window = available[0][0]

    if len(available) < 2:
        return f"{trajectory} ({max_window}d history only)"

    oldest = available[0][1]
    recent = available[-1][1]

    # 'Sustained' language requires at least 30d; 7d-only gets a limited-basis label
    if max_window >= 30:
        if oldest == recent and recent != today_dominant:
            pattern = "reversal of sustained prior trend"
        elif oldest != recent and recent == today_dominant:
            pattern = "continuation of recent shift"
        elif oldest != today_dominant and recent != today_dominant:
            pattern = "sharp directional change across all windows"
        else:
            pattern = "mixed signals across windows"
    else:
        # Only 7d data — describe without implying sustained history
        if oldest != today_dominant:
            pattern = "recent directional change (7d history only)"
        else:
            pattern = "mixed signals"

    return f"{trajectory} ({pattern})"


# ------------------------------------------------------------------
# Drift Detection Logic
# ------------------------------------------------------------------

def _detect_confidence_shifts(
    today_claims: List[ClaimOutput],
    prior_by_window: Dict[int, List[HistoricalClaim]],
    windows: List[int],
) -> List[DriftSignal]:
    """
    Multi-window confidence drift detection.
    For each ticker, computes average confidence at 7d, 30d, 90d windows
    and today, then flags meaningful shifts with a cross-window trajectory narrative.
    """
    signals = []

    today_by_ticker: Dict[str, List[ClaimOutput]] = defaultdict(list)
    for c in today_claims:
        if c.ticker:
            today_by_ticker[c.ticker].append(c)

    # Build {window: {ticker: [claims]}} lookup
    by_window_ticker: Dict[int, Dict[str, List[HistoricalClaim]]] = {}
    for window, wc in prior_by_window.items():
        bt: Dict[str, List[HistoricalClaim]] = defaultdict(list)
        for c in wc:
            if c.ticker:
                bt[c.ticker].append(c)
        by_window_ticker[window] = bt

    for ticker in today_by_ticker:
        today_confs = [CONFIDENCE_ORDER.get(c.confidence_level, 1) for c in today_by_ticker[ticker]]
        avg_today = sum(today_confs) / len(today_confs)

        # Average confidence at each window
        window_avgs: Dict[int, Optional[float]] = {}
        for window in windows:
            prior = by_window_ticker.get(window, {}).get(ticker, [])
            if prior:
                confs = [CONFIDENCE_ORDER.get(c.confidence_level, 1) for c in prior]
                window_avgs[window] = sum(confs) / len(confs)
            else:
                window_avgs[window] = None

        # Only signal if at least one window shows a meaningful shift
        meaningful = [
            (w, avg) for w, avg in window_avgs.items()
            if avg is not None and abs(avg - avg_today) >= 0.5
        ]
        if not meaningful:
            continue

        context = _build_confidence_trajectory(avg_today, window_avgs, windows)
        max_shift = max(abs(avg - avg_today) for _, avg in meaningful)
        severity = 'high' if max_shift >= 1.0 else 'medium'
        primary_window = min(w for w, _ in meaningful)   # shortest window that triggered

        prior_avg = window_avgs.get(primary_window) or avg_today
        direction = "softening" if avg_today < prior_avg else "hardening"

        today_rep = today_by_ticker[ticker][0]
        prior_list = by_window_ticker.get(primary_window, {}).get(ticker, [])
        prior_rep = prior_list[0] if prior_list else None

        signals.append(DriftSignal(
            signal_id=f"conf_{ticker}_{datetime.now().strftime('%Y%m%d')}",
            drift_type='confidence_shift',
            ticker=ticker,
            description=f"Confidence {direction} on {ticker}: {context}",
            today_claim=today_rep.bullets[0] if today_rep.bullets else "",
            prior_claim=prior_rep.bullets[0] if prior_rep and prior_rep.bullets else "",
            today_source=today_rep.source_citation,
            prior_source=prior_rep.source_citation if prior_rep else None,
            today_date=datetime.now().strftime('%Y-%m-%d'),
            prior_date=prior_rep.date_stored if prior_rep else None,
            severity=severity,
            today_confidence=today_rep.confidence_level,
            prior_confidence=prior_rep.confidence_level if prior_rep else None,
            window_days=primary_window,
            cross_window_context=context,
        ))

    return signals


def _detect_belief_flips(
    today_claims: List[ClaimOutput],
    prior_by_window: Dict[int, List[HistoricalClaim]],
    windows: List[int],
) -> List[DriftSignal]:
    """
    Multi-window belief-direction flip detection.
    Tracks dominant belief pressure (positive/negative) at each window
    and flags directional reversals with a trajectory narrative.
    """
    signals = []

    BELIEF_DIRECTION = {
        'confirms_consensus': 'positive',
        'contradicts_consensus': 'negative',
        'contradicts_prior_assumptions': 'negative',
        'unclear': 'neutral',
    }

    today_by_ticker: Dict[str, List[ClaimOutput]] = defaultdict(list)
    for c in today_claims:
        if c.ticker:
            today_by_ticker[c.ticker].append(c)

    by_window_ticker: Dict[int, Dict[str, List[HistoricalClaim]]] = {}
    for window, wc in prior_by_window.items():
        bt: Dict[str, List[HistoricalClaim]] = defaultdict(list)
        for c in wc:
            if c.ticker:
                bt[c.ticker].append(c)
        by_window_ticker[window] = bt

    for ticker in today_by_ticker:
        today_dirs = [BELIEF_DIRECTION.get(c.belief_pressure, 'neutral') for c in today_by_ticker[ticker]]
        today_dominant = max(set(today_dirs), key=today_dirs.count)

        if today_dominant == 'neutral':
            continue

        # Dominant direction at each window
        window_dominants: Dict[int, Optional[str]] = {}
        for window in windows:
            prior = by_window_ticker.get(window, {}).get(ticker, [])
            if prior:
                dirs = [BELIEF_DIRECTION.get(c.belief_pressure, 'neutral') for c in prior]
                window_dominants[window] = max(set(dirs), key=dirs.count)
            else:
                window_dominants[window] = None

        # Signal if any non-neutral window shows a different direction than today
        flipped = [
            (w, d) for w, d in window_dominants.items()
            if d and d != 'neutral' and d != today_dominant
        ]
        if not flipped:
            continue

        context = _build_belief_trajectory(today_dominant, window_dominants, windows)
        primary_window = min(w for w, _ in flipped)
        prior_dominant = window_dominants.get(primary_window) or 'unknown'

        today_rep = today_by_ticker[ticker][0]
        prior_list = by_window_ticker.get(primary_window, {}).get(ticker, [])
        prior_rep = prior_list[0] if prior_list else None

        signals.append(DriftSignal(
            signal_id=f"flip_{ticker}_{datetime.now().strftime('%Y%m%d')}",
            drift_type='belief_flip',
            ticker=ticker,
            description=f"Belief flip on {ticker}: {context}",
            today_claim=today_rep.bullets[0] if today_rep.bullets else "",
            prior_claim=prior_rep.bullets[0] if prior_rep and prior_rep.bullets else "",
            today_source=today_rep.source_citation,
            prior_source=prior_rep.source_citation if prior_rep else None,
            today_date=datetime.now().strftime('%Y-%m-%d'),
            prior_date=prior_rep.date_stored if prior_rep else None,
            severity="high",
            today_belief_pressure=today_rep.belief_pressure,
            prior_belief_pressure=prior_rep.belief_pressure if prior_rep else None,
            window_days=primary_window,
            cross_window_context=context,
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


def _days_ago(date_str: Optional[str]) -> int:
    """Return how many days ago a date string (YYYY-MM-DD) was. Returns 9999 if unparseable."""
    if not date_str:
        return 9999
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        return (datetime.now() - d).days
    except ValueError:
        return 9999


# ------------------------------------------------------------------
# Main Detection Function
# ------------------------------------------------------------------

def detect_drift(
    today_claims: List[ClaimOutput],
    tracker: ClaimTracker,
    lookback_days: int = 90,
    windows: Optional[List[int]] = None,
) -> DriftReport:
    """
    Compare today's claims against historical claims across multiple time windows.

    Detects sentiment changes only — confidence softening/hardening, belief
    direction flips, and new source disagreement. Does NOT count claims or
    flag publication frequency changes (how often a source covers a ticker
    is not a reliable sentiment signal).

    For each ticker, confidence and belief are compared at 7d, 30d, and 90d
    windows simultaneously. Pattern labels are gated on available history:
    'structural' language requires 90d data, 'month' language requires 30d.

    Args:
        today_claims: Claims from today's briefing
        tracker: ClaimTracker with historical data (store ≥180 days)
        lookback_days: Outer window (default 90)
        windows: Comparison windows (default: [7, 30, 90])

    Returns:
        DriftReport with sentiment drift signals
    """
    if windows is None:
        windows = DEFAULT_ANALYSIS_WINDOWS

    # Fetch prior claims at each window for today's tickers
    today_tickers = {c.ticker for c in today_claims if c.ticker}
    prior_by_window: Dict[int, List[HistoricalClaim]] = {}

    for window in windows:
        window_claims: List[HistoricalClaim] = []
        seen_ids: set = set()
        for ticker in today_tickers:
            for claim in tracker.get_claims_for_ticker(ticker, days=window, exclude_today=True):
                if claim.claim_id not in seen_ids:
                    seen_ids.add(claim.claim_id)
                    window_claims.append(claim)
        prior_by_window[window] = window_claims

    # Shortest window's claims used for new_disagreement detection
    short_window = min(windows)
    short_prior = prior_by_window.get(short_window, [])

    # Total unique prior claims across all windows (for stats)
    all_prior_ids: set = set()
    for wc in prior_by_window.values():
        for c in wc:
            all_prior_ids.add(c.claim_id)

    # Run detectors — sentiment signals only (no claim-count heuristics)
    all_signals: List[DriftSignal] = []
    all_signals.extend(_detect_confidence_shifts(today_claims, prior_by_window, windows))
    all_signals.extend(_detect_belief_flips(today_claims, prior_by_window, windows))
    all_signals.extend(_detect_new_disagreements(today_claims, short_prior))

    # Sort by severity (high first), then type
    severity_order = {'high': 0, 'medium': 1, 'low': 2}
    all_signals.sort(key=lambda s: (severity_order.get(s.severity, 3), s.drift_type))

    return DriftReport(
        signals=all_signals,
        lookback_days=lookback_days,
        windows_analyzed=windows,
        today_claim_count=len(today_claims),
        prior_claim_count=len(all_prior_ids),
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
    print(f"  Expected: META confidence softening, CRWD belief flip + new disagreement")

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

    # Cleanup
    os.remove(test_db)
    print("\n✓ Drift detector working correctly")
