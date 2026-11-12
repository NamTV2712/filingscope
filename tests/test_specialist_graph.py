from __future__ import annotations

import threading
import time
from typing import Any

from src.agent.complexity_router import ComplexityRouter, ExecutionPath
from src.agent.specialist_graph import SpecialistResearchGraph
from src.agent.specialists import SpecialistStatus
from src.generation.answer_generator import AnswerGenerationResult
from src.ingestion.company_facts import RevisionKind
from src.ledger.models import EvidenceSourceType
from src.verification.models import ClaimStatus, ResponseDisposition


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
                                "accn": f"{cik:010d}-23-000001",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "val": int(value_2023),
                            },
                            {
                                "accn": f"{cik:010d}-24-000001",
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


def test_specialist_releases_only_rechecked_claims_and_keeps_draft_audit() -> None:
    class DraftGenerator:
        def generate(self, question, chunks):
            return AnswerGenerationResult(
                answer=(
                    "Apple revenue was $110 billion in FY2024 [Source 1]. "
                    "Apple net income was $999 billion in FY2024 [Source 1]."
                ),
                model_id="fixture", prompt_tokens=50, completion_tokens=30, latency_ms=0.0,
            )

    graph = SpecialistResearchGraph(retriever=FakeRetriever([_annual_chunk()]), generator=DraftGenerator())
    result = graph.run("What was Apple's revenue in FY2024?", request_id="m11-revision")

    assert result.status == "PARTIAL"
    assert result.usage.correction_passes == 1
    assert result.usage.llm_calls == 1
    assert result.usage.graph_steps == 4
    assert "$110 billion" in result.answer and "$999 billion" not in result.answer
    assert result.generation is not None and result.generation.answer == result.answer
    records = {record.verifier_version: record.result for record in result.ledger_snapshot.verifications}
    assert records["M11"] == result.verification
    assert records["M11-draft"].disposition == ResponseDisposition.REJECTED
    verified, rejected = records["M11-draft"].claims
    assert records["M11"].claims[0].claim_id == verified.claim_id
    assert rejected.status == ClaimStatus.UNSUPPORTED
    claim = next(item for item in result.ledger_snapshot.claims if item.claim_id == rejected.claim_id)
    assert claim.claim_type == "financial_fact" and claim.verification_status == ClaimStatus.UNSUPPORTED
    assert claim.cited_evidence_ids and not claim.supporting_evidence_ids


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
    assert {item.calculation_id for item in result.ledger_snapshot.claims} == {
        item.calculation_id for item in result.calculations
    }
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


class ConcurrentFixtureRetriever(FakeRetriever):
    supports_concurrent_retrieval = True

    def __init__(self, *, reverse: bool = False, bad_company: str | None = None):
        super().__init__([])
        self.reverse = reverse
        self.bad_company = bad_company
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.completions: list[str] = []

    def retrieve(self, query: str, top_k: int = 5, **filters: Any) -> list[dict[str, Any]]:
        company = query.split()[0].casefold()
        with self.lock:
            self.calls.append((query, top_k))
            self.active += 1
            self.peak = max(self.active, self.peak)
        try:
            time.sleep(0.04 if (company == "apple") != self.reverse else 0.01)
            if "consolidated financial statement table" in query:
                return []
            if company == self.bad_company:
                return [None]  # type: ignore[list-item]
            if company == "apple":
                return [_annual_chunk()]
            chunk = _annual_chunk(chunk_id="msft-revenue", ticker="MSFT", company="Microsoft Corporation")
            chunk["text"] = "Revenue was $92 billion in FY2024."
            return [chunk]
        finally:
            with self.lock:
                self.active -= 1
                self.completions.append(company)


def test_fanout_bounds_concurrency_and_coalesces_evidence_across_six_tasks() -> None:
    question = "Compare Apple and Microsoft revenue for FY2022, FY2023, and FY2024."
    retriever = ConcurrentFixtureRetriever()
    result = SpecialistResearchGraph(retriever=retriever).run(question, request_id="fanout")

    assert result.usage.parallel_task_count == 6
    assert 1 < result.usage.peak_parallel_tasks == retriever.peak <= result.route.budget.max_concurrency
    assert result.usage.retrieval_calls == len(retriever.calls) == 6
    assert len({query for query, _ in retriever.calls}) == 6
    assert {query for query, _ in retriever.calls} == {
        f"{company} revenue FY{year}"
        for company in ("apple", "microsoft") for year in (2022, 2023, 2024)
    }
    assert sum(top_k for _, top_k in retriever.calls) == result.route.budget.max_candidate_chunks
    assert result.usage.tool_calls <= result.route.budget.max_tool_calls
    assert result.usage.duplicate_candidate_chunks == 4
    assert result.usage.graph_steps == result.route.budget.max_graph_steps
    sources = [record for record in result.ledger_snapshot.evidence_records if not record.metric_id]
    assert len(sources) == 2
    assert all(len(record.task_ids) == 3 for record in sources)


def test_fan_in_is_deterministic_when_worker_completion_order_reverses() -> None:
    question = "Compare Apple and Microsoft revenue for FY2024."
    first = ConcurrentFixtureRetriever()
    second = ConcurrentFixtureRetriever(reverse=True)
    left = SpecialistResearchGraph(retriever=first).run(question, request_id="same")
    right = SpecialistResearchGraph(retriever=second).run(question, request_id="same")

    assert first.completions[:2] == ["microsoft", "apple"]
    assert second.completions[:2] == ["apple", "microsoft"]
    assert left.ledger_snapshot == right.ledger_snapshot
    assert left.answer == right.answer
    assert left.coverage is not None and left.coverage.sufficient
    assert "$110 billion" in left.answer and "$92 billion" in left.answer


def test_failed_worker_keeps_sibling_evidence_and_charges_attempt() -> None:
    retriever = ConcurrentFixtureRetriever(bad_company="microsoft")
    result = SpecialistResearchGraph(retriever=retriever).run(
        "Compare Apple and Microsoft revenue for FY2024.",
    )

    workers = [item for item in result.specialist_results if item.worker_id == "filing_research_worker"]
    failed = next(item for item in workers if item.status == SpecialistStatus.FAILED)
    assert failed.error_code == "TypeError"
    assert failed.retrieval_calls == 1
    assert failed.missing_requirement_ids and not failed.evidence_ids
    assert any(item.status == SpecialistStatus.COMPLETE and item.evidence_ids for item in workers)
    assert result.usage.retrieval_calls == len(retriever.calls)
    assert {record.ticker for record in result.ledger_snapshot.evidence_records} == {"AAPL"}
    assert result.coverage is not None and not result.coverage.sufficient


def test_filing_and_table_search_reuse_duplicate_queries() -> None:
    question = "Compare Apple and Microsoft revenue for FY2024."
    router = ComplexityRouter()
    route = router.route(question)
    plan = route.research_plan
    assert plan is not None
    extra = plan.tasks[0].model_copy(update={"task_id": "duplicate-apple"})
    route = route.model_copy(update={
        "research_plan": plan.model_copy(update={"tasks": (*plan.tasks, extra)}),
    })
    retriever = ConcurrentFixtureRetriever()
    result = SpecialistResearchGraph(router=router, retriever=retriever).run(question, route=route)

    assert result.usage.parallel_task_count == 2
    assert result.usage.deduplicated_query_tasks == 1
    assert result.usage.retrieval_calls == len({query for query, _ in retriever.calls}) == 3
    source = next(
        record for record in result.ledger_snapshot.evidence_records
        if record.ticker == "AAPL" and not record.metric_id
    )
    assert "duplicate-apple" in source.task_ids


def test_unmarked_retriever_retains_serial_query_plan() -> None:
    retriever = FakeRetriever([])
    question = "Compare Apple and Microsoft revenue for FY2024."
    result = SpecialistResearchGraph(retriever=retriever).run(question)

    assert result.usage.parallel_task_count == result.usage.peak_parallel_tasks == 0
    assert len(retriever.calls) == 2
    assert retriever.calls[0][0] == question


def test_fan_in_refuses_conflicting_versions_of_the_same_chunk() -> None:
    class ConflictingRetriever(ConcurrentFixtureRetriever):
        def retrieve(self, query: str, top_k: int = 5, **filters: Any) -> list[dict[str, Any]]:
            if "financial statement table" in query:
                return []
            chunk = _annual_chunk()
            if query.startswith("microsoft"):
                chunk["text"] = "Revenue was $92 billion in FY2024."
            return [chunk]

    result = SpecialistResearchGraph(retriever=ConflictingRetriever()).run(
        "Compare Apple and Microsoft revenue for FY2024.",
    )
    assert result.ledger_snapshot.evidence_records == ()
    failures = [item for item in result.specialist_results if item.error_code == "LedgerConflictError"]
    assert len(failures) == 2
    assert all(item.retrieval_calls == 1 and item.missing_requirement_ids for item in failures)


def _apple_revenue_rows(sec: FakeSECCompanyFacts) -> list[dict[str, Any]]:
    return sec.facts[320193]["facts"]["us-gaap"][
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    ]["units"]["USD"]


def test_explicit_revision_uses_revised_sec_fact_and_cites_its_accession() -> None:
    sec = FakeSECCompanyFacts()
    rows = _apple_revenue_rows(sec)
    rows.append({
        **rows[1], "accn": "0000320193-25-000009", "filed": "2025-03-15",
        "form": "10-K/A", "val": 94_000_000_000,
    })
    result = SpecialistResearchGraph(retriever=FakeRetriever([_annual_chunk()]), sec_client=sec).run(
        "What was Apple's restated revenue in FY2024?",
    )
    assert result.selected_path == ExecutionPath.RESEARCH
    assert result.coverage is not None and result.coverage.sufficient
    assert "94,000,000,000" in result.answer and "amended filing" in result.answer
    assert result.status == "VERIFIED"
    assert "110 billion" not in result.answer
    fact = result.ledger_snapshot.financial_facts[0]
    assert fact.xbrl_provenance is not None
    assert fact.xbrl_provenance.revision_kind == RevisionKind.AMENDMENT
    assert fact.xbrl_provenance.accession == "0000320193-25-000009"
    record = next(item for item in result.ledger_snapshot.evidence_records if item.evidence_id in fact.evidence_ids)
    assert "0000320193-25-000009-index.html" in (record.source_url or "")


def test_missing_revision_does_not_use_an_unversioned_filing_excerpt() -> None:
    chunk = _annual_chunk()
    chunk["source_type"] = "XBRL_FACT"
    result = SpecialistResearchGraph(
        retriever=FakeRetriever([chunk]), sec_client=FakeSECCompanyFacts(),
    ).run("What was Apple's restated revenue in FY2024?")
    assert result.status == "ABSTAIN"
    assert result.coverage is not None and not result.coverage.sufficient
    assert not result.ledger_snapshot.financial_facts


def test_disagreement_between_filing_and_sec_value_blocks_answer() -> None:
    chunk = _annual_chunk()
    chunk["text"] = "Revenue was $105 billion in FY2024."
    result = SpecialistResearchGraph(
        retriever=FakeRetriever([chunk]), sec_client=FakeSECCompanyFacts(),
    ).run("Compare Apple and Microsoft revenue for FY2024.")
    assert result.status == "ABSTAIN"
    assert result.coverage is not None and result.coverage.conflicted_requirement_ids


def test_agreement_across_scales_keeps_filing_and_structured_provenance() -> None:
    result = SpecialistResearchGraph(
        retriever=FakeRetriever([_annual_chunk()]), sec_client=FakeSECCompanyFacts(),
    ).run("Compare Apple and Microsoft revenue for FY2024.")
    assert result.coverage is not None and result.coverage.sufficient
    assert len([fact for fact in result.ledger_snapshot.financial_facts if fact.ticker == "AAPL"]) == 2


def test_calculation_cannot_silently_combine_different_tags() -> None:
    sec = FakeSECCompanyFacts()
    gaap = sec.facts[320193]["facts"]["us-gaap"]
    rows = _apple_revenue_rows(sec)
    gaap["SalesRevenueNet"] = {"units": {"USD": [rows.pop(0)]}}
    result = SpecialistResearchGraph(sec_client=sec).run(
        "Calculate Apple's revenue growth as reported from FY2023 to FY2024.",
    )
    assert result.coverage is not None and result.coverage.sufficient
    assert result.status == "ABSTAIN" and not result.calculations
    assert any(
        item.key == "calculation_skipped" and "incompatible_fact_provenance" in item.value
        for task in result.specialist_results for item in task.observations
    )


def test_currency_request_cannot_use_a_differently_denominated_filing_value() -> None:
    result = SpecialistResearchGraph(retriever=FakeRetriever([_annual_chunk()])).run(
        "What was Apple's revenue in CAD for FY2024?",
    )
    assert result.coverage is not None and not result.coverage.sufficient
    assert result.status == "ABSTAIN"


def test_optional_report_dates_preserve_the_company_facts_budget() -> None:
    class SECWithReportDates(FakeSECCompanyFacts):
        def get_company_report_dates(self, cik: int) -> dict[str, str]:
            self.request_count += 1
            return {}

    sec = SECWithReportDates()
    graph = SpecialistResearchGraph(sec_client=sec)
    question = "Compare Apple and Microsoft revenue for FY2024."
    route = graph.router.route(question)
    route = route.model_copy(update={"budget": route.budget.model_copy(update={"max_tool_calls": 2})})
    result = graph.run(question, route=route)
    assert sec.request_count == result.usage.tool_calls == 2
    assert result.coverage is not None and result.coverage.sufficient


def test_mixed_revision_request_ends_without_sec_calls() -> None:
    sec = FakeSECCompanyFacts()
    result = SpecialistResearchGraph(sec_client=sec).run(
        "Compare Apple's originally reported and restated revenue in FY2024.",
    )
    assert result.status == "UNSUPPORTED"
    assert "mixed_filing_revision_request" in result.route.decision.reason_codes
    assert sec.request_count == 0
