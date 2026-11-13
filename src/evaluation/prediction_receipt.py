"""Bind a reviewer-held prediction run to a hash-only Git commit."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Literal

from src.evaluation.independent_final import ARMS, Freeze, GitSha, Hash, _Record


class PredictionReceipt(_Record):
    schema_version: Literal["filingscope-prediction-receipt-v1"] = "filingscope-prediction-receipt-v1"
    git_sha: GitSha
    freeze_sha256: Hash
    predictions_sha256: Hash

    @property
    def git_path(self) -> str:
        return f"evaluation_receipts/{self.freeze_sha256.removeprefix('sha256:')}.json"


def read_frozen_predictions(path: Path, freeze: Freeze, receipt: PredictionReceipt) -> dict:
    content = path.read_bytes()
    if f"sha256:{hashlib.sha256(content).hexdigest()}" != receipt.predictions_sha256:
        raise ValueError("Frozen prediction hash mismatch")
    predictions = json.loads(content)
    if predictions["git_sha"] != freeze.git_sha or predictions["freeze_sha256"] != receipt.freeze_sha256:
        raise ValueError("Prediction provenance differs from the reviewer freeze")
    if predictions["python"] != freeze.python_version or predictions["dependencies"] != freeze.dependencies:
        raise ValueError("Prediction dependency provenance differs from the reviewer freeze")
    return predictions


def validate_prediction_membership(predictions: dict, case_ids: set[str]) -> None:
    arms = predictions["predictions"]
    if set(arms) != set(ARMS) or any(set(cases) != case_ids for cases in arms.values()):
        raise ValueError("Both prediction arms must contain the complete cohort")


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, encoding="utf-8").strip()


def verify_prediction_commit(root: Path, commit: str, expected: PredictionReceipt) -> None:
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Use the full prediction receipt commit SHA")
    try:
        lineage = _git(root, "rev-list", "--parents", "-n", "1", commit).split()
        change = _git(root, "diff-tree", "--no-commit-id", "--name-status", "--no-renames", "-r", commit)
        entry = _git(root, "ls-tree", commit, "--", expected.git_path)
    except subprocess.CalledProcessError as error:
        raise ValueError("Prediction receipt commit is unavailable") from error
    if (lineage != [commit, expected.git_sha] or change != f"A\t{expected.git_path}"
            or not entry.startswith("100644 blob ")):
        raise ValueError("Prediction receipt commit must add only the hash receipt over the frozen revision")
    committed = PredictionReceipt.model_validate_json(_git(root, "show", f"{commit}:{expected.git_path}"))
    if committed != expected:
        raise ValueError("Committed prediction receipt differs from the supplied hashes")
