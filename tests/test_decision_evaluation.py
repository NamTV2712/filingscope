from src.evaluation.decision_evaluation import decision_scenarios, evaluate_decisions


def test_decision_scenario_labels_are_unique_and_cover_all_actions() -> None:
    scenarios = decision_scenarios()

    assert len({scenario.case_id for scenario in scenarios}) == len(scenarios)
    assert {scenario.expected_action.value for scenario in scenarios} == {
        "ANSWER", "RETRIEVE_MORE", "ABSTAIN"
    }


def test_fixed_decision_evaluation_matches_frozen_scenario_labels() -> None:
    report = evaluate_decisions()

    assert report["case_count"] == 15
    assert report["action_correct"] == 15
    assert report["action_accuracy"] == 1.0
    assert report["reason_correct"] == 15
    assert report["reason_accuracy"] == 1.0
