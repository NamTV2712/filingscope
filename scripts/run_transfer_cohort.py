"""Predict without labels, then score the frozen internal Ford/Chevron cohort."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from configs.offline_guard import offline_socket_guard
from src.evaluation.answer_metrics import numeric_fact_signatures
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.independent_final import ARMS, Corpus, Question, read_pinned
from src.retrieval.canonical_json import canonical_sha256, sha256_file


def load_inputs(bundle: Path, freeze_hash: str):
    """Validate label-free files only; prediction never opens the label path."""
    freeze = json.loads(read_pinned(bundle / "transfer-freeze.json", freeze_hash))
    files = freeze["files"]
    corpus = Corpus.model_validate_json(read_pinned(bundle / "corpus.json", files["corpus.json"]))
    read_pinned(bundle / "filing-inventory.json", files["filing-inventory.json"])
    questions = [Question.model_validate_json(line) for line in read_pinned(bundle / "questions.jsonl", files["questions.jsonl"]).splitlines()]
    if len(questions) != freeze["cases"] or len({q.case_id for q in questions}) != len(questions):
        raise ValueError("The frozen cohort requires unique complete question IDs")
    return freeze, corpus, questions


def score_predictions(questions: list[Question], labels: list[dict], predictions: dict, *, reviews: dict | None = None) -> dict:
    ids = {q.case_id for q in questions}
    if {row["case_id"] for row in labels} != ids or len(labels) != len(ids):
        raise ValueError("Label membership differs from the frozen question cohort")
    if set(predictions) != set(ARMS) or any(set(predictions[arm]) != ids for arm in ARMS):
        raise ValueError("Predictions must cover all frozen IDs in both arms")
    reviews = reviews or {}
    if set(reviews) - set(ARMS):
        raise ValueError("Source reviews contain an unknown architecture")
    reports = {}
    for arm in ARMS:
        rows = []
        for label in labels:
            prediction = predictions[arm][label["case_id"]]
            answer = prediction["answer"]
            released = bool(answer.strip()) and prediction["disposition"] in {"VERIFIED", "PARTIAL"}
            numeric_exact = citation_complete = None
            if label["answerable"]:
                expected = f"{label['value']}%" if label["kind"] == "percent" else f"USD {label['value']}"
                numeric_exact = bool(Counter(numeric_fact_signatures(expected)) <= Counter(numeric_fact_signatures(answer)))
                sources = prediction["citation_sources"]
                cited = {sources[int(index) - 1] for index in re.findall(r"\[Source ([1-9]\d*)\]", answer) if int(index) <= len(sources)}
                citation_complete = bool(label["evidence"]) and all(row["source"] in cited for row in label["evidence"])
            correct = bool(released and numeric_exact and citation_complete) if label["answerable"] else not released
            review = reviews.get(arm, {}).get(label["case_id"])
            grounded = None
            if review is not None:
                if not released or review.get("answer_sha256") != canonical_sha256(answer):
                    raise ValueError("Source review does not bind the released answer")
                if type(review.get("grounded_correct")) is not bool or not review.get("reviewer"):
                    raise ValueError("Source reviews require a reviewer and a Boolean judgment")
                if review["grounded_correct"]:
                    if not correct or not label["answerable"]:
                        raise ValueError("A grounded review requires the frozen numeric value and citation locators")
                    if review.get("checked_evidence") != label["evidence"]:
                        raise ValueError("Review must bind every frozen source cell and operand role")
                    if review.get("all_atomic_claims_supported") is not True:
                        raise ValueError("A grounded review must check every atomic claim and citation")
                grounded = review["grounded_correct"]
            rows.append({"case_id": label["case_id"], "category": label["category"], "answerable": label["answerable"],
                         "released": released, "numeric_exact": numeric_exact, "citation_complete": citation_complete,
                         "numeric_and_locator_correct": correct, "disposition": prediction["disposition"],
                         "answer": answer, "citation_sources": prediction["citation_sources"], "latency_ms": prediction["latency_ms"],
                         "source_reviewed_grounded_correct": grounded})
        positive = [row for row in rows if row["answerable"]]
        negative = [row for row in rows if not row["answerable"]]
        releases = [row for row in rows if row["released"]]
        if set(reviews.get(arm, {})) - {row["case_id"] for row in releases}:
            raise ValueError("Source review membership differs from released predictions")
        reports[arm] = {"overall": {"cases": len(rows), "answerable": len(positive), "unanswerable": len(negative),
                                    "released": sum(row["released"] for row in rows),
                                    "numeric_and_locator_correct": sum(row["numeric_and_locator_correct"] for row in positive),
                                    "correct_abstentions": sum(row["numeric_and_locator_correct"] for row in negative),
                                    "source_reviewed_grounded_correct": sum(row["source_reviewed_grounded_correct"] is True for row in positive),
                                    "source_reviewed_releases": sum(row["source_reviewed_grounded_correct"] is not None for row in releases),
                                    "unreviewed_releases": sum(row["source_reviewed_grounded_correct"] is None for row in releases),
                                    "known_release_errors": sum(row["source_reviewed_grounded_correct"] is False or not row["answerable"] for row in releases)},
                        "per_case": rows}
    return {"status": "INTERNAL_DEVELOPMENT_EXPOSED", "scoring": "Numeric answer and frozen citation locators; source review of every released claim remains required.",
            "results": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("predict", "score"))
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--predictions-sha256")
    parser.add_argument("--reviews", type=Path, help="Post-prediction source/operand review JSON")
    parser.add_argument("--reviews-sha256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "score" and (args.predictions is None or not args.predictions_sha256):
        parser.error("Scoring requires the recorded prediction path and hash")
    if (args.reviews or args.reviews_sha256) and (args.mode != "score" or not (args.reviews and args.reviews_sha256)):
        parser.error("Both review arguments are supported in score mode only")
    output = args.output.resolve()
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    if output.exists() or not output.is_relative_to(root / "data"):
        parser.error("Use a new output file under the ignored data directory")
    with offline_socket_guard():
        freeze, corpus, questions = load_inputs(args.bundle, args.freeze_sha256)
        if args.mode == "predict":
            from scripts.run_independent_final import predict_filing_questions
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            report = predict_filing_questions(args.bundle, corpus, questions, git_sha=sha, cutoff=freeze["cutoff"], threads=freeze["threads"])
        else:
            saved = json.loads(read_pinned(args.predictions, args.predictions_sha256))
            if saved["freeze_sha256"] != args.freeze_sha256:
                raise ValueError("Predictions belong to another cohort freeze")
            labels = [json.loads(line) for line in read_pinned(args.bundle / "labels.jsonl", freeze["files"]["labels.jsonl"]).splitlines()]
            reviews = None
            if args.reviews:
                reviewed = json.loads(read_pinned(args.reviews, args.reviews_sha256))
                if reviewed.get("predictions_sha256") != args.predictions_sha256 or reviewed.get("freeze_sha256") != args.freeze_sha256:
                    raise ValueError("Source reviews belong to different predictions or cohort freeze")
                reviews = reviewed["arms"]
            report = score_predictions(questions, labels, saved["predictions"], reviews=reviews)
            if args.reviews:
                report["reviews_sha256"] = args.reviews_sha256
            report["predictions_sha256"] = args.predictions_sha256
            report["runtime"] = {key: value for key, value in saved.items() if key != "predictions"}
            print(json.dumps({arm: row["overall"] for arm, row in report["results"].items()}, indent=2))
        report["freeze_sha256"] = args.freeze_sha256
        write_json_atomic(output, report)
        print(sha256_file(output))


if __name__ == "__main__":
    main()
