from __future__ import annotations

from datetime import date

import pytest

from src.decision.models import EvidenceFact
from src.decision.policy import EvidenceDecisionLayer
from src.evaluation.advanced_verification_evaluation import advanced_verification_cases
from src.evaluation.verification_evaluation import _financial_chunk, _industry_chunk
from src.ingestion.period_identity import PeriodIdentity, PeriodKind, requested_reporting_interval
from src.verification.atomic_claim_verifier import AtomicClaimVerifier
from src.verification.models import ClaimStatus, ResponseDisposition
from src.verification.response_policy import INSUFFICIENT_EVIDENCE_ANSWER, verify_and_release


def test_explicit_interval_checks_the_claim_and_its_accession():
    question = "What was Apple's revenue from 2023-10-01 to 2024-09-28 in 10-K 0000320193-24-000123?"
    layer = EvidenceDecisionLayer()
    requirements = layer.extractor.extract(question)
    interval = requested_reporting_interval(question)
    assert interval and requirements.reporting_interval == interval and requirements.periods == ()
    assert len(requirements.evidence) == 1
    chunk = _financial_chunk(chunk_id="apple")
    chunk["accession"] = interval.accession
    chunk["approved_facts"] = (EvidenceFact(
        evidence_id="apple", entity_id="AAPL", metric_id="revenue", period="FY2024",
        period_identity=PeriodIdentity.from_label("FY2024", kind=PeriodKind.DURATION, start=interval.start, end=interval.end),
        value="USD 110 billion", numeric_value="110", currency="USD", scale="billion", value_kind="amount",
        document_id=chunk["doc_name"], page_number=chunk["page_number"], source_url=chunk.get("source_url"),
    ),)
    verifier = AtomicClaimVerifier()
    answer = "Apple reported revenue of USD 110 billion for FY2024. [Source 1]"
    assert verifier.verify(question, answer, [chunk]).disposition == ResponseDisposition.VERIFIED
    wrong_sources = [
        {**chunk, "accession": "0000320193-23-000106"},
        {**chunk, "accession_number": "0000320193-23-000106"},
        {**chunk, "approved_facts": (chunk["approved_facts"][0].model_copy(update={"period_identity": None}),)},
    ]
    for wrong in wrong_sources:
        assert verifier.verify(question, answer, [wrong]).disposition == ResponseDisposition.REJECTED
    assert verifier.verify(question, answer.replace("FY2024", "FY2023"), [chunk]).disposition == ResponseDisposition.REJECTED


@pytest.mark.parametrize("dates", ["2024-02-30 to 2024-09-28", "2024-09-28 to 2023-10-01",
                                    "2023-10-01 to September", "2023-10-01 to 2024-09-28 and FY2023"])
def test_ambiguous_or_invalid_intervals_do_not_fall_back_to_fiscal_years(dates):
    req = EvidenceDecisionLayer().extractor.extract(f"What was Apple's revenue from {dates}?")
    assert not req.supported and not req.evidence


@pytest.mark.parametrize("scope", [
    "2023-09-30 and 2023-09-30 in 10-K 0000320193-24-000123",
    "2023-02-30 and 2024-09-28 in 10-K 0000320193-24-000123",
    "2023-09-30 and 2024-09-28 in its annual filing",
    "2023-09-30 and 2024-09-28 in 10-K 0000320193-24-000123 or 0000320193-24-000124",
])
def test_invalid_fiscal_year_pairs_do_not_fall_back_to_bare_years(scope):
    req = EvidenceDecisionLayer().extractor.extract(f"What was Apple's revenue for the fiscal years ended {scope}?")
    assert not req.supported and not req.evidence


