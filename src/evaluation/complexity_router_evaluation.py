"""Synthetic routing audit and unlabeled FinanceBench route-distribution run."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
import time
import tracemalloc
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.agent.complexity_router import (
    ROUTER_VERSION,
    ComplexityClass,
    ComplexityRouter,
    ExecutionPath,
    RouterExecution,
)
from src.evaluation.financebench_dataset import FinanceBenchCase
from src.research.corpus_map import CorpusMap

EVALUATION_VERSION = "1.0.0"
_SOURCE_FILES = (
    "requirements.txt",
    "src/agent/complexity_router.py",
    "src/evaluation/complexity_router_evaluation.py",
    "scripts/run_complexity_router_evaluation.py",
)


# These are policy-behavior fixtures, not prevalence-weighted examples or
# independently annotated natural-language intent labels.
SYNTHETIC_ROUTING_CASES: tuple[tuple[ComplexityClass, str], ...] = (
    (ComplexityClass.SIMPLE_LOOKUP, "What was Apple's revenue in FY2024?"),
    (ComplexityClass.SIMPLE_LOOKUP, "What was Microsoft's operating income in FY2023?"),
    (ComplexityClass.SIMPLE_LOOKUP, "What was Amazon's net income in FY2022?"),
    (ComplexityClass.SIMPLE_LOOKUP, "What was Alphabet's diluted EPS in FY2024?"),
    (ComplexityClass.SIMPLE_LOOKUP, "What was Meta's free cash flow in FY2023?"),
    (ComplexityClass.SIMPLE_LOOKUP, "What was Nvidia's gross profit in FY2024?"),
    (ComplexityClass.SIMPLE_LOOKUP, "What was Tesla's total assets in FY2022?"),
    (ComplexityClass.SIMPLE_LOOKUP, "What were Intel's capital expenditures in FY2023?"),
    (ComplexityClass.SINGLE_DOCUMENT, "What was Apple's operating margin in the FY2024 10-K?"),
    (ComplexityClass.SINGLE_DOCUMENT, "What risks did Microsoft report in the FY2023 annual report?"),
    (ComplexityClass.SINGLE_DOCUMENT, "What business segments does Amazon list in its 10-K?"),
    (ComplexityClass.SINGLE_DOCUMENT, "According to Alphabet's FY2024 filing, what was revenue?"),
    (ComplexityClass.SINGLE_DOCUMENT, "What products are described in Meta's FY2023 annual report?"),
    (ComplexityClass.SINGLE_DOCUMENT, "What operating income appears in Nvidia's FY2024 10-K?"),
    (ComplexityClass.SINGLE_DOCUMENT, "What customer risks are described in Tesla's 10-K?"),
    (ComplexityClass.SINGLE_DOCUMENT, "What was Intel's net income in its FY2023 annual report?"),
    (ComplexityClass.NUMERICAL, "Calculate Apple's revenue growth from FY2023 to FY2024."),
    (ComplexityClass.NUMERICAL, "Compute Microsoft's operating margin difference from FY2023 to FY2024."),
    (ComplexityClass.NUMERICAL, "Calculate Amazon's net income growth between FY2022 and FY2023."),
    (ComplexityClass.NUMERICAL, "What was Alphabet's revenue increase from FY2023 to FY2024?"),
    (ComplexityClass.NUMERICAL, "Compute Meta's gross margin change from FY2022 to FY2023."),
    (ComplexityClass.NUMERICAL, "Calculate Nvidia's operating income growth from FY2023 to FY2024."),
    (ComplexityClass.NUMERICAL, "What was Tesla's total assets difference between FY2022 and FY2023?"),
    (ComplexityClass.NUMERICAL, "Calculate Intel's capital expenditures growth from FY2023 to FY2024."),
    (ComplexityClass.COMPARATIVE, "Compare Apple's and Microsoft's revenue in FY2024."),
    (ComplexityClass.COMPARATIVE, "Compare Amazon's and Alphabet's operating income in FY2023."),
    (ComplexityClass.COMPARATIVE, "Compare Meta and Nvidia gross profit in FY2024."),
    (ComplexityClass.COMPARATIVE, "Compare Tesla and Intel net income in FY2023."),
    (ComplexityClass.COMPARATIVE, "Which company had higher revenue in FY2024, Apple or Amazon?"),
    (ComplexityClass.COMPARATIVE, "Compare Microsoft's and Nvidia's operating margin in FY2023."),
    (ComplexityClass.COMPARATIVE, "Compare Alphabet and Meta free cash flow in FY2024."),
    (ComplexityClass.COMPARATIVE, "Compare Tesla's and Apple's total assets in FY2022."),
    (ComplexityClass.MULTI_HOP, "Why did Apple's operating income change from FY2023 to FY2024?"),
    (ComplexityClass.MULTI_HOP, "Explain what drove Microsoft's revenue change between FY2022 and FY2023."),
    (ComplexityClass.MULTI_HOP, "Why did Amazon's operating margin move from FY2023 to FY2024?"),
    (ComplexityClass.MULTI_HOP, "Explain the relationship between Alphabet's revenue and operating income in FY2024."),
    (ComplexityClass.MULTI_HOP, "What caused Meta's net income change between FY2022 and FY2023?"),
    (ComplexityClass.MULTI_HOP, "Trace Nvidia's operating income change from FY2023 to FY2024."),
    (ComplexityClass.MULTI_HOP, "Why did Tesla's capital expenditures affect cash flow from FY2022 to FY2023?"),
    (ComplexityClass.MULTI_HOP, "Reconcile Intel's revenue and operating income changes across FY2023 and FY2024."),
    (ComplexityClass.DEEP_RESEARCH, "Provide a comprehensive analysis of Apple's revenue, operating income, and net income from FY2021 to FY2023."),
    (ComplexityClass.DEEP_RESEARCH, "Give a thorough review of Microsoft's revenue, operating margin, and net income across FY2021 to FY2023."),
    (ComplexityClass.DEEP_RESEARCH, "Conduct an in-depth analysis of Amazon's revenue, operating income, and free cash flow from FY2021 to FY2023."),
    (ComplexityClass.DEEP_RESEARCH, "Review every available filing for Alphabet's revenue, operating income, and net income from FY2021 to FY2023."),
    (ComplexityClass.DEEP_RESEARCH, "Give a comprehensive analysis of Meta's revenue, gross profit, and net income from FY2021 to FY2023."),
    (ComplexityClass.DEEP_RESEARCH, "Provide an in-depth analysis of Nvidia's revenue, operating income, and net income from FY2021 to FY2023."),
    (ComplexityClass.DEEP_RESEARCH, "Conduct a thorough review of Tesla's revenue, operating margin, and free cash flow from FY2021 to FY2023."),
    (ComplexityClass.DEEP_RESEARCH, "Analyze all available filings for Intel's revenue, operating income, and capital expenditures from FY2021 to FY2023."),
    (ComplexityClass.UNSUPPORTED, "Forecast Apple's revenue next year."),
    (ComplexityClass.UNSUPPORTED, "Should I buy Microsoft stock based on its FY2024 revenue?"),
    (ComplexityClass.UNSUPPORTED, "What was Acme's revenue in FY2024?"),
    (ComplexityClass.UNSUPPORTED, "What was Apple's brand awareness score in FY2024?"),
    (ComplexityClass.UNSUPPORTED, "Predict Amazon's operating income for the upcoming fiscal year."),
    (ComplexityClass.UNSUPPORTED, "What was Alphabet's revenue growth in FY2024?"),
    (ComplexityClass.UNSUPPORTED, "What will Meta's operating margin be next quarter?"),
    (ComplexityClass.UNSUPPORTED, "Recommend whether to sell Tesla shares after FY2024."),
)

_EXPECTED_PATH = {
    ComplexityClass.SIMPLE_LOOKUP: ExecutionPath.FAST,
    ComplexityClass.SINGLE_DOCUMENT: ExecutionPath.FAST,
    ComplexityClass.NUMERICAL: ExecutionPath.FAST,
    ComplexityClass.COMPARATIVE: ExecutionPath.RESEARCH,
    ComplexityClass.MULTI_HOP: ExecutionPath.RESEARCH,
    ComplexityClass.DEEP_RESEARCH: ExecutionPath.RESEARCH,
    ComplexityClass.UNSUPPORTED: ExecutionPath.UNSUPPORTED,
}


def _nearest_rank(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(quantile * len(ordered)) - 1)], 4)


def _case_fingerprint(rows: Sequence[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


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
            raise FileNotFoundError(f"Cannot fingerprint router source: {filename}")
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", *_SOURCE_FILES],
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


def _usage_summary(runs: Sequence[RouterExecution]) -> dict[str, Any]:
    return {
        "planned_tasks": sum(run.planned_task_count for run in runs),
        "planned_retrieval_calls": sum(run.planned_retrieval_calls for run in runs),
        "actual_retrieval_calls": sum(run.actual_retrieval_calls for run in runs),
        "planned_llm_calls": sum(run.planned_llm_calls for run in runs),
        "actual_llm_calls": sum(run.actual_llm_calls for run in runs),
        "actual_tool_calls": sum(run.actual_tool_calls for run in runs),
        "actual_multi_agent_invocations": 0,
        "actual_tokens": sum(run.actual_tokens for run in runs),
        "estimated_cost_usd": round(sum(run.estimated_cost_usd for run in runs), 8),
        "llm_or_retrieval_execution_enabled": False,
        "agent_execution_enabled": False,
    }


def _route_distribution(runs: Sequence[RouterExecution]) -> dict[str, int]:
    return dict(sorted(Counter(run.selected_path.value for run in runs).items()))


def _reason_code_distribution(runs: Sequence[RouterExecution]) -> dict[str, int]:
    counts = Counter(
        reason_code
        for run in runs
        for reason_code in run.decision.reason_codes
    )
    return dict(sorted(counts.items()))


def _enforced_budget_violation_count(runs: Sequence[RouterExecution]) -> int:
    violations = 0
    for run in runs:
        violations += run.graph_steps_used > run.budget.max_graph_steps
        violations += run.planned_task_count > run.budget.max_planned_tasks
        violations += run.planned_retrieval_calls > run.budget.max_retrieval_calls
        violations += run.planned_llm_calls > run.budget.max_llm_calls
        violations += (
            run.planned_retrieval_calls + run.planned_llm_calls
            > run.budget.max_tool_calls
        )
        violations += run.actual_tool_calls > run.budget.max_tool_calls
        violations += run.actual_retrieval_calls > run.budget.max_retrieval_calls
        violations += run.actual_llm_calls > run.budget.max_llm_calls
        violations += run.actual_tokens > run.budget.max_context_tokens
    return violations


def evaluate_complexity_routing(
    *,
    financebench_cases: Sequence[FinanceBenchCase] | None = None,
    financebench_corpus_map: CorpusMap | None = None,
) -> dict[str, Any]:
    """Measure authored routing behavior and label-free benchmark distribution.

    FinanceBench answer labels are not read by the router or this evaluator;
    only each question string is passed to ``ComplexityRouter.route``.
    """
    trace_started = time.perf_counter()
    tracemalloc.start()
    tracemalloc.reset_peak()
    router_initialization_started = time.perf_counter()
    router = ComplexityRouter()
    corpus_aware_router = (
        ComplexityRouter(financebench_corpus_map)
        if financebench_corpus_map is not None
        else None
    )
    router_initialization_ms = max(
        0.0,
        (time.perf_counter() - router_initialization_started) * 1000,
    )

    labeled_runs: list[tuple[ComplexityClass, RouterExecution]] = []
    for expected_complexity, question in SYNTHETIC_ROUTING_CASES:
        labeled_runs.append((expected_complexity, router.route(question)))

    observed_runs: list[tuple[FinanceBenchCase, RouterExecution]] = []
    corpus_aware_runs: list[tuple[FinanceBenchCase, RouterExecution]] = []
    for case in financebench_cases or ():
        observed_runs.append((case, router.route(case.question)))
        if corpus_aware_router is not None:
            corpus_aware_runs.append((case, corpus_aware_router.route(case.question)))

    _, peak_allocated_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    evaluation_wall_time_ms = max(0.0, (time.perf_counter() - trace_started) * 1000)

    class_names = [item.value for item in ComplexityClass]
    confusion = {expected: {predicted: 0 for predicted in class_names} for expected in class_names}
    class_stats: dict[str, dict[str, float | int]] = {}
    mistakes: list[dict[str, str]] = []
    path_errors: list[dict[str, str]] = []
    expected_nonresearch = 0
    unnecessary_research = 0
    expected_research = 0
    incorrect_fast = 0
    for expected, run in labeled_runs:
        predicted = run.decision.complexity
        confusion[expected.value][predicted.value] += 1
        expected_path = _EXPECTED_PATH[expected]
        if expected_path != ExecutionPath.RESEARCH:
            expected_nonresearch += 1
            unnecessary_research += run.selected_path == ExecutionPath.RESEARCH
        else:
            expected_research += 1
            incorrect_fast += run.selected_path == ExecutionPath.FAST
        if predicted != expected:
            mistakes.append({
                "question": run.question,
                "expected_complexity": expected.value,
                "predicted_complexity": predicted.value,
                "selected_path": run.selected_path.value,
                "reason_codes": ",".join(run.decision.reason_codes),
            })
        if run.selected_path != expected_path:
            path_errors.append({
                "question": run.question,
                "expected_path": expected_path.value,
                "selected_path": run.selected_path.value,
                "expected_complexity": expected.value,
                "predicted_complexity": predicted.value,
            })

    total = len(labeled_runs)
    correct = total - len(mistakes)
    f1_values = []
    for class_name in class_names:
        tp = confusion[class_name][class_name]
        fp = sum(confusion[other][class_name] for other in class_names if other != class_name)
        fn = sum(confusion[class_name][other] for other in class_names if other != class_name)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        f1_values.append(f1)
        class_stats[class_name] = {
            "support": sum(confusion[class_name].values()),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    synthetic_runs = [run for _, run in labeled_runs]
    observed_only_runs = [run for _, run in observed_runs]
    corpus_aware_observed_runs = [run for _, run in corpus_aware_runs]
    synthetic_questions = [
        {"expected_complexity": expected.value, "question": question}
        for expected, question in SYNTHETIC_ROUTING_CASES
    ]
    financebench_questions = [
        {"case_id": case.case_id, "question": case.question}
        for case, _ in observed_runs
    ]
    timings = [
        run.routing_latency_ms
        for run in [*synthetic_runs, *observed_only_runs, *corpus_aware_observed_runs]
    ]
    all_observed = [*observed_only_runs, *corpus_aware_observed_runs]
    path_distribution = _route_distribution([*synthetic_runs, *all_observed])

    by_split_question_only: dict[str, dict[str, int]] = defaultdict(dict)
    for case, run in observed_runs:
        by_split_question_only[case.split][run.selected_path.value] = (
            by_split_question_only[case.split].get(run.selected_path.value, 0) + 1
        )
    by_split_corpus_aware: dict[str, dict[str, int]] = defaultdict(dict)
    for case, run in corpus_aware_runs:
        by_split_corpus_aware[case.split][run.selected_path.value] = (
            by_split_corpus_aware[case.split].get(run.selected_path.value, 0) + 1
        )

    return {
        "evaluation_version": EVALUATION_VERSION,
        "router_version": ROUTER_VERSION,
        "benchmark": {
            "synthetic_policy_fixture": {
                "case_count": total,
                "case_set_sha256": _case_fingerprint(synthetic_questions),
                "class_accuracy": round(correct / total, 4) if total else 0.0,
                "macro_f1": round(sum(f1_values) / len(f1_values), 4),
                "per_class": class_stats,
                "confusion_matrix": confusion,
                "selected_path_counts": _route_distribution(synthetic_runs),
                "unnecessary_research_path_selection_rate": round(
                    unnecessary_research / expected_nonresearch, 4
                ) if expected_nonresearch else 0.0,
                "incorrect_fast_path_rate": round(
                    incorrect_fast / expected_research, 4
                ) if expected_research else 0.0,
                "unsupported_routing_errors": sum(
                    (expected == ComplexityClass.UNSUPPORTED)
                    != (run.selected_path == ExecutionPath.UNSUPPORTED)
                    for expected, run in labeled_runs
                ),
                "routing_mistakes": mistakes,
                "path_mistakes": path_errors,
                "interpretation": (
                    "Hand-authored behavior fixtures validate the deterministic rules; "
                    "they are not independent semantic labels or a production prevalence sample."
                ),
            },
            "financebench_unlabeled_route_distribution": {
                "case_count": len(observed_runs),
                "question_set_sha256": _case_fingerprint(financebench_questions),
                "question_only_alias_catalog": {
                    "route_counts": _route_distribution(observed_only_runs),
                    "reason_code_counts": _reason_code_distribution(observed_only_runs),
                    "route_counts_by_split": dict(sorted(by_split_question_only.items())),
                    "routing_latency_p50_ms": _nearest_rank(
                        [run.routing_latency_ms for run in observed_only_runs], 0.50
                    ),
                    "routing_latency_p95_ms": _nearest_rank(
                        [run.routing_latency_ms for run in observed_only_runs], 0.95
                    ),
                    "usage": _usage_summary(observed_only_runs),
                },
                "corpus_map_aware": {
                    "route_counts": _route_distribution(corpus_aware_observed_runs),
                    "reason_code_counts": _reason_code_distribution(corpus_aware_observed_runs),
                    "route_counts_by_split": dict(sorted(by_split_corpus_aware.items())),
                    "routing_latency_p50_ms": _nearest_rank(
                        [run.routing_latency_ms for run in corpus_aware_observed_runs], 0.50
                    ),
                    "routing_latency_p95_ms": _nearest_rank(
                        [run.routing_latency_ms for run in corpus_aware_observed_runs], 0.95
                    ),
                    "usage": _usage_summary(corpus_aware_observed_runs),
                    "corpus_map": (
                        {
                            "index_generation_id": financebench_corpus_map.index_generation_id,
                            "document_count": len(financebench_corpus_map.documents),
                            "chunk_count": financebench_corpus_map.chunk_count,
                            "metadata_coverage": {
                                key: value.value
                                for key, value in financebench_corpus_map.metadata_coverage.items()
                            },
                        }
                        if financebench_corpus_map is not None
                        else None
                    ),
                },
                "labels_passed_to_router": False,
                "quality_labeling": "unmeasured; route distribution only; no retrieval or answer execution",
            },
        },
        "routing_distribution_all_runs": path_distribution,
        "resource_use": {
            "routing_latency_p50_ms": _nearest_rank(timings, 0.50),
            "routing_latency_p95_ms": _nearest_rank(timings, 0.95),
            "evaluation_wall_time_ms": round(evaluation_wall_time_ms, 3),
            "router_initialization_ms": round(router_initialization_ms, 3),
            "python_peak_allocated_bytes": max(0, peak_allocated_bytes),
            "process_rss_measured": False,
            "runtime_python": platform.python_version(),
            "cpu_or_gpu_model_calls": 0,
        },
        "usage": {
            "synthetic_policy_fixture": _usage_summary(synthetic_runs),
            "financebench_unlabeled_route_distribution": _usage_summary(observed_only_runs),
            "financebench_corpus_map_aware": _usage_summary(corpus_aware_observed_runs),
        },
        "route_budgets": {
            "selected_route_maxima": {
                "max_graph_steps": max((run.budget.max_graph_steps for run in [*synthetic_runs, *all_observed]), default=0),
                "max_tool_calls": max((run.budget.max_tool_calls for run in [*synthetic_runs, *all_observed]), default=0),
                "max_retrieval_calls": max((run.budget.max_retrieval_calls for run in [*synthetic_runs, *all_observed]), default=0),
                "max_llm_calls": max((run.budget.max_llm_calls for run in [*synthetic_runs, *all_observed]), default=0),
                "max_candidate_chunks": max((run.budget.max_candidate_chunks for run in [*synthetic_runs, *all_observed]), default=0),
                "max_context_tokens": max((run.budget.max_context_tokens for run in [*synthetic_runs, *all_observed]), default=0),
                "max_concurrency": max((run.budget.max_concurrency for run in [*synthetic_runs, *all_observed]), default=0),
                "max_wall_time_seconds": max((run.budget.max_wall_time_seconds for run in [*synthetic_runs, *all_observed]), default=0),
                "max_planned_tasks": max((run.budget.max_planned_tasks for run in [*synthetic_runs, *all_observed]), default=0),
            },
            "maximum_graph_steps_used": max((run.graph_steps_used for run in [*synthetic_runs, *all_observed]), default=0),
            "maximum_planned_task_count": max((run.planned_task_count for run in [*synthetic_runs, *all_observed]), default=0),
            "maximum_planned_retrieval_calls": max((run.planned_retrieval_calls for run in [*synthetic_runs, *all_observed]), default=0),
            "enforced_budget_violations": _enforced_budget_violation_count(
                [*synthetic_runs, *all_observed]
            ),
            "enforced_dimensions": [
                "graph_steps",
                "planned_tasks",
                "planned_retrieval_calls",
                "actual_tool_calls",
                "actual_llm_calls",
                "actual_context_tokens",
            ],
            "execution_milestone_enforcement_pending": [
                "candidate_chunks",
                "context_tokens",
                "concurrency",
                "wall_time_seconds",
            ],
        },
        "source_provenance": _source_provenance(),
    }


def load_router_financebench_inputs(
    data_dir: Path,
    run_dir: Path | None = None,
) -> tuple[list[FinanceBenchCase], CorpusMap, dict[str, Any]]:
    from src.evaluation.corpus_aware_planning import load_corpus_planning_inputs

    path = data_dir / "source" / "financebench_open_source.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"FinanceBench routing questions are missing: {path}")
    cases, _, corpus_map, manifest = load_corpus_planning_inputs(data_dir, run_dir)
    return cases, corpus_map, manifest


__all__ = [
    "EVALUATION_VERSION",
    "SYNTHETIC_ROUTING_CASES",
    "evaluate_complexity_routing",
    "load_router_financebench_inputs",
]
