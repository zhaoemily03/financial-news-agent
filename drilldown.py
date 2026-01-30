"""
Drill-down integrity — make every claim challengeable.

Analysts must be able to ask "Why is this here?" and get an instant answer.

Each claim links to:
- Original chunk text (verbatim source)
- PDF page reference
- Tier assignment reason
- Related claims (same ticker, same theme, same document)

Usage:
    from drilldown import DrillDownIndex, build_drilldown_index

    index = build_drilldown_index(claims, chunks, documents, tier_assignment)
    view = index.get_claim("chunk-123")
    print(view.format_markdown())
"""

from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict

from schemas import Document, Chunk
from claim_extractor import ClaimOutput
from tier_router import TierAssignment, get_tier_reasons


# ------------------------------------------------------------------
# Drill-Down View (answer to "Why is this here?")
# ------------------------------------------------------------------

@dataclass
class DrillDownView:
    """Complete provenance for a single claim."""
    # The claim
    claim: ClaimOutput
    tier: int                         # 1, 2, or 3

    # Original source
    chunk_text: str                   # verbatim chunk text
    pdf_page: Optional[str]           # "p.3" or "pp.3-5"
    document_title: str
    document_url: str
    pdf_url: str

    # Why it's here
    tier_reasons: List[str]           # explicit reasons for tier assignment

    # Related claims
    same_ticker_claims: List[str]     # chunk_ids of claims on same ticker
    same_doc_claims: List[str]        # chunk_ids of claims from same doc
    same_theme_claims: List[str]      # chunk_ids with same claim_type (thematic)

    def format_markdown(self) -> str:
        """Format drill-down as markdown for analyst review."""
        lines = []

        # Header
        ticker_tag = f"[{self.claim.ticker}]" if self.claim.ticker else "[Thematic]"
        lines.append(f"## Drill-Down: {ticker_tag} {self.claim.chunk_id}")
        lines.append("")

        # The claim itself
        lines.append("### Claim")
        for bullet in self.claim.bullets:
            lines.append(f"- {bullet}")
        lines.append(f"\n*{self.claim.source_citation}*")
        lines.append("")

        # Why is this here?
        lines.append("### Why Is This Here?")
        lines.append(f"**Tier {self.tier}** — {self._tier_label()}")
        lines.append("")
        for reason in self.tier_reasons:
            lines.append(f"- {reason}")
        lines.append("")

        # Judgment hooks
        lines.append("### Judgment Hooks")
        lines.append(f"- **Confidence**: {self.claim.confidence_level}")
        lines.append(f"- **Time Sensitivity**: {self.claim.time_sensitivity}")
        lines.append(f"- **Belief Pressure**: {self.claim.belief_pressure}")
        lines.append(f"- **Claim Type**: {self.claim.claim_type}")
        if self.claim.uncertainty_preserved:
            lines.append("- **Uncertainty**: Preserved from source")
        lines.append("")

        # Original source text
        lines.append("### Original Source Text")
        lines.append("```")
        # Truncate very long chunks
        text = self.chunk_text
        if len(text) > 1000:
            text = text[:1000] + "\n[...truncated...]"
        lines.append(text)
        lines.append("```")
        if self.pdf_page:
            lines.append(f"*PDF {self.pdf_page}*")
        lines.append("")

        # Document reference
        lines.append("### Source Document")
        lines.append(f"- **Title**: {self.document_title}")
        if self.document_url:
            lines.append(f"- **Report URL**: {self.document_url}")
        if self.pdf_url:
            lines.append(f"- **PDF URL**: {self.pdf_url}")
        lines.append("")

        # Related claims
        lines.append("### Related Claims")

        if self.same_ticker_claims:
            ticker = self.claim.ticker or "this topic"
            lines.append(f"\n**Same ticker ({ticker}):** {len(self.same_ticker_claims)}")
            for cid in self.same_ticker_claims[:5]:
                lines.append(f"- `{cid}`")
            if len(self.same_ticker_claims) > 5:
                lines.append(f"  *[+{len(self.same_ticker_claims) - 5} more]*")

        if self.same_doc_claims:
            lines.append(f"\n**Same document:** {len(self.same_doc_claims)}")
            for cid in self.same_doc_claims[:5]:
                lines.append(f"- `{cid}`")
            if len(self.same_doc_claims) > 5:
                lines.append(f"  *[+{len(self.same_doc_claims) - 5} more]*")

        if self.same_theme_claims:
            lines.append(f"\n**Same theme ({self.claim.claim_type}):** {len(self.same_theme_claims)}")
            for cid in self.same_theme_claims[:5]:
                lines.append(f"- `{cid}`")
            if len(self.same_theme_claims) > 5:
                lines.append(f"  *[+{len(self.same_theme_claims) - 5} more]*")

        if not (self.same_ticker_claims or self.same_doc_claims or self.same_theme_claims):
            lines.append("*No related claims found.*")

        return '\n'.join(lines)

    def _tier_label(self) -> str:
        """Human-readable tier label."""
        labels = {
            1: "Demands Attention Today",
            2: "Signal vs Noise",
            3: "Reference",
        }
        return labels.get(self.tier, "Unknown")

    def to_dict(self) -> dict:
        """Serialize for API/storage."""
        return {
            "chunk_id": self.claim.chunk_id,
            "tier": self.tier,
            "tier_reasons": self.tier_reasons,
            "pdf_page": self.pdf_page,
            "document_title": self.document_title,
            "same_ticker_claims": self.same_ticker_claims,
            "same_doc_claims": self.same_doc_claims,
            "same_theme_claims": self.same_theme_claims,
        }


