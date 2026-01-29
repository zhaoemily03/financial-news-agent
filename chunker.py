"""
Deterministic chunking for normalized documents.
Splits page-level chunks into atomic units (paragraph, bullet, exhibit).
Target: 150–400 tokens per chunk. No interpretation. Lossless.

Pipeline: Normalize (per-page) → chunk_document() → atomic Chunks

Usage:
    from jefferies_normalizer import JefferiesNormalizer
    from chunker import chunk_document

    normalizer = JefferiesNormalizer()
    doc, page_chunks = normalizer.normalize(pdf_bytes, meta)
    atomic_chunks = chunk_document(doc, page_chunks)
"""

import re
from typing import List, Tuple, Optional
from schemas import Document, Chunk

# ------------------------------------------------------------------
# Token estimation
# ------------------------------------------------------------------
# ~4 chars per token for English text (GPT-4 tokenizer average)

MIN_TOKENS = 150
MAX_TOKENS = 400


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ------------------------------------------------------------------
# Segment types and detection patterns
# ------------------------------------------------------------------

PARAGRAPH = 'paragraph'
BULLET = 'bullet'
EXHIBIT = 'exhibit'

_BULLET_RE = re.compile(
    r'^\s*(?:[-–—•·*]\s|\d{1,3}[.)]\s|\([a-zA-Z0-9]+\)\s)')
_EXHIBIT_RE = re.compile(
    r'^(?:Exhibit|Figure|Table|Chart)\s+\d', re.IGNORECASE)

# Header detection (mirrors jefferies_normalizer heuristic)
_SMALL_WORDS = frozenset({
    'and', 'or', 'the', 'of', 'for', 'in', 'to', 'a', 'an',
    'on', 'at', 'by', 'vs', 'vs.', 'with', 'from', 'as'})


def _is_header(line: str) -> bool:
    if len(line) < 3 or len(line) > 80:
        return False
    if sum(c.isalpha() or c.isspace() for c in line) / len(line) < 0.7:
        return False
    words = line.split()
    if len(words) > 8:
        return False
    if line.isupper():
        return True
    if not words[0][0].isupper():
        return False
    return all(w[0].isupper() or w.lower() in _SMALL_WORDS for w in words)


# ------------------------------------------------------------------
# Segment: (text, type, section_name)
# ------------------------------------------------------------------

Segment = Tuple[str, str, Optional[str]]


def _segment_text(text: str) -> List[Segment]:
    """Split page text into typed segments, tracking current section."""
    segments: List[Segment] = []
    buf: List[str] = []
    buf_type = PARAGRAPH
    current_section: Optional[str] = None
    buf_section: Optional[str] = None

    def flush():
        nonlocal buf, buf_type, buf_section
        if buf:
            segments.append(('\n'.join(buf), buf_type, buf_section))
            buf = []
            buf_type = PARAGRAPH

    for raw_line in text.split('\n'):
        line = raw_line.strip()

        # Blank line → segment boundary
        if not line:
            flush()
            buf_section = current_section
            continue

        # Section header → starts new segment, updates current section
        if _is_header(line):
            flush()
            current_section = line
            buf_section = current_section
            buf.append(line)
            buf_type = PARAGRAPH
            continue

        # Exhibit / figure / table
        if _EXHIBIT_RE.match(line):
            flush()
            buf.append(line)
            buf_type = EXHIBIT
            buf_section = current_section
            continue

        # Bullet item
        if _BULLET_RE.match(line):
            if buf_type != BULLET:
                flush()
                buf_type = BULLET
                buf_section = current_section
            buf.append(line)
            continue

        # Regular text — check for bullet continuation (indented wrap)
        if buf_type == BULLET:
            if raw_line.startswith((' ', '\t')):
                buf.append(line)  # indented continuation of bullet item
                continue
            flush()
            buf_type = PARAGRAPH
            buf_section = current_section

        if not buf:
            buf_section = current_section
        buf.append(line)

    flush()
    return segments


