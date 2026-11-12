import json

import numpy as np

from src.decision.requirement_extractor import EvidenceRequirementExtractor
from src.retrieval.canonical_json import sha256_file
from src.retrieval.financial_statement_ranker import FinancialStatementRanker
from src.retrieval.frozen_dense import FrozenDenseRetriever
from src.retrieval.pdf_page_cache import FrozenPdfPages


class QueryEmbedder:
    def embed_query(self, query):
        return [1.0, 0.0]


def test_scoped_statement_ranker_promotes_only_matching_period_and_metric(tmp_path):
    document = "AAPL_2024Q3_10Q"
    statement = """Condensed Consolidated Statements of Income
Three Months Ended September 30, Nine Months Ended September 30,
(USD in millions) 2024 2023 2024 2023
Net sales $ 105 $ 98 $ 305 $ 291
"""
    path = tmp_path / "pages.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in (
        {"doc_name": document, "page_number": 0, "text": "Quarterly highlights"},
        {"doc_name": document, "page_number": 1, "text": statement},
    )), encoding="utf-8")
    pages = FrozenPdfPages(path, expected_sha256=sha256_file(path))
    chunks = [{"chunk_id": str(page), "doc_name": document, "document_id": document,
               "page_number": page, "reporting_periods": ["2024"], "doc_type": "10Q"} for page in range(2)]
    ranker = FinancialStatementRanker(pages, EvidenceRequirementExtractor())
    index = FrozenDenseRetriever(chunks, np.array([[1.0, 0.0], [0.8, 0.6]]), QueryEmbedder(),
                                 pdf_pages=pages, statement_ranker=ranker)
    question = "What was Apple's Q3 YTD FY2024 revenue?"
    selected, = index.retrieve(question, 1, document_ids=(document,))
    assert (selected["chunk_id"], selected["retrieval_method"], selected["score_kind"]) == ("1", "statement_slot_rank", "rank")
    assert index.retrieve(question, 1)[0]["chunk_id"] == "0"
    assert index.retrieve("What was Apple's FY2024 revenue?", 1, document_ids=(document,))[0]["chunk_id"] == "0"
    assert index.retrieve(question, 1, document_ids=("another_filing",)) == []
