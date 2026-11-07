"""Page-aware PDF text extraction and chunking for financial reports."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from configs.financebench import PDF_CHUNK_OVERLAP, PDF_CHUNK_SIZE
from src.ingestion.chunker import chunk_text, count_tokens


class PdfIngestionError(RuntimeError):
    """Raised when a source PDF cannot be parsed reliably."""


def _normalize_page_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_pdf_page_text(text: str | None) -> str:
    """Remove repeated horizontal layout padding before chunking for retrieval."""
    text = _normalize_page_text(text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def extract_pdf_pages(pdf_path: Path) -> list[dict[str, Any]]:
    """Extract every PDF page with a stable zero-based page index.

    Empty-text pages are returned and counted. pypdf does not perform OCR, so
    image-only pages remain empty and are handled as retrieval misses later.
    """
    try:
        reader = PdfReader(str(pdf_path), strict=False)
        pages = []
        for page_number, page in enumerate(reader.pages):
            try:
                text = page.extract_text(
                    extraction_mode="layout",
                    layout_mode_space_vertically=False,
                )
            except Exception as exc:  # pypdf errors vary by malformed source PDF
                raise PdfIngestionError(
                    f"Unable to extract page {page_number} from {pdf_path.name}"
                ) from exc
            pages.append(
                {
                    "page_number": page_number,
                    "text": _normalize_page_text(text),
                }
            )
        return pages
    except PdfIngestionError:
        raise
    except Exception as exc:
        raise PdfIngestionError(f"Unable to read PDF {pdf_path}") from exc


def ingest_pdf_document(
    pdf_path: Path,
    *,
    document_metadata: Mapping[str, Any],
    chunk_size: int = PDF_CHUNK_SIZE,
    overlap: int = PDF_CHUNK_OVERLAP,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Extract and chunk a report while retaining source-page provenance."""
    doc_name = document_metadata.get("doc_name")
    company = document_metadata.get("company")
    if not isinstance(doc_name, str) or not doc_name:
        raise ValueError("document_metadata.doc_name must be a non-empty string")
    if not isinstance(company, str) or not company:
        raise ValueError(f"document_metadata.company is required for {doc_name}")

    pages = extract_pdf_pages(pdf_path)
    chunks, stats = chunk_pdf_pages(
        pages,
        document_metadata=document_metadata,
        chunk_size=chunk_size,
        overlap=overlap,
    )
    stats["page_count"] = len(pages)
    return chunks, stats


def chunk_pdf_pages(
    pages: list[dict[str, Any]],
    *,
    document_metadata: Mapping[str, Any],
    chunk_size: int = PDF_CHUNK_SIZE,
    overlap: int = PDF_CHUNK_OVERLAP,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Chunk previously extracted pages without dropping their page indexes."""
    doc_name = document_metadata.get("doc_name")
    company = document_metadata.get("company")
    if not isinstance(doc_name, str) or not doc_name:
        raise ValueError("document_metadata.doc_name must be a non-empty string")
    if not isinstance(company, str) or not company:
        raise ValueError(f"document_metadata.company is required for {doc_name}")
    doc_key = hashlib.sha256(doc_name.encode("utf-8")).hexdigest()[:12]
    chunks: list[dict[str, Any]] = []
    nonempty_pages = 0
    extracted_chars = 0
    for page in pages:
        text = normalize_pdf_page_text(page["text"])
        if not text:
            continue
        nonempty_pages += 1
        extracted_chars += len(text)
        page_number = page["page_number"]
        pieces = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        for chunk_index, piece in enumerate(pieces):
            chunks.append(
                {
                    "chunk_id": f"financebench_{doc_key}_p{page_number:04d}_c{chunk_index:03d}",
                    "dataset_id": "financebench",
                    "document_id": doc_name,
                    "doc_name": doc_name,
                    "company": company,
                    "doc_type": document_metadata.get("doc_type"),
                    "reporting_periods": list(
                        document_metadata.get("reporting_periods", ())
                    ),
                    "metadata_conflicts": list(
                        document_metadata.get("metadata_conflicts", ())
                    ),
                    "source_url": document_metadata.get("doc_link"),
                    "source_repository_url": document_metadata.get(
                        "source_repository_url"
                    ),
                    "page_number": page_number,
                    "section": "document",
                    "chunk_index": chunk_index,
                    "token_count": count_tokens(piece),
                    "text": piece,
                }
            )

    return chunks, {
        "nonempty_page_count": nonempty_pages,
        "empty_page_count": sum(
            not bool(normalize_pdf_page_text(page["text"])) for page in pages
        ),
        "extracted_char_count": extracted_chars,
        "chunk_count": len(chunks),
    }
