"""In-memory, request-scoped blackboard with deterministic merge semantics."""

from __future__ import annotations

import hashlib
import json
from threading import RLock
from typing import Iterable

from src.decision.models import QuestionRequirements
from src.research.planner import ResearchPlan, ResearchTask
from src.verification.models import ClaimStatus, VerificationResult
from src.ledger.models import (
    CalculationValidationStatus,
    DerivedCalculation,
    EvidenceRecord,
    EvidenceSourceType,
    EvidenceStatus,
    FinancialFact,
    GeneratedClaim,
    LedgerSnapshot,
    RetrievalObservation,
    VerificationRecord,
    _calculation_identity,
    _canonical,
    _evidence_identity,
    _fact_identity,
)


class LedgerConflictError(ValueError):
    """Raised when one stable ledger ID is presented with incompatible data."""


class LedgerReferenceError(ValueError):
    """Raised when an artifact refers to a missing or cross-request record."""


_EVIDENCE_STATUS_PRIORITY = {
    EvidenceStatus.CURRENT: 0,
    EvidenceStatus.UNKNOWN: 1,
    EvidenceStatus.CONFLICTED: 2,
    EvidenceStatus.SUPERSEDED: 3,
}
_CALCULATION_STATUS_PRIORITY = {
    CalculationValidationStatus.VALID: 0,
    CalculationValidationStatus.PENDING: 1,
    CalculationValidationStatus.UNVERIFIABLE: 2,
    CalculationValidationStatus.MISMATCH: 3,
}
_CLAIM_STATUS_PRIORITY = {
    ClaimStatus.SUPPORTED: 0,
    ClaimStatus.PARTIALLY_SUPPORTED: 1,
    ClaimStatus.UNVERIFIABLE: 2,
    ClaimStatus.UNSUPPORTED: 3,
    ClaimStatus.CONTRADICTED: 4,
}


