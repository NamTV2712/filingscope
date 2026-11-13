"""Replay a frozen SEC corpus and compare numeric observations with Company Facts."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from configs.offline_guard import offline_socket_guard
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.sec_ixbrl_evaluation import build_cohorts, compare_filing
from src.evaluation.sec_mixed_cohorts import build_mixed_cohorts
from src.ingestion.sec_corpus import MAX_METADATA_BYTES, SourceCache
from src.retrieval.canonical_json import canonical_sha256, sha256_file

MEMBERSHIP = {"pilot": {"AAPL", "AMZN"}, "development": {"GOOG", "KO", "MSFT"}, "validation": {"NVDA", "TSLA", "WMT"}}
LIMITS = {"pilot": 32, "development": 100, "validation": 72}


def evaluate(corpus: Path, cache_path: Path, *, mixed: bool = False) -> tuple[dict, dict]:
    started = perf_counter()
    manifest_path = corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    cache = SourceCache(cache_path, None)
    sources = {}
    for issuer in manifest["issuers"]:
        receipt = issuer["company_facts"]
        path, observed = cache.source(receipt["url"], MAX_METADATA_BYTES)
        if observed != receipt:
            raise ValueError("Company Facts cache receipt differs from corpus manifest")
        sources[issuer["ticker"]] = json.loads(path.read_bytes(), parse_float=Decimal)
    rows = []
    for filing in manifest["filings"]:
        facts = corpus / "facts" / f"{filing['accession_number']}.json"
        if sha256_file(facts) != filing["facts_sha256"]:
            raise ValueError("Inline XBRL extraction differs from corpus manifest")
        rows.extend(compare_filing(json.loads(facts.read_bytes())["facts"], sources[filing["ticker"]], filing))
    cohorts = build_cohorts(rows, MEMBERSHIP, LIMITS)
    indexed = {(row["accession"], row["tag"], row["start"], row["end"]): row for row in rows}
    structured = {}
    for name, cases in cohorts.items():
        controls = [indexed[case["accession"], case["tag"], case["period_start"], case["period_end"]] for case in cases]
        exact_count = sum(row["status"] == "EXACT" for row in controls)
        released = sum(len(row["company_facts_values"]) == 1 for row in controls)
        structured[name] = {"cases": len(cases), "exact": exact_count, "released": released,
                            "incorrect_releases": released - exact_count}
    statuses = Counter(row["status"] for row in rows)
    exact, mismatches = statuses["EXACT"], statuses["MISMATCH"]
    summary = {
        "corpus_manifest_sha256": sha256_file(manifest_path),
        "status": "PROVISIONAL_NOT_INDEPENDENT",
        "comparison": {
            "inline_group_count": len(rows), "status_counts": dict(statuses),
            "unique_value_pairs": exact + mismatches,
            "exact_agreement": exact / (exact + mismatches) if exact + mismatches else None,
        },
        "cohorts": {name: {"cases": len(items), "issuers": len({case["issuer_cik"] for case in items})}
                    for name, items in cohorts.items()},
        "overlap": "PASS",
        "tracks": {
            "structured_only": {"method": "Company Facts accession/period exact lookup against AUTO_XBRL labels",
                                "cohorts": structured},
            "document_only": {"status": "PDF_CELL_COMPARISON_SEPARATE"},
            "hybrid": {"status": "NOT_RUN"},
            "narrative_non_xbrl": {"status": "AWAITING_HUMAN_VERIFIED_LABELS"},
        },
        "resources": {"wall_seconds": round(perf_counter() - started, 3), "peak_memory_bytes": peak_memory_bytes(),
                      "provider_calls": 0, "provider_tokens": 0, "provider_cost_usd": 0},
    }
    if mixed:
        cohorts, diagnostic = build_mixed_cohorts(rows, manifest["filings"], corpus, cache, MEMBERSHIP, LIMITS, sources)
        summary["cohorts"] = {
            name: {"cases": len(items), "issuers": len({doc["cik"] for case in items for doc in case["documents"]}),
                   "categories": dict(Counter(case["category"] for case in items)),
                   "label_provenance": dict(Counter(case["label_provenance"] for case in items)),
                   "cases_sha256": canonical_sha256(items)}
            for name, items in cohorts.items()
        }
        summary["tracks"] = {
            "structured_only": {"method": "Company Facts exact accession, concept, currency and interval lookup",
                                "by_cohort_and_category": diagnostic},
            "document_only": {"status": "NOT_RUN_ON_MIXED_COHORTS"},
            "hybrid": {"status": "NOT_RUN_ON_MIXED_COHORTS"},
            "narrative_non_xbrl": {"status": "AUTHOR_CHECKED_REFERENCES_PREDICTIONS_NOT_RUN"},
        }
        summary["resources"].update(wall_seconds=round(perf_counter() - started, 3), peak_memory_bytes=peak_memory_bytes())
    return {"summary": summary, "comparisons": rows}, cohorts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mixed-cohorts", action="store_true", help="Build the issuer-disjoint mixed evaluation cohorts")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use a fresh output directory")
    with offline_socket_guard():
        comparison, cohorts = evaluate(args.corpus, args.cache, mixed=args.mixed_cohorts)
    write_json_atomic(args.output / "comparison.json", comparison)
    for name, cases in cohorts.items():
        cohort = {
            "status": "PROVISIONAL_NOT_INDEPENDENT",
            "corpus_manifest_sha256": comparison["summary"]["corpus_manifest_sha256"],
            "cases": cases,
        }
        if args.mixed_cohorts:
            cohort["schema"] = "filingscope-sec-mixed-cohort-v1"
            cohort["cases_sha256"] = comparison["summary"]["cohorts"][name]["cases_sha256"]
        write_json_atomic(args.output / f"{name}.json", cohort)
    print(json.dumps(comparison["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
