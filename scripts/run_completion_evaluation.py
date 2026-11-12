"""Replay all six decision points and plot-ready risk/coverage operating points."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.run_retrieval_diagnostics import _write_json_atomic
from src.evaluation.decision_points import evaluate_decision_points


DEFAULT_ABLATION = Path("data/financebench/ablation_runs/m13-results.json")
THRESHOLDS = {
    "all_rendered": None,
    "partial_or_verified": frozenset({"PARTIAL", "VERIFIED"}),
    "verified_only": frozenset({"VERIFIED"}),
    "withhold_all": frozenset(),
}


def risk_coverage_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        raise ValueError("Risk coverage requires labeled cases")
    answerable = sum(row["answerable"] for row in rows)
    points = []
    for name, dispositions in THRESHOLDS.items():
        released = [
            row for row in rows
            if row["answered"] and (dispositions is None or row["disposition"] in dispositions)
        ]
        errors = sum(not row["grounded_exact"] for row in released)
        released_answerable = sum(row["answerable"] for row in released)
        points.append({
            "threshold": name,
            "case_count": len(rows),
            "released": len(released),
            "errors": errors,
            "coverage": len(released) / len(rows),
            "risk": errors / len(released) if released else None,
            "correct_abstentions": len(rows) - answerable - (len(released) - released_answerable),
            "false_abstentions": answerable - released_answerable,
        })
    return points


def risk_coverage_report(path: Path) -> dict[str, Any]:
    source = path.read_bytes()
    ablation = json.loads(source)
    variants = {}
    for variant, record in ablation["variants"].items():
        rows = record["per_case"]
        splits = sorted({row["split"] for row in rows})
        variants[variant] = {
            "overall": risk_coverage_points(rows),
            "splits": {
                split: risk_coverage_points([row for row in rows if row["split"] == split])
                for split in splits
            },
        }
    return {
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "ranking_signal": "verifier_disposition",
        "error": "released_response_is_not_grounded_exact",
        "variants": variants,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ablation", type=Path, default=DEFAULT_ABLATION)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    decisions = evaluate_decision_points()
    report = {"decision_benchmark": decisions, "risk_coverage": risk_coverage_report(args.ablation)}
    _write_json_atomic(args.output, report)
    print(json.dumps({key: value["metrics"] for key, value in decisions["decisions"].items()}, indent=2))
    print(args.output)


if __name__ == "__main__":
    main()
