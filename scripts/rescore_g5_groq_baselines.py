"""Replay saved Groq drafts against typed SEC pilot identities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from configs.offline_guard import offline_socket_guard
from configs.sec_runtime_pilot import CASES, STATUS
from scripts.run_g5_local_baselines import PAGE_HASH, REFERENCE_HASHES, Draft
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.pilot_numeric import score_claims
from src.retrieval.canonical_json import sha256_file


def rescore(source: Path) -> dict:
    started = perf_counter()
    original = json.loads(source.read_bytes())
    if (original["status"] != STATUS or original["reference_sha256"] not in REFERENCE_HASHES
            or original["pages_sha256"] != PAGE_HASH):
        raise ValueError("Expected completed predictions on the frozen SEC pilot")
    cases = {case.case_id: case for case in CASES}
    tracks = {}
    for track, original_track in original["tracks"].items():
        rows = []
        for saved in original_track["per_case"]:
            case = cases[saved["case_id"]]
            invalid = saved["response_error"] is not None
            draft = None if invalid else Draft.model_validate_json(saved["raw"])
            claims = [] if draft is None else [
                (claim.statement, saved["supplied_pages"].get(str(claim.source))) for claim in draft.claims
            ]
            result = score_claims(case, claims) if not invalid else {
                "exact": False, "grounded_exact": False, "matched_claims": 0, "matching_locators": 0,
            }
            rows.append({
                "case_id": case.case_id, "answerable": bool(case.cells), "released": invalid or bool(claims),
                "expected_claims": len(case.cells), "claimed": len(claims),
                "citations": sum(claim.source is not None for claim in draft.claims) if draft else 0,
                **result, "historical_exact": saved["exact"], "historical_grounded_exact": saved["grounded_exact"],
            })
        if len({row["case_id"] for row in rows}) != len(rows):
            raise ValueError("Duplicate case in saved predictions")
        answerable = [row for row in rows if row["answerable"]]
        released = [row for row in rows if row["released"]]
        tracks[track] = {
            "answerable": len(answerable), "questions": len(rows), "releases": len(released),
            "numeric_exact": sum(row["exact"] for row in answerable),
            "grounded_exact": sum(row["grounded_exact"] for row in answerable),
            "historical_numeric_exact": sum(row["historical_exact"] for row in answerable),
            "historical_grounded_exact": sum(row["historical_grounded_exact"] for row in answerable),
            "correct_abstentions": sum(not row["answerable"] and not row["released"] for row in rows),
            "numeric_errors_among_releases": sum(not row["exact"] for row in released),
            "locator_errors_among_releases": sum(not row["grounded_exact"] for row in released),
            "citation_matches": sum(row["matching_locators"] for row in rows),
            "citation_count": sum(row["citations"] for row in rows),
            "per_case": rows,
        }
    return {
        "scorer": "sec-pilot-typed-numeric-v1", "status": STATUS, "source_sha256": sha256_file(source),
        "reference_sha256": original["reference_sha256"], "pages_sha256": original["pages_sha256"],
        "tracks": tracks, "provider_calls": 0, "cost_usd": 0,
        "elapsed_ms": round((perf_counter() - started) * 1_000, 3), "peak_memory_bytes": peak_memory_bytes(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output file")
    with offline_socket_guard():
        write_json_atomic(args.output, rescore(args.source))


if __name__ == "__main__":
    main()
