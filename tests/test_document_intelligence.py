"""Offline checks for Docling provenance and table-aware chunks."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from scripts.evaluate_document_intelligence import _label_regex, _native_row, _ordered, _text_row
from src.ingestion.docling_pdf import materialize_document
from src.ingestion.structured_pdf_chunks import chunk_docling_pages


def _prov(page, span=(0, 0)):
    return SimpleNamespace(page_no=page, charspan=span)


def _text(label, value, *provenance):
    return SimpleNamespace(label=label, text=value, prov=provenance)


def _cell(text, row, col, *, col_end=None, header=False, row_header=False):
    return SimpleNamespace(
        text=text, start_row_offset_idx=row, end_row_offset_idx=row + 1,
        start_col_offset_idx=col, end_col_offset_idx=col + 1 if col_end is None else col_end,
        column_header=header, row_header=row_header,
    )


def _document(*items):
    return SimpleNamespace(pages={5: None, 6: None}, iterate_items=lambda: [(item, 0) for item in items])


def _table(*provenance):
    return SimpleNamespace(
        label="table", self_ref="#/tables/0", prov=provenance,
        data=SimpleNamespace(num_rows=3, num_cols=3, table_cells=[
            _cell("Three months ended", 0, 1, col_end=3, header=True),
            _cell("2024", 1, 1, header=True),
            _cell("2023", 1, 2, header=True),
            _cell("Net income", 2, 0, row_header=True),
            _cell("$ 42", 2, 1),
            _cell("$ (10)", 2, 2),
        ]),
        export_to_markdown=lambda **_: "| Net income | $ 42 | (10) |",
    )


def test_docling_page_map_retains_physical_indexes_and_refuses_unaligned_table():
    doc = _document(
        _text("section_header", "Results", _prov(5)),
        _text("text", "First second", _prov(5, (0, 5)), _prov(6, (6, 12))),
        _table(_prov(5), _prov(6)),
    )
    result = materialize_document(doc, (5, 6))
    assert [page["page_number"] for page in result["pages"]] == [4, 5]
    assert [page["text"] for page in result["pages"]] == ["Results\n\nFirst", "second"]
    assert result["unassigned_blocks"] == 1
    with pytest.raises(ValueError, match="page map"):
        materialize_document(doc, (1, 2))


def test_structured_chunks_preserve_table_id_and_both_spanning_headers():
    result = materialize_document(
        _document(_text("section_header", "Results", _prov(5)), _table(_prov(5))),
        (5, 6),
    )
    chunks = chunk_docling_pages(
        result["pages"],
        document_metadata={"doc_name": "fixture", "company": "Example", "doc_link": "https://example.org/report"},
    )
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk["page_number"] == 4
    assert chunk["section"] == "financial_table"
    assert chunk["table_id"] == "fixture:#/tables/0"
    assert chunk["source_url"] == "https://example.org/report"
    assert "Three months ended / 2024: $ 42" in chunk["text"]
    assert "Three months ended / 2023: $ (10)" in chunk["text"]
    assert chunk["text"].startswith("Results")


def test_audit_distinguishes_amount_recovery_from_header_association():
    parse = materialize_document(_document(_table(_prov(5))), (5, 6))
    page = parse["pages"][0]
    pattern = _label_regex("Net income")
    values = (Decimal(42), Decimal(-10))
    assert _text_row(page["text"], pattern, values)
    assert _native_row(page, pattern, values, (
        ("Three months ended", "2024"), ("Six months ended", "2023"),
    )) == (True, True, 1)
    assert _ordered("A\nB. C", ("A", "B", "C"))
    assert not _ordered("C B A", ("A", "B", "C"))
