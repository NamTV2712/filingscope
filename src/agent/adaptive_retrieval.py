"""Bounded targeted retrieval controlled by evidence gaps.

The controller applies the source Agent's tested bounded-research patterns:
fingerprinted tool requests, an evidence ledger keyed by source identity,
finite attempts, and explicit no-progress outcomes. It uses FilingScope's
migrated ``HybridRetriever.retrieve`` as the search tool and the P2 decision
layer as its only completion policy.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.decision.models import (
    DecisionAction,
    DecisionBudget,
    DecisionResult,
    EvidenceRequirement,
)
from src.decision.policy import EvidenceDecisionLayer
from src.ingestion.chunker import count_tokens


class RetrievalTool(Protocol):
    """The narrow synchronous tool contract implemented by HybridRetriever."""

    def retrieve(self, query: str, top_k: int = 5) -> Sequence[Any]: ...


class AdaptiveStopReason(StrEnum):
    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    UNSUPPORTED_QUESTION = "unsupported_question"
    RETRIEVAL_BUDGET_EXHAUSTED = "retrieval_budget_exhausted"
    QUERY_BUDGET_EXHAUSTED = "query_budget_exhausted"
    TIME_BUDGET_EXHAUSTED = "time_budget_exhausted"
    EVIDENCE_TOKEN_BUDGET_EXHAUSTED = "evidence_token_budget_exhausted"
    NO_PROGRESS = "no_progress"
    NO_TARGETED_QUERY = "no_targeted_query"
    RETRIEVAL_ERROR = "retrieval_error"


class AdaptiveRetrievalBudget(BaseModel):
    """Hard bounds for one in-memory adaptive retrieval run."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    max_rounds: int = Field(default=3, ge=0, le=8)
    max_queries: int = Field(default=6, ge=0, le=16)
    max_evidence_tokens: int = Field(default=16000, ge=1, le=100000)
    time_budget_seconds: float = Field(default=30.0, gt=0, le=300, allow_inf_nan=False)
    top_k: int = Field(default=5, ge=1, le=10)


class AdaptiveRetrievalTrace(BaseModel):
    """One target query attempt, without storing retrieved source text."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    round_index: int = Field(ge=1, le=8)
    query_index: int = Field(ge=1, le=16)
    query: str = Field(min_length=1, max_length=512)
    query_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirement_ids: tuple[str, ...] = Field(max_length=16)
    retrieved_count: int = Field(ge=0)
    added_chunk_ids: tuple[str, ...] = Field(max_length=50)
    unresolved_before: tuple[str, ...] = Field(max_length=32)
    unresolved_after: tuple[str, ...] = Field(max_length=32)
    evidence_tokens_used: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0, allow_inf_nan=False)
    outcome: Literal[
        "progress",
        "no_progress",
        "duplicate_query",
        "token_budget_exhausted",
        "time_budget_exhausted",
        "retrieval_error",
    ]
    error_type: str | None = Field(default=None, max_length=80)


class AdaptiveRetrievalResult(BaseModel):
    """Final decision, retained evidence, resource usage, and audit trace."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    question: str
    initial_decision: DecisionResult
    final_decision: DecisionResult
    evidence_chunks: tuple[dict[str, Any], ...]
    trace: tuple[AdaptiveRetrievalTrace, ...]
    stop_reason: AdaptiveStopReason
    queries_used: int = Field(ge=0, le=16)
    rounds_used: int = Field(ge=0, le=8)
    evidence_tokens_used: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0, allow_inf_nan=False)


def _as_mapping(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, Mapping):
        return dict(chunk)
    if is_dataclass(chunk):
        return asdict(chunk)
    if hasattr(chunk, "model_dump"):
        return chunk.model_dump()
    if hasattr(chunk, "__dict__"):
        return dict(vars(chunk))
    raise TypeError("Retrieved evidence must be a mapping or structured object")


