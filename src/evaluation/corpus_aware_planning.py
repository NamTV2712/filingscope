"""Query-only versus Corpus Map conditioned planning on a frozen BM25 index."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import platform
import subprocess
import time
import tracemalloc
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from functools import wraps
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from src.decision.company_catalog import DEFAULT_COMPANY_ALIASES
from src.evaluation.financebench_dataset import FinanceBenchCase, load_financebench_cases
from src.evaluation.retrieval_metrics import evaluate_retrieval
from src.ingestion.chunker import count_tokens
from src.research.corpus_map import CorpusMap, SourceAvailability
from src.research.planner import (
    PLANNER_VERSION,
    CorpusAwarePlanner,
    QuestionOnlyPlanner,
    ResearchPlan,
)
from src.retrieval.hybrid_retriever import _tokenize

_TOP_K = 10
_CANDIDATE_K = 50
_SOURCE_FILES = (
    "src/research/corpus_map.py",
    "src/research/planner.py",
    "src/evaluation/corpus_aware_planning.py",
    "scripts/run_corpus_aware_planning_evaluation.py",
)


def _nearest_rank(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[index], 4)


def _track_peak_python_allocations(function):
    """Attach incremental peak Python allocations without reporting process RSS."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        already_tracing = tracemalloc.is_tracing()
        if not already_tracing:
            tracemalloc.start()
        baseline, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        try:
            result = function(*args, **kwargs)
            _, peak = tracemalloc.get_traced_memory()
            result["resource_use"]["python_peak_allocated_bytes"] = max(0, peak - baseline)
            return result
        finally:
            if not already_tracing:
                tracemalloc.stop()

    return wrapped


def _git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _source_provenance() -> dict[str, Any]:
    digest = hashlib.sha256()
    for filename in _SOURCE_FILES:
        path = Path(filename)
        if not path.is_file():
            raise FileNotFoundError(f"Cannot fingerprint corpus planner source: {filename}")
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        status = "unknown"
    return {
        "fingerprinted_files": list(_SOURCE_FILES),
        "git_revision": _git_revision(),
        "source_fingerprint_sha256": digest.hexdigest(),
        "working_tree_dirty": bool(status.strip()) if status != "unknown" else None,
    }


def _rank_plan(
    plan: ResearchPlan,
    *,
    bm25: BM25Okapi,
    chunks: list[Mapping[str, Any]],
    indices_by_document: Mapping[str, tuple[int, ...]],
) -> tuple[list[dict[str, Any]], set[tuple[str, int]], float, int, int]:
    query_started = time.perf_counter()
    max_score_by_index: dict[int, float] = {}
    candidate_pages: set[tuple[str, int]] = set()
    total_query_tokens = 0
    query_count = 0

    for task in plan.tasks:
        query = task.query
        if not query:
            continue
        query_count += 1
        tokens = _tokenize(query)
        total_query_tokens += count_tokens(query)
        scores = bm25.get_scores(tokens)
        if task.target_document_ids:
            eligible_indices = sorted({
                index
                for document_id in task.target_document_ids
                for index in indices_by_document.get(document_id, ())
            })
        else:
            eligible_indices = range(len(chunks))
        ranked_indices = heapq.nsmallest(
            max(_CANDIDATE_K, _TOP_K),
            eligible_indices,
            key=lambda index: (-float(scores[index]), str(chunks[index].get("chunk_id", ""))),
        )
        for index in ranked_indices[:_CANDIDATE_K]:
            document_id = chunks[index].get("doc_name") or chunks[index].get("document_id")
            page_number = chunks[index].get("page_number")
            if (
                isinstance(document_id, str)
                and isinstance(page_number, int)
                and not isinstance(page_number, bool)
            ):
                candidate_pages.add((document_id, page_number))
        for index in ranked_indices[:_TOP_K]:
            numeric_score = float(scores[index])
            current = max_score_by_index.get(index)
            if current is None or numeric_score > current:
                max_score_by_index[index] = numeric_score

    final_indices = sorted(
        max_score_by_index,
        key=lambda index: (-max_score_by_index[index], str(chunks[index].get("chunk_id", ""))),
    )[:_TOP_K]
    predictions = []
    for index in final_indices:
        chunk = chunks[index]
        predictions.append({
            "doc_name": chunk.get("doc_name") or chunk.get("document_id"),
            "page_number": chunk.get("page_number"),
            "chunk_id": chunk.get("chunk_id"),
            "score": max_score_by_index[index],
        })
    elapsed_ms = max(0.0, (time.perf_counter() - query_started) * 1000)
    return predictions, candidate_pages, elapsed_ms, query_count, total_query_tokens


