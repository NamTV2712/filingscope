"""Score a local batch of explicitly adjudicated answers and retrieval runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from pydantic import TypeAdapter

from configs.offline_guard import offline_socket_guard
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.primary_metrics import ScoredCase, score_primary_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adjudications", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() == args.adjudications.resolve():
        parser.error("Use a separate output path")
    with offline_socket_guard():
        started = perf_counter()
        payload = args.adjudications.read_bytes()
        cases = TypeAdapter(list[ScoredCase]).validate_json(payload)
        report = score_primary_metrics(cases)
        report["adjudications_sha256"] = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        report["resources"] = {
            "scoring_wall_ms": round((perf_counter() - started) * 1000, 3),
            "process_peak_bytes": peak_memory_bytes(),
            "provider_calls": 0,
            "provider_tokens": 0,
            "provider_cost_usd": 0,
        }
        write_json_atomic(args.output, report)
    print(json.dumps({"case_count": report["case_count"], "primary": report["primary"]}, sort_keys=True))


if __name__ == "__main__":
    main()
