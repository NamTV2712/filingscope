from src.research.corpus_map import CorpusMap, SourceAvailability
from src.research.planner import (
    CorpusAwarePlanner,
    PlanningMode,
    QuestionOnlyPlanner,
)


def _map(rows=None):
    return CorpusMap.from_chunks(
        rows
        or [
            {
                "document_id": "ACME_2023_10K",
                "company": "Acme Corp",
                "doc_type": "10k",
                "reporting_periods": ["2023"],
                "section": "document",
            },
            {
                "document_id": "ACME_2021_10K",
                "company": "Acme Corp",
                "doc_type": "10k",
                "reporting_periods": ["2021"],
                "section": "document",
            },
        ],
        index_generation_id="index-abc",
    )


def test_corpus_planner_uses_existing_document_for_available_period():
    plan = CorpusAwarePlanner(_map()).plan("What was Acme revenue in FY2023?")

    assert plan.planning_mode == PlanningMode.CORPUS_AWARE
    assert plan.index_generation_id == "index-abc"
    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.source_availability == SourceAvailability.AVAILABLE
    assert task.availability_reason == "matching_filing_period_available"
    assert task.target_document_ids == ("ACME_2023_10K",)
    assert task.query is not None


def test_form_request_matches_sec_form_spelling_variants():
    corpus_map = _map(
        [
            {
                "document_id": "ACME_2023_10K",
                "company": "Acme Corp",
                "doc_type": "Form 10-K",
                "reporting_periods": ["2023"],
                "section": "document",
            }
        ]
    )
    task = CorpusAwarePlanner(corpus_map).plan(
        "What was Acme revenue in FY2023 from the 10-K?"
    ).tasks[0]

    assert task.source_availability == SourceAvailability.AVAILABLE
    assert task.form_types == ("10k",)
    assert task.target_document_ids == ("ACME_2023_10K",)


def test_missing_exact_period_is_explicit_and_fallback_is_local():
    corpus_map = _map()
    plan = CorpusAwarePlanner(corpus_map).plan("What was Acme revenue in FY2024?")

    task = plan.tasks[0]
    local_ids = {document.document_id for document in corpus_map.documents}
    assert task.source_availability == SourceAvailability.MISSING
    assert task.availability_reason.startswith("exact_filing_period_not_indexed")
    assert task.target_document_ids
    assert set(task.target_document_ids).issubset(local_ids)
    assert task.query is not None


def test_absent_company_is_missing_only_when_company_inventory_is_complete():
    plan = CorpusAwarePlanner(_map()).plan("What was Apple's revenue in FY2023?")

    task = plan.tasks[0]
    assert task.source_availability == SourceAvailability.MISSING
    assert task.availability_reason == "company_absent_from_complete_runtime_inventory"
    assert task.query is None
    assert task.target_document_ids == ()


def test_unindexed_company_field_stays_unknown_and_can_search_without_fake_ids():
    corpus_map = _map(
        [
            {"document_id": "DOC_1", "section": "document"},
            {"document_id": "DOC_2", "section": "document"},
        ]
    )
    plan = CorpusAwarePlanner(corpus_map).plan("What was Apple's revenue in FY2023?")

    task = plan.tasks[0]
    assert task.source_availability == SourceAvailability.UNKNOWN
    assert task.availability_reason == "company_inventory_incomplete"
    assert task.query is not None
    assert task.target_document_ids == ()


def test_conflicted_company_inventory_cannot_claim_absence():
    corpus_map = _map(
        [
            {
                "document_id": "DOC_1",
                "company": "Acme Corp",
                "doc_type": "10k",
                "reporting_periods": ["2023"],
                "section": "document",
            },
            {
                "document_id": "DOC_1",
                "company": "Different Company",
                "doc_type": "10k",
                "reporting_periods": ["2023"],
                "section": "document",
            },
        ]
    )

    task = CorpusAwarePlanner(corpus_map).plan(
        "What was Apple's revenue in FY2023?"
    ).tasks[0]

    assert task.source_availability == SourceAvailability.UNKNOWN
    assert task.query is not None
    assert task.target_document_ids == ()
    assert "company" in corpus_map.documents[0].metadata_conflicts


def test_quarter_request_with_year_only_metadata_is_unknown():
    plan = CorpusAwarePlanner(_map()).plan("What was Acme revenue in Q1 FY2023?")

    task = plan.tasks[0]
    assert task.source_availability == SourceAvailability.UNKNOWN
    assert task.availability_reason == "filing_period_granularity_or_metadata_incomplete"
    assert set(task.target_document_ids).issubset({"ACME_2021_10K", "ACME_2023_10K"})


def test_task_limit_is_enforced_and_question_only_has_no_corpus_targets():
    question = "Compare Apple's and Microsoft's revenue growth from FY2021 to FY2023"
    bounded = CorpusAwarePlanner(_map(), max_tasks=2).plan(question)
    baseline = QuestionOnlyPlanner(max_tasks=2).plan("What was Apple's revenue in FY2023?")

    assert len(bounded.tasks) == 2
    assert "task_limit_reached:2" in bounded.warnings
    assert baseline.planning_mode == PlanningMode.QUESTION_ONLY
    assert baseline.tasks[0].source_availability == SourceAvailability.UNKNOWN
    assert baseline.tasks[0].query is not None
    assert baseline.tasks[0].target_document_ids == ()
