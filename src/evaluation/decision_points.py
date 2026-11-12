"""Replay independent control-plane decisions with frozen behavior labels."""

from __future__ import annotations

from itertools import zip_longest
from time import perf_counter
from typing import Any

from src.agent.complexity_router import ComplexityClass, ComplexityRouter, ExecutionPath
from src.decision.models import DecisionAction
from src.evaluation.advanced_verification_evaluation import evaluate_advanced_verification
from src.evaluation.complexity_router_evaluation import SYNTHETIC_ROUTING_CASES
from src.evaluation.decision_evaluation import evaluate_decisions
from src.evaluation.evidence_policy_benchmark import evidence_policy_scenarios
from src.policy.calibration import binary_acceptance_metrics
from src.policy.decision_backend import DeterministicDecisionBackend
from src.policy.evidence_policy import CandidateDisposition
from src.verification.models import ClaimStatus, ResponseDisposition


def _row(case_id: str, expected: bool, observed: bool) -> dict[str, Any]:
    return {"case_id": case_id, "expected": expected, "observed": observed}


def _score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "metrics": binary_acceptance_metrics(
            [row["expected"] for row in rows], [row["observed"] for row in rows]
        ),
        "cases": rows,
    }


def evaluate_decision_points() -> dict[str, Any]:
    started = perf_counter()
    router = ComplexityRouter()
    backend = DeterministicDecisionBackend()
    retrieve_rows = [
        _row(
            f"route_{index:02d}",
            label != ComplexityClass.UNSUPPORTED,
            router.route(question).selected_path != ExecutionPath.UNSUPPORTED,
        )
        for index, (label, question) in enumerate(SYNTHETIC_ROUTING_CASES, 1)
    ]
    candidate_rows = [{
        **_row(
            case.case_id, case.expected_disposition == CandidateDisposition.ACCEPT,
            backend.decide(case.features).disposition == CandidateDisposition.ACCEPT,
        ),
        "split": case.split,
        "failure_group": case.failure_group,
    } for case in evidence_policy_scenarios()]
    evidence = evaluate_decisions()["cases"]
    sufficient_rows = [
        _row(case["case_id"], case["expected_action"] == DecisionAction.ANSWER, case["coverage_sufficient"])
        for case in evidence
    ]
    retrieve_more_rows = [
        _row(
            case["case_id"], case["expected_action"] == DecisionAction.RETRIEVE_MORE,
            case["actual_action"] == DecisionAction.RETRIEVE_MORE,
        )
        for case in evidence
    ]
    verification = evaluate_advanced_verification(repeats=1)["cases"]
    supported_rows = []
    abstain_rows = []
    claim_count_mismatches = []
    withholding = {ResponseDisposition.ABSTAIN, ResponseDisposition.REJECTED}
    for case in verification:
        expected = case["expected"]
        observed = case["M11"]
        case_id = case["case_id"]
        abstain_rows.append(_row(case_id, expected["release"] in withholding, observed["release"] in withholding))
        if len(expected["claim_statuses"]) != len(observed["claim_statuses"]):
            claim_count_mismatches.append(case_id)
        for index, (gold, actual) in enumerate(
            zip_longest(expected["claim_statuses"], observed["claim_statuses"]), 1
        ):
            # An omitted check or an extra atom is a failed alignment regardless of its label.
            positive = gold == ClaimStatus.SUPPORTED
            predicted = actual == ClaimStatus.SUPPORTED if gold is not None and actual is not None else not positive
            supported_rows.append(_row(f"{case_id}:{index}", positive, predicted))
    return {
        "benchmark": "filingscope-control-plane-decisions-v1",
        "fixture_type": "authored_behavior_replay",
        "decisions": {
            "ShouldRetrieve": _score(retrieve_rows),
            "CandidateAccept": _score(candidate_rows),
            "EvidenceSufficient": _score(sufficient_rows),
            "ShouldRetrieveMore": _score(retrieve_more_rows),
            "ClaimSupported": _score(supported_rows),
            "ShouldAbstain": _score(abstain_rows),
        },
        "claim_count_mismatches": claim_count_mismatches,
        "calibration": "not_applicable_no_probabilistic_backend",
        "llm_calls": 0,
        "retrieval_calls": 0,
        "provider_cost_usd": 0,
        "wall_time_ms": round((perf_counter() - started) * 1000, 3),
    }
