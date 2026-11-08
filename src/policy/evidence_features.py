"""Versioned, provider-neutral observations about one evidence candidate."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FEATURE_SCHEMA_VERSION = "1.0.0"


class EntityMatch(StrEnum):
    EXACT = "EXACT"
    ALIAS = "ALIAS"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


class Alignment(StrEnum):
    EXACT = "EXACT"
    COMPATIBLE = "COMPATIBLE"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


class FilingTypeAlignment(StrEnum):
    EXACT = "EXACT"
    COMPATIBLE = "COMPATIBLE"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SupportLevel(StrEnum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    NONE = "NONE"
    CONTRADICTED = "CONTRADICTED"


class SourceQuality(StrEnum):
    PRIMARY = "PRIMARY"
    DERIVED = "DERIVED"
    SECONDARY = "SECONDARY"
    UNKNOWN = "UNKNOWN"


class TableContextIntegrity(StrEnum):
    INTACT = "INTACT"
    PARTIAL = "PARTIAL"
    BROKEN = "BROKEN"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class NumericConsistency(StrEnum):
    CONSISTENT = "CONSISTENT"
    INCONSISTENT = "INCONSISTENT"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SourceRevisionValidity(StrEnum):
    VALID = "VALID"
    SUPERSEDED = "SUPERSEDED"
    UNKNOWN = "UNKNOWN"


class ProvenanceValidity(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class ScoreObservation(BaseModel):
    """A normalized score with enough provenance to interpret its scale."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: float = Field(ge=0.0, le=1.0)
    observer_id: str = Field(min_length=1)
    observer_version: str = Field(min_length=1)
    is_calibrated_probability: bool = False
    calibration_id: str | None = None

    @model_validator(mode="after")
    def validate_probability_provenance(self) -> ScoreObservation:
        if self.is_calibrated_probability and not self.calibration_id:
            raise ValueError("calibrated probability observations require a calibration_id")
        return self


class EvidenceCandidateFeatures(BaseModel):
    """Structured observations supplied to deterministic evidence policy."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.0.0"] = FEATURE_SCHEMA_VERSION
    candidate_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    entity_match: EntityMatch
    metric_match: Alignment
    period_match: Alignment
    filing_type_match: FilingTypeAlignment = FilingTypeAlignment.NOT_APPLICABLE
    support_level: SupportLevel
    source_quality: SourceQuality
    table_context_integrity: TableContextIntegrity = TableContextIntegrity.NOT_APPLICABLE
    requires_table_context: bool = False
    numeric_consistency: NumericConsistency = NumericConsistency.NOT_APPLICABLE
    requires_numeric_consistency: bool = False
    contradiction_flag: bool | None
    provenance_validity: ProvenanceValidity
    source_revision_validity: SourceRevisionValidity
    semantic_relevance: ScoreObservation
    retrieval_confidence: ScoreObservation


__all__ = [
    "Alignment",
    "EvidenceCandidateFeatures",
    "EntityMatch",
    "FilingTypeAlignment",
    "FEATURE_SCHEMA_VERSION",
    "NumericConsistency",
    "ProvenanceValidity",
    "ScoreObservation",
    "SourceQuality",
    "SourceRevisionValidity",
    "SupportLevel",
    "TableContextIntegrity",
]
