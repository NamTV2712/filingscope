"""Compare question-only and Corpus Map conditioned query planning."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from src.evaluation.corpus_aware_planning import (
    evaluate_corpus_aware_planning,
    load_corpus_planning_inputs,
)

DEFAULT_OUTPUT = Path("data/financebench/planning_runs/m4-corpus-aware-v1.json")


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
    args = parser.parse_args()

    map_started = time.perf_counter()
    cases, chunks, corpus_map, index_manifest = load_corpus_planning_inputs(
        data_dir=args.data_dir,
        run_dir=args.run_dir,
    )
    map_build_ms = max(0.0, (time.perf_counter() - map_started) * 1000)
    result = evaluate_corpus_aware_planning(
        cases,
        chunks,
        corpus_map,
        index_manifest=index_manifest,
    )
    result["corpus_map"]["construction_and_load_latency_ms"] = round(map_build_ms, 3)
    _write_json(args.output, result)
    summary = {
        "output": str(args.output),
        "benchmark": result["benchmark"],
        "case_count": result["case_count"],
        "corpus_map": result["corpus_map"],
        "comparison": result["comparison"],
        "synthetic_absent_company_probes": result["synthetic_absent_company_probes"],
        "resource_use": result["resource_use"],
        "evaluation_wall_time_ms": result["evaluation_wall_time_ms"],
        "source_provenance": result["source_provenance"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