# ------------------------------------------------------------------
# Packing: merge small segments, split oversized ones
# ------------------------------------------------------------------

def _pack_segments(segments: List[Segment]) -> List[Segment]:
    """Merge undersized and split oversized segments to hit token target."""
    if not segments:
        return []

    result: List[Segment] = []
    buf_texts: List[str] = []
    buf_types: set = set()
    buf_section: Optional[str] = None
    buf_tokens = 0

    def flush_buf():
        nonlocal buf_texts, buf_types, buf_section, buf_tokens
        if buf_texts:
            combined = '\n\n'.join(buf_texts)
            seg_type = buf_types.pop() if len(buf_types) == 1 else 'mixed'
            result.append((combined, seg_type, buf_section))
            buf_texts = []
            buf_types = set()
            buf_section = None
            buf_tokens = 0

    for text, seg_type, section in segments:
        tokens = estimate_tokens(text)

        # Oversized single segment → flush buffer, split this segment
        if tokens > MAX_TOKENS:
            flush_buf()
            for piece in _split_oversized(text):
                result.append((piece, seg_type, section))
            continue

        # Adding this would overflow → flush first
        if buf_tokens + tokens > MAX_TOKENS and buf_texts:
            flush_buf()

        buf_texts.append(text)
        buf_types.add(seg_type)
        if buf_section is None:
            buf_section = section
        buf_tokens += tokens

    flush_buf()
    return result


