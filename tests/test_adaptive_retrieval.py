from __future__ import annotations

from typing import Any

from src.agent.adaptive_retrieval import (
    AdaptiveRetrievalBudget,
    AdaptiveRetrievalController,
    AdaptiveStopReason,
)
from src.decision.models import DecisionAction


COMPARISON = "Compare Apple and Microsoft revenue growth between 2022 and 2024"


def _table_chunk(
    *,
    chunk_id: str,
    ticker: str,
    company: str,
    year_values: tuple[tuple[str, str], ...],
    token_count: int = 8,
    label: str = "Total revenue",
) -> dict[str, Any]:
    years = "\n".join(year for year, _ in year_values)
    values = "\n".join(value for _, value in year_values)
    return {
        "chunk_id": chunk_id,
        "ticker": ticker,
        "company": company,
        "doc_name": f"{ticker}_annual_report.pdf",
        "document_id": f"{ticker}_annual_report.pdf",
        "page_number": 4,
        "source_url": "https://example.com/report.pdf",
        "token_count": token_count,
        "text": f"{years}\n{label}\n{values}",
    }


def _initial_one_gap() -> tuple[dict[str, Any], ...]:
    return (
        _table_chunk(
            chunk_id="aapl-complete", ticker="AAPL", company="Apple Inc.",
            year_values=(("2024", "$391 billion"), ("2022", "$394 billion")),
        ),
        _table_chunk(
            chunk_id="msft-fy2024", ticker="MSFT", company="Microsoft Corporation",
            year_values=(("2024", "$245 billion"),),
        ),
    )


def _final_msft_fy2022() -> dict[str, Any]:
    return _table_chunk(
        chunk_id="msft-fy2022", ticker="MSFT", company="Microsoft Corporation",
        year_values=(("2022", "$198 billion"),),
    )


class RecordingRetriever:
    def __init__(self, responses: list[list[Any]]):
        self.responses = responses
        self.queries: list[str] = []

    def retrieve(self, query: str, top_k: int = 5) -> list[Any]:
        self.queries.append(query)
        index = len(self.queries) - 1
        return self.responses[index] if index < len(self.responses) else []


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_one_targeted_search_resolves_missing_company_period_slot() -> None:
    initial = _initial_one_gap()
    retriever = RecordingRetriever([[_final_msft_fy2022()]])

    result = AdaptiveRetrievalController(retriever).run(COMPARISON, initial)

    assert result.final_decision.action == DecisionAction.ANSWER
    assert result.stop_reason == AdaptiveStopReason.EVIDENCE_SUFFICIENT
    assert result.queries_used == result.rounds_used == 1
    assert "microsoft" in retriever.queries[0].casefold()
    assert "FY2022" in retriever.queries[0]
    assert {item["chunk_id"] for item in result.evidence_chunks} >= {
        item["chunk_id"] for item in initial
    }
    assert result.trace[0].outcome == "progress"


def test_two_gap_queries_reassess_and_complete_across_rounds() -> None:
    initial = (
        _table_chunk(
            chunk_id="aapl-fy2024", ticker="AAPL", company="Apple Inc.",
            year_values=(("2024", "$391 billion"),),
        ),
        _table_chunk(
            chunk_id="msft-fy2024", ticker="MSFT", company="Microsoft Corporation",
            year_values=(("2024", "$245 billion"),),
        ),
    )
    apple_2022 = _table_chunk(
        chunk_id="aapl-fy2022", ticker="AAPL", company="Apple Inc.",
        year_values=(("2022", "$394 billion"),),
    )
    retriever = RecordingRetriever([[apple_2022], [_final_msft_fy2022()]])

    result = AdaptiveRetrievalController(retriever).run(
        COMPARISON,
        initial,
        budget=AdaptiveRetrievalBudget(max_rounds=3, max_queries=4),
    )

    assert result.final_decision.action == DecisionAction.ANSWER
    assert result.rounds_used == result.queries_used == 2
    assert result.trace[0].unresolved_after != result.trace[0].unresolved_before
    assert result.trace[1].outcome == "progress"


