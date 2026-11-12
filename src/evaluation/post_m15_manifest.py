"""Provenance for offline Post-M15 replay artifacts."""

from __future__ import annotations

import json
import platform
import subprocess
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path

from configs.multi_agent_ablation import CASES
from src.retrieval.canonical_json import canonical_sha256, sha256_file


_REPLAY_FILES = (
    "configs/multi_agent_ablation.py",
    "scripts/run_multi_agent_ablation.py",
    "scripts/run_failure_attribution.py",
    "src/evaluation/failure_attribution.py",
    "src/evaluation/m13_failure_replay.py",
    "src/evaluation/oracle_interventions.py",
    "src/evaluation/post_m15_manifest.py",
)


def build_manifest(
    *,
    p1_run: Path,
    source_manifest: Path,
    sec_manifest: Path,
    pages: Path,
    artifacts: dict[str, Path],
    configuration: dict,
    code_files: tuple[str, ...] = _REPLAY_FILES,
) -> dict:
    def read(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()

    sources = read(source_manifest)
    index = read(p1_run / "index_manifest.json")
    embedding = read(p1_run / "embedding_manifest.json")
    return {
        "schema": "filingscope-post-m15-manifest-v1",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_sha": git("rev-parse", "HEAD"),
        "worktree_dirty": bool(git("status", "--porcelain")),
        "tracked_diff_sha256": canonical_sha256(git("diff", "--binary", "HEAD")),
        "dataset": {
            "financebench": sources["dataset"],
            "financebench_original_split": "OPEN_SOURCE",
            "m13_split": dict(Counter(case.split for case in CASES)),
            "m13_usage": "exposed retrospective diagnostic cohort",
            "m13_labels_sha256": sha256_file(Path("configs/multi_agent_ablation.py")),
            "source_manifest_sha256": sha256_file(source_manifest),
            "document_hashes": {
                info["doc_name"]: info["sha256"] for info in sources["files"]["source_pdfs"]
            },
        },
        "corpus_fingerprint": index["corpus_fingerprint"],
        "embedding": embedding,
        "retrieval": {"engine": "local frozen dense cosine", "index": index},
        "source_snapshots": {
            "sec_manifest_sha256": sha256_file(sec_manifest),
            "sec": read(sec_manifest),
            "pdf_page_cache_sha256": sha256_file(pages),
            "pdf_page_cache_manifest_sha256": sha256_file(pages.with_suffix(".json")),
        },
        "configuration": configuration,
        "configuration_sha256": canonical_sha256(configuration),
        "replay_code_sha256": {file: sha256_file(Path(file)) for file in code_files if Path(file).is_file()},
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_version": git("--version"),
        "dependencies": dict(sorted(
            (dist.metadata["Name"], dist.version) for dist in distributions()
        )),
        "artifacts": {
            name: {"filename": path.name, "sha256": sha256_file(path)}
            for name, path in artifacts.items()
        },
    }
