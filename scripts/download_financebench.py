"""Fetch the pinned public FinanceBench sample and referenced source PDFs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from configs.financebench import (
    FINANCEBENCH_EXPECTED_CASES,
    FINANCEBENCH_EXPECTED_DOCUMENTS,
    FINANCEBENCH_GITHUB_REPOSITORY,
    FINANCEBENCH_GITHUB_REVISION,
    FINANCEBENCH_HUGGINGFACE_REVISION,
    FINANCEBENCH_LICENSE,
    FINANCEBENCH_LICENSE_URL,
)
from src.evaluation.financebench_dataset import (
    normalize_document_metadata,
    validate_case_records,
)

logger = logging.getLogger(__name__)

DATA_FILES = (
    "data/financebench_open_source.jsonl",
    "data/financebench_document_information.jsonl",
)
REQUEST_TIMEOUT_SECONDS = (15, 120)


def _git_blob_sha1_bytes(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            records.append(value)
    return records


def validate_financebench_sources(
    cases: list[dict[str, Any]],
    document_rows: list[dict[str, Any]],
    tree_entries: list[dict[str, Any]],
    *,
    expected_case_count: int = FINANCEBENCH_EXPECTED_CASES,
    expected_document_count: int = FINANCEBENCH_EXPECTED_DOCUMENTS,
) -> dict[str, Any]:
    validate_case_records(cases, expected_count=expected_case_count)
    case_documents = {row["doc_name"] for row in cases}
    if len(case_documents) != expected_document_count:
        raise ValueError(
            f"Expected {expected_document_count} case documents, found {len(case_documents)}"
        )
    normalized_metadata, conflicts = normalize_document_metadata(document_rows)
    tree_by_path = {entry.get("path"): entry for entry in tree_entries}
    missing_metadata = sorted(case_documents - set(normalized_metadata))
    if missing_metadata:
        raise ValueError(f"Case documents missing metadata rows: {missing_metadata[:5]}")
    missing_pdfs = sorted(
        doc_name
        for doc_name in case_documents
        if f"pdfs/{doc_name}.pdf" not in tree_by_path
    )
    if missing_pdfs:
        raise ValueError(f"Case documents missing repository PDFs: {missing_pdfs[:5]}")
    evidence_pages = sum(len(row["evidence"]) for row in cases)
    return {
        "case_count": len(cases),
        "document_metadata_row_count": len(document_rows),
        "unique_case_document_count": len(case_documents),
        "evidence_record_count": evidence_pages,
        "metadata_document_count": len(normalized_metadata),
        "metadata_conflict_count": len(conflicts),
        "metadata_conflicts": conflicts,
        "case_documents": sorted(case_documents),
    }


def _atomic_download(
    session: requests.Session,
    *,
    url: str,
    destination: Path,
    expected_size: int,
    expected_blob_sha: str,
    require_pdf_magic: bool = False,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    sha256 = hashlib.sha256()
    sha1 = hashlib.sha1(f"blob {expected_size}\0".encode("ascii"))
    byte_count = 0
    prefix = bytearray()
    temporary_path: Path | None = None
    try:
        response = session.get(url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".download",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            for block in response.iter_content(chunk_size=1024 * 1024):
                if not block:
                    continue
                byte_count += len(block)
                sha256.update(block)
                sha1.update(block)
                if len(prefix) < 5:
                    prefix.extend(block[: 5 - len(prefix)])
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if byte_count != expected_size:
            raise ValueError(
                f"Downloaded file size mismatch for {destination.name}: "
                f"expected {expected_size}, got {byte_count}"
            )
        if sha1.hexdigest() != expected_blob_sha:
            raise ValueError(f"Git blob SHA mismatch for {destination.name}")
        if require_pdf_magic and not bytes(prefix).startswith(b"%PDF-"):
            raise ValueError(f"Downloaded source is not a PDF: {destination.name}")
        os.replace(temporary_path, destination)
        temporary_path = None
        return {
            "path": destination.as_posix(),
            "size_bytes": byte_count,
            "git_blob_sha": sha1.hexdigest(),
            "sha256": f"sha256:{sha256.hexdigest()}",
        }
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(value, temporary_file, indent=2, ensure_ascii=False, sort_keys=True)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def download_financebench(data_dir: Path = Path("data/financebench")) -> dict[str, Any]:
    """Download the public sample and exactly the PDFs referenced by its cases."""
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "User-Agent": "FilingScope research benchmark",
        }
    )
    repository_root = f"https://api.github.com/repos/{FINANCEBENCH_GITHUB_REPOSITORY}"
    tree_url = (
        f"{repository_root}/git/trees/{FINANCEBENCH_GITHUB_REVISION}?recursive=1"
    )
    tree_response = session.get(tree_url, timeout=REQUEST_TIMEOUT_SECONDS)
    tree_response.raise_for_status()
    tree_data = tree_response.json()
    if tree_data.get("truncated"):
        raise ValueError("Pinned FinanceBench source tree response was truncated")
    tree_entries = tree_data.get("tree", [])
    tree_by_path = {entry.get("path"): entry for entry in tree_entries}

    source_dir = data_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    downloaded_sources = {}
    raw_base = (
        f"https://raw.githubusercontent.com/{FINANCEBENCH_GITHUB_REPOSITORY}/"
        f"{FINANCEBENCH_GITHUB_REVISION}/"
    )
    for repository_path in DATA_FILES:
        entry = tree_by_path.get(repository_path)
        if entry is None:
            raise ValueError(f"Pinned FinanceBench tree has no {repository_path}")
        filename = Path(repository_path).name
        downloaded_sources[repository_path] = _atomic_download(
            session,
            url=raw_base + quote(repository_path, safe="/"),
            destination=source_dir / filename,
            expected_size=entry["size"],
            expected_blob_sha=entry["sha"],
        )

    cases = _load_jsonl(source_dir / Path(DATA_FILES[0]).name)
    document_rows = _load_jsonl(source_dir / Path(DATA_FILES[1]).name)
    stats = validate_financebench_sources(
        cases,
        document_rows,
        tree_entries,
    )
    normalized_metadata, conflicts = normalize_document_metadata(document_rows)

    downloaded_pdfs = []
    for pdf_index, doc_name in enumerate(stats["case_documents"], start=1):
        repository_path = f"pdfs/{doc_name}.pdf"
        entry = tree_by_path[repository_path]
        pdf_metadata = _atomic_download(
            session,
            url=raw_base + quote(repository_path, safe="/"),
            destination=data_dir / "pdfs" / f"{doc_name}.pdf",
            expected_size=entry["size"],
            expected_blob_sha=entry["sha"],
            require_pdf_magic=True,
        )
        downloaded_pdfs.append(
            {
                "doc_name": doc_name,
                "company": normalized_metadata[doc_name]["company"],
                "doc_type": normalized_metadata[doc_name]["doc_type"],
                "reporting_periods": normalized_metadata[doc_name]["reporting_periods"],
                "doc_link": normalized_metadata[doc_name]["doc_link"],
                "doc_links": normalized_metadata[doc_name]["doc_links"],
                "metadata_conflicts": normalized_metadata[doc_name]["metadata_conflicts"],
                "repository_path": repository_path,
                **pdf_metadata,
            }
        )
        if pdf_index % 10 == 0 or pdf_index == len(stats["case_documents"]):
            logger.info("Verified %d/%d referenced source PDFs", pdf_index, len(stats["case_documents"]))

    manifest = {
        "schema_version": 1,
        "acquired_at_utc": datetime.now(UTC).isoformat(),
        "dataset": {
            "name": "FinanceBench public open-source sample",
            "attribution": "Patronus AI",
            "license": FINANCEBENCH_LICENSE,
            "license_url": FINANCEBENCH_LICENSE_URL,
            "huggingface_revision": FINANCEBENCH_HUGGINGFACE_REVISION,
            "github_repository": FINANCEBENCH_GITHUB_REPOSITORY,
            "github_revision": FINANCEBENCH_GITHUB_REVISION,
            "case_count": stats["case_count"],
            "document_metadata_row_count": stats["document_metadata_row_count"],
            "case_document_count": stats["unique_case_document_count"],
            "evidence_record_count": stats["evidence_record_count"],
        },
        "files": {
            "source_jsonl": downloaded_sources,
            "source_pdfs": downloaded_pdfs,
        },
        "metadata_conflicts": conflicts,
        "coverage": {
            "missing_case_documents": [],
            "pdf_count": len(downloaded_pdfs),
        },
    }
    _write_json_atomic(data_dir / "source_manifest.json", manifest)
    logger.info(
        "Verified FinanceBench acquisition: %d cases, %d source PDFs, %d metadata conflicts",
        stats["case_count"],
        len(downloaded_pdfs),
        len(conflicts),
    )
    return manifest


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    download_financebench()


if __name__ == "__main__":
    main()
