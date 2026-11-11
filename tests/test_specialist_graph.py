from __future__ import annotations

from typing import Any

from src.agent.complexity_router import ComplexityRouter, ExecutionPath
from src.agent.specialist_graph import SpecialistResearchGraph
from src.ledger.models import EvidenceSourceType
from src.verification.models import ResponseDisposition


class FakeRetriever:
    def __init__(self, chunks: list[dict[str, Any]]):
        self.chunks = chunks
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, top_k: int = 5, **filters: Any) -> list[dict[str, Any]]:
        self.calls.append((query, top_k))
        return self.chunks[:top_k]


class FakeSECCompanyFacts:
    def __init__(self):
        self.request_count = 0
        self.facts = {
            320193: _company_facts("Apple Inc.", 320193, "100000000000", "110000000000"),
            789019: _company_facts("Microsoft Corporation", 789019, "80000000000", "92000000000"),
        }

    @staticmethod
    def estimated_company_facts_requests(ticker: str) -> int:
        return 1

    def get_cik(self, ticker: str) -> int:
        return {"AAPL": 320193, "MSFT": 789019}[ticker]

    def get_company_facts(self, cik: int) -> dict[str, Any]:
        self.request_count += 1
        return self.facts[cik]


def _company_facts(name: str, cik: int, value_2023: str, value_2024: str) -> dict[str, Any]:
    return {
        "cik": cik,
        "entityName": name,
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "label": "Revenue from Contract with Customer",
                    "units": {
                        "USD": [
                            {
                                "accn": f"{cik}-23-000001",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "val": int(value_2023),
                            },
                            {
                                "accn": f"{cik}-24-000001",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-01",
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "val": int(value_2024),
                            },
                        ]
                    },
                }
            }
        },
    }


def _annual_chunk(
    *, chunk_id: str = "aapl-revenue", ticker: str = "AAPL", company: str = "Apple Inc."
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "ticker": ticker,
        "company": company,
        "doc_name": f"{ticker}_annual_report.pdf",
        "document_id": f"{ticker}_annual_report.pdf",
        "page_number": 10,
        "filing_type": "10-K",
        "filing_date": "2025-02-01",
        "source_url": f"https://example.com/{ticker.lower()}-annual-report.pdf",
        "section": "financial_statements",
        "text": "Revenue was $110 billion in FY2024.",
        "score": 0.9,
    }


def test_fast_route_runs_only_four_nodes_and_verifies_grounded_lookup() -> None:
    retriever = FakeRetriever([_annual_chunk()])
    graph = SpecialistResearchGraph(retriever=retriever)

    result = graph.run("What was Apple's revenue in FY2024?", request_id="fast-1")

    assert result.selected_path == ExecutionPath.FAST
    assert result.graph_trace == (
        "filing_worker",
        "evidence_analyst",
        "report_writer",
        "claim_verifier",
    )
    assert result.usage.graph_steps == 4
    assert result.usage.retrieval_calls == 1
    assert result.usage.tool_calls <= result.route.budget.max_tool_calls
    assert result.status == "VERIFIED"
    assert result.verification is not None
    assert result.verification.disposition == ResponseDisposition.VERIFIED
    assert "[Source 1]" in result.answer
    assert result.ledger_snapshot.evidence_records
    assert result.ledger_snapshot.claims
    assert result.ledger_snapshot.verifications


def test_fast_numerical_route_runs_reasoner_within_four_graph_steps() -> None:
    chunk = _annual_chunk()
    chunk["text"] = "2023\n2024\nRevenue\n$100 billion\n$110 billion"
    graph = SpecialistResearchGraph(retriever=FakeRetriever([chunk]))

    result = graph.run(
        "Calculate Apple's revenue growth from FY2023 to FY2024.",
        request_id="fast-growth-1",
    )

    assert result.selected_path == ExecutionPath.FAST
    assert result.usage.graph_steps == 4
    assert len(result.calculations) == 1
    assert str(result.calculations[0].result) == "10.00"
    assert "growth was 10%" in result.answer
    assert result.verification is not None
    assert result.verification.disposition == ResponseDisposition.VERIFIED
    assert result.usage.tool_calls <= result.route.budget.max_tool_calls


