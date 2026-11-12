"""In-process dense retrieval over a validated, normalized corpus snapshot."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from src.ingestion.period_identity import PeriodKind
from src.retrieval.financial_statement_ranker import STATEMENT_CANDIDATE_POOL, FinancialStatementRanker
from src.retrieval.pdf_page_cache import FrozenPdfPages


class FrozenDenseRetriever:
    supports_concurrent_retrieval = True
    supports_document_scope = True

    def __init__(
        self, chunks: list[dict[str, Any]], vectors: np.ndarray, embedder: Any, *,
        pdf_pages: FrozenPdfPages | None = None, statement_ranker: FinancialStatementRanker | None = None,
    ):
        self.chunks = chunks
        self.vectors = vectors
        self.embedder = embedder
        self.document_ids = np.array([item["document_id"] for item in chunks])
        self.model_lock = threading.Lock()
        self.pdf_pages = pdf_pages
        self.statement_ranker = statement_ranker
        statement_keys = {
            (doc, page) for doc, pages in pdf_pages.statements.items() for page, _ in pages
        } if pdf_pages else set()
        self._statement_chunks = {}
        for chunk in chunks:
            key = chunk["document_id"], chunk.get("page_number")
            if key in statement_keys:
                self._statement_chunks.setdefault(key, chunk)
        self.statement_document_ids = frozenset(doc for doc, _ in self._statement_chunks)

    def get_source_page(self, document: str, page_number: int) -> str | None:
        return self.pdf_pages.get(document, page_number) if self.pdf_pages is not None else None

    def retrieve_statement_candidates(
        self, document_ids: tuple[str, ...], kind: PeriodKind, *, top_k: int,
    ) -> list[dict[str, Any]]:
        if self.pdf_pages is None or top_k <= 0:
            return []
        matches = []
        for document in document_ids:
            for page, page_kind in self.pdf_pages.statements.get(document, ()):
                chunk = self._statement_chunks.get((document, page))
                if page_kind == kind and chunk is not None:
                    matches.append({**chunk, "retrieval_method": "physical_statement_page"})
                    if len(matches) == top_k:
                        return matches
        return matches

    def retrieve(
        self, query: str, top_k: int = 10, *,
        document_ids: tuple[str, ...] = (), eligible: np.ndarray | None = None,
    ) -> list[dict[str, Any]]:
        if top_k <= 0:
            return []
        with self.model_lock:
            query_vector = np.asarray(self.embedder.embed_query(query), dtype=np.float32)
        norm = np.linalg.norm(query_vector)
        if not np.isfinite(norm) or norm == 0:
            raise ValueError("The query embedding must be finite and nonzero")
        scores = self.vectors @ (query_vector / norm)
        if eligible is not None:
            scores = np.where(eligible, scores, -np.inf)
        if document_ids:
            scores = np.where(np.isin(self.document_ids, document_ids), scores, -np.inf)
        ranker = self.statement_ranker if document_ids else None
        wanted = ranker.requirements(query) if ranker is not None else frozenset()
        pool_size = max(top_k, STATEMENT_CANDIDATE_POOL) if wanted else top_k
        order = [int(position) for position in np.argsort(-scores, kind="stable")[:pool_size]
                 if np.isfinite(scores[position])]
        if ranker is not None and wanted:
            ranked = sorted(order, key=lambda position: -ranker.priority(self.chunks[position], wanted))
            if ranked[:top_k] != order[:top_k]:
                return [
                    {**self.chunks[position], "score": float(len(ranked) - rank), "score_kind": "rank",
                     "dense_score": float(scores[position]), "retrieval_method": "statement_slot_rank"}
                    for rank, position in enumerate(ranked[:top_k])
                ]
        return [
            {**self.chunks[position], "score": float(scores[position]), "score_kind": "dense"}
            for position in order[:top_k]
        ]
