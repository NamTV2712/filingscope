from dataclasses import replace

from src.evaluation.evidence_policy_benchmark import (
    BENCHMARK_ID,
    evidence_policy_scenarios,
)
from src.evaluation.evidence_policy_evaluation import evaluate_evidence_policy
from src.policy.evidence_features import ScoreObservation


def test_evidence_policy_benchmark_has_fixed_balanced_labels_and_splits() -> None:
    cases = evidence_policy_scenarios()

    assert len(cases) == 60
    assert len({case.case_id for case in cases}) == 60
    assert {case.expected_disposition.value for case in cases} == {"ACCEPT", "WEAK", "REJECT"}
    assert {split: sum(case.split == split for case in cases) for split in {case.split for case in cases}} == {
        "development": 24,
        "validation": 18,
        "held_out": 18,
    }


def test_evidence_policy_evaluation_freezes_development_thresholds_and_improves_heldout() -> None:
    report = evaluate_evidence_policy()

    assert report["benchmark"] == BENCHMARK_ID
    assert report["provider_calls"] == 0
    assert report["input_tokens"] == 0
    assert report["split_counts"] == {
        "development": 24,
        "validation": 18,
        "held_out": 18,
    }
    assert report["threshold_selection"]["policy"]["selection_split"] == "development"
    assert report["threshold_selection"]["score_only_baseline"]["selection_split"] == "development"

    held_out = report["by_split"]["held_out"]
    policy = held_out["candidate_acceptance"]
    baseline = held_out["score_only_baseline"]
    assert held_out["policy_dispositions"]["disposition_accuracy"] == 1.0
    assert held_out["policy_dispositions"]["reason_code_agreement"] == 1.0
    assert policy["false_accept_rate"] == 0.0
    assert policy["false_reject_rate"] == 0.0
    assert baseline["false_reject_rate"] > policy["false_reject_rate"]
    assert baseline["false_accept_rate"] > policy["false_accept_rate"]
    assert report["probability_calibration"]["status"] == "not_applicable_no_probabilistic_backend"
    assert report["probability_calibration"]["metrics"] is None


def test_heldout_label_changes_do_not_change_development_selected_thresholds() -> None:
    cases = evidence_policy_scenarios()
    held_out_case = next(case for case in cases if case.split == "held_out")
    changed_features = held_out_case.features.model_copy(update={
        "semantic_relevance": ScoreObservation(
            score=1.0,
            observer_id="modified-heldout",
            observer_version="test",
        ),
    })
    changed = replace(
        held_out_case,
        features=changed_features,
        expected_disposition=held_out_case.expected_disposition,
    )
    changed_cases = tuple(changed if case.case_id == held_out_case.case_id else case for case in cases)

    original = evaluate_evidence_policy(cases)
    updated = evaluate_evidence_policy(changed_cases)
    assert original["threshold_selection"] == updated["threshold_selection"]
