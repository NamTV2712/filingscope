"""Run FinanceBench retrieval-stage diagnostics without provider calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from configs.financebench import FINANCEBENCH_GITHUB_REVISION
from configs.settings import settings
from src.decision.company_catalog import CompanyCatalog
from src.evaluation.benchmark_io import write_json_atomic as _write_json_atomic
from src.evaluation.financebench_dataset import FinanceBenchCase, load_financebench_cases
from src.evaluation.retrieval_diagnostics import (
    fuse_ranked_ids,
    metadata_filter_profiles,
    metadata_filters_from_question,
    ranked_ids_from_trace,
    rerank_candidate_ids,
    route_aware_fusion_weights,
)
from src.evaluation.retrieval_metrics import evaluate_retrieval
from src.retrieval.embedder import Embedder
from src.retrieval.hybrid_retriever import CROSS_ENCODER_BATCH_SIZE, HybridRetriever
from src.retrieval.vector_store import VectorStore

logger = logging.getLogger(__name__)
DEFAULT_DATA_DIR = Path("data/financebench")
RANKING_POOL = 50
POOL_LEVELS = (10, 25, 50)
SOURCE_NAMES = {
    "bm25": ("BM25", "bm25_rank"),
    "dense": ("Dense", "dense_rank"),
    "lexical": ("Lexical ladder", "lexical_rank"),
}
WEIGHTED_RRF = {"bm25": 1.0, "dense": 2.0, "lexical": 0.5}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            records.append(value)
    return records


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
    files = (
        "configs/financebench.py",
        "configs/settings.py",
        "requirements.txt",
        "src/decision/company_catalog.py",
        "src/evaluation/financebench_dataset.py",
        "src/evaluation/retrieval_diagnostics.py",
        "src/evaluation/retrieval_metrics.py",
        "src/retrieval/embedder.py",
        "src/retrieval/hybrid_retriever.py",
        "src/retrieval/lexical_ladder.py",
        "src/retrieval/query_shaper.py",
        "src/retrieval/vector_store.py",
        "scripts/run_retrieval_diagnostics.py",
    )
    digest = hashlib.sha256()
    for filename in files:
        path = Path(filename)
        if not path.is_file():
            raise FileNotFoundError(f"Cannot fingerprint diagnostic source: {filename}")
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
        "fingerprinted_files": list(files),
        "git_revision": _git_revision(),
        "source_fingerprint_sha256": digest.hexdigest(),
        "working_tree_dirty": bool(status.strip()) if status != "unknown" else None,
    }


def _nearest_rank(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, int(np.ceil(quantile * len(ordered))) - 1)
    return round(ordered[index], 3)


def _source_candidate_metrics(
    cases: list[FinanceBenchCase],
    ranked_ids: dict[str, list[str]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, float | int]:
    total_gold_pages = 0
    found_gold_pages = 0
    case_recall: list[float] = []
    complete_cases = 0
    for case in cases:
        gold = set(case.gold_pages)
        observed = {
            chunk.get("page_number")
            for chunk_id in ranked_ids.get(case.case_id, [])
            if (chunk := chunks_by_id.get(chunk_id)) is not None
            and chunk.get("doc_name") == case.doc_name
            and isinstance(chunk.get("page_number"), int)
        }
        hits = len(gold.intersection(observed))
        total_gold_pages += len(gold)
        found_gold_pages += hits
        case_recall.append(hits / max(1, len(gold)))
        complete_cases += int(gold.issubset(observed))
    return {
        "case_count": len(cases),
        "gold_page_recall_micro": round(found_gold_pages / max(1, total_gold_pages), 4),
        "gold_page_recall_macro": round(sum(case_recall) / max(1, len(case_recall)), 4),
        "full_evidence_coverage": round(complete_cases / max(1, len(cases)), 4),
        "complete_case_count": complete_cases,
    }


def _retrieval_metrics(
    cases: list[FinanceBenchCase],
    predictions: dict[str, list[str]],
    chunks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    materialized = {
        case_id: [
            {
                "doc_name": chunks_by_id[chunk_id].get("doc_name"),
                "page_number": chunks_by_id[chunk_id].get("page_number"),
                "chunk_id": chunk_id,
            }
            for chunk_id in chunk_ids
            if chunk_id in chunks_by_id
        ]
        for case_id, chunk_ids in predictions.items()
    }
    result = evaluate_retrieval(cases, materialized)
    result.pop("case_metrics", None)
    for summary in (result["overall"], *result["by_split"].values()):
        summary.pop("latency_ms_p50", None)
        summary.pop("latency_ms_p95", None)
    return result


def _case_predictions(
    *,
    question: str,
    bm25_ids: list[str],
    dense_ids: list[str],
    lexical_ids: list[str],
    cross_scores_by_pool: dict[int, dict[str, float]],
) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for top_k in (5, 10):
        output[f"bm25_top_{top_k}"] = bm25_ids[:top_k]
        output[f"dense_top_{top_k}"] = dense_ids[:top_k]
        output[f"lexical_top_{top_k}"] = lexical_ids[:top_k]

        current_rrf, _ = fuse_ranked_ids(
            bm25_ids=bm25_ids,
            dense_ids=dense_ids,
            lexical_ids=lexical_ids,
            bm25_candidates=RANKING_POOL,
            dense_candidates=RANKING_POOL,
            lexical_candidates=RANKING_POOL,
            fusion_candidates=RANKING_POOL,
        )
        output[f"rrf_top_{top_k}"] = current_rrf[:top_k]
        weighted_rrf, _ = fuse_ranked_ids(
            bm25_ids=bm25_ids,
            dense_ids=dense_ids,
            lexical_ids=lexical_ids,
            bm25_candidates=RANKING_POOL,
            dense_candidates=RANKING_POOL,
            lexical_candidates=RANKING_POOL,
            fusion_candidates=RANKING_POOL,
            weights=WEIGHTED_RRF,
        )
        output[f"weighted_rrf_top_{top_k}"] = weighted_rrf[:top_k]
        dense_preserving, _ = fuse_ranked_ids(
            bm25_ids=bm25_ids,
            dense_ids=dense_ids,
            lexical_ids=lexical_ids,
            bm25_candidates=RANKING_POOL,
            dense_candidates=25,
            lexical_candidates=RANKING_POOL,
            fusion_candidates=RANKING_POOL,
            dense_preserving=True,
        )
        output[f"dense_preserving_top_{top_k}"] = dense_preserving[:top_k]
        _, route_weights = route_aware_fusion_weights(question)
        route_aware, _ = fuse_ranked_ids(
            bm25_ids=bm25_ids,
            dense_ids=dense_ids,
            lexical_ids=lexical_ids,
            bm25_candidates=RANKING_POOL,
            dense_candidates=RANKING_POOL,
            lexical_candidates=RANKING_POOL,
            fusion_candidates=RANKING_POOL,
            weights=route_weights,
        )
        output[f"route_aware_top_{top_k}"] = route_aware[:top_k]
        for pool_size, scores in cross_scores_by_pool.items():
            if top_k == 10:
                output[f"rrf_cross_encoder_pool_{pool_size}_top_10"] = rerank_candidate_ids(
                    current_rrf[:pool_size], scores, top_k=10
                )
    return output


def _pool_sweep_predictions(
    *,
    bm25_ids: list[str],
    dense_ids: list[str],
    lexical_ids: list[str],
    cross_scores_by_pool: dict[int, dict[str, float]],
) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    baseline_sources = {
        "bm25_candidates": (RANKING_POOL, RANKING_POOL, RANKING_POOL),
        "dense_candidates": (RANKING_POOL, RANKING_POOL, RANKING_POOL),
        "lexical_candidates": (RANKING_POOL, RANKING_POOL, RANKING_POOL),
        "fusion_candidates": (RANKING_POOL, RANKING_POOL, RANKING_POOL),
    }
    for source_name in baseline_sources:
        levels = (0, 10, 25, 50) if source_name == "lexical_candidates" else POOL_LEVELS
        for level in levels:
            b_count, d_count, l_count = baseline_sources[source_name]
            fusion_count = RANKING_POOL
            if source_name == "bm25_candidates":
                b_count = level
            elif source_name == "dense_candidates":
                d_count = level
            elif source_name == "lexical_candidates":
                l_count = level
            else:
                fusion_count = level
            ranking, _ = fuse_ranked_ids(
                bm25_ids=bm25_ids,
                dense_ids=dense_ids,
                lexical_ids=lexical_ids,
                bm25_candidates=b_count,
                dense_candidates=d_count,
                lexical_candidates=l_count,
                fusion_candidates=fusion_count,
            )
            output[f"sweep_{source_name}_{level}"] = ranking[:10]

    full_ranking, _ = fuse_ranked_ids(
        bm25_ids=bm25_ids,
        dense_ids=dense_ids,
        lexical_ids=lexical_ids,
        bm25_candidates=RANKING_POOL,
        dense_candidates=RANKING_POOL,
        lexical_candidates=RANKING_POOL,
        fusion_candidates=RANKING_POOL,
    )
    for pool_size, scores in cross_scores_by_pool.items():
        output[f"sweep_rerank_candidates_{pool_size}"] = rerank_candidate_ids(
            full_ranking[:pool_size], scores, top_k=10
        )
    for top_k in (5, 10):
        output[f"sweep_final_k_{top_k}"] = full_ranking[:top_k]
        scores = cross_scores_by_pool[50]
        output[f"sweep_rerank_50_final_k_{top_k}"] = rerank_candidate_ids(
            full_ranking[:50], scores, top_k=top_k
        )
    return output


def _load_p1_run(run_dir: Path, data_dir: Path) -> tuple[list[FinanceBenchCase], list[dict[str, Any]], dict[str, Any]]:
    required = (
        "run_manifest.json",
        "index_manifest.json",
        "corpus_chunks.jsonl",
        "predictions_bm25.jsonl",
        "predictions_dense.jsonl",
        "predictions_hybrid.jsonl",
        "predictions_hybrid_rerank.jsonl",
    )
    missing = [name for name in required if not (run_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"P1 run is incomplete: {', '.join(missing)}")
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    index_manifest = json.loads((run_dir / "index_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset_revision") != FINANCEBENCH_GITHUB_REVISION:
        raise ValueError("P1 run does not use the pinned FinanceBench revision")
    if manifest.get("prediction_artifacts_exclude_gold_answers") is not True:
        raise ValueError("P1 prediction artifacts must exclude gold answers")
    if manifest.get("corpus_fingerprint") != index_manifest.get("corpus_fingerprint"):
        raise ValueError("P1 index and corpus fingerprints do not match")
    cases = load_financebench_cases(data_dir / "source" / "financebench_open_source.jsonl")
    chunks = _read_jsonl(run_dir / "corpus_chunks.jsonl")
    if len(chunks) != manifest.get("index_manifest", {}).get("point_count"):
        raise ValueError("P1 corpus chunk count does not match its index manifest")
    return cases, chunks, {"run": manifest, "index": index_manifest}


def _metadata_capabilities(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    fields = ("company", "ticker", "cik", "reporting_periods", "doc_type", "form_type", "section")
    summaries = {}
    for field in fields:
        observed: set[str] = set()
        covered_chunks = 0
        for chunk in chunks:
            raw_value = chunk.get(field)
            values = raw_value if isinstance(raw_value, (list, tuple, set)) else (raw_value,)
            values = {str(value) for value in values if value is not None and str(value)}
            if values:
                covered_chunks += 1
                observed.update(values)
        summaries[field] = {
            "covered_chunks": covered_chunks,
            "unique_values": len(observed),
            "available": bool(observed),
            "values_preview": sorted(observed)[:12],
        }
    return {
        "fields": summaries,
        "query_filter_fields": ["company", "reporting_periods", "doc_type"],
        "limitations": {
            "cik": "not present in the P1 PDF chunk metadata",
            "ticker": "not present in the P1 PDF chunk metadata",
            "form_type": "not present; doc_type is available instead",
            "section": "only one section value is present, so section filtering is not discriminative",
        },
    }


def _company_values_by_entity(
    chunks: list[dict[str, Any]],
    catalog: CompanyCatalog,
) -> dict[str, set[str]]:
    output: dict[str, set[str]] = defaultdict(set)
    for chunk in chunks:
        company = chunk.get("company")
        if isinstance(company, str) and company.strip():
            entity_id = catalog.metadata_entity_id(company)
            if entity_id:
                output[entity_id].add(company)
    return output


def run_diagnostics(
    *,
    retrieval_run_dir: Path,
    data_dir: Path = DEFAULT_DATA_DIR,
    max_cases: int | None = None,
    split: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    cases, chunks, p1_manifest = _load_p1_run(retrieval_run_dir, data_dir)
    selected_cases = [case for case in cases if split is None or case.split == split]
    if max_cases is not None:
        if max_cases < 1:
            raise ValueError("max_cases must be positive")
        selected_cases = selected_cases[:max_cases]
    if not selected_cases:
        raise ValueError("No FinanceBench cases selected")
    chunks_by_id = {str(chunk["chunk_id"]): chunk for chunk in chunks}
    if len(chunks_by_id) != len(chunks):
        raise ValueError("P1 corpus contains duplicate chunk IDs")
    company_catalog = CompanyCatalog.from_document_rows(chunks)
    company_values_by_entity = _company_values_by_entity(chunks, company_catalog)
    available_periods = {
        str(period)
        for chunk in chunks
        for period in chunk.get("reporting_periods", ())
        if period is not None
    }
    available_doc_types = {
        str(chunk["doc_type"])
        for chunk in chunks
        if chunk.get("doc_type") is not None
    }
    metadata_capabilities = _metadata_capabilities(chunks)

    p1_predictions = {}
    for preset in ("bm25", "dense", "hybrid", "hybrid_rerank"):
        records = _read_jsonl(retrieval_run_dir / f"predictions_{preset}.jsonl")
        p1_predictions[preset] = {str(row["case_id"]): row for row in records}
        if any(case.case_id not in p1_predictions[preset] for case in selected_cases):
            raise ValueError(f"P1 {preset} predictions do not cover the selected cases")

    index_manifest = p1_manifest["index"]
    embedder = Embedder(
        model_name=settings.embedding_model_id,
        revision=settings.embedding_model_revision,
    )
    store = VectorStore(
        path=retrieval_run_dir / "qdrant",
        collection_name=index_manifest["collection_name"],
    )
    retriever = HybridRetriever(
        embedder=embedder,
        store=store,
        all_chunks=chunks,
        device=embedder.device,
        cross_encoder_model=settings.reranker_model_id,
        cross_encoder_revision=settings.reranker_model_revision,
    )

    source_predictions: dict[str, dict[str, list[str]]] = {
        name: {} for name in SOURCE_NAMES
    }
    variant_predictions: dict[str, dict[str, list[str]]] = {}
    stage_timings: dict[str, list[float]] = {}
    rerank_timings: dict[int, list[float]] = {size: [] for size in POOL_LEVELS}
    replay_matches: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    metadata_filter_field_counts: Counter[str] = Counter()
    metadata_filter_predictions: dict[str, dict[str, dict[str, list[str]]]] = {}
    metadata_filter_cases: dict[str, dict[str, FinanceBenchCase]] = {}
    metadata_filter_fields_by_profile: dict[str, set[str]] = {}
    metadata_filter_latency: dict[str, list[float]] = defaultdict(list)
    per_case: list[dict[str, Any]] = []

    try:
        warmup = retriever.inspect(
            "FilingScope retrieval diagnostics warmup",
            top_k=10,
            candidate_pool=RANKING_POOL,
            preset="hybrid",
        )
        del warmup
        for case_number, case in enumerate(selected_cases, start=1):
            embedding_started = time.perf_counter()
            query_embedding = retriever.embed_query(case.question)
            query_embedding_ms = max(0.0, (time.perf_counter() - embedding_started) * 1000)
            trace = retriever.inspect(
                case.question,
                top_k=10,
                candidate_pool=RANKING_POOL,
                preset="hybrid",
                query_embedding=query_embedding,
            )
            ranked = {
                source: ranked_ids_from_trace(trace, rank_key)
                for source, (_, rank_key) in SOURCE_NAMES.items()
            }
            for source, ids in ranked.items():
                source_predictions[source][case.case_id] = ids
            bm25_ids = ranked["bm25"]
            dense_ids = ranked["dense"]
            lexical_ids = ranked["lexical"]

            current_rrf, _ = fuse_ranked_ids(
                bm25_ids=bm25_ids,
                dense_ids=dense_ids,
                lexical_ids=lexical_ids,
                bm25_candidates=RANKING_POOL,
                dense_candidates=RANKING_POOL,
                lexical_candidates=RANKING_POOL,
                fusion_candidates=RANKING_POOL,
            )
            cross_scores_by_pool: dict[int, dict[str, float]] = {}
            for pool_size in POOL_LEVELS:
                candidates = current_rrf[:pool_size]
                pairs = [(case.question, chunks_by_id[chunk_id]["text"]) for chunk_id in candidates]
                started = time.perf_counter()
                with retriever._model_lock:
                    scores = retriever.cross_encoder.predict(
                        pairs,
                        batch_size=CROSS_ENCODER_BATCH_SIZE,
                    )
                elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000)
                rerank_timings[pool_size].append(elapsed_ms)
                cross_scores_by_pool[pool_size] = {
                    chunk_id: float(score)
                    for chunk_id, score in zip(candidates, scores, strict=True)
                }

            route_name, _ = route_aware_fusion_weights(case.question)
            route_counts[route_name] += 1
            predictions = _case_predictions(
                question=case.question,
                bm25_ids=bm25_ids,
                dense_ids=dense_ids,
                lexical_ids=lexical_ids,
                cross_scores_by_pool=cross_scores_by_pool,
            )
            predictions.update(_pool_sweep_predictions(
                bm25_ids=bm25_ids,
                dense_ids=dense_ids,
                lexical_ids=lexical_ids,
                cross_scores_by_pool=cross_scores_by_pool,
            ))
            for variant, ids in predictions.items():
                variant_predictions.setdefault(variant, {})[case.case_id] = ids

            query_filters = metadata_filters_from_question(
                case.question,
                company_catalog=company_catalog,
                company_values_by_entity=company_values_by_entity,
                available_periods=available_periods,
                available_doc_types=available_doc_types,
            )
            metadata_filter_field_counts.update(query_filters.keys())
            profiles = metadata_filter_profiles(query_filters)
            metadata_filter_candidate_ids: dict[str, dict[str, list[str]]] = {}
            for profile, filters in profiles.items():
                filter_started = time.perf_counter()
                filtered_trace = retriever.inspect(
                    case.question,
                    top_k=10,
                    candidate_pool=RANKING_POOL,
                    preset="hybrid",
                    query_embedding=query_embedding,
                    metadata_filters=filters,
                )
                filtered_ranked = {
                    source: ranked_ids_from_trace(filtered_trace, rank_key)
                    for source, (_, rank_key) in SOURCE_NAMES.items()
                }
                filtered_rrf, _ = fuse_ranked_ids(
                    bm25_ids=filtered_ranked["bm25"],
                    dense_ids=filtered_ranked["dense"],
                    lexical_ids=filtered_ranked["lexical"],
                    bm25_candidates=RANKING_POOL,
                    dense_candidates=RANKING_POOL,
                    lexical_candidates=RANKING_POOL,
                    fusion_candidates=RANKING_POOL,
                )
                profile_predictions = metadata_filter_predictions.setdefault(
                    profile,
                    {"dense": {}, "rrf": {}},
                )
                profile_predictions["dense"][case.case_id] = filtered_ranked["dense"][:10]
                profile_predictions["rrf"][case.case_id] = filtered_rrf[:10]
                metadata_filter_candidate_ids[profile] = {
                    "dense_top_10": filtered_ranked["dense"][:10],
                    "rrf_top_10": filtered_rrf[:10],
                }
                metadata_filter_cases.setdefault(profile, {})[case.case_id] = case
                metadata_filter_fields_by_profile[profile] = set(filters)
                metadata_filter_latency[profile].append(
                    max(0.0, (time.perf_counter() - filter_started) * 1000)
                )

            for preset, ids in (
                ("bm25", bm25_ids[:10]),
                ("dense", dense_ids[:10]),
                ("hybrid", current_rrf[:10]),
                (
                    "hybrid_rerank",
                    rerank_candidate_ids(current_rrf[:50], cross_scores_by_pool[50], top_k=10),
                ),
            ):
                p1_ids = [str(item["chunk_id"]) for item in p1_predictions[preset][case.case_id]["retrieved"]]
                replay_matches[preset] += int(ids == p1_ids)

            for stage in trace.get("stages", []):
                if (
                    stage.get("name") == "embedding"
                    and stage.get("status") == "reused"
                ):
                    stage_timings.setdefault("embedding", []).append(query_embedding_ms)
                elif stage.get("status") == "executed" and isinstance(stage.get("elapsed_ms"), (float, int)):
                    stage_timings.setdefault(str(stage["name"]), []).append(float(stage["elapsed_ms"]))
            per_case.append({
                "case_id": case.case_id,
                "split": case.split,
                "stage_candidate_counts": {name: len(ids) for name, ids in ranked.items()},
                "gold_page_recall": {
                    source: _source_candidate_metrics(
                        [case], {case.case_id: ids}, chunks_by_id
                    )["gold_page_recall_macro"]
                    for source, ids in ranked.items()
                },
                "candidate_union_gold_page_recall": _source_candidate_metrics(
                    [case], {case.case_id: list(dict.fromkeys((*bm25_ids, *dense_ids, *lexical_ids)))},
                    chunks_by_id,
                )["gold_page_recall_macro"],
                "fusion_route": route_name,
                "query_derived_metadata_filters": {
                    field: list(values) for field, values in query_filters.items()
                },
                "metadata_filter_candidates": metadata_filter_candidate_ids,
                "selected_chunk_ids": predictions,
            })
            if case_number % 10 == 0 or case_number == len(selected_cases):
                logger.info("Diagnosed %d/%d cases", case_number, len(selected_cases))

        candidate_stages = {}
        for source, (_, _) in SOURCE_NAMES.items():
            candidate_stages[source] = {
                str(cutoff): _source_candidate_metrics(
                    selected_cases,
                    {
                        case.case_id: source_predictions[source][case.case_id][:cutoff]
                        for case in selected_cases
                    },
                    chunks_by_id,
                )
                for cutoff in (5, 10, 25, 50)
            }
        union_predictions = {
            case.case_id: list(dict.fromkeys((
                *source_predictions["bm25"][case.case_id],
                *source_predictions["dense"][case.case_id],
                *source_predictions["lexical"][case.case_id],
            )))
            for case in selected_cases
        }
        candidate_stages["union_top_50_per_source"] = _source_candidate_metrics(
            selected_cases, union_predictions, chunks_by_id
        )

        variant_metrics = {
            variant: _retrieval_metrics(selected_cases, predictions, chunks_by_id)
            for variant, predictions in sorted(variant_predictions.items())
        }
        metadata_filter_metrics = {}
        for profile, predictions in sorted(metadata_filter_predictions.items()):
            profile_cases = list(metadata_filter_cases[profile].values())
            baseline = {
                "dense": {
                    case.case_id: source_predictions["dense"][case.case_id][:10]
                    for case in profile_cases
                },
                "rrf": {
                    case.case_id: variant_predictions["rrf_top_10"][case.case_id]
                    for case in profile_cases
                },
            }
            latency_values = metadata_filter_latency[profile]
            metadata_filter_metrics[profile] = {
                "eligible_case_count": len(profile_cases),
                "applied_fields": sorted(metadata_filter_fields_by_profile[profile]),
                "baseline_unfiltered": {
                    variant: _retrieval_metrics(profile_cases, rows, chunks_by_id)
                    for variant, rows in baseline.items()
                },
                "filtered": {
                    variant: _retrieval_metrics(profile_cases, rows, chunks_by_id)
                    for variant, rows in predictions.items()
                },
                "retrieval_latency_ms": {
                    "p50": _nearest_rank(latency_values, 0.50),
                    "p95": _nearest_rank(latency_values, 0.95),
                    "case_count": len(latency_values),
                },
            }
        stage_latency = {
            stage: {
                "p50_ms": _nearest_rank(values, 0.50),
                "p95_ms": _nearest_rank(values, 0.95),
                "case_count": len(values),
            }
            for stage, values in sorted(stage_timings.items())
        }
        rerank_latency = {
            str(size): {
                "p50_ms": _nearest_rank(values, 0.50),
                "p95_ms": _nearest_rank(values, 0.95),
                "case_count": len(values),
                "pairs_per_case": size,
            }
            for size, values in sorted(rerank_timings.items())
        }
        results = {
            "schema_version": 1,
            "benchmark": "FinanceBench retrieval stage diagnostics",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "provider_calls": 0,
            "dataset_revision": FINANCEBENCH_GITHUB_REVISION,
            "case_count": len(selected_cases),
            "split_counts": dict(Counter(case.split for case in selected_cases)),
            "p1_run": {
                "path": str(retrieval_run_dir),
                "corpus_fingerprint": p1_manifest["run"]["corpus_fingerprint"],
                "index_id": p1_manifest["index"]["index_id"],
                "candidate_pool": p1_manifest["run"]["retrieval"]["candidate_pool"],
            },
            "configuration": {
                "source_candidate_ceiling": RANKING_POOL,
                "candidate_pool_sweeps": list(POOL_LEVELS),
                "fusion_pool_sweeps": list(POOL_LEVELS),
                "rerank_pool_sweeps": list(POOL_LEVELS),
                "weighted_rrf_weights": WEIGHTED_RRF,
                "route_aware_fusion": {
                    "signal": "query_shaper.exact_phrases",
                    "profiles": {
                        "filing_native_phrase": {
                            "bm25": 1.0,
                            "dense": 1.0,
                            "lexical": 2.0,
                        },
                        "dense_priority": WEIGHTED_RRF,
                    },
                },
                "dense_preserving_config": {
                    "dense_candidates": 25,
                    "dense_candidates_reserved": True,
                    "bm25_candidates": 50,
                    "lexical_candidates": 50,
                    "fusion_candidates": 50,
                },
                "reranker_relative_cutoff": 0.5,
                "final_k_values": [5, 10],
                "retrieval_model": {
                    "id": settings.embedding_model_id,
                    "revision": settings.embedding_model_revision,
                    "device": embedder.device,
                },
                "reranker_model": {
                    "id": settings.reranker_model_id,
                    "revision": settings.reranker_model_revision,
                },
            },
            "source_candidate_metrics": candidate_stages,
            "variant_metrics": variant_metrics,
            "route_aware_route_counts": dict(route_counts),
            "metadata_filter_capabilities": metadata_capabilities,
            "metadata_filter_query_coverage": {
                "field_case_counts": {
                    field: metadata_filter_field_counts.get(field, 0)
                    for field in ("company", "reporting_periods", "doc_type")
                },
                "profile_case_counts": {
                    profile: len(cases_by_id)
                    for profile, cases_by_id in sorted(metadata_filter_cases.items())
                },
                "filters_are_derived_from_questions_only": True,
            },
            "metadata_filter_metrics": metadata_filter_metrics,
            "stage_latency": stage_latency,
            "rerank_latency": rerank_latency,
            "p1_replay_parity": {
                preset: {
                    "matched_case_count": replay_matches[preset],
                    "compared_case_count": len(selected_cases),
                    "match_rate": round(replay_matches[preset] / len(selected_cases), 4),
                }
                for preset in ("bm25", "dense", "hybrid", "hybrid_rerank")
            },
            "source_provenance": _source_provenance(),
            "per_case": per_case,
            "interpretation_note": (
                "Candidate/fusion variants reuse one set of per-question stage rankings to isolate ranking changes. "
                "Their request latency is not measured as a full pipeline. Stage and reranker latencies are measured directly. "
                "Metadata-filter metrics include only cases where exact values can be derived from the question and available corpus metadata."
            ),
        }
        if output_dir is not None:
            _write_json_atomic(output_dir / "results.json", results)
        return results
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval-run-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--split", choices=("development", "validation", "held_out"))
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    output_dir = args.output_dir
    if output_dir is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_dir = args.data_dir / "diagnostic_runs" / timestamp
    result = run_diagnostics(
        retrieval_run_dir=args.retrieval_run_dir,
        data_dir=args.data_dir,
        split=args.split,
        max_cases=args.max_cases,
        output_dir=output_dir,
    )
    summary = {
        "output_dir": str(output_dir),
        "case_count": result["case_count"],
        "source_candidate_metrics": result["source_candidate_metrics"],
        "p1_replay_parity": result["p1_replay_parity"],
        "stage_latency": result["stage_latency"],
        "rerank_latency": result["rerank_latency"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
