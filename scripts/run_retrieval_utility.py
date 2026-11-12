"""Measure Q5 candidate recall, ranking and grounded release under one corpus pin."""

from __future__ import annotations

import argparse
import math
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

import numpy as np

from configs.financebench import P1_EMBEDDING_REVISION, P1_INDEX_ID, P1_PAGE_CACHE, P1_RUN
from configs.hard_negatives import CASES as M12_CASES
from configs.multi_agent_ablation import CASES as M13_CASES
from configs.offline_guard import offline_socket_guard
from configs.retrieval_utility import CASES, ISSUERS
from configs.sec_snapshots import COMPANY_TICKERS, SEC_CUTOFF, SEC_ISSUERS
from configs.source_routing import CASES as DIRECT_CASES
from scripts.run_late_interaction_retrieval import DEFAULT_MODEL, _colbert, _cross_encoder
from scripts.run_multi_agent_ablation import CompanyFactsReplay, _ledger_key, _PolicyLayer, _RecordingRetriever, _specialist_observation
from src.agent.complexity_router import ComplexityRouter, CorpusMap
from src.agent.specialist_graph import SpecialistResearchGraph
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.hard_negative_retrieval import resolve_passages, score_case, summarize
from src.evaluation.multi_agent_ablation import evaluate_observation, paired_grounded_exact, summarize_ablation
from src.evaluation.retrieval_utility import VARIANTS, Ranking, UtilityIndex
from src.retrieval.canonical_json import sha256_file
from src.retrieval.frozen_artifacts import load_frozen_corpus, load_frozen_vectors
from src.retrieval.frozen_dense import FrozenDenseRetriever
from src.retrieval.pdf_page_cache import FrozenPdfPages


SEED = 20261112
NATURAL_VARIANTS = ("natural_dense", "natural_table_rank", "natural_table_rank100", "natural_runtime")


@dataclass(frozen=True)
class QueryRequest:
    case_id: str
    question: str
    scope: tuple[str, ...]


class ReplayRetriever(_RecordingRetriever):
    supports_concurrent_retrieval = False

    def __init__(self, utility, name):
        super().__init__(utility.index)
        self.utility, self.name = utility, name
        self.rankings = []

    def reset(self):
        super().reset()
        self.rankings.clear()

    def retrieve(self, query: str, top_k: int = 10, *, document_ids: tuple[str, ...] = ()) -> list[dict]:
        started = time.perf_counter()
        ranked = self.utility.rank(query, self.name, document_ids)
        chunks = self.utility.present(self.name, ranked, top_k)
        ids = tuple(row["chunk_id"] for row in chunks)
        self.calls.append((" ".join(query.casefold().split()), document_ids, ids))
        self.chunks.update((row["chunk_id"], row) for row in chunks)
        replay_ms = (time.perf_counter() - started) * 1000
        self.rankings.append({
            "query": query, "document_ids": document_ids, "top_k": top_k,
            "pool": ranked.pool, "rank_ms": ranked.replay_rank_ms if ranked.replay_rank_ms is not None else replay_ms,
            "replay_rank_overhead_ms": replay_ms if ranked.replay_rank_ms is not None else None,
            "embedding_input_tokens": ranked.embedding_input_tokens,
            "retrieved": ids,
        })
        return chunks


def _percentiles(values):
    ordered = sorted(values)
    return {f"p{percent}": round(ordered[math.ceil(len(ordered) * percent / 100) - 1], 3) if ordered else None
            for percent in (50, 95)}


def _source(chunk):
    return f"{chunk['doc_name']}#p{chunk['page_number']}"


def _expected_sources(case):
    return tuple(set(slot) for claim in case.claims for slot in claim.source_slots)


def _page_coverage(positions, chunks, expected):
    sources = {_source(chunks[position]) for position in positions}
    return sum(bool(sources.intersection(group)) for group in expected) / len(expected) if expected else None