def test_unsupported_route_terminates_without_calls() -> None:
    retriever = FakeRetriever([_annual_chunk()])
    graph = SpecialistResearchGraph(retriever=retriever)

    result = graph.run("Forecast Apple's revenue next year.", request_id="unsupported-1")

    assert result.selected_path == ExecutionPath.UNSUPPORTED
    assert result.graph_trace == ("unsupported_path",)
    assert result.status == "UNSUPPORTED"
    assert result.usage.tool_calls == result.usage.retrieval_calls == result.usage.llm_calls == 0
    assert retriever.calls == []
    assert result.ledger_snapshot.evidence_records == ()


def test_research_route_uses_sec_facts_and_emits_linked_growth_calculations() -> None:
    sec = FakeSECCompanyFacts()
    question = "Compare Apple and Microsoft revenue growth between 2023 and 2024."
    graph = SpecialistResearchGraph(
        retriever=FakeRetriever([]),
        sec_client=sec,  # type: ignore[arg-type]
        ticker_by_company={"apple": "AAPL", "microsoft": "MSFT"},
    )

    result = graph.run(question, request_id="research-1")

    assert result.selected_path == ExecutionPath.RESEARCH
    assert result.graph_trace == (
        "supervisor",
        "filing_worker",
        "structured_data_worker",
        "table_worker",
        "evidence_analyst",
        "financial_reasoner",
        "report_writer",
        "claim_verifier",
    )
    assert result.usage.graph_steps == 8
    assert result.usage.tool_calls <= result.route.budget.max_tool_calls
    assert result.usage.retrieval_calls <= result.route.budget.max_retrieval_calls
    assert sec.request_count == 2
    assert result.coverage is not None and result.coverage.sufficient
    assert len(result.calculations) == 2
    assert {str(item.result) for item in result.calculations} == {"10.00", "15.00"}
    assert "growth was" in result.answer
    assert result.verification is not None
    assert {
        item.source_type for item in result.ledger_snapshot.evidence_records
    } == {EvidenceSourceType.XBRL_FACT, EvidenceSourceType.DERIVED_FACT}
    assert all(item.input_evidence_ids for item in result.calculations)
    for calculation in result.ledger_snapshot.calculations:
        derived_records = [
            item for item in result.ledger_snapshot.evidence_records
            if item.calculation_id == calculation.calculation_id
        ]
        assert derived_records
        assert all(
            record.derived_from_evidence_ids == calculation.input_evidence_ids
            for record in derived_records
        )


def test_table_worker_uses_only_remaining_retrieval_budget_for_table_queries() -> None:
    table_chunk = _annual_chunk()
    table_chunk["section"] = "financial_table"
    table_chunk["table_id"] = "aapl-income-statement"
    table_chunk["text"] = (
        "### Consolidated Income Statement\n"
        "| Metric | FY2023 | FY2024 |\n|---|---|---|\n"
        "| Total net sales | $100 billion | $110 billion |"
    )
    class TableQueryRetriever(FakeRetriever):
        def retrieve(self, query: str, top_k: int = 5, **filters: Any) -> list[dict[str, Any]]:
            self.calls.append((query, top_k))
            if "consolidated financial statement table" in query.casefold():
                return [table_chunk]
            return []

    retriever = TableQueryRetriever([])
    graph = SpecialistResearchGraph(
        retriever=retriever,
        ticker_by_company={"apple": "AAPL", "microsoft": "MSFT"},
    )

    result = graph.run(
        "Compare Apple and Microsoft revenue in FY2023 and FY2024.",
        request_id="table-1",
    )

    table_records = [
        item for item in result.ledger_snapshot.evidence_records
        if item.source_type == EvidenceSourceType.TABLE_EVIDENCE
    ]
    assert result.selected_path == ExecutionPath.RESEARCH
    assert table_records
    assert all(item.table_id == "aapl-income-statement" for item in table_records)
    table_result = next(item for item in result.specialist_results if item.worker_id == "table_evidence_worker")
    filing_result = next(item for item in result.specialist_results if item.worker_id == "filing_research_worker")
    assert table_result.retrieval_calls > 0
    assert table_result.retrieval_calls <= result.route.budget.max_retrieval_calls - filing_result.retrieval_calls
    assert result.usage.retrieval_calls == len(retriever.calls)
    assert result.usage.retrieval_calls <= result.route.budget.max_retrieval_calls
