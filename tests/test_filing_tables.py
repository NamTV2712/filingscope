"""Revenue cells must retain their subtotal, period and explicit source units."""

from decimal import Decimal
import json

import pytest

from src.agent.complexity_router import ComplexityRouter
from src.agent.specialist_graph import SpecialistResearchGraph
from src.decision.filing_tables import MonetaryDeclaration, filing_identity_matches, parse_revenue_table
from src.decision.models import EvidenceFact
from src.decision.evidence_coverage import _normalized_facts
from src.decision.requirement_extractor import EvidenceRequirementExtractor
from src.ledger.models import EvidenceRecord, EvidenceSourceType, FinancialFact
from src.research.corpus_map import CorpusMap
from src.retrieval.canonical_json import sha256_file
from src.retrieval.pdf_page_cache import FrozenPdfPages


TABLE = """Example Corporation
Disaggregation of Revenue
The following table presents revenue from contracts with customers.
                           Year Ended December 31,
                            2024       2023       2022
Oil                         $ 60       $ 50       $ 40
Gas                           20         10          8
NGL                           10          5          2
Oil, gas and NGL sales         90         65         50
Oil                           12         10          8
Gas                            5          3          2
NGL                            3          2          1
Marketing and midstream revenues   20         15         11
Total revenues from contracts with customers  $ 110      $ 80       $ 61
Customers
The customer concentration disclosure follows.
"""
DECLARATION = MonetaryDeclaration("USD", "millions", 1)
DOCUMENT = "EX_FY2024_10K"
SOURCE = "https://www.sec.gov/Archives/edgar/data/1234/000000123425000001/report.htm"


def chunk(text=TABLE, **changes):
    return {
        "chunk_id": "table", "doc_name": DOCUMENT, "document_id": DOCUMENT, "company": "Example Corporation",
        "ticker": "EX", "cik": "1234", "doc_type": "10-K", "source_url": SOURCE,
        "accession_number": "0000001234-25-000001", "reporting_periods": [2024], "page_number": 2,
        "section": "document", "text": text, "score": 1.0, **changes,
    }


def parse(text=TABLE, declaration=DECLARATION):
    return parse_revenue_table(text, form="10-K", fiscal_year=2024, declaration=declaration)


def test_duplicate_commodity_labels_bind_to_the_subtotal_and_typed_columns():
    result = parse()
    assert result.recognized and len(result.values) == 15
    oil = next(cell for cell in result.values if cell.metric_id == "oil_sales" and cell.period == "FY2024")
    assert oil.amount == Decimal(60) and oil.base_amount == Decimal(60000000)
    assert (oil.row_group, oil.row_label, oil.unit_source_page) == ("Oil, gas and NGL sales", "Oil", 1)
    assert oil.period_identity.end.isoformat() == "2024-12-31"
    reversed_columns = TABLE.replace("2024       2023       2022", "2022       2023       2024")
    reversed_oil = next(cell for cell in parse(reversed_columns).values
                        if cell.metric_id == "oil_sales" and cell.period == "FY2024")
    assert reversed_oil.amount == Decimal(40) and reversed_oil.column_index == 2


def test_invalid_group_sums_cannot_authorize_component_rows():
    bad = TABLE.replace("90         65         50", "91         65         50")
    assert not any(cell.metric_id in {"oil_sales", "gas_sales", "ngl_sales"} for cell in parse(bad).values)
    wrong_group = TABLE.replace("Oil, gas and NGL sales", "Unrelated revenue subtotal")
    assert not any(cell.metric_id == "oil_sales" for cell in parse(wrong_group).values)


def test_currency_and_units_must_be_explicit_and_consistent():
    assert not parse(declaration=None).values
    overridden = parse(TABLE.replace("Year Ended", "In billions of CAD\nYear Ended"))
    assert overridden.values and all(cell.currency == "CAD" and cell.scale == "billions" for cell in overridden.values)
    assert not parse(TABLE.replace("Year Ended", "In millions of CAD and USD\nYear Ended")).values
    assert not parse(TABLE.replace("$ 60", "€ 60")).values
    local = TABLE.replace("Year Ended", "In millions of USD\nYear Ended")
    assert parse(local, declaration=None).values
    assert not parse_revenue_table(TABLE, form="10-Q", fiscal_year=2024, declaration=DECLARATION).recognized