def _m12_rows(utility, name, passages):
    rows = []
    for case in M12_CASES:
        started = time.perf_counter()
        rank = utility.rank(case.question, name)
        results = utility.present(name, rank, 10)
        elapsed = rank.replay_rank_ms if rank.replay_rank_ms is not None else (time.perf_counter() - started) * 1000
        values = np.full(len(utility.chunks), -np.inf)
        for index, item in enumerate(rank.order):
            values[item] = -index
        row = score_case(case, passages, rank.order, values)
        pool = set(rank.pool)
        gold = {passages[reference] for reference in case.evidence}
        covered = {identifier for result in results for identifier in result.get("context_chunk_ids", (result["chunk_id"],))}
        # Pair discrimination is restricted to pairs that actually enter the candidate pool.
        for kind, counts in row["pairs"].items():
            outside = sum(negative.kind.value == kind and passages[negative.passage] not in pool for negative in case.negatives)
            counts["wins"] -= outside * len(gold.intersection(pool))
            counts["filtered_positive_pairs"] += outside * len(gold.intersection(pool))
        row.update(
            candidate_recall=len(gold.intersection(pool)) / len(gold), pool_size=len(pool),
            context_complete=all(utility.chunks[item]["chunk_id"] in covered for item in gold),
            latency_ms=round(elapsed, 3), ranking=[utility.chunks[item]["chunk_id"] for item in rank.order],
            embedding_input_tokens=rank.embedding_input_tokens,
            candidate_ids=[utility.chunks[item]["chunk_id"] for item in rank.pool],
        )
        rows.append(row)
    return rows


def _page_rows(utility, name):
    rows = []
    for case in CASES:
        expected = _expected_sources(case)
        if not expected:
            continue
        started = time.perf_counter()
        rank = utility.rank(case.question, name)
        elapsed = rank.replay_rank_ms if rank.replay_rank_ms is not None else (time.perf_counter() - started) * 1000
        sources = [_source(utility.chunks[item]) for item in rank.order]
        unique = list(dict.fromkeys(sources))
        gold_sources = set().union(*expected)
        hits = [position for position, source in enumerate(unique[:10], start=1) if source in gold_sources]
        dcg = sum(1 / math.log2(position + 1) for position in hits if position <= 5)
        ideal = sum(1 / math.log2(position + 1) for position in range(1, min(len(gold_sources), 5) + 1))
        recall_5 = _page_coverage(rank.order[:5], utility.chunks, expected)
        recall_10 = _page_coverage(rank.order[:10], utility.chunks, expected)
        rows.append({
            "case_id": case.case_id, "split": case.split, "category": case.category,
            "candidate_recall": _page_coverage(rank.pool, utility.chunks, expected), "pool_size": len(rank.pool),
            "recall_at_5": recall_5, "recall_at_10": recall_10, "full_at_10": recall_10 == 1,
            "page_mrr_at_10": 1 / hits[0] if hits else 0, "page_ndcg_at_5": dcg / ideal,
            "latency_ms": round(elapsed, 3), "ranking": sources, "embedding_input_tokens": rank.embedding_input_tokens,
            "candidate_ids": [utility.chunks[item]["chunk_id"] for item in rank.pool],
        })
    return rows