def _candidate_recall_at_50(
    cases: Sequence[FinanceBenchCase],
    candidate_pages: Mapping[str, set[tuple[str, int]]],
) -> dict[str, Any]:
    recalls = []
    full_coverage = []
    for case in cases:
        gold = {(case.doc_name, page) for page in case.gold_pages}
        found = candidate_pages.get(case.case_id, set())
        recalls.append(len(gold.intersection(found)) / len(gold))
        full_coverage.append(float(gold.issubset(found)))
    return {
        "case_count": len(cases),
        "gold_page_candidate_recall_at_50_per_query_union": round(sum(recalls) / len(recalls), 4) if recalls else None,
        "full_evidence_coverage_at_50": round(sum(full_coverage) / len(full_coverage), 4) if full_coverage else None,
        "candidate_union_note": "Candidate pages are the union of each task query's top 50 chunk pages.",
    }


def _metric_without_cases(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "overall": result["overall"],
        "by_split": result["by_split"],
        "failures_by_question_type": result["failures_by_question_type"],
    }


def _planner_comparison(
    cases: Sequence[FinanceBenchCase],
    *,
    plans: Mapping[str, ResearchPlan],
    bm25: BM25Okapi,
    chunks: list[Mapping[str, Any]],
    indices_by_document: Mapping[str, tuple[int, ...]],
    planning_latencies: Mapping[str, float],
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], dict[str, float], dict[str, set[tuple[str, int]]]]:
    predictions: dict[str, list[dict[str, Any]]] = {}
    latency_ms: dict[str, float] = {}
    candidate_pages: dict[str, set[tuple[str, int]]] = {}
    retrieval_latency: list[float] = []
    query_counts = []
    query_token_counts = []
    source_states: Counter[str] = Counter()
    target_doc_hits = 0
    target_doc_opportunities = 0

    for case in cases:
        plan = plans[case.case_id]
        predictions_for_case, candidates, retrieve_ms, query_count, query_tokens = _rank_plan(
            plan,
            bm25=bm25,
            chunks=chunks,
            indices_by_document=indices_by_document,
        )
        predictions[case.case_id] = predictions_for_case
        candidate_pages[case.case_id] = candidates
        latency_ms[case.case_id] = retrieve_ms
        retrieval_latency.append(retrieve_ms)
        query_counts.append(query_count)
        query_token_counts.append(query_tokens)
        known_tasks = []
        for task in plan.tasks:
            source_states[task.source_availability.value] += 1
            if task.source_availability != SourceAvailability.UNKNOWN:
                known_tasks.append(task)
        if known_tasks:
            target_doc_opportunities += 1
            target_doc_hits += int(
                any(case.doc_name in task.target_document_ids for task in known_tasks)
            )

    retrieval_result = evaluate_retrieval(cases, predictions, latency_ms)
    available_planning_latency = list(planning_latencies.values())
    query_terms_mean = (
        sum(query_token_counts) / len(query_token_counts)
        if query_token_counts else 0.0
    )
    return ({
        "retrieval_metrics": _metric_without_cases(retrieval_result),
        "candidate_recall_at_50": _candidate_recall_at_50(cases, candidate_pages),
        "retrieval_calls": sum(query_counts),
        "retrieval_calls_per_question_mean": round(
            sum(query_counts) / len(query_counts), 4
        ) if query_counts else 0.0,
        "generated_query_tokens_per_question_mean": round(query_terms_mean, 4),
        "source_availability_counts": dict(sorted(source_states.items())),
        "gold_source_document_target_rate": (
            round(target_doc_hits / target_doc_opportunities, 4)
            if target_doc_opportunities
            else None
        ),
        "gold_source_document_target_opportunities": target_doc_opportunities,
        "planner_latency_ms": {
            "p50": _nearest_rank(available_planning_latency, 0.50),
            "p95": _nearest_rank(available_planning_latency, 0.95),
            "measured_case_count": len(available_planning_latency),
        },
        "bm25_latency_ms": {
            "p50": _nearest_rank(retrieval_latency, 0.50),
            "p95": _nearest_rank(retrieval_latency, 0.95),
            "case_count": len(retrieval_latency),
        },
    }, predictions, latency_ms, candidate_pages)