# ------------------------------------------------------------------
# Drill-Down Index (all claims indexed for lookup)
# ------------------------------------------------------------------

@dataclass
class DrillDownIndex:
    """Index enabling instant drill-down for any claim."""
    # Core lookups
    claims_by_id: Dict[str, ClaimOutput] = field(default_factory=dict)
    chunks_by_id: Dict[str, Chunk] = field(default_factory=dict)
    docs_by_id: Dict[str, Document] = field(default_factory=dict)

    # Tier assignment
    tier_by_claim: Dict[str, int] = field(default_factory=dict)
    all_claims: List[ClaimOutput] = field(default_factory=list)

    # Relationship indexes
    claims_by_ticker: Dict[str, List[str]] = field(default_factory=dict)
    claims_by_doc: Dict[str, List[str]] = field(default_factory=dict)
    claims_by_type: Dict[str, List[str]] = field(default_factory=dict)

    def get_claim(self, chunk_id: str) -> Optional[DrillDownView]:
        """
        Get complete drill-down view for a claim.
        This answers: "Why is this here?"
        """
        claim = self.claims_by_id.get(chunk_id)
        if not claim:
            return None

        # Get source chunk and document
        chunk = self.chunks_by_id.get(claim.chunk_id)
        doc = self.docs_by_id.get(claim.doc_id)

        # Build PDF page reference
        pdf_page = None
        if chunk and chunk.page_start:
            if chunk.page_end and chunk.page_end != chunk.page_start:
                pdf_page = f"pp.{chunk.page_start}-{chunk.page_end}"
            else:
                pdf_page = f"p.{chunk.page_start}"

        # Get tier reasons
        tier = self.tier_by_claim.get(chunk_id, 3)
        tier_reasons = get_tier_reasons(claim, self.all_claims)

        # Find related claims (exclude self)
        same_ticker = [
            cid for cid in self.claims_by_ticker.get(claim.ticker or "", [])
            if cid != chunk_id
        ]
        same_doc = [
            cid for cid in self.claims_by_doc.get(claim.doc_id, [])
            if cid != chunk_id
        ]
        same_theme = [
            cid for cid in self.claims_by_type.get(claim.claim_type, [])
            if cid != chunk_id and not self.claims_by_id[cid].ticker  # thematic only
        ]

        return DrillDownView(
            claim=claim,
            tier=tier,
            chunk_text=chunk.text if chunk else "[Chunk not found]",
            pdf_page=pdf_page,
            document_title=doc.title if doc else "[Document not found]",
            document_url=doc.url if doc else "",
            pdf_url=doc.pdf_url if doc else "",
            tier_reasons=tier_reasons,
            same_ticker_claims=same_ticker,
            same_doc_claims=same_doc,
            same_theme_claims=same_theme,
        )

    def list_claims(self, tier: Optional[int] = None) -> List[str]:
        """List all claim IDs, optionally filtered by tier."""
        if tier is None:
            return list(self.claims_by_id.keys())
        return [cid for cid, t in self.tier_by_claim.items() if t == tier]

    def summary(self) -> str:
        """Summary of indexed content."""
        tier_counts = defaultdict(int)
        for t in self.tier_by_claim.values():
            tier_counts[t] += 1

        return (
            f"Claims: {len(self.claims_by_id)} | "
            f"Chunks: {len(self.chunks_by_id)} | "
            f"Docs: {len(self.docs_by_id)} | "
            f"T1: {tier_counts[1]} | T2: {tier_counts[2]} | T3: {tier_counts[3]}"
        )


# ------------------------------------------------------------------
# Index Builder
# ------------------------------------------------------------------

