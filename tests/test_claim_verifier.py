from __future__ import annotations

from src.verification import ClaimLevelVerifier
from src.verification.models import ClaimStatus, CitationStatus, ResponseDisposition


def _financial_chunk(
    *,
    chunk_id: str = "apple-revenue",
    values: tuple[tuple[str, str], ...] = (("2023", "$100 billion"), ("2024", "$110 billion")),
    label: str = "Revenue",
) -> dict[str, object]:
    years = "\n".join(year for year, _ in values)
    amounts = "\n".join(value for _, value in values)
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


def test_cited_numeric_fact_is_supported_and_wrong_value_is_contradicted() -> None:
    verifier = ClaimLevelVerifier()
    evidence = [_financial_chunk()]

    supported = verifier.verify(
        "What was Apple's revenue in FY2024?",
        "Apple revenue was $110 billion in FY2024 [Source 1].",
        evidence,
    )
    contradicted = verifier.verify(
        "What was Apple's revenue in FY2024?",
        "Apple revenue was $109 billion in FY2024 [Source 1].",
        evidence,
    )

    assert supported.disposition == ResponseDisposition.VERIFIED
    assert supported.claims[0].status == ClaimStatus.SUPPORTED
    assert supported.claims[0].citation_status == CitationStatus.VALID
    assert contradicted.disposition == ResponseDisposition.REJECTED
    assert contradicted.claims[0].status == ClaimStatus.CONTRADICTED
    assert contradicted.claims[0].reason_codes == ("claimed_value_conflicts_with_evidence",)


def test_verifier_requires_valid_in_range_source_citations() -> None:
    verifier = ClaimLevelVerifier()
    evidence = [_financial_chunk()]
    answer = "Apple revenue was $110 billion in FY2024"

    missing = verifier.verify("Apple revenue FY2024", answer, evidence)
    malformed = verifier.verify("Apple revenue FY2024", answer + " 【 1 † L3-L5】", evidence)
    out_of_range = verifier.verify("Apple revenue FY2024", answer + " [Source 2]", evidence)

    assert missing.disposition == ResponseDisposition.ABSTAIN
    assert missing.claims[0].citation_status == CitationStatus.MISSING
    assert malformed.claims[0].citation_status == CitationStatus.MALFORMED
    assert out_of_range.claims[0].citation_status == CitationStatus.OUT_OF_RANGE
    assert out_of_range.invalid_citation_count == 1


def test_value_must_match_the_metric_and_period_inside_the_citation() -> None:
    verifier = ClaimLevelVerifier()
    wrong_metric = verifier.verify(
        "What was Apple's revenue in FY2024?",
        "Apple revenue was $110 billion in FY2024 [Source 1].",
        [_financial_chunk(label="Net income")],
    )
    wrong_period = verifier.verify(
        "What was Apple's revenue in FY2024?",
        "Apple revenue was $100 billion in FY2024 [Source 1].",
        [_financial_chunk(values=(("2023", "$100 billion"),), chunk_id="apple-2023")],
    )

    assert wrong_metric.disposition == ResponseDisposition.REJECTED
    assert wrong_metric.claims[0].status == ClaimStatus.UNSUPPORTED
    assert wrong_period.claims[0].status == ClaimStatus.UNSUPPORTED


def test_uncited_matching_chunk_cannot_support_a_claim() -> None:
    verifier = ClaimLevelVerifier()
    result = verifier.verify(
        "What was Apple's revenue in FY2024?",
        "Apple revenue was $110 billion in FY2024 [Source 1].",
        [
            _financial_chunk(chunk_id="wrong-source", label="Net income"),
            _financial_chunk(chunk_id="uncited-correct-source"),
        ],
    )

    assert result.claims[0].status == ClaimStatus.UNSUPPORTED
    assert result.claims[0].evidence_ids == ("wrong-source",)


def test_final_response_is_rejected_if_any_claim_is_contradicted() -> None:
    result = ClaimLevelVerifier().verify(
        "What was Apple's revenue in FY2024?",
        "Apple revenue was $110 billion in FY2024 [Source 1]. "
        "Apple revenue was $115 billion in FY2024 [Source 1].",
        [_financial_chunk()],
    )

    assert len(result.claims) == 2
    assert result.supported_claim_count == 1
    assert result.contradicted_claim_count == 1
    assert result.disposition == ResponseDisposition.REJECTED


