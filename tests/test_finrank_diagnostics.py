"""Boundary attribution must reflect measured losses without guessed causes."""

from scripts.run_finrank_diagnostics import PageInterventionRetriever, failure_signals
from src.evaluation.failure_attribution import FailureStage, attribution


def test_route_rejection_precedes_retrieval_and_uses_requirement_reason():
    observation = {"disposition": "UNSUPPORTED", "retrieved_sources": [], "finally_missing": []}
    result = attribution(failure_signals(("metric_not_recognized",), observation, ("doc#p1",)), failed=True)
    assert result["first_failure_stage"] == FailureStage.METRIC_RESOLUTION
    assert result["failure_reason"] == "metric_not_recognized"


def test_missing_gold_page_and_unresolved_slots_are_distinct_boundaries():
    observation = {"disposition": "ABSTAIN", "retrieved_sources": ["doc#p2"], "finally_missing": ["metric:2024"]}
    missing = attribution(failure_signals((), observation, ("doc#p1",)), failed=True)
    found = attribution(failure_signals((), observation, ("doc#p2",)), failed=True)
    assert missing["first_failure_stage"] == FailureStage.CANDIDATE_RETRIEVAL
    assert found["first_failure_stage"] == FailureStage.EVIDENCE_SET_SUFFICIENCY
    assert found["failure_reason"] == "required_slots_unresolved_after_retrieval"


def test_no_evidence_of_a_specific_failure_stays_undetermined():
    observation = {"disposition": "ABSTAIN", "retrieved_sources": [], "finally_missing": []}
    result = attribution(failure_signals((), observation, None), failed=True)
    assert result["first_failure_stage"] == FailureStage.UNDETERMINED


def test_location_oracle_preserves_raw_text_and_document_scope():
    rows = ({"chunk_id": "a", "doc_name": "one", "text": "raw source page"},
            {"chunk_id": "b", "doc_name": "two", "text": "another source page"})
    retriever = PageInterventionRetriever(None, rows)
    assert retriever.retrieve("rephrased question", document_ids=("one",)) == [rows[0]]
    assert retriever.retrieve("same question", document_ids=("absent",)) == []
    assert retriever.chunks == {"a": rows[0]}
