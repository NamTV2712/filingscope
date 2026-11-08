"""Deterministic, versioned evidence-candidate acceptance policy."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from src.policy.evidence_features import (
    Alignment,
    EvidenceCandidateFeatures,
    EntityMatch,
    FilingTypeAlignment,
    NumericConsistency,
    ProvenanceValidity,
    SourceQuality,
    SourceRevisionValidity,
    SupportLevel,
    TableContextIntegrity,
)

POLICY_VERSION = "1.0.0"


class CandidateDisposition(StrEnum):
    ACCEPT = "ACCEPT"
    WEAK = "WEAK"
    REJECT = "REJECT"


class PolicyReason(StrEnum):
    CANDIDATE_ACCEPTED = "CANDIDATE_ACCEPTED"
    ENTITY_MISMATCH = "ENTITY_MISMATCH"
    METRIC_MISMATCH = "METRIC_MISMATCH"
    PERIOD_MISMATCH = "PERIOD_MISMATCH"
    FILING_TYPE_MISMATCH = "FILING_TYPE_MISMATCH"
    INVALID_PROVENANCE = "INVALID_PROVENANCE"
    SUPERSEDED_SOURCE_REVISION = "SUPERSEDED_SOURCE_REVISION"
    CONTRADICTED_SUPPORT = "CONTRADICTED_SUPPORT"
    NO_SUPPORT = "NO_SUPPORT"
    CONTRADICTION_DETECTED = "CONTRADICTION_DETECTED"
    NUMERIC_INCONSISTENCY = "NUMERIC_INCONSISTENCY"
    BROKEN_TABLE_CONTEXT = "BROKEN_TABLE_CONTEXT"
    ENTITY_ALIGNMENT_UNKNOWN = "ENTITY_ALIGNMENT_UNKNOWN"
    METRIC_ALIGNMENT_COMPATIBLE = "METRIC_ALIGNMENT_COMPATIBLE"
    METRIC_ALIGNMENT_UNKNOWN = "METRIC_ALIGNMENT_UNKNOWN"
    PERIOD_ALIGNMENT_COMPATIBLE = "PERIOD_ALIGNMENT_COMPATIBLE"
    PERIOD_ALIGNMENT_UNKNOWN = "PERIOD_ALIGNMENT_UNKNOWN"
    FILING_TYPE_COMPATIBLE = "FILING_TYPE_COMPATIBLE"
    FILING_TYPE_UNKNOWN = "FILING_TYPE_UNKNOWN"
    PARTIAL_SUPPORT = "PARTIAL_SUPPORT"
    SECONDARY_SOURCE = "SECONDARY_SOURCE"
    SOURCE_QUALITY_UNKNOWN = "SOURCE_QUALITY_UNKNOWN"
    TABLE_CONTEXT_PARTIAL = "TABLE_CONTEXT_PARTIAL"
    TABLE_CONTEXT_UNKNOWN = "TABLE_CONTEXT_UNKNOWN"
    NUMERIC_CONSISTENCY_UNKNOWN = "NUMERIC_CONSISTENCY_UNKNOWN"
    CONTRADICTION_STATUS_UNKNOWN = "CONTRADICTION_STATUS_UNKNOWN"
    PROVENANCE_UNKNOWN = "PROVENANCE_UNKNOWN"
    SOURCE_REVISION_UNKNOWN = "SOURCE_REVISION_UNKNOWN"
    LOW_SEMANTIC_RELEVANCE = "LOW_SEMANTIC_RELEVANCE"
    LOW_RETRIEVAL_CONFIDENCE = "LOW_RETRIEVAL_CONFIDENCE"


class EvidencePolicyConfig(BaseModel):
    """Versioned policy thresholds; score thresholds only create WEAK results."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: str = Field(default=POLICY_VERSION, min_length=1)
    minimum_semantic_relevance: float = Field(default=0.50, ge=0.0, le=1.0)
    minimum_retrieval_confidence: float = Field(default=0.25, ge=0.0, le=1.0)


class EvidencePolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    requirement_id: str
    feature_schema_version: str
    policy_version: str
    disposition: CandidateDisposition
    reason_codes: tuple[PolicyReason, ...]
    acceptance_probability: float | None = Field(default=None, ge=0.0, le=1.0)


