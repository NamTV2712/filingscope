"""Run controlled retrieval presets through the migrated retrieval stack."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.retrieval.hybrid_retriever import HybridRetriever

RETRIEVAL_PRESETS = ("bm25", "dense", "hybrid", "hybrid_rerank")


class FinanceBenchRetrievalAdapter:
    def __init__(
        self,
        retriever: HybridRetriever,
        *,
        top_k: int = 10,
        candidate_pool: int = 50,
    ):
        if top_k < 1 or candidate_pool < top_k:
            raise ValueError("candidate_pool must be at least top_k, and top_k must be positive")
        self.retriever = retriever
        self.top_k = top_k
        self.candidate_pool = candidate_pool

    def retrieve(
        self,
        query: str,
        *,
        preset: str,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        if preset not in RETRIEVAL_PRESETS:
            raise ValueError(f"unsupported retrieval preset: {preset}")
        if not query.strip():
            return []

        if preset == "bm25":
            tokens = self.retriever.tokenize_query(query)
            scores = self.retriever.bm25_scores(tokens)
            ranked = sorted(
                zip(self.retriever._all_chunks, scores, strict=True),
                key=lambda item: item[1],
                reverse=True,
            )[: self.top_k]
            return [self._to_record(chunk, float(score), "bm25") for chunk, score in ranked]

        embedding = query_embedding or self.retriever.embed_query(query)
        if preset == "dense":
            results = self.retriever.store.search(
                query_vector=embedding,
                top_k=self.top_k,
            )
            return [
                self._to_record(result, float(result.get("score", 0.0)), "dense")
                for result in results
            ]

        results = self.retriever.retrieve_with_embedding(
            query=query,
            query_embedding=embedding,
            top_k=self.top_k,
            candidate_pool=self.candidate_pool,
            use_lexical_ladder=True,
            use_reranker=preset == "hybrid_rerank",
            use_structured_lookup=False,
        )
        return [
            self._to_record(
                {
                    "chunk_id": item.chunk_id,
                    "doc_name": item.doc_name,
                    "page_number": item.page_number,
                    "company": item.company,
                    "section": item.section,
                    "text": item.text,
                },
                item.score,
                item.score_kind,
            )
            for item in results
        ]

    @staticmethod
    def _to_record(
        chunk: Mapping[str, Any],
        score: float,
        score_kind: str,
    ) -> dict[str, Any]:
        return {
            "chunk_id": chunk.get("chunk_id"),
            "doc_name": chunk.get("doc_name"),
            "page_number": chunk.get("page_number"),
            "company": chunk.get("company"),
            "score": float(score),
            "score_kind": score_kind,
        }
