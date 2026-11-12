from __future__ import annotations

from src.decision.company_catalog import CompanyCatalog
from src.decision.models import CoverageStatus, DecisionAction, DecisionBudget, EvidenceSupport, SetSufficiency
from src.decision.policy import EvidenceDecisionLayer
from src.decision.requirement_extractor import EvidenceRequirementExtractor


COMPARISON = "Compare Apple and Microsoft revenue growth between 2022 and 2024"


def _table_chunk(
    *,
    chunk_id: str,
    ticker: str,
    company: str,
    year_values: tuple[tuple[str, str], ...] = (("2024", "$391 billion"), ("2022", "$394 billion")),
    label: str = "Total revenue",
    currency: str = "$",
    source_url: str | None = "https://example.com/report.pdf",
    text_prefix: str = "",
) -> dict:
    years = "\n".join(year for year, _ in year_values)
    values = "\n".join(value.replace("$", currency).replace("€", currency) for _, value in year_values)
    return {
        "chunk_id": chunk_id,
        "ticker": ticker,
        "company": company,
        "doc_name": f"{ticker}_annual_report.pdf",
        "document_id": f"{ticker}_annual_report.pdf",
        "page_number": 4,
        "source_url": source_url,
        "text": f"{text_prefix}{years}\n{label}\n{values}",
    }


def _complete_comparison() -> list[dict]:
    return [
        _table_chunk(chunk_id="aapl-p4", ticker="AAPL", company="Apple Inc."),
        _table_chunk(
            chunk_id="msft-p4",
            ticker="MSFT",
            company="Microsoft Corporation",
            year_values=(("2024", "$245 billion"), ("2022", "$198 billion")),
        ),
    ]


def test_partial_filing_text_cannot_create_a_conflict_or_fill_a_slot() -> None:
    layer = EvidenceDecisionLayer()
    question = "What was Apple's FY2024 revenue?"
    base = _table_chunk(chunk_id="total", ticker="AAPL", company="Apple Inc.")
    distractor = {**base, "chunk_id": "component", "filing_page_checked": True,
                  "text": "Services revenue increased USD 7 billion in FY2024."}
    unsupported = layer.assess(question, [distractor])
    assert unsupported.set_sufficiency == SetSufficiency.INCOMPLETE
    assert unsupported.findings[0].support == EvidenceSupport.PARTIAL_SUPPORT
    assert layer.assess(question, [base, distractor]).set_sufficiency == SetSufficiency.COMPLETE


def test_explicit_filing_assertions_preserve_genuine_contradictions() -> None:
    layer = EvidenceDecisionLayer()
    question = "What was Apple's FY2024 revenue?"
    base = {**_table_chunk(chunk_id="one", ticker="AAPL", company="Apple Inc."), "filing_page_checked": True,
            "text": "Apple's consolidated revenue for FY2024 was USD 391 billion."}
    conflict = {**base, "chunk_id": "two", "text": "In FY2024, Apple revenue was USD 400 billion."}
    assert layer.assess(question, [base]).set_sufficiency == SetSufficiency.COMPLETE
    decision = layer.decide(question, [base, conflict], budget=DecisionBudget(remaining_retrieval_attempts=0))
    assert decision.action == DecisionAction.ABSTAIN
    assert decision.coverage.set_sufficiency == SetSufficiency.CONTRADICTORY
    assert decision.coverage.findings[0].support == EvidenceSupport.CONTRADICTORY


def test_conflicting_source_issuer_identifiers_do_not_support_a_value() -> None:
    chunk = _table_chunk(chunk_id="mislabeled", ticker="AAPL", company="Microsoft")
    coverage = EvidenceDecisionLayer().assess("What was Apple's FY2024 revenue?", [chunk])
    assert coverage.set_sufficiency == SetSufficiency.CONTRADICTORY
    assert coverage.findings[0].missing_reason == "source_metadata_conflict"
    assert not coverage.findings[0].facts


