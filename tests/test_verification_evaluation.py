from src.evaluation.verification_evaluation import evaluate_verifications, verification_scenarios


def test_verification_scenarios_are_unique_and_cover_core_outcomes() -> None:
    scenarios = verification_scenarios()

    assert len({scenario.case_id for scenario in scenarios}) == len(scenarios)
    assert {scenario.expected_disposition.value for scenario in scenarios} == {
        "VERIFIED", "PARTIAL", "REJECTED", "ABSTAIN"
    }
    assert {scenario.expected_claim_status.value for scenario in scenarios if scenario.expected_claim_status} == {
        "SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "UNVERIFIABLE"
    }


def test_fixed_verification_evaluation_matches_hand_labeled_cases() -> None:
    report = evaluate_verifications()

    assert report["case_count"] == 15
    assert report["disposition_correct"] == 15
    assert report["disposition_accuracy"] == 1.0
    assert report["claim_status_labeled_cases"] == 14
    assert report["claim_status_correct"] == 14
    assert report["claim_status_accuracy"] == 1.0
