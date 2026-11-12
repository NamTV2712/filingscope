"""Run the controlled P4 and M11 verifier replay on fixed draft answers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.evaluation.advanced_verification_evaluation import evaluate_advanced_verification


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=20)
    args = parser.parse_args()
    report = evaluate_advanced_verification(repeats=args.repeats)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    advanced = report["summary"]["M11"]
    return int(any(advanced[key] != report["case_count"] for key in (
        "exact_draft_claim_status_sequences", "expected_release_dispositions", "expected_correction_counts",
    )))


if __name__ == "__main__":
    raise SystemExit(main())
