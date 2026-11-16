"""Prepare the internally authored, frozen Ford/Chevron FY2024 cohort."""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import requests

from scripts.prepare_independent_corpus import FilingInput, prepare
from src.evaluation.benchmark_io import write_json_atomic
from src.retrieval.canonical_json import canonical_json_bytes, sha256_file


SOURCES = (
    {
        "document_id": "F_FY2024_10K", "company": "Ford Motor Company", "ticker": "F", "cik": 37996,
        "filed": "2025-02-06", "accession": "0000037996-25-000013",
        "source_url": "https://www.sec.gov/Archives/edgar/data/37996/000003799625000013/f-20241231.htm",
        "pdf_url": "https://d18rn0p25nwr6d.cloudfront.net/CIK-0000037996/84a96449-fb41-499a-9b18-db6f76998e81.pdf",
        "document_sha256": "sha256:9b4a74ac0a3395513e239084d9b1d7f5f45e481611d9dbfefe1014f3b77c6cb8",
        "page_index": 113, "printed_page": "109", "column_order": [2023, 2024],
        "values": {"total assets": 285196, "total current assets": 124474, "total liabilities": 240338,
                   "total current liabilities": 106859, "cash and cash equivalents": 22935},
        "segment": "Ford Blue",
    },
    {
        "document_id": "CVX_FY2024_10K", "company": "Chevron Corporation", "ticker": "CVX", "cik": 93410,
        "filed": "2025-02-21", "accession": "0000093410-25-000009",
        "source_url": "https://www.sec.gov/Archives/edgar/data/93410/000009341025000009/cvx-20241231.htm",
        "pdf_url": "https://www.annualreports.com/HostedData/AnnualReportArchive/c/NYSE_CVX_2024.pdf",
        "document_sha256": "sha256:0044b0f397d47c70ca34c572002b0f21a9a575e411ac20a2d612fe642eb56983",
        "page_index": 57, "printed_page": "56", "column_order": [2024, 2023],
        "values": {"total assets": 256938, "total current assets": 40911, "total liabilities": 103781,
                   "total current liabilities": 38558, "cash and cash equivalents": 6781},
        "segment": "U.S. upstream",
    },
)