def _absent_company_probes(
    corpus_map: CorpusMap,
    question_planner: QuestionOnlyPlanner,
    corpus_planner: CorpusAwarePlanner,
) -> dict[str, Any]:
    absent_entities = [
        (entity_id, aliases)
        for entity_id, aliases in sorted(DEFAULT_COMPANY_ALIASES.items())
        if entity_id not in corpus_map.indexed_company_entity_ids
    ]
    baseline_queries = 0
    corpus_queries = 0
    correctly_marked_missing = 0
    rows = []
    for entity_id, aliases in absent_entities:
        display_name = next(
            (alias for alias in aliases if alias.upper() != entity_id),
            entity_id,
        )
        question = f"What was {display_name} revenue in FY2024?"
        baseline = question_planner.plan(question)
        conditioned = corpus_planner.plan(question)
        baseline_queries += baseline.retrieval_call_count
        corpus_queries += conditioned.retrieval_call_count
        states = [task.source_availability for task in conditioned.tasks]
        marked_missing = bool(states) and all(
            state == SourceAvailability.MISSING for state in states
        )
        correctly_marked_missing += int(marked_missing)
        rows.append({
            "company_entity_id": entity_id,
            "question_only_retrieval_calls": baseline.retrieval_call_count,
            "corpus_aware_retrieval_calls": conditioned.retrieval_call_count,
            "corpus_aware_source_states": sorted({state.value for state in states}),
            "missing_source_marked": marked_missing,
        })
    return {
        "probe_count": len(rows),
        "question_only_retrieval_calls": baseline_queries,
        "corpus_aware_retrieval_calls": corpus_queries,
        "retrieval_calls_avoided": baseline_queries - corpus_queries,
        "correctly_marked_missing_count": correctly_marked_missing,
        "missing_state_accuracy": (
            round(correctly_marked_missing / len(rows), 4) if rows else None
        ),
        "probes": rows,
        "interpretation_note": (
            "Probes use default catalog companies absent from the runtime index. "
            "They are an explicit source-availability stress set, not user-query prevalence estimates."
        ),
    }


