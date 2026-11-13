"""Check exact evidence-span applicability on the 2025+ corpus."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from zipfile import ZipFile

from bs4 import BeautifulSoup

from configs.offline_guard import offline_socket_guard
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.finagent_benchmark import FINAGENT_REVISION, FINAGENT_SHA256, load_finagent
from src.ingestion.sec_corpus import MAX_ARCHIVE_BYTES, SourceCache
from src.retrieval.canonical_json import sha256_file


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def evaluate(dataset: Path, manifest: Path, cache_path: Path) -> dict:
    filings = json.loads(manifest.read_bytes())["filings"]
    cache = SourceCache(cache_path, None)
    sources = []
    for filing in filings:
        archive, receipt = cache.source(filing["archive"]["url"], MAX_ARCHIVE_BYTES)
        if receipt != filing["archive"]:
            raise ValueError("Cached filing differs from the manifest")
        with ZipFile(archive) as bundle:
            soup = BeautifulSoup(bundle.read(filing["primary_document"]), "lxml")
        for tag in soup.find_all(["ix:header", "script", "style"]):
            tag.decompose()
        sources.append((filing, _normalized(soup.get_text(" ", strip=True))))
    rows = []
    for case in load_finagent(dataset):
        eligible = [filing["accession_number"] for filing, _ in sources
                    if filing["ticker"] in case.tickers and filing["form_type"] in case.forms]
        evidence = _normalized(case.evidence)
        matches = [
            filing["accession_number"] for filing, text in sources
            if filing["accession_number"] in eligible and len(evidence.split()) >= 8
            and f" {evidence} " in f" {text} "
        ]
        rows.append({"case_id": case.case_id, "eligible_accessions": eligible, "exact_excerpt_accessions": matches})
    return {
        "dataset_revision": FINAGENT_REVISION, "dataset_sha256": FINAGENT_SHA256,
        "corpus_manifest_sha256": sha256_file(manifest), "case_count": len(rows),
        "cases_with_eligible_filings": sum(bool(row["eligible_accessions"]) for row in rows),
        "cases_with_exact_excerpt_match": sum(bool(row["exact_excerpt_accessions"]) for row in rows),
        "unique_exact_matches": sum(len(row["exact_excerpt_accessions"]) == 1 for row in rows),
        "case_results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with offline_socket_guard():
        report = evaluate(args.dataset, args.manifest, args.cache)
        write_json_atomic(args.output, report)
    print(json.dumps({key: value for key, value in report.items() if key != "case_results"}, sort_keys=True))


if __name__ == "__main__":
    main()
