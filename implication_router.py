"""
Implication routing for Tier 3 — index claims to coverage universe.
Maps claims to covered stocks and active theses WITHOUT analysis.

Think: index, not analysis.

Output per claim:
- covered_tickers: Tickers from coverage that relate
- related_themes: Investment themes that relate

No new insights. No summaries. Just linking.

Usage:
    from implication_router import build_tier3_index, Tier3Index

    index = build_tier3_index(tier_3_claims)
    print(index.by_ticker['META'])  # claims related to META
    print(index.by_theme['AI & Machine Learning'])  # claims related to AI
"""

import re
from typing import List, Dict, Set, Optional
from dataclasses import dataclass, field
from collections import defaultdict

from claim_extractor import ClaimOutput
from config import (
    TICKERS,
    ALL_TICKERS,
    INVESTMENT_THEMES,
    TICKER_PRIORITY,
)

# ------------------------------------------------------------------
# Implication Map Schema
# ------------------------------------------------------------------

@dataclass
class ImplicationMap:
    """Mapping of a single claim to coverage universe."""
    claim: ClaimOutput
    covered_tickers: List[str] = field(default_factory=list)  # tickers from coverage
    related_themes: List[str] = field(default_factory=list)   # theme names
    ticker_priority: str = "none"  # "high", "medium", or "none"

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.claim.chunk_id,
            "covered_tickers": self.covered_tickers,
            "related_themes": self.related_themes,
            "ticker_priority": self.ticker_priority,
        }

    def has_coverage(self) -> bool:
        """True if claim maps to any covered ticker or theme."""
        return bool(self.covered_tickers or self.related_themes)


@dataclass
class Tier3Index:
    """Complete index for Tier 3 reference material."""
    by_ticker: Dict[str, List[ClaimOutput]] = field(default_factory=dict)
    by_theme: Dict[str, List[ClaimOutput]] = field(default_factory=dict)
    mappings: List[ImplicationMap] = field(default_factory=list)
    unlinked: List[ClaimOutput] = field(default_factory=list)  # no coverage match

    def summary(self) -> str:
        tickers = len(self.by_ticker)
        themes = len(self.by_theme)
        linked = len([m for m in self.mappings if m.has_coverage()])
        unlinked = len(self.unlinked)
        return f"Linked: {linked} | Unlinked: {unlinked} | Tickers: {tickers} | Themes: {themes}"

    def to_dict(self) -> dict:
        return {
            "by_ticker": {k: [c.chunk_id for c in v] for k, v in self.by_ticker.items()},
            "by_theme": {k: [c.chunk_id for c in v] for k, v in self.by_theme.items()},
            "unlinked": [c.chunk_id for c in self.unlinked],
        }


# ------------------------------------------------------------------
# Ticker Matching
# ------------------------------------------------------------------

def _extract_tickers_from_text(text: str) -> Set[str]:
    """
    Extract ticker symbols from text.
    Looks for: $TICKER, (TICKER), TICKER:, or standalone caps.
    """
    found = set()

    # Pattern 1: $TICKER
    for match in re.findall(r'\$([A-Z]{2,5})', text):
        found.add(match)

    # Pattern 2: (TICKER) - common in research
    for match in re.findall(r'\(([A-Z]{2,5})\)', text):
        found.add(match)

    # Pattern 3: Check for known tickers as whole words
    text_upper = text.upper()
    for ticker in ALL_TICKERS:
        # Match as whole word
        pattern = r'\b' + re.escape(ticker) + r'\b'
        if re.search(pattern, text_upper):
            found.add(ticker)

    return found


def _find_covered_tickers(claim: ClaimOutput) -> List[str]:
    """Find which covered tickers a claim relates to."""
    related = set()

    # Direct ticker on claim
    if claim.ticker and claim.ticker in ALL_TICKERS:
        related.add(claim.ticker)

    # Tickers mentioned in bullets
    for bullet in claim.bullets:
        mentioned = _extract_tickers_from_text(bullet)
        related.update(mentioned & set(ALL_TICKERS))

    return sorted(related)