def test_as_of_claim_checks_the_rendered_date_against_the_cited_balance():
    accession = "0000320193-24-000123"
    question = f"What were Apple's total assets as of 2024-09-28 in 10-K {accession}?"
    chunk = _financial_chunk(chunk_id="apple-assets")
    chunk.update(accession=accession, source_type="XBRL_FACT", financial_concept="us-gaap:Assets", filing_type="10-K")
    chunk["normalized_facts"] = (EvidenceFact(
        evidence_id=chunk["chunk_id"], entity_id="AAPL", metric_id="total_assets", period="FY2024",
        period_identity=PeriodIdentity.from_label("FY2024", kind=PeriodKind.INSTANT, end=date(2024, 9, 28)),
        value="USD 364 billion", numeric_value="364", currency="USD", scale="billion", value_kind="amount",
        document_id=chunk["doc_name"], page_number=chunk["page_number"], source_url=chunk.get("source_url"),
    ),)
    answer = "AAPL reported total assets of USD 364 billion as of 2024-09-28 (FY2024). [Source 1]"
    verifier = AtomicClaimVerifier()
    assert verifier.verify(question, answer, [chunk]).disposition == ResponseDisposition.VERIFIED
    assert verifier.verify(question, answer.replace("2024-09-28", "2024-09-29"), [chunk]).disposition == ResponseDisposition.REJECTED
    assert verifier.verify(question, answer, [{**chunk, "accession": "0000320193-24-000124"}]).disposition == ResponseDisposition.REJECTED


def test_consolidated_income_tax_cannot_support_a_component_or_use_a_different_tag():
    question = "What was Apple's income tax expense in FY2024?"
    chunk = _financial_chunk(chunk_id="apple-tax")
    chunk.update(source_type="XBRL_FACT", financial_concept="us-gaap:IncomeTaxExpenseBenefit", normalized_facts=(
        EvidenceFact(
            evidence_id="apple-tax", entity_id="AAPL", metric_id="income_tax_expense", period="FY2024",
            period_identity=PeriodIdentity.from_label("FY2024", kind=PeriodKind.DURATION,
                                                      start=date(2023, 10, 1), end=date(2024, 9, 28)),
            value="USD 4 billion", numeric_value="4", currency="USD", scale="billion", value_kind="amount",
            document_id=chunk["doc_name"], page_number=chunk["page_number"], source_url=chunk.get("source_url"),
        ),
    ))
    answer = "Apple reported income tax expense of USD 4 billion for FY2024. [Source 1]"
    verifier = AtomicClaimVerifier()
    assert verifier.verify(question, answer, [chunk]).disposition == ResponseDisposition.VERIFIED

    for negative_amount in ("-$4 billion", "−$4 billion", "($4 billion)"):
        wrong_sign = answer.replace("USD 4 billion", negative_amount)
        assert verifier.verify(question, wrong_sign, [chunk]).disposition == ResponseDisposition.REJECTED

    for qualifier in ("current", "deferred"):
        qualified_answer = answer.replace("income tax expense", f"{qualifier} income tax expense")
        assert verifier.verify(question, qualified_answer, [chunk]).disposition != ResponseDisposition.VERIFIED
        qualified_question = question.replace("income tax expense", f"{qualifier} income tax expense")
        assert not EvidenceDecisionLayer().assess(qualified_question, [chunk]).sufficient

    other_tag = {**chunk, "financial_concept": "us-gaap:CurrentIncomeTaxExpenseBenefit"}
    assert verifier.verify(question, answer, [other_tag]).disposition != ResponseDisposition.VERIFIED


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


def test_comparison_uncertainty_and_speculation_are_distinct_claim_types():
    verifier = AtomicClaimVerifier()
    evidence = [_financial_chunk(chunk_id="endpoints")]
    question = "Did Apple's revenue grow from FY2023 to FY2024?"
    result = verifier.verify(question, "Apple revenue grew from FY2023 to FY2024 [Source 1].", evidence)
    assert result.claims[0].claim_type == "comparison" and result.claims[0].status == ClaimStatus.SUPPORTED
    assert len(result.claims[0].requirement_ids) == 2
    for text, kind in (("Apple may report revenue of USD 110 billion in FY2024.", "speculation"),
                       ("There is not enough evidence for Apple's revenue in FY2024.", "uncertainty")):
        result = verifier.verify(question, f"{text.rstrip('.')} [Source 1].", evidence)
        assert result.claims[0].claim_type == kind
        assert result.claims[0].status != ClaimStatus.SUPPORTED


def test_abbreviated_extra_amount_is_still_checked_in_numeric_claims():
    evidence = [_financial_chunk(chunk_id="revenue")]
    result = AtomicClaimVerifier().verify(
        "What was Apple's FY2024 revenue?",
        "Apple FY2024 revenue was USD 110 billion and 3M in additional expense [Source 1].", evidence,
    )
    assert result.disposition != ResponseDisposition.VERIFIED


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
