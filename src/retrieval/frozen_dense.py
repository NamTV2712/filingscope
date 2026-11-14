"""In-process dense retrieval over a validated, normalized corpus snapshot."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from src.decision.filing_disclosures import (
    BUSINESS_DISCLOSURE_METRICS, filing_industry_relations, filing_segment_disclosures,
    is_segment_list_question, segment_kind_matches,
)
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
        scope = eligible
        if document_ids:
            document_scope = np.isin(self.document_ids, document_ids)
            scope = document_scope if scope is None else document_scope & scope
        query_vector = query_vector / norm
        if scope is None or np.count_nonzero(scope) * 2 >= len(self.vectors):
            scores = self.vectors @ query_vector
            if scope is not None:
                scores = np.where(scope, scores, -np.inf)
            positions = None
        else:
            positions = np.flatnonzero(scope)
            scores = self.vectors[positions] @ query_vector
        ranker = self.statement_ranker if document_ids else None
        wanted = ranker.requirements(query) if ranker is not None else frozenset()
        topics = {metric.metric_id for metric in ranker.extractor.extract(query).metrics} if ranker is not None else set()
        industry_lookup = "industry" in topics
        segment_lookup = len(topics) == 1 and topics <= BUSINESS_DISCLOSURE_METRICS and is_segment_list_question(query)
        pool_size = max(top_k, STATEMENT_CANDIDATE_POOL) if wanted or industry_lookup or segment_lookup else top_k
        local_order = [int(position) for position in np.argsort(-scores, kind="stable")[:pool_size]
                       if np.isfinite(scores[position])]
        order = local_order if positions is None else [int(positions[position]) for position in local_order]
        dense_scores = dict(zip(order, scores[local_order], strict=True))
        if ranker is not None and wanted:
            ranked = sorted(order, key=lambda position: -ranker.priority(self.chunks[position], wanted))
            if ranked[:top_k] != order[:top_k]:
                return [
                    {**self.chunks[position], "score": float(len(ranked) - rank), "score_kind": "rank",
                     "dense_score": float(dense_scores[position]), "retrieval_method": "statement_slot_rank"}
                    for rank, position in enumerate(ranked[:top_k])
                ]
        if ranker is not None and (industry_lookup or segment_lookup):
            def explicit_disclosure(position: int) -> bool:
                chunk = self.chunks[position]
                entity = ranker.extractor.catalog.metadata_entity_id(
                    chunk.get("ticker"), chunk.get("company"), chunk.get("doc_name"), chunk.get("document_id"),
                )
                aliases = ranker.extractor.catalog.aliases_for(entity) if entity else ()
                if not aliases:
                    return False
                if segment_lookup:
                    return any(segment_kind_matches(query, kind, len(names))
                               for kind, names in filing_segment_disclosures(chunk["text"], aliases))
                return bool(filing_industry_relations(chunk["text"], aliases))

            order = sorted(order, key=lambda position: not explicit_disclosure(position))
        return [
            {**self.chunks[position], "score": float(dense_scores[position]), "score_kind": "dense"}
            for position in order[:top_k]
        ]
