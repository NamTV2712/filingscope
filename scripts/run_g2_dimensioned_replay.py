"""Compare exact iXBRL dimension lookups with PDF cells and Company Facts."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from configs.offline_guard import offline_socket_guard
from configs.sec_runtime_pilot import APPLE, NVIDIA, STATUS, TESLA, WALMART, StatementCell
from scripts.run_sec_runtime_pilot import _check_pdf_cell, _load_manifest
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.sec_ixbrl_evaluation import ISO_USD, company_facts_values
from src.ingestion.company_facts import normalize_cik
from src.ingestion.inline_xbrl import Dimension, FactIdentity, resolve_inline_fact
from src.ingestion.sec_client import FilingMetadata
from src.ingestion.sec_corpus import MAX_METADATA_BYTES, SourceCache
from src.retrieval.canonical_json import sha256_file
from src.retrieval.pdf_page_cache import FrozenPdfPages

PAGE_HASH = "sha256:f4ffa093f7b0f325eda948e82288050207d03e814abded4e1a903fe2bd5341b5"
SALES = "RevenueFromContractWithCustomerExcludingAssessedTax"


@dataclass(frozen=True)
class Control:
    id: str
    cell: StatementCell
    axis: str
    member: str
    taxonomy_year: int = 2024


def _control(id, pdf, page, row, value, concept, start, end, axis, member, taxonomy_year=2024):
    return Control(id, StatementCell(pdf, page, row, 0, "revenue", f"FY{pdf.fiscal_year}", value, concept, start, end),
                   axis, member, taxonomy_year)


CONTROLS = (
    _control("tesla_energy_total", TESLA, 39, "Energy generation and storage segment revenue", 10_086,
             "Revenues", "2024-01-01", "2024-12-31", "us-gaap", "{http://www.tesla.com/20241231}EnergyGenerationAndStorageSegmentMember"),
    _control("tesla_energy_sales", TESLA, 57, "Energy generation and storage sales", 9_564,
             SALES, "2024-01-01", "2024-12-31", "srt", "{http://www.tesla.com/20241231}EnergyGenerationAndStorageSalesMember"),
    _control("tesla_energy_leasing", TESLA, 57, "Energy generation and storage leasing", 522,
             SALES, "2024-01-01", "2024-12-31", "srt", "{http://www.tesla.com/20241231}EnergyGenerationAndStorageLeasingMember"),
    _control("walmart_us_net_sales", WALMART, 41, "Net sales", 462_415,
             SALES, "2024-02-01", "2025-01-31", "us-gaap", "{http://www.walmart.com/20250131}WalmartUSMember"),
    _control("walmart_international_net_sales", WALMART, 42, "Net sales", 121_885,
             SALES, "2024-02-01", "2025-01-31", "us-gaap", "{http://www.walmart.com/20250131}WalmartInternationalMember"),
    _control("walmart_sams_club_net_sales", WALMART, 43, "Net sales", 90_238,
             SALES, "2024-02-01", "2025-01-31", "us-gaap", "{http://www.walmart.com/20250131}SamsClubUSMember"),
    _control("nvidia_data_center", NVIDIA, 171, "Data Center", 115_186,
             "Revenues", "2024-01-29", "2025-01-26", "srt", "{http://www.nvidia.com/20250126}DataCenterMember"),
    _control("nvidia_gaming", NVIDIA, 171, "Gaming", 11_350,
             "Revenues", "2024-01-29", "2025-01-26", "srt", "{http://www.nvidia.com/20250126}GamingMember"),
    _control("apple_iphone", APPLE, 38, "iPhone", 209_586,
             SALES, "2024-09-29", "2025-09-27", "srt", "{http://www.apple.com/20250927}IPhoneMember", 2025),
    _control("apple_services", APPLE, 31, "Services", 109_158,
             SALES, "2024-09-29", "2025-09-27", "srt", "{http://fasb.org/us-gaap/2025}ServiceMember", 2025),
)


def _identity(control: Control, filing: FilingMetadata) -> FactIdentity:
    cell = control.cell
    axis_name = {"us-gaap": "StatementBusinessSegmentsAxis", "srt": "ProductOrServiceAxis"}[control.axis]
    axis = f"{{http://fasb.org/{control.axis}/{control.taxonomy_year}}}{axis_name}"
    concept = f"{{http://fasb.org/us-gaap/{control.taxonomy_year}}}{cell.sec_concept}"
    return FactIdentity(normalize_cik(filing.cik), concept, cell.start, cell.end, (ISO_USD,), (),
                        (Dimension(axis, "explicit", control.member, "segment"),), filing.accession_number, "FILED", "")


def evaluate(facts: Path, pages: Path, cache: Path, manifest_path: Path) -> dict:
    start = perf_counter()
    manifest = _load_manifest(manifest_path)
    filings = {row["accession_number"]: row for row in manifest["filings"]}
    issuers = {row["ticker"]: row for row in manifest["issuers"]}
    pdf_pages = FrozenPdfPages(pages, expected_sha256=PAGE_HASH)
    source_cache = SourceCache(cache, None)
    loaded = {}
    rows = []
    for control in CONTROLS:
        cell = control.cell
        if cell.pdf.accession not in loaded:
            entry = filings[cell.pdf.accession]
            filing = FilingMetadata(**{key: entry[key] for key in FilingMetadata.__dataclass_fields__})
            path = facts / f"{filing.accession_number}.json"
            if sha256_file(path) != entry["facts_sha256"]:
                raise ValueError("iXBRL extraction differs from the frozen corpus")
            receipt = issuers[filing.ticker]["company_facts"]
            company_path, actual = source_cache.source(receipt["url"], MAX_METADATA_BYTES)
            if receipt != actual:
                raise ValueError("Company Facts differs from the frozen corpus")
            company_facts = company_facts_values(json.loads(company_path.read_bytes(), parse_float=Decimal),
                                                 normalize_cik(filing.cik), filing.accession_number)
            loaded[cell.pdf.accession] = filing, json.loads(path.read_bytes())["facts"], company_facts
        filing, observations, company_facts = loaded[cell.pdf.accession]
        text = pdf_pages.get(cell.pdf.name, cell.page)
        if text is None:
            raise ValueError("Frozen reference page is missing")
        if control.id == "walmart_sams_club_net_sales":
            # The same page reports a separate net-sales row excluding fuel.
            _, _, including_fuel = text.partition("Including Fuel")
            text = including_fuel.partition("Excluding Fuel")[0]
        elif control.id == "apple_services":
            # The cost-of-sales section also has a Services row.
            text = text.partition("Cost of sales:")[0]
        _check_pdf_cell(cell, text)
        identity = _identity(control, filing)
        result = resolve_inline_fact(observations, identity, filing=filing)
        dimension, = identity.dimensions
        negatives = {
            "wrong_axis": replace(identity, dimensions=(replace(dimension, axis=dimension.axis + "Unknown"),)),
            "wrong_member": replace(identity, dimensions=(replace(dimension, member=dimension.member + "Unknown"),)),
            "wrong_period": replace(identity, start="1900-01-01"),
            "wrong_unit": replace(identity, unit_numerator=("{http://www.xbrl.org/2003/iso4217}EUR",)),
            "wrong_revision": replace(identity, revision="AMENDMENT"),
        }
        rejected = {key: resolve_inline_fact(observations, request, filing=filing).reason
                    for key, request in negatives.items()}
        consolidated = company_facts.get((cell.sec_concept, cell.start, cell.end), ())
        rows.append({
            "case_id": control.id, "identity": asdict(identity), "fact_id": identity.fact_id,
            "pdf_locator": f"{cell.pdf.name}#p{cell.page}", "pdf_value_usd": cell.millions_usd * 1_000_000,
            "inline_value_usd": str(result.value) if result.value is not None else None,
            "inline_reason": result.reason, "inline_sources": result.source_urls,
            "exact": result.value == cell.millions_usd * 1_000_000, "negative_controls": rejected,
            "company_facts_dimensioned_result": "DIMENSION_UNAVAILABLE",
            "company_facts_same_tag_entity_wide_usd": sorted(map(str, consolidated)),
        })
    return {
        "status": STATUS, "label_source": "PDF_TRANSCRIBED", "manifest_sha256": sha256_file(manifest_path),
        "pages_sha256": PAGE_HASH, "case_count": len(rows), "exact": sum(row["exact"] for row in rows),
        "rejected_negative_controls": sum(reason != "resolved" for row in rows for reason in row["negative_controls"].values()),
        "cases": rows, "wall_ms": round((perf_counter() - start) * 1000, 3), "peak_memory_bytes": peak_memory_bytes(),
        "provider_calls": 0, "cost_usd": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--pages", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=Path("docs/G2_SEC_CORPUS_MANIFEST.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh output file")
    with offline_socket_guard():
        report = evaluate(args.facts, args.pages, args.cache, args.manifest)
        write_json_atomic(args.output, report)
    print(f"Exact {report['exact']}/{report['case_count']}; rejected {report['rejected_negative_controls']} controls")


if __name__ == "__main__":
    main()
