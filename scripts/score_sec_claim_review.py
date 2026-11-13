"""Score source-reviewed claims on the frozen SEC document-only pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from pydantic import TypeAdapter

from configs.offline_guard import offline_socket_guard
from configs.sec_runtime_pilot import CASES, STATUS
from src.evaluation.benchmark_io import peak_memory_bytes, wilson_rate, write_json_atomic
from src.evaluation.independent_final import read_pinned
from src.evaluation.independent_primary import _validate_claims
from src.evaluation.primary_metrics import ScoredCase, score_primary_metrics
from src.retrieval.canonical_json import sha256_file


def score_review(report: dict, judgments: list[ScoredCase]) -> dict:
    cases = {case.case_id: bool(case.cells) for case in CASES}
    rows = report["tracks"]["document_only"]["per_case"]
    by_id = {row["case_id"]: row for row in rows}
    if by_id.keys() != cases.keys() or len(by_id) != len(rows) or {row.case_id for row in judgments} != cases.keys():
        raise ValueError("Review and predictions must cover the frozen pilot")
    for judgment in judgments:
        row = by_id[judgment.case_id]
        answerable = cases[judgment.case_id]
        if (judgment.answerable, judgment.numeric_applicable, judgment.released) != (answerable, answerable, row["answered"]):
            raise ValueError(f"Review applicability differs from the frozen case: {judgment.case_id}")
        if not judgment.released:
            continue
        if judgment.claims is None or judgment.answer_exact is None or (answerable and judgment.numeric_checks is None):
            raise ValueError(f"Release needs a complete review: {judgment.case_id}")
        _validate_claims(judgment, row)
    scored = score_primary_metrics(judgments)
    risk = scored["primary"]["incorrect_or_unsupported_release_risk"]
    scored["release_risk_interval"] = wilson_rate(risk["numerator"], risk["denominator"])
    return scored


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=Path("docs/G1_SEC_CLAIM_REVIEW.json"))
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output path")
    with offline_socket_guard():
        started = perf_counter()
        reviewed = json.loads(args.review.read_bytes())
        arms = {}
        for name, directory in (("original", args.original), ("current", args.current)):
            arm = reviewed["arms"][name]
            report = json.loads(read_pinned(directory / "report.json", arm["report_sha256"]))
            for filename, field in (("pages.jsonl", "pages_sha256"), ("reference.json", "reference_sha256")):
                digest = reviewed[field]
                if report[field] != digest or sha256_file(directory / filename) != digest:
                    raise ValueError(f"Frozen {filename} differs from the review")
            rows = TypeAdapter(list[ScoredCase]).validate_json(json.dumps(arm["judgments"]))
            arms[name] = score_review(report, rows)
        result = {
            "status": STATUS, "method": "AUTHOR_REVIEWED_DEVELOPMENT_EXPOSED",
            "review_sha256": sha256_file(args.review), "arms": arms,
            "resources": {"scoring_wall_ms": round((perf_counter() - started) * 1000, 3),
                          "peak_memory_bytes": peak_memory_bytes(), "provider_calls": 0, "provider_cost_usd": 0},
        }
        write_json_atomic(args.output, result)
    print(json.dumps({name: report["primary"] for name, report in arms.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