def build_drilldown_index(
    claims: List[ClaimOutput],
    chunks: List[Chunk],
    documents: List[Document],
    tier_assignment: TierAssignment,
) -> DrillDownIndex:
    """
    Build drill-down index from pipeline outputs.

    Args:
        claims: All extracted claims
        chunks: All source chunks
        documents: All source documents
        tier_assignment: Tier routing result

    Returns:
        DrillDownIndex ready for lookups
    """
    index = DrillDownIndex()

    # Index claims
    for claim in claims:
        index.claims_by_id[claim.chunk_id] = claim

    # Index chunks
    for chunk in chunks:
        index.chunks_by_id[chunk.chunk_id] = chunk

    # Index documents
    for doc in documents:
        index.docs_by_id[doc.doc_id] = doc

    # Store all claims for tier_reasons calculation
    index.all_claims = claims

    # Build tier mapping
    for claim in tier_assignment.tier_1:
        index.tier_by_claim[claim.chunk_id] = 1
    for claim in tier_assignment.tier_2:
        index.tier_by_claim[claim.chunk_id] = 2
    for claim in tier_assignment.tier_3:
        index.tier_by_claim[claim.chunk_id] = 3

    # Build relationship indexes
    by_ticker = defaultdict(list)
    by_doc = defaultdict(list)
    by_type = defaultdict(list)

    for claim in claims:
        if claim.ticker:
            by_ticker[claim.ticker].append(claim.chunk_id)
        by_doc[claim.doc_id].append(claim.chunk_id)
        by_type[claim.claim_type].append(claim.chunk_id)

    index.claims_by_ticker = dict(by_ticker)
    index.claims_by_doc = dict(by_doc)
    index.claims_by_type = dict(by_type)

    return index


# ------------------------------------------------------------------
# Quick Lookup Functions
# ------------------------------------------------------------------

def explain_claim(
    chunk_id: str,
    index: DrillDownIndex,
) -> str:
    """
    Quick answer to "Why is this claim here?"
    Returns one-line explanation.
    """
    view = index.get_claim(chunk_id)
    if not view:
        return f"Claim {chunk_id} not found in index."

    reasons = ' + '.join(view.tier_reasons[:2])
    return f"Tier {view.tier}: {reasons}"


def get_source_text(
    chunk_id: str,
    index: DrillDownIndex,
) -> Optional[str]:
    """Get original chunk text for a claim."""
    view = index.get_claim(chunk_id)
    return view.chunk_text if view else None


