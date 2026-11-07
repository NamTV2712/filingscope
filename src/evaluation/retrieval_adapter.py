"""Run controlled retrieval presets through the migrated retrieval stack."""

from __future__ import annotations

import time
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
        timing_sink: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        if preset not in RETRIEVAL_PRESETS:
            raise ValueError(f"unsupported retrieval preset: {preset}")
        if not query.strip():
            return []
        total_started = time.perf_counter()

        if preset == "bm25":
            stage_started = time.perf_counter()
            tokens = self.retriever.tokenize_query(query)
            scores = self.retriever.bm25_scores(tokens)
            ranked = sorted(
                zip(self.retriever._all_chunks, scores, strict=True),
                key=lambda item: item[1],
                reverse=True,
            )[: self.top_k]
            records = [self._to_record(chunk, float(score), "bm25") for chunk, score in ranked]
            if timing_sink is not None:
                timing_sink["bm25_ms"] = max(0.0, (time.perf_counter() - stage_started) * 1000)
                timing_sink["total_ms"] = max(0.0, (time.perf_counter() - total_started) * 1000)
            return records

        embedding = query_embedding
        if embedding is None:
            embedding_started = time.perf_counter()
            embedding = self.retriever.embed_query(query)
            if timing_sink is not None:
                timing_sink["query_embedding_ms"] = max(0.0, (time.perf_counter() - embedding_started) * 1000)
        if preset == "dense":
            stage_started = time.perf_counter()
            results = self.retriever.store.search(
                query_vector=embedding,
                top_k=self.top_k,
            )
            records = [
                self._to_record(result, float(result.get("score", 0.0)), "dense")
                for result in results
            ]
            if timing_sink is not None:
                timing_sink["dense_search_ms"] = max(0.0, (time.perf_counter() - stage_started) * 1000)
                timing_sink["total_ms"] = max(0.0, (time.perf_counter() - total_started) * 1000)
            return records

        call_kwargs = dict(
            query=query,
            query_embedding=embedding,
            top_k=self.top_k,
            candidate_pool=self.candidate_pool,
            use_lexical_ladder=True,
            use_reranker=preset == "hybrid_rerank",
            use_structured_lookup=False,
        )
        if timing_sink is not None:
            call_kwargs["timing_sink"] = timing_sink
        results = self.retriever.retrieve_with_embedding(
            **call_kwargs,
        )
        records = [
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
        if timing_sink is not None:
            timing_sink["total_ms"] = max(0.0, (time.perf_counter() - total_started) * 1000)
        return records

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