def cohort_rows():
    """Return authored questions and source-reviewed labels without runtime output."""
    questions, labels = [], []
    for source in SOURCES:
        company, ticker = source["company"], source["ticker"]
        locator = f"{source['document_id']}#p{source['page_index']}"
        evidence = {"document_id": source["document_id"], "source": locator, "page_index": source["page_index"],
                    "printed_page": source["printed_page"], "table": "Consolidated Balance Sheet",
                    "column": "December 31, 2024", "currency": "USD", "scale": "million",
                    "accession": source["accession"], "basis": "consolidated", "relation": "=",
                    "review": "Internal source review of the frozen PDF balance-sheet rows; development-exposed."}
        for position, metric in enumerate(("total assets", "total current assets", "total liabilities", "total current liabilities"), 1):
            case_id = f"{ticker}-lookup-{position}"
            questions.append({"case_id": case_id, "category": "lookup", "issuer_ciks": [source["cik"]],
                              "question": f"What were {company}'s {metric} at December 31, 2024?"})
            labels.append({"case_id": case_id, "category": "lookup", "answerable": True,
                           "value": str(Decimal(source["values"][metric]) * 1000000), "kind": "amount",
                           "metric": metric, "evidence": [{**evidence, "row": metric, "raw_value": str(source["values"][metric])}],
                           "rounding": "exact filed amount in USD millions"})
        pairs = (("cash and cash equivalents", "total assets"), ("total current assets", "total assets"),
                 ("total liabilities", "total assets"), ("total current liabilities", "total liabilities"))
        for position, (numerator, denominator) in enumerate(pairs, 1):
            case_id = f"{ticker}-percentage-{position}"
            questions.append({"case_id": case_id, "category": "percentage", "issuer_ciks": [source["cik"]],
                              "question": f"At December 31, 2024, what percentage of {company}'s {denominator} was {numerator}?"})
            result = (Decimal(source["values"][numerator]) / Decimal(source["values"][denominator]) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            labels.append({"case_id": case_id, "category": "percentage", "answerable": True,
                           "value": str(result), "kind": "percent", "metric": f"{numerator} / {denominator}",
                           "evidence": [{**evidence, "row": metric, "role": role, "raw_value": str(source["values"][metric])}
                                        for role, metric in (("numerator", numerator), ("denominator", denominator))],
                           "rounding": "Decimal ROUND_HALF_UP to two decimal places"})
        negatives = (
            (f"What were {company}'s total assets at December 31, 2030?", "The frozen FY2024 filing has no FY2030 balances."),
            (f"What were {company}'s total assets in euros at December 31, 2024?", "The statement reports USD and supplies no exchange rate or euro balance."),
            (f"What were {company}'s {source['segment']} segment cash and cash equivalents at December 31, 2024?", "The filing discloses consolidated cash, but the requested segment-specific cash measure is absent from its segment disclosures."),
            (f"What were {company}'s restated total assets at December 31, 2024, as corrected in its 2025 Form 10-K/A?", "The bundle includes the original Form 10-K and contains no correcting Form 10-K/A."),
        )
        for position, (question, reason) in enumerate(negatives, 1):
            case_id = f"{ticker}-unanswerable-{position}"
            questions.append({"case_id": case_id, "category": "unanswerable", "issuer_ciks": [source["cik"]], "question": question})
            labels.append({"case_id": case_id, "category": "unanswerable", "answerable": False, "reason": reason, "evidence": []})
    return questions, labels


def _write_rows(path: Path, rows):
    path.write_bytes(b"".join(canonical_json_bytes(row) + b"\n" for row in rows))


def prepare_inputs(bundle: Path, *, acquire: bool = False):
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "filings").mkdir(exist_ok=True)
    if (bundle / "transfer-freeze.json").exists():
        raise ValueError("The transfer cohort is already frozen; reuse its files without rewriting them")
    preindex = bundle / "preindex-freeze.json"
    if preindex.exists():
        expected = json.loads(preindex.read_text(encoding="utf-8"))
        if any(sha256_file(bundle / name) != digest for name, digest in expected.items()):
            raise ValueError("Prepared cohort changed after its pre-index freeze")
        return [FilingInput.model_validate(row) for row in json.loads((bundle / "filing-inventory.json").read_text(encoding="utf-8"))]
    inventory = []
    for source in SOURCES:
        path = bundle / "filings" / f"{source['document_id']}.pdf"
        if not path.is_file() and acquire:
            response = requests.get(source["pdf_url"], headers={"User-Agent": "FilingScope-public-research/1.0"}, timeout=60)
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise ValueError("The source returned a non-PDF response")
            path.write_bytes(response.content)
        if sha256_file(path) != source["document_sha256"]:
            raise ValueError(f"PDF differs from the source-reviewed input: {path.name}")
        fields = {key: source[key] for key in ("document_id", "company", "ticker", "cik", "filed", "accession", "source_url", "document_sha256")}
        inventory.append(FilingInput(**fields, form="10-K", fiscal_year=2024))
    write_json_atomic(bundle / "filing-inventory.json", [row.model_dump(mode="json") for row in inventory])
    questions, labels = cohort_rows()
    _write_rows(bundle / "questions.jsonl", questions)
    _write_rows(bundle / "labels.jsonl", labels)
    write_json_atomic(bundle / "transfer-sources.json", SOURCES)
    write_json_atomic(preindex, {name: sha256_file(bundle / name) for name in (
        "filing-inventory.json", "questions.jsonl", "labels.jsonl", "transfer-sources.json",
    )})
    return inventory


def freeze_cohort(bundle: Path) -> dict:
    """Bind prepared evidence and preserve any earlier question/label receipt."""
    destination = bundle / "transfer-freeze.json"
    if destination.exists():
        raise ValueError("The transfer cohort is already frozen")
    preindex = bundle / "preindex-freeze.json"
    if preindex.exists():
        expected = json.loads(preindex.read_text(encoding="utf-8"))
        if any(sha256_file(bundle / name) != digest for name, digest in expected.items()):
            raise ValueError("Prepared cohort changed after its pre-index freeze")
    files = ("corpus.json", "filing-inventory.json", "questions.jsonl", "labels.jsonl", "transfer-sources.json")
    freeze = {"cohort": "Ford/Chevron FY2024", "status": "INTERNAL_DEVELOPMENT_EXPOSED", "cutoff": "2025-12-31",
              "threads": 6, "cases": 24, "answerable": 16, "unanswerable": 8,
              "success": {"grounded_answerable_minimum": 12, "correct_abstentions": 8, "known_release_errors": 0},
              "files": {name: sha256_file(bundle / name) for name in files}}
    write_json_atomic(destination, freeze)
    return freeze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path("data/transfer-fy2024"))
    parser.add_argument("--acquire", action="store_true")
    parser.add_argument("--index", action="store_true")
    args = parser.parse_args()
    inventory = prepare_inputs(args.bundle, acquire=args.acquire)
    if args.index:
        import torch
        from configs.financebench import P1_EMBEDDING_REVISION
        from configs.offline_guard import offline_socket_guard
        from src.retrieval.embedder import Embedder
        with offline_socket_guard():
            torch.set_num_threads(6)
            prepare(args.bundle, inventory, date(2025, 12, 31), Embedder(device="cpu", revision=P1_EMBEDDING_REVISION))
    if not (args.bundle / "corpus.json").is_file():
        raise ValueError("Prepare the frozen index before creating the cohort freeze")
    freeze_cohort(args.bundle)
    print(sha256_file(args.bundle / "transfer-freeze.json"))


if __name__ == "__main__":
    main()
