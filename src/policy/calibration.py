"""Metrics for candidate acceptance and optional calibrated probabilities."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def binary_acceptance_metrics(
    expected_accept: Sequence[bool],
    predicted_accept: Sequence[bool],
) -> dict[str, Any]:
    """Measure acceptance quality; WEAK/REJECT both count as not accepted."""
    if len(expected_accept) != len(predicted_accept):
        raise ValueError("expected_accept and predicted_accept lengths must match")
    if len(expected_accept) == 0:
        raise ValueError("acceptance metrics require at least one case")

    true_positive = false_positive = true_negative = false_negative = 0
    for expected, predicted in zip(expected_accept, predicted_accept, strict=True):
        if expected and predicted:
            true_positive += 1
        elif not expected and predicted:
            false_positive += 1
        elif not expected and not predicted:
            true_negative += 1
        else:
            false_negative += 1

    accepted = true_positive + false_positive
    positives = true_positive + false_negative
    negatives = false_positive + true_negative
    return {
        "case_count": len(expected_accept),
        "accuracy": (true_positive + true_negative) / len(expected_accept),
        "precision": true_positive / accepted if accepted else None,
        "recall": true_positive / positives if positives else None,
        "false_accept_rate": false_positive / negatives if negatives else None,
        "false_reject_rate": false_negative / positives if positives else None,
        "confusion": {
            "true_accept": true_positive,
            "false_accept": false_positive,
            "true_reject": true_negative,
            "false_reject": false_negative,
        },
    }


def probability_calibration_metrics(
    probabilities: Sequence[float],
    outcomes: Sequence[bool],
    *,
    bins: int = 10,
) -> dict[str, Any]:
    """Compute Brier score and fixed-width ECE for actual probabilities only."""
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes lengths must match")
    if len(probabilities) == 0:
        raise ValueError("calibration metrics require at least one probability")
    if bins < 1:
        raise ValueError("bins must be positive")
    if any(not 0.0 <= probability <= 1.0 for probability in probabilities):
        raise ValueError("probabilities must lie in [0, 1]")

    brier = sum(
        (probability - int(outcome)) ** 2
        for probability, outcome in zip(probabilities, outcomes, strict=True)
    ) / len(probabilities)
    bucketed: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for probability, outcome in zip(probabilities, outcomes, strict=True):
        index = min(bins - 1, int(probability * bins))
        bucketed[index].append((probability, outcome))

    reliability = []
    ece = 0.0
    for index, values in enumerate(bucketed):
        if not values:
            continue
        mean_probability = sum(probability for probability, _ in values) / len(values)
        observed_rate = sum(int(outcome) for _, outcome in values) / len(values)
        weight = len(values) / len(probabilities)
        ece += weight * abs(mean_probability - observed_rate)
        reliability.append({
            "bin_index": index,
            "lower_bound": index / bins,
            "upper_bound": (index + 1) / bins,
            "count": len(values),
            "mean_probability": mean_probability,
            "observed_rate": observed_rate,
        })
    return {
        "case_count": len(probabilities),
        "bin_count": bins,
        "brier_score": brier,
        "expected_calibration_error": ece,
        "reliability_bins": reliability,
    }


__all__ = ["binary_acceptance_metrics", "probability_calibration_metrics"]
