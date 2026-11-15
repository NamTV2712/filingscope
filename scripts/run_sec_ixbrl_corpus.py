"""Acquire or replay a bounded 2025+ SEC Inline XBRL corpus."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from contextlib import nullcontext
from datetime import date
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from configs.offline_guard import offline_socket_guard
from configs.settings import settings
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.ingestion.company_facts import normalize_cik
from src.ingestion.inline_xbrl import SEC_TRANSFORM_FILES, SEC_TRANSFORM_REVISION, extract_numeric_facts
from src.ingestion.sec_client import EdgarNotFoundError, SECEdgarClient
from src.ingestion.sec_corpus import (
    FORMS, MAX_ARCHIVE_BYTES, MAX_METADATA_BYTES, SEC_FIRST_FILED,
    SourceCache, filing_record, filings_from_submissions, revision_links,
)
from src.retrieval.canonical_json import sha256_file


def build(args, client: SECEdgarClient | None) -> tuple[dict, dict]:
    cache = SourceCache(args.cache, client)
    filings, unavailable, issuers = [], [], []
    resources = {}
    for ticker, cik in sorted(args.issuer):
        normalized = normalize_cik(cik)
        path, submissions = cache.source(SECEdgarClient.SUBMISSIONS_URL_TEMPLATE.format(cik=normalized), MAX_METADATA_BYTES)
        metadata = json.loads(path.read_bytes())
        scope = {"cik": cik, "ticker": ticker, "cutoff": args.cutoff, "forms": frozenset(args.form)}
        available = filings_from_submissions(metadata, **scope)
        links = revision_links(available)
        if args.current_report_item is not None:
            available = filings_from_submissions(metadata, current_report_item=args.current_report_item, **scope)
        _, company_facts = cache.source(SECEdgarClient.COMPANY_FACTS_URL_TEMPLATE.format(cik=normalized), MAX_METADATA_BYTES)
        issuers.append({"ticker": ticker, "cik": normalized, "submissions": submissions, "company_facts": company_facts})
        selected = [filing for form in sorted(set(args.form))
                    for filing in [row for row in available if row.form_type == form][:args.per_form]]
        for filing in selected:
            accession = filing.accession_number
            folder = filing.filing_url.rsplit("/", 1)[0]
            url = f"{folder}/{accession}-xbrl.zip"
            try:
                archive, receipt = cache.source(url, MAX_ARCHIVE_BYTES)
            except (EdgarNotFoundError, FileNotFoundError) as error:
                # Cache confirmed negative results only. A missing replay cache
                # remains an error unless acquisition recorded the absence.
                missing = args.cache / "missing" / f"{accession}.json"
                if isinstance(error, EdgarNotFoundError):
                    write_json_atomic(missing, {"url": url, "http_status": 404})
                if not missing.is_file() or json.loads(missing.read_bytes()) != {"url": url, "http_status": 404}:
                    raise
                unavailable.append({**filing_record(filing, {"url": url}, links), "status": "NO_XBRL_ARCHIVE"})
                continue
            started = perf_counter()
            with offline_socket_guard():
                extraction = extract_numeric_facts(
                    archive, filing, cache_directory=args.cache / "arelle", sec_transforms=args.sec_transforms,
                )
            resources[accession] = {"extract_ms": round((perf_counter() - started) * 1000, 3)}
            facts_path = args.output / "facts" / f"{accession}.json"
            write_json_atomic(facts_path, extraction)
            filings.append({
                **filing_record(filing, receipt, links), "facts_sha256": sha256_file(facts_path),
                "numeric_observations": len(extraction["facts"]),
                "dimensioned_observations": sum(bool(row["identity"]["dimensions"]) for row in extraction["facts"]),
                "skipped": extraction["skipped"],
            })
    manifest = {
        "schema": "filingscope-sec-ixbrl-corpus-v1", "first_filed": SEC_FIRST_FILED.isoformat(),
        "cutoff": args.cutoff.isoformat(), "arelle_version": version("arelle-release"),
        "forms": sorted(set(args.form)), "max_per_form_per_issuer": args.per_form,
        "issuers": issuers, "filings": filings, "unavailable_filings": unavailable,
    }
    if args.current_report_item is not None:
        manifest["current_report_item"] = args.current_report_item
    if args.sec_transforms is not None:
        manifest["sec_transforms"] = {"revision": SEC_TRANSFORM_REVISION, "files": SEC_TRANSFORM_FILES}
    telemetry = {"by_accession": resources, "request_attempts": client.request_count if client else 0,
                 "peak_memory_bytes": peak_memory_bytes(), "provider_cost_usd": 0}
    return manifest, telemetry


def _issuer(value: str) -> tuple[str, int]:
    ticker, separator, cik = value.partition("=")
    if not separator or not ticker.strip():
        raise argparse.ArgumentTypeError("Supply TICKER=CIK")
    try:
        return ticker.upper().strip(), int(normalize_cik(cik))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected a numeric CIK") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", action="append", required=True, type=_issuer)
    parser.add_argument("--form", action="append", choices=sorted(FORMS), required=True)
    parser.add_argument("--current-report-item", help="Filter 8-K and 8-K/A by EDGAR item code, such as 2.02")
    parser.add_argument("--cutoff", type=date.fromisoformat, required=True)
    parser.add_argument("--per-form", type=int, default=1)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sec-transforms", type=Path, help="Directory containing the pinned SEC Inline Transforms source files")
    parser.add_argument("--acquire", action="store_true")
    args = parser.parse_args()
    ciks = {cik for _, cik in args.issuer}
    tickers = {ticker for ticker, _ in args.issuer}
    if not 1 <= args.per_form <= 5 or len(ciks) != len(args.issuer) or len(tickers) != len(args.issuer):
        parser.error("Use unique issuers and 1–5 filings per form")
    if not SEC_FIRST_FILED <= args.cutoff <= date.today():
        parser.error("Cutoff must fall between 2025-01-01 and today")
    if args.current_report_item is not None and (
        not re.fullmatch(r"[1-9]\.[0-9]{2}", args.current_report_item) or not {"8-K", "8-K/A"}.intersection(args.form)
    ):
        parser.error("A current report item requires an EDGAR item code and an 8-K or 8-K/A form")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use a fresh output directory")
    client = SECEdgarClient(settings.sec_user_agent) if args.acquire else None
    started = perf_counter()
    with nullcontext() if args.acquire else offline_socket_guard():
        manifest, telemetry = build(args, client)
    telemetry["wall_seconds"] = round(perf_counter() - started, 3)
    write_json_atomic(args.output / "manifest.json", manifest)
    write_json_atomic(args.output / "resources.json", telemetry)
    print(json.dumps({
        "filings": len(manifest["filings"]), "unavailable": len(manifest["unavailable_filings"]),
        "forms": dict(Counter(row["form_type"] for row in manifest["filings"])),
        "observations": sum(row["numeric_observations"] for row in manifest["filings"]),
        "requests": telemetry["request_attempts"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