def _run_graph(utility, name, router, *, cases=CASES, sec_client=None):
    natural = name.startswith("natural_")
    ranking = name.removeprefix("natural_")
    if name == "natural_runtime":
        index = utility.index
        retriever = _RecordingRetriever(FrozenDenseRetriever(
            index.chunks, index.vectors, index.embedder, pdf_pages=index.pdf_pages, statement_ranker=utility.statement_ranker,
        ))
    else:
        retriever = ReplayRetriever(utility, ranking)
    graph = SpecialistResearchGraph(router=router, retriever=retriever, retriever_concurrency_safe=False,
                                    sec_client=sec_client, ticker_by_company=COMPANY_TICKERS)
    layer = _PolicyLayer(router.extractor)
    rows = []
    for case in cases:
        retriever.reset()
        sec_before = sec_client.request_count if sec_client is not None else 0
        started = time.perf_counter()
        result = graph.run(case.question, request_id=f"q5-{name}-{case.case_id}", force_research=not natural)
        elapsed = (time.perf_counter() - started) * 1000
        if name in utility.deep_rankings and len(retriever.calls) != result.usage.retrieval_calls:
            raise ValueError(f"A learned reranker did not cover every attempted query for {case.case_id}")
        expected = _expected_sources(case)
        ranks = retriever.rankings if isinstance(retriever, ReplayRetriever) else []
        estimated = sum(call["rank_ms"] - call["replay_rank_overhead_ms"]
                        for call in ranks if call["replay_rank_overhead_ms"] is not None)
        sec_calls = sec_client.request_count - sec_before if sec_client is not None else 0
        scored = evaluate_observation(case, _specialist_observation(result, retriever, sec_calls, layer), latency_ms=elapsed + estimated)
        pool = set().union(*(call["pool"] for call in ranks))
        citations = {record.evidence_id: record for record in result.ledger_snapshot.evidence_records}
        scored.update(
            candidate_recall=_page_coverage(pool, utility.chunks, expected) if ranks else None,
            candidate_count=len(pool), rank_latencies_ms=[round(call["rank_ms"], 3) for call in ranks],
            final_missing=tuple(result.coverage.missing_requirement_ids) if result.coverage else (),
            final_conflicts=tuple(result.coverage.conflicted_requirement_ids) if result.coverage else (),
            queries=[{"query": call["query"], "scope": call["document_ids"], "retrieved": call["retrieved"],
                      "candidate_ids": [utility.chunks[item]["chunk_id"] for item in call["pool"]]} for call in ranks]
            if isinstance(retriever, ReplayRetriever) else
            [{"query": query, "scope": scope, "retrieved": ids} for query, scope, ids in retriever.calls],
            citation_sources=tuple(_ledger_key(citations[key]) for key in result.citation_evidence_ids),
            statement_calls=retriever.statement_calls, graph_replay_wall_ms=round(elapsed, 3),
            verifier_reasons=result.verification.reason_codes if result.verification else (),
            operation_gaps=result.coverage.operation_gaps if result.coverage else (),
            embedding_calls=len(retriever.calls), embedding_input_tokens=sum(call["embedding_input_tokens"] for call in ranks)
            if isinstance(retriever, ReplayRetriever) else None,
        )
        rows.append(scored)
    return rows


def _rank_summary(rows, *, m12):
    metrics = ("candidate_recall", "pool_size") if m12 else (
        "candidate_recall", "pool_size", "recall_at_5", "recall_at_10", "full_at_10", "page_mrr_at_10", "page_ndcg_at_5",
    )
    result = summarize(rows) if m12 else {"case_count": len(rows)}
    result.update({metric: round(mean(row[metric] for row in rows), 4) for metric in metrics})
    result["latency_ms"] = _percentiles([row["latency_ms"] for row in rows])
    result["embedding_calls"] = len(rows)
    result["embedding_input_tokens"] = sum(row["embedding_input_tokens"] for row in rows)
    if m12:
        result["context_complete_cases"] = sum(row["context_complete"] for row in rows)
    return result


def _graph_summary(rows):
    summary = summarize_ablation(rows)
    recalls = [row["candidate_recall"] for row in rows if row["candidate_recall"] is not None]
    summary["candidate_recall"] = round(mean(recalls), 4) if recalls else None
    summary["rank_latency_ms"] = _percentiles([value for row in rows for value in row["rank_latencies_ms"]])
    summary["unsupported_releases"] = sum(row["unsupported_released_claims"] > 0 for row in rows)
    summary["correct_abstentions"] = sum(not row["answered"] and not row["answerable"] for row in rows)
    summary["embedding_calls"] = sum(row["embedding_calls"] for row in rows)
    token_counts = [row["embedding_input_tokens"] for row in rows]
    summary["embedding_input_tokens"] = sum(token_counts) if all(count is not None for count in token_counts) else None
    return summary


def _groups(rows, key, aggregate):
    return {name: aggregate([row for row in rows if row[key] == name]) for name in sorted({row[key] for row in rows})}


