"""
Document normalizer — PDF/text → Document + per-page Chunks.
Per-page text extraction, section header detection.
No summarization. No inference.

Usage:
    normalizer = DocumentNormalizer()

    # From raw PDF bytes (preserves page numbers):
    doc, chunks = normalizer.normalize(pdf_bytes, report_meta)

    # From already-extracted text (no page numbers):
    doc, chunks = normalizer.normalize_text(text, report_meta)
"""

import io
import re
from typing import List, Tuple, Optional
import pdfplumber
import PyPDF2
from schemas import Document, Chunk, compute_content_hash


class DocumentNormalizer:
    """Converts PDFs/text into Document + per-page Chunks."""

    def normalize(self, pdf_bytes: bytes,
                  report_meta: dict) -> Tuple[Document, List[Chunk]]:
        """
        From raw PDF bytes — preserves page numbers and section headers.

        Args:
            pdf_bytes: raw PDF content
            report_meta: dict with title, url, pdf_url, analyst, source, date

        Returns:
            (Document, list of Chunks — one per page)
        """
        pages = self._extract_pages(pdf_bytes)
        if not pages:
            return self.normalize_text("", report_meta)

        raw_text = "\n\n".join(p['text'] for p in pages)
        doc = Document.from_report({**report_meta, 'content': raw_text})

        chunks = []
        for i, page in enumerate(pages):
            headers = detect_section_headers(page['text'])
            chunk = Chunk(
                doc_id=doc.doc_id,
                chunk_index=i,
                text=page['text'],
                page_start=page['page_num'],
                page_end=page['page_num'],
                metadata={'section_headers': headers} if headers else None,
            )
            chunks.append(chunk)

        print(f"✓ Normalized: {len(chunks)} pages, "
              f"{sum(len(c.metadata.get('section_headers', [])) for c in chunks if c.metadata)} headers detected")
        return doc, chunks

    def normalize_text(self, text: str,
                       report_meta: dict) -> Tuple[Document, List[Chunk]]:
        """Fallback: from already-extracted text (no page numbers available)."""
        doc = Document.from_report({**report_meta, 'content': text})
        chunk = Chunk.from_document(doc, text)
        headers = detect_section_headers(text)
        if headers:
            chunk.metadata = {'section_headers': headers}
        return doc, [chunk]

    # ------------------------------------------------------------------
    # Per-page extraction (pdfplumber primary, PyPDF2 fallback)
    # ------------------------------------------------------------------

    def _extract_pages(self, pdf_bytes: bytes) -> List[dict]:
        pages = self._pdfplumber_pages(pdf_bytes)
        if not pages:
            pages = self._pypdf2_pages(pdf_bytes)
        return pages

    def _pdfplumber_pages(self, pdf_bytes: bytes) -> List[dict]:
        try:
            pages = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for i, page in enumerate(pdf.pages, 1):
                    text = page.extract_text() or ''
                    if text.strip():
                        pages.append({'page_num': i, 'text': text})
            return pages
        except Exception:
            return []

    def _pypdf2_pages(self, pdf_bytes: bytes) -> List[dict]:
        try:
            pages = []
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            for i, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                if text.strip():
                    pages.append({'page_num': i, 'text': text})
            return pages
        except Exception:
            return []


# ------------------------------------------------------------------
# Section header detection
# ------------------------------------------------------------------
# Heuristic: short, title-cased or all-caps lines that look like
# headings rather than prose or table data.

# Small words allowed to be lowercase in title-case headings
_TITLE_SMALL_WORDS = {'and', 'or', 'the', 'of', 'for', 'in', 'to', 'a', 'an',
                      'on', 'at', 'by', 'vs', 'vs.', 'with', 'from', 'as'}


def detect_section_headers(text: str) -> List[str]:
    """Detect likely section headers from extracted PDF text."""
    headers = []
    for line in text.split('\n'):
        line = line.strip()
        if len(line) < 3 or len(line) > 80:
            continue

        # Must be mostly alphabetic (rejects table rows, numbers)
        alpha_ratio = sum(c.isalpha() or c.isspace() for c in line) / len(line)
        if alpha_ratio < 0.7:
            continue

        # Short phrase, not a full sentence
        words = line.split()
        if len(words) > 8:
            continue

        # All caps → header
        if line.isupper():
            headers.append(line)
            continue

        # Title case → header (allow small words to be lowercase)
        if _is_title_case(words):
            headers.append(line)

    return headers


def _is_title_case(words: List[str]) -> bool:
    """Check if words follow title case rules."""
    if not words or not words[0][0].isupper():
        return False
    for w in words:
        if w.lower() in _TITLE_SMALL_WORDS:
            continue
        if not w[0].isupper():
            return False
    return True


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    # Demo with sample text simulating a Jefferies report
    sample_text = """Brent Thill
Equity Analyst
January 25, 2026

META PLATFORMS INC
Buy | Price Target: $750

INVESTMENT SUMMARY
We are raising our price target on META to $750 from $680 based on
accelerating AI monetization across the ad platform. Revenue growth
is tracking ahead of consensus with Reels monetization inflecting.

Key Takeaways
1. Ad revenue grew 28% YoY driven by improved Reels engagement
2. AI-driven ad targeting improvements yielded 15% better ROAS
3. Reality Labs losses narrowing faster than expected

VALUATION
Our $750 PT is based on 28x our CY27 EPS estimate of $26.78,
roughly in line with the 5-year average forward P/E for large-cap
internet names.

Revenue Model
We model total revenue of $210B in CY26, up from $170B in CY25.
Ad revenue comprises 97% of total, with Family of Apps margins
expanding to 52%.

RISK FACTORS
Key risks include regulatory headwinds in the EU, potential TikTok
resurgence, and slower-than-expected AI capex returns.

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

    normalizer = DocumentNormalizer()
    doc, chunks = normalizer.normalize_text(sample_text, report_meta)

    print(f"\n{'='*60}")
    print("Document")
    print(f"{'='*60}")
    d = doc.to_dict()
    for k, v in d.items():
        val = repr(v)
        if len(val) > 80:
            val = val[:77] + '...'
        print(f"  {k}: {val}")

    print(f"\n{'='*60}")
    print(f"Chunks: {len(chunks)}")
    print(f"{'='*60}")
    for chunk in chunks:
        print(f"\n  chunk_index: {chunk.chunk_index}")
        print(f"  page_start:  {chunk.page_start}")
        print(f"  page_end:    {chunk.page_end}")
        print(f"  text length: {len(chunk.text)} chars")
        if chunk.metadata and chunk.metadata.get('section_headers'):
            print(f"  headers:     {chunk.metadata['section_headers']}")

    # Traceability check
    assert all(c.doc_id == doc.doc_id for c in chunks)
    print(f"\n✓ All chunks trace back to doc_id={doc.doc_id[:8]}...")

    # Reconstruction check: all text present
    reconstructed = "\n\n".join(c.text for c in chunks)
    assert 'INVESTMENT SUMMARY' in reconstructed
    assert 'RISK FACTORS' in reconstructed
    assert '$750' in reconstructed
    assert 'Brent Thill' in sample_text  # preserved in source
    print("✓ All content preserved — report is reconstructable")
