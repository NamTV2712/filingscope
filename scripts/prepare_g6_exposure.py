"""Generate an offline draft of known development exposure for reviewer verification."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from configs.offline_guard import offline_socket_guard
from configs.sec_runtime_pilot import PDFS
from configs.sec_snapshots import SEC_CUTOFF, SEC_ISSUERS
from configs.tickers import TICKER_CIK_OVERRIDES
from scripts.run_sec_runtime_pilot import _load_manifest
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.finagent_benchmark import load_finagent
from src.evaluation.independent_final import Filing, Membership
from src.ingestion.sec_client import SECEdgarClient
from src.ingestion.sec_corpus import MAX_METADATA_BYTES, SourceCache
from src.retrieval.canonical_json import canonical_json_bytes, sha256_file

# FinanceBench company labels use short names, including delisted issuers.
FINANCEBENCH_TICKERS = {
    "3M": "MMM", "AES Corporation": "AES", "AMD": "AMD", "Activision Blizzard": "ATVI", "Adobe": "ADBE",
    "Amazon": "AMZN", "Amcor": "AMCR", "American Express": "AXP", "American Water Works": "AWK", "Best Buy": "BBY",
    "Block": "XYZ", "Boeing": "BA", "CVS Health": "CVS", "Coca-Cola": "KO", "Corning": "GLW", "Costco": "COST",
    "Foot Locker": "FL", "General Mills": "GIS", "JPMorgan": "JPM", "Johnson & Johnson": "JNJ", "Kraft Heinz": "KHC",
    "Lockheed Martin": "LMT", "MGM Resorts": "MGM", "Microsoft": "MSFT", "Netflix": "NFLX", "Nike": "NKE",
    "Paypal": "PYPL", "PepsiCo": "PEP", "Pfizer": "PFE", "Ulta Beauty": "ULTA", "Verizon": "VZ", "Walmart": "WMT",
}
HISTORICAL_CIKS = {**TICKER_CIK_OVERRIDES, "ATVI": 718877, "FL": 850209, "CTRA": 858470}
FINANCEBENCH_MANIFEST_HASH = "sha256:7fa1bbc5ca0298ebce98e7aea369acc2bb4c6a23615b6f18ef8ffa7ace281dee"
FINRANK_HASH = "sha256:e9295f680bd6085362486c90c170bce243be7f85ed18074d6ba21cb75141ac78"
SEC_TICKER_MAP_HASH = "sha256:391effc6a807ae1752c9d2c351dbecab8f15aa1c59b035a9a28f7955a94feb0f"


def _resolve(tickers: set[str], current: dict[str, int]) -> dict[str, int]:
    mapping = {**current, **HISTORICAL_CIKS}
    if missing := tickers - mapping.keys():
        raise ValueError(f"Unresolved exposed tickers: {', '.join(sorted(missing))}")
    return {ticker: mapping[ticker] for ticker in sorted(tickers)}


def _issuer_group(resolved: dict[str, int], current: dict[str, int]) -> set[int]:
    # Exclude both identities when a present-day mapping differs from the filing-era CIK.
    return set(resolved.values()) | {current[ticker] for ticker in resolved if ticker in current}


def _membership(cohort: str, ciks, documents, through: str) -> Membership:
    return Membership(cohort=cohort, issuer_ciks=tuple(sorted(set(ciks))),
                      document_ids=tuple(sorted(set(documents))), through=date.fromisoformat(through))


def _prepare(financebench: Path, g2: Path, finagent: Path, finrank: Path, external_inventory: Path, ticker_cache: Path):
    if sha256_file(financebench) != FINANCEBENCH_MANIFEST_HASH or sha256_file(finrank) != FINRANK_HASH:
        raise ValueError("FinanceBench or FinRank input differs from the recorded snapshot")
    ticker_path, ticker_receipt = SourceCache(ticker_cache, None).source(SECEdgarClient.TICKER_MAP_URL, MAX_METADATA_BYTES)
    if ticker_receipt["sha256"] != SEC_TICKER_MAP_HASH:
        raise ValueError("SEC ticker map differs from the recorded snapshot")
    ticker_rows = json.loads(ticker_path.read_bytes())
    ticker_map = {row["ticker"]: row["cik_str"] for row in ticker_rows.values()}

    docs = json.loads(financebench.read_bytes())["files"]["source_pdfs"]
    financebench_ciks = _resolve({FINANCEBENCH_TICKERS[row["company"]] for row in docs}, ticker_map)
    financebench_docs = defaultdict(list)
    for row in docs:
        financebench_docs[FINANCEBENCH_TICKERS[row["company"]]].append(row["doc_name"])
    manifest = _load_manifest(g2)
    g2_filings = manifest["filings"]
    g2_issuers = {row["ticker"]: int(row["cik"]) for row in manifest["issuers"]}
    finagent_ciks = _resolve({ticker for row in load_finagent(finagent) for ticker in row.tickers}, ticker_map)
    finrank_rows = [json.loads(line) for line in finrank.read_text(encoding="utf-8").splitlines() if line.strip()]
    finrank_ciks = _resolve({row["ticker"] for row in finrank_rows}, ticker_map)
    external = [Filing.model_validate({key: row[key] for key in Filing.model_fields})
                for row in json.loads(external_inventory.read_bytes())]
    if not external:
        raise ValueError("The local FinRank filing inventory is empty")

    memberships = [
        _membership("FinanceBench_P1_P5_M13_Q2_Q7", _issuer_group(financebench_ciks, ticker_map) | set(SEC_ISSUERS.values()),
                    (row["doc_name"] for row in docs), SEC_CUTOFF),
        _membership("G2_G3_G5_SEC_pilot", g2_issuers.values(), (pdf.name for pdf in PDFS), manifest["cutoff"]),
        _membership("FinAgent_v1.1.1", _issuer_group(finagent_ciks, ticker_map), (), manifest["cutoff"]),
        _membership("FinRank_public_and_local_sources", _issuer_group(finrank_ciks, ticker_map) | {row.cik for row in external},
                    (row.document_id for row in external), max(row.filed.isoformat() for row in external)),
    ]
    return memberships, {
        "status": "DRAFT_FOR_REVIEWER_VERIFICATION",
        "sources": {name: sha256_file(path) for name, path in {
            "financebench": financebench, "g2_sec": g2, "finagent": finagent, "finrank": finrank,
            "finrank_local_filing_inventory": external_inventory,
        }.items()},
        "sec_ticker_map": ticker_receipt,
        "financebench_issuers": financebench_ciks,
        "financebench_document_ids_by_ticker": dict(sorted(financebench_docs.items())),
        "g2_issuers": g2_issuers,
        "g2_accessions": {row["accession_number"]: row["cik"] for row in g2_filings},
        "finagent_issuers": finagent_ciks, "finrank_issuers": finrank_ciks,
        "also_excluded_current_ciks": {ticker: ticker_map[ticker] for ticker, cik in HISTORICAL_CIKS.items()
                                       if ticker in ticker_map and ticker_map[ticker] != cik},
        "finrank_local_accessions": {row.accession: row.cik for row in external},
        "review_required": [
            "Verify historical aliases, former issuers and corporate-successor groups.",
            "Check actual filing-date ceilings. FinAgent excerpt metadata has no complete accession list. "
            "FinRank year labels do not establish filed dates; its draft date covers locally identified filings only.",
            "Add issuers and documents from reviewer-known or undocumented development exposures.",
        ],
        "unique_issuer_count": len({cik for member in memberships for cik in member.issuer_ciks}),
        "document_id_count": len({doc for member in memberships for doc in member.document_ids}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--financebench", type=Path, default=Path("data/financebench/source_manifest.json"))
    parser.add_argument("--g2", type=Path, default=Path("docs/G2_SEC_CORPUS_MANIFEST.json"))
    parser.add_argument("--finagent", type=Path, default=Path(".local/g2/finagent-v1.1.1.json"))
    parser.add_argument("--finrank", type=Path, default=Path("data/independent-final/public-sources/FinRank.jsonl"))
    parser.add_argument("--external-inventory", type=Path, default=Path("data/independent-final/finrank-2025/filing-inventory.json"))
    parser.add_argument("--ticker-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with offline_socket_guard():
        memberships, report = _prepare(args.financebench, args.g2, args.finagent, args.finrank,
                                       args.external_inventory, args.ticker_cache)
        args.output.mkdir(parents=True, exist_ok=False)
        draft = args.output / "draft-exposed.jsonl"
        with draft.open("xb") as stream:
            for member in memberships:
                stream.write(canonical_json_bytes(member.model_dump(mode="json")) + b"\n")
        report["draft_exposed_sha256"] = sha256_file(draft)
        write_json_atomic(args.output / "report.json", report)
    print(f"Draft exposure inventory: {report['unique_issuer_count']} issuers and {report['document_id_count']} document IDs")


if __name__ == "__main__":
    main()
