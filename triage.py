"""
Aggressive triage — volume kill step for <5-page daily briefing.
Uses Classification + AnalystConfig to aggressively reduce content.

Rules:
1. Drop low-novelty chunks (rehash, stale incremental)
2. De-duplicate similar chunks (Jaccard similarity)
3. Enforce relevance threshold
4. Cap total output

Constraint: If everything survives, triage has failed.

Usage:
    from triage import triage_chunks, TriageResult

    result = triage_chunks(chunks, classifications, source='jefferies')
    print(result.summary())
    surviving_chunks = result.kept
"""

import re
from typing import List, Tuple, Set, Dict, Optional
from dataclasses import dataclass, field
from collections import defaultdict

from schemas import Chunk
from classifier import ChunkClassification
from analyst_config_tmt import (
    score_chunk, RELEVANCE_THRESHOLD, MAX_CLAIM_COUNT,
    NOVELTY_WEIGHTS, MINIMUM_NOVELTY_THRESHOLD,
)

# ------------------------------------------------------------------
# Triage Configuration
# ------------------------------------------------------------------

# Similarity threshold for de-duplication (0.0-1.0)
# Lower = more aggressive dedup (0.3 means 30% token overlap triggers dedup)
SIMILARITY_THRESHOLD = 0.3

# If chunks share same ticker, use lower threshold (more aggressive)
SAME_TICKER_SIMILARITY_THRESHOLD = 0.20

# Minimum chunks to keep (even if all score below threshold)
MIN_SURVIVING_CHUNKS = 5

# Target compression ratio (input/output)
# If ratio < this, triage isn't aggressive enough
TARGET_COMPRESSION_RATIO = 2.0

# ------------------------------------------------------------------
# Drop Reasons (for audit trail)
# ------------------------------------------------------------------

class DropReason:
    LOW_NOVELTY = "low_novelty"           # rehash or stale incremental
    BELOW_THRESHOLD = "below_threshold"   # relevance score too low
    DUPLICATE = "duplicate"               # similar to higher-scoring chunk
    OVER_LIMIT = "over_limit"             # exceeded max claim count


# ------------------------------------------------------------------
# Triage Result (with audit trail)
# ------------------------------------------------------------------

@dataclass
class TriageResult:
    """Result of triage with full audit trail."""
    kept: List[Tuple[Chunk, ChunkClassification, float]]  # (chunk, clf, score)
    dropped: List[Tuple[Chunk, ChunkClassification, str]]  # (chunk, clf, reason)
    input_count: int
    output_count: int

    @property
    def compression_ratio(self) -> float:
        if self.output_count == 0:
            return float('inf')
        return self.input_count / self.output_count

    @property
    def drop_rate(self) -> float:
        if self.input_count == 0:
            return 0.0
        return len(self.dropped) / self.input_count

    def drop_counts(self) -> Dict[str, int]:
        """Count drops by reason."""
        counts = defaultdict(int)
        for _, _, reason in self.dropped:
            counts[reason] += 1
        return dict(counts)

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Triage Summary",
            f"  Input:  {self.input_count} chunks",
            f"  Output: {self.output_count} chunks",
            f"  Dropped: {len(self.dropped)} ({self.drop_rate:.0%})",
            f"  Compression: {self.compression_ratio:.1f}x",
        ]
        drops = self.drop_counts()
        if drops:
            lines.append("  Drop reasons:")
            for reason, count in sorted(drops.items(), key=lambda x: -x[1]):
                lines.append(f"    - {reason}: {count}")

        # Warning if triage didn't reduce enough
        if self.compression_ratio < TARGET_COMPRESSION_RATIO:
            lines.append(f"  ⚠ Warning: compression ratio below {TARGET_COMPRESSION_RATIO}x target")

        return '\n'.join(lines)


# ------------------------------------------------------------------
# Text Similarity (Jaccard on word tokens)
# ------------------------------------------------------------------

_WORD_RE = re.compile(r'\b\w+\b')