class EvidenceLedger:
    """Mutable request-scoped ledger; snapshots are immutable and sorted.

    Every mutation is protected by a reentrant lock. ``merge`` stages all
    relationships in a clone and only swaps the completed result into place,
    so a bad reference or conflicting stable ID cannot leave a partial merge.
    """

    def __init__(self, request_id: str):
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id must be a non-empty string")
        self.request_id = request_id
        self._lock = RLock()
        self._question_requirements: QuestionRequirements | None = None
        self._research_plans: dict[str, ResearchPlan] = {}
        self._tasks: dict[str, ResearchTask] = {}
        self._evidence: dict[str, EvidenceRecord] = {}
        self._facts: dict[str, FinancialFact] = {}
        self._calculations: dict[str, DerivedCalculation] = {}
        self._claims: dict[str, GeneratedClaim] = {}
        self._verifications: dict[str, VerificationRecord] = {}

    def register_requirements(self, requirements: QuestionRequirements) -> None:
        with self._lock:
            if self._question_requirements is None:
                self._question_requirements = requirements
            elif self._question_requirements != requirements:
                raise LedgerConflictError("request has conflicting question requirements")

    def register_plan(self, plan: ResearchPlan) -> None:
        with self._lock:
            self._validate_plan(plan)
            self._register_tasks_unlocked(plan.tasks)
            key = _plan_id(self.request_id, plan)
            existing = self._research_plans.get(key)
            if existing is not None and existing != plan:
                raise LedgerConflictError(f"research plan ID collision: {key}")
            self._research_plans[key] = plan

    def register_tasks(self, tasks: Iterable[ResearchTask]) -> None:
        with self._lock:
            self._register_tasks_unlocked(tuple(tasks))

    def add_evidence(self, record: EvidenceRecord) -> EvidenceRecord:
        with self._lock:
            return self._add_evidence_unlocked(record)

    def add_fact(self, fact: FinancialFact) -> FinancialFact:
        with self._lock:
            return self._add_fact_unlocked(fact)

    def add_calculation(self, calculation: DerivedCalculation) -> EvidenceRecord:
        """Store a calculation and its linked ``DERIVED_FACT`` record."""
        with self._lock:
            return self._add_calculation_unlocked(calculation)

    def add_claim(self, claim: GeneratedClaim) -> GeneratedClaim:
        with self._lock:
            return self._add_claim_unlocked(claim)

    def add_verification(
        self,
        result: VerificationResult,
        *,
        verifier_id: str,
        verifier_version: str,
    ) -> VerificationRecord:
        record = VerificationRecord.create(
            request_id=self.request_id,
            verifier_id=verifier_id,
            verifier_version=verifier_version,
            result=result,
        )
        with self._lock:
            return self._add_verification_unlocked(record)

    def evidence(self, evidence_id: str) -> EvidenceRecord:
        with self._lock:
            try:
                return self._evidence[evidence_id]
            except KeyError as error:
                raise LedgerReferenceError(f"unknown evidence ID: {evidence_id}") from error

    def snapshot(self) -> LedgerSnapshot:
        with self._lock:
            return LedgerSnapshot(
                request_id=self.request_id,
                question_requirements=self._question_requirements,
                research_plans=tuple(
                    self._research_plans[key] for key in sorted(self._research_plans)
                ),
                tasks=tuple(self._tasks[key] for key in sorted(self._tasks)),
                evidence_records=tuple(self._evidence[key] for key in sorted(self._evidence)),
                financial_facts=tuple(self._facts[key] for key in sorted(self._facts)),
                calculations=tuple(
                    self._calculations[key] for key in sorted(self._calculations)
                ),
                claims=tuple(self._claims[key] for key in sorted(self._claims)),
                verifications=tuple(
                    self._verifications[key] for key in sorted(self._verifications)
                ),
            )

    def merge(self, source: "EvidenceLedger | LedgerSnapshot") -> LedgerSnapshot:
        """Atomically merge a worker ledger/snapshot and return the new view.

        Re-merging an identical snapshot is idempotent. Duplicate source
        records are coalesced by stable evidence ID; incompatible data using
        the same task, fact, calculation, claim, or verification ID fails.
        """
        incoming = source.snapshot() if isinstance(source, EvidenceLedger) else source
        if incoming.request_id != self.request_id:
            raise LedgerReferenceError("cannot merge records from a different request")
        with self._lock:
            staged = EvidenceLedger(self.request_id)
            staged._merge_snapshot_unlocked(self._snapshot_unlocked())
            staged._merge_snapshot_unlocked(incoming)
            self._copy_state_unlocked(staged)
            return self._snapshot_unlocked()

    @classmethod
    def from_snapshot(cls, snapshot: LedgerSnapshot) -> "EvidenceLedger":
        ledger = cls(snapshot.request_id)
        with ledger._lock:
            ledger._merge_snapshot_unlocked(snapshot)
        return ledger

    def _snapshot_unlocked(self) -> LedgerSnapshot:
        return LedgerSnapshot(
            request_id=self.request_id,
            question_requirements=self._question_requirements,
            research_plans=tuple(self._research_plans[key] for key in sorted(self._research_plans)),
            tasks=tuple(self._tasks[key] for key in sorted(self._tasks)),
            evidence_records=tuple(self._evidence[key] for key in sorted(self._evidence)),
            financial_facts=tuple(self._facts[key] for key in sorted(self._facts)),
            calculations=tuple(self._calculations[key] for key in sorted(self._calculations)),
            claims=tuple(self._claims[key] for key in sorted(self._claims)),
            verifications=tuple(self._verifications[key] for key in sorted(self._verifications)),
        )

    def _copy_state_unlocked(self, other: "EvidenceLedger") -> None:
        self._question_requirements = other._question_requirements
        self._research_plans = other._research_plans
        self._tasks = other._tasks
        self._evidence = other._evidence
        self._facts = other._facts
        self._calculations = other._calculations
        self._claims = other._claims
        self._verifications = other._verifications

    def _merge_snapshot_unlocked(self, snapshot: LedgerSnapshot) -> None:
        if snapshot.request_id != self.request_id:
            raise LedgerReferenceError("cannot merge records from a different request")
        if snapshot.question_requirements is not None:
            self.register_requirements(snapshot.question_requirements)
        for plan in snapshot.research_plans:
            self.register_plan(plan)
        self.register_tasks(snapshot.tasks)

        for record in snapshot.evidence_records:
            if record.source_type != EvidenceSourceType.DERIVED_FACT:
                self.add_evidence(record)

        pending = {item.calculation_id: item for item in snapshot.calculations}
        while pending:
            ready = [
                item
                for item in pending.values()
                if set(item.input_evidence_ids).issubset(self._evidence)
            ]
            if not ready:
                missing = sorted({
                    evidence_id
                    for item in pending.values()
                    for evidence_id in item.input_evidence_ids
                    if evidence_id not in self._evidence
                })
                raise LedgerReferenceError(
                    "calculation graph has missing or cyclic inputs: " + ", ".join(missing)
                )
            for calculation in sorted(ready, key=lambda item: item.calculation_id):
                self.add_calculation(calculation)
                pending.pop(calculation.calculation_id)

        for record in snapshot.evidence_records:
            if record.source_type == EvidenceSourceType.DERIVED_FACT:
                self.add_evidence(record)
        for fact in snapshot.financial_facts:
            self.add_fact(fact)
        for claim in snapshot.claims:
            self.add_claim(claim)
        for verification in snapshot.verifications:
            self._add_verification_unlocked(verification)

    def _validate_plan(self, plan: ResearchPlan) -> None:
        if self._question_requirements is None and any(
            task.requirement_ids for task in plan.tasks
        ):
            raise LedgerReferenceError("register question requirements before a linked research plan")
        if self._question_requirements is not None:
            if plan.question != self._question_requirements.question:
                raise LedgerReferenceError("research plan question does not match request requirements")
            known = {item.requirement_id for item in self._question_requirements.evidence}
            for task in plan.tasks:
                if not set(task.requirement_ids).issubset(known):
                    raise LedgerReferenceError("research plan references an unknown requirement")

    def _register_tasks_unlocked(self, tasks: tuple[ResearchTask, ...]) -> None:
        if self._question_requirements is None and any(task.requirement_ids for task in tasks):
            raise LedgerReferenceError("register question requirements before linked research tasks")
        known_requirements = (
            {item.requirement_id for item in self._question_requirements.evidence}
            if self._question_requirements is not None
            else set()
        )
        for task in sorted(tasks, key=lambda item: item.task_id):
            if self._question_requirements is not None and not set(task.requirement_ids).issubset(known_requirements):
                raise LedgerReferenceError("research task references an unknown requirement")
            existing = self._tasks.get(task.task_id)
            if existing is not None and existing != task:
                raise LedgerConflictError(f"conflicting research task ID: {task.task_id}")
            self._tasks[task.task_id] = task

    def _validate_request_and_requirements(
        self,
        request_id: str,
        requirement_ids: tuple[str, ...],
    ) -> None:
        if request_id != self.request_id:
            raise LedgerReferenceError("artifact belongs to another request")
        if requirement_ids:
            if self._question_requirements is None:
                raise LedgerReferenceError("register question requirements before linked artifacts")
            known = {item.requirement_id for item in self._question_requirements.evidence}
            unknown = set(requirement_ids) - known
            if unknown:
                raise LedgerReferenceError("unknown requirement IDs: " + ", ".join(sorted(unknown)))

    def _validate_task_link(
        self,
        task_id: str | None,
        task_ids: tuple[str, ...],
        requirement_ids: tuple[str, ...],
    ) -> None:
        linked_tasks = set(task_ids)
        if task_id is not None:
            linked_tasks.add(task_id)
        if not linked_tasks:
            return
        missing = sorted(item for item in linked_tasks if item not in self._tasks)
        if missing:
            raise LedgerReferenceError("unknown research tasks: " + ", ".join(missing))
        tasks = [self._tasks[item] for item in sorted(linked_tasks)]
        assigned = {requirement_id for task in tasks if task is not None for requirement_id in task.requirement_ids}
        if not set(requirement_ids).issubset(assigned):
            raise LedgerReferenceError("artifact requirements are not assigned to linked research tasks")

    def _add_evidence_unlocked(self, record: EvidenceRecord) -> EvidenceRecord:
        self._validate_request_and_requirements(record.request_id, record.requirement_ids)
        self._validate_task_link(record.task_id, record.task_ids, record.requirement_ids)
        missing_inputs = set(record.derived_from_evidence_ids) - self._evidence.keys()
        if missing_inputs:
            raise LedgerReferenceError(
                "evidence references missing inputs: " + ", ".join(sorted(missing_inputs))
            )
        if record.source_type == EvidenceSourceType.DERIVED_FACT:
            calculation = self._calculations.get(record.calculation_id or "")
            if calculation is None:
                raise LedgerReferenceError("derived evidence must reference a registered calculation")
            if record.derived_from_evidence_ids != calculation.input_evidence_ids:
                raise LedgerReferenceError("derived evidence must list every calculation input in order")
        current = self._evidence.get(record.evidence_id)
        if current is None:
            self._evidence[record.evidence_id] = record
        else:
            self._evidence[record.evidence_id] = _merge_evidence(current, record)
        return self._evidence[record.evidence_id]

    def _add_fact_unlocked(self, fact: FinancialFact) -> FinancialFact:
        self._validate_request_and_requirements(fact.request_id, fact.requirement_ids)
        missing = set(fact.evidence_ids) - self._evidence.keys()
        if missing:
            raise LedgerReferenceError("financial fact references missing evidence: " + ", ".join(sorted(missing)))
        current = self._facts.get(fact.fact_id)
        self._facts[fact.fact_id] = fact if current is None else _merge_fact(current, fact)
        return self._facts[fact.fact_id]

    def _add_calculation_unlocked(self, calculation: DerivedCalculation) -> EvidenceRecord:
        self._validate_request_and_requirements(calculation.request_id, calculation.requirement_ids)
        self._validate_task_link(
            calculation.task_id,
            calculation.task_ids,
            calculation.requirement_ids,
        )
        missing = set(calculation.input_evidence_ids) - self._evidence.keys()
        if missing:
            raise LedgerReferenceError("calculation references missing evidence: " + ", ".join(sorted(missing)))
        current = self._calculations.get(calculation.calculation_id)
        stored = calculation if current is None else _merge_calculation(current, calculation)
        self._calculations[stored.calculation_id] = stored
        record = EvidenceRecord.from_source(
            request_id=self.request_id,
            metric=stored.metric_id,
            metric_id=stored.metric_id,
            company=stored.company,
            fiscal_period=stored.fiscal_period,
            raw_value=str(stored.result),
            normalized_value=str(stored.result),
            unit=stored.unit,
            currency=stored.currency,
            source_type=EvidenceSourceType.DERIVED_FACT,
            discovered_by=stored.discovered_by,
            evidence_status=EvidenceStatus.UNKNOWN,
            task_id=stored.task_id,
            task_ids=stored.task_ids,
            requirement_ids=stored.requirement_ids,
            derived_from_evidence_ids=stored.input_evidence_ids,
            calculation_id=stored.calculation_id,
        )
        return self._add_evidence_unlocked(record)

    def _add_claim_unlocked(self, claim: GeneratedClaim) -> GeneratedClaim:
        self._validate_request_and_requirements(claim.request_id, claim.requirement_ids)
        missing = set(claim.linked_citation_ids) - self._evidence.keys()
        if missing:
            raise LedgerReferenceError("claim references missing evidence: " + ", ".join(sorted(missing)))
        if claim.calculation_id is not None and claim.calculation_id not in self._calculations:
            raise LedgerReferenceError(f"claim references unknown calculation: {claim.calculation_id}")
        current = self._claims.get(claim.claim_id)
        normalized = _claim_with_status(claim, None)
        if current is not None and _claim_with_status(current, None) != normalized:
            raise LedgerConflictError(f"conflicting generated claim ID: {claim.claim_id}")
        self._claims[claim.claim_id] = normalized if current is None else current
        self._refresh_claim_statuses_unlocked()
        return self._claims[claim.claim_id]

    def _add_verification_unlocked(self, record: VerificationRecord) -> VerificationRecord:
        if record.request_id != self.request_id:
            raise LedgerReferenceError("verification belongs to another request")
        for assessment in record.result.claims:
            claim = self._claims.get(assessment.claim_id)
            if claim is None:
                raise LedgerReferenceError(f"verification references unknown claim: {assessment.claim_id}")
            missing = set(assessment.evidence_ids) - self._evidence.keys()
            if missing:
                raise LedgerReferenceError("verification references missing evidence: " + ", ".join(sorted(missing)))
            if not set(assessment.evidence_ids).issubset(claim.linked_citation_ids):
                raise LedgerReferenceError("verification cites evidence not linked to its generated claim")
            if not set(assessment.supporting_evidence_ids).issubset(claim.supporting_evidence_ids):
                raise LedgerReferenceError("verification support is not linked to its generated claim")
        current = self._verifications.get(record.verification_id)
        if current is not None and current != record:
            raise LedgerConflictError(f"conflicting verification ID: {record.verification_id}")
        self._verifications[record.verification_id] = record
        self._refresh_claim_statuses_unlocked()
        return self._verifications[record.verification_id]

    def _refresh_claim_statuses_unlocked(self) -> None:
        observations: dict[str, list[ClaimStatus]] = {claim_id: [] for claim_id in self._claims}
        for record in self._verifications.values():
            for assessment in record.result.claims:
                if assessment.claim_id in observations:
                    observations[assessment.claim_id].append(assessment.status)
        for claim_id, claim in tuple(self._claims.items()):
            statuses = observations.get(claim_id, [])
            status = (
                max(statuses, key=lambda item: _CLAIM_STATUS_PRIORITY[item])
                if statuses
                else None
            )
            self._claims[claim_id] = _claim_with_status(claim, status)


