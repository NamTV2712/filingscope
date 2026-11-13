"""Compare six published Apple FY2025 PDF statement cells with iXBRL."""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from configs.offline_guard import offline_socket_guard
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.ingestion.pdf_ingestion import extract_pdf_pages
from src.retrieval.canonical_json import sha256_file

PDF_SHA256 = "sha256:43e7f0730b3cce0fc37301a2f43c29712bbde6ab299d97c6df345fd0c754508a"
PDF_URL = "https://www.apple.com/newsroom/pdfs/fy2025-q4/FY25_Q4_Consolidated_Financial_Statements.pdf"
ACCESSION = "0000320193-25-000079"
CELLS = {
    "Total net sales (1)": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Gross margin": "GrossProfit",
    "Research and development": "ResearchAndDevelopmentExpense",
    "Operating income": "OperatingIncomeLoss",
    "Income before provision for income taxes":
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "Net income": "NetIncomeLoss",
}


def evaluate(pdf: Path, comparison: Path) -> dict:
    started = perf_counter()
    if sha256_file(pdf) != PDF_SHA256:
        raise ValueError("Expected the frozen Apple financial statements PDF")
    report = json.loads(comparison.read_bytes())
    controls = {
        row["tag"]: row for row in report["comparisons"]
        if row["accession"] == ACCESSION and row["start"] == "2024-09-29" and row["end"] == "2025-09-27"
    }
    page = extract_pdf_pages(pdf)[0]
    rows = []
    for label, tag in CELLS.items():
        amounts = next((re.findall(r"-?[0-9,]+", line.strip()[len(label):]) for line in page["text"].splitlines()
                        if line.strip().startswith(f"{label} ")), [])
        value = Decimal(amounts[2].replace(",", "")) * 1_000_000 if len(amounts) == 4 else None
        control = controls.get(tag, {})
        inline_values = [Decimal(item) for item in control.get("inline_values", ())]
        rows.append({
            "row_label": label, "tag": tag, "pdf_value": str(value) if value is not None else None,
            "pdf_page": page["page_number"], "ixbrl_values": control.get("inline_values", []),
            "company_facts_values": control.get("company_facts_values", []),
            "exact": value is not None and inline_values == [value] and control["status"] == "EXACT",
        })
    return {
        "pdf_url": PDF_URL, "pdf_sha256": PDF_SHA256, "accession": ACCESSION,
        "comparison_sha256": sha256_file(comparison), "rows": rows,
        "exact": sum(row["exact"] for row in rows), "denominator": len(rows),
        "resources": {"wall_ms": round((perf_counter() - started) * 1000, 3),
                      "peak_memory_bytes": peak_memory_bytes(), "provider_cost_usd": 0},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--comparison", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with offline_socket_guard():
        report = evaluate(args.pdf, args.comparison)
        write_json_atomic(args.output, report)
    print(f"Exact PDF, iXBRL and Company Facts cells: {report['exact']}/{report['denominator']}")


if __name__ == "__main__":
    main()
