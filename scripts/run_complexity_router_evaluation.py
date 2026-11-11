"""Evaluate deterministic FAST/RESEARCH complexity routing behavior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.evaluation.complexity_router_evaluation import (
    evaluate_complexity_routing,
    load_router_financebench_inputs,
)

DEFAULT_OUTPUT = Path("data/financebench/router_runs/m5-complexity-routing-v1.json")


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
    parser.add_argument("--data-dir", type=Path, default=Path("data/financebench"))
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--skip-financebench",
        action="store_true",
        help="Run only the synthetic route-rule audit when the private local dataset is unavailable.",
    )
    args = parser.parse_args()

    if args.skip_financebench:
        cases, corpus_map = None, None
    else:
        cases, corpus_map, _ = load_router_financebench_inputs(args.data_dir, args.run_dir)
    result = evaluate_complexity_routing(
        financebench_cases=cases,
        financebench_corpus_map=corpus_map,
    )
    _write_json(args.output, result)
    summary = {
        "output": str(args.output),
        "benchmark": result["benchmark"],
        "routing_distribution_all_runs": result["routing_distribution_all_runs"],
        "resource_use": result["resource_use"],
        "usage": result["usage"],
        "route_budgets": result["route_budgets"],
        "source_provenance": result["source_provenance"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