def _tokenize(text: str) -> Set[str]:
    """Extract lowercase word tokens."""
    return set(_WORD_RE.findall(text.lower()))


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity between two texts."""
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)

    return intersection / union if union > 0 else 0.0


def find_duplicates(
    chunks: List[Tuple[Chunk, ChunkClassification, float]],
    threshold: float = SIMILARITY_THRESHOLD,
) -> Set[str]:
    """
    Find chunk_ids that are duplicates of higher-scoring chunks.

    Uses text similarity + asset overlap for smarter dedup.
    Chunks with same ticker use lower threshold (more aggressive).

    Returns set of chunk_ids to drop.
    """
    # Sort by score descending (keep higher-scoring ones)
    sorted_chunks = sorted(chunks, key=lambda x: x[2], reverse=True)

    # Track kept items with their text and tickers
    kept_items: List[Tuple[str, str, Set[str]]] = []  # (chunk_id, text, tickers)
    duplicates: Set[str] = set()

    for chunk, clf, score in sorted_chunks:
        chunk_tickers = set(clf.asset_exposure) if clf.asset_exposure else set()
        is_dup = False

        for kept_id, kept_text, kept_tickers in kept_items:
            # Check for ticker overlap
            has_ticker_overlap = bool(chunk_tickers & kept_tickers)

            # Use lower threshold if same ticker (more aggressive dedup)
            effective_threshold = (
                SAME_TICKER_SIMILARITY_THRESHOLD if has_ticker_overlap
                else threshold
            )

            sim = jaccard_similarity(chunk.text, kept_text)
            if sim >= effective_threshold:
                is_dup = True
                break

        if is_dup:
            duplicates.add(chunk.chunk_id)
        else:
            kept_items.append((chunk.chunk_id, chunk.text, chunk_tickers))

    return duplicates


# ------------------------------------------------------------------
# Main Triage Function
# ------------------------------------------------------------------

def triage_chunks(
    chunks: List[Chunk],
    classifications: List[ChunkClassification],
    source: str = 'jefferies',
    max_output: Optional[int] = None,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> TriageResult:
    """
    Aggressively triage chunks to fit <5-page constraint.

    Steps:
    1. Score all chunks
    2. Drop low-novelty (rehash)
    3. Drop below relevance threshold
    4. De-duplicate similar chunks
    5. Cap at max output

    Args:
        chunks: Input Chunk objects
        classifications: Corresponding classifications
        source: Source name for scoring
        max_output: Max chunks to keep (default: MAX_CLAIM_COUNT)
        similarity_threshold: Jaccard threshold for dedup

    Returns:
        TriageResult with kept chunks and audit trail
    """
    if max_output is None:
        max_output = MAX_CLAIM_COUNT

    input_count = len(chunks)
    kept: List[Tuple[Chunk, ChunkClassification, float]] = []
    dropped: List[Tuple[Chunk, ChunkClassification, str]] = []

    # ------------------------------------------------------------------
    # Phase 1: Score and filter by novelty + relevance threshold
    # ------------------------------------------------------------------
    for chunk, clf in zip(chunks, classifications):
        # Check novelty first (hard filter)
        novelty_weight = NOVELTY_WEIGHTS.get(clf.novelty, 0.5)
        if novelty_weight < MINIMUM_NOVELTY_THRESHOLD:
            dropped.append((chunk, clf, DropReason.LOW_NOVELTY))
            continue

        # Score chunk
        score = score_chunk(chunk, clf, source)

        # Check relevance threshold
        if score < RELEVANCE_THRESHOLD:
            dropped.append((chunk, clf, DropReason.BELOW_THRESHOLD))
            continue

        kept.append((chunk, clf, score))

    # ------------------------------------------------------------------
    # Phase 2: De-duplicate similar chunks
    # ------------------------------------------------------------------
    if len(kept) > 1:
        duplicate_ids = find_duplicates(kept, similarity_threshold)

        new_kept = []
        for chunk, clf, score in kept:
            if chunk.chunk_id in duplicate_ids:
                dropped.append((chunk, clf, DropReason.DUPLICATE))
            else:
                new_kept.append((chunk, clf, score))
        kept = new_kept

    # ------------------------------------------------------------------
    # Phase 3: Sort by score and cap at max
    # ------------------------------------------------------------------
    kept.sort(key=lambda x: x[2], reverse=True)

    if len(kept) > max_output:
        over_limit = kept[max_output:]
        for chunk, clf, score in over_limit:
            dropped.append((chunk, clf, DropReason.OVER_LIMIT))
        kept = kept[:max_output]

    # ------------------------------------------------------------------
    # Validation: ensure minimum survival
    # ------------------------------------------------------------------
    # If we dropped too much, pull back some from dropped (by score)
    # Never recover: low_novelty (stale content) or duplicates (redundant)
    if len(kept) < MIN_SURVIVING_CHUNKS and dropped:
        recoverable = [
            (c, clf, score_chunk(c, clf, source))
            for c, clf, reason in dropped
            if reason not in (DropReason.LOW_NOVELTY, DropReason.DUPLICATE)
        ]
        recoverable.sort(key=lambda x: x[2], reverse=True)

        needed = MIN_SURVIVING_CHUNKS - len(kept)
        for item in recoverable[:needed]:
            kept.append(item)
            # Remove from dropped
            dropped = [(c, clf, r) for c, clf, r in dropped
                       if c.chunk_id != item[0].chunk_id]

        kept.sort(key=lambda x: x[2], reverse=True)

    return TriageResult(
        kept=kept,
        dropped=dropped,
        input_count=input_count,
        output_count=len(kept),
    )


# ------------------------------------------------------------------
# Convenience: get just the chunks
# ------------------------------------------------------------------

def get_triaged_chunks(result: TriageResult) -> List[Chunk]:
    """Extract just the Chunk objects from triage result."""
    return [chunk for chunk, _, _ in result.kept]


def get_triaged_with_scores(result: TriageResult) -> List[Tuple[Chunk, float]]:
    """Extract (Chunk, score) pairs from triage result."""
    return [(chunk, score) for chunk, _, score in result.kept]


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    from classifier import ChunkClassification

    print("=" * 60)
    print("Aggressive Triage Test")
    print("=" * 60)

    # Create test data with intentional redundancy and low-quality chunks
    test_chunks = []
    test_classifications = []

    # High-quality, unique chunks (should survive)
    test_chunks.append(Chunk(chunk_id="1", doc_id="doc", text="""
        META is raising price target to $750 based on AI monetization.
        Revenue growth tracking ahead with Reels inflecting positively.
        AI-driven ad targeting yielding 15% better ROAS across platforms.
    """))
    test_classifications.append(ChunkClassification(
        chunk_id="1", topic="ai_ml", asset_exposure=["META"],
        content_type="forecast", polarity="positive", novelty="new",
    ))

    test_chunks.append(Chunk(chunk_id="2", doc_id="doc", text="""
        CRWD faces regulatory headwinds in EU market expansion.
        Potential TikTok resurgence poses competitive threat.
        Apple privacy changes continue to impact measurement.
    """))
    test_classifications.append(ChunkClassification(
        chunk_id="2", topic="cybersecurity", asset_exposure=["CRWD"],
        content_type="risk", polarity="negative", novelty="new",
    ))

    # Duplicate of chunk 1 (should be deduped)
    test_chunks.append(Chunk(chunk_id="3", doc_id="doc", text="""
        META raising PT to $750 on AI monetization acceleration.
        Revenue growth ahead of consensus, Reels monetization inflecting.
        AI ad targeting improvements driving 15% ROAS gains.
    """))
    test_classifications.append(ChunkClassification(
        chunk_id="3", topic="advertising", asset_exposure=["META"],
        content_type="forecast", polarity="positive", novelty="incremental",
    ))

    # Low novelty - rehash (should be dropped)
    test_chunks.append(Chunk(chunk_id="4", doc_id="doc", text="""
        As widely reported, META continues to be a large-cap internet company.
        The company operates Facebook and Instagram social networks.
        Advertising remains the primary revenue source.
    """))
    test_classifications.append(ChunkClassification(
        chunk_id="4", topic="social", asset_exposure=["META"],
        content_type="fact", polarity="neutral", novelty="rehash",
    ))

    # Low relevance - off topic (should be dropped if below threshold)
    test_chunks.append(Chunk(chunk_id="5", doc_id="doc", text="""
        General market commentary on macroeconomic conditions.
        Interest rates may impact growth stocks broadly.
        Consumer spending patterns showing mixed signals.
    """))
    test_classifications.append(ChunkClassification(
        chunk_id="5", topic="general", asset_exposure=[],
        content_type="interpretation", polarity="neutral", novelty="incremental",
    ))

    # Medium quality (might survive depending on threshold)
    test_chunks.append(Chunk(chunk_id="6", doc_id="doc", text="""
        GOOGL cloud revenue growing 28% YoY on enterprise adoption.
        AI workloads driving incremental compute demand.
        Margin expansion expected as scale improves efficiency.
    """))
    test_classifications.append(ChunkClassification(
        chunk_id="6", topic="cloud", asset_exposure=["GOOGL"],
        content_type="fact", polarity="positive", novelty="new",
    ))

    # Another duplicate-ish of chunk 2
    test_chunks.append(Chunk(chunk_id="7", doc_id="doc", text="""
        CRWD regulatory challenges in European Union markets.
        TikTok competition remains a potential headwind.
        Privacy regulation changes affecting ad measurement accuracy.
    """))
    test_classifications.append(ChunkClassification(
        chunk_id="7", topic="cybersecurity", asset_exposure=["CRWD"],
        content_type="risk", polarity="negative", novelty="incremental",
    ))

    # Run triage
    print(f"\nInput: {len(test_chunks)} chunks\n")

    result = triage_chunks(test_chunks, test_classifications)

    print(result.summary())

    print("\n" + "-" * 60)
    print("Surviving Chunks:")
    print("-" * 60)
    for chunk, clf, score in result.kept:
        preview = chunk.text.strip()[:60].replace('\n', ' ')
        print(f"  [{chunk.chunk_id}] {clf.topic:<12} score={score:.3f} | {preview}...")

    print("\n" + "-" * 60)
    print("Dropped Chunks:")
    print("-" * 60)
    for chunk, clf, reason in result.dropped:
        preview = chunk.text.strip()[:40].replace('\n', ' ')
        print(f"  [{chunk.chunk_id}] {reason:<16} | {preview}...")

    # Verification
    print("\n" + "=" * 60)
    print("Verification")
    print("=" * 60)

    # Must drop something
    assert len(result.dropped) > 0, "Triage must drop at least one chunk"
    print("✓ Triage dropped chunks (not everything survived)")

    # Rehash must be dropped
    rehash_kept = [c for c, clf, _ in result.kept if clf.novelty == 'rehash']
    assert len(rehash_kept) == 0, "Rehash content should not survive"
    print("✓ Low-novelty (rehash) filtered out")

    # Duplicates should be reduced
    meta_chunks = [c for c, clf, _ in result.kept if 'META' in clf.asset_exposure]
    assert len(meta_chunks) <= 1, "Duplicate META chunks should be deduped"
    print("✓ Similar chunks de-duplicated")

    # Compression ratio check (small test set limits compression)
    assert result.compression_ratio >= 1.3, "Should achieve meaningful compression"
    print(f"✓ Compression ratio: {result.compression_ratio:.1f}x (target ≥2.0x with real data)")

    # Audit trail complete
    assert result.input_count == len(test_chunks)
    assert result.output_count + len(result.dropped) == result.input_count
    print("✓ Full audit trail preserved")

    print(f"\nTriage validated. Ready for <5-page briefing constraint.")
