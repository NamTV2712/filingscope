from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from src.evaluation.evidence_policy_benchmark import evidence_policy_scenarios
from src.policy.decision_backend import CandidateFeatureObserver, DeterministicDecisionBackend
from src.policy.evidence_features import (
    Alignment, FilingTypeAlignment, SourceRevisionValidity, SupportLevel, TableContextIntegrity,
)
from src.policy.evidence_policy import CandidateDisposition, PolicyReason
from src.policy.jev_observer import (
    DEFAULT_JEV_MODEL_ID, JevCandidateObserver, ObserverConfig, ObserverTransportError, SemanticRequest,
)

CANDIDATE = {"text": "The consolidated statements list annual net sales.", "private_metadata": "not projected"}
REQUIREMENT = {"description": "Find text concerning net sales.", "other": "not projected"}
BASELINE = next(
    case.features for case in evidence_policy_scenarios()
    if case.expected_disposition == CandidateDisposition.ACCEPT
)


def test_observer_is_optional_and_offline_by_default():
    fallback = Mock(return_value=None)
    fallback.observe.return_value = BASELINE
    observer = JevCandidateObserver(fallback)
    assert isinstance(observer, CandidateFeatureObserver)
    assert observer.config.model_id == DEFAULT_JEV_MODEL_ID == "typesafe/jev-1.14"
    assert observer.observe(CANDIDATE, REQUIREMENT) is BASELINE
    fallback.observe.assert_called_once_with(CANDIDATE, REQUIREMENT)


def test_mock_transport_can_only_lower_semantic_relevance():
    fallback = Mock()
    fallback.observe.return_value = BASELINE
    transport = Mock(return_value={"relevance": "irrelevant"})
    observer = JevCandidateObserver(
        fallback, transport=transport,
        config=ObserverConfig(provider="fixture", model_id="jev-test", timeout_seconds=0.25),
    )
    result = observer.observe(CANDIDATE, REQUIREMENT)
    transport.assert_called_once_with(
        SemanticRequest(evidence=CANDIDATE["text"], requirement=REQUIREMENT["description"]),
        provider="fixture", model_id="jev-test", timeout_seconds=0.25,
    )
    assert result.semantic_relevance.score == 0
    assert not result.semantic_relevance.is_calibrated_probability
    assert result.semantic_relevance.observer_version == "fixture/jev-test:relevance-v1"
    assert result.model_dump(exclude={"semantic_relevance"}) == BASELINE.model_dump(exclude={"semantic_relevance"})
    decision = DeterministicDecisionBackend().decide(result)
    assert decision.disposition == CandidateDisposition.WEAK
    assert PolicyReason.LOW_SEMANTIC_RELEVANCE in decision.reason_codes


@pytest.mark.parametrize("reply", [
    {"relevance": "relevant", "disposition": "ACCEPT"},
    {"relevance": "relevant", "numeric_consistency": "CONSISTENT"},
    {"relevance": True},
    {"relevance": "accept"},
    {},
    "relevant",
    None,
])
def test_malformed_transport_reply_uses_deterministic_fallback(reply):
    fallback = Mock()
    fallback.observe.return_value = BASELINE
    transport = Mock(return_value=reply)
    assert JevCandidateObserver(fallback, transport=transport).observe(CANDIDATE, REQUIREMENT) is BASELINE


@pytest.mark.parametrize("failure", [TimeoutError, OSError, ObserverTransportError])
def test_timeout_or_transport_error_falls_back_without_retry(failure):
    fallback = Mock()
    fallback.observe.return_value = BASELINE
    transport = Mock(side_effect=failure("sensitive transport detail"))
    result = JevCandidateObserver(fallback, transport=transport).observe(CANDIDATE, REQUIREMENT)
    assert result is BASELINE
    assert transport.call_count == 1


def test_bad_input_skips_transport():
    fallback = Mock()
    fallback.observe.return_value = BASELINE
    transport = Mock()
    observer = JevCandidateObserver(fallback, transport=transport)
    assert observer.observe({"text": " "}, REQUIREMENT) is BASELINE
    assert observer.observe({"text": "x" * 16_001}, REQUIREMENT) is BASELINE
    transport.assert_not_called()


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), "1", True])
def test_timeout_config_is_strict(value):
    with pytest.raises(ValidationError):
        ObserverConfig(timeout_seconds=value)


def test_positive_observation_preserves_all_deterministic_decisions():
    backend = DeterministicDecisionBackend()
    fallback = Mock()
    observer = JevCandidateObserver(fallback, transport=Mock(return_value={"relevance": "relevant"}))
    scenarios = [case.features for case in evidence_policy_scenarios()]
    scenarios.extend((
        BASELINE.model_copy(update={"unit_match": Alignment.MISMATCH}),
        BASELINE.model_copy(update={"filing_type_match": FilingTypeAlignment.MISMATCH}),
        BASELINE.model_copy(update={"source_revision_validity": SourceRevisionValidity.MISMATCH}),
        BASELINE.model_copy(update={"support_level": SupportLevel.NONE}),
        BASELINE.model_copy(update={"requires_table_context": True, "table_context_integrity": TableContextIntegrity.BROKEN}),
    ))
    hard_reasons = set()
    for features in scenarios:
        fallback.observe.return_value = features
        baseline = backend.decide(features)
        candidate = backend.decide(observer.observe(CANDIDATE, REQUIREMENT))
        assert candidate == baseline
        if baseline.disposition == CandidateDisposition.REJECT:
            hard_reasons.update(baseline.reason_codes)
    assert {
        PolicyReason.ENTITY_MISMATCH, PolicyReason.METRIC_MISMATCH, PolicyReason.PERIOD_MISMATCH,
        PolicyReason.UNIT_MISMATCH, PolicyReason.INVALID_PROVENANCE, PolicyReason.SOURCE_REVISION_MISMATCH,
        PolicyReason.NUMERIC_INCONSISTENCY, PolicyReason.FILING_TYPE_MISMATCH, PolicyReason.NO_SUPPORT,
        PolicyReason.CONTRADICTED_SUPPORT, PolicyReason.CONTRADICTION_DETECTED,
        PolicyReason.SUPERSEDED_SOURCE_REVISION, PolicyReason.BROKEN_TABLE_CONTEXT,
    } <= hard_reasons
