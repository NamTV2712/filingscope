"""Decision and observation interfaces for evidence-candidate policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from src.policy.evidence_features import EvidenceCandidateFeatures
from src.policy.evidence_policy import (
    EvidencePolicy,
    EvidencePolicyConfig,
    EvidencePolicyDecision,
)


@runtime_checkable
class CandidateFeatureObserver(Protocol):
    """Provider-neutral interface for structured candidate observations.

    Model-backed observers may implement this interface, but their output is
    still only a feature vector. It is not an evidence acceptance decision.
    """

    observer_id: str

    def observe(
        self,
        candidate: Mapping[str, Any],
        requirement: Mapping[str, Any],
    ) -> EvidenceCandidateFeatures: ...


@runtime_checkable
class DecisionBackend(Protocol):
    """Interface for applying the evidence policy to typed observations."""

    backend_id: str

    def decide(self, features: EvidenceCandidateFeatures) -> EvidencePolicyDecision: ...


class DeterministicDecisionBackend:
    """Production-safe decision backend; no provider or probabilistic output."""

    backend_id = "deterministic-evidence-policy"

    def __init__(self, config: EvidencePolicyConfig | None = None):
        self.policy = EvidencePolicy(config)

    def decide(self, features: EvidenceCandidateFeatures) -> EvidencePolicyDecision:
        return self.policy.decide(features)


__all__ = [
    "CandidateFeatureObserver",
    "DecisionBackend",
    "DeterministicDecisionBackend",
]
