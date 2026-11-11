"""Typed, provenance-linked records for the shared Evidence Ledger."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.decision.models import EvidenceRequirement, QuestionRequirements
from src.research.planner import ResearchPlan, ResearchTask
from src.verification.models import ClaimStatus, VerificationResult


class EvidenceSourceType(StrEnum):
    TEXT_EVIDENCE = "TEXT_EVIDENCE"
    TABLE_EVIDENCE = "TABLE_EVIDENCE"
    XBRL_FACT = "XBRL_FACT"
    DERIVED_FACT = "DERIVED_FACT"


class EvidenceStatus(StrEnum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    CONFLICTED = "CONFLICTED"
    UNKNOWN = "UNKNOWN"


class CalculationValidationStatus(StrEnum):
    PENDING = "PENDING"
    VALID = "VALID"
    MISMATCH = "MISMATCH"
    UNVERIFIABLE = "UNVERIFIABLE"


_CLAIM_VERIFICATION_PRIORITY = {
    ClaimStatus.SUPPORTED: 0,
    ClaimStatus.PARTIALLY_SUPPORTED: 1,
    ClaimStatus.UNVERIFIABLE: 2,
    ClaimStatus.UNSUPPORTED: 3,
    ClaimStatus.CONTRADICTED: 4,
}


class RetrievalObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    method: str = Field(min_length=1)
    rank: int | None = Field(default=None, ge=0)


def _canonical(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def _stable_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(
        _canonical(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:32]}"


def _tuple_values(value: Any, *, sort: bool = False) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = (value,)
    else:
        values = tuple(value)
    return tuple(sorted(set(values), key=str)) if sort else values


_EVIDENCE_ID_FIELDS = (
    "request_id",
    "source_type",
    "document_id",
    "chunk_id",
    "company",
    "ticker",
    "cik",
    "form_type",
    "filing_date",
    "fiscal_period",
    "section",
    "page",
    "table_id",
    "metric",
    "metric_id",
    "financial_concept",
    "raw_value",
    "normalized_value",
    "unit",
    "currency",
    "source_url",
    "source_revision",
    "derived_from_evidence_ids",
    "calculation_id",
)


class EvidenceRecord(BaseModel):
    """Metadata-only pointer to primary or explicitly derived evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    evidence_id: str = Field(pattern=r"^ev_[0-9a-f]{32}$")
    request_id: str = Field(min_length=1)
    document_id: str | None = None
    chunk_id: str | None = None
    company: str | None = None
    ticker: str | None = None
    cik: str | None = None
    form_type: str | None = None
    filing_date: str | None = None
    fiscal_period: str | None = None
    section: str | None = None
    page: int | None = Field(default=None, ge=0)
    table_id: str | None = None
    metric: str | None = None
    metric_id: str | None = None
    financial_concept: str | None = None
    raw_value: str | None = None
    normalized_value: str | None = None
    unit: str | None = None
    currency: str | None = None
    source_type: EvidenceSourceType
    source_url: str | None = None
    retrieval_method: str | None = None
    retrieval_rank: int | None = Field(default=None, ge=0)
    retrieval_observations: tuple[RetrievalObservation, ...] = ()
    discovered_by: tuple[str, ...] = Field(default=("unknown",), min_length=1)
    source_revision: str | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.UNKNOWN
    task_id: str | None = None
    task_ids: tuple[str, ...] = ()
    requirement_ids: tuple[str, ...] = ()
    derived_from_evidence_ids: tuple[str, ...] = ()
    calculation_id: str | None = None

    @classmethod
    def from_source(cls, **values: Any) -> "EvidenceRecord":
        if "evidence_id" in values:
            raise ValueError("evidence_id is computed from request and source identity")
        prepared = dict(values)
        if not isinstance(prepared.get("source_type"), EvidenceSourceType):
            prepared["source_type"] = EvidenceSourceType(prepared["source_type"])
        if "evidence_status" in prepared and not isinstance(prepared["evidence_status"], EvidenceStatus):
            prepared["evidence_status"] = EvidenceStatus(prepared["evidence_status"])
        task_ids = set(_tuple_values(prepared.get("task_ids")))
        if prepared.get("task_id") is not None:
            task_ids.add(prepared["task_id"])
        prepared["task_ids"] = tuple(sorted(task_ids))
        prepared["task_id"] = prepared["task_ids"][0] if prepared["task_ids"] else None
        prepared["requirement_ids"] = _tuple_values(prepared.get("requirement_ids"), sort=True)
        prepared["derived_from_evidence_ids"] = _tuple_values(
            prepared.get("derived_from_evidence_ids")
        )
        prepared["discovered_by"] = _tuple_values(
            prepared.get("discovered_by", ("unknown",)), sort=True
        ) or ("unknown",)
        observations = prepared.get("retrieval_observations", ())
        prepared["retrieval_observations"] = tuple(
            item if isinstance(item, RetrievalObservation) else RetrievalObservation.model_validate(item)
            for item in observations
        )
        if prepared.get("retrieval_method"):
            prepared["retrieval_observations"] = (
                *prepared["retrieval_observations"],
                RetrievalObservation(
                    method=prepared["retrieval_method"],
                    rank=prepared.get("retrieval_rank"),
                ),
            )
        prepared["retrieval_observations"] = _sorted_observations(
            prepared["retrieval_observations"]
        )
        best = _best_observation(prepared["retrieval_observations"])
        prepared["retrieval_method"] = best.method if best else None
        prepared["retrieval_rank"] = best.rank if best else None
        prepared["evidence_id"] = _stable_id("ev", _evidence_identity(prepared))
        return cls(**prepared)

    @model_validator(mode="after")
    def validate_identity_and_provenance(self) -> "EvidenceRecord":
        if self.evidence_id != _stable_id("ev", _evidence_identity(self)):
            raise ValueError("evidence_id does not match its stable source identity")
        if tuple(sorted(set(self.requirement_ids))) != self.requirement_ids:
            raise ValueError("requirement_ids must be unique and sorted")
        if tuple(sorted(set(self.task_ids))) != self.task_ids:
            raise ValueError("task_ids must be unique and sorted")
        if (self.task_ids[0] if self.task_ids else None) != self.task_id:
            raise ValueError("task_id must be the first canonical task_ids value")
        if len(set(self.derived_from_evidence_ids)) != len(self.derived_from_evidence_ids):
            raise ValueError("derived input evidence IDs must be unique")
        if tuple(sorted(set(self.discovered_by))) != self.discovered_by:
            raise ValueError("discovered_by values must be unique and sorted")
        if _sorted_observations(self.retrieval_observations) != self.retrieval_observations:
            raise ValueError("retrieval observations must be unique and sorted")
        best = _best_observation(self.retrieval_observations)
        if (best.method if best else None) != self.retrieval_method:
            raise ValueError("retrieval_method must identify the best recorded observation")
        if (best.rank if best else None) != self.retrieval_rank:
            raise ValueError("retrieval_rank must match the best recorded observation")
        if self.source_type == EvidenceSourceType.DERIVED_FACT:
            if not self.calculation_id or not self.derived_from_evidence_ids:
                raise ValueError("derived facts require a calculation and every input evidence ID")
        elif self.calculation_id is not None or self.derived_from_evidence_ids:
            raise ValueError("primary evidence cannot declare derived calculation inputs")
        elif self.source_type == EvidenceSourceType.TEXT_EVIDENCE:
            if not self.document_id or not (self.chunk_id or self.page is not None):
                raise ValueError("text evidence requires a document and chunk or page locator")
        elif self.source_type == EvidenceSourceType.TABLE_EVIDENCE:
            if not self.document_id or not (self.table_id or self.chunk_id or self.page is not None):
                raise ValueError("table evidence requires a document and table/chunk/page locator")
        elif self.source_type == EvidenceSourceType.XBRL_FACT:
            if not self.financial_concept or not (self.document_id or self.source_url):
                raise ValueError("XBRL facts require a concept and accession/document or source URL")
        return self


