"""Typed contracts for claim, citation, and deterministic calculation checks."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClaimStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIABLE = "UNVERIFIABLE"


class CitationStatus(StrEnum):
    VALID = "valid"
    MISSING = "missing"
    MALFORMED = "malformed"
    OUT_OF_RANGE = "out_of_range"


class ResponseDisposition(StrEnum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    ABSTAIN = "ABSTAIN"


class CalculationOperation(StrEnum):
    ADDITION = "addition"
    SUBTRACTION = "subtraction"
    DIFFERENCE = "difference"
    PERCENTAGE_GROWTH = "percentage_growth"


class CalculationOperand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    value: Decimal
    currency: str | None = None
    scale: str | None = None


class CalculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    operation: CalculationOperation
    operands: tuple[CalculationOperand, ...] = Field(min_length=2, max_length=10)
    reported_value: Decimal
    reported_currency: str | None = None
    reported_scale: str | None = None
    reported_kind: Literal["amount", "percent"] = "amount"
    rounding_precision: int = Field(default=2, ge=0, le=8)


class CalculationVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    passed: bool
    status: Literal["verified", "mismatch", "unverifiable"]
    operation: CalculationOperation
    expected_value: Decimal | None = None
    reported_value: Decimal
    expected_kind: Literal["amount", "percent"] | None = None
    expected_currency: str | None = None
    expected_scale: str | None = None
    reason_code: str


class ClaimValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    metric_id: str
    entity_id: str | None = None
    raw_value: str
    numeric_value: Decimal
    currency: str | None = None
    scale: str | None = None
    value_kind: Literal["amount", "percent", "currency_per_share"]
    period: str | None = None


class ClaimDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    claim_id: str = Field(pattern=r"^claim_[1-9][0-9]*$")
    statement: str = Field(min_length=1, max_length=2000)
    citations: tuple[int, ...] = Field(max_length=64)
    citation_marker_count: int = Field(ge=0, le=32)
    malformed_citation_count: int = Field(ge=0, le=32)
    entity_ids: tuple[str, ...] = Field(max_length=8)
    metric_ids: tuple[str, ...] = Field(max_length=8)
    periods: tuple[str, ...] = Field(max_length=8)
    values: tuple[ClaimValue, ...] = Field(max_length=32)
    has_unparsed_numeric_value: bool = False
    operation: str | None = None


class ClaimAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    claim_id: str
    statement: str
    status: ClaimStatus
    citation_status: CitationStatus
    citations: tuple[int, ...] = ()
    supported_values: tuple[str, ...] = ()
    unsupported_values: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    calculation: CalculationVerification | None = None
    reason_codes: tuple[str, ...] = ()
    claim_type: Literal["financial_fact", "calculation", "qualitative", "unclassified"] | None = None
    supporting_evidence_ids: tuple[str, ...] = ()
    requirement_ids: tuple[str, ...] = ()


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    disposition: ResponseDisposition
    claims: tuple[ClaimAssessment, ...] = ()
    reason_codes: tuple[str, ...] = ()
    valid_citation_count: int = Field(ge=0)
    invalid_citation_count: int = Field(ge=0)
    supported_claim_count: int = Field(ge=0)
    partial_claim_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    contradicted_claim_count: int = Field(ge=0)
    unverifiable_claim_count: int = Field(ge=0)
