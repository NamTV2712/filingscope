from datetime import date
from decimal import Decimal

from src.agent.complexity_router import ComplexityRouter
from src.agent.specialist_graph import SpecialistResearchGraph
from src.decision.statement_columns import parse_statement_columns
from src.research.corpus_map import CorpusMap
from src.verification.atomic_claim_verifier import AtomicClaimVerifier


TABLE = """Consolidated Balance Sheet   Financial Table of Contents
Consolidated Balance Sheet   Financial Table of Contents
Millions of dollars, except per-share amounts
At December 31
2023    2024
Assets
Cash and cash equivalents (Note 9)      $ 20   $ 25
Cash and cash equivalents (Note 9)      $ 20   $ 25
Total Assets     $ 90   $ 100
Liabilities
Total Liabilities2     $ 55   $ 60
Total Liabilities and Equity     $ 90   $ 100
The following table includes certain subsidiary assets.
2023    2024
Cash and cash equivalents      $ 5    $ 4
"""
FILING = {
    "chunk_id": "filing-physical-page", "doc_name": "EXMP_FY2024_10K", "document_id": "EXMP_FY2024_10K",
    "company": "Example Corporation", "ticker": "EXMP", "cik": "1234", "doc_type": "10-K", "page_number": 2,
    "accession_number": "0000001234-25-000001", "reporting_periods": [2024], "filing_date": "2025-02-01",
    "source_url": "https://www.sec.gov/Archives/edgar/data/1234/000000123425000001/example.htm",
    "score": 1.0, "text": TABLE,
}
QUESTION = "At December 31, 2024, what percentage of Example Corporation's total assets was cash and cash equivalents?"


class PageRetriever:
    def __init__(self, row):
        self.row = row

    def retrieve(self, query, top_k=10, **filters):
        return [self.row]

    def get_source_page(self, document, page):
        return self.row["text"] if (document, page) == (self.row["doc_name"], self.row["page_number"]) else None


def test_scoped_balance_uses_original_row_and_excludes_subsidiary_table():
    parsed = parse_statement_columns(TABLE, form="10-K", fiscal_year=2024, exact_balance_sheet=True,
                                     scoped_balance_sheet=True)
    cells = {item.metric_id: item for item in parsed.values if item.period == "FY2024"}
    assert cells["cash_and_equivalents"].amount == Decimal(25)
    assert cells["cash_and_equivalents"].row_index == 6
    assert cells["total_liabilities"].amount == Decimal(60)
    assert cells["total_liabilities"].row_label == "Total Liabilities"
    assert cells["total_assets"].period_identity.end == date(2024, 12, 31)


def test_routed_percentage_validates_both_source_cells_and_withholds_incompatible_inputs():
    class RecordingVerifier(AtomicClaimVerifier):
        def verify(self, question, answer, evidence_chunks):
            self.chunks = list(evidence_chunks)
            return super().verify(question, answer, self.chunks)

    router = ComplexityRouter(CorpusMap.from_chunks([FILING]))
    verifier = RecordingVerifier(catalog=router.extractor.catalog)
    graph = SpecialistResearchGraph(router=router, retriever=PageRetriever(FILING), verifier=verifier)
    result = graph.run(QUESTION)
    assert result.status == "VERIFIED", result
    assert "represented 25.00% of total assets" in result.answer
    calculation, = result.calculations
    assert calculation.normalized_inputs == ("25000000", "100000000")
    assert len(set(calculation.input_evidence_ids)) == 2
    cited = verifier.chunks
    wrong_answers = (
        result.answer.replace("25.00", "400.00"),
        result.answer.replace("total assets", "total liabilities"),
        result.answer.replace("FY2024", "FY2023"),
        result.answer.replace("[Source 1]", ""),
    )
    for answer in wrong_answers:
        assert verifier.verify(QUESTION, answer, cited).disposition != "VERIFIED"
    missing = [{**chunk, "approved_facts": tuple(fact for fact in chunk["approved_facts"]
                                                if fact.metric_id != "total_assets")} for chunk in cited]
    assert verifier.verify(QUESTION, result.answer, missing).disposition != "VERIFIED"
    assert graph.run(QUESTION.replace("December 31", "June 30")).status != "VERIFIED"
    assert graph.run(QUESTION.replace("total assets", "total assets in euros")).status != "VERIFIED"
    zero = {**FILING, "text": TABLE.replace("$ 90   $ 100", "$ 90   $ 0")}
    assert SpecialistResearchGraph(router=router, retriever=PageRetriever(zero)).run(QUESTION).status != "VERIFIED"
