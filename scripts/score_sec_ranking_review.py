"""Score author-reviewed alternative page evidence on the frozen SEC pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from configs.sec_runtime_pilot import CASES, STATUS
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.primary_metrics import RetrievalAdjudication, score_retrieval


def _score(report: dict, review: dict) -> dict:
    if any(review[key] != report[key] for key in ("reference_sha256", "pages_sha256")):
        raise ValueError("Review is for a different reference or PDF page extraction")
    ranking = report["ranking_controls"]["ranking_only"]
    cases = {case.case_id: case for case in CASES}
    reviewed = review["cases"]
    case_ids = set(reviewed)
    ranked_by_arm = {name: {row["case_id"]: tuple(row["ranked_pages"]) for row in arm["per_case"]}
                     for name, arm in ranking.items()}
    results = {}
    for name, rows in ranked_by_arm.items():
        adjudications = []
        for case_id in sorted(case_ids):
            judged = reviewed[case_id]
            targets = {key: frozenset(pages) for key, pages in judged["targets"].items()}
            originals = {f"{cell.pdf.name}#p{cell.page}" for cell in cases[case_id].cells}
            relevant = frozenset().union(*targets.values())
            observed = {page for arm in ranked_by_arm.values() for page in arm[case_id][:10]}
            reviewed_pages = set(judged["reviewed_pages"])
            if not observed <= reviewed_pages:
                raise ValueError(f"Review does not cover every ranked page for {case_id}")
            if not originals <= relevant <= reviewed_pages or len(targets) != len(cases[case_id].cells):
                raise ValueError(f"Reviewed targets are inconsistent for {case_id}")
            adjudications.append(RetrievalAdjudication(
                granularity="page", ranked_ids=rows[case_id], relevant_ids=relevant, gold_targets=targets,
            ))
        results[name] = score_retrieval(adjudications)["page"]
    return {"status": STATUS, "method": "author_reviewed_post_run_scoped_dense_misses", "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review", type=Path, default=Path("docs/G3_SEC_RANKING_REVIEW.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output path")
    report, review = args.report.read_bytes(), args.review.read_bytes()
    result = _score(json.loads(report), json.loads(review))
    result.update(report_sha256=f"sha256:{hashlib.sha256(report).hexdigest()}",
                  review_sha256=f"sha256:{hashlib.sha256(review).hexdigest()}")
    write_json_atomic(args.output, result)
    print(json.dumps(result["results"], sort_keys=True))


if __name__ == "__main__":
    main()
