from collections import Counter
from pathlib import Path

import pytest

from configs.financebench import SPLIT_TARGETS
from scripts.download_financebench import validate_financebench_sources
from src.evaluation.financebench_dataset import (
    build_company_splits,
    normalize_document_metadata,
)


def _case(case_id: str, company: str, doc_name: str) -> dict:
    return {
        "financebench_id": case_id,
        "company": company,
        "doc_name": doc_name,
        "question": "Synthetic question",
        "evidence": [{"doc_name": doc_name, "evidence_page_num": 0}],
    }


def test_company_split_is_exact_deterministic_and_leakage_free() -> None:
    cases = [
        _case("a1", "A", "A-report"),
        _case("a2", "A", "A-report"),
        _case("b1", "B", "B-report"),
        _case("b2", "B", "B-report"),
        _case("c1", "C", "C-report"),
        _case("d1", "D", "D-report"),
    ]
    targets = {"development": 3, "validation": 2, "held_out": 1}

    first = build_company_splits(cases, targets=targets, seed="split-test")
    second = build_company_splits(cases, targets=targets, seed="split-test")

    assert first == second
    counts = Counter(first[case["company"]] for case in cases)
    assert counts == Counter(targets)
    companies_by_split = {
        split: {company for company, value in first.items() if value == split}
        for split in targets
    }
    assert not (companies_by_split["development"] & companies_by_split["validation"])
    assert not (companies_by_split["development"] & companies_by_split["held_out"])
    assert not (companies_by_split["validation"] & companies_by_split["held_out"])


def test_metadata_normalization_preserves_conflicting_periods() -> None:
    metadata, conflicts = normalize_document_metadata(
        [
            {"doc_name": "REPORT", "company": "Company A", "doc_period": "2022", "doc_type": "10-K"},
            {"doc_name": "REPORT", "company": "Company A", "doc_period": "2023", "doc_type": "10-K"},
        ]
    )

    assert metadata["REPORT"]["reporting_periods"] == ["2022", "2023"]
    assert metadata["REPORT"]["metadata_conflicts"] == [
        {"field": "doc_period", "values": ["2022", "2023"]}
    ]
    assert conflicts == [
        {
            "doc_name": "REPORT",
            "conflicts": [{"field": "doc_period", "values": ["2022", "2023"]}],
        }
    ]


def test_downloader_validation_checks_schema_and_pdf_coverage() -> None:
    cases = [_case("case-1", "Company A", "REPORT-A"), _case("case-2", "Company B", "REPORT-B")]
    document_rows = [
        {"doc_name": "REPORT-A", "company": "Company A", "doc_period": "2022"},
        {"doc_name": "REPORT-B", "company": "Company B", "doc_period": "2023"},
    ]
    tree = [
        {"path": "pdfs/REPORT-A.pdf"},
        {"path": "pdfs/REPORT-B.pdf"},
    ]

    stats = validate_financebench_sources(
        cases,
        document_rows,
        tree,
        expected_case_count=2,
        expected_document_count=2,
    )

    assert stats["case_count"] == 2
    assert stats["unique_case_document_count"] == 2
    assert stats["evidence_record_count"] == 2
    with pytest.raises(ValueError, match="missing repository PDFs"):
        validate_financebench_sources(
            cases,
            document_rows,
            tree[:1],
            expected_case_count=2,
            expected_document_count=2,
        )


@pytest.mark.skipif(
    not Path("data/financebench/source/financebench_open_source.jsonl").is_file(),
    reason="requires locally acquired, git-ignored FinanceBench sample",
)
def test_pinned_financebench_sample_has_expected_company_splits() -> None:
    from src.evaluation.financebench_dataset import load_financebench_cases

    cases = load_financebench_cases(Path("data/financebench/source/financebench_open_source.jsonl"))
    assert len(cases) == 150
    assert Counter(case.split for case in cases) == Counter(SPLIT_TARGETS)
    split_companies = {
        split: {case.company for case in cases if case.split == split}
        for split in SPLIT_TARGETS
    }
    assert not (split_companies["development"] & split_companies["validation"])
    assert not (split_companies["development"] & split_companies["held_out"])
    assert not (split_companies["validation"] & split_companies["held_out"])
