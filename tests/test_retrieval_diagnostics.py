import pytest

from src.evaluation.retrieval_diagnostics import (
    fuse_ranked_ids,
    metadata_filter_profiles,
    metadata_filters_from_question,
    ranked_ids_from_trace,
    rerank_candidate_ids,
    route_aware_fusion_weights,
)
from src.decision.company_catalog import CompanyCatalog
from src.evaluation.financebench_dataset import FinanceBenchCase
from scripts.run_retrieval_diagnostics import _source_candidate_metrics


def test_ranked_ids_from_trace_uses_rank_and_skips_unranked_candidates() -> None:
    trace = {
        "candidates": [
            {"chunk_id": "later", "bm25_rank": 3},
            {"chunk_id": "first", "bm25_rank": 1},
            {"chunk_id": "unranked", "bm25_rank": None},
            {"chunk_id": "second", "bm25_rank": 2},
        ]
    }

    assert ranked_ids_from_trace(trace, "bm25_rank") == ["first", "second", "later"]


def test_weighted_rrf_changes_source_influence() -> None:
    equal, _ = fuse_ranked_ids(
        bm25_ids=["lexical-first", "shared"],
        dense_ids=["semantic-first", "shared"],
        lexical_ids=[],
        bm25_candidates=2,
        dense_candidates=2,
        lexical_candidates=0,
        fusion_candidates=3,
    )
    dense_weighted, _ = fuse_ranked_ids(
        bm25_ids=["lexical-first", "shared"],
        dense_ids=["semantic-first", "shared"],
        lexical_ids=[],
        bm25_candidates=2,
        dense_candidates=2,
        lexical_candidates=0,
        fusion_candidates=3,
        weights={"dense": 3.0},
    )

    assert equal.index("lexical-first") < equal.index("semantic-first")
    assert dense_weighted.index("semantic-first") < dense_weighted.index("lexical-first")


def test_dense_preserving_pool_retains_dense_prefix_before_filling() -> None:
    selected, _ = fuse_ranked_ids(
        bm25_ids=["b1", "x"],
        dense_ids=["d1", "d2", "d3"],
        lexical_ids=["x", "l1"],
        bm25_candidates=2,
        dense_candidates=3,
        lexical_candidates=2,
        fusion_candidates=3,
        dense_preserving=True,
    )

    assert len(selected) == 3
    assert {"d1", "d2", "d3"}.issubset(selected)


def test_fusion_rejects_invalid_limits_and_weights() -> None:
    with pytest.raises(ValueError, match="candidate limits"):
        fuse_ranked_ids(
            bm25_ids=[], dense_ids=[], lexical_ids=[],
            bm25_candidates=-1, dense_candidates=0, lexical_candidates=0,
            fusion_candidates=1,
        )
    with pytest.raises(ValueError, match="non-negative"):
        fuse_ranked_ids(
            bm25_ids=[], dense_ids=[], lexical_ids=[],
            bm25_candidates=0, dense_candidates=0, lexical_candidates=0,
            fusion_candidates=1, weights={"dense": -1},
        )


def test_rerank_applies_relative_cutoff_and_top_k() -> None:
    assert rerank_candidate_ids(
        ["weak", "strong", "medium"],
        {"weak": 0.2, "strong": 1.0, "medium": 0.8},
        top_k=3,
        relative_cutoff=0.5,
    ) == ["strong", "medium"]


def test_candidate_metrics_count_gold_pages_once_per_document_page() -> None:
    case = FinanceBenchCase(
        case_id="case-1",
        company="Example Co",
        doc_name="EXAMPLE_10K",
        question="What was revenue?",
        gold_pages=(2, 3),
        question_type="simple_lookup",
        split="development",
    )
    chunks = {
        "same-page-a": {"doc_name": "EXAMPLE_10K", "page_number": 2},
        "same-page-b": {"doc_name": "EXAMPLE_10K", "page_number": 2},
        "other-document": {"doc_name": "OTHER_10K", "page_number": 3},
    }

    result = _source_candidate_metrics(
        [case], {"case-1": ["same-page-a", "same-page-b", "other-document"]}, chunks
    )

    assert result["gold_page_recall_micro"] == 0.5
    assert result["gold_page_recall_macro"] == 0.5
    assert result["full_evidence_coverage"] == 0.0


def test_route_aware_weights_use_query_shaper_hints_only() -> None:
    phrase_route, phrase_weights = route_aware_fusion_weights(
        "How did AWS net sales growth change year over year?"
    )
    default_route, default_weights = route_aware_fusion_weights("What was revenue?")

    assert phrase_route == "filing_native_phrase"
    assert phrase_weights == {"bm25": 1.0, "dense": 1.0, "lexical": 2.0}
    assert default_route == "dense_priority"
    assert default_weights == {"bm25": 1.0, "dense": 2.0, "lexical": 0.5}


def test_query_metadata_filters_use_only_explicit_query_values() -> None:
    rows = [
        {"company": "Acme Corporation"},
        {"company": "Beta Incorporated"},
    ]
    catalog = CompanyCatalog.from_document_rows(rows)
    values_by_entity = {
        catalog.metadata_entity_id(row["company"]): {row["company"]}
        for row in rows
    }

    filters = metadata_filters_from_question(
        "Compare Acme Corporation and Beta Incorporated in FY2021 and FY2022 10-K reports.",
        company_catalog=catalog,
        company_values_by_entity=values_by_entity,
        available_periods={"2021", "2022", "2023"},
        available_doc_types={"10k", "10q"},
    )

    assert filters == {
        "company": ("Acme Corporation", "Beta Incorporated"),
        "reporting_periods": ("2021", "2022"),
        "doc_type": ("10k",),
    }
    profiles = metadata_filter_profiles(filters)
    assert profiles["company_period"] == {
        "company": ("Acme Corporation", "Beta Incorporated"),
        "reporting_periods": ("2021", "2022"),
    }
    assert profiles["company_period_form"] == filters


def test_query_metadata_filters_leave_unavailable_values_unfiltered() -> None:
    catalog = CompanyCatalog.from_document_rows([{"company": "Acme Corporation"}])
    entity_id = catalog.metadata_entity_id("Acme Corporation")
    assert entity_id is not None

    filters = metadata_filters_from_question(
        "What happened to Acme Corporation in FY2030?",
        company_catalog=catalog,
        company_values_by_entity={entity_id: {"Acme Corporation"}},
        available_periods={"2021"},
        available_doc_types={"10k"},
    )

    assert filters == {"company": ("Acme Corporation",)}
