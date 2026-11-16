"""Validated P2 contracts for evidence requirements and decisions."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_serializer

from src.ingestion.period_identity import (
    FilingInstant, FiscalYearPair, PeriodIdentity, PeriodScope, QuarterYtdLookup, ReportingInterval,
)


class DecisionAction(StrEnum):
    ANSWER = "ANSWER"
    RETRIEVE_MORE = "RETRIEVE_MORE"
    ABSTAIN = "ABSTAIN"


class CoverageStatus(StrEnum):
    FOUND = "found"
    MISSING = "missing"
    CONFLICTED = "conflicted"
    UNSUPPORTED = "unsupported"


class EvidenceSupport(StrEnum):
    FULL_SUPPORT = "FULL_SUPPORT"
    PARTIAL_SUPPORT = "PARTIAL_SUPPORT"
    IRRELEVANT = "IRRELEVANT"
    MISSING = "MISSING"
    CONTRADICTORY = "CONTRADICTORY"


class SetSufficiency(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    CONTRADICTORY = "CONTRADICTORY"
    UNSUPPORTED = "UNSUPPORTED"


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
    period_scope: PeriodScope | None = None
    period_end: date | None = None
    filing_instant: FilingInstant | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        data = handler(self)
        if self.period_scope is None:
            data.pop("period_scope", None)
        if self.period_end is None:
            data.pop("period_end", None)
        if self.filing_instant is None:
            data.pop("filing_instant", None)
        return data


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
    reporting_interval: ReportingInterval | None = None
    quarter_ytd: QuarterYtdLookup | None = None
    fiscal_year_pair: FiscalYearPair | None = None

    @property
    def has_filing_instants(self) -> bool:
        return any(item.filing_instant is not None for item in self.evidence)

    @property
    def requires_period_pair(self) -> bool:
        return (self.quarter_ytd is not None or self.fiscal_year_pair is not None
                or (len(self.evidence) == 2 and self.has_filing_instants))

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        data = handler(self)
        if self.reporting_interval is None:
            data.pop("reporting_interval", None)
        if self.quarter_ytd is None:
            data.pop("quarter_ytd", None)
        if self.fiscal_year_pair is None:
            data.pop("fiscal_year_pair", None)
        return data


class EvidenceFact(BaseModel):
    """A value or topical fact aligned to one source chunk."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str
    entity_id: str
    metric_id: str
    period: str | None = None
    period_identity: PeriodIdentity | None = None
    value: str | None = None
    raw_value: str | None = None
    numeric_value: str | None = None
    currency: str | None = None
    scale: str | None = None
    original_scale: str | None = None
    table_row: int | None = None
    table_column: int | None = None
    table_title: str | None = None
    row_label: str | None = None
    row_group: str | None = None
    unit_source_page: int | None = None
    filing_accession: str | None = None
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

    @computed_field
    @property
    def support(self) -> EvidenceSupport:
        if self.status == CoverageStatus.FOUND:
            return EvidenceSupport.FULL_SUPPORT
        if self.status == CoverageStatus.CONFLICTED:
            return EvidenceSupport.CONTRADICTORY
        if self.missing_reason in {"entity_mismatch", "metric_mismatch", "period_mismatch", "unit_mismatch",
                                   "source_revision_mismatch"}:
            return EvidenceSupport.IRRELEVANT
        if self.facts or self.missing_reason == "numerical_value_or_period_alignment_missing":
            return EvidenceSupport.PARTIAL_SUPPORT
        return EvidenceSupport.MISSING


class EvidenceCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    requirements: QuestionRequirements
    findings: tuple[EvidenceFinding, ...] = ()
    missing_requirement_ids: tuple[str, ...] = ()
    conflicted_requirement_ids: tuple[str, ...] = ()
    operation_gaps: tuple[str, ...] = ()
    sufficient: bool = False

    @computed_field
    @property
    def set_sufficiency(self) -> SetSufficiency:
        if not self.requirements.supported:
            return SetSufficiency.UNSUPPORTED
        if self.conflicted_requirement_ids:
            return SetSufficiency.CONTRADICTORY
        return SetSufficiency.COMPLETE if self.sufficient else SetSufficiency.INCOMPLETE


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
