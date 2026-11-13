"""Bind a historical paired replay and create a label-free reviewer handoff."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from configs.multi_agent_ablation import CASES
from configs.offline_guard import offline_socket_guard
from scripts.run_completion_evaluation import risk_coverage_points
from src.evaluation.benchmark_io import wilson_rate, write_json_atomic
from src.evaluation.independent_final import ARMS, CATEGORIES, Corpus, Freeze, Label, Membership, Question
from src.evaluation.independent_primary import ReviewedPredictions
from src.evaluation.m13_failure_replay import expected_slots
from src.evaluation.multi_agent_ablation import paired_grounded_exact
from src.retrieval.canonical_json import sha256_file

CRITERIA = {"minimum_coverage": 0.5, "maximum_incorrect_release_point": 0.05,
            "confidence": 0.95, "maximum_critical_identity_errors": 0}
FREEZE_RELEASE_RISK = {"minimum_coverage": CRITERIA["minimum_coverage"],
                       "maximum_incorrect_release": CRITERIA["maximum_incorrect_release_point"]}


def historical_report(source: Path) -> dict:
    report = json.loads(source.read_bytes())
    cohort = report["cohorts"]["m13"]
    expected = [case.case_id for case in CASES]
    arms = {}
    for name in ARMS:
        arm = cohort[name]
        rows = arm["per_case"]
        if [row["case_id"] for row in rows] != expected:
            raise ValueError("Expected the complete ordered historical M13 cohort")
        releases = [row for row in rows if row["answered"]]
        risk = wilson_rate(sum(not row["grounded_exact"] for row in releases), len(releases))
        arms[name] = {
            "historical_metrics": arm["overall"],
            "incorrect_release": risk,
            "coverage": wilson_rate(len(releases), len(rows)),
            "risk_coverage": risk_coverage_points(rows),
            "risk_claim": (
                "MEETS_DESCRIPTIVE_BOUND" if risk["wilson_95"] and risk["wilson_95"][1] <= CRITERIA["maximum_incorrect_release_point"]
                else "INCONCLUSIVE"
            ),
            "failures": [row for row in rows if row["answerable"] != row["answered"]
                         or row["answered"] and not row["grounded_exact"]],
        }
    paired = paired_grounded_exact(cohort["C_routed"]["per_case"], cohort["B_adaptive"]["per_case"],
                                   {case.case_id: {slot.entity for slot in expected_slots(case)}
                                    for case in CASES if case.claims},
                                   seed=20261112)
    return {
        "status": "PROVISIONAL_NOT_INDEPENDENT", "cohort": "development-exposed M13",
        "historical_architecture_report_sha256": sha256_file(source), "configuration": report["configuration"],
        "reviewer_threshold_proposal": CRITERIA, "case_count": len(expected), "arms": arms,
        "paired_grounded_exact": paired,
        "peak_working_set_bytes": report["peak_working_set_bytes"],
        "strict_semantic_metrics": "AWAITING_ADJUDICATED_RELEASES",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use a fresh output directory")
    with offline_socket_guard():
        report = historical_report(args.historical_report)
        write_json_atomic(args.output / "provisional-report.json", report)
        write_json_atomic(args.output / "reviewer-handoff.json", {
            "status": "PROVISIONAL_NOT_INDEPENDENT",
            "workflow": ["freeze", "predict", "record_prediction_sha256", "release_labels",
                         "adjudicate_frozen_predictions", "record_adjudication_sha256", "score"],
            "target_questions": 160, "target_issuer_groups_minimum": 20,
            "target_category_counts": dict.fromkeys(sorted(CATEGORIES), 20),
            "reviewer_threshold_proposal": CRITERIA,
            "freeze_release_risk_proposal": FREEZE_RELEASE_RISK,
            "required_external_inputs": [
                "Complete exposed issuer/document crosswalk, including G2 and external benchmark exposure",
                "Later filing inventory, PDF renditions, frozen index and Company Facts snapshots",
                "Independently authored questions and reviewer-held gold with separately committed hashes",
                "Post-prediction numeric, retrieval and atomic claim/citation judgments for G1 primary metrics",
            ],
            "schemas": {model.__name__: model.model_json_schema()
                        for model in (Freeze, Membership, Corpus, Question, Label, ReviewedPredictions)},
        })
    print(f"Historical readiness replay: {report['case_count']} cases, {report['status']}")


if __name__ == "__main__":
    main()
