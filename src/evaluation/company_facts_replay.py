"""Local Company Facts snapshots for reproducible specialist comparisons."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.ingestion.sec_client import SECEdgarClient


def _file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def acquire_company_facts(
    directory: Path, issuers: dict[str, int], *, latest_filed: str, user_agent: str,
) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    if manifest_path.is_file():
        replay = CompanyFactsReplay(directory, issuers, latest_filed=latest_filed)
        return replay.manifest
    client = SECEdgarClient(user_agent, ticker_cik_overrides=issuers)
    files = {}
    for ticker, cik in issuers.items():
        path = directory / f"CIK{cik:010d}.json"
        if path.is_file():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing["cik"] != cik or not _within_cutoff(existing, latest_filed):
                raise ValueError(f"Existing snapshot identity or cutoff differs for {ticker}")
        else:
            payload = client.get_company_facts(cik)
            if payload["cik"] != cik:
                raise ValueError(f"SEC payload CIK differs for {ticker}")
            for taxonomy in payload["facts"].values():
                for concept in taxonomy.values():
                    concept["units"] = {
                        unit: [row for row in rows if row.get("filed", "9999-12-31") <= latest_filed]
                        for unit, rows in concept["units"].items()
                    }
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)
        files[ticker] = {
            "cik": cik, "file": path.name, "sha256": _file_sha256(path),
            "source_url": client.COMPANY_FACTS_URL_TEMPLATE.format(cik=f"{cik:010d}"),
        }
    manifest = {"acquired_at_utc": datetime.now(UTC).isoformat(), "latest_filed": latest_filed, "issuers": files}
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


def _within_cutoff(payload: dict[str, Any], latest_filed: str) -> bool:
    return all(
        row.get("filed", "9999-12-31") <= latest_filed
        for taxonomy in payload["facts"].values()
        for concept in taxonomy.values()
        for rows in concept["units"].values()
        for row in rows
    )


class CompanyFactsReplay:
    """Implement the SEC worker's client contract without timed HTTP calls."""

    def __init__(self, directory: Path, issuers: dict[str, int], *, latest_filed: str):
        self.manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if self.manifest["latest_filed"] != latest_filed:
            raise ValueError("Unexpected Company Facts cutoff")
        self.issuers = dict(issuers)
        self.facts = {}
        self.request_count = 0
        for ticker, cik in issuers.items():
            record = self.manifest["issuers"][ticker]
            expected_name = f"CIK{cik:010d}.json"
            expected_url = SECEdgarClient.COMPANY_FACTS_URL_TEMPLATE.format(cik=f"{cik:010d}")
            if record["cik"] != cik or record["file"] != expected_name or record["source_url"] != expected_url:
                raise ValueError(f"Invalid Company Facts provenance for {ticker}")
            path = directory / expected_name
            if _file_sha256(path) != record["sha256"]:
                raise ValueError(f"Company Facts snapshot hash differs for {ticker}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload["cik"] != cik or not _within_cutoff(payload, latest_filed):
                raise ValueError(f"Company Facts payload CIK or cutoff differs for {ticker}")
            self.facts[cik] = payload

    def get_cik(self, ticker: str) -> int:
        return self.issuers[ticker]

    @staticmethod
    def estimated_company_facts_requests(ticker: str) -> int:
        return 1

    def get_company_facts(self, cik: int) -> dict[str, Any]:
        self.request_count += 1
        return self.facts[cik]
