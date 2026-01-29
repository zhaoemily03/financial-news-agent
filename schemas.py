"""
Minimal schemas for daily digest pipeline.
Version 1.0 — Document, Chunk, Claim, AnalystConfig.

Traceability chain: Claim → Chunk → Document → source PDF
Extensibility: from_dict ignores unknown keys, schema_version enables migration.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional
import hashlib
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now().isoformat()


# ------------------------------------------------------------------
# Document — a source PDF or article
# ------------------------------------------------------------------

@dataclass
class Document:
    schema_version: str = "1.0"
    doc_id: str = field(default_factory=_uuid)
    source: str = ""              # firm key: "jefferies", "jpmorgan", etc.
    source_type: str = "sellside" # "sellside" | "substack" | "x"
    title: str = ""
    url: str = ""                 # report page URL
    pdf_url: str = ""             # direct PDF download link
    analyst: str = ""
    date_published: Optional[str] = None  # YYYY-MM-DD
    date_ingested: str = field(default_factory=_now)
    content_hash: str = ""        # SHA-256 of raw text, for dedup

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_report(cls, report: dict) -> "Document":
        """Bridge from existing pipeline report dicts."""
        raw_text = report.get('content', '')
        return cls(
            source=report.get('source', '').lower(),
            source_type="sellside",
            title=report.get('title', ''),
            url=report.get('url', ''),
            pdf_url=report.get('pdf_url', ''),
            analyst=report.get('analyst', ''),
            date_published=report.get('date'),
            content_hash=compute_content_hash(raw_text) if raw_text else "",
        )


# ------------------------------------------------------------------
# Chunk — a segment of extracted text from a Document
# ------------------------------------------------------------------

@dataclass
class Chunk:
    schema_version: str = "1.0"
    chunk_id: str = field(default_factory=_uuid)
    doc_id: str = ""              # parent Document.doc_id
    chunk_index: int = 0          # position within document
    text: str = ""
    page_start: Optional[int] = None  # first PDF page (1-indexed)
    page_end: Optional[int] = None    # last PDF page (inclusive)
    metadata: Optional[Dict] = field(default=None)  # extensible annotations

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_document(cls, doc: Document, text: str) -> "Chunk":
        """Create a single chunk from a full document (no splitting)."""
        return cls(doc_id=doc.doc_id, chunk_index=0, text=text)


# ------------------------------------------------------------------
# Claim — a structured assertion extracted from a Chunk
# ------------------------------------------------------------------
# claim_type values: "rating_change", "price_target", "thesis",
#                    "catalyst", "risk", "data_point", "other"

@dataclass
class Claim:
    schema_version: str = "1.0"
    claim_id: str = field(default_factory=_uuid)
    doc_id: str = ""              # source Document.doc_id
    chunk_id: str = ""            # source Chunk.chunk_id
    claim_type: str = ""          # see valid types above
    ticker: Optional[str] = None
    content: str = ""             # the claim text
    confidence: Optional[float] = None  # 0.0–1.0
    extracted_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Claim":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ------------------------------------------------------------------
# AnalystConfig — analyst preferences driving relevance filtering
# ------------------------------------------------------------------

@dataclass
class AnalystConfig:
    schema_version: str = "1.0"
    tickers: Dict[str, List[str]] = field(default_factory=dict)
    ticker_priority: Dict[str, List[str]] = field(default_factory=dict)
    trusted_analysts: Dict[str, List[str]] = field(default_factory=dict)
    themes: List[Dict] = field(default_factory=list)
    sources: Dict[str, Dict] = field(default_factory=dict)
    briefing_days: int = 5
    relevance_threshold: float = 0.7

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AnalystConfig":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_config_module(cls) -> "AnalystConfig":
        """Build from existing config.py constants."""
        from config import (
            TICKERS, TICKER_PRIORITY, TRUSTED_ANALYSTS,
            INVESTMENT_THEMES, SOURCES, RELEVANCE_THRESHOLD,
        )
        return cls(
            tickers=TICKERS,
            ticker_priority=TICKER_PRIORITY,
            trusted_analysts=TRUSTED_ANALYSTS,
            themes=INVESTMENT_THEMES,
            sources=SOURCES,
            relevance_threshold=RELEVANCE_THRESHOLD,
        )

    def all_tickers_flat(self) -> List[str]:
        """Flat deduplicated ticker list across all groups."""
        return list({t for group in self.tickers.values() for t in group})


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------

def compute_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