def _get_ticker_priority(tickers: List[str]) -> str:
    """Get highest priority among tickers."""
    if not tickers:
        return "none"

    high_tickers = set(TICKER_PRIORITY.get('high', []))
    medium_tickers = set(TICKER_PRIORITY.get('medium', []))

    for ticker in tickers:
        if ticker in high_tickers:
            return "high"

    for ticker in tickers:
        if ticker in medium_tickers:
            return "medium"

    return "none"


# ------------------------------------------------------------------
# Theme Matching
# ------------------------------------------------------------------

def _find_related_themes(claim: ClaimOutput) -> List[str]:
    """Find which investment themes a claim relates to."""
    related = []

    # Combine all text for matching
    text = ' '.join(claim.bullets).lower()

    for theme in INVESTMENT_THEMES:
        theme_name = theme['name']
        keywords = theme.get('keywords', [])

        # Check if any keyword matches
        for keyword in keywords:
            if keyword.lower() in text:
                related.append(theme_name)
                break  # only add theme once

    return related


# ------------------------------------------------------------------
# Main Index Builder
# ------------------------------------------------------------------

def build_tier3_index(claims: List[ClaimOutput]) -> Tier3Index:
    """
    Build index mapping Tier 3 claims to coverage universe.

    Maps each claim to:
    - Covered tickers (from config.py TICKERS)
    - Related themes (from config.py INVESTMENT_THEMES)

    No analysis. No insights. Just linking.

    Args:
        claims: List of Tier 3 claims

    Returns:
        Tier3Index with claims organized by ticker/theme
    """
    index = Tier3Index()
    by_ticker = defaultdict(list)
    by_theme = defaultdict(list)

    for claim in claims:
        # Find coverage links
        covered = _find_covered_tickers(claim)
        themes = _find_related_themes(claim)
        priority = _get_ticker_priority(covered)

        # Create mapping
        mapping = ImplicationMap(
            claim=claim,
            covered_tickers=covered,
            related_themes=themes,
            ticker_priority=priority,
        )
        index.mappings.append(mapping)

        # Index by ticker
        for ticker in covered:
            by_ticker[ticker].append(claim)

        # Index by theme
        for theme in themes:
            by_theme[theme].append(claim)

        # Track unlinked
        if not mapping.has_coverage():
            index.unlinked.append(claim)

    index.by_ticker = dict(by_ticker)
    index.by_theme = dict(by_theme)

    return index


# ------------------------------------------------------------------
# Formatting (index view, not analysis)
# ------------------------------------------------------------------

def format_tier3_index_markdown(index: Tier3Index) -> str:
    """
    Format Tier 3 index as markdown.
    Just listing, no synthesis.
    """
    lines = []

    lines.append("## Tier 3: Reference Index")
    lines.append(f"*{index.summary()}*\n")

    # By ticker (if any)
    if index.by_ticker:
        lines.append("### By Ticker")
        for ticker in sorted(index.by_ticker.keys()):
            claims = index.by_ticker[ticker]
            lines.append(f"\n**{ticker}** ({len(claims)} claims)")
            for claim in claims:
                bullet = claim.bullets[0][:80] + "..." if len(claim.bullets[0]) > 80 else claim.bullets[0]
                lines.append(f"- {bullet}")
                lines.append(f"  *{claim.source_citation}*")

    # By theme (if any)
    if index.by_theme:
        lines.append("\n### By Theme")
        for theme in sorted(index.by_theme.keys()):
            claims = index.by_theme[theme]
            lines.append(f"\n**{theme}** ({len(claims)} claims)")
            for claim in claims:
                ticker_tag = f"[{claim.ticker}] " if claim.ticker else ""
                bullet = claim.bullets[0][:80] + "..." if len(claim.bullets[0]) > 80 else claim.bullets[0]
                lines.append(f"- {ticker_tag}{bullet}")
                lines.append(f"  *{claim.source_citation}*")

    # Unlinked (no coverage match)
    if index.unlinked:
        lines.append("\n### Unlinked (outside coverage)")
        for claim in index.unlinked:
            bullet = claim.bullets[0][:80] + "..." if len(claim.bullets[0]) > 80 else claim.bullets[0]
            lines.append(f"- {bullet}")
            lines.append(f"  *{claim.source_citation}*")

    return '\n'.join(lines)


