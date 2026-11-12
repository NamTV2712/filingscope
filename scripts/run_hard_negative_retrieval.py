"""Replay financial hard negatives against the full, frozen P1 passage corpus."""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi

from configs.financebench import P1_CORPUS_FINGERPRINT, P1_EMBEDDING_REVISION, P1_INDEX_ID, P1_RUN as DEFAULT_RUN
from configs.hard_negatives import CASES, M2_SEED_CASES
from scripts.run_retrieval_diagnostics import _nearest_rank, _write_json_atomic
from src.decision.company_catalog import CompanyCatalog
from src.evaluation.benchmark_io import peak_memory_bytes as _peak_memory_bytes
from src.evaluation.hard_negative_retrieval import resolve_passages, score_case, summarize
from src.evaluation.retrieval_diagnostics import metadata_filters_from_question
from src.retrieval.frozen_artifacts import load_frozen_corpus as _load_corpus, load_frozen_vectors as _load_vectors
from src.retrieval.hybrid_retriever import _tokenize


SPLITS = ("development", "validation", "held_out")
TOP_K = 50
RANDOM_SEED = 20261112


class _QueryFilters:
    """Construct eligibility exclusively from the question and corpus metadata."""

    def __init__(self, chunks: list[dict[str, Any]]):
        self.catalog = CompanyCatalog.from_document_rows(chunks)
        self.companies = defaultdict(set)
        for chunk in chunks:
            company = chunk["company"]
            entity = self.catalog.metadata_entity_id(None, company, chunk["doc_name"], chunk["document_id"])
            if entity:
                self.companies[entity].add(company)
        self.values = {
            "company": [(chunk["company"],) for chunk in chunks],
            "reporting_periods": [tuple(chunk["reporting_periods"]) for chunk in chunks],
            "doc_type": [(chunk["doc_type"],) for chunk in chunks],
        }
        self.periods = {period for row in self.values["reporting_periods"] for period in row}
        self.forms = {form for row in self.values["doc_type"] for form in row}

    def mask(self, question: str) -> tuple[dict[str, tuple[str, ...]], np.ndarray]:
        filters = metadata_filters_from_question(
            question, company_catalog=self.catalog, company_values_by_entity=self.companies,
            available_periods=self.periods, available_doc_types=self.forms,
        )
        mask = np.ones(len(self.values["company"]), dtype=bool)
        for field, values in filters.items():
            allowed = set(values)
            mask &= np.fromiter((not allowed.isdisjoint(row) for row in self.values[field]), dtype=bool, count=len(mask))
        return filters, mask


def _rank(scores: np.ndarray, *, positive_only: bool = False) -> list[int]:
    ranked = np.argsort(-scores, kind="stable")[:TOP_K]
    return [int(item) for item in ranked if np.isfinite(scores[item]) and (not positive_only or scores[item] > 0)]