def _plan_id(request_id: str, plan: ResearchPlan) -> str:
    payload = {"request_id": request_id, "plan": plan.model_dump(mode="json")}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _merge_evidence(left: EvidenceRecord, right: EvidenceRecord) -> EvidenceRecord:
    if _canonical(_evidence_identity(left)) != _canonical(_evidence_identity(right)):
        raise LedgerConflictError(f"conflicting evidence payload for stable ID: {left.evidence_id}")
    observations = _merge_observations(
        left.retrieval_observations,
        right.retrieval_observations,
    )
    best = observations[0] if observations else None
    evidence_status = max(
        (left.evidence_status, right.evidence_status),
        key=lambda item: _EVIDENCE_STATUS_PRIORITY[item],
    )
    values = left.model_dump(mode="python")
    values.update(
        retrieval_observations=observations,
        retrieval_method=best.method if best else None,
        retrieval_rank=best.rank if best else None,
        discovered_by=tuple(sorted(set(left.discovered_by) | set(right.discovered_by))),
        task_ids=tuple(sorted(set(left.task_ids) | set(right.task_ids))),
        task_id=min(set(left.task_ids) | set(right.task_ids), default=None),
        requirement_ids=tuple(sorted(set(left.requirement_ids) | set(right.requirement_ids))),
        evidence_status=evidence_status,
    )
    return EvidenceRecord.model_validate(values)


