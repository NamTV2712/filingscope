"""Controlled synthetic evaluation for the evidence decision layer.

These cases test decision behavior with explicit, small evidence bundles. They
are not FinanceBench answer-quality labels and contain no provider calls.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.decision.company_catalog import CompanyCatalog
from src.decision.models import DecisionAction, DecisionBudget
from src.decision.policy import EvidenceDecisionLayer


@dataclass(frozen=True)
class DecisionScenario:
    case_id: str
    question: str
    chunks: tuple[dict[str, Any], ...]
    expected_action: DecisionAction
    expected_reason_code: str
    remaining_retrieval_attempts: int = 1


def _table_chunk(
    *,
    chunk_id: str,
    ticker: str,
    company: str,
    year_values: tuple[tuple[str, str], ...],
    label: str = "Total revenue",
    source_url: str | None = "https://example.com/report.pdf",
    page_number: int | None = 4,
) -> dict[str, Any]:
    years = "\n".join(year for year, _ in year_values)
    values = "\n".join(value for _, value in year_values)
    return {
        "chunk_id": chunk_id,
        "ticker": ticker,
        "company": company,
        "doc_name": f"{ticker}_annual_report.pdf",
        "document_id": f"{ticker}_annual_report.pdf",
        "page_number": page_number,
        "source_url": source_url,
        "text": f"{years}\n{label}\n{values}",
    }


def _complete_comparison() -> tuple[dict[str, Any], ...]:
    return (
        _table_chunk(
            chunk_id="aapl-complete",
            ticker="AAPL",
            company="Apple Inc.",
            year_values=(("2024", "$391 billion"), ("2022", "$394 billion")),
        ),
        _table_chunk(
            chunk_id="msft-complete",
            ticker="MSFT",
            company="Microsoft Corporation",
            year_values=(("2024", "$245 billion"), ("2022", "$198 billion")),
        ),
    )


def decision_scenarios() -> tuple[DecisionScenario, ...]:
    """Return the fixed, hand-labeled P2 decision test set."""
    complete = _complete_comparison()
    incomplete = (
        complete[0],
        _table_chunk(
            chunk_id="msft-one-period",
            ticker="MSFT",
            company="Microsoft Corporation",
            year_values=(("2024", "$245 billion"),),
        ),
    )
    conflicting = (
        _table_chunk(
            chunk_id="aapl-value-one",
            ticker="AAPL",
            company="Apple Inc.",
            year_values=(("2022", "$394 billion"),),
        ),
        _table_chunk(
            chunk_id="aapl-value-two",
            ticker="AAPL",
            company="Apple Inc.",
            year_values=(("2022", "$390 billion"),),
        ),
    )
    return (
        DecisionScenario(
            "complete_comparison", "Compare Apple and Microsoft revenue growth between 2022 and 2024",
            complete, DecisionAction.ANSWER, "requirements_satisfied",
        ),
        DecisionScenario(
            "missing_company_period", "Compare Apple and Microsoft revenue growth between 2022 and 2024",
            incomplete, DecisionAction.RETRIEVE_MORE, "missing_evidence",
        ),
        DecisionScenario(
            "missing_after_budget", "Compare Apple and Microsoft revenue growth between 2022 and 2024",
            incomplete, DecisionAction.ABSTAIN, "incomplete_evidence_after_budget", 0,
        ),
        DecisionScenario(
            "wrong_entity", "What was Apple's revenue in FY2022?",
            (_table_chunk(
                chunk_id="wrong-company", ticker="MSFT", company="Microsoft Corporation",
                year_values=(("2022", "$198 billion"),),
            ),),
            DecisionAction.RETRIEVE_MORE, "missing_evidence",
        ),
        DecisionScenario(
            "wrong_metric", "What was Apple's revenue in FY2022?",
            (_table_chunk(
                chunk_id="wrong-metric", ticker="AAPL", company="Apple Inc.",
                year_values=(("2022", "$99 billion"),), label="Net income",
            ),),
            DecisionAction.RETRIEVE_MORE, "missing_evidence",
        ),
        DecisionScenario(
            "wrong_period", "What was Apple's revenue in FY2022?",
            (_table_chunk(
                chunk_id="wrong-period", ticker="AAPL", company="Apple Inc.",
                year_values=(("2024", "$391 billion"),),
            ),),
            DecisionAction.RETRIEVE_MORE, "missing_evidence",
        ),
        DecisionScenario(
            "missing_numeric_value", "What was Apple's revenue in FY2022?",
            ({
                "chunk_id": "no-number", "ticker": "AAPL", "company": "Apple Inc.",
                "doc_name": "AAPL_annual_report.pdf", "page_number": 4,
                "source_url": "https://example.com/report.pdf",
                "text": "Apple revenue grew during FY2022.",
            },),
            DecisionAction.RETRIEVE_MORE, "missing_evidence",
        ),
        DecisionScenario(
            "missing_provenance", "What was Apple's revenue in FY2022?",
            (_table_chunk(
                chunk_id="unattributed", ticker="AAPL", company="Apple Inc.",
                year_values=(("2022", "$394 billion"),), source_url=None, page_number=None,
            ),),
            DecisionAction.RETRIEVE_MORE, "missing_evidence",
        ),
        DecisionScenario(
            "conflicting_values", "What was Apple's revenue in FY2022?",
            conflicting, DecisionAction.RETRIEVE_MORE, "conflicting_evidence",
        ),
        DecisionScenario(
            "conflicting_source_metadata", "What was Apple's revenue in FY2022?",
            ({
                **_table_chunk(
                    chunk_id="metadata-conflict", ticker="AAPL", company="Apple Inc.",
                    year_values=(("2022", "$394 billion"),),
                ),
                "metadata_conflicts": [{"field": "company", "observed": "Other issuer"}],
            },),
            DecisionAction.RETRIEVE_MORE, "conflicting_evidence",
        ),
        DecisionScenario(
            "conflict_after_budget", "What was Apple's revenue in FY2022?",
            conflicting, DecisionAction.ABSTAIN, "conflicting_evidence_after_budget", 0,
        ),
        DecisionScenario(
            "unit_mismatch", "Compare Apple and Microsoft revenue growth between 2022 and 2024",
            (
                complete[0],
                _table_chunk(
                    chunk_id="msft-eur", ticker="MSFT", company="Microsoft Corporation",
                    year_values=(("2024", "€245 billion"), ("2022", "€198 billion")),
                ),
            ),
            DecisionAction.RETRIEVE_MORE, "incomplete_operation_inputs",
        ),
        DecisionScenario(
            "complete_qualitative", "What industry does Amcor operate in?",
            ({
                "chunk_id": "amcor-industry", "company": "Amcor plc",
                "doc_name": "AMCOR_2023_annualreport", "page_number": 1,
                "source_url": "https://example.com/amcor.pdf",
                "text": "Amcor plc operates in the packaging industry and serves food, beverage and healthcare markets.",
            },),
            DecisionAction.ANSWER, "requirements_satisfied",
        ),
        DecisionScenario(
            "unsupported_relative_period", "What was Apple's revenue in the last 3 years through FY2024?",
            complete, DecisionAction.ABSTAIN, "relative_period_not_supported",
        ),
        DecisionScenario(
            "unrecognized_metric", "Compare Apple and Microsoft performance",
            complete, DecisionAction.ABSTAIN, "metric_not_recognized",
        ),
    )


def evaluate_decisions(
    scenarios: tuple[DecisionScenario, ...] | None = None,
) -> dict[str, Any]:
    """Run the fixed cases and calculate action/reason correctness."""
    cases = scenarios or decision_scenarios()
    outputs: list[dict[str, Any]] = []
    action_confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    action_correct = reason_correct = 0

    for scenario in cases:
        # Production derives non-default company aliases from verified corpus
        # metadata. Build the same lookup from each controlled fixture bundle.
        catalog_rows = [
            {
                "company": chunk.get("company"),
                "ticker": chunk.get("ticker"),
                "doc_name": chunk.get("doc_name"),
            }
            for chunk in scenario.chunks
            if chunk.get("company")
        ]
        layer = EvidenceDecisionLayer(
            catalog=CompanyCatalog.from_document_rows(catalog_rows)
        )
        result = layer.decide(
            scenario.question,
            scenario.chunks,
            budget=DecisionBudget(
                remaining_retrieval_attempts=scenario.remaining_retrieval_attempts
            ),
        )
        actual_action = result.action.value
        expected_action = scenario.expected_action.value
        action_confusion[expected_action][actual_action] += 1
        is_action_correct = actual_action == expected_action
        is_reason_correct = result.reason_code == scenario.expected_reason_code
        action_correct += int(is_action_correct)
        reason_correct += int(is_reason_correct)
        outputs.append({
            "case_id": scenario.case_id,
            "expected_action": expected_action,
            "actual_action": actual_action,
            "expected_reason_code": scenario.expected_reason_code,
            "actual_reason_code": result.reason_code,
            "action_correct": is_action_correct,
            "reason_correct": is_reason_correct,
            "gap_requirement_ids": list(result.gap_requirement_ids),
            "gap_codes": list(result.gap_codes),
        })

    count = len(cases)
    confusion = {
        expected: dict(sorted(actual.items()))
        for expected, actual in sorted(action_confusion.items())
    }
    return {
        "benchmark": "filingscope-p2-decision-synthetic-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "case_count": count,
        "action_correct": action_correct,
        "action_accuracy": action_correct / count if count else 0.0,
        "reason_correct": reason_correct,
        "reason_accuracy": reason_correct / count if count else 0.0,
        "action_confusion": confusion,
        "cases": outputs,
    }
