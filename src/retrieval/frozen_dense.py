"""In-process dense retrieval over a validated, normalized corpus snapshot."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from src.retrieval.pdf_page_cache import FrozenPdfPages


class FrozenDenseRetriever:
    supports_concurrent_retrieval = True
    supports_document_scope = True

    def __init__(
        self, chunks: list[dict[str, Any]], vectors: np.ndarray, embedder: Any, *,
        pdf_pages: FrozenPdfPages | None = None,
    ):
        self.chunks = chunks
        self.vectors = vectors
        self.embedder = embedder
        self.document_ids = np.array([item["document_id"] for item in chunks])
        self.model_lock = threading.Lock()
        self.pdf_pages = pdf_pages

    def get_source_page(self, document: str, page_number: int) -> str | None:
        return self.pdf_pages.get(document, page_number) if self.pdf_pages is not None else None

    def retrieve(
        self, query: str, top_k: int = 10, *,
        document_ids: tuple[str, ...] = (), eligible: np.ndarray | None = None,
    ) -> list[dict[str, Any]]:
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
        order = np.argsort(-scores, kind="stable")[:top_k]
        return [
            {**self.chunks[position], "score": float(scores[position]), "score_kind": "dense"}
            for position in order if np.isfinite(scores[position])
        ]