class EvidencePolicy:
    """Apply hard alignment/provenance constraints before softer observations."""

    def __init__(self, config: EvidencePolicyConfig | None = None):
        self.config = config or EvidencePolicyConfig()

    def decide(self, features: EvidenceCandidateFeatures) -> EvidencePolicyDecision:
        hard_reasons: list[PolicyReason] = []
        if features.entity_match == EntityMatch.MISMATCH:
            hard_reasons.append(PolicyReason.ENTITY_MISMATCH)
        if features.metric_match == Alignment.MISMATCH:
            hard_reasons.append(PolicyReason.METRIC_MISMATCH)
        if features.period_match == Alignment.MISMATCH:
            hard_reasons.append(PolicyReason.PERIOD_MISMATCH)
        if features.filing_type_match == FilingTypeAlignment.MISMATCH:
            hard_reasons.append(PolicyReason.FILING_TYPE_MISMATCH)
        if features.provenance_validity == ProvenanceValidity.INVALID:
            hard_reasons.append(PolicyReason.INVALID_PROVENANCE)
        if features.source_revision_validity == SourceRevisionValidity.SUPERSEDED:
            hard_reasons.append(PolicyReason.SUPERSEDED_SOURCE_REVISION)
        if features.support_level == SupportLevel.CONTRADICTED:
            hard_reasons.append(PolicyReason.CONTRADICTED_SUPPORT)
        if features.support_level == SupportLevel.NONE:
            hard_reasons.append(PolicyReason.NO_SUPPORT)
        if features.contradiction_flag is True:
            hard_reasons.append(PolicyReason.CONTRADICTION_DETECTED)
        if features.numeric_consistency == NumericConsistency.INCONSISTENT:
            hard_reasons.append(PolicyReason.NUMERIC_INCONSISTENCY)
        if (
            features.requires_table_context
            and features.table_context_integrity == TableContextIntegrity.BROKEN
        ):
            hard_reasons.append(PolicyReason.BROKEN_TABLE_CONTEXT)
        if hard_reasons:
            return self._decision(features, CandidateDisposition.REJECT, hard_reasons)

        weak_reasons: list[PolicyReason] = []
        if features.entity_match == EntityMatch.UNKNOWN:
            weak_reasons.append(PolicyReason.ENTITY_ALIGNMENT_UNKNOWN)
        if features.metric_match == Alignment.COMPATIBLE:
            weak_reasons.append(PolicyReason.METRIC_ALIGNMENT_COMPATIBLE)
        elif features.metric_match == Alignment.UNKNOWN:
            weak_reasons.append(PolicyReason.METRIC_ALIGNMENT_UNKNOWN)
        if features.period_match == Alignment.COMPATIBLE:
            weak_reasons.append(PolicyReason.PERIOD_ALIGNMENT_COMPATIBLE)
        elif features.period_match == Alignment.UNKNOWN:
            weak_reasons.append(PolicyReason.PERIOD_ALIGNMENT_UNKNOWN)
        if features.filing_type_match == FilingTypeAlignment.COMPATIBLE:
            weak_reasons.append(PolicyReason.FILING_TYPE_COMPATIBLE)
        elif features.filing_type_match == FilingTypeAlignment.UNKNOWN:
            weak_reasons.append(PolicyReason.FILING_TYPE_UNKNOWN)
        if features.support_level == SupportLevel.PARTIAL:
            weak_reasons.append(PolicyReason.PARTIAL_SUPPORT)
        if features.source_quality == SourceQuality.SECONDARY:
            weak_reasons.append(PolicyReason.SECONDARY_SOURCE)
        elif features.source_quality == SourceQuality.UNKNOWN:
            weak_reasons.append(PolicyReason.SOURCE_QUALITY_UNKNOWN)
        if features.requires_table_context:
            if features.table_context_integrity == TableContextIntegrity.PARTIAL:
                weak_reasons.append(PolicyReason.TABLE_CONTEXT_PARTIAL)
            elif features.table_context_integrity == TableContextIntegrity.UNKNOWN:
                weak_reasons.append(PolicyReason.TABLE_CONTEXT_UNKNOWN)
        if (
            features.requires_numeric_consistency
            and features.numeric_consistency == NumericConsistency.UNKNOWN
        ):
            weak_reasons.append(PolicyReason.NUMERIC_CONSISTENCY_UNKNOWN)
        if features.contradiction_flag is None:
            weak_reasons.append(PolicyReason.CONTRADICTION_STATUS_UNKNOWN)
        if features.provenance_validity == ProvenanceValidity.UNKNOWN:
            weak_reasons.append(PolicyReason.PROVENANCE_UNKNOWN)
        if features.source_revision_validity == SourceRevisionValidity.UNKNOWN:
            weak_reasons.append(PolicyReason.SOURCE_REVISION_UNKNOWN)
        if features.semantic_relevance.score < self.config.minimum_semantic_relevance:
            weak_reasons.append(PolicyReason.LOW_SEMANTIC_RELEVANCE)
        if features.retrieval_confidence.score < self.config.minimum_retrieval_confidence:
            weak_reasons.append(PolicyReason.LOW_RETRIEVAL_CONFIDENCE)
        if weak_reasons:
            return self._decision(features, CandidateDisposition.WEAK, weak_reasons)
        return self._decision(
            features,
            CandidateDisposition.ACCEPT,
            [PolicyReason.CANDIDATE_ACCEPTED],
        )

    def _decision(
        self,
        features: EvidenceCandidateFeatures,
        disposition: CandidateDisposition,
        reason_codes: list[PolicyReason],
    ) -> EvidencePolicyDecision:
        return EvidencePolicyDecision(
            candidate_id=features.candidate_id,
            requirement_id=features.requirement_id,
            feature_schema_version=features.schema_version,
            policy_version=self.config.policy_version,
            disposition=disposition,
            reason_codes=tuple(reason_codes),
        )


__all__ = [
    "CandidateDisposition",
    "EvidencePolicy",
    "EvidencePolicyConfig",
    "EvidencePolicyDecision",
    "POLICY_VERSION",
    "PolicyReason",
]