def get_claims_for_ticker(index: Tier3Index, ticker: str) -> List[ClaimOutput]:
    """Get all claims related to a specific ticker."""
    return index.by_ticker.get(ticker, [])


def get_claims_for_theme(index: Tier3Index, theme: str) -> List[ClaimOutput]:
    """Get all claims related to a specific theme."""
    return index.by_theme.get(theme, [])


def get_high_priority_claims(index: Tier3Index) -> List[ClaimOutput]:
    """Get claims linked to high-priority tickers."""
    return [m.claim for m in index.mappings if m.ticker_priority == "high"]


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Tier 3 Implication Router Test")
    print("=" * 60)

    # Test claims simulating Tier 3 reference material
    test_claims = [
        # Direct ticker match (META - primary)
        ClaimOutput(
            chunk_id="t3-1",
            doc_id="doc1",
            bullets=["META Reality Labs R&D spending increased 20% YoY"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, p.5",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # Theme match (AI & ML)
        ClaimOutput(
            chunk_id="t3-2",
            doc_id="doc1",
            bullets=["Enterprise AI infrastructure spending continues to accelerate"],
            ticker=None,
            claim_type="fact",
            source_citation="Jefferies, p.8",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # Multiple ticker mentions in bullet
        ClaimOutput(
            chunk_id="t3-3",
            doc_id="doc1",
            bullets=["Cloud market share: AMZN (32%), MSFT (23%), GOOGL (10%)"],
            ticker=None,
            claim_type="fact",
            source_citation="Jefferies, p.12",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # Theme + ticker (Cybersecurity + CRWD)
        ClaimOutput(
            chunk_id="t3-4",
            doc_id="doc1",
            bullets=["CRWD maintaining endpoint protection market leadership with XDR expansion"],
            ticker="CRWD",
            claim_type="fact",
            source_citation="Jefferies, p.15",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # Theme match (Digital Transformation)
        ClaimOutput(
            chunk_id="t3-5",
            doc_id="doc1",
            bullets=["SaaS adoption rates remain strong in mid-market enterprise segment"],
            ticker=None,
            claim_type="fact",
            source_citation="Jefferies, p.18",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        # Unlinked (no coverage match)
        ClaimOutput(
            chunk_id="t3-6",
            doc_id="doc1",
            bullets=["European consumer sentiment improving in Q4 surveys"],
            ticker=None,
            claim_type="fact",
            source_citation="Jefferies, p.22",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="unclear",
            uncertainty_preserved=False,
        ),
        # Watchlist ticker (NFLX - medium priority)
        ClaimOutput(
            chunk_id="t3-7",
            doc_id="doc1",
            bullets=["NFLX ad-supported tier subscriber growth ahead of internal projections"],
            ticker="NFLX",
            claim_type="fact",
            source_citation="Jefferies, p.25",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
    ]

    print(f"\nInput: {len(test_claims)} Tier 3 claims")
    print("Testing: ticker matching, theme matching, priority assignment\n")

    # Build index
    index = build_tier3_index(test_claims)

    print("-" * 60)
    print("Index Summary")
    print("-" * 60)
    print(f"\n{index.summary()}\n")

    print("-" * 60)
    print("Claims by Ticker")
    print("-" * 60)
    for ticker, claims in sorted(index.by_ticker.items()):
        priority = "primary" if ticker in TICKER_PRIORITY.get('high', []) else "watchlist"
        print(f"\n{ticker} ({priority}): {len(claims)} claims")
        for c in claims:
            print(f"  - [{c.chunk_id}] {c.bullets[0][:50]}...")

    print("\n" + "-" * 60)
    print("Claims by Theme")
    print("-" * 60)
    for theme, claims in sorted(index.by_theme.items()):
        print(f"\n{theme}: {len(claims)} claims")
        for c in claims:
            ticker_tag = f"[{c.ticker}] " if c.ticker else ""
            print(f"  - [{c.chunk_id}] {ticker_tag}{c.bullets[0][:50]}...")

    print("\n" + "-" * 60)
    print("Unlinked Claims (outside coverage)")
    print("-" * 60)
    for c in index.unlinked:
        print(f"  - [{c.chunk_id}] {c.bullets[0][:50]}...")

    print("\n" + "-" * 60)
    print("Mapping Details")
    print("-" * 60)
    for m in index.mappings:
        c = m.claim
        print(f"\n[{c.chunk_id}] {c.bullets[0][:40]}...")
        print(f"  Tickers: {m.covered_tickers or 'none'}")
        print(f"  Themes: {m.related_themes or 'none'}")
        print(f"  Priority: {m.ticker_priority}")

    # Verification
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    # All claims processed
    assert len(index.mappings) == len(test_claims)
    print("✓ All claims processed")

    # t3-1: META should be linked to META ticker
    m1 = [m for m in index.mappings if m.claim.chunk_id == "t3-1"][0]
    assert "META" in m1.covered_tickers
    assert m1.ticker_priority == "high"
    print("✓ Direct ticker match (META) with high priority")

    # t3-2: Should match AI & ML theme
    m2 = [m for m in index.mappings if m.claim.chunk_id == "t3-2"][0]
    assert "AI & Machine Learning" in m2.related_themes
    print("✓ Theme match (AI & Machine Learning)")

    # t3-3: Should find multiple tickers in bullet
    m3 = [m for m in index.mappings if m.claim.chunk_id == "t3-3"][0]
    assert "AMZN" in m3.covered_tickers
    assert "MSFT" in m3.covered_tickers
    assert "GOOGL" in m3.covered_tickers
    print("✓ Multiple ticker extraction from bullet")

    # t3-4: Should match both ticker and theme
    m4 = [m for m in index.mappings if m.claim.chunk_id == "t3-4"][0]
    assert "CRWD" in m4.covered_tickers
    assert "Cybersecurity" in m4.related_themes
    print("✓ Combined ticker + theme match (CRWD + Cybersecurity)")

    # t3-5: Should match Digital Transformation
    m5 = [m for m in index.mappings if m.claim.chunk_id == "t3-5"][0]
    assert "Digital Transformation" in m5.related_themes
    print("✓ Theme match (Digital Transformation via 'SaaS adoption')")

    # t3-6: Should be unlinked
    assert any(c.chunk_id == "t3-6" for c in index.unlinked)
    print("✓ Unlinked claim detected (European consumer sentiment)")

    # t3-7: Watchlist ticker should have medium priority
    m7 = [m for m in index.mappings if m.claim.chunk_id == "t3-7"][0]
    assert "NFLX" in m7.covered_tickers
    assert m7.ticker_priority == "medium"
    print("✓ Watchlist ticker (NFLX) with medium priority")

    # Index lookups work
    meta_claims = get_claims_for_ticker(index, "META")
    assert len(meta_claims) >= 1
    print(f"✓ Ticker lookup: {len(meta_claims)} claims for META")

    ai_claims = get_claims_for_theme(index, "AI & Machine Learning")
    assert len(ai_claims) >= 1
    print(f"✓ Theme lookup: {len(ai_claims)} claims for AI & Machine Learning")

    high_priority = get_high_priority_claims(index)
    assert len(high_priority) >= 1
    print(f"✓ Priority filter: {len(high_priority)} high-priority claims")

    print("\n" + "=" * 60)
    print("Markdown Output Preview")
    print("=" * 60)
    print(format_tier3_index_markdown(index))