def test_requirement_extraction_builds_entity_metric_period_slots() -> None:
    requirements = EvidenceRequirementExtractor().extract(COMPARISON)

    assert requirements.supported is True
    assert requirements.companies == ("AAPL", "MSFT")
    assert [metric.metric_id for metric in requirements.metrics] == ["revenue"]
    assert requirements.periods == ("FY2022", "FY2024")
    assert [item.operation for item in requirements.operations] == ["growth", "compare"]
    assert {
        (item.entity_id, item.period) for item in requirements.evidence
    } == {
        ("AAPL", "FY2022"),
        ("AAPL", "FY2024"),
        ("MSFT", "FY2022"),
        ("MSFT", "FY2024"),
    }


def test_company_catalog_merges_canonical_names_with_source_aliases() -> None:
    catalog = CompanyCatalog.from_document_rows(
        [{"company": "Apple Inc.", "doc_name": "AAPL_2024_annualreport"}]
    )

    assert [match.entity_id for match in catalog.identify("Compare Apple revenue") ] == ["AAPL"]
    assert catalog.metadata_entity_id("Apple Inc.") == "AAPL"
    with_case_variants = CompanyCatalog({"BA": ("boeing", "Boeing")})
    assert with_case_variants.identify("Boeing revenue")[0].canonical_name == "Boeing"


def test_complete_evidence_returns_answer_without_using_scores() -> None:
    decision = EvidenceDecisionLayer().decide(COMPARISON, _complete_comparison())

    assert decision.action == DecisionAction.ANSWER
    assert decision.reason_code == "requirements_satisfied"
    assert decision.coverage.sufficient is True
    assert len(decision.coverage.findings) == 4
    assert all(finding.status == CoverageStatus.FOUND for finding in decision.coverage.findings)


def test_missing_company_period_slot_requests_more_evidence() -> None:
    chunks = _complete_comparison()
    chunks[1] = _table_chunk(
        chunk_id="msft-p4-partial",
        ticker="MSFT",
        company="Microsoft Corporation",
        year_values=(("2024", "$245 billion"),),
    )

    decision = EvidenceDecisionLayer().decide(COMPARISON, chunks)

    assert decision.action == DecisionAction.RETRIEVE_MORE
    assert decision.reason_code == "missing_evidence"
    assert decision.gap_requirement_ids == ("MSFT:revenue:FY2022",)
    missing = next(
        finding for finding in decision.coverage.findings
        if finding.requirement_id == "MSFT:revenue:FY2022"
    )
    assert missing.missing_reason == "period_mismatch"


def test_missing_evidence_after_budget_is_abstention() -> None:
    chunks = _complete_comparison()
    chunks[1] = _table_chunk(
        chunk_id="msft-p4-partial",
        ticker="MSFT",
        company="Microsoft Corporation",
        year_values=(("2024", "$245 billion"),),
    )

    decision = EvidenceDecisionLayer().decide(
        COMPARISON,
        chunks,
        budget=DecisionBudget(remaining_retrieval_attempts=0),
    )

    assert decision.action == DecisionAction.ABSTAIN
    assert decision.reason_code == "incomplete_evidence_after_budget"


def test_wrong_entity_metric_and_period_are_distinct_gaps() -> None:
    extractor = EvidenceRequirementExtractor()
    analyzer = EvidenceDecisionLayer().analyzer
    requirements = extractor.extract("What was Apple's revenue in FY2022?")

    wrong_entity = _table_chunk(
        chunk_id="wrong-company",
        ticker="MSFT",
        company="Microsoft Corporation",
    )
    wrong_metric = _table_chunk(
        chunk_id="wrong-metric",
        ticker="AAPL",
        company="Apple Inc.",
        label="Net income",
    )
    wrong_period = _table_chunk(
        chunk_id="wrong-period",
        ticker="AAPL",
        company="Apple Inc.",
        year_values=(("2024", "$391 billion"), ("2021", "$365 billion")),
    )

    assert analyzer.analyze(requirements, [wrong_entity]).findings[0].missing_reason == "entity_mismatch"
    assert analyzer.analyze(requirements, [wrong_metric]).findings[0].missing_reason == "metric_mismatch"
    assert analyzer.analyze(requirements, [wrong_period]).findings[0].missing_reason == "period_mismatch"


