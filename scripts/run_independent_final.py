"""Run sealed questions on a frozen corpus, then score after the labels are released."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path

from configs.financebench import P1_EMBEDDING_REVISION
from configs.offline_guard import offline_socket_guard
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.independent_final import (
    ARMS, Corpus, Freeze, Label, Membership, Question, check_membership, read_pinned, read_rows, score_cohort,
)
from src.evaluation.independent_primary import ReviewedPredictions, score_reviewed_predictions
from src.evaluation.prediction_receipt import (
    PredictionReceipt, read_frozen_predictions, validate_prediction_membership, verify_prediction_commit,
)
from src.retrieval.canonical_json import sha256_file


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()


def _dependencies() -> dict[str, str]:
    return dict(sorted((dist.metadata["Name"], dist.version) for dist in distributions()))


def _predict(bundle: Path, freeze: Freeze, corpus: Corpus, questions: list[Question]) -> dict:
    return predict_filing_questions(bundle, corpus, questions, git_sha=freeze.git_sha,
                                    cutoff=freeze.filing_through.isoformat(), threads=freeze.threads)


def predict_filing_questions(bundle: Path, corpus: Corpus, questions: list[Question], *,
                             git_sha: str, cutoff: str, threads: int) -> dict:
    import torch

    from scripts.run_multi_agent_ablation import _PolicyLayer, _RecordingRetriever
    from scripts.run_specialist_architectures import observe
    from src.runtime.filing_bundle import load_filing_runtime

    started = time.perf_counter()
    torch.set_num_threads(threads)
    runtime = load_filing_runtime(bundle, corpus=corpus, cutoff=cutoff, retriever_wrapper=_RecordingRetriever)
    graph, router, retriever, sec = runtime.graph, runtime.router, runtime.retriever, runtime.sec
    policy = _PolicyLayer(router.extractor)
    setup_ms = (time.perf_counter() - started) * 1000
    predictions = {arm: {} for arm in ARMS}
    for position, question in enumerate(questions):
        # Alternate the first arm to reduce systematic warm-up effects.
        for arm in ARMS if position % 2 == 0 else reversed(ARMS):
            observation, elapsed, _ = observe(question.question, question.case_id, arm, graph, None, retriever, sec, policy)
            row = asdict(observation)
            row["retrieved_sources"] = sorted(observation.retrieved_sources)
            predictions[arm][question.case_id] = dict(row, latency_ms=round(elapsed, 3))
    return {
        "git_sha": git_sha,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": _dependencies(),
        "setup_ms": round(setup_ms, 3),
        "peak_working_set_bytes": peak_memory_bytes(),
        "predictions": predictions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "predict", "receipt", "score"))
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True, help="Reviewer-supplied sha256:<hex> before opening the question file")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--predictions-sha256", help="Prediction hash recorded before label release")
    parser.add_argument("--prediction-receipt-commit", help="Reviewer-recorded Git commit containing the prediction receipt")
    parser.add_argument("--adjudications", type=Path, help="Reviewer-supplied post-prediction G1 judgments")
    parser.add_argument("--adjudications-sha256", help="Reviewer-recorded hash for the judgment file")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode in ("predict", "score") and args.output is None:
        parser.error("--output is required for predict and score")
    if args.mode in ("receipt", "score") and (args.predictions is None or not args.predictions_sha256):
        parser.error("--predictions and --predictions-sha256 are required for receipt and score")
    if args.prediction_receipt_commit and args.mode != "score":
        parser.error("--prediction-receipt-commit is supported in score mode only")
    if args.mode == "receipt" and args.output is not None:
        parser.error("Receipt mode derives the output path from the freeze hash")
    if args.adjudications or args.adjudications_sha256:
        if args.mode != "score" or not (args.adjudications and args.adjudications_sha256):
            parser.error("Both adjudication arguments are supported in score mode only")
    if args.output is not None:
        # Require a fresh local result file and avoid overwriting sealed inputs.
        root = Path(_git("rev-parse", "--show-toplevel"))
        output = args.output.resolve()
        if (output.exists() or not output.is_relative_to(root / "data") or not _git("check-ignore", "--", str(output))):
            parser.error("--output must be a new file under the repository's ignored data directory")
    with offline_socket_guard():
        bundle = args.bundle
        freeze = Freeze.model_validate_json(read_pinned(bundle / "freeze.json", args.freeze_sha256))
        head = _git("rev-parse", "HEAD")
        if head not in {freeze.git_sha, args.prediction_receipt_commit} or _git("status", "--porcelain"):
            parser.error("Check out the exact frozen revision with a clean worktree")
        if args.mode == "score" and freeze.require_committed_prediction_receipt and not args.prediction_receipt_commit:
            parser.error("This freeze requires --prediction-receipt-commit before labels can be read")
        corpus = Corpus.model_validate_json(read_pinned(bundle / "corpus.json", freeze.corpus_sha256))
        exposed = read_rows(bundle / "exposed.jsonl", freeze.exposed_membership_sha256, Membership)
        questions = read_rows(bundle / "questions.jsonl", freeze.questions_sha256, Question)
        check_membership(freeze, exposed, corpus, questions)
        if args.mode == "preflight":
            print(f"Frozen cohort metadata passed for {len(questions)} cases. Labels were not opened.")
            return 0
        if args.mode == "predict":
            if platform.python_version() != freeze.python_version or _dependencies() != freeze.dependencies:
                raise ValueError("Python or installed dependency versions differ from the reviewer freeze")
            report = _predict(bundle, freeze, corpus, questions)
        else:
            receipt = PredictionReceipt(git_sha=freeze.git_sha, freeze_sha256=args.freeze_sha256,
                                        predictions_sha256=args.predictions_sha256)
            predictions = read_frozen_predictions(args.predictions, freeze, receipt)
            validate_prediction_membership(predictions, {row.case_id for row in questions})
            if args.mode == "receipt":
                root = Path(_git("rev-parse", "--show-toplevel"))
                destination = root / receipt.git_path
                if destination.parent.resolve() != destination.parent:
                    raise ValueError("The receipt directory must be inside the frozen worktree")
                destination.parent.mkdir(exist_ok=True)
                with destination.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(receipt.model_dump_json(indent=2) + "\n")
                print(receipt.git_path)
                return 0
            if args.prediction_receipt_commit:
                verify_prediction_commit(root, args.prediction_receipt_commit, receipt)
            labels = read_rows(bundle / "labels.jsonl", freeze.labels_sha256, Label)
            report = score_cohort(freeze, corpus, questions, labels, predictions["predictions"])
            if args.adjudications:
                reviewed = ReviewedPredictions.model_validate_json(read_pinned(
                    args.adjudications, args.adjudications_sha256,
                ))
                report["primary_adjudication"] = score_reviewed_predictions(
                    freeze, questions, labels, predictions["predictions"], reviewed,
                    freeze_sha256=args.freeze_sha256, predictions_sha256=args.predictions_sha256,
                )
                report["adjudications_sha256"] = args.adjudications_sha256
            report["predictions_sha256"] = args.predictions_sha256
            if args.prediction_receipt_commit:
                report["prediction_receipt_commit"] = args.prediction_receipt_commit
            report["runtime"] = {key: value for key, value in predictions.items() if key != "predictions"}
        report["freeze_sha256"] = args.freeze_sha256
        report["corpus"] = corpus.model_dump(mode="json")
        report["configuration"] = freeze.model_dump(mode="json")
        write_json_atomic(output, report)
        print(sha256_file(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
