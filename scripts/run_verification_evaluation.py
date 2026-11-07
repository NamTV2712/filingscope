"""Run the deterministic P4 claim and citation verification evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from src.evaluation.verification_evaluation import evaluate_verifications


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for a JSON result (local evaluation artifacts are git-ignored).",
    )
    args = parser.parse_args(argv)

    report = evaluate_verifications()
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["disposition_accuracy"] == 1.0 and report["claim_status_accuracy"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