def test_missing_numeric_value_is_not_treated_as_covered() -> None:
    chunk = {
        "chunk_id": "no-number",
        "ticker": "AAPL",
        "company": "Apple Inc.",
        "doc_name": "AAPL_annual_report.pdf",
        "page_number": 4,
        "source_url": "https://example.com/report.pdf",
        "text": "Apple revenue grew during FY2022.",
    }

    decision = EvidenceDecisionLayer().decide("What was Apple's revenue in FY2022?", [chunk])

    assert decision.action == DecisionAction.RETRIEVE_MORE
    assert decision.coverage.findings[0].missing_reason == "numerical_value_missing"


def test_missing_source_provenance_is_not_answerable() -> None:
    chunk = _table_chunk(
        chunk_id="unattributed",
        ticker="AAPL",
        company="Apple Inc.",
        source_url=None,
    )
    chunk["page_number"] = None

    decision = EvidenceDecisionLayer().decide("What was Apple's revenue in FY2022?", [chunk])

    assert decision.action == DecisionAction.RETRIEVE_MORE
    assert decision.coverage.findings[0].missing_reason == "source_provenance_missing"


def test_conflicting_values_trigger_retrieval_then_abstention() -> None:
    chunks = [
        _table_chunk(
            chunk_id="value-one",
            ticker="AAPL",
            company="Apple Inc.",
            year_values=(("2022", "$394 billion"),),
        ),
        _table_chunk(
            chunk_id="value-two",
            ticker="AAPL",
            company="Apple Inc.",
            year_values=(("2022", "$390 billion"),),
        ),
    ]
    question = "What was Apple's revenue in FY2022?"

    layer = EvidenceDecisionLayer()
    retrieve = layer.decide(question, chunks)
    abstain = layer.decide(
        question,
        chunks,
        budget=DecisionBudget(remaining_retrieval_attempts=0),
    )

    assert retrieve.action == DecisionAction.RETRIEVE_MORE
    assert retrieve.coverage.findings[0].status == CoverageStatus.CONFLICTED
    assert retrieve.coverage.findings[0].missing_reason == "contradictory_values_or_units"
    assert abstain.action == DecisionAction.ABSTAIN
    assert abstain.reason_code == "conflicting_evidence_after_budget"


def test_source_metadata_conflict_blocks_answer() -> None:
    chunk = _table_chunk(
        chunk_id="source-conflict",
        ticker="AAPL",
        company="Apple Inc.",
        year_values=(("2022", "$394 billion"),),
    )
    chunk["metadata_conflicts"] = [{"field": "company", "observed": "Other issuer"}]

    decision = EvidenceDecisionLayer().decide("What was Apple's revenue in FY2022?", [chunk])

    assert decision.action == DecisionAction.RETRIEVE_MORE
    assert decision.reason_code == "conflicting_evidence"
    assert decision.coverage.findings[0].missing_reason == "source_metadata_conflict"


def test_equivalent_numeric_formatting_is_not_a_value_conflict() -> None:
    chunks = [
        _table_chunk(
            chunk_id="value-one",
            ticker="AAPL",
            company="Apple Inc.",
            year_values=(("2022", "$394 billion"),),
        ),
        _table_chunk(
            chunk_id="value-two",
            ticker="AAPL",
            company="Apple Inc.",
            year_values=(("2022", "$394.0 billion"),),
        ),
    ]

    decision = EvidenceDecisionLayer().decide("What was Apple's revenue in FY2022?", chunks)

    assert decision.action == DecisionAction.ANSWER
    assert decision.coverage.findings[0].status == CoverageStatus.FOUND


