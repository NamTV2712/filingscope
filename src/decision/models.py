"""Validated P2 contracts for evidence requirements and decisions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DecisionAction(StrEnum):
    ANSWER = "ANSWER"
    RETRIEVE_MORE = "RETRIEVE_MORE"
    ABSTAIN = "ABSTAIN"


class CoverageStatus(StrEnum):
    FOUND = "found"
    MISSING = "missing"
    CONFLICTED = "conflicted"
    UNSUPPORTED = "unsupported"


class EvidenceEntity(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_id: str
    canonical_name: str
    matched_alias: str


class MetricRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric_id: str
    display_name: str
    aliases: tuple[str, ...]
    quantitative: bool = True
    expected_value_kind: str = "amount"


class EvidenceRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement_id: str
    entity_id: str
    metric_id: str
    period: str | None = None
    minimum_observations: int = Field(default=1, ge=1)
    quantitative: bool = True


class OperationRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation: str
    metric_id: str | None = None
    requires_period_alignment: bool = False
    requires_unit_compatibility: bool = False


class QuestionRequirements(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str
    entities: tuple[EvidenceEntity, ...] = ()
    companies: tuple[str, ...] = ()
    metrics: tuple[MetricRequirement, ...] = ()
    periods: tuple[str, ...] = ()
    requested_currency: str | None = None
    operations: tuple[OperationRequirement, ...] = ()
    evidence: tuple[EvidenceRequirement, ...] = ()
    supported: bool = True
    unsupported_reasons: tuple[str, ...] = ()


class EvidenceFact(BaseModel):
    """A value or topical fact aligned to one source chunk."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    entity_id: str
    metric_id: str
    period: str | None = None
    value: str | None = None
    numeric_value: str | None = None
    currency: str | None = None
    scale: str | None = None
    value_kind: str | None = None
    document_id: str
    page_number: int | None = None
    source_url: str | None = None

    @property
    def unit(self) -> tuple[str | None, str | None]:
        return self.currency, self.scale


class EvidenceFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirement_id: str
    entity_id: str
    metric_id: str
    period: str | None = None
    status: CoverageStatus
    evidence_ids: tuple[str, ...] = ()
    facts: tuple[EvidenceFact, ...] = ()
    missing_reason: str | None = None


class EvidenceCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirements: QuestionRequirements
    findings: tuple[EvidenceFinding, ...] = ()
    missing_requirement_ids: tuple[str, ...] = ()
    conflicted_requirement_ids: tuple[str, ...] = ()
    operation_gaps: tuple[str, ...] = ()
    sufficient: bool = False


class DecisionBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    remaining_retrieval_attempts: int = Field(default=1, ge=0)


class DecisionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: DecisionAction
    reason_code: str
    coverage: EvidenceCoverage
    gap_requirement_ids: tuple[str, ...] = ()
    gap_codes: tuple[str, ...] = ()
    rationale: str