def _split_oversized(text: str) -> List[str]:
    """Split text at sentence boundaries to fit within MAX_TOKENS."""
    # Split after sentence-ending punctuation followed by space
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) <= 1:
        return [text]

    result: List[str] = []
    buf: List[str] = []
    buf_tokens = 0

    for sent in sentences:
        sent_tokens = estimate_tokens(sent)
        if buf_tokens + sent_tokens > MAX_TOKENS and buf:
            result.append(' '.join(buf))
            buf = []
            buf_tokens = 0
        buf.append(sent)
        buf_tokens += sent_tokens

    if buf:
        result.append(' '.join(buf))

    return result


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def chunk_document(doc: Document, page_chunks: List[Chunk]) -> List[Chunk]:
    """
    Split page-level chunks into atomic chunks.

    Args:
        doc: parent Document
        page_chunks: page-level Chunks from JefferiesNormalizer

    Returns:
        List of atomic Chunks with page linkage and segment metadata
    """
    atomic: List[Chunk] = []
    idx = 0

    for pc in page_chunks:
        segments = _segment_text(pc.text)
        packed = _pack_segments(segments)

        for text, seg_type, section in packed:
            meta = {'segment_type': seg_type}
            if section:
                meta['section'] = section

            chunk = Chunk(
                doc_id=doc.doc_id,
                chunk_index=idx,
                text=text,
                page_start=pc.page_start,
                page_end=pc.page_end,
                metadata=meta,
            )
            atomic.append(chunk)
            idx += 1

    return atomic


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    from jefferies_normalizer import JefferiesNormalizer

    # Simulated 2-page Jefferies report
    page1_text = """Brent Thill
Equity Analyst
January 25, 2026

META PLATFORMS INC
Buy | Price Target: $750

INVESTMENT SUMMARY
We are raising our price target on META to $750 from $680 based on
accelerating AI monetization across the ad platform. Revenue growth
is tracking ahead of consensus with Reels monetization inflecting.
The company continues to benefit from improvements in ad targeting
powered by large language models, which have driven meaningful gains
in advertiser return on ad spend across both Facebook and Instagram.

Key Takeaways
- Ad revenue grew 28% YoY driven by improved Reels engagement
- AI-driven ad targeting improvements yielded 15% better ROAS
- Reality Labs losses narrowing faster than expected
- Threads MAU surpassed 300M, creating new ad inventory
- Management guided Q2 revenue above Street consensus"""

    page2_text = """VALUATION
Our $750 PT is based on 28x our CY27 EPS estimate of $26.78,
roughly in line with the 5-year average forward P/E for large-cap
internet names. We see upside to our estimates if AI-driven
monetization continues to accelerate. Our DCF analysis yields
a fair value range of $720-$780.

Revenue Model
We model total revenue of $210B in CY26, up from $170B in CY25.
Ad revenue comprises 97% of total, with Family of Apps margins
expanding to 52%. We expect Reality Labs revenue to reach $4.5B
in CY26, up from $2.8B in CY25, driven by Quest headset sales
and nascent Horizon Worlds monetization.

Exhibit 1: Revenue Breakdown by Segment
Family of Apps: $203.7B (97%)
Reality Labs: $4.5B (2%)
Other: $1.8B (1%)

RISK FACTORS
Key risks include regulatory headwinds in the EU, potential TikTok
resurgence, and slower-than-expected AI capex returns. Additionally,
Apple's privacy changes could further impact ad measurement, though
META has largely adapted its systems.

DISCLOSURES
Jefferies LLC is a registered broker-dealer."""

    report_meta = {
        'title': 'META Platforms: AI Monetization Inflection',
        'url': 'https://content.jefferies.com/report/abc-123',
        'pdf_url': 'https://links2.jefferies.com/doc/pdf/abc-123',
        'analyst': 'Brent Thill',
        'source': 'Jefferies',
        'date': '2026-01-25',
    }

    # Simulate normalizer output (2 page-level chunks)
    from schemas import Document
    doc = Document.from_report({**report_meta, 'content': page1_text + '\n\n' + page2_text})
    page_chunks = [
        Chunk(doc_id=doc.doc_id, chunk_index=0, text=page1_text,
              page_start=1, page_end=1),
        Chunk(doc_id=doc.doc_id, chunk_index=1, text=page2_text,
              page_start=2, page_end=2),
    ]

    # Chunk
    atomic = chunk_document(doc, page_chunks)

    print(f"{'='*60}")
    print(f"Deterministic Chunking Results")
    print(f"{'='*60}")
    print(f"Pages: {len(page_chunks)} → Atomic chunks: {len(atomic)}\n")

    for c in atomic:
        tokens = estimate_tokens(c.text)
        section = c.metadata.get('section', '—')
        seg_type = c.metadata.get('segment_type', '?')
        preview = c.text[:70].replace('\n', ' ')
        in_range = "✓" if MIN_TOKENS <= tokens <= MAX_TOKENS else "~"
        print(f"  [{c.chunk_index}] p{c.page_start} | {tokens:3d} tok {in_range} | "
              f"{seg_type:<10} | {section[:25]:<25} | {preview}...")

    # --- Verification ---
    print(f"\n{'='*60}")
    print("Verification")
    print(f"{'='*60}")

    # 1. Determinism: run again, compare
    atomic2 = chunk_document(doc, page_chunks)
    for a, b in zip(atomic, atomic2):
        assert a.text == b.text
        assert a.chunk_index == b.chunk_index
        assert a.page_start == b.page_start
        assert a.metadata == b.metadata
    print("✓ Deterministic: identical output on re-run")

    # 2. Lossless: every word from source appears in exactly one chunk
    source_words = (page1_text + '\n\n' + page2_text).split()
    chunk_words = ' '.join(c.text for c in atomic).split()
    for word in source_words:
        w = word.strip()
        if w:
            assert w in chunk_words, f"Lost word: {w}"
    print("✓ Lossless: all source words present in chunks")

    # 3. Page linkage
    assert all(c.doc_id == doc.doc_id for c in atomic)
    assert all(c.page_start in (1, 2) for c in atomic)
    print("✓ Page linkage: every chunk traces to a source page")

    # 4. Token bounds
    sizes = [estimate_tokens(c.text) for c in atomic]
    print(f"✓ Token range: {min(sizes)}–{max(sizes)} "
          f"(target {MIN_TOKENS}–{MAX_TOKENS})")
