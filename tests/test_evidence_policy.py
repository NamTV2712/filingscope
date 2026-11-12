import pytest

from src.policy.decision_backend import DeterministicDecisionBackend
from src.policy.evidence_features import EvidenceCandidateFeatures, ScoreObservation
from src.policy.evidence_policy import (
    CandidateDisposition,
    EvidencePolicy,
    EvidencePolicyConfig,
    PolicyReason,
)


def _features(**overrides) -> EvidenceCandidateFeatures:
    values = {
        "candidate_id": "candidate-1",
        "requirement_id": "requirement-1",
        "entity_match": "EXACT",
        "metric_match": "EXACT",
        "period_match": "EXACT",
        "support_level": "FULL",
        "source_quality": "PRIMARY",
        "table_context_integrity": "INTACT",
        "requires_table_context": True,
        "numeric_consistency": "CONSISTENT",
        "requires_numeric_consistency": True,
        "contradiction_flag": False,
        "provenance_validity": "VALID",
        "source_revision_validity": "VALID",
        "semantic_relevance": {
            "score": 0.9,
            "observer_id": "test-observer",
            "observer_version": "1.0.0",
        },
        "retrieval_confidence": {
            "score": 0.8,
            "observer_id": "test-ranker",
            "observer_version": "1.0.0",
        },
    }
    values.update(overrides)
    return EvidenceCandidateFeatures(**values)


def test_policy_accepts_complete_aligned_primary_candidate() -> None:
    decision = EvidencePolicy().decide(_features())

    assert decision.disposition == CandidateDisposition.ACCEPT
    assert decision.reason_codes == (PolicyReason.CANDIDATE_ACCEPTED,)
    assert decision.feature_schema_version == "1.1.0"
    assert decision.policy_version == "1.1.0"


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"entity_match": "MISMATCH"}, PolicyReason.ENTITY_MISMATCH),
        ({"metric_match": "MISMATCH"}, PolicyReason.METRIC_MISMATCH),
        ({"period_match": "MISMATCH"}, PolicyReason.PERIOD_MISMATCH),
        ({"filing_type_match": "MISMATCH"}, PolicyReason.FILING_TYPE_MISMATCH),
        ({"provenance_validity": "INVALID"}, PolicyReason.INVALID_PROVENANCE),
        ({"source_revision_validity": "SUPERSEDED"}, PolicyReason.SUPERSEDED_SOURCE_REVISION),
        ({"support_level": "NONE"}, PolicyReason.NO_SUPPORT),
        ({"support_level": "CONTRADICTED"}, PolicyReason.CONTRADICTED_SUPPORT),
        ({"contradiction_flag": True}, PolicyReason.CONTRADICTION_DETECTED),
        ({"numeric_consistency": "INCONSISTENT"}, PolicyReason.NUMERIC_INCONSISTENCY),
        ({"table_context_integrity": "BROKEN"}, PolicyReason.BROKEN_TABLE_CONTEXT),
    ],
)
def test_hard_constraint_rejects_even_with_high_similarity(override, reason) -> None:
    decision = EvidencePolicy().decide(_features(
        **override,
        semantic_relevance={
            "score": 1.0,
            "observer_id": "high-score-model",
            "observer_version": "test",
        },
        retrieval_confidence={
            "score": 1.0,
            "observer_id": "high-score-ranker",
            "observer_version": "test",
        },
    ))

    assert decision.disposition == CandidateDisposition.REJECT
    assert reason in decision.reason_codes


def test_soft_uncertainty_becomes_weak_with_stable_reason_order() -> None:
    decision = EvidencePolicy().decide(_features(
        period_match="COMPATIBLE",
        support_level="PARTIAL",
        source_quality="SECONDARY",
    ))

    assert decision.disposition == CandidateDisposition.WEAK
    assert decision.reason_codes == (
        PolicyReason.PERIOD_ALIGNMENT_COMPATIBLE,
        PolicyReason.PARTIAL_SUPPORT,
        PolicyReason.SECONDARY_SOURCE,
    )


def test_low_scores_only_demote_and_never_override_a_hard_mismatch() -> None:
    weak = EvidencePolicy().decide(_features(
        semantic_relevance={"score": 0.1, "observer_id": "m", "observer_version": "1"},
    ))
    rejected = EvidencePolicy().decide(_features(
        entity_match="MISMATCH",
        semantic_relevance={"score": 0.1, "observer_id": "m", "observer_version": "1"},
    ))

    assert weak.disposition == CandidateDisposition.WEAK
    assert PolicyReason.LOW_SEMANTIC_RELEVANCE in weak.reason_codes
    assert rejected.disposition == CandidateDisposition.REJECT
    assert PolicyReason.ENTITY_MISMATCH in rejected.reason_codes


def test_score_thresholds_are_versioned_and_do_not_produce_probabilities() -> None:
    backend = DeterministicDecisionBackend(EvidencePolicyConfig(
        policy_version="test-policy-1",
        minimum_semantic_relevance=0.7,
    ))
    decision = backend.decide(_features())

    assert decision.policy_version == "test-policy-1"
    assert decision.disposition == CandidateDisposition.ACCEPT
    assert decision.acceptance_probability is None


def test_feature_schema_rejects_invalid_scores_and_unversioned_probabilities() -> None:
    with pytest.raises(ValueError):
        _features(semantic_relevance={
            "score": 1.1,
            "observer_id": "model",
            "observer_version": "1",
        })
    with pytest.raises(ValueError, match="calibration_id"):
        ScoreObservation(
            score=0.8,
            observer_id="judge",
            observer_version="1",
            is_calibrated_probability=True,
        )


def test_metric_and_period_alignment_cannot_be_marked_not_applicable() -> None:
    with pytest.raises(ValueError):
        _features(metric_match="NOT_APPLICABLE")
    with pytest.raises(ValueError):
        _features(period_match="NOT_APPLICABLE")


def test_observed_numeric_inconsistency_is_always_a_hard_rejection() -> None:
    decision = EvidencePolicy().decide(_features(
        requires_numeric_consistency=False,
        numeric_consistency="INCONSISTENT",
    ))

    assert decision.disposition == CandidateDisposition.REJECT
    assert PolicyReason.NUMERIC_INCONSISTENCY in decision.reason_codes
