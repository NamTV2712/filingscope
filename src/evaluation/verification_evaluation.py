"""Controlled synthetic evaluation for claim and citation verification."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.verification import ClaimLevelVerifier
from src.verification.models import ClaimStatus, ResponseDisposition


def _financial_chunk(
    *,
    chunk_id: str,
    values: tuple[tuple[str, str], ...] = (("2023", "$100 billion"), ("2024", "$110 billion")),
    label: str = "Revenue",
) -> dict[str, Any]:
    years = "\n".join(year for year, _ in values)
    amounts = "\n".join(amount for _, amount in values)
    return {
        "chunk_id": chunk_id,
        "ticker": "AAPL",
        "company": "Apple Inc.",
        "doc_name": "AAPL_annual_report.pdf",
        "document_id": "AAPL_annual_report.pdf",
        "page_number": 10,
        "source_url": "https://example.com/apple-annual-report.pdf",
        "text": f"{years}\n{label}\n{amounts}",
    }


def _industry_chunk() -> dict[str, Any]:
    return {
        "chunk_id": "amcor-profile",
        "ticker": "AMCR",
        "company": "Amcor plc",
        "doc_name": "AMCR_annual_report.pdf",
        "page_number": 1,
        "source_url": "https://example.com/amcor.pdf",
        "text": "Amcor plc operates in the packaging industry and serves food, beverage, and healthcare markets.",
    }


@dataclass(frozen=True)
class VerificationScenario:
    case_id: str
    question: str
    answer: str
    evidence: tuple[dict[str, Any], ...]
    expected_disposition: ResponseDisposition
    expected_claim_status: ClaimStatus | None


def verification_scenarios() -> tuple[VerificationScenario, ...]:
    """Return fixed, hand-labeled cases for core P4 verifier behaviors."""
    return (
        VerificationScenario(
            "supported_financial_value",
            "What was Apple's revenue in FY2024?",
            "Apple revenue was $110 billion in FY2024 [Source 1].",
            (_financial_chunk(chunk_id="apple-revenue"),),
            ResponseDisposition.VERIFIED, ClaimStatus.SUPPORTED,
        ),
        VerificationScenario(
            "contradicted_financial_value",
            "What was Apple's revenue in FY2024?",
            "Apple revenue was $109 billion in FY2024 [Source 1].",
            (_financial_chunk(chunk_id="apple-revenue"),),
            ResponseDisposition.REJECTED, ClaimStatus.CONTRADICTED,
        ),
        VerificationScenario(
            "unsupported_metric_in_citation",
            "What was Apple's revenue in FY2024?",
            "Apple revenue was $110 billion in FY2024 [Source 1].",
            (_financial_chunk(chunk_id="apple-net-income", label="Net income"),),
            ResponseDisposition.REJECTED, ClaimStatus.UNSUPPORTED,
        ),
        VerificationScenario(
            "wrong_evidence_period",
            "What was Apple's revenue in FY2024?",
            "Apple revenue was $110 billion in FY2024 [Source 1].",
            (_financial_chunk(chunk_id="apple-2023", values=(("2023", "$110 billion"),)),),
            ResponseDisposition.REJECTED, ClaimStatus.UNSUPPORTED,
        ),
        VerificationScenario(
            "missing_citation",
            "What was Apple's revenue in FY2024?",
            "Apple revenue was $110 billion in FY2024.",
            (_financial_chunk(chunk_id="apple-revenue"),),
            ResponseDisposition.ABSTAIN, ClaimStatus.UNVERIFIABLE,
        ),
        VerificationScenario(
            "malformed_legacy_citation",
            "What was Apple's revenue in FY2024?",
            "Apple revenue was $110 billion in FY2024 【 1 † L3-L5】.",
            (_financial_chunk(chunk_id="apple-revenue"),),
            ResponseDisposition.ABSTAIN, ClaimStatus.UNVERIFIABLE,
        ),
        VerificationScenario(
            "out_of_range_citation",
            "What was Apple's revenue in FY2024?",
            "Apple revenue was $110 billion in FY2024 [Source 2].",
            (_financial_chunk(chunk_id="apple-revenue"),),
            ResponseDisposition.ABSTAIN, ClaimStatus.UNVERIFIABLE,
        ),
        VerificationScenario(
            "growth_recomputed_correctly",
            "Did Apple's revenue grow from FY2023 to FY2024?",
            "Apple revenue grew 10% from FY2023 to FY2024 [Source 1].",
            (_financial_chunk(chunk_id="apple-revenue"),),
            ResponseDisposition.VERIFIED, ClaimStatus.SUPPORTED,
        ),
        VerificationScenario(
            "growth_arithmetic_mismatch",
            "Did Apple's revenue grow from FY2023 to FY2024?",
            "Apple revenue grew 15% from FY2023 to FY2024 [Source 1].",
            (_financial_chunk(chunk_id="apple-revenue"),),
            ResponseDisposition.REJECTED, ClaimStatus.CONTRADICTED,
        ),
        VerificationScenario(
            "period_difference_recomputed",
            "How much did Apple's revenue increase from FY2023 to FY2024?",
            "Apple revenue increased by $10 billion from FY2023 to FY2024 [Source 1].",
            (_financial_chunk(chunk_id="apple-revenue"),),
            ResponseDisposition.VERIFIED, ClaimStatus.SUPPORTED,
        ),
        VerificationScenario(
            "period_difference_mismatch",
            "How much did Apple's revenue increase from FY2023 to FY2024?",
            "Apple revenue increased by $12 billion from FY2023 to FY2024 [Source 1].",
            (_financial_chunk(chunk_id="apple-revenue"),),
            ResponseDisposition.REJECTED, ClaimStatus.CONTRADICTED,
        ),
        VerificationScenario(
            "supported_topical_claim",
            "What industry does Amcor operate in?",
            "Amcor operates in the packaging industry [Source 1].",
            (_industry_chunk(),),
            ResponseDisposition.VERIFIED, ClaimStatus.SUPPORTED,
        ),
        VerificationScenario(
            "partially_supported_topical_claim",
            "What industry does Amcor operate in?",
            "Amcor operates in the packaging and aerospace industries [Source 1].",
            (_industry_chunk(),),
            ResponseDisposition.PARTIAL, ClaimStatus.PARTIALLY_SUPPORTED,
        ),
        VerificationScenario(
            "conflicting_cited_sources",
            "What was Apple's revenue in FY2024?",
            "Apple revenue was $110 billion in FY2024 [Source 1] [Source 2].",
            (
                _financial_chunk(chunk_id="apple-a"),
                _financial_chunk(chunk_id="apple-b", values=(("2024", "$109 billion"),)),
            ),
            ResponseDisposition.ABSTAIN, ClaimStatus.UNVERIFIABLE,
        ),
        VerificationScenario(
            "fallback_answer",
            "What was Apple's revenue in FY2024?",
            "I could not find sufficient information to answer.",
            (_financial_chunk(chunk_id="apple-revenue"),),
            ResponseDisposition.ABSTAIN, None,
        ),
    )


def evaluate_verifications(
    scenarios: tuple[VerificationScenario, ...] | None = None,
) -> dict[str, Any]:
    """Run fixed cases and report disposition/status agreement."""
    cases = scenarios or verification_scenarios()
    verifier = ClaimLevelVerifier()
    outputs: list[dict[str, Any]] = []
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    disposition_correct = status_correct = status_labeled = 0

    for scenario in cases:
        result = verifier.verify(scenario.question, scenario.answer, scenario.evidence)
        actual_status = result.claims[0].status.value if result.claims else None
        expected_status = scenario.expected_claim_status.value if scenario.expected_claim_status else None
        expected_disposition = scenario.expected_disposition.value
        actual_disposition = result.disposition.value
        disposition_match = actual_disposition == expected_disposition
        status_match = actual_status == expected_status
        disposition_correct += int(disposition_match)
        if expected_status is not None:
            status_labeled += 1
            status_correct += int(status_match)
        confusion[expected_disposition][actual_disposition] += 1
        outputs.append({
            "case_id": scenario.case_id,
            "expected_disposition": expected_disposition,
            "actual_disposition": actual_disposition,
            "expected_claim_status": expected_status,
            "actual_claim_status": actual_status,
            "disposition_correct": disposition_match,
            "claim_status_correct": status_match,
            "citation_status": result.claims[0].citation_status.value if result.claims else None,
            "reason_codes": list(result.claims[0].reason_codes) if result.claims else list(result.reason_codes),
        })

    count = len(cases)
    return {
        "benchmark": "filingscope-p4-verification-synthetic-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "case_count": count,
        "disposition_correct": disposition_correct,
        "disposition_accuracy": disposition_correct / count if count else 0.0,
        "claim_status_labeled_cases": status_labeled,
        "claim_status_correct": status_correct,
        "claim_status_accuracy": status_correct / status_labeled if status_labeled else 0.0,
        "disposition_confusion": {
            expected: dict(sorted(actual.items()))
            for expected, actual in sorted(confusion.items())
        },
        "cases": outputs,
    }
