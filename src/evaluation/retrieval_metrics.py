"""Document-page retrieval metrics with duplicate-page collapse."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from src.evaluation.financebench_dataset import FinanceBenchCase


def _retrieved_page(item: Mapping[str, Any]) -> tuple[str, int] | None:
    doc_name = item.get("doc_name")
    page_number = item.get("page_number")
    if not isinstance(doc_name, str) or isinstance(page_number, bool) or not isinstance(page_number, int):
        return None
    return doc_name, page_number


def _reciprocal_rank_at_k(
    ranked_pages: list[tuple[str, int] | None],
    gold_pages: set[tuple[str, int]],
    k: int,
) -> float:
    for rank, page in enumerate(ranked_pages[:k], start=1):
        if page in gold_pages:
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(
    ranked_pages: list[tuple[str, int] | None],
    gold_pages: set[tuple[str, int]],
    k: int,
) -> float:
    seen: set[tuple[str, int]] = set()
    dcg = 0.0
    for rank, page in enumerate(ranked_pages[:k], start=1):
        if page in gold_pages and page not in seen:
            dcg += 1.0 / math.log2(rank + 1)
            seen.add(page)
    ideal_relevant = min(k, len(gold_pages))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_relevant + 1))
    return dcg / idcg if idcg else 0.0


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def evaluate_retrieval(
    cases: Iterable[FinanceBenchCase],
    predictions: Mapping[str, list[Mapping[str, Any]]],
    latencies_ms: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    case_list = list(cases)
    if not case_list:
        raise ValueError("Cannot evaluate an empty case set")
    latencies = latencies_ms or {}
    case_metrics = []
    for case in case_list:
        ranked = [_retrieved_page(item) for item in predictions.get(case.case_id, [])]
        gold = {(case.doc_name, page) for page in case.gold_pages}
        relevant_at_5 = {page for page in ranked[:5] if page in gold}
        relevant_at_10 = {page for page in ranked[:10] if page in gold}
        case_metrics.append(
            {
                "case_id": case.case_id,
                "split": case.split,
                "question_type": case.question_type,
                "recall_at_5": len(relevant_at_5) / len(gold),
                "recall_at_10": len(relevant_at_10) / len(gold),
                "mrr_at_10": _reciprocal_rank_at_k(ranked, gold, 10),
                "ndcg_at_5": _ndcg_at_k(ranked, gold, 5),
                "all_evidence_pages_at_5": float(gold.issubset(relevant_at_5)),
                "all_evidence_pages_at_10": float(gold.issubset(relevant_at_10)),
                "latency_ms": float(latencies.get(case.case_id, 0.0)),
            }
        )

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"case_count": 0}
        average = lambda key: round(sum(row[key] for row in rows) / len(rows), 4)
        return {
            "case_count": len(rows),
            "Recall@5": average("recall_at_5"),
            "Recall@10": average("recall_at_10"),
            "MRR@10": average("mrr_at_10"),
            "nDCG@5": average("ndcg_at_5"),
            "AllEvidencePages@5": average("all_evidence_pages_at_5"),
            "AllEvidencePages@10": average("all_evidence_pages_at_10"),
            "latency_ms_p50": round(_nearest_rank([row["latency_ms"] for row in rows], 0.50), 3),
            "latency_ms_p95": round(_nearest_rank([row["latency_ms"] for row in rows], 0.95), 3),
        }

    split_names = ("development", "validation", "held_out")
    by_split = {
        split: summarize([row for row in case_metrics if row["split"] == split])
        for split in split_names
    }
    failures_by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"cases": 0, "miss_at_10": 0})
    for row in case_metrics:
        failure = failures_by_type[row["question_type"]]
        failure["cases"] += 1
        failure["miss_at_10"] += int(row["recall_at_10"] == 0)
    return {
        "overall": summarize(case_metrics),
        "by_split": by_split,
        "failures_by_question_type": dict(sorted(failures_by_type.items())),
        "case_metrics": case_metrics,
    }
