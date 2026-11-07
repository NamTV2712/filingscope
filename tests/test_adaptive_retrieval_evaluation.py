from src.evaluation.adaptive_retrieval_evaluation import evaluate_adaptive_retrieval


def test_fixed_adaptive_retrieval_evaluation_matches_expected_outcomes() -> None:
    report = evaluate_adaptive_retrieval()

    assert report["case_count"] == 9
    assert report["action_accuracy"] == 1.0
    assert report["stop_reason_accuracy"] == 1.0
    assert report["multi_hop_completed"] == 2
    assert report["multi_hop_completion_rate"] == 1.0
    assert report["no_progress_detected"] == 2
    assert report["no_progress_detection_rate"] == 1.0