def _evidence_identity(record: EvidenceRecord | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(record, EvidenceRecord):
        return {field: getattr(record, field) for field in _EVIDENCE_ID_FIELDS}
    return {
        field: record.get(field, () if field == "derived_from_evidence_ids" else None)
        for field in _EVIDENCE_ID_FIELDS
    }


_FACT_ID_FIELDS = (
    "request_id",
    "entity_id",
    "company",
    "ticker",
    "cik",
    "metric_id",
    "financial_concept",
    "fiscal_period",
    "raw_value",
    "normalized_value",
    "unit",
    "currency",
    "source_type",
    "source_revision",
)


class FinancialFact(BaseModel):
    """Normalized financial observation linked to one or more source records."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    fact_id: str = Field(pattern=r"^fact_[0-9a-f]{32}$")
    request_id: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    requirement_ids: tuple[str, ...] = ()
    entity_id: str | None = None
    company: str | None = None
    ticker: str | None = None
    cik: str | None = None
    metric_id: str = Field(min_length=1)
    financial_concept: str | None = None
    fiscal_period: str | None = None
    raw_value: str | None = None
    normalized_value: str | None = None
    unit: str | None = None
    currency: str | None = None
    source_type: EvidenceSourceType
    source_revision: str | None = None

    @classmethod
    def from_evidence(
        cls,
        record: EvidenceRecord,
        *,
        entity_id: str | None = None,
        requirement_ids: tuple[str, ...] = (),
    ) -> "FinancialFact":
        if not record.metric_id:
            raise ValueError("evidence must have a metric_id before it can become a financial fact")
        values = {
            "request_id": record.request_id,
            "evidence_ids": (record.evidence_id,),
            "requirement_ids": _tuple_values(requirement_ids, sort=True),
            "entity_id": entity_id,
            "company": record.company,
            "ticker": record.ticker,
            "cik": record.cik,
            "metric_id": record.metric_id,
            "financial_concept": record.financial_concept,
            "fiscal_period": record.fiscal_period,
            "raw_value": record.raw_value,
            "normalized_value": record.normalized_value,
            "unit": record.unit,
            "currency": record.currency,
            "source_type": record.source_type,
            "source_revision": record.source_revision,
        }
        return cls(fact_id=_stable_id("fact", _fact_identity(values)), **values)

    @model_validator(mode="after")
    def validate_fact_identity(self) -> "FinancialFact":
        if self.fact_id != _stable_id("fact", _fact_identity(self)):
            raise ValueError("fact_id does not match its normalized fact identity")
        if tuple(sorted(set(self.evidence_ids))) != self.evidence_ids:
            raise ValueError("financial fact evidence_ids must be unique and sorted")
        if tuple(sorted(set(self.requirement_ids))) != self.requirement_ids:
            raise ValueError("financial fact requirement_ids must be unique and sorted")
        return self


def _fact_identity(fact: FinancialFact | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(fact, FinancialFact):
        return {field: getattr(fact, field) for field in _FACT_ID_FIELDS}
    return {field: fact.get(field) for field in _FACT_ID_FIELDS}


_CALCULATION_ID_FIELDS = (
    "request_id",
    "operation",
    "formula",
    "input_evidence_ids",
    "normalized_inputs",
    "result",
    "metric_id",
    "company",
    "fiscal_period",
    "unit",
    "currency",
    "rounding_policy",
)


class DerivedCalculation(BaseModel):
    """Arithmetic result with a complete ordered set of source evidence IDs."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    calculation_id: str = Field(pattern=r"^calc_[0-9a-f]{32}$")
    request_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    input_evidence_ids: tuple[str, ...] = Field(min_length=2)
    normalized_inputs: tuple[str, ...] = Field(min_length=2)
    result: Decimal
    metric_id: str = Field(min_length=1)
    company: str | None = None
    fiscal_period: str | None = None
    unit: str | None = None
    currency: str | None = None
    rounding_policy: str = Field(min_length=1)
    validation_status: CalculationValidationStatus = CalculationValidationStatus.PENDING
    task_id: str | None = None
    task_ids: tuple[str, ...] = ()
    requirement_ids: tuple[str, ...] = ()
    discovered_by: tuple[str, ...] = Field(default=("financial_reasoner",), min_length=1)

    @classmethod
    def create(cls, **values: Any) -> "DerivedCalculation":
        prepared = dict(values)
        prepared["input_evidence_ids"] = _tuple_values(
            prepared.get("input_evidence_ids")
        )
        prepared["normalized_inputs"] = tuple(
            str(value) for value in prepared.get("normalized_inputs", ())
        )
        prepared["requirement_ids"] = _tuple_values(
            prepared.get("requirement_ids"), sort=True
        )
        task_ids = set(_tuple_values(prepared.get("task_ids")))
        if prepared.get("task_id") is not None:
            task_ids.add(prepared["task_id"])
        prepared["task_ids"] = tuple(sorted(task_ids))
        prepared["task_id"] = prepared["task_ids"][0] if prepared["task_ids"] else None
        prepared["discovered_by"] = _tuple_values(
            prepared.get("discovered_by", ("financial_reasoner",)), sort=True
        ) or ("financial_reasoner",)
        if "validation_status" in prepared and not isinstance(
            prepared["validation_status"], CalculationValidationStatus
        ):
            prepared["validation_status"] = CalculationValidationStatus(
                prepared["validation_status"]
            )
        if not isinstance(prepared.get("result"), Decimal):
            prepared["result"] = Decimal(str(prepared["result"]))
        prepared["calculation_id"] = _stable_id("calc", _calculation_identity(prepared))
        return cls(**prepared)

    @model_validator(mode="after")
    def validate_calculation_identity(self) -> "DerivedCalculation":
        if self.calculation_id != _stable_id("calc", _calculation_identity(self)):
            raise ValueError("calculation_id does not match its inputs and result")
        if len(self.input_evidence_ids) != len(set(self.input_evidence_ids)):
            raise ValueError("calculation input evidence IDs must be unique")
        if len(self.normalized_inputs) != len(self.input_evidence_ids):
            raise ValueError("normalized_inputs must align one-to-one with input evidence IDs")
        if tuple(sorted(set(self.requirement_ids))) != self.requirement_ids:
            raise ValueError("calculation requirement_ids must be unique and sorted")
        if tuple(sorted(set(self.task_ids))) != self.task_ids:
            raise ValueError("calculation task_ids must be unique and sorted")
        if (self.task_ids[0] if self.task_ids else None) != self.task_id:
            raise ValueError("task_id must be the first canonical task_ids value")
        if tuple(sorted(set(self.discovered_by))) != self.discovered_by:
            raise ValueError("calculation discovered_by values must be unique and sorted")
        if not self.result.is_finite():
            raise ValueError("calculation results must be finite Decimals")
        return self


def _calculation_identity(
    calculation: DerivedCalculation | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(calculation, DerivedCalculation):
        return {field: getattr(calculation, field) for field in _CALCULATION_ID_FIELDS}
    return {field: calculation.get(field) for field in _CALCULATION_ID_FIELDS}


class GeneratedClaim(BaseModel):
    """A report claim that references ledger evidence and optional arithmetic."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    claim_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    claim_text: str = Field(min_length=1, max_length=4_000)
    claim_type: str = Field(min_length=1)
    supporting_evidence_ids: tuple[str, ...] = ()
    calculation_id: str | None = None
    requirement_ids: tuple[str, ...] = ()
    verification_status: ClaimStatus | None = None

    @classmethod
    def create(
        cls,
        *,
        claim_text: str,
        claim_type: str,
        request_id: str,
        supporting_evidence_ids: tuple[str, ...] = (),
        calculation_id: str | None = None,
        requirement_ids: tuple[str, ...] = (),
        claim_id: str | None = None,
    ) -> "GeneratedClaim":
        evidence_ids = _tuple_values(supporting_evidence_ids, sort=True)
        requirement_ids = _tuple_values(requirement_ids, sort=True)
        identity = {
            "request_id": request_id,
            "claim_text": claim_text,
            "claim_type": claim_type,
            "supporting_evidence_ids": evidence_ids,
            "calculation_id": calculation_id,
        }
        return cls(
            claim_id=claim_id or _stable_id("claim", identity),
            request_id=request_id,
            claim_text=claim_text,
            claim_type=claim_type,
            supporting_evidence_ids=evidence_ids,
            calculation_id=calculation_id,
            requirement_ids=requirement_ids,
        )

    @model_validator(mode="after")
    def validate_claim_references(self) -> "GeneratedClaim":
        if tuple(sorted(set(self.supporting_evidence_ids))) != self.supporting_evidence_ids:
            raise ValueError("claim evidence IDs must be unique and sorted")
        if tuple(sorted(set(self.requirement_ids))) != self.requirement_ids:
            raise ValueError("claim requirement IDs must be unique and sorted")
        return self


class VerificationRecord(BaseModel):
    """Versioned final verification output linked to the claim assessments."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    verification_id: str = Field(pattern=r"^ver_[0-9a-f]{32}$")
    request_id: str = Field(min_length=1)
    verifier_id: str = Field(min_length=1)
    verifier_version: str = Field(min_length=1)
    result: VerificationResult

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        verifier_id: str,
        verifier_version: str,
        result: VerificationResult,
    ) -> "VerificationRecord":
        payload = {
            "request_id": request_id,
            "verifier_id": verifier_id,
            "verifier_version": verifier_version,
            "result": result,
        }
        return cls(verification_id=_stable_id("ver", payload), **payload)

    @model_validator(mode="after")
    def validate_verification_identity(self) -> "VerificationRecord":
        expected = _stable_id("ver", {
            "request_id": self.request_id,
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "result": self.result,
        })
        if self.verification_id != expected:
            raise ValueError("verification_id does not match the verifier result")
        return self


class LedgerSnapshot(BaseModel):
    """Immutable, deterministically ordered view of one request's ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    request_id: str = Field(min_length=1)
    question_requirements: QuestionRequirements | None = None
    research_plans: tuple[ResearchPlan, ...] = ()
    tasks: tuple[ResearchTask, ...] = ()
    evidence_records: tuple[EvidenceRecord, ...] = ()
    financial_facts: tuple[FinancialFact, ...] = ()
    calculations: tuple[DerivedCalculation, ...] = ()
    claims: tuple[GeneratedClaim, ...] = ()
    verifications: tuple[VerificationRecord, ...] = ()

    @model_validator(mode="after")
    def validate_request_graph(self) -> "LedgerSnapshot":
        reqs = {
            item.requirement_id
            for item in (self.question_requirements.evidence if self.question_requirements else ())
        }
        tasks = {item.task_id: item for item in self.tasks}
        evidence = {item.evidence_id: item for item in self.evidence_records}
        facts = {item.fact_id: item for item in self.financial_facts}
        calculations = {item.calculation_id: item for item in self.calculations}
        claims = {item.claim_id: item for item in self.claims}
        if len(tasks) != len(self.tasks) or len(evidence) != len(self.evidence_records):
            raise ValueError("ledger task and evidence IDs must be unique")
        if len(facts) != len(self.financial_facts) or len(calculations) != len(self.calculations):
            raise ValueError("ledger fact and calculation IDs must be unique")
        if len(claims) != len(self.claims):
            raise ValueError("ledger claim IDs must be unique")
        for task in self.tasks:
            if not set(task.requirement_ids).issubset(reqs):
                raise ValueError("research task references an unknown question requirement")
        for plan in self.research_plans:
            if self.question_requirements is not None and plan.question != self.question_requirements.question:
                raise ValueError("research plan question does not match ledger requirements")
            for task in plan.tasks:
                if task.task_id not in tasks or tasks[task.task_id] != task:
                    raise ValueError("research plan task is missing from the ledger task set")
        for record in self.evidence_records:
            if record.request_id != self.request_id:
                raise ValueError("evidence record belongs to another request")
            if not set(record.task_ids).issubset(tasks):
                raise ValueError("evidence record references an unknown research task")
            assigned_requirements = {
                requirement_id
                for task_id in record.task_ids
                for requirement_id in tasks[task_id].requirement_ids
            }
            if not set(record.requirement_ids).issubset(assigned_requirements):
                raise ValueError("evidence record requirement is not assigned to its task links")
            if not set(record.requirement_ids).issubset(reqs):
                raise ValueError("evidence record references an unknown requirement")
            if not set(record.derived_from_evidence_ids).issubset(evidence):
                raise ValueError("derived fact references missing input evidence")
            if record.calculation_id is not None and record.calculation_id not in calculations:
                raise ValueError("derived fact references an unknown calculation")
            if record.calculation_id is not None and (
                record.derived_from_evidence_ids
                != calculations[record.calculation_id].input_evidence_ids
            ):
                raise ValueError("derived fact must preserve every calculation input evidence ID")
        for fact in self.financial_facts:
            if fact.request_id != self.request_id or not set(fact.evidence_ids).issubset(evidence):
                raise ValueError("financial fact has missing or cross-request evidence")
            if not set(fact.requirement_ids).issubset(reqs):
                raise ValueError("financial fact references an unknown requirement")
        for calculation in self.calculations:
            if calculation.request_id != self.request_id:
                raise ValueError("calculation belongs to another request")
            if not set(calculation.input_evidence_ids).issubset(evidence):
                raise ValueError("calculation references missing input evidence")
            if not set(calculation.task_ids).issubset(tasks):
                raise ValueError("calculation references an unknown research task")
            assigned_requirements = {
                requirement_id
                for task_id in calculation.task_ids
                for requirement_id in tasks[task_id].requirement_ids
            }
            if not set(calculation.requirement_ids).issubset(assigned_requirements):
                raise ValueError("calculation requirement is not assigned to its task links")
            if not set(calculation.requirement_ids).issubset(reqs):
                raise ValueError("calculation references an unknown requirement")
        for claim in self.claims:
            if claim.request_id != self.request_id:
                raise ValueError("claim belongs to another request")
            if not set(claim.supporting_evidence_ids).issubset(evidence):
                raise ValueError("claim references missing supporting evidence")
            if claim.calculation_id is not None and claim.calculation_id not in calculations:
                raise ValueError("claim references an unknown calculation")
            if not set(claim.requirement_ids).issubset(reqs):
                raise ValueError("claim references an unknown requirement")
        for verification in self.verifications:
            if verification.request_id != self.request_id:
                raise ValueError("verification belongs to another request")
            for assessment in verification.result.claims:
                if assessment.claim_id not in claims:
                    raise ValueError("verification references an unknown generated claim")
                if not set(assessment.evidence_ids).issubset(evidence):
                    raise ValueError("verification references missing evidence")
                if not set(assessment.evidence_ids).issubset(
                    claims[assessment.claim_id].supporting_evidence_ids
                ):
                    raise ValueError("verification cites evidence not linked to its generated claim")
        observed_statuses: dict[str, list[ClaimStatus]] = {
            claim_id: [] for claim_id in claims
        }
        for verification in self.verifications:
            for assessment in verification.result.claims:
                observed_statuses[assessment.claim_id].append(assessment.status)
        for claim_id, claim in claims.items():
            statuses = observed_statuses[claim_id]
            expected_status = (
                max(statuses, key=lambda item: _CLAIM_VERIFICATION_PRIORITY[item])
                if statuses
                else None
            )
            if claim.verification_status != expected_status:
                raise ValueError("claim verification_status does not match linked verification results")
        return self


def _sorted_observations(
    observations: tuple[RetrievalObservation, ...],
) -> tuple[RetrievalObservation, ...]:
    unique = {(item.method, item.rank): item for item in observations}
    return tuple(sorted(unique.values(), key=lambda item: (item.rank is None, item.rank or 0, item.method)))


def _best_observation(
    observations: tuple[RetrievalObservation, ...],
) -> RetrievalObservation | None:
    return observations[0] if observations else None


__all__ = [
    "CalculationValidationStatus",
    "DerivedCalculation",
    "EvidenceRecord",
    "EvidenceSourceType",
    "EvidenceStatus",
    "FinancialFact",
    "GeneratedClaim",
    "LedgerSnapshot",
    "RetrievalObservation",
    "VerificationRecord",
]