def get_related_claims(
    chunk_id: str,
    index: DrillDownIndex,
) -> Dict[str, List[str]]:
    """Get all related claims for a claim."""
    view = index.get_claim(chunk_id)
    if not view:
        return {}

    return {
        "same_ticker": view.same_ticker_claims,
        "same_document": view.same_doc_claims,
        "same_theme": view.same_theme_claims,
    }


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Drill-Down Integrity Test")
    print("=" * 60)

    # Create test data

    # Documents
    doc1 = Document(
        doc_id="doc-1",
        source="jefferies",
        title="META Platforms: AI Monetization Inflection",
        url="https://jefferies.com/report/123",
        pdf_url="https://jefferies.com/report/123.pdf",
        analyst="Brent Thill",
        date_published="2026-01-29",
    )

    doc2 = Document(
        doc_id="doc-2",
        source="jefferies",
        title="Cloud Infrastructure: 2026 Outlook",
        url="https://jefferies.com/report/456",
        pdf_url="https://jefferies.com/report/456.pdf",
        analyst="Joseph Gallo",
        date_published="2026-01-29",
    )

    # Chunks
    chunks = [
        Chunk(
            chunk_id="c1",
            doc_id="doc-1",
            text="""Breaking: META announced this morning that Threads daily active users
surpassed 300M, far exceeding analyst expectations of 200M. This
represents a significant acceleration from 150M DAU reported last quarter.
Management attributed growth to improved recommendation algorithms.""",
            page_start=2,
            page_end=2,
        ),
        Chunk(
            chunk_id="c2",
            doc_id="doc-1",
            text="""META Reality Labs losses narrowing faster than expected, down to
$3.5B in Q4 vs $4.2B in Q3. VR headset sales exceeded internal targets
by 15%, suggesting improving consumer adoption of the platform.""",
            page_start=5,
            page_end=6,
        ),
        Chunk(
            chunk_id="c3",
            doc_id="doc-2",
            text="""Cloud infrastructure demand projected to accelerate in 2026,
driven by enterprise AI workloads. We see AMZN and MSFT as primary
beneficiaries, with GOOGL gaining share in AI-specific workloads.""",
            page_start=3,
            page_end=3,
        ),
        Chunk(
            chunk_id="c4",
            doc_id="doc-2",
            text="""Rising interest rates may pressure growth stock valuations across
the tech sector. We note potential margin compression in software names
with high R&D intensity.""",
            page_start=8,
            page_end=8,
        ),
    ]

    # Claims
    claims = [
        ClaimOutput(
            chunk_id="c1",
            doc_id="doc-1",
            bullets=["META Threads surpassed 300M DAU, exceeding 200M consensus expectations"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, Brent Thill, p.2, 2026-01-29",
            confidence_level="high",
            time_sensitivity="breaking",
            belief_pressure="contradicts_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="c2",
            doc_id="doc-1",
            bullets=["META Reality Labs losses narrowing: $3.5B Q4 vs $4.2B Q3"],
            ticker="META",
            claim_type="fact",
            source_citation="Jefferies, Brent Thill, pp.5-6, 2026-01-29",
            confidence_level="high",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="c3",
            doc_id="doc-2",
            bullets=["Cloud infrastructure demand projected to accelerate in 2026"],
            ticker=None,
            claim_type="forecast",
            source_citation="Jefferies, Joseph Gallo, p.3, 2026-01-29",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=False,
        ),
        ClaimOutput(
            chunk_id="c4",
            doc_id="doc-2",
            bullets=["Rising interest rates may pressure growth stock valuations"],
            ticker=None,
            claim_type="risk",
            source_citation="Jefferies, Joseph Gallo, p.8, 2026-01-29",
            confidence_level="medium",
            time_sensitivity="ongoing",
            belief_pressure="confirms_consensus",
            uncertainty_preserved=True,
        ),
    ]

    # Tier assignment
    tier_assignment = TierAssignment(
        tier_1=[claims[0]],           # Breaking news
        tier_2=[claims[1], claims[2]], # Cluster
        tier_3=[claims[3]],           # Reference
    )

    # Build index
    print("\nBuilding drill-down index...")
    index = build_drilldown_index(
        claims=claims,
        chunks=chunks,
        documents=[doc1, doc2],
        tier_assignment=tier_assignment,
    )

    print(f"\n{index.summary()}\n")

    # Test drill-down for Tier 1 claim
    print("-" * 60)
    print("Drill-Down: Tier 1 Claim (c1)")
    print("-" * 60)

    view1 = index.get_claim("c1")
    print(view1.format_markdown())

    # Test drill-down for Tier 3 claim
    print("\n" + "-" * 60)
    print("Drill-Down: Tier 3 Claim (c4)")
    print("-" * 60)

    view4 = index.get_claim("c4")
    print(view4.format_markdown())

    # Test quick functions
    print("\n" + "-" * 60)
    print("Quick Lookup Functions")
    print("-" * 60)

    print(f"\nexplain_claim('c1'): {explain_claim('c1', index)}")
    print(f"explain_claim('c3'): {explain_claim('c3', index)}")
    print(f"explain_claim('c4'): {explain_claim('c4', index)}")

    print(f"\nget_related_claims('c1'): {get_related_claims('c1', index)}")
    print(f"get_related_claims('c3'): {get_related_claims('c3', index)}")

    # Verification
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    # All claims indexed
    assert len(index.claims_by_id) == len(claims)
    print("✓ All claims indexed")

    # Tier assignment preserved
    assert index.tier_by_claim["c1"] == 1
    assert index.tier_by_claim["c2"] == 2
    assert index.tier_by_claim["c4"] == 3
    print("✓ Tier assignments correct")

    # Chunk text available
    assert "300M" in view1.chunk_text
    print("✓ Original chunk text available")

    # PDF page reference
    assert view1.pdf_page == "p.2"
    assert index.get_claim("c2").pdf_page == "pp.5-6"
    print("✓ PDF page references correct")

    # Document links available
    assert view1.document_url == "https://jefferies.com/report/123"
    assert view1.pdf_url == "https://jefferies.com/report/123.pdf"
    print("✓ Document URLs available")

    # Related claims found
    assert "c2" in view1.same_ticker_claims  # c1 and c2 both META
    assert "c2" in view1.same_doc_claims     # c1 and c2 both doc-1
    print("✓ Related claims detected (same ticker, same doc)")

    # Tier reasons present
    assert len(view1.tier_reasons) > 0
    assert "breaking" in view1.tier_reasons[0].lower() or "contradict" in view1.tier_reasons[0].lower()
    print("✓ Tier reasons explain 'why is this here?'")

    # Thematic claims have theme relations
    view3 = index.get_claim("c3")
    view4 = index.get_claim("c4")
    # c3 and c4 are from same doc
    assert "c4" in view3.same_doc_claims or "c3" in view4.same_doc_claims
    print("✓ Thematic claims linked via document")

    print("\nDrill-down integrity validated. Analysts can challenge every claim.")
