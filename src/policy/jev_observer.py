"""Offline Jev observer scaffold for the existing candidate feature contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from src.policy.decision_backend import CandidateFeatureObserver
from src.policy.evidence_features import EvidenceCandidateFeatures, ScoreObservation

DEFAULT_JEV_MODEL_ID = "typesafe/jev-1.14"
NonemptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ObserverConfig(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    provider: NonemptyText = "openrouter"
    model_id: NonemptyText = DEFAULT_JEV_MODEL_ID
    timeout_seconds: float = Field(default=2.0, gt=0, allow_inf_nan=False)

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def numeric_timeout(cls, value: object) -> object:
        if type(value) not in (float, int):
            raise ValueError("Expected a numeric timeout")
        return value


class SemanticRequest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    evidence: Annotated[NonemptyText, Field(max_length=16_000)]
    requirement: Annotated[NonemptyText, Field(max_length=2_000)]


class SemanticObservation(BaseModel):
    """Provider-neutral semantic judgment with no authorization fields."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    relevance: Literal["relevant", "unclear", "irrelevant"]

    def constrain(
        self, trusted: EvidenceCandidateFeatures, *, observer_id: str, observer_version: str,
    ) -> EvidenceCandidateFeatures:
        relevance = {"relevant": 1.0, "unclear": 0.5, "irrelevant": 0.0}[self.relevance]
        if relevance >= trusted.semantic_relevance.score:
            return trusted
        return trusted.model_copy(update={
            "semantic_relevance": ScoreObservation(score=relevance, observer_id=observer_id,
                                                    observer_version=observer_version),
        })


class ObserverTransportError(Exception):
    """Provider transport failed or could not normalize the response."""


class ObserverTransport(Protocol):
    def __call__(
        self, request: SemanticRequest, *, provider: str, model_id: str, timeout_seconds: float,
    ) -> object:
        """Enforce the supplied deadline and return a normalized observation payload."""
        ...


class JevCandidateObserver:
    """Apply an optional conservative semantic observation to trusted features."""

    observer_id = "jev-candidate-observer"

    def __init__(
        self, fallback: CandidateFeatureObserver, *, config: ObserverConfig | None = None,
        transport: ObserverTransport | None = None,
    ):
        self.fallback = fallback
        self.config = config or ObserverConfig()
        self.transport = transport

    def observe(
        self, candidate: Mapping[str, Any], requirement: Mapping[str, Any],
    ) -> EvidenceCandidateFeatures:
        trusted = self.fallback.observe(candidate, requirement)
        if self.transport is None:
            return trusted
        try:
            request = SemanticRequest.model_validate({
                "evidence": candidate.get("text"),
                "requirement": requirement.get("description"),
            })
            reply = self.transport(
                request, provider=self.config.provider, model_id=self.config.model_id,
                timeout_seconds=self.config.timeout_seconds,
            )
            observation = SemanticObservation.model_validate(reply)
        except (ValidationError, OSError, ObserverTransportError):
            return trusted

        return observation.constrain(trusted, observer_id=self.observer_id,
                                     observer_version=f"{self.config.provider}/{self.config.model_id}:relevance-v1")
