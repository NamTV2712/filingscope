from __future__ import annotations

import pytest

from src.decision.policy import EvidenceDecisionLayer
from src.evaluation.advanced_verification_evaluation import advanced_verification_cases
from src.evaluation.verification_evaluation import _financial_chunk, _industry_chunk
from src.verification.atomic_claim_verifier import AtomicClaimVerifier
from src.verification.models import ClaimStatus, ResponseDisposition
from src.verification.response_policy import INSUFFICIENT_EVIDENCE_ANSWER, verify_and_release


@pytest.mark.parametrize("case", advanced_verification_cases(), ids=lambda case: case.case_id)
def test_frozen_atomic_claims_and_release_policy(case):
    requirements = EvidenceDecisionLayer().extractor.extract(case.question)
    release = verify_and_release(AtomicClaimVerifier(), case.question, case.answer, list(case.evidence), requirements)
    assert tuple(claim.status for claim in release.initial.claims) == case.claim_statuses
    assert release.result.disposition == case.release
    assert release.correction_passes == case.corrections
    if case.release in (ResponseDisposition.REJECTED, ResponseDisposition.ABSTAIN):
        assert release.answer == INSUFFICIENT_EVIDENCE_ANSWER
    else:
        assert all(claim.status == ClaimStatus.SUPPORTED and claim.supporting_evidence_ids
                   for claim in release.result.claims)
    if case.case_id in {"growth_correctable", "growth_direction_correctable"}:
        assert "grew 10%" in release.answer
    if case.case_id == "compound_mixed_support":
        assert "$110 billion" in release.answer and "$29 billion" not in release.answer


def test_claim_support_excludes_other_cited_sources():
    case = next(case for case in advanced_verification_cases() if case.case_id == "compound_shared_sources")
    result = AtomicClaimVerifier().verify(case.question, case.answer, case.evidence)
    assert [claim.evidence_ids for claim in result.claims] == [("apple-revenue", "apple-income")] * 2
    assert [claim.supporting_evidence_ids for claim in result.claims] == [("apple-revenue",), ("apple-income",)]
    assert all(len(claim.requirement_ids) == 1 for claim in result.claims)


def test_numeric_fact_cannot_cover_two_companies_with_one_value():
    apple = _financial_chunk(chunk_id="apple")
    microsoft = {**apple, "chunk_id": "microsoft", "ticker": "MSFT", "company": "Microsoft"}
    question = "Compare Apple and Microsoft revenue for FY2024."
    answer = "Apple and Microsoft reported revenue of $110 billion in FY2024 [Source 1] [Source 2]."
    result = AtomicClaimVerifier().verify(question, answer, [apple, microsoft])
    assert result.disposition == ResponseDisposition.ABSTAIN
    assert not result.claims[0].requirement_ids


def test_topical_relation_does_not_release_an_unchecked_coordinated_predicate():
    question = "What industry does Amcor operate in?"
    answer = "Amcor operates in the packaging industry and serves aerospace companies [Source 1]."
    requirements = EvidenceDecisionLayer().extractor.extract(question)
    release = verify_and_release(AtomicClaimVerifier(), question, answer, [_industry_chunk()], requirements)
    assert release.result.disposition == ResponseDisposition.PARTIAL
    assert release.correction_passes == 1
    assert "packaging industry" in release.answer and "aerospace" not in release.answer


def test_exhausted_budget_leaves_rejected_draft_unreleased():
    case = next(case for case in advanced_verification_cases() if case.case_id == "growth_correctable")
    requirements = EvidenceDecisionLayer().extractor.extract(case.question)
    release = verify_and_release(
        AtomicClaimVerifier(), case.question, case.answer, list(case.evidence), requirements, can_correct=lambda: False,
    )
    assert release.correction_passes == 0
    assert release.result.disposition == ResponseDisposition.REJECTED
    assert release.answer == INSUFFICIENT_EVIDENCE_ANSWER


@pytest.mark.parametrize("wording", (
    "Apple did not report revenue of $110 billion in FY2024.",
    "Apple expects revenue of $110 billion in FY2024.",
))
def test_disclaimed_or_forecast_value_does_not_support_actual_revenue(wording):
    source = {**_financial_chunk(chunk_id="projected"), "text": wording}
    result = AtomicClaimVerifier().verify(
        "What was Apple's revenue in FY2024?", "Apple revenue was $110 billion in FY2024 [Source 1].", [source],
    )
    assert result.disposition == ResponseDisposition.REJECTED
    assert result.claims[0].status == ClaimStatus.UNSUPPORTED


def test_conflicting_cited_endpoints_cannot_verify_growth_direction():
    first = _financial_chunk(chunk_id="first")
    conflicting = _financial_chunk(chunk_id="conflicting", values=(("2024", "$90 billion"),))
    question = "Did Apple's revenue grow from FY2023 to FY2024?"
    result = AtomicClaimVerifier().verify(
        question, "Apple revenue grew from FY2023 to FY2024 [Source 1] [Source 2].", [first, conflicting],
    )
    assert result.disposition == ResponseDisposition.ABSTAIN
    assert result.claims[0].status == ClaimStatus.UNVERIFIABLE


def test_original_value_cannot_verify_a_restated_claim():
    evidence = {**_financial_chunk(chunk_id="original"), "revision_kind": "ORIGINAL"}
    result = AtomicClaimVerifier().verify(
        "What was Apple's restated FY2024 revenue?",
        "Apple FY2024 revenue was USD 110 billion [Source 1].", [evidence],
    )
    assert result.disposition == ResponseDisposition.REJECTED
    assert result.claims[0].reason_codes == ("cited_source_revision_does_not_match_claim",)


def test_release_checks_requested_arithmetic_for_each_company():
    apple = _financial_chunk(chunk_id="apple")
    microsoft = {**apple, "chunk_id": "microsoft", "ticker": "MSFT", "company": "Microsoft",
                 "doc_name": "MSFT.pdf", "document_id": "MSFT.pdf", "source_url": "https://example.com/msft.pdf"}
    question = "Compare Apple and Microsoft revenue growth between FY2023 and FY2024."
    answer = (
        "Apple revenue grew 10% from FY2023 to FY2024 [Source 1]. "
        "Microsoft revenue was $100 billion in FY2023 [Source 2]. "
        "Microsoft revenue was $110 billion in FY2024 [Source 2]."
    )
    requirements = EvidenceDecisionLayer().extractor.extract(question)
    release = verify_and_release(AtomicClaimVerifier(), question, answer, [apple, microsoft], requirements)
    assert release.initial.disposition == ResponseDisposition.VERIFIED
    assert release.result.disposition == ResponseDisposition.PARTIAL
    assert release.correction_passes == 0


def test_fallback_phrase_does_not_erase_other_draft_claims():
    question = "What were Apple's revenue and net income in FY2024?"
    answer = "Apple revenue was $110 billion in FY2024 [Source 1]. Insufficient evidence for net income."
    requirements = EvidenceDecisionLayer().extractor.extract(question)
    release = verify_and_release(AtomicClaimVerifier(), question, answer, [_financial_chunk(chunk_id="revenue")], requirements)
    assert [claim.status for claim in release.initial.claims] == [ClaimStatus.SUPPORTED, ClaimStatus.UNVERIFIABLE]
    assert release.result.disposition == ResponseDisposition.PARTIAL