def test_sec_structured_row_match_uses_its_aligned_table_header() -> None:
    chunk = {
        "chunk_id": "aapl-financial-table",
        "ticker": "AAPL",
        "company": "Apple Inc.",
        "doc_name": "AAPL_10-K.html",
        "section": "financial_table",
        "page_number": 10,
        "source_url": "https://example.com/aapl-10k",
        "text": (
            "### Consolidated Statements of Operations\n"
            "| Metric | FY2022 | FY2021 |\n"
            "| --- | --- | --- |\n"
            "| Revenue excluding divested business | $999 billion | $900 billion |\n"
            "| --- | --- | --- |\n"
            "| Total revenue | $394 billion | $365 billion |"
        ),
    }

    decision = EvidenceDecisionLayer().decide("What was Apple's total revenue in FY2022?", [chunk])

    assert decision.action == DecisionAction.ANSWER
    finding = decision.coverage.findings[0]
    assert finding.status == CoverageStatus.FOUND
    assert [(fact.period, fact.numeric_value) for fact in finding.facts] == [("FY2022", "394")]


def test_unit_mismatch_blocks_comparative_answer() -> None:
    chunks = _complete_comparison()
    chunks[1] = _table_chunk(
        chunk_id="msft-eur",
        ticker="MSFT",
        company="Microsoft Corporation",
        currency="€",
        year_values=(("2024", "€245 billion"), ("2022", "€198 billion")),
    )

    decision = EvidenceDecisionLayer().decide(COMPARISON, chunks)

    assert decision.action == DecisionAction.RETRIEVE_MORE
    assert "growth:unit_mismatch" in decision.coverage.operation_gaps
    assert "compare:unit_mismatch" in decision.coverage.operation_gaps


def test_relative_period_scope_and_unknown_metric_abstain_safely() -> None:
    layer = EvidenceDecisionLayer()

    relative = layer.decide("What was Apple's revenue in the last 3 years?", _complete_comparison())
    unknown = layer.decide("Compare Apple and Microsoft performance", _complete_comparison())

    assert relative.action == DecisionAction.ABSTAIN
    assert relative.reason_code == "relative_period_not_supported"
    assert unknown.action == DecisionAction.ABSTAIN
    assert unknown.reason_code == "metric_not_recognized"


def test_explicit_year_does_not_hide_unsupported_relative_period_scope() -> None:
    decision = EvidenceDecisionLayer().decide(
        "What was Apple's revenue in the last 3 years through FY2024?",
        _complete_comparison(),
    )

    assert decision.action == DecisionAction.ABSTAIN
    assert decision.reason_code == "relative_period_not_supported"


def test_quarter_and_year_over_year_periods_are_explicit() -> None:
    extractor = EvidenceRequirementExtractor()
    quarter = extractor.extract("What was Apple's revenue in Q2 FY2023?")
    yoy = extractor.extract("What was Apple's year-over-year revenue growth in FY2024?")

    assert quarter.periods == ("Q2 FY2023",)
    assert yoy.periods == ("FY2023", "FY2024")
    assert [item.period for item in yoy.evidence] == ["FY2023", "FY2024"]


def test_qualitative_evidence_uses_corpus_company_aliases() -> None:
    extractor = EvidenceRequirementExtractor.from_document_rows(
        [{"company": "Amcor plc", "doc_name": "AMCOR_2023_annualreport"}]
    )
    chunk = {
        "chunk_id": "amcor-industry",
        "company": "Amcor plc",
        "doc_name": "AMCOR_2023_annualreport",
        "page_number": 1,
        "source_url": "https://example.com/amcor.pdf",
        "text": "Amcor plc operates in the packaging industry and serves food, beverage and healthcare markets.",
    }

    decision = EvidenceDecisionLayer(extractor=extractor).decide(
        "What industry does Amcor operate in?",
        [chunk],
    )

    assert decision.action == DecisionAction.ANSWER
    assert decision.coverage.findings[0].status == CoverageStatus.FOUND