def _fingerprint(query: str) -> str:
    normalized = " ".join(query.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _chunk_identity(chunk: Mapping[str, Any]) -> tuple[str, str]:
    chunk_id = chunk.get("chunk_id")
    if not isinstance(chunk_id, str) or not chunk_id.strip():
        raise ValueError("Retrieved chunk is missing a stable chunk_id")
    document_id = chunk.get("document_id") or chunk.get("doc_name") or ""
    return str(document_id), chunk_id.strip()


def _chunk_token_count(chunk: Mapping[str, Any]) -> int:
    stored = chunk.get("token_count")
    text = chunk.get("text")
    if (
        isinstance(stored, int)
        and not isinstance(stored, bool)
        and stored >= 0
        and (stored > 0 or not isinstance(text, str) or not text)
    ):
        return stored
    return count_tokens(text) if isinstance(text, str) else 0


def _unresolved(decision: DecisionResult) -> tuple[str, ...]:
    coverage = decision.coverage
    return tuple(sorted(set((
        *coverage.missing_requirement_ids,
        *coverage.conflicted_requirement_ids,
        *coverage.operation_gaps,
    ))))


def _has_coverage_progress(before: DecisionResult, after: DecisionResult) -> bool:
    if after.action == DecisionAction.ANSWER:
        return True
    previous = before.coverage
    current = after.coverage
    previous_requirement_gaps = (
        len(previous.missing_requirement_ids)
        + len(previous.conflicted_requirement_ids)
    )
    current_requirement_gaps = (
        len(current.missing_requirement_ids)
        + len(current.conflicted_requirement_ids)
    )
    return (
        current_requirement_gaps < previous_requirement_gaps
        or len(current.operation_gaps) < len(previous.operation_gaps)
    )


def _query_candidates(
    decision: DecisionResult,
) -> tuple[tuple[EvidenceRequirement, str | None], ...]:
    """Build deterministic query targets from current gaps, in slot order."""
    coverage = decision.coverage
    requirements = coverage.requirements
    by_id = {item.requirement_id: item for item in requirements.evidence}
    target_ids = list(dict.fromkeys((
        *coverage.missing_requirement_ids,
        *coverage.conflicted_requirement_ids,
    )))

    targeted: list[tuple[EvidenceRequirement, str | None]] = [
        (by_id[item], None) for item in target_ids if item in by_id
    ]

    for gap in coverage.operation_gaps:
        operation_name = gap.split(":", 1)[0]
        operation = next(
            (item for item in requirements.operations if item.operation == operation_name),
            None,
        )
        if operation is None:
            continue
        operation_slots = [
            item for item in requirements.evidence
            if operation.metric_id is None or item.metric_id == operation.metric_id
        ]
        targeted.extend((item, gap) for item in operation_slots)

    seen: set[tuple[str, str | None]] = set()
    result: list[tuple[EvidenceRequirement, str | None]] = []
    for requirement, gap in targeted:
        key = (requirement.requirement_id, gap)
        if key not in seen:
            seen.add(key)
            result.append((requirement, gap))
    return tuple(result)


def _target_query(
    question: str,
    decision: DecisionResult,
    requirement: EvidenceRequirement,
    operation_gap: str | None,
) -> str:
    requirements = decision.coverage.requirements
    entity = next(item for item in requirements.entities if item.entity_id == requirement.entity_id)
    metric = next(item for item in requirements.metrics if item.metric_id == requirement.metric_id)
    terms = [entity.canonical_name, metric.display_name]
    if requirement.period:
        terms.append(requirement.period)
    else:
        terms.append("fiscal period values")
    if operation_gap and ("unit" in operation_gap or "currency" in operation_gap):
        terms.extend(("financial statement", "reporting currency scale"))
    if operation_gap and "period" in operation_gap:
        terms.append("aligned fiscal periods")
    terms.extend(("question context:", question.strip()))
    query = " ".join(" ".join(terms).split())
    return query[:512].rstrip()


class AdaptiveRetrievalController:
    """Reassess targeted retrieval until evidence is sufficient or a bound stops it."""

    def __init__(
        self,
        retriever: RetrievalTool,
        *,
        decision_layer: EvidenceDecisionLayer | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.retriever = retriever
        self.decision_layer = decision_layer or EvidenceDecisionLayer()
        self.clock = clock

    def run(
        self,
        question: str,
        initial_chunks: Iterable[Any] = (),
        *,
        budget: AdaptiveRetrievalBudget | None = None,
    ) -> AdaptiveRetrievalResult:
        limits = budget or AdaptiveRetrievalBudget()
        started = self.clock()
        deadline = started + limits.time_budget_seconds
        chunks: list[dict[str, Any]] = []
        identities: set[tuple[str, str]] = set()
        token_total = 0
        for raw in initial_chunks:
            record = _as_mapping(raw)
            identity = _chunk_identity(record)
            if identity in identities:
                continue
            identities.add(identity)
            chunks.append(record)
            token_total += _chunk_token_count(record)

        initial_decision = self.decision_layer.decide(
            question,
            chunks,
            budget=DecisionBudget(remaining_retrieval_attempts=limits.max_rounds),
        )
        decision = initial_decision
        trace: list[AdaptiveRetrievalTrace] = []
        seen_queries: set[str] = set()
        queries_used = rounds_used = 0
        stop_reason: AdaptiveStopReason | None = None

        if decision.action == DecisionAction.ANSWER:
            stop_reason = AdaptiveStopReason.EVIDENCE_SUFFICIENT
        elif not decision.coverage.requirements.supported:
            stop_reason = AdaptiveStopReason.UNSUPPORTED_QUESTION
        elif token_total >= limits.max_evidence_tokens:
            stop_reason = AdaptiveStopReason.EVIDENCE_TOKEN_BUDGET_EXHAUSTED
            decision = self._exhausted_decision(question, chunks)
        elif limits.max_rounds == 0:
            stop_reason = AdaptiveStopReason.RETRIEVAL_BUDGET_EXHAUSTED
        elif limits.max_queries == 0:
            stop_reason = AdaptiveStopReason.QUERY_BUDGET_EXHAUSTED
            decision = self._exhausted_decision(question, chunks)

        for round_index in range(1, limits.max_rounds + 1):
            if stop_reason is not None:
                break
            if decision.action != DecisionAction.RETRIEVE_MORE:
                stop_reason = (
                    AdaptiveStopReason.UNSUPPORTED_QUESTION
                    if not decision.coverage.requirements.supported
                    else AdaptiveStopReason.RETRIEVAL_BUDGET_EXHAUSTED
                )
                break
            if queries_used >= limits.max_queries:
                stop_reason = AdaptiveStopReason.QUERY_BUDGET_EXHAUSTED
                decision = self._exhausted_decision(question, chunks)
                break
            if self.clock() >= deadline:
                stop_reason = AdaptiveStopReason.TIME_BUDGET_EXHAUSTED
                decision = self._exhausted_decision(question, chunks)
                break

            candidates = _query_candidates(decision)
            if not candidates:
                stop_reason = AdaptiveStopReason.NO_TARGETED_QUERY
                decision = self._exhausted_decision(question, chunks)
                break
            decision_before = decision
            before = _unresolved(decision_before)
            selected: tuple[EvidenceRequirement, str | None, str, str] | None = None
            for requirement, operation_gap in candidates:
                query = _target_query(question, decision, requirement, operation_gap)
                signature = _fingerprint(query)
                if signature not in seen_queries:
                    selected = (requirement, operation_gap, query, signature)
                    break
            if selected is None:
                requirement, operation_gap = candidates[0]
                query = _target_query(question, decision, requirement, operation_gap)
                signature = _fingerprint(query)
                trace.append(AdaptiveRetrievalTrace(
                    round_index=round_index,
                    query_index=queries_used + 1,
                    query=query,
                    query_fingerprint=signature,
                    requirement_ids=(requirement.requirement_id,),
                    retrieved_count=0,
                    added_chunk_ids=(),
                    unresolved_before=before[:32],
                    unresolved_after=before[:32],
                    evidence_tokens_used=token_total,
                    elapsed_ms=max(0.0, (self.clock() - started) * 1000),
                    outcome="duplicate_query",
                ))
                stop_reason = AdaptiveStopReason.NO_PROGRESS
                decision = self._exhausted_decision(question, chunks)
                break

            requirement, operation_gap, query, signature = selected
            seen_queries.add(signature)
            rounds_used += 1
            try:
                retrieved = list(self.retriever.retrieve(query, top_k=limits.top_k))
                retrieved_records = [_as_mapping(item) for item in retrieved]
                # Validate identities before mutating the evidence ledger.
                new_records = [
                    (record, _chunk_identity(record)) for record in retrieved_records
                ]
            except Exception as error:
                trace.append(AdaptiveRetrievalTrace(
                    round_index=round_index,
                    query_index=queries_used + 1,
                    query=query,
                    query_fingerprint=signature,
                    requirement_ids=(requirement.requirement_id,),
                    retrieved_count=0,
                    added_chunk_ids=(),
                    unresolved_before=before[:32],
                    unresolved_after=before[:32],
                    evidence_tokens_used=token_total,
                    elapsed_ms=max(0.0, (self.clock() - started) * 1000),
                    outcome="retrieval_error",
                    error_type=type(error).__name__,
                ))
                queries_used += 1
                stop_reason = AdaptiveStopReason.RETRIEVAL_ERROR
                decision = self._exhausted_decision(question, chunks)
                break

            queries_used += 1
            added_ids: list[str] = []
            token_budget_hit = False
            for record, identity in new_records:
                if identity in identities:
                    continue
                record_tokens = _chunk_token_count(record)
                if token_total + record_tokens > limits.max_evidence_tokens:
                    token_budget_hit = True
                    continue
                identities.add(identity)
                chunks.append(record)
                token_total += record_tokens
                added_ids.append(identity[1])

            remaining_attempts = max(0, limits.max_rounds - round_index)
            decision = self.decision_layer.decide(
                question,
                chunks,
                budget=DecisionBudget(remaining_retrieval_attempts=remaining_attempts),
            )
            after = _unresolved(decision)
            progressed = _has_coverage_progress(decision_before, decision)
            elapsed_ms = max(0.0, (self.clock() - started) * 1000)
            past_deadline = self.clock() >= deadline
            outcome = (
                "progress" if decision.action == DecisionAction.ANSWER else
                "token_budget_exhausted" if token_budget_hit else
                "time_budget_exhausted" if past_deadline else
                "progress" if progressed else "no_progress"
            )
            trace.append(AdaptiveRetrievalTrace(
                round_index=round_index,
                query_index=queries_used,
                query=query,
                query_fingerprint=signature,
                requirement_ids=(requirement.requirement_id,),
                retrieved_count=len(retrieved_records),
                added_chunk_ids=tuple(added_ids),
                unresolved_before=before[:32],
                unresolved_after=after[:32],
                evidence_tokens_used=token_total,
                elapsed_ms=elapsed_ms,
                outcome=outcome,
            ))

            if decision.action == DecisionAction.ANSWER:
                stop_reason = AdaptiveStopReason.EVIDENCE_SUFFICIENT
                break
            if token_budget_hit:
                stop_reason = AdaptiveStopReason.EVIDENCE_TOKEN_BUDGET_EXHAUSTED
                decision = self._exhausted_decision(question, chunks)
                break
            if past_deadline:
                stop_reason = AdaptiveStopReason.TIME_BUDGET_EXHAUSTED
                decision = self._exhausted_decision(question, chunks)
                break
            if not progressed:
                stop_reason = AdaptiveStopReason.NO_PROGRESS
                decision = self._exhausted_decision(question, chunks)
                break
            if decision.action == DecisionAction.ABSTAIN:
                stop_reason = AdaptiveStopReason.RETRIEVAL_BUDGET_EXHAUSTED
                break

        if stop_reason is None:
            stop_reason = AdaptiveStopReason.RETRIEVAL_BUDGET_EXHAUSTED
            decision = self._exhausted_decision(question, chunks)

        return AdaptiveRetrievalResult(
            question=question,
            initial_decision=initial_decision,
            final_decision=decision,
            evidence_chunks=tuple(chunks),
            trace=tuple(trace),
            stop_reason=stop_reason,
            queries_used=queries_used,
            rounds_used=rounds_used,
            evidence_tokens_used=token_total,
            elapsed_ms=max(0.0, (self.clock() - started) * 1000),
        )

    def _exhausted_decision(
        self,
        question: str,
        chunks: Sequence[Mapping[str, Any]],
    ) -> DecisionResult:
        return self.decision_layer.decide(
            question,
            chunks,
            budget=DecisionBudget(remaining_retrieval_attempts=0),
        )