def test_growth_percentage_is_recomputed_from_cited_period_values() -> None:
    verifier = ClaimLevelVerifier()
    evidence = [_financial_chunk()]
    supported = verifier.verify(
        "Did Apple's revenue grow from FY2023 to FY2024?",
        "Apple revenue grew 10% from FY2023 to FY2024 [Source 1].",
        evidence,
    )
    contradicted = verifier.verify(
        "Did Apple's revenue grow from FY2023 to FY2024?",
        "Apple revenue grew 15% from FY2023 to FY2024 [Source 1].",
        evidence,
    )

    assert supported.claims[0].status == ClaimStatus.SUPPORTED
    assert supported.claims[0].calculation is not None
    assert supported.claims[0].calculation.expected_value == 10
    assert contradicted.claims[0].status == ClaimStatus.CONTRADICTED
    assert contradicted.claims[0].reason_codes == ("arithmetic_mismatch",)


def test_reported_period_difference_is_recomputed_from_cited_values() -> None:
    verifier = ClaimLevelVerifier()
    evidence = [_financial_chunk()]
    supported = verifier.verify(
        "How much did Apple's revenue increase from FY2023 to FY2024?",
        "Apple revenue increased by $10 billion from FY2023 to FY2024 [Source 1].",
        evidence,
    )
    contradicted = verifier.verify(
        "How much did Apple's revenue increase from FY2023 to FY2024?",
        "Apple revenue increased by $12 billion from FY2023 to FY2024 [Source 1].",
        evidence,
    )

    assert supported.claims[0].status == ClaimStatus.SUPPORTED
    assert supported.claims[0].calculation is not None
    assert supported.claims[0].calculation.operation.value == "difference"
    assert contradicted.claims[0].status == ClaimStatus.CONTRADICTED


def test_citation_after_terminal_punctuation_stays_with_its_claim() -> None:
    result = ClaimLevelVerifier().verify(
        "What was Apple's revenue in FY2024?",
        "Apple revenue was $110 billion in FY2024. [Source 1]",
        [_financial_chunk()],
    )

    assert result.disposition == ResponseDisposition.VERIFIED
    assert len(result.claims) == 1


def test_qualitative_claims_use_only_cited_topical_evidence() -> None:
    verifier = ClaimLevelVerifier()
    evidence = [{
        "chunk_id": "amcor-profile",
        "company": "Amcor plc",
        "ticker": "AMCR",
        "doc_name": "AMCR_annual_report.pdf",
        "page_number": 1,
        "source_url": "https://example.com/amcor.pdf",
        "text": "Amcor plc operates in the packaging industry and serves food, beverage, and healthcare markets.",
    }]
    supported = verifier.verify(
        "What industry does Amcor operate in?",
        "Amcor operates in the packaging industry [Source 1].",
        evidence,
    )
    partial = verifier.verify(
        "What industry does Amcor operate in?",
        "Amcor operates in the packaging and aerospace industries [Source 1].",
        evidence,
    )

    assert supported.claims[0].status == ClaimStatus.SUPPORTED
    assert partial.claims[0].status == ClaimStatus.PARTIALLY_SUPPORTED
    assert partial.disposition == ResponseDisposition.PARTIAL


def test_conflicting_sources_and_fallback_answers_fail_closed() -> None:
    verifier = ClaimLevelVerifier()
    conflict = verifier.verify(
        "What was Apple's revenue in FY2024?",
        "Apple revenue was $110 billion in FY2024 [Source 1] [Source 2].",
        [
            _financial_chunk(chunk_id="apple-a"),
            _financial_chunk(chunk_id="apple-b", values=(("2024", "$109 billion"),)),
        ],
    )
    fallback = verifier.verify(
        "What was Apple's revenue in FY2024?",
        "I could not find sufficient information to answer.",
        [_financial_chunk()],
    )

    assert conflict.claims[0].status == ClaimStatus.UNVERIFIABLE
    assert conflict.claims[0].reason_codes == ("cited_sources_conflict",)
    assert fallback.disposition == ResponseDisposition.ABSTAIN
    assert fallback.claims == ()
