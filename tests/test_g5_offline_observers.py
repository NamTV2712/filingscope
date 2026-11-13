from scripts.run_g5_offline_observers import evaluate


def test_offline_observer_ablation_preserves_hard_rejections():
    result = evaluate()
    assert result["status"] == "API_VALIDATION_BLOCKED"
    assert result["provider_calls"] == result["provider_tokens"] == result["provider_cost_usd"] == 0
    arms = result["arms"]
    assert {name: row["correct"] for name, row in arms.items()} == {
        "deterministic": 60, "mock_positive": 60, "mock_negative": 40, "mock_timeout": 60,
    }
    assert arms["mock_negative"]["accept_downgrades"] == 20
    assert arms["mock_timeout"]["simulated_timeouts"] == 60
    assert all(row["critical_false_accepts"] == row["false_rejects"] == 0 for row in arms.values())
    assert arms["deterministic"]["rows"] == arms["mock_timeout"]["rows"] == arms["mock_positive"]["rows"]
