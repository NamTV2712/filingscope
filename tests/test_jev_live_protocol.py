from unittest.mock import Mock

import pytest
import requests

from scripts.run_g5_groq_observer import _request
from scripts.run_g5_jev_observer import ENDPOINT, SERVED_MODEL, _jev_plan, _observe, _paired_summary


def test_jev_request_uses_the_same_evidence_and_omits_gold():
    groq = {"payload": _request("Question?", "FILING", "Excerpt."), "gold_supports_slot": True,
            "prompt_sha256": "groq-hash", "estimated_input_tokens": 500}
    row, = _jev_plan([groq])
    assert row["payload"]["state"] == {"question": "Question?", "source_document": "FILING", "page_text": "Excerpt."}
    assert "gold_supports_slot" not in row["payload"]
    assert row["groq_prompt_sha256"] == "groq-hash"
    assert row["prompt_sha256"] != "groq-hash"


@pytest.mark.parametrize("model,probability,error", [
    (SERVED_MODEL, 0.75, None),
    ("typesafe/jev-1.13", 0.75, "ValueError"),
    (SERVED_MODEL, 0.30, "ValidationError"),
])
def test_jev_response_checks_snapshot_probabilities_and_usage(model, probability, error):
    session = Mock()
    session.post.return_value = Mock(status_code=200, **{"json.return_value": {
        "model": model, "provider": "TypeSafe", "id": "gen-dec-fixture",
        "usage": {"input_tokens": 300, "output_tokens": 20, "cost": 0.0000126},
        "answers": {"relevance": {"type": "choice", "choice": "relevant", "confidence": probability,
                                  "probabilities": {"relevant": probability, "irrelevant": 0.20, "unclear": 0.05}}},
    }})
    observation, receipt = _observe(session, {})
    assert session.post.call_args.args == (ENDPOINT,)
    assert session.post.call_args.kwargs["allow_redirects"] is False
    assert receipt.get("error") == error
    assert receipt["input_tokens"] == 300 and receipt["cost_usd"] == 0.0000126
    if error:
        assert observation is None and "support_probability" not in receipt
    else:
        assert observation.relevance == "relevant" and receipt["support_probability"] == probability


def test_jev_timeout_and_calibration_denominators():
    session = Mock()
    session.post.side_effect = requests.Timeout
    observation, receipt = _observe(session, {})
    assert observation is None and receipt["error"] == "Timeout"
    relevant = {"relevance": "relevant", "provider": {"support_probability": 0.75, "cost_usd": 0.0000126},
                "gold_supports_slot": True, "baseline_supports_slot": False}
    unclear = {"relevance": "unclear", "provider": {"support_probability": 0.25}, "gold_supports_slot": False}
    summary = _paired_summary([relevant, unclear], [relevant, unclear])
    assert summary["matched_binary_predictions"] == 1
    assert summary["jev_correct"] == summary["groq_correct"] == 1
    assert summary["deterministic_support_correct"] == 0
    assert summary["probability_diagnostic"] == {"cases": 2, "bins": [0, 1, 0, 1, 0], "brier": 0.0625, "ece": 0.25}
    assert summary["reported_usage_count"] == 1