def _cohort_report(chunks: list[dict[str, Any]], passages: dict) -> dict[str, Any]:
    return {
        "case_count": len(CASES),
        "case_counts_by_split": dict(Counter(case.split for case in CASES)),
        "case_counts_by_type": dict(Counter(kind for case in CASES for kind in {item.kind.value for item in case.negatives})),
        "positive_judgments": sum(len(case.evidence) for case in CASES),
        "negative_judgments_by_type": dict(Counter(item.kind.value for case in CASES for item in case.negatives)),
        "judged_documents": len({chunks[index]["doc_name"] for index in passages.values()}),
        "candidate_corpus_chunks": len(chunks),
        "candidate_corpus_documents": len({row["doc_name"] for row in chunks}),
        "m2_seed_cases": M2_SEED_CASES,
        "passage_provenance": {
            row["chunk_id"]: {
                key: row.get(key) for key in ("doc_name", "page_number", "chunk_index", "company", "source_url", "source_repository_url")
            }
            for row in (chunks[index] for index in sorted(set(passages.values())))
        },
        "cases": [
            {
                "case_id": case.case_id, "split": case.split, "question": case.question,
                "gold": [chunks[passages[item]]["chunk_id"] for item in case.evidence],
                "hard_negatives": {chunks[passages[item.passage]]["chunk_id"]: item.kind.value for item in case.negatives},
            }
            for case in CASES
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p1-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--labels-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.threads <= 16:
        parser.error("threads must be between 1 and 16")

    chunks = _load_corpus(args.p1_run)
    passages = resolve_passages(CASES, chunks)
    report: dict[str, Any] = {
        "benchmark": "filingscope-financial-hard-negatives-v1",
        "p1_index_id": P1_INDEX_ID, "corpus_fingerprint": P1_CORPUS_FINGERPRINT,
        "cohort": _cohort_report(chunks, passages), "provider_calls": 0,
    }
    if args.labels_only:
        _write_json_atomic(args.output, report)
        return

    import torch

    from src.retrieval.embedder import Embedder

    torch.set_num_threads(args.threads)
    started = time.perf_counter()
    vectors = _load_vectors(args.p1_run, chunks)
    bm25 = BM25Okapi([_tokenize(chunk["text"]) for chunk in chunks])
    query_filters = _QueryFilters(chunks)
    embedder = Embedder(device="cpu", revision=P1_EMBEDDING_REVISION)
    setup_seconds = time.perf_counter() - started
    variants = {name: [] for name in ("dense", "bm25", "dense_query_metadata")}
    for case in CASES:
        started = time.perf_counter()
        embedding = np.asarray(embedder.embed_query(case.question), dtype=np.float32)
        dense_scores = vectors @ (embedding / np.linalg.norm(embedding))
        dense_ranking = _rank(dense_scores)
        dense_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        bm25_scores = bm25.get_scores(_tokenize(case.question))
        bm25_ranking = _rank(bm25_scores, positive_only=True)
        bm25_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        filters, mask = query_filters.mask(case.question)
        filtered_scores = np.where(mask, dense_scores, -np.inf)
        filtered_ranking = _rank(filtered_scores)
        filtered_ms = dense_ms + (time.perf_counter() - started) * 1000

        # Sample the same number of other-company passages as the audited hard
        # negatives. Selection happens after the three full-corpus scores.
        company = chunks[passages[case.evidence[0]]]["company"]
        audited = {passages[item.passage] for item in case.negatives}
        pool = [position for position, chunk in enumerate(chunks) if chunk["company"] != company and position not in audited]
        random_ids = random.Random(f"{RANDOM_SEED}:{case.case_id}").sample(pool, len(case.negatives))
        for name, ranking, scores, latency_ms in (
            ("dense", dense_ranking, dense_scores, dense_ms),
            ("bm25", bm25_ranking, bm25_scores, bm25_ms),
            ("dense_query_metadata", filtered_ranking, filtered_scores, filtered_ms),
        ):
            row = score_case(case, passages, ranking, scores, random_negatives=random_ids)
            row.update(
                latency_ms=round(latency_ms, 3), ranking=[chunks[index]["chunk_id"] for index in ranking],
                random_controls=[chunks[index]["chunk_id"] for index in random_ids],
            )
            if name == "dense_query_metadata":
                row.update(filters=filters, eligible_chunks=int(mask.sum()),
                           filtered_gold_chunks=sum(not mask[passages[item]] for item in case.evidence))
            variants[name].append(row)

    report.update(
        embedding_revision=P1_EMBEDDING_REVISION, threads=args.threads, random_seed=RANDOM_SEED,
        setup_seconds=round(setup_seconds, 3), peak_memory_bytes=_peak_memory_bytes(),
        variants={
            name: {
                "overall": summarize(rows),
                "by_split": {split: summarize([row for row in rows if row["split"] == split]) for split in SPLITS},
                "latency_ms": {"p50": _nearest_rank([row["latency_ms"] for row in rows], .5),
                               "p95": _nearest_rank([row["latency_ms"] for row in rows], .95)},
                "per_case": rows,
            }
            for name, rows in variants.items()
        },
    )
    _write_json_atomic(args.output, report)
    print(args.output)


if __name__ == "__main__":
    main()