@_track_peak_python_allocations
def evaluate_corpus_aware_planning(
    cases: Sequence[FinanceBenchCase],
    chunks: Sequence[Mapping[str, Any]],
    corpus_map: CorpusMap,
    *,
    index_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare deterministic question-only and map-conditioned query plans.

    The planners receive only `case.question`. Gold source document/page labels
    are used only after retrieval, to score the resulting rankings.
    """
    if not cases:
        raise ValueError("corpus-aware planning evaluation requires cases")
    if not chunks:
        raise ValueError("corpus-aware planning evaluation requires corpus chunks")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("evaluation cases must have unique IDs")

    started = time.perf_counter()
    question_planner = QuestionOnlyPlanner()
    corpus_planner = CorpusAwarePlanner(corpus_map)
    planning_times: dict[str, dict[str, float]] = {"question_only": {}, "corpus_aware": {}}
    question_plans: dict[str, ResearchPlan] = {}
    corpus_plans: dict[str, ResearchPlan] = {}
    all_texts = []
    indices_by_document_lists: dict[str, list[int]] = defaultdict(list)
    for index, chunk in enumerate(chunks):
        text = chunk.get("text")
        if not isinstance(text, str):
            raise ValueError(f"corpus chunk at index {index} has no text")
        all_texts.append(_tokenize(text))
        document_id = chunk.get("doc_name") or chunk.get("document_id")
        if isinstance(document_id, str) and document_id:
            indices_by_document_lists[document_id].append(index)
    indices_by_document = {
        document_id: tuple(indices)
        for document_id, indices in indices_by_document_lists.items()
    }
    bm25 = BM25Okapi(all_texts)

    for case in cases:
        plan_started = time.perf_counter()
        question_plans[case.case_id] = question_planner.plan(case.question)
        planning_times["question_only"][case.case_id] = max(
            0.0, (time.perf_counter() - plan_started) * 1000
        )
        plan_started = time.perf_counter()
        corpus_plans[case.case_id] = corpus_planner.plan(case.question)
        planning_times["corpus_aware"][case.case_id] = max(
            0.0, (time.perf_counter() - plan_started) * 1000
        )

    chunks_list = list(chunks)
    question_result, _, _, _ = _planner_comparison(
        cases,
        plans=question_plans,
        bm25=bm25,
        chunks=chunks_list,
        indices_by_document=indices_by_document,
        planning_latencies=planning_times["question_only"],
    )
    corpus_result, _, _, _ = _planner_comparison(
        cases,
        plans=corpus_plans,
        bm25=bm25,
        chunks=chunks_list,
        indices_by_document=indices_by_document,
        planning_latencies=planning_times["corpus_aware"],
    )

    synthetic_probes = _absent_company_probes(corpus_map, question_planner, corpus_planner)
    planned_source_rate = corpus_result["gold_source_document_target_rate"]
    counts_by_split = Counter(case.split for case in cases)
    chunk_text_count = sum(len(tokens) for tokens in all_texts)
    map_bytes = len(
        json.dumps(corpus_map.runtime_payload(), ensure_ascii=False, sort_keys=True).encode("utf-8")
    )

    return {
        "schema_version": 1,
        "benchmark": "filingscope-corpus-aware-planning-financebench-bm25-v1",
        "benchmark_version": "1.0.0",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "case_count": len(cases),
        "split_counts": dict(sorted(counts_by_split.items())),
        "dataset": {
            "name": "FinanceBench public open-source sample",
            "case_count": len(cases),
            "gold_labels_passed_to_planners": False,
        },
        "corpus_map": {
            "schema_version": corpus_map.schema_version,
            "index_generation_id": corpus_map.index_generation_id,
            "collection_name": corpus_map.collection_name,
            "document_count": len(corpus_map.documents),
            "chunk_count": corpus_map.chunk_count,
            "company_count": len(corpus_map.indexed_company_entity_ids),
            "metadata_coverage": {
                key: value.value for key, value in corpus_map.metadata_coverage.items()
            },
            "source_coverage": {
                key: value.value for key, value in corpus_map.source_coverage.items()
            },
            "serialized_size_bytes": map_bytes,
        },
        "configuration": {
            "question_only_planner_version": PLANNER_VERSION,
            "corpus_aware_planner_version": PLANNER_VERSION,
            "retrieval_method": "BM25 on frozen indexed chunk text",
            "top_k": _TOP_K,
            "candidate_pool_k": _CANDIDATE_K,
            "fallback_document_limit": corpus_planner.fallback_document_limit,
        },
        "comparison": {
            "question_only": question_result,
            "corpus_aware": corpus_result,
        },
        "synthetic_absent_company_probes": synthetic_probes,
        "provider_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_provider_cost_usd": 0.0,
        "resource_use": {
            "indexed_chunk_count": len(chunks),
            "bm25_tokenized_chunk_token_count": chunk_text_count,
            "corpus_map_serialized_size_bytes": map_bytes,
            "python_peak_allocated_bytes": None,
            "peak_process_memory_bytes": None,
        },
        "runtime_environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "index_manifest": dict(index_manifest or {}),
        "source_provenance": _source_provenance(),
        "interpretation_note": (
            "Retrieval measurements use BM25 only to isolate query planning; they do not replace or retune "
            "the dense FinanceBench baseline. Corpus Map metadata comes from indexed chunk payloads. "
            "Only the question string reaches either planner; source page/document labels are read by the evaluator. "
            f"Corpus-aware gold-source-document target rate is {planned_source_rate}."
        ),
        "evaluation_wall_time_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def load_corpus_planning_inputs(
    data_dir: Path = Path("data/financebench"),
    run_dir: Path | None = None,
) -> tuple[list[FinanceBenchCase], list[dict[str, Any]], CorpusMap, dict[str, Any]]:
    """Load the frozen evaluation cases and runtime corpus artifact separately."""
    source_path = data_dir / "source" / "financebench_open_source.jsonl"
    if not source_path.is_file():
        raise FileNotFoundError(f"FinanceBench evaluation cases are missing: {source_path}")
    cases = load_financebench_cases(source_path)
    selected_run = run_dir or _find_corpus_run(data_dir)
    index_manifest_path = selected_run / "index_manifest.json"
    chunks_path = selected_run / "corpus_chunks.jsonl"
    if not index_manifest_path.is_file() or not chunks_path.is_file():
        raise FileNotFoundError(f"Runtime corpus run is incomplete: {selected_run}")
    index_manifest = json.loads(index_manifest_path.read_text(encoding="utf-8"))
    chunks = []
    with chunks_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{chunks_path}:{line_number} must contain a JSON object")
            chunks.append(row)
    if len(chunks) != index_manifest.get("point_count"):
        raise ValueError("runtime corpus chunk count does not match index manifest")
    corpus_map = CorpusMap.from_chunks(
        chunks,
        index_generation_id=index_manifest.get("index_id"),
        collection_name=index_manifest.get("collection_name"),
    )
    return cases, chunks, corpus_map, index_manifest


def _find_corpus_run(data_dir: Path) -> Path:
    candidates = []
    for index_path in (data_dir / "runs").glob("*/index_manifest.json"):
        try:
            manifest = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("status") != "green":
            continue
        if not (index_path.parent / "corpus_chunks.jsonl").is_file():
            continue
        run_manifest_path = index_path.parent / "run_manifest.json"
        completed = ""
        if run_manifest_path.is_file():
            try:
                completed = str(json.loads(run_manifest_path.read_text(encoding="utf-8")).get("completed_at_utc", ""))
            except (OSError, json.JSONDecodeError):
                pass
        candidates.append((completed, index_path.parent))
    if not candidates:
        raise FileNotFoundError(f"No green runtime index exists under {data_dir / 'runs'}")
    return max(candidates, key=lambda item: item[0])[1]


__all__ = [
    "evaluate_corpus_aware_planning",
    "load_corpus_planning_inputs",
]
