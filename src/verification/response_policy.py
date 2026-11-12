"""Release only supported claims after a single actionable correction pass."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.decision.models import QuestionRequirements
from src.verification.atomic_claim_verifier import AtomicClaimVerifier
from src.verification.claim_verifier import _DECLINE_RE, _SCALE_FACTORS, _context_unit
from src.verification.models import (
    CalculationOperation, ClaimAssessment, ClaimStatus, ResponseDisposition, VerificationResult,
)


INSUFFICIENT_EVIDENCE_ANSWER = (
    "I could not find sufficient information in the available documents to answer this question with confidence."
)
_INCREASE = re.compile(r"\b(?:grew|increased|rose|gained)\b", re.I)
_NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class AnswerRelease:
    answer: str
    result: VerificationResult
    initial: VerificationResult
    correction_passes: int = 0


def _arithmetic_correction(claim: ClaimAssessment) -> str | None:
    calculation = claim.calculation
    if calculation is None or calculation.status != "mismatch" or calculation.expected_value is None:
        return None
    if len(claim.unsupported_values) != 1:
        return None
    raw = claim.unsupported_values[0]
    if not raw or claim.statement.count(raw) != 1 or len(_NUMBER.findall(raw)) != 1:
        return None
    statement = claim.statement
    value = calculation.expected_value
    if calculation.operation == CalculationOperation.PERCENTAGE_GROWTH:
        if _DECLINE_RE.search(statement):
            if value > 0:
                statement = _DECLINE_RE.sub("grew", statement, count=1)
            else:
                value = abs(value)
        elif value < 0 and _INCREASE.search(statement):
            statement = _INCREASE.sub("declined", statement, count=1)
            value = abs(value)
    elif calculation.operation == CalculationOperation.DIFFERENCE:
        if "absolute" not in statement.casefold():
            return None
        _currency, scale = _context_unit(raw, None, None)
        if scale is not None:
            value /= _SCALE_FACTORS[scale]
    else:
        return None
    number = format(value, "f")
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    replacement = _NUMBER.sub(number, raw, count=1)
    return statement.replace(raw, replacement, 1)


def _disposition(result: VerificationResult, disposition: ResponseDisposition, reason: str) -> VerificationResult:
    return result.model_copy(update={
        "disposition": disposition,
        "reason_codes": (*result.reason_codes, reason),
    })


def _release_supported(
    result: VerificationResult, answer: str, requirements: QuestionRequirements, *, dropped: bool,
) -> tuple[str, VerificationResult]:
    if result.disposition in {ResponseDisposition.REJECTED, ResponseDisposition.ABSTAIN}:
        return INSUFFICIENT_EVIDENCE_ANSWER, result
    supported = [claim for claim in result.claims if
        claim.status == ClaimStatus.SUPPORTED and claim.supporting_evidence_ids]
    if len(supported) != len(result.claims) or not supported:
        result = _disposition(result, ResponseDisposition.ABSTAIN, "no_safe_complete_draft")
        return INSUFFICIENT_EVIDENCE_ANSWER, result
    required = {item.requirement_id for item in requirements.evidence}
    covered = {item for claim in supported for item in claim.requirement_ids}
    if required and not required.intersection(covered):
        result = _disposition(result, ResponseDisposition.ABSTAIN, "no_requested_claim_supported")
        return INSUFFICIENT_EVIDENCE_ANSWER, result
    slots = {item.requirement_id: (item.entity_id, item.metric_id) for item in requirements.evidence if item.quantitative}
    required_arithmetic = {
        (operation.operation, entity, metric)
        for operation in requirements.operations
        if operation.operation in {"growth", "difference", "ratio", "average", "cagr"}
        for entity, metric in slots.values() if operation.metric_id in (None, metric)
    }
    observed_arithmetic = set()
    for claim in supported:
        operation = None
        if claim.calculation is not None:
            if claim.calculation.operation == CalculationOperation.PERCENTAGE_GROWTH:
                operation = "growth"
            elif claim.calculation.operation == CalculationOperation.DIFFERENCE:
                operation = "difference"
        elif "growth_direction_matches_cited_values" in claim.reason_codes:
            operation = "growth"
        if operation:
            observed_arithmetic.update((operation, *slots[item]) for item in claim.requirement_ids if item in slots)
    if dropped or not required.issubset(covered) or not required_arithmetic.issubset(observed_arithmetic):
        reason = "claims_removed_on_revision" if dropped else "requested_answer_incomplete"
        result = _disposition(result, ResponseDisposition.PARTIAL, reason)
    return answer, result


def verify_and_release(
    verifier: AtomicClaimVerifier,
    question: str,
    answer: str,
    chunks: list[dict[str, Any]],
    requirements: QuestionRequirements,
    *,
    can_correct: Callable[[], bool] = lambda: True,
) -> AnswerRelease:
    initial = verifier.verify(question, answer, chunks)
    if all(claim.status == ClaimStatus.SUPPORTED for claim in initial.claims):
        text, result = _release_supported(initial, answer, requirements, dropped=False)
        return AnswerRelease(text, result, initial)

    statements: list[str] = []
    dropped = False
    for claim in initial.claims:
        if claim.status == ClaimStatus.SUPPORTED and claim.supporting_evidence_ids:
            statements.append(claim.statement)
        elif corrected := _arithmetic_correction(claim):
            statements.append(corrected)
        else:
            dropped = True
    if not statements or not can_correct():
        text, result = _release_supported(initial, answer, requirements, dropped=False)
        return AnswerRelease(text, result, initial)

    revised = "\n".join(statements)
    rechecked = verifier.verify(question, revised, chunks)
    text, result = _release_supported(rechecked, revised, requirements, dropped=dropped)
    return AnswerRelease(text, result, initial, correction_passes=1)
