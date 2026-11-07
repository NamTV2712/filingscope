from pathlib import Path

import src.ingestion.pdf_ingestion as pdf_module
from src.ingestion.pdf_ingestion import chunk_pdf_pages, extract_pdf_pages
from src.retrieval.retriever import RetrievedChunk


class _FakePage:
    def __init__(self, text: str | None):
        self.text = text

    def extract_text(
        self,
        extraction_mode: str,
        layout_mode_space_vertically: bool,
    ):
        assert extraction_mode == "layout"
        assert layout_mode_space_vertically is False
        return self.text


class _FakeReader:
    def __init__(self, _path: str, strict: bool):
        assert strict is False
        self.pages = [_FakePage("Revenue\nwas $100 million."), _FakePage(None)]


def test_pdf_page_extraction_preserves_zero_based_pages_and_empty_pages(monkeypatch) -> None:
    monkeypatch.setattr(pdf_module, "PdfReader", _FakeReader)

    pages = extract_pdf_pages(Path("synthetic.pdf"))

    assert pages == [
        {"page_number": 0, "text": "Revenue\nwas $100 million."},
        {"page_number": 1, "text": ""},
    ]


def test_pdf_chunks_keep_source_page_citation_and_do_not_add_labels() -> None:
    chunks, stats = chunk_pdf_pages(
        [
            {"page_number": 0, "text": "Revenue was $100 million."},
            {"page_number": 1, "text": ""},
        ],
        document_metadata={
            "doc_name": "SYNTHETIC_2024_10K",
            "company": "Synthetic Co",
            "reporting_periods": ["2024"],
        },
        chunk_size=40,
        overlap=5,
    )

    assert len(chunks) == 1
    assert chunks[0]["page_number"] == 0
    assert "answer" not in chunks[0]
    assert "evidence_text" not in chunks[0]
    assert stats["empty_page_count"] == 1
    result = RetrievedChunk.from_raw(chunks[0], score=0.25, score_kind="rrf")
    assert result.page_number == 0
    assert result.doc_name == "SYNTHETIC_2024_10K"
    assert result.citation == "SYNTHETIC_2024_10K, PDF page 1"
    assert result.score_kind == "rrf"


def test_pdf_chunking_collapses_pathological_layout_whitespace_before_embedding() -> None:
    chunks, _stats = chunk_pdf_pages(
        [{"page_number": 3, "text": "Revenue" + (" " * 40_000) + "$100 million."}],
        document_metadata={"doc_name": "SYNTHETIC_10K", "company": "Synthetic Co"},
        chunk_size=40,
        overlap=5,
    )

    assert len(chunks) == 1
    assert len(chunks[0]["text"]) < 100
    assert "Revenue" in chunks[0]["text"]
    assert "$100 million" in chunks[0]["text"]
