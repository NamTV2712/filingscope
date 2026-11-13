"""Run the CI test and fixture evaluation steps with outbound sockets guarded."""

from __future__ import annotations

import pytest

from configs.offline_guard import offline_socket_guard


def main() -> int:
    with offline_socket_guard():
        status = pytest.main(["-q", "-ra", "-m", "not live_network", "tests"])
        if status:
            return int(status)
        from src.evaluation.verification_evaluation import evaluate_verifications

        report = evaluate_verifications()
        expected = {"disposition_accuracy": 1.0, "claim_status_accuracy": 1.0}
        observed = {key: report[key] for key in expected}
        print(f"Deterministic claim/citation evaluation: {observed}")
        if observed != expected:
            print("Run python -m scripts.run_verification_evaluation to inspect per-scenario results.")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