def test_complete_initial_evidence_skips_retrieval() -> None:
    complete = (
        _table_chunk(
            chunk_id="aapl-complete", ticker="AAPL", company="Apple Inc.",
            year_values=(("2024", "$391 billion"), ("2022", "$394 billion")),
        ),
        _table_chunk(
            chunk_id="msft-complete", ticker="MSFT", company="Microsoft Corporation",
            year_values=(("2024", "$245 billion"), ("2022", "$198 billion")),
        ),
    )
    retriever = RecordingRetriever([])

    result = AdaptiveRetrievalController(retriever).run(COMPARISON, complete)

    assert result.final_decision.action == DecisionAction.ANSWER
    assert result.stop_reason == AdaptiveStopReason.EVIDENCE_SUFFICIENT
    assert result.queries_used == 0
    assert retriever.queries == []


def test_repeated_evidence_stops_without_a_duplicate_search_loop() -> None:
    initial = _initial_one_gap()
    retriever = RecordingRetriever([[initial[1], initial[1]]])

    result = AdaptiveRetrievalController(retriever).run(COMPARISON, initial)

    assert result.final_decision.action == DecisionAction.ABSTAIN
    assert result.stop_reason == AdaptiveStopReason.NO_PROGRESS
    assert result.queries_used == 1
    assert result.rounds_used == 1
    assert result.trace[0].retrieved_count == 2
    assert result.trace[0].added_chunk_ids == ()
    assert len({item["chunk_id"] for item in result.evidence_chunks}) == len(result.evidence_chunks)


def test_fingerprinted_query_is_not_executed_twice_after_partial_progress() -> None:
    question = "What were Apple's revenue and net income in FY2022?"
    net_income = _table_chunk(
        chunk_id="aapl-net-income", ticker="AAPL", company="Apple Inc.",
        year_values=(("2022", "$99 billion"),), label="Net income",
    )
    # The first revenue-targeted call returns the other requested metric.
    retriever = RecordingRetriever([[net_income], [net_income]])

    result = AdaptiveRetrievalController(retriever).run(
        question,
        budget=AdaptiveRetrievalBudget(max_rounds=3, max_queries=3),
    )

    assert result.final_decision.action == DecisionAction.ABSTAIN
    assert result.stop_reason == AdaptiveStopReason.NO_PROGRESS
    assert result.queries_used == 1
    assert len(retriever.queries) == 1
    assert len(result.trace) == 2
    assert result.trace[1].outcome == "duplicate_query"


def test_irrelevant_new_evidence_is_preserved_but_stops_as_no_progress() -> None:
    initial = _initial_one_gap()
    irrelevant = _table_chunk(
        chunk_id="msft-net-income", ticker="MSFT", company="Microsoft Corporation",
        year_values=(("2022", "$72 billion"),), label="Net income",
    )
    retriever = RecordingRetriever([[irrelevant]])

    result = AdaptiveRetrievalController(retriever).run(COMPARISON, initial)

    assert result.final_decision.action == DecisionAction.ABSTAIN
    assert result.stop_reason == AdaptiveStopReason.NO_PROGRESS
    assert {item["chunk_id"] for item in result.evidence_chunks} == {
        *(item["chunk_id"] for item in initial), "msft-net-income"
    }


def test_query_budget_exhaustion_keeps_evidence_and_abstains() -> None:
    initial = (
        _table_chunk(
            chunk_id="aapl-fy2024", ticker="AAPL", company="Apple Inc.",
            year_values=(("2024", "$391 billion"),),
        ),
        _table_chunk(
            chunk_id="msft-fy2024", ticker="MSFT", company="Microsoft Corporation",
            year_values=(("2024", "$245 billion"),),
        ),
    )
    retriever = RecordingRetriever([[
        _table_chunk(
            chunk_id="aapl-fy2022", ticker="AAPL", company="Apple Inc.",
            year_values=(("2022", "$394 billion"),),
        ),
    ]])

    result = AdaptiveRetrievalController(retriever).run(
        COMPARISON,
        initial,
        budget=AdaptiveRetrievalBudget(max_rounds=3, max_queries=1),
    )

    assert result.final_decision.action == DecisionAction.ABSTAIN
    assert result.stop_reason == AdaptiveStopReason.QUERY_BUDGET_EXHAUSTED
    assert result.queries_used == 1
    assert {item["chunk_id"] for item in result.evidence_chunks} >= {
        "aapl-fy2022", "aapl-fy2024", "msft-fy2024"
    }


def test_zero_query_budget_abstains_without_calling_retriever() -> None:
    retriever = RecordingRetriever([])

    result = AdaptiveRetrievalController(retriever).run(
        COMPARISON,
        _initial_one_gap(),
        budget=AdaptiveRetrievalBudget(max_queries=0),
    )

    assert result.final_decision.action == DecisionAction.ABSTAIN
    assert result.stop_reason == AdaptiveStopReason.QUERY_BUDGET_EXHAUSTED
    assert result.queries_used == 0
    assert retriever.queries == []


