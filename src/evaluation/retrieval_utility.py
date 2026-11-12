"""Controlled retrieval adapters for the offline Q5 replay."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi

from src.ingestion.chunker import count_tokens
from src.retrieval.embedder import QUERY_PREFIX
from src.retrieval.financial_statement_ranker import FinancialStatementRanker
from src.retrieval.hybrid_retriever import _tokenize
from src.retrieval.parent_context import PageParent, expand_contexts, page_key
from src.retrieval.provenance_graph import FilingPassageGraph


POOL = 50
VARIANTS = (
    "dense", "dense20", "dense100", "issuer_filter", "year_filter", "form_filter", "section_filter",
    "company_rank", "period_rank", "query_shaping", "rrf", "dbsf", "route_rrf", "rrf_preserve_dense",
    "table_rank", "table_rank20", "table_rank100", "parent_selective",
    "graphrag_local", "hipporag_pagerank", "lightrag_dual_level",
)
_FUSIONS = {"rrf", "dbsf", "route_rrf", "rrf_preserve_dense"}
_TABLES = {"table_rank", "table_rank20", "table_rank100"}
_GRAPHS = {"graphrag_local", "hipporag_pagerank", "lightrag_dual_level"}
_SHAPING_TERMS = {
    "revenue": "total revenues net sales", "total_assets": "total assets consolidated balance sheets",
    "operating_income": "income from operations operating income", "net_income": "net earnings net income",
    "cash_and_equivalents": "cash and cash equivalents consolidated balance sheets",
    "operating_cash_flow": "net cash provided by operating activities consolidated statements of cash flows",
}


@dataclass(frozen=True)
class Ranking:
    pool: tuple[int, ...]
    order: tuple[int, ...]
    scores: dict[int, float]
    replay_rank_ms: float | None = None
    embedding_input_tokens: int = 0


def _top(scores: np.ndarray, limit: int, *, positive: bool = False) -> tuple[int, ...]:
    return tuple(int(index) for index in np.argsort(-scores, kind="stable")[:limit]
                 if np.isfinite(scores[index]) and (not positive or scores[index] > 0))


def fuse(method: str, channels: tuple[tuple[int, ...], ...], values: tuple[np.ndarray, ...], weights: tuple[float, ...]):
    scores: dict[int, float] = defaultdict(float)
    for channel, raw, weight in zip(channels, values, weights, strict=True):
        if not channel:
            continue
        if method == "dbsf":
            selected = raw[list(channel)].astype(np.float64)
            deviation = np.std(selected, ddof=1) if len(channel) > 1 else 0.0
            contributions = 0.5 + (selected - selected.mean()) / (6 * deviation) if deviation else np.full(len(channel), 0.5)
        else:
            contributions = [1 / (60 + rank) for rank in range(1, len(channel) + 1)]
        for item, value in zip(channel, contributions, strict=True):
            scores[item] += weight * float(value)
    return dict(scores)


class UtilityIndex:
    def __init__(self, index, extractor, variants=VARIANTS):
        self.index = index
        self.chunks = index.chunks
        self.extractor = extractor
        self.graph = FilingPassageGraph(self.chunks)
        self.bm25 = BM25Okapi([_tokenize(row["text"]) for row in self.chunks]) if _FUSIONS.intersection(variants) else None
        self.company = np.array([unit.company for unit in self.graph.units], dtype=object)
        self.form = np.array([unit.form for unit in self.graph.units], dtype=object)
        self.years = tuple(unit.years for unit in self.graph.units)
        self.sections = tuple(unit.disclosures for unit in self.graph.units)
        self.parent_ids = defaultdict(list)
        self.deep_rankings: dict[str, dict[tuple[str, tuple[str, ...]], Ranking]] = {}
        for row in self.chunks:
            self.parent_ids[page_key(row)].append(row["chunk_id"])
        self.statement_ranker = FinancialStatementRanker(index.pdf_pages, extractor)

    def _dense(self, query: str, document_ids: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
        with self.index.model_lock:
            vector = np.asarray(self.index.embedder.embed_query(query), dtype=np.float32)
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm == 0:
            raise ValueError("Invalid query embedding")
        eligible = np.isin(self.index.document_ids, document_ids) if document_ids else np.ones(len(self.chunks), dtype=bool)
        return np.where(eligible, self.index.vectors @ (vector / norm), -np.inf), eligible

    @lru_cache(maxsize=256)
    def _embedding_tokens(self, query: str) -> int:
        model = self.index.embedder.model
        return len(model.tokenizer(QUERY_PREFIX + query, truncation=True, max_length=model.max_seq_length)["input_ids"])

    @lru_cache(maxsize=128)
    def _parent(self, key: tuple[str, int]) -> PageParent | None:
        text = self.index.get_source_page(*key)
        if text is None:
            return None
        return PageParent(*key, text, tuple(self.parent_ids[key]), count_tokens(text))

    def rank(self, query: str, name: str, document_ids: tuple[str, ...] = ()) -> Ranking:
        if name in self.deep_rankings:
            return self.deep_rankings[name][query, document_ids]
        size = 20 if name.endswith("20") else 100 if name.endswith("100") else POOL
        if name == "query_shaping":
            requirements = self.extractor.extract(query)
            terms = (_SHAPING_TERMS[metric.metric_id] for metric in requirements.metrics if metric.metric_id in _SHAPING_TERMS)
            query = " ".join((query, *terms)).strip()
        dense, eligible = self._dense(query, document_ids)
        input_tokens = self._embedding_tokens(query)
        pool = _top(dense, size)
        scores = {item: float(dense[item]) for item in pool}
        if name in {"dense", "dense20", "dense100", "parent_selective", "query_shaping"} or not pool:
            return Ranking(pool, pool, scores, embedding_input_tokens=input_tokens)

        cues = self.graph.cues(query)
        if name.endswith("_filter"):
            if name == "issuer_filter" and cues.companies:
                eligible &= np.isin(self.company, tuple(cues.companies))
            elif name == "year_filter" and cues.years:
                eligible &= np.fromiter((bool(cues.years.intersection(years)) for years in self.years), dtype=bool)
            elif name == "form_filter" and cues.forms:
                eligible &= np.isin(self.form, tuple(cues.forms))
            elif name == "section_filter" and cues.disclosures:
                eligible &= np.fromiter((bool(cues.disclosures.intersection(sections)) for sections in self.sections), dtype=bool)
            pool = _top(np.where(eligible, dense, -np.inf), size)
            return Ranking(pool, pool, {item: float(dense[item]) for item in pool}, embedding_input_tokens=input_tokens)
        if name in _FUSIONS:
            sparse = np.where(eligible, self.bm25.get_scores(_tokenize(query)), -np.inf)
            sparse_pool = _top(sparse, size, positive=True)
            weights = (1.0, 1.0)
            if name == "route_rrf":
                weights = (1.0, 1.5) if cues.disclosures or cues.forms else (1.5, 1.0)
            scores = fuse(name, (pool, sparse_pool), (dense, sparse), weights)
            order = tuple(sorted(scores, key=lambda item: (-scores[item], item)))
            if name == "rrf_preserve_dense":
                order = tuple(dict.fromkeys((*pool[:3], *order)))
            return Ranking(tuple(dict.fromkeys((*pool, *sparse_pool))), order, scores, embedding_input_tokens=input_tokens)
        if name in _TABLES:
            wanted = self.statement_ranker.requirements(query)
            order = tuple(sorted(pool, key=lambda item: -self.statement_ranker.priority(self.chunks[item], wanted)))
        elif name in _GRAPHS:
            ranker = {"graphrag_local": self.graph.local_search, "hipporag_pagerank": self.graph.personalized_pagerank,
                      "lightrag_dual_level": self.graph.dual_level}[name]
            scores = ranker(cues, pool)
            order = tuple(sorted(scores, key=lambda item: (-scores[item], item)))
        elif name == "company_rank":
            order = tuple(sorted(pool, key=lambda item: (self.company[item] not in cues.companies, -dense[item], item)))
        elif name == "period_rank":
            order = tuple(sorted(pool, key=lambda item: (not cues.years.intersection(self.years[item]), -dense[item], item)))
        else:
            raise ValueError(f"Unknown retrieval variant {name}")
        return Ranking(pool, order, scores, embedding_input_tokens=input_tokens)

    def present(self, name: str, ranking: Ranking, top_k: int) -> list[dict[str, Any]]:
        ranked = [{**self.chunks[item], "score": float(len(ranking.order) - position), "score_kind": "rank"}
                  for position, item in enumerate(ranking.order)]
        if name in {"dense", "dense20", "dense100", "query_shaping", "issuer_filter", "year_filter", "form_filter", "section_filter"}:
            return [{**row, "score": ranking.scores[item], "score_kind": "dense"}
                    for row, item in zip(ranked[:top_k], ranking.order[:top_k], strict=True)]
        if name != "parent_selective":
            return ranked[:top_k]
        parents = {key: parent for row in ranked[:top_k] if (parent := self._parent(key := page_key(row))) is not None}
        contexts = expand_contexts(ranked, parents, mode="selective", max_contexts=top_k)
        source_by_id = {row["chunk_id"]: row for row in ranked[:top_k]}
        selected = []
        for context in contexts:
            ids = set(context.chunk_ids)
            source = next(row for key, row in source_by_id.items() if key in ids)
            selected.append({**source, "text": context.text, "token_count": context.token_count,
                             "context_chunk_ids": context.chunk_ids})
        return selected
