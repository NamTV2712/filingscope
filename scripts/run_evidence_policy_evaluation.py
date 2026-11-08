"""Run the versioned evidence-candidate policy benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.evaluation.evidence_policy_evaluation import evaluate_evidence_policy

DEFAULT_OUTPUT = Path("data/decision_evaluation/m3-evidence-policy-v1.json")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    result = evaluate_evidence_policy()
    _write_json(args.output, result)
    summary = {
        "output": str(args.output),
        "benchmark": result["benchmark"],
        "case_count": result["case_count"],
        "split_counts": result["split_counts"],
        "policy_config": result["policy_config"],
        "by_split": result["by_split"],
        "probability_calibration": result["probability_calibration"]["status"],
        "provider_calls": result["provider_calls"],
        "source_provenance": result["source_provenance"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