def test_evidence_token_budget_rejects_oversized_new_chunks() -> None:
    initial = _initial_one_gap()
    initial = tuple({**chunk, "token_count": 1} for chunk in initial)
    oversized = {**_final_msft_fy2022(), "token_count": 10}
    retriever = RecordingRetriever([[oversized]])

    result = AdaptiveRetrievalController(retriever).run(
        COMPARISON,
        initial,
        budget=AdaptiveRetrievalBudget(max_evidence_tokens=5),
    )

    assert result.final_decision.action == DecisionAction.ABSTAIN
    assert result.stop_reason == AdaptiveStopReason.EVIDENCE_TOKEN_BUDGET_EXHAUSTED
    assert result.evidence_tokens_used == 2
    assert {item["chunk_id"] for item in result.evidence_chunks} == {
        item["chunk_id"] for item in initial
    }
    assert result.trace[0].outcome == "token_budget_exhausted"


def test_exhausted_initial_token_budget_abstains_without_dropping_input() -> None:
    initial = tuple({**chunk, "token_count": 2} for chunk in _initial_one_gap())
    retriever = RecordingRetriever([])

    result = AdaptiveRetrievalController(retriever).run(
        COMPARISON,
        initial,
        budget=AdaptiveRetrievalBudget(max_evidence_tokens=4),
    )

    assert result.final_decision.action == DecisionAction.ABSTAIN
    assert result.stop_reason == AdaptiveStopReason.EVIDENCE_TOKEN_BUDGET_EXHAUSTED
    assert result.queries_used == 0
    assert result.evidence_chunks == initial


def test_time_budget_stops_before_starting_another_retrieval_round() -> None:
    clock = FakeClock()
    initial = (
        _table_chunk(
            chunk_id="aapl-fy2024", ticker="AAPL", company="Apple Inc.",
            year_values=(("2024", "$391 billion"),),
        ),
        _table_chunk(
            chunk_id="msft-fy2024", ticker="MSFT", company="Microsoft Corporation",
            year_values=(("2024", "$245 billion"),),
        ),
    )

    class SlowFirstRetriever(RecordingRetriever):
        def retrieve(self, query: str, top_k: int = 5) -> list[Any]:
            result = super().retrieve(query, top_k)
            clock.now += 2.0
            return result

    first_gap = _table_chunk(
        chunk_id="aapl-fy2022", ticker="AAPL", company="Apple Inc.",
        year_values=(("2022", "$394 billion"),),
    )
    retriever = SlowFirstRetriever([[first_gap], [_final_msft_fy2022()]])

    result = AdaptiveRetrievalController(retriever, clock=clock).run(
        COMPARISON,
        initial,
        budget=AdaptiveRetrievalBudget(max_rounds=3, time_budget_seconds=1.0),
    )

    assert result.final_decision.action == DecisionAction.ABSTAIN
    assert result.stop_reason == AdaptiveStopReason.TIME_BUDGET_EXHAUSTED
    assert result.queries_used == 1
    assert len(retriever.queries) == 1
    assert result.trace[0].outcome == "time_budget_exhausted"


def test_unsupported_question_never_calls_retriever() -> None:
    retriever = RecordingRetriever([[_final_msft_fy2022()]])

    result = AdaptiveRetrievalController(retriever).run(
        "What was Apple's revenue in the last 3 years?",
        _initial_one_gap(),
    )

    assert result.final_decision.action == DecisionAction.ABSTAIN
    assert result.stop_reason == AdaptiveStopReason.UNSUPPORTED_QUESTION
    assert result.queries_used == 0
    assert retriever.queries == []


def test_retrieval_error_is_traced_and_ends_in_abstention() -> None:
    class BrokenRetriever:
        def retrieve(self, query: str, top_k: int = 5) -> list[Any]:
            raise TimeoutError("fixture failure")

    result = AdaptiveRetrievalController(BrokenRetriever()).run(
        COMPARISON,
        _initial_one_gap(),
    )

    assert result.final_decision.action == DecisionAction.ABSTAIN
    assert result.stop_reason == AdaptiveStopReason.RETRIEVAL_ERROR
    assert result.queries_used == 1
    assert result.trace[0].outcome == "retrieval_error"
    assert result.trace[0].error_type == "TimeoutError"
