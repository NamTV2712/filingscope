"""Evaluate the versioned candidate Evidence Policy on fixed synthetic labels."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.evaluation.evidence_policy_benchmark import (
    BENCHMARK_ID,
    BENCHMARK_VERSION,
    EvidencePolicyScenario,
    evidence_policy_scenarios,
)
from src.policy.calibration import binary_acceptance_metrics, probability_calibration_metrics
from src.policy.decision_backend import DeterministicDecisionBackend
from src.policy.evidence_policy import (
    CandidateDisposition,
    EvidencePolicyConfig,
    EvidencePolicyDecision,
)

_POLICY_SCORE_GRID = (0.35, 0.45, 0.50)
_CONFIDENCE_SCORE_GRID = (0.15, 0.20, 0.25)
_POLICY_FALSE_ACCEPT_LIMIT = 0.05
_SCORE_ONLY_FALSE_ACCEPT_LIMIT = 0.10


def _nearest_rank(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, int(math.ceil(quantile * len(ordered))) - 1)
    return round(ordered[index], 4)


def _binary_metrics_for_decisions(
    cases: list[EvidencePolicyScenario],
    decisions: list[bool],
) -> dict[str, Any]:
    return binary_acceptance_metrics(
        [case.expected_disposition == CandidateDisposition.ACCEPT for case in cases],
        decisions,
    )


def _policy_disposition_metrics(
    cases: list[EvidencePolicyScenario],
    decisions: list[EvidencePolicyDecision],
) -> dict[str, Any]:
    labels = tuple(action.value for action in CandidateDisposition)
    matrix = {expected: {predicted: 0 for predicted in labels} for expected in labels}
    exact = reason_exact = 0
    by_disposition: dict[str, dict[str, int]] = {}
    for case, decision in zip(cases, decisions, strict=True):
        expected = case.expected_disposition.value
        predicted = decision.disposition.value
        matrix[expected][predicted] += 1
        exact += int(expected == predicted)
        expected_reasons = tuple(case.expected_reason_codes)
        predicted_reasons = tuple(reason.value for reason in decision.reason_codes)
        reason_exact += int(expected_reasons == predicted_reasons)
        counts = by_disposition.setdefault(expected, {"case_count": 0, "correct": 0})
        counts["case_count"] += 1
        counts["correct"] += int(expected == predicted)
    return {
        "case_count": len(cases),
        "disposition_accuracy": exact / len(cases) if cases else 0.0,
        "reason_code_agreement": reason_exact / len(cases) if cases else 0.0,
        "confusion_matrix": matrix,
        "by_expected_disposition": {
            name: {
                **counts,
                "accuracy": counts["correct"] / counts["case_count"] if counts["case_count"] else 0.0,
            }
            for name, counts in sorted(by_disposition.items())
        },
    }


def _select_policy_config(cases: list[EvidencePolicyScenario]) -> tuple[EvidencePolicyConfig, dict[str, Any]]:
    development = [case for case in cases if case.split == "development"]
    if not development:
        raise ValueError("policy threshold selection requires development cases")
    trials = []
    for semantic_threshold in _POLICY_SCORE_GRID:
        for confidence_threshold in _CONFIDENCE_SCORE_GRID:
            config = EvidencePolicyConfig(
                minimum_semantic_relevance=semantic_threshold,
                minimum_retrieval_confidence=confidence_threshold,
            )
            backend = DeterministicDecisionBackend(config)
            decisions = [backend.decide(case.features) for case in development]
            disposition_metrics = _policy_disposition_metrics(development, decisions)
            acceptance_metrics = _binary_metrics_for_decisions(
                development,
                [decision.disposition == CandidateDisposition.ACCEPT for decision in decisions],
            )
            trials.append({
                "config": config,
                "disposition_accuracy": disposition_metrics["disposition_accuracy"],
                "reason_code_agreement": disposition_metrics["reason_code_agreement"],
                "false_accept_rate": acceptance_metrics["false_accept_rate"],
                "false_reject_rate": acceptance_metrics["false_reject_rate"],
            })
    eligible = [
        trial for trial in trials
        if (trial["false_accept_rate"] or 0.0) <= _POLICY_FALSE_ACCEPT_LIMIT
    ]
    if not eligible:
        raise ValueError("no policy threshold configuration met the development false-accept limit")
    selected = max(eligible, key=lambda trial: (
        trial["disposition_accuracy"],
        trial["reason_code_agreement"],
        -(trial["false_reject_rate"] or 0.0),
        trial["config"].minimum_semantic_relevance,
        trial["config"].minimum_retrieval_confidence,
    ))
    summary = {
        "selection_split": "development",
        "false_accept_rate_limit": _POLICY_FALSE_ACCEPT_LIMIT,
        "trial_count": len(trials),
        "selected_development_disposition_accuracy": selected["disposition_accuracy"],
        "selected_development_reason_code_agreement": selected["reason_code_agreement"],
        "selected_development_false_accept_rate": selected["false_accept_rate"],
        "selected_development_false_reject_rate": selected["false_reject_rate"],
    }
    return selected["config"], summary


def _select_score_only_threshold(cases: list[EvidencePolicyScenario]) -> tuple[float, dict[str, Any]]:
    development = [case for case in cases if case.split == "development"]
    if not development:
        raise ValueError("score-only threshold selection requires development cases")
    scores = [case.features.semantic_relevance.score for case in development]
    thresholds = sorted({0.0, 1.0, *scores, math.nextafter(max(scores), math.inf)})
    trials = []
    for threshold in thresholds:
        predictions = [score >= threshold for score in scores]
        metrics = _binary_metrics_for_decisions(development, predictions)
        if (metrics["false_accept_rate"] or 0.0) <= _SCORE_ONLY_FALSE_ACCEPT_LIMIT:
            trials.append({"threshold": threshold, "metrics": metrics})
    if not trials:
        raise ValueError("no score-only threshold met the development false-accept limit")
    selected = max(trials, key=lambda trial: (
        trial["metrics"]["recall"] or 0.0,
        -(trial["metrics"]["false_accept_rate"] or 0.0),
        trial["threshold"],
    ))
    return selected["threshold"], {
        "selection_split": "development",
        "baseline": "semantic_relevance_score_only",
        "false_accept_rate_limit": _SCORE_ONLY_FALSE_ACCEPT_LIMIT,
        "selected_development_metrics": selected["metrics"],
    }


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
        "src/policy/evidence_features.py",
        "src/policy/evidence_policy.py",
        "src/policy/decision_backend.py",
        "src/policy/calibration.py",
        "src/evaluation/evidence_policy_benchmark.py",
        "src/evaluation/evidence_policy_evaluation.py",
        "scripts/run_evidence_policy_evaluation.py",
    )
    digest = hashlib.sha256()
    for filename in files:
        path = Path(filename)
        if not path.is_file():
            raise FileNotFoundError(f"Cannot fingerprint policy source: {filename}")
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


def evaluate_evidence_policy(
    cases: tuple[EvidencePolicyScenario, ...] | None = None,
) -> dict[str, Any]:
    """Tune policy and score-only thresholds on development; freeze both later."""
    scenarios = list(cases or evidence_policy_scenarios())
    if not scenarios:
        raise ValueError("evidence policy evaluation requires at least one case")
    case_ids = [case.case_id for case in scenarios]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("evidence policy benchmark case IDs must be unique")
    split_names = {case.split for case in scenarios}
    if not split_names.issubset({"development", "validation", "held_out"}):
        raise ValueError("evidence policy benchmark contains an unsupported split")

    policy_config, policy_selection = _select_policy_config(scenarios)
    score_threshold, score_selection = _select_score_only_threshold(scenarios)
    backend = DeterministicDecisionBackend(policy_config)
    split_scenarios = {
        split: [case for case in scenarios if case.split == split]
        for split in ("development", "validation", "held_out")
    }
    per_case: list[dict[str, Any]] = []
    split_results: dict[str, Any] = {}
    latency_ms: list[float] = []
    all_decisions: list[EvidencePolicyDecision] = []
    all_cases: list[EvidencePolicyScenario] = []
    failure_group_results: dict[str, dict[str, Any]] = {}

    for split, rows in split_scenarios.items():
        if not rows:
            continue
        decisions = []
        score_predictions = []
        for case in rows:
            started = time.perf_counter()
            decision = backend.decide(case.features)
            latency_ms.append(max(0.0, (time.perf_counter() - started) * 1000))
            decisions.append(decision)
            all_decisions.append(decision)
            all_cases.append(case)
            score_accept = case.features.semantic_relevance.score >= score_threshold
            score_predictions.append(score_accept)
            predicted_reasons = [reason.value for reason in decision.reason_codes]
            is_policy_correct = decision.disposition == case.expected_disposition
            is_reason_correct = tuple(predicted_reasons) == case.expected_reason_codes
            per_case.append({
                "case_id": case.case_id,
                "split": case.split,
                "failure_group": case.failure_group,
                "expected_disposition": case.expected_disposition.value,
                "policy_disposition": decision.disposition.value,
                "expected_reason_codes": list(case.expected_reason_codes),
                "policy_reason_codes": predicted_reasons,
                "policy_disposition_correct": is_policy_correct,
                "reason_code_correct": is_reason_correct,
                "score_only_accept": score_accept,
                "semantic_relevance_score": case.features.semantic_relevance.score,
            })
            group = failure_group_results.setdefault(case.failure_group, {
                "case_count": 0,
                "expected_disposition_counts": Counter(),
                "policy_correct_count": 0,
                "score_only_accept_count": 0,
            })
            group["case_count"] += 1
            group["expected_disposition_counts"][case.expected_disposition.value] += 1
            group["policy_correct_count"] += int(is_policy_correct)
            group["score_only_accept_count"] += int(score_accept)

        policy_accept_predictions = [
            decision.disposition == CandidateDisposition.ACCEPT
            for decision in decisions
        ]
        split_results[split] = {
            "case_count": len(rows),
            "candidate_acceptance": _binary_metrics_for_decisions(rows, policy_accept_predictions),
            "policy_dispositions": _policy_disposition_metrics(rows, decisions),
            "score_only_baseline": _binary_metrics_for_decisions(rows, score_predictions),
        }

    overall_policy_accept = [
        decision.disposition == CandidateDisposition.ACCEPT
        for decision in all_decisions
    ]
    overall_score_accept = [
        case.features.semantic_relevance.score >= score_threshold
        for case in all_cases
    ]
    calibration_rows = [
        (decision.acceptance_probability, case.expected_disposition == CandidateDisposition.ACCEPT)
        for case, decision in zip(all_cases, all_decisions, strict=True)
        if decision.acceptance_probability is not None
    ]
    if calibration_rows and len(calibration_rows) == len(all_cases):
        calibration_status = {
            "status": "measured",
            "metrics": probability_calibration_metrics(
                [float(probability) for probability, _ in calibration_rows],
                [outcome for _, outcome in calibration_rows],
            ),
        }
    elif calibration_rows:
        calibration_status = {"status": "incomplete_probability_outputs", "metrics": None}
    else:
        calibration_status = {
            "status": "not_applicable_no_probabilistic_backend",
            "metrics": None,
        }

    return {
        "schema_version": 1,
        "benchmark": BENCHMARK_ID,
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "case_count": len(scenarios),
        "split_counts": {
            split: len(rows) for split, rows in split_scenarios.items() if rows
        },
        "label_counts": dict(Counter(case.expected_disposition.value for case in scenarios)),
        "provider_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_provider_cost_usd": 0.0,
        "threshold_selection": {
            "policy": {
                **policy_selection,
                "selected_policy_version": policy_config.policy_version,
                "selected_minimum_semantic_relevance": policy_config.minimum_semantic_relevance,
                "selected_minimum_retrieval_confidence": policy_config.minimum_retrieval_confidence,
            },
            "score_only_baseline": {
                **score_selection,
                "selected_semantic_relevance_threshold": score_threshold,
            },
        },
        "policy_config": policy_config.model_dump(mode="json"),
        "overall": {
            "candidate_acceptance": _binary_metrics_for_decisions(all_cases, overall_policy_accept),
            "policy_dispositions": _policy_disposition_metrics(all_cases, all_decisions),
            "score_only_baseline": _binary_metrics_for_decisions(all_cases, overall_score_accept),
            "policy_decision_latency_ms": {
                "p50": _nearest_rank(latency_ms, 0.50),
                "p95": _nearest_rank(latency_ms, 0.95),
                "case_count": len(latency_ms),
            },
        },
        "by_split": split_results,
        "by_failure_group": {
            name: {
                "case_count": values["case_count"],
                "expected_disposition_counts": dict(values["expected_disposition_counts"]),
                "policy_disposition_accuracy": values["policy_correct_count"] / values["case_count"],
                "score_only_accept_count": values["score_only_accept_count"],
            }
            for name, values in sorted(failure_group_results.items())
        },
        "probability_calibration": calibration_status,
        "per_case": per_case,
        "runtime_environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "source_provenance": _source_provenance(),
        "interpretation_note": (
            "Labels are fixed hand-authored synthetic feature cases, not real financial documents. "
            "The held-out split measures deterministic replay on unseen fixture cases only. "
            "The semantic relevance baseline is an uncalibrated score and is not used as a probability."
        ),
    }


__all__ = ["evaluate_evidence_policy"]
