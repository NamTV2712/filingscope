"""Bounded acquisition and content-addressed replay of SEC filing sources."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from src.ingestion.company_facts import normalize_cik
from src.ingestion.sec_client import FilingMetadata, SECEdgarClient
from src.retrieval.canonical_json import canonical_json_bytes, sha256_file

SEC_FIRST_FILED = date(2025, 1, 1)
FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A"})
ACCESSION = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")
PRIMARY_DOCUMENT = re.compile(r"[a-zA-Z0-9_-][a-zA-Z0-9_.-]*\.html?")
MAX_METADATA_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024


class SourceCache:
    def __init__(self, root: Path, client: SECEdgarClient | None):
        self.root = root
        self.client = client

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(payload)
                stream.close()
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)

    def source(self, url: str, max_bytes: int) -> tuple[Path, dict]:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        extension = ".zip" if url.endswith(".zip") else ".blob"
        receipt = self.root / "urls" / f"{key}.json"
        if receipt.is_file():
            record = json.loads(receipt.read_bytes())
            digest = record.get("sha256")
            if record.get("url") != url or not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                raise ValueError(f"Invalid cache receipt for {url}")
            path = self.root / "sha256" / f"{digest[7:]}{extension}"
            if (not path.is_file() or path.stat().st_size > max_bytes
                    or path.stat().st_size != record["size"] or sha256_file(path) != digest):
                raise ValueError(f"Corrupt or oversized cached SEC source: {url}")
            return path, record
        if self.client is None:
            raise FileNotFoundError(f"SEC source is absent from the offline cache: {url}")
        payload = self.client.fetch_bounded(url, max_bytes=max_bytes)
        digest = hashlib.sha256(payload).hexdigest()
        path = self.root / "sha256" / f"{digest}{extension}"
        record = {"url": url, "sha256": f"sha256:{digest}", "size": len(payload)}
        self._atomic_write(path, payload)
        self._atomic_write(receipt, canonical_json_bytes(record))
        return path, record


def filings_from_submissions(
    payload: dict, *, cik: int, ticker: str, cutoff: date, forms: frozenset[str],
) -> list[FilingMetadata]:
    if normalize_cik(payload["cik"]) != normalize_cik(cik):
        raise ValueError("SEC Submissions CIK mismatch")
    recent = payload["filings"]["recent"]
    rows = []
    for form, accession, filed, report, primary in zip(
        recent["form"], recent["accessionNumber"], recent["filingDate"],
        recent["reportDate"], recent["primaryDocument"], strict=True,
    ):
        if form not in forms or not SEC_FIRST_FILED <= date.fromisoformat(filed) <= cutoff:
            continue
        if not ACCESSION.fullmatch(accession) or not PRIMARY_DOCUMENT.fullmatch(primary):
            continue
        if not report or date.fromisoformat(report) > date.fromisoformat(filed):
            continue
        rows.append(FilingMetadata(ticker, cik, form, accession, filed, report, primary))
    return sorted(rows, key=lambda row: (row.filing_date, row.accession_number), reverse=True)


def revision_links(filings: list[FilingMetadata]) -> dict[str, dict]:
    result = {}
    for filing in filings:
        if not filing.form_type.endswith("/A"):
            continue
        candidates = [
            row for row in filings if row.cik == filing.cik and row.report_date == filing.report_date
            and row.form_type == filing.form_type.removesuffix("/A") and row.filing_date <= filing.filing_date
        ]
        result[filing.accession_number] = {
            "status": "UNIQUE_SAME_PERIOD_FORM" if len(candidates) == 1 else "UNRESOLVED",
            "original_accession": candidates[0].accession_number if len(candidates) == 1 else None,
        }
    return result


def filing_record(filing: FilingMetadata, archive: dict, links: dict) -> dict:
    return {
        **asdict(filing), "source_url": filing.filing_url, "archive": archive,
        "amendment_relationship": links.get(filing.accession_number),
    }
