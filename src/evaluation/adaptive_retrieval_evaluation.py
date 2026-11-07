"""Controlled evaluation of bounded multi-hop adaptive retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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


def _aapl_complete() -> dict[str, Any]:
    return _table_chunk(
        chunk_id="aapl-complete", ticker="AAPL", company="Apple Inc.",
        year_values=(("2024", "$391 billion"), ("2022", "$394 billion")),
    )


def _msft_fy2024() -> dict[str, Any]:
    return _table_chunk(
        chunk_id="msft-fy2024", ticker="MSFT", company="Microsoft Corporation",
        year_values=(("2024", "$245 billion"),),
    )


def _msft_fy2022() -> dict[str, Any]:
    return _table_chunk(
        chunk_id="msft-fy2022", ticker="MSFT", company="Microsoft Corporation",
        year_values=(("2022", "$198 billion"),),
    )


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _FixtureRetriever:
    def __init__(
        self,
        responses: tuple[tuple[dict[str, Any], ...], ...],
        *,
        clock: _Clock,
        advance_seconds: float = 0.0,
    ) -> None:
        self.responses = responses
        self.clock = clock
        self.advance_seconds = advance_seconds
        self.queries: list[str] = []

    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        self.queries.append(query)
        self.clock.now += self.advance_seconds
        index = len(self.queries) - 1
        return list(self.responses[index]) if index < len(self.responses) else []


@dataclass(frozen=True)
class _Scenario:
    case_id: str
    initial_chunks: tuple[dict[str, Any], ...]
    responses: tuple[tuple[dict[str, Any], ...], ...]
    expected_action: DecisionAction
    expected_stop: AdaptiveStopReason
    budget: AdaptiveRetrievalBudget = AdaptiveRetrievalBudget()
    completion_eligible: bool = False
    advance_seconds: float = 0.0
    question: str = COMPARISON


def _scenarios() -> tuple[_Scenario, ...]:
    complete = (
        _aapl_complete(),
        _table_chunk(
            chunk_id="msft-complete", ticker="MSFT", company="Microsoft Corporation",
            year_values=(("2024", "$245 billion"), ("2022", "$198 billion")),
        ),
    )
    one_gap = (_aapl_complete(), _msft_fy2024())
    two_gaps = (
        _table_chunk(
            chunk_id="aapl-fy2024", ticker="AAPL", company="Apple Inc.",
            year_values=(("2024", "$391 billion"),),
        ),
        _msft_fy2024(),
    )
    aapl_fy2022 = _table_chunk(
        chunk_id="aapl-fy2022", ticker="AAPL", company="Apple Inc.",
        year_values=(("2022", "$394 billion"),),
    )
    return (
        _Scenario(
            "already_sufficient", complete, (), DecisionAction.ANSWER,
            AdaptiveStopReason.EVIDENCE_SUFFICIENT,
        ),
        _Scenario(
            "one_gap_completion", one_gap, ((_msft_fy2022(),),),
            DecisionAction.ANSWER, AdaptiveStopReason.EVIDENCE_SUFFICIENT,
            completion_eligible=True,
        ),
        _Scenario(
            "two_gap_multi_hop_completion", two_gaps,
            ((aapl_fy2022,), (_msft_fy2022(),)),
            DecisionAction.ANSWER, AdaptiveStopReason.EVIDENCE_SUFFICIENT,
            completion_eligible=True,
        ),
        _Scenario(
            "no_progress_duplicate", one_gap, ((_msft_fy2024(),),),
            DecisionAction.ABSTAIN, AdaptiveStopReason.NO_PROGRESS,
        ),
        _Scenario(
            "irrelevant_result", one_gap,
            ((_table_chunk(
                chunk_id="msft-net-income", ticker="MSFT",
                company="Microsoft Corporation", year_values=(("2022", "$72 billion"),),
                label="Net income",
            ),),),
            DecisionAction.ABSTAIN, AdaptiveStopReason.NO_PROGRESS,
        ),
        _Scenario(
            "query_budget", two_gaps, ((aapl_fy2022,),),
            DecisionAction.ABSTAIN, AdaptiveStopReason.QUERY_BUDGET_EXHAUSTED,
            budget=AdaptiveRetrievalBudget(max_rounds=3, max_queries=1),
        ),
        _Scenario(
            "time_budget", two_gaps, ((aapl_fy2022,),),
            DecisionAction.ABSTAIN, AdaptiveStopReason.TIME_BUDGET_EXHAUSTED,
            budget=AdaptiveRetrievalBudget(max_rounds=3, time_budget_seconds=1.0),
            advance_seconds=2.0,
        ),
        _Scenario(
            "evidence_token_budget", tuple(
                {**chunk, "token_count": 1} for chunk in one_gap
            ), ((_table_chunk(
                chunk_id="msft-fy2022", ticker="MSFT",
                company="Microsoft Corporation", year_values=(("2022", "$198 billion"),),
                token_count=10,
            ),),),
            DecisionAction.ABSTAIN, AdaptiveStopReason.EVIDENCE_TOKEN_BUDGET_EXHAUSTED,
            budget=AdaptiveRetrievalBudget(max_evidence_tokens=5),
        ),
        _Scenario(
            "unsupported_relative_period", one_gap, ((_msft_fy2022(),),),
            DecisionAction.ABSTAIN, AdaptiveStopReason.UNSUPPORTED_QUESTION,
            question="What was Apple's revenue in the last 3 years?",
        ),
    )


def evaluate_adaptive_retrieval() -> dict[str, Any]:
    scenarios = _scenarios()
    case_results: list[dict[str, Any]] = []
    action_correct = stop_correct = 0
    multi_hop_correct = multi_hop_count = 0
    query_total = 0
    no_progress_detected = no_progress_cases = 0

    for scenario in scenarios:
        clock = _Clock()
        retriever = _FixtureRetriever(
            scenario.responses,
            clock=clock,
            advance_seconds=scenario.advance_seconds,
        )
        result = AdaptiveRetrievalController(retriever, clock=clock).run(
            scenario.question,
            scenario.initial_chunks,
            budget=scenario.budget,
        )
        actual_action = result.final_decision.action
        action_ok = actual_action == scenario.expected_action
        stop_ok = result.stop_reason == scenario.expected_stop
        action_correct += int(action_ok)
        stop_correct += int(stop_ok)
        query_total += result.queries_used
        if scenario.completion_eligible:
            multi_hop_count += 1
            multi_hop_correct += int(actual_action == DecisionAction.ANSWER)
        if scenario.expected_stop == AdaptiveStopReason.NO_PROGRESS:
            no_progress_cases += 1
            no_progress_detected += int(result.stop_reason == AdaptiveStopReason.NO_PROGRESS)
        case_results.append({
            "case_id": scenario.case_id,
            "expected_action": scenario.expected_action.value,
            "actual_action": actual_action.value,
            "expected_stop_reason": scenario.expected_stop.value,
            "actual_stop_reason": result.stop_reason.value,
            "action_correct": action_ok,
            "stop_reason_correct": stop_ok,
            "queries_used": result.queries_used,
            "rounds_used": result.rounds_used,
            "initial_evidence_count": len(scenario.initial_chunks),
            "final_evidence_count": len(result.evidence_chunks),
            "trace": [item.model_dump(mode="json") for item in result.trace],
        })

    count = len(scenarios)
    return {
        "benchmark": "filingscope-p3-adaptive-synthetic-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "case_count": count,
        "action_correct": action_correct,
        "action_accuracy": action_correct / count if count else 0.0,
        "stop_reason_correct": stop_correct,
        "stop_reason_accuracy": stop_correct / count if count else 0.0,
        "multi_hop_completed": multi_hop_correct,
        "multi_hop_completion_cases": multi_hop_count,
        "multi_hop_completion_rate": (
            multi_hop_correct / multi_hop_count if multi_hop_count else 0.0
        ),
        "no_progress_detected": no_progress_detected,
        "no_progress_cases": no_progress_cases,
        "no_progress_detection_rate": (
            no_progress_detected / no_progress_cases if no_progress_cases else 0.0
        ),
        "total_queries": query_total,
        "mean_queries_per_case": query_total / count if count else 0.0,
        "cases": case_results,
    }