def _deep_rankings(utility, backend, p1_run, vector_cache, threads, baseline):
    keys = {(case.question, ()) for case in M12_CASES}
    keys.update((case.question, ()) for case in CASES if case.claims)
    keys.update((call["query"], tuple(call["scope"])) for row in baseline for call in row["queries"])
    requests = tuple(QueryRequest(f"q5-{position:03d}", question, scope)
                     for position, (question, scope) in enumerate(sorted(keys)))
    pools, dense_ms, input_tokens = {}, {}, {}
    for request in requests:
        started = time.perf_counter()
        ranking = utility.rank(request.question, "dense20", request.scope)
        pools[request.case_id] = ranking.pool
        dense_ms[request.case_id] = (time.perf_counter() - started) * 1000
        input_tokens[request.case_id] = ranking.embedding_input_tokens
    nonempty = tuple(request for request in requests if pools[request.case_id])
    if backend == "colbert":
        results, metadata = _colbert(utility.chunks, pools, DEFAULT_MODEL, vector_cache, threads,
                                     cases=nonempty, measure_tokens=True)
    else:
        results, metadata = _cross_encoder(utility.chunks, pools, p1_run, threads, cases=nonempty, measure_tokens=True)
    for name, (by_query, model_ms) in results.items():
        rankings = {}
        for request in requests:
            scores = by_query.get(request.case_id, {})
            pool = pools[request.case_id]
            if scores.keys() != set(pool) or not all(np.isfinite(value) for value in scores.values()):
                raise ValueError(f"{name} changed the frozen candidate pool for {request.case_id}")
            order = tuple(sorted(scores, key=lambda item: (-scores[item], item)))
            rankings[request.question, request.scope] = Ranking(pool, order, scores,
                                                               dense_ms[request.case_id] + model_ms.get(request.case_id, 0),
                                                               input_tokens[request.case_id])
        utility.deep_rankings[name] = rankings
    return {**metadata, "request_count": len(requests), "pool_limit": 20,
            "latency_method": "measured warm rank plus graph replay overhead; no provider calls"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p1-run", type=Path, default=P1_RUN)
    parser.add_argument("--pages", type=Path, default=P1_PAGE_CACHE)
    parser.add_argument("--variants", nargs="+", choices=(*VARIANTS, *NATURAL_VARIANTS), default=(*VARIANTS, "natural_dense"))
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--deep-backend", choices=("colbert", "cross-encoder"))
    parser.add_argument("--colbert-cache", type=Path, default=Path("data/financebench/advanced_runs/q5-colbert20.npz"))
    parser.add_argument("--safety", action="store_true")
    parser.add_argument("--sec-dir", type=Path, default=Path("data/financebench/ablation_runs/m13-sec"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.threads <= 16 or "dense" not in args.variants or args.deep_backend and "dense20" not in args.variants:
        parser.error("Use 1–16 CPU threads, include Dense, and include Dense20 for a learned reranker")
    if args.safety and ("natural_dense" not in args.variants or not any(name in args.variants for name in NATURAL_VARIANTS[1:])):
        parser.error("Safety comparison requires natural Dense and a natural candidate")
    import torch
    from src.retrieval.embedder import Embedder

    torch.set_num_threads(args.threads)
    with offline_socket_guard():
        start = time.perf_counter()
        chunks = load_frozen_corpus(args.p1_run)
        vectors = load_frozen_vectors(args.p1_run, chunks)
        pages = FrozenPdfPages.from_run(args.pages, args.p1_run)
        artifact_seconds = time.perf_counter() - start
        start = time.perf_counter()
        embedder = Embedder(device="cpu", revision=P1_EMBEDDING_REVISION)
        model_seconds = time.perf_counter() - start
        start = time.perf_counter()
        index = FrozenDenseRetriever(chunks, vectors, embedder, pdf_pages=pages)
        router = ComplexityRouter(CorpusMap.from_chunks(chunks, index_generation_id=P1_INDEX_ID))
        utility = UtilityIndex(index, router.extractor, args.variants)
        sec = CompanyFactsReplay(args.sec_dir, SEC_ISSUERS, latest_filed=SEC_CUTOFF) if args.safety else None
        setup_seconds = time.perf_counter() - start
        references = resolve_passages(M12_CASES, chunks)
        page_sources = {_source(row) for row in chunks}
        if any(not slot.issubset(page_sources) for case in CASES for slot in _expected_sources(case)):
            raise ValueError("A Q5 labeled page does not exist in the pinned corpus")
        report = {"configuration": {
            "index_id": P1_INDEX_ID, "embedding_revision": P1_EMBEDDING_REVISION, "seed": SEED,
            "pages_sha256": sha256_file(args.pages), "m12_labels_sha256": sha256_file(Path("configs/hard_negatives.py")),
            "q5_labels_sha256": sha256_file(Path("configs/retrieval_utility.py")), "threads": args.threads,
            "pdf_only_controlled_graph": True, "providers": [],
        }, "resources": {"index_bytes_on_disk": sum((args.p1_run / file).stat().st_size for file in (
            "corpus_chunks.jsonl", "embedded_chunks.jsonl", "index_manifest.json", "embedding_manifest.json",
        )), "normalized_matrix_bytes": vectors.nbytes,
            "artifact_load_seconds": round(artifact_seconds, 3), "dense_model_setup_seconds": round(model_seconds, 3),
            "benchmark_adapter_setup_seconds": round(setup_seconds, 3),
        }, "variants": {}}
        natural_reference = ("natural_dense",) if any(name in args.variants for name in NATURAL_VARIANTS[1:]) else ()
        names = list(dict.fromkeys(("dense", *natural_reference, *args.variants)))
        for name in names:
            print(f"Q5 {name}", flush=True)
            m12 = _m12_rows(utility, name, references) if name not in NATURAL_VARIANTS else []
            pages = _page_rows(utility, name) if name not in NATURAL_VARIANTS else []
            e2e = _run_graph(utility, name, router)
            variant = {"e2e": _graph_summary(e2e), "e2e_per_case": e2e,
                       "e2e_by_split": _groups(e2e, "split", _graph_summary),
                       "e2e_by_class": _groups(e2e, "category", _graph_summary)}
            if m12:
                variant.update(m12=_rank_summary(m12, m12=True), m12_per_case=m12,
                               m12_by_split=_groups(m12, "split", lambda rows: _rank_summary(rows, m12=True)),
                               pages=_rank_summary(pages, m12=False), pages_per_case=pages,
                               pages_by_split=_groups(pages, "split", lambda rows: _rank_summary(rows, m12=False)))
            if name != "dense":
                control_name = "natural_dense" if name in NATURAL_VARIANTS[1:] else "dense20" if name in utility.deep_rankings else "dense"
                control = report["variants"][control_name]["e2e_per_case"]
                variant["paired_validation"] = paired_grounded_exact(
                    [row for row in e2e if row["split"] == "validation"],
                    [row for row in control if row["split"] == "validation"], ISSUERS, seed=SEED,
                )
            report["variants"][name] = variant
            if sec is not None and name in NATURAL_VARIANTS:
                m13_safety = _run_graph(utility, name, router, cases=M13_CASES, sec_client=sec)
                direct_safety = _run_graph(utility, name, router, cases=DIRECT_CASES, sec_client=sec)
                variant["m13_safety"] = {"summary": _graph_summary(m13_safety), "per_case": m13_safety}
                variant["direct_safety"] = {"summary": _graph_summary(direct_safety), "per_case": direct_safety}
            if name == "dense20" and args.deep_backend:
                print(f"Q5 preparing {args.deep_backend} fixed 20-candidate pools", flush=True)
                report["resources"]["learned_backend"] = _deep_rankings(
                    utility, args.deep_backend, args.p1_run, args.colbert_cache, args.threads, e2e,
                )
                names.extend(utility.deep_rankings)
        report["resources"]["peak_working_set_bytes"] = peak_memory_bytes()
    write_json_atomic(args.output, report)


if __name__ == "__main__":
    main()
