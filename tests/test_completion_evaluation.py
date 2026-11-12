from scripts.run_completion_evaluation import risk_coverage_points
from src.evaluation.decision_points import evaluate_decision_points


def test_decision_benchmark_covers_all_six_labeled_gates() -> None:
    report = evaluate_decision_points()
    assert not report["claim_count_mismatches"]
    assert report["llm_calls"] == report["retrieval_calls"] == 0
    assert {key: row["metrics"]["case_count"] for key, row in report["decisions"].items()} == {
        "ShouldRetrieve": 56,
        "CandidateAccept": 60,
        "EvidenceSufficient": 15,
        "ShouldRetrieveMore": 15,
        "ClaimSupported": 19,
        "ShouldAbstain": 16,
    }
    for row in report["decisions"].values():
        metrics = row["metrics"]
        assert metrics["confusion"]["true_accept"] > 0
        assert metrics["confusion"]["true_reject"] > 0
        assert metrics["accuracy"] == metrics["precision"] == metrics["recall"] == 1
        assert metrics["false_accept_rate"] == metrics["false_reject_rate"] == 0


def test_risk_uses_grounded_errors_among_releases_and_tracks_abstention() -> None:
    rows = [
        {"answered": True, "disposition": "VERIFIED", "grounded_exact": True, "answerable": True},
        {"answered": True, "disposition": "PARTIAL", "grounded_exact": False, "answerable": True},
        {"answered": True, "disposition": "ABSTAIN", "grounded_exact": False, "answerable": False},
        {"answered": False, "disposition": "ABSTAIN", "grounded_exact": False, "answerable": True},
    ]
    all_rendered, partial, verified, withheld = risk_coverage_points(rows)
    assert [item["coverage"] for item in (all_rendered, partial, verified, withheld)] == [0.75, 0.5, 0.25, 0]
    assert [item["risk"] for item in (all_rendered, partial, verified, withheld)] == [2 / 3, 0.5, 0, None]
    assert partial["correct_abstentions"] == 1
    assert verified["false_abstentions"] == 2
    assert withheld["false_abstentions"] == 3