@pytest.mark.parametrize("changes", [
    {"accession_number": "0000001234-25-000002"}, {"cik": "5678"},
    {"source_url": SOURCE.replace("www.sec.gov", "other.example")}, {"accession_number": None},
])
def test_filing_identity_requires_matching_sec_cik_and_accession(changes):
    assert filing_identity_matches(chunk())
    assert not filing_identity_matches(chunk(**changes))


def test_global_units_conflict_and_source_locator_survive_page_cache(tmp_path):
    path = tmp_path / "pages.jsonl"
    rows = [
        {"doc_name": DOCUMENT, "page_number": 1,
         "text": "All monetary amounts are stated in millions of U.S. dollars unless otherwise specified."},
        {"doc_name": DOCUMENT, "page_number": 2, "text": TABLE},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    pages = FrozenPdfPages(path, expected_sha256=sha256_file(path))
    assert pages.monetary_declaration(DOCUMENT) == DECLARATION
    rows.append({"doc_name": DOCUMENT, "page_number": 3,
                 "text": "All monetary values are stated in thousands of U.S. dollars."})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert FrozenPdfPages(path, expected_sha256=sha256_file(path)).monetary_declaration(DOCUMENT) is None


def test_raw_or_mistagged_normalized_facts_cannot_replace_checked_cells():
    extractor = EvidenceRequirementExtractor.from_document_rows([chunk()])
    metric = next(metric for metric in extractor.extract("What were Example Corporation's FY2024 oil sales?").metrics
                  if metric.metric_id == "oil_sales")
    source = chunk(filing_page_checked=True)
    fact = EvidenceFact(evidence_id="table", entity_id="EX", metric_id="oil_sales", period="FY2024",
                        value="USD 60000000", numeric_value="60000000", currency="USD", scale="unit",
                        document_id=DOCUMENT, source_url=SOURCE)
    assert not _normalized_facts({**source, "normalized_facts": (fact,)}, metric, "EX")


def test_cell_metadata_contributes_to_ledger_identity_only_when_present():
    record = EvidenceRecord.from_source(request_id="req", document_id=DOCUMENT, chunk_id="table",
                                       source_type=EvidenceSourceType.TABLE_EVIDENCE, metric_id="oil_sales")
    same = EvidenceRecord.from_source(**{key: value for key, value in record.model_dump().items() if key != "evidence_id"})
    assert same.evidence_id == record.evidence_id
    bound = EvidenceRecord.from_source(request_id="req", document_id=DOCUMENT, chunk_id="table",
                                      source_type=EvidenceSourceType.TABLE_EVIDENCE, metric_id="oil_sales",
                                      table_title="Disaggregation of Revenue", row_label="Oil",
                                      row_group="Oil, gas and NGL sales", unit_source_page=1,
                                      filing_accession="0000001234-25-000001")
    assert bound.evidence_id != record.evidence_id
    fact = FinancialFact.from_evidence(bound)
    assert (fact.row_group, fact.unit_source_page, fact.filing_accession) == (
        bound.row_group, bound.unit_source_page, bound.filing_accession,
    )


def test_normal_research_entry_point_verifies_each_commodity_cell():
    class FilingRetriever:
        def retrieve(self, query, top_k=5, **filters):
            return [chunk()]

        def get_source_page(self, document, page):
            return TABLE if (document, page) == (DOCUMENT, 2) else None

        def get_document_unit_declaration(self, document):
            return DECLARATION if document == DOCUMENT else None

    graph = SpecialistResearchGraph(router=ComplexityRouter(CorpusMap.from_chunks([chunk()])), retriever=FilingRetriever())
    question = "What was Example Corporation's FY2024 sales split by commodity?"
    result = graph.run(question)
    assert result.status == "VERIFIED", result.answer
    assert all(value in result.answer for value in ("60,000,000", "20,000,000", "10,000,000"))
    cells = [record for record in result.ledger_snapshot.evidence_records if record.table_title]
    assert len(cells) == 3 and all(record.row_group == "Oil, gas and NGL sales" for record in cells)
    assert result.verification.supported_claim_count == 3