def _merge_observations(
    left: tuple[RetrievalObservation, ...],
    right: tuple[RetrievalObservation, ...],
) -> tuple[RetrievalObservation, ...]:
    unique = {(item.method, item.rank): item for item in (*left, *right)}
    return tuple(sorted(unique.values(), key=lambda item: (item.rank is None, item.rank or 0, item.method)))


def _merge_fact(left: FinancialFact, right: FinancialFact) -> FinancialFact:
    if _canonical(_fact_identity(left)) != _canonical(_fact_identity(right)):
        raise LedgerConflictError(f"conflicting financial fact ID: {left.fact_id}")
    values = left.model_dump(mode="python")
    values["evidence_ids"] = tuple(sorted(set(left.evidence_ids) | set(right.evidence_ids)))
    values["requirement_ids"] = tuple(sorted(set(left.requirement_ids) | set(right.requirement_ids)))
    return FinancialFact.model_validate(values)


def _merge_calculation(
    left: DerivedCalculation,
    right: DerivedCalculation,
) -> DerivedCalculation:
    if _canonical(_calculation_identity(left)) != _canonical(_calculation_identity(right)):
        raise LedgerConflictError(f"conflicting calculation ID: {left.calculation_id}")
    values = left.model_dump(mode="python")
    values["validation_status"] = max(
        (left.validation_status, right.validation_status),
        key=lambda item: _CALCULATION_STATUS_PRIORITY[item],
    )
    values["discovered_by"] = tuple(sorted(set(left.discovered_by) | set(right.discovered_by)))
    values["task_ids"] = tuple(sorted(set(left.task_ids) | set(right.task_ids)))
    values["task_id"] = min(set(left.task_ids) | set(right.task_ids), default=None)
    values["requirement_ids"] = tuple(sorted(set(left.requirement_ids) | set(right.requirement_ids)))
    return DerivedCalculation.model_validate(values)


def _claim_with_status(
    claim: GeneratedClaim,
    status: ClaimStatus | None,
) -> GeneratedClaim:
    values = claim.model_dump(mode="python")
    values["verification_status"] = status
    return GeneratedClaim.model_validate(values)


__all__ = [
    "EvidenceLedger",
    "LedgerConflictError",
    "LedgerReferenceError",
]
