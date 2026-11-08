import pytest

from src.policy.calibration import (
    binary_acceptance_metrics,
    probability_calibration_metrics,
)


def test_binary_acceptance_metrics_report_false_accept_and_false_reject() -> None:
    metrics = binary_acceptance_metrics(
        expected_accept=[True, True, False, False],
        predicted_accept=[True, False, True, False],
    )

    assert metrics["accuracy"] == 0.5
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["false_accept_rate"] == 0.5
    assert metrics["false_reject_rate"] == 0.5
    assert metrics["confusion"] == {
        "true_accept": 1,
        "false_accept": 1,
        "true_reject": 1,
        "false_reject": 1,
    }


def test_calibration_metrics_compute_brier_ece_and_reliability_bins() -> None:
    metrics = probability_calibration_metrics(
        probabilities=[0.9, 0.2],
        outcomes=[True, False],
        bins=10,
    )

    assert metrics["brier_score"] == pytest.approx(0.025)
    assert metrics["expected_calibration_error"] == pytest.approx(0.15)
    assert metrics["case_count"] == 2
    assert len(metrics["reliability_bins"]) == 2


def test_calibration_metrics_validate_inputs() -> None:
    with pytest.raises(ValueError, match="lengths must match"):
        probability_calibration_metrics([0.5], [True, False])
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        probability_calibration_metrics([1.1], [True])
    with pytest.raises(ValueError, match="bins must be positive"):
        probability_calibration_metrics([0.5], [True], bins=0)
