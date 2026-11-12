"""Optional Docling adapter for page text and native table provenance."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any


def _cell(item: Any) -> dict[str, Any]:
    return {
        "text": item.text,
        "row_start": item.start_row_offset_idx,
        "row_end": item.end_row_offset_idx,
        "column_start": item.start_col_offset_idx,
        "column_end": item.end_col_offset_idx,
        "column_header": item.column_header,
        "row_header": item.row_header,
    }


def _page_texts(item: Any, pages: set[int]) -> list[tuple[int, str]]:
    text = getattr(item, "text", "")
    if not isinstance(text, str) or not text.strip():
        return []
    provenances = list(item.prov)
    if len(pages) == 1:
        return [(next(iter(pages)), text.strip())]
    spans = []
    for part in provenances:
        start, end = part.charspan
        if not 0 <= start < end <= len(text):
            return []
        spans.append((part.page_no, start, end))
    spans.sort(key=lambda part: part[1])
    if any(left[2] > right[1] for left, right in zip(spans, spans[1:])):
        return []
    return [(number, text[start:end].strip()) for number, start, end in spans]


def materialize_document(document: Any, expected_pages: Iterable[int]) -> dict[str, Any]:
    """Convert Docling's one-based page references to source PDF indexes."""
    expected = set(expected_pages)
    if set(document.pages) != expected:
        raise ValueError("Docling page map differs from the requested source pages")
    page_blocks: dict[int, list[dict[str, Any]]] = {page: [] for page in sorted(expected)}
    omitted = 0
    heading = ""
    for item, _level in document.iterate_items():
        label = getattr(item.label, "value", item.label)
        pages = {prov.page_no for prov in getattr(item, "prov", ())}
        if not pages or not pages.issubset(expected):
            if label == "table" or getattr(item, "text", ""):
                omitted += 1
            continue
        if label == "table":
            if len(pages) != 1:
                omitted += 1
                continue
            number = next(iter(pages))
            page_blocks[number].append({
                "kind": "table",
                "heading": heading,
                "text": item.export_to_markdown(doc=document),
                "table_id": str(item.self_ref),
                "rows": item.data.num_rows,
                "columns": item.data.num_cols,
                "cells": [_cell(cell) for cell in item.data.table_cells],
            })
            continue
        values = _page_texts(item, pages)
        if not values and getattr(item, "text", ""):
            omitted += 1
        for number, text in values:
            if not text:
                continue
            if label in {"section_header", "title"}:
                heading = text
            page_blocks[number].append({"kind": label, "heading": heading, "text": text})
    return {
        "unassigned_blocks": omitted,
        "pages": [
            {
                "page_number": number - 1,
                "text": "\n\n".join(block["text"] for block in blocks),
                "blocks": blocks,
            }
            for number, blocks in page_blocks.items()
        ],
    }


class DoclingParser:
    def __init__(self, *, artifacts_path: Path, table_mode: str, threads: int = 4):
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode, TableStructureOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        options = PdfPipelineOptions(
            artifacts_path=artifacts_path,
            do_ocr=False,
            do_table_structure=True,
            table_structure_options=TableStructureOptions(mode=TableFormerMode(table_mode)),
            accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=threads),
        )
        self.converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
        )

    def extract(self, path: Path, *, page_range: tuple[int, int]) -> dict[str, Any]:
        result = self.converter.convert(path, page_range=page_range)
        if result.status.value != "success":
            raise ValueError(f"Docling conversion failed for {path.name}: {result.status}")
        return materialize_document(result.document, range(page_range[0], page_range[1] + 1))
