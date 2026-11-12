"""Structure aware PDF chunking with the FinanceBench page metadata contract."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from configs.financebench import PDF_CHUNK_OVERLAP, PDF_CHUNK_SIZE
from src.ingestion.chunker import count_tokens
from src.ingestion.pdf_ingestion import chunk_pdf_pages


def column_headers(cells: list[dict[str, Any]], row: int, column: int) -> tuple[str, ...]:
    """Find the table headers spanning a cell's physical column."""
    spanning = sorted(
        (cell for cell in cells
         if cell["column_header"] and cell["row_end"] <= row
         and cell["column_start"] <= column < cell["column_end"] and cell["text"].strip()),
        key=lambda cell: (cell["row_start"], cell["column_start"]),
    )
    return tuple(dict.fromkeys(" ".join(cell["text"].split()) for cell in spanning))


def _table_text(block: dict[str, Any]) -> str:
    cells = block["cells"]
    lines = []
    for row in range(block["rows"]):
        row_cells = sorted(
            (cell for cell in cells if cell["row_start"] == row and not cell["column_header"]),
            key=lambda cell: cell["column_start"],
        )
        parts = []
        for cell in row_cells:
            text = " ".join(cell["text"].split())
            if not text:
                continue
            headers = column_headers(cells, row, cell["column_start"])
            if headers and not cell["row_header"]:
                text = f"{' / '.join(headers)}: {text}"
            parts.append(text)
        if parts:
            lines.append(" | ".join(parts))
    return "\n".join(lines) or block["text"]


def _sections(page: dict[str, Any]) -> Iterator[tuple[str, str, str | None]]:
    heading = ""
    parts: list[str] = []
    pending_heading = False
    for block in page["blocks"]:
        block_heading = block["heading"]
        if block["kind"] == "table" or block_heading != heading:
            if parts:
                yield heading, "\n\n".join(parts), None
                parts = []
            elif pending_heading and block_heading != heading:
                yield "", heading, None
            heading = block_heading
        if block["kind"] == "table":
            yield heading, _table_text(block), block["table_id"]
            pending_heading = False
        elif block["text"] != heading:
            parts.append(block["text"])
            pending_heading = False
        else:
            pending_heading = True
    if parts:
        yield heading, "\n\n".join(parts), None
    elif pending_heading:
        yield "", heading, None


def chunk_docling_pages(
    pages: list[dict[str, Any]],
    *,
    document_metadata: Mapping[str, Any],
    chunk_size: int = PDF_CHUNK_SIZE,
    overlap: int = PDF_CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for page in pages:
        page_index = page["page_number"]
        for section_index, (heading, text, table_id) in enumerate(_sections(page)):
            heading = heading[:200].strip()
            heading_budget = count_tokens(heading + "\n\n") if heading else 0
            if heading_budget >= chunk_size:
                heading, heading_budget = "", 0
            body_budget = max(1, chunk_size - heading_budget)
            pieces, _ = chunk_pdf_pages(
                [{"page_number": page_index, "text": text}],
                document_metadata=document_metadata,
                chunk_size=body_budget, overlap=min(overlap, body_budget - 1),
            )
            for piece in pieces:
                if heading:
                    piece["text"] = f"{heading}\n\n{piece['text']}"
                    piece["token_count"] = count_tokens(piece["text"])
                piece["chunk_id"] += f"_s{section_index:03d}"
                piece["section"] = "financial_table" if table_id else "section"
                if table_id:
                    piece["table_id"] = f"{piece['document_id']}:{table_id}"
                chunks.append(piece)
    return chunks
