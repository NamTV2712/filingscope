"""Bounded, evidence-ID-oriented specialist capabilities for M7."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.agent.complexity_router import RouteBudget
from src.decision.models import (
    DecisionBudget,
    DecisionResult,
    EvidenceCoverage,
    QuestionRequirements,
)
from src.decision.policy import EvidenceDecisionLayer
from src.generation.answer_generator import (
    AnswerGenerationResult,
    AnswerGenerator,
)
from src.ingestion.sec_client import SECEdgarClient
from src.ledger.evidence_ledger import EvidenceLedger
from src.ledger.models import (
    CalculationValidationStatus,
    DerivedCalculation,
    EvidenceRecord,
    EvidenceSourceType,
    FinancialFact,
    RetrievalObservation,
)
from src.research.planner import ResearchPlan, ResearchTask
from src.verification.claim_verifier import ClaimLevelVerifier
from src.verification.models import VerificationResult


class SpecialistStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    SKIPPED = "SKIPPED"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"


class SpecialistObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    key: str = Field(min_length=1)
    value: str = Field(min_length=1)


class SpecialistTaskResult(BaseModel):
    """Small worker receipt; source text remains in the request-local store."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    worker_id: str = Field(min_length=1)
    status: SpecialistStatus
    task_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    missing_requirement_ids: tuple[str, ...] = ()
    observations: tuple[SpecialistObservation, ...] = ()
    tool_calls: int = Field(default=0, ge=0)
    retrieval_calls: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    candidate_chunks: int = Field(default=0, ge=0)
    context_tokens: int = Field(default=0, ge=0)
    elapsed_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    error_code: str | None = None


class SpecialistTaskAssignment(BaseModel):
    """Explicit capability and budget packet for one independent worker."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    task_id: str = Field(min_length=1)
    task_ids: tuple[str, ...] = Field(min_length=1)
    objective: str = Field(min_length=1)
    allowed_tools: tuple[str, ...] = ()
    evidence_requirement_ids: tuple[str, ...] = ()
    budget: RouteBudget
    tasks: tuple[ResearchTask, ...] = Field(min_length=1)


class ChunkRetriever(Protocol):
    def retrieve(self, query: str, top_k: int = 5, **filters: Any) -> list[Any]: ...


class _RuntimeBudget:
    def __init__(self, budget: Any):
        self.budget = budget
        self.started = time.perf_counter()
        self.tool_calls = 0
        self.retrieval_calls = 0
        self.llm_calls = 0
        self.candidate_chunks = 0
        self.context_tokens = 0

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.perf_counter() - self.started)

    def can_start(self, *, tools: int = 1, retrieval: bool = False, llm: bool = False) -> bool:
        if self.elapsed_seconds >= self.budget.max_wall_time_seconds:
            return False
        if self.tool_calls + tools > self.budget.max_tool_calls:
            return False
        if retrieval and self.retrieval_calls >= self.budget.max_retrieval_calls:
            return False
        if llm and self.llm_calls >= self.budget.max_llm_calls:
            return False
        return True

    def charge(self, *, tools: int = 1, retrieval: bool = False, llm: bool = False) -> None:
        self.tool_calls += tools
        self.retrieval_calls += int(retrieval)
        self.llm_calls += int(llm)

    def remaining_candidates(self) -> int:
        return max(0, self.budget.max_candidate_chunks - self.candidate_chunks)


class _ParallelTaskTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = 0
        self._peak = 0

    def enter(self) -> None:
        with self._lock:
            self._active += 1
            self._peak = max(self._peak, self._active)

    def exit(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)

    @property
    def peak(self) -> int:
        with self._lock:
            return self._peak


@dataclass
class SpecialistRuntime:
    """Per-invocation dependencies and ephemeral source-text storage.

    LangGraph state contains identifiers and structured results. Retrieved text
    stays in this request-local runtime object and is materialized only for the
    bounded analyst, writer, and verifier calls that need it.
    """

    request_id: str
    ledger: EvidenceLedger
    budget: Any
    requirements: QuestionRequirements
    plan: ResearchPlan | None
    retriever: ChunkRetriever | None = None
    sec_client: SECEdgarClient | None = None
    ticker_by_company: dict[str, str] = field(default_factory=dict)
    generator: AnswerGenerator | None = None
    decision_layer: EvidenceDecisionLayer = field(default_factory=EvidenceDecisionLayer)
    verifier: ClaimLevelVerifier = field(default_factory=ClaimLevelVerifier)
    source_chunks: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence_id_by_chunk_id: dict[str, str] = field(default_factory=dict)
    chunk_tasks: dict[str, set[str]] = field(default_factory=dict)
    preferred_evidence_by_chunk_id: dict[str, str] = field(default_factory=dict)
    specialist_results: list[SpecialistTaskResult] = field(default_factory=list)
    coverage: EvidenceCoverage | None = None
    decision: DecisionResult | None = None
    generation: AnswerGenerationResult | None = None
    verification: VerificationResult | None = None
    calculations: list[DerivedCalculation] = field(default_factory=list)
    parallel_task_tracker: _ParallelTaskTracker = field(default_factory=_ParallelTaskTracker)
    effective_max_concurrency: int = 0
    parallel_task_count: int = 0
    deduplicated_query_count: int = 0
    duplicate_candidate_chunks: int = 0
    _pending_workers: dict[str, "SpecialistRuntime"] = field(default_factory=dict, init=False, repr=False)
    _artifact_lock: Any = field(default_factory=threading.Lock, init=False, repr=False)
    budget_tracker: _RuntimeBudget = field(init=False)
    registered: bool = False

    def __post_init__(self) -> None:
        self.budget_tracker = _RuntimeBudget(self.budget)

    def register_plan(self) -> None:
        if self.registered:
            return
        self.ledger.register_requirements(self.requirements)
        if self.plan is not None:
            self.ledger.register_plan(self.plan)
        self.registered = True

    def save_result(self, result: SpecialistTaskResult) -> None:
        self.specialist_results.append(result)

    def stage_retrieval_artifacts(self, assignment_id: str, worker: "SpecialistRuntime") -> None:
        with self._artifact_lock:
            self._pending_workers[assignment_id] = worker

    def take_retrieval_artifacts(self, assignment_id: str) -> "SpecialistRuntime":
        return self._pending_workers.pop(assignment_id)

    def merge_retrieval_artifacts(self, worker: "SpecialistRuntime") -> None:
        """Keep each selected chunk and its citation pointer together at fan-in."""
        for chunk_id, chunk in worker.source_chunks.items():
            if chunk_id not in self.source_chunks:
                self.source_chunks[chunk_id] = chunk
                self.evidence_id_by_chunk_id[chunk_id] = worker.evidence_id_by_chunk_id[chunk_id]
                self.preferred_evidence_by_chunk_id[chunk_id] = worker.preferred_evidence_by_chunk_id[chunk_id]
            self.chunk_tasks.setdefault(chunk_id, set()).update(worker.chunk_tasks[chunk_id])


class FilingResearchWorker:
    """Retrieve filing chunks and register stable source pointers in the ledger."""

    worker_id = "filing_research_worker"

    def run(self, tasks: tuple[ResearchTask, ...], runtime: SpecialistRuntime) -> SpecialistTaskResult:
        started = time.perf_counter()
        runtime.register_plan()
        evidence_ids: set[str] = set()
        task_ids: set[str] = set()
        missing: set[str] = set()
        observations: list[SpecialistObservation] = []
        retrieval_calls_before = runtime.budget_tracker.retrieval_calls
        tools_before = runtime.budget_tracker.tool_calls
        candidates_before = runtime.budget_tracker.candidate_chunks
        query_groups: dict[str, list[ResearchTask]] = {}
        for task in tasks:
            if task.query is None or task.source_availability.value == "MISSING":
                missing.update(task.requirement_ids)
                continue
            normalized_query = " ".join(task.query.casefold().split())
            query_groups.setdefault(normalized_query, []).append(task)

        if runtime.retriever is None:
            status = SpecialistStatus.UNKNOWN
            missing.update(requirement_id for task in tasks for requirement_id in task.requirement_ids)
            observations.append(SpecialistObservation(key="retrieval", value="retriever_not_configured"))
        else:
            for grouped_tasks in query_groups.values():
                if not runtime.budget_tracker.remaining_candidates():
                    missing.update(req for task in grouped_tasks for req in task.requirement_ids)
                    observations.append(SpecialistObservation(key="budget", value="candidate_limit_reached"))
                    continue
                if not runtime.budget_tracker.can_start(retrieval=True):
                    missing.update(req for task in grouped_tasks for req in task.requirement_ids)
                    observations.append(SpecialistObservation(key="budget", value="retrieval_or_tool_budget_reached"))
                    continue
                runtime.budget_tracker.charge(retrieval=True)
                top_k = min(10, runtime.budget_tracker.remaining_candidates())
                try:
                    found = runtime.retriever.retrieve(grouped_tasks[0].query or "", top_k=top_k)
                except Exception as error:  # report an adapter failure without hiding it
                    observations.append(SpecialistObservation(
                        key="retrieval_error",
                        value=type(error).__name__,
                    ))
                    missing.update(req for task in grouped_tasks for req in task.requirement_ids)
                    continue

                normalized = [_chunk_mapping(item) for item in found]
                normalized = [item for item in normalized if item.get("chunk_id")]
                deduplicated: dict[str, dict[str, Any]] = {}
                for item in normalized:
                    chunk_id = str(item["chunk_id"])
                    old = deduplicated.get(chunk_id)
                    if old is None or _score(item) > _score(old):
                        deduplicated[chunk_id] = item
                ordered = sorted(deduplicated.values(), key=lambda item: (-_score(item), str(item["chunk_id"])))
                for rank, chunk in enumerate(ordered[:top_k]):
                    chunk_id = str(chunk["chunk_id"])
                    if chunk_id not in runtime.source_chunks:
                        if not runtime.budget_tracker.remaining_candidates():
                            break
                        runtime.budget_tracker.candidate_chunks += 1
                        runtime.source_chunks[chunk_id] = chunk
                    runtime.chunk_tasks.setdefault(chunk_id, set()).update(
                        task.task_id for task in grouped_tasks
                    )
                    for task in grouped_tasks:
                        record = _source_record(
                            runtime=runtime,
                            chunk=chunk,
                            task=task,
                            rank=rank,
                            source_type=(
                                EvidenceSourceType.TABLE_EVIDENCE
                                if _is_table_chunk(chunk)
                                else EvidenceSourceType.TEXT_EVIDENCE
                            ),
                            discovered_by=(self.worker_id,),
                        )
                        saved = runtime.ledger.add_evidence(record)
                        evidence_ids.add(saved.evidence_id)
                        runtime.evidence_id_by_chunk_id[chunk_id] = saved.evidence_id
                        runtime.preferred_evidence_by_chunk_id.setdefault(chunk_id, saved.evidence_id)
                        task_ids.add(task.task_id)
                if not ordered:
                    missing.update(req for task in grouped_tasks for req in task.requirement_ids)
                else:
                    observations.append(SpecialistObservation(
                        key="query_candidates",
                        value=f"{len(ordered[:top_k])} candidates for {len(grouped_tasks)} task(s)",
                    ))

        if missing and evidence_ids:
            status = SpecialistStatus.PARTIAL
        elif missing:
            status = SpecialistStatus.UNKNOWN if runtime.retriever is None else SpecialistStatus.PARTIAL
        elif evidence_ids:
            status = SpecialistStatus.COMPLETE
        else:
            status = SpecialistStatus.SKIPPED
        result = SpecialistTaskResult(
            worker_id=self.worker_id,
            status=status,
            task_ids=tuple(sorted(task_ids)),
            evidence_ids=tuple(sorted(evidence_ids)),
            missing_requirement_ids=tuple(sorted(missing)),
            observations=tuple(observations),
            tool_calls=runtime.budget_tracker.tool_calls - tools_before,
            retrieval_calls=runtime.budget_tracker.retrieval_calls - retrieval_calls_before,
            candidate_chunks=runtime.budget_tracker.candidate_chunks - candidates_before,
            elapsed_ms=_elapsed_ms(started),
        )
        runtime.save_result(result)
        return result


class TableEvidenceWorker:
    """Retrieve table-focused candidates and preserve their filing context."""

    worker_id = "table_evidence_worker"

    def run(self, runtime: SpecialistRuntime) -> SpecialistTaskResult:
        started = time.perf_counter()
        evidence_ids: set[str] = set()
        task_ids: set[str] = set()
        observations: list[SpecialistObservation] = []
        tools_before = runtime.budget_tracker.tool_calls
        retrievals_before = runtime.budget_tracker.retrieval_calls
        candidates_before = runtime.budget_tracker.candidate_chunks
        table_tasks_seen: set[str] = set()
        for chunk_id, chunk in sorted(runtime.source_chunks.items()):
            if not _is_table_chunk(chunk):
                continue
            for task_id in sorted(runtime.chunk_tasks.get(chunk_id, ())):
                task = _task_by_id(runtime.plan, task_id)
                if task is None or not _chunk_matches_task(chunk, task, runtime.ticker_by_company):
                    continue
                saved = self._register_table_chunk(
                    chunk_id=chunk_id,
                    chunk=chunk,
                    task=task,
                    rank=_rank_for_chunk(runtime, chunk_id),
                    runtime=runtime,
                )
                evidence_ids.add(saved.evidence_id)
                task_ids.add(task.task_id)
                table_tasks_seen.add(task.task_id)

        # Filing retrieval is the primary candidate path. Spend remaining
        # retrieval budget on a table-shaped query only for tasks that have not
        # yet produced a matching table chunk.
        table_queries: dict[str, list[dict[str, Any]]] = {}
        for task in (runtime.plan.tasks if runtime.plan else ()):
            if task.task_id in table_tasks_seen or task.query is None or task.source_availability.value == "MISSING":
                continue
            query = f"{task.query} consolidated financial statement table"
            key = " ".join(query.casefold().split())
            if key not in table_queries:
                top_k = min(10, runtime.budget_tracker.remaining_candidates())
                if not top_k or runtime.retriever is None or not runtime.budget_tracker.can_start(retrieval=True):
                    observations.append(SpecialistObservation(key="table_budget", value="budget_or_retriever_unavailable"))
                    continue
                runtime.budget_tracker.charge(retrieval=True)
                try:
                    found = runtime.retriever.retrieve(query, top_k=top_k)
                    table_queries[key] = [_chunk_mapping(item) for item in found[:top_k]]
                except Exception as error:
                    table_queries[key] = []
                    observations.append(SpecialistObservation(key="table_retrieval_error", value=type(error).__name__))
            table_candidates = [
                item for item in table_queries[key]
                if item.get("chunk_id") and _is_table_chunk(item)
                and _chunk_matches_task(item, task, runtime.ticker_by_company)
            ]
            table_candidates.sort(key=lambda item: (-_score(item), str(item["chunk_id"])))
            if not table_candidates:
                observations.append(SpecialistObservation(
                    key="table_query",
                    value=f"no_table_candidate:{task.task_id}",
                ))
                continue
            for rank, chunk in enumerate(table_candidates):
                chunk_id = str(chunk["chunk_id"])
                existing = runtime.source_chunks.get(chunk_id)
                if existing is None:
                    if not runtime.budget_tracker.remaining_candidates():
                        continue
                    runtime.source_chunks[chunk_id] = chunk
                    runtime.budget_tracker.candidate_chunks += 1
                elif _score(chunk) > _score(existing):
                    runtime.source_chunks[chunk_id] = chunk
                runtime.chunk_tasks.setdefault(chunk_id, set()).add(task.task_id)
                saved = self._register_table_chunk(
                    chunk_id=chunk_id,
                    chunk=chunk,
                    task=task,
                    rank=rank,
                    runtime=runtime,
                )
                evidence_ids.add(saved.evidence_id)
                task_ids.add(task.task_id)
                table_tasks_seen.add(task.task_id)
                runtime.evidence_id_by_chunk_id[chunk_id] = saved.evidence_id
                runtime.preferred_evidence_by_chunk_id[chunk_id] = saved.evidence_id
        result_status = SpecialistStatus.COMPLETE if evidence_ids else SpecialistStatus.UNKNOWN
        result = SpecialistTaskResult(
            worker_id=self.worker_id,
            status=result_status,
            task_ids=tuple(sorted(task_ids)),
            evidence_ids=tuple(sorted(evidence_ids)),
            observations=(SpecialistObservation(
                key="table_chunks",
                value=str(len(evidence_ids)),
            ), *observations),
            tool_calls=runtime.budget_tracker.tool_calls - tools_before,
            retrieval_calls=runtime.budget_tracker.retrieval_calls - retrievals_before,
            candidate_chunks=runtime.budget_tracker.candidate_chunks - candidates_before,
            elapsed_ms=_elapsed_ms(started),
        )
        runtime.save_result(result)
        return result

    def _register_table_chunk(
        self,
        *,
        chunk_id: str,
        chunk: dict[str, Any],
        task: ResearchTask,
        rank: int,
        runtime: SpecialistRuntime,
    ) -> EvidenceRecord:
        base_id = runtime.evidence_id_by_chunk_id.get(chunk_id)
        base = runtime.ledger.evidence(base_id) if base_id else None
        if base is not None:
            record = EvidenceRecord.from_source(
                request_id=runtime.request_id,
                document_id=base.document_id,
                chunk_id=base.chunk_id,
                company=base.company,
                ticker=base.ticker,
                cik=base.cik,
                form_type=base.form_type,
                filing_date=base.filing_date,
                fiscal_period=base.fiscal_period,
                section=base.section,
                page=base.page,
                table_id=base.table_id or str(chunk.get("table_id") or chunk_id),
                source_type=EvidenceSourceType.TABLE_EVIDENCE,
                source_url=base.source_url,
                retrieval_method=base.retrieval_method,
                retrieval_rank=base.retrieval_rank,
                retrieval_observations=base.retrieval_observations,
                discovered_by=tuple(sorted(set(base.discovered_by) | {self.worker_id})),
                source_revision=base.source_revision,
                evidence_status=base.evidence_status,
                task_id=task.task_id,
                requirement_ids=task.requirement_ids,
            )
        else:
            record = _source_record(
                runtime=runtime,
                chunk=chunk,
                task=task,
                rank=rank,
                source_type=EvidenceSourceType.TABLE_EVIDENCE,
                discovered_by=(self.worker_id,),
            )
        return runtime.ledger.add_evidence(record)


class StructuredFinancialDataWorker:
    """Read a narrow set of standard XBRL concepts from SEC Company Facts.

    Tag drift, amended filing precedence, duration/instant normalization, and
    restatement reconciliation are deliberately deferred to M9.
    """

    worker_id = "structured_financial_data_worker"

    METRIC_TAGS: dict[str, tuple[str, ...]] = {
        "revenue": (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
        "net_income": ("NetIncomeLoss", "ProfitLoss"),
        "total_assets": ("Assets",),
        "total_liabilities": ("Liabilities",),
        "operating_income": ("OperatingIncomeLoss",),
        "gross_profit": ("GrossProfit",),
        "cash_and_equivalents": ("CashAndCashEquivalentsAtCarryingValue",),
    }

    def __init__(self, sec_client: SECEdgarClient | None = None):
        self.sec_client = sec_client

    def run(self, tasks: tuple[ResearchTask, ...], runtime: SpecialistRuntime) -> SpecialistTaskResult:
        started = time.perf_counter()
        evidence_ids: set[str] = set()
        task_ids: set[str] = set()
        missing: set[str] = set()
        observations: list[SpecialistObservation] = []
        tools_before = runtime.budget_tracker.tool_calls
        if self.sec_client is None:
            missing.update(req for task in tasks for req in task.requirement_ids)
            result = SpecialistTaskResult(
                worker_id=self.worker_id,
                status=SpecialistStatus.UNKNOWN,
                task_ids=tuple(task.task_id for task in tasks),
                missing_requirement_ids=tuple(sorted(missing)),
                observations=(SpecialistObservation(key="xbrl", value="sec_client_not_configured"),),
                elapsed_ms=_elapsed_ms(started),
            )
            runtime.save_result(result)
            return result

        grouped: dict[str, list[ResearchTask]] = {}
        for task in tasks:
            if task.metric_id not in self.METRIC_TAGS:
                missing.update(task.requirement_ids)
                continue
            ticker = _resolve_ticker(task.company_name, runtime.ticker_by_company)
            if ticker is None:
                missing.update(task.requirement_ids)
                observations.append(SpecialistObservation(
                    key="xbrl_unavailable",
                    value=f"ticker_unresolved:{task.task_id}",
                ))
                continue
            grouped.setdefault(ticker, []).append(task)

        for ticker, ticker_tasks in grouped.items():
            estimate = _estimated_sec_requests(self.sec_client, ticker)
            # Leave one finite tool call for the report writer when configured.
            reserve_for_writer = int(runtime.generator is not None and runtime.budget.max_llm_calls > 0)
            if not runtime.budget_tracker.can_start(tools=estimate + reserve_for_writer):
                missing.update(req for task in ticker_tasks for req in task.requirement_ids)
                observations.append(SpecialistObservation(key="budget", value="sec_request_budget_reached"))
                continue
            request_count = getattr(self.sec_client, "request_count", None)
            before = request_count if isinstance(request_count, int) else None
            runtime.budget_tracker.charge(tools=estimate)
            try:
                cik = self.sec_client.get_cik(ticker)
                company_facts = self.sec_client.get_company_facts(cik)
            except Exception as error:
                observations.append(SpecialistObservation(
                    key="xbrl_error",
                    value=type(error).__name__,
                ))
                missing.update(req for task in ticker_tasks for req in task.requirement_ids)
                continue
            after = getattr(self.sec_client, "request_count", None)
            if before is not None and isinstance(after, int):
                actual = max(0, after - before)
                runtime.budget_tracker.tool_calls -= max(0, estimate - actual)

            company_name = str(company_facts.get("entityName") or ticker)
            for task in ticker_tasks:
                found = self._records_for_task(
                    task=task,
                    ticker=ticker,
                    cik=cik,
                    company_name=company_name,
                    company_facts=company_facts,
                    runtime=runtime,
                )
                if found:
                    evidence_ids.update(record.evidence_id for record in found)
                    task_ids.add(task.task_id)
                else:
                    missing.update(task.requirement_ids)
            observations.append(SpecialistObservation(
                key="company_fact_entities",
                value=f"{ticker}:{len([item for item in ticker_tasks if item.task_id in task_ids])} task(s)",
            ))

        if evidence_ids and missing:
            status = SpecialistStatus.PARTIAL
        elif evidence_ids:
            status = SpecialistStatus.COMPLETE
        elif missing:
            status = SpecialistStatus.UNKNOWN
        else:
            status = SpecialistStatus.SKIPPED
        result = SpecialistTaskResult(
            worker_id=self.worker_id,
            status=status,
            task_ids=tuple(sorted(task_ids)),
            evidence_ids=tuple(sorted(evidence_ids)),
            missing_requirement_ids=tuple(sorted(missing)),
            observations=tuple(observations),
            tool_calls=runtime.budget_tracker.tool_calls - tools_before,
            elapsed_ms=_elapsed_ms(started),
        )
        runtime.save_result(result)
        return result

    def _records_for_task(
        self,
        *,
        task: ResearchTask,
        ticker: str,
        cik: int | str,
        company_name: str,
        company_facts: dict[str, Any],
        runtime: SpecialistRuntime,
    ) -> tuple[EvidenceRecord, ...]:
        facts_root = company_facts.get("facts", {})
        candidates: list[tuple[int, dict[str, Any], str, str, str]] = []
        concept_order = self.METRIC_TAGS.get(task.metric_id or "", ())
        target_year, target_quarter = _period_parts(task.period)
        for namespace, namespace_facts in sorted(facts_root.items()):
            if not isinstance(namespace_facts, dict):
                continue
            for tag_rank, tag in enumerate(concept_order):
                fact_payload = namespace_facts.get(tag)
                if not isinstance(fact_payload, dict):
                    continue
                for unit, rows in sorted((fact_payload.get("units") or {}).items()):
                    if not isinstance(rows, list):
                        continue
                    eligible = [row for row in rows if isinstance(row, dict) and _xbrl_period_matches(
                        row, target_year=target_year, target_quarter=target_quarter
                    )]
                    if not eligible:
                        continue
                    eligible.sort(key=lambda row: (
                        str(row.get("filed") or ""),
                        str(row.get("accn") or ""),
                        str(row.get("end") or ""),
                    ), reverse=True)
                    candidates.append((tag_rank, eligible[0], namespace, tag, unit))

        # Keep the first tag in the narrow M7 alias list per namespace/unit.
        # Other namespaces and units remain separate evidence to expose conflicts.
        selected: dict[tuple[str, str], tuple[int, dict[str, Any], str, str, str]] = {}
        for item in candidates:
            key = (item[2], item[4])
            if key not in selected or item[0] < selected[key][0]:
                selected[key] = item

        records: list[EvidenceRecord] = []
        for _, row, namespace, tag, unit in sorted(
            selected.values(),
            key=lambda item: (item[2], item[3], item[4], str(item[1].get("accn") or "")),
        ):
            value = row.get("val")
            try:
                normalized = Decimal(str(value))
            except (InvalidOperation, TypeError):
                continue
            if not normalized.is_finite():
                continue
            accn = str(row.get("accn") or "unknown-accession")
            filed = str(row.get("filed") or "") or None
            period = _format_xbrl_period(row, task.period)
            source_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).zfill(10)}.json"
            metric = _metric_label(runtime.requirements, task.metric_id or "")
            chunk_id = f"xbrl-{str(cik).zfill(10)}-{accn}-{namespace}-{tag}-{period or 'period-unknown'}-{unit}"
            record = EvidenceRecord.from_source(
                request_id=runtime.request_id,
                document_id=f"CIK{str(cik).zfill(10)}:{accn}",
                chunk_id=chunk_id,
                company=company_name,
                ticker=ticker,
                cik=str(cik).zfill(10),
                form_type=str(row.get("form") or "") or None,
                filing_date=filed,
                fiscal_period=period,
                section="xbrl_company_facts",
                metric=metric,
                metric_id=task.metric_id,
                financial_concept=f"{namespace}:{tag}",
                raw_value=str(value),
                normalized_value=format(normalized, "f"),
                unit=unit,
                currency=unit if unit in {"USD", "EUR", "GBP"} else None,
                source_type=EvidenceSourceType.XBRL_FACT,
                source_url=source_url,
                discovered_by=(self.worker_id,),
                source_revision=f"{accn}|{filed or ''}|{namespace}:{tag}|{row.get('start') or 'instant'}:{row.get('end') or ''}|{unit}",
                task_id=task.task_id,
                requirement_ids=task.requirement_ids,
            )
            is_new_candidate = record.chunk_id not in runtime.source_chunks
            if is_new_candidate and not runtime.budget_tracker.remaining_candidates():
                continue
            record = runtime.ledger.add_evidence(record)
            records.append(record)
            if is_new_candidate:
                runtime.budget_tracker.candidate_chunks += 1
            value_text = f"{format(normalized, ',f')} {unit}"
            text = f"{company_name} {metric} for {period or 'the reported period'}: {value_text} ({namespace}:{tag})."
            pseudo_chunk = {
                "chunk_id": record.chunk_id,
                "source_type": EvidenceSourceType.XBRL_FACT.value,
                "document_id": record.document_id,
                "doc_name": record.document_id,
                "ticker": ticker,
                "company": company_name,
                "filing_date": filed or "",
                "section": record.section,
                "source_url": source_url,
                "text": text,
                "financial_concept": record.financial_concept,
                "metric_id": task.metric_id,
                "period": period,
                "currency": record.currency,
            }
            runtime.source_chunks[str(record.chunk_id)] = pseudo_chunk
            runtime.evidence_id_by_chunk_id[str(record.chunk_id)] = record.evidence_id
            runtime.preferred_evidence_by_chunk_id[str(record.chunk_id)] = record.evidence_id
            runtime.chunk_tasks.setdefault(str(record.chunk_id), set()).add(task.task_id)
        return tuple(records)


class EvidenceAnalyst:
    """Run the existing P2 evidence sufficiency layer and promote parsed facts."""

    worker_id = "evidence_analyst"

    def run(self, question: str, runtime: SpecialistRuntime) -> SpecialistTaskResult:
        started = time.perf_counter()
        runtime.register_plan()
        all_chunks = _ordered_chunks(runtime)
        filing_chunks = [
            item for item in all_chunks
            if item.get("source_type") != EvidenceSourceType.XBRL_FACT.value
        ]
        filing_coverage = runtime.decision_layer.assess(question, filing_chunks)
        uncovered = set(filing_coverage.missing_requirement_ids)
        xbrl_chunks: list[dict[str, Any]] = []
        for item in all_chunks:
            if item.get("source_type") != EvidenceSourceType.XBRL_FACT.value:
                continue
            task_requirement_ids = {
                requirement_id
                for task_id in runtime.chunk_tasks.get(str(item.get("chunk_id")), ())
                if (task := _task_by_id(runtime.plan, task_id)) is not None
                for requirement_id in task.requirement_ids
            }
            if uncovered.intersection(task_requirement_ids):
                xbrl_chunks.append(item)
        # Keep already covered filing slots out of the M7 XBRL sufficiency pass.
        # M9 adds unit/scale normalization before these sources are reconciled.
        chunks = [*filing_chunks, *xbrl_chunks]
        runtime.coverage = runtime.decision_layer.assess(question, chunks)
        runtime.decision = runtime.decision_layer.decide(
            question,
            chunks,
            budget=DecisionBudget(remaining_retrieval_attempts=0),
        )
        added: set[str] = set()
        task_ids: set[str] = set()
        for finding in runtime.coverage.findings:
            for fact in finding.facts:
                base_id = runtime.preferred_evidence_by_chunk_id.get(fact.evidence_id)
                if base_id is None:
                    continue
                base = runtime.ledger.evidence(base_id)
                if base.source_type == EvidenceSourceType.XBRL_FACT:
                    numeric_record = base
                else:
                    numeric_record = _numeric_source_record(
                        runtime=runtime,
                        base=base,
                        fact=fact,
                        requirement_id=finding.requirement_id,
                    )
                    numeric_record = runtime.ledger.add_evidence(numeric_record)
                financial_fact = FinancialFact.from_evidence(
                    numeric_record,
                    entity_id=fact.entity_id,
                    requirement_ids=(finding.requirement_id,),
                )
                runtime.ledger.add_fact(financial_fact)
                added.add(numeric_record.evidence_id)
                task_ids.update(numeric_record.task_ids)
        missing = set(runtime.coverage.missing_requirement_ids) | set(runtime.coverage.conflicted_requirement_ids)
        result = SpecialistTaskResult(
            worker_id=self.worker_id,
            status=SpecialistStatus.COMPLETE if runtime.coverage.sufficient else SpecialistStatus.PARTIAL,
            task_ids=tuple(sorted(task_ids)),
            evidence_ids=tuple(sorted(added)),
            missing_requirement_ids=tuple(sorted(missing)),
            observations=(
                SpecialistObservation(key="sufficient", value=str(runtime.coverage.sufficient).lower()),
                SpecialistObservation(key="financial_facts", value=str(len(added))),
            ),
            elapsed_ms=_elapsed_ms(started),
        )
        runtime.save_result(result)
        return result


class FinancialReasoner:
    """Calculate bounded period-to-period growth and absolute differences."""

    worker_id = "financial_reasoner"

    def run(self, runtime: SpecialistRuntime) -> SpecialistTaskResult:
        started = time.perf_counter()
        if runtime.coverage is None:
            result = SpecialistTaskResult(
                worker_id=self.worker_id,
                status=SpecialistStatus.FAILED,
                observations=(SpecialistObservation(key="reasoner", value="coverage_not_available"),),
            )
            runtime.save_result(result)
            return result
        if not runtime.coverage.sufficient:
            result = SpecialistTaskResult(
                worker_id=self.worker_id,
                status=SpecialistStatus.SKIPPED,
                missing_requirement_ids=tuple(sorted(set(runtime.coverage.missing_requirement_ids))),
                observations=(SpecialistObservation(key="reasoner", value="evidence_not_sufficient"),),
            )
            runtime.save_result(result)
            return result
        snapshot = runtime.ledger.snapshot()
        evidence_by_id = {record.evidence_id: record for record in snapshot.evidence_records}
        requirement_by_id = {
            item.requirement_id: item for item in runtime.requirements.evidence
        }
        calculations: list[DerivedCalculation] = []
        notes: list[SpecialistObservation] = []
        for operation in runtime.requirements.operations:
            if operation.operation not in {"growth", "difference"}:
                continue
            if operation.operation == "growth" and re.search(r"\bcagr\b|compound annual", runtime.requirements.question, re.I):
                notes.append(SpecialistObservation(key="calculation_skipped", value="cagr_not_supported"))
                continue
            metric_ids = (
                (operation.metric_id,)
                if operation.metric_id
                else tuple(dict.fromkeys(fact.metric_id for fact in snapshot.financial_facts))
            )
            for entity in runtime.requirements.entities:
                for metric_id in metric_ids:
                    relevant = [
                        fact for fact in snapshot.financial_facts
                        if fact.entity_id == entity.entity_id and fact.metric_id == metric_id
                    ]
                    by_period: dict[str, list[FinancialFact]] = {}
                    for fact in relevant:
                        if fact.fiscal_period:
                            by_period.setdefault(fact.fiscal_period, []).append(fact)
                    requested_periods = list(dict.fromkeys(
                        item.period for item in runtime.requirements.evidence
                        if item.entity_id == entity.entity_id and item.metric_id == metric_id and item.period
                    ))
                    periods = sorted(
                        (period for period in by_period if not requested_periods or period in requested_periods),
                        key=_period_order,
                    )
                    if len(periods) < 2:
                        continue
                    earlier, later = periods[0], periods[-1]
                    earlier_value = _consensus_fact(by_period[earlier])
                    later_value = _consensus_fact(by_period[later])
                    if earlier_value is None or later_value is None:
                        notes.append(SpecialistObservation(
                            key="calculation_skipped",
                            value=f"conflicted_or_unverifiable_input:{entity.entity_id}:{metric_id}",
                        ))
                        continue
                    earlier_number, earlier_unit, earlier_currency, earlier_evidence_ids = earlier_value
                    later_number, later_unit, later_currency, later_evidence_ids = later_value
                    if earlier_unit not in {"%", "USD", "EUR", "GBP"}:
                        notes.append(SpecialistObservation(
                            key="calculation_skipped",
                            value=f"unit_unknown:{entity.entity_id}:{metric_id}",
                        ))
                        continue
                    if earlier_unit != later_unit or earlier_currency != later_currency:
                        notes.append(SpecialistObservation(
                            key="calculation_skipped",
                            value=f"unit_mismatch:{entity.entity_id}:{metric_id}",
                        ))
                        continue
                    if operation.operation == "growth" and earlier_number <= 0:
                        notes.append(SpecialistObservation(
                            key="calculation_skipped",
                            value=f"nonpositive_baseline:{entity.entity_id}:{metric_id}",
                        ))
                        continue
                    with localcontext() as context:
                        context.prec = 28
                        raw_result = (
                            (later_number - earlier_number) / earlier_number * Decimal(100)
                            if operation.operation == "growth"
                            else abs(later_number - earlier_number)
                        )
                        result_value = raw_result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    input_ids = (*earlier_evidence_ids, *later_evidence_ids)
                    normalized_inputs = tuple(
                        [str(earlier_number) for _ in earlier_evidence_ids]
                        + [str(later_number) for _ in later_evidence_ids]
                    )
                    input_records = [evidence_by_id[item] for item in input_ids]
                    input_task_ids = tuple(sorted({task for item in input_records for task in item.task_ids}))
                    input_requirements = tuple(sorted({
                        req for item in input_records for req in item.requirement_ids
                    }))
                    all_periods = f"{earlier} to {later}"
                    calculation = DerivedCalculation.create(
                        request_id=runtime.request_id,
                        operation=operation.operation,
                        formula=(
                            "(later - earlier) / earlier * 100"
                            if operation.operation == "growth"
                            else "absolute(later - earlier)"
                        ),
                        input_evidence_ids=input_ids,
                        normalized_inputs=normalized_inputs,
                        result=result_value,
                        metric_id=metric_id,
                        company=entity.canonical_name,
                        fiscal_period=all_periods,
                        unit="%" if operation.operation == "growth" else earlier_unit,
                        currency=None if operation.operation == "growth" else earlier_currency,
                        rounding_policy="Decimal ROUND_HALF_UP to 2 places after normalization",
                        validation_status=CalculationValidationStatus.PENDING,
                        task_ids=input_task_ids,
                        requirement_ids=input_requirements,
                    )
                    runtime.ledger.add_calculation(calculation)
                    calculations.append(calculation)
        runtime.calculations.extend(calculations)
        result = SpecialistTaskResult(
            worker_id=self.worker_id,
            status=SpecialistStatus.COMPLETE if calculations else SpecialistStatus.SKIPPED,
            task_ids=tuple(sorted({task for calc in calculations for task in calc.task_ids})),
            evidence_ids=tuple(sorted({item for calc in calculations for item in calc.input_evidence_ids})),
            observations=tuple((
                SpecialistObservation(key="calculations", value=str(len(calculations))),
                *notes,
            )),
            elapsed_ms=_elapsed_ms(started),
        )
        runtime.save_result(result)
        return result


def _chunk_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise TypeError("retrieval chunks must be mappings or structured objects")


def _score(chunk: dict[str, Any]) -> float:
    try:
        return float(chunk.get("score", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _is_table_chunk(chunk: dict[str, Any]) -> bool:
    section = str(chunk.get("section") or "").casefold().replace("-", "_").replace(" ", "_")
    if chunk.get("table_id") or section in {"financial_table", "table", "financial_tables"}:
        return True
    text = chunk.get("text")
    return isinstance(text, str) and bool(re.search(r"(?m)^\s*\|.+\|\s*$", text))


def _source_record(
    *,
    runtime: SpecialistRuntime,
    chunk: dict[str, Any],
    task: ResearchTask,
    rank: int,
    source_type: EvidenceSourceType,
    discovered_by: tuple[str, ...],
) -> EvidenceRecord:
    ticker = chunk.get("ticker")
    company = chunk.get("company")
    doc_name = chunk.get("doc_name")
    document_id = chunk.get("document_id") or doc_name
    if document_id is None and chunk.get("source_url"):
        document_id = str(chunk["source_url"])
    if document_id is None:
        document_id = f"{ticker or company or 'unknown'}:{chunk['chunk_id']}"
    raw_page = chunk.get("page_number", chunk.get("page"))
    page = raw_page + 1 if isinstance(raw_page, int) and not isinstance(raw_page, bool) and "page_number" in chunk else raw_page
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        page = None
    source_url = chunk.get("source_url") or chunk.get("filing_url") or chunk.get("source_repository_url")
    method = str(chunk.get("retrieval_method") or chunk.get("retrieval_method_name") or "dense")
    observations = (RetrievalObservation(method=method, rank=rank),)
    return EvidenceRecord.from_source(
        request_id=runtime.request_id,
        document_id=str(document_id),
        chunk_id=str(chunk["chunk_id"]),
        company=str(company) if company else None,
        ticker=str(ticker).upper() if ticker else None,
        cik=str(chunk["cik"]) if chunk.get("cik") is not None else None,
        form_type=str(chunk.get("filing_type") or chunk.get("form_type") or "") or None,
        filing_date=str(chunk.get("filing_date") or "") or None,
        fiscal_period=_fiscal_period(chunk),
        section=str(chunk.get("section") or "") or None,
        page=page,
        table_id=(
            str(chunk.get("table_id") or chunk["chunk_id"])
            if source_type == EvidenceSourceType.TABLE_EVIDENCE
            else str(chunk.get("table_id")) if chunk.get("table_id") else None
        ),
        source_type=source_type,
        source_url=str(source_url) if source_url else None,
        retrieval_method=method,
        retrieval_rank=rank,
        retrieval_observations=observations,
        discovered_by=discovered_by,
        source_revision=str(chunk.get("source_revision") or chunk.get("accession_number") or chunk.get("filing_date") or "") or None,
        task_id=task.task_id,
        requirement_ids=task.requirement_ids,
    )


def _fiscal_period(chunk: dict[str, Any]) -> str | None:
    for key in ("fiscal_period", "reporting_period", "report_date"):
        value = chunk.get(key)
        if value:
            match = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", str(value))
            if match:
                return f"FY{match.group(0)}"
    return None


def _task_by_id(plan: ResearchPlan | None, task_id: str | None) -> ResearchTask | None:
    if plan is None or task_id is None:
        return None
    return next((task for task in plan.tasks if task.task_id == task_id), None)


def _chunk_matches_task(
    chunk: dict[str, Any], task: ResearchTask, ticker_by_company: dict[str, str]
) -> bool:
    expected_ticker = _resolve_ticker(task.company_name, ticker_by_company)
    found_ticker = chunk.get("ticker")
    return not expected_ticker or not found_ticker or str(found_ticker).upper() == expected_ticker


def _rank_for_chunk(runtime: SpecialistRuntime, chunk_id: str) -> int:
    evidence_id = runtime.evidence_id_by_chunk_id.get(chunk_id)
    if evidence_id is None:
        return 0
    return runtime.ledger.evidence(evidence_id).retrieval_rank or 0


def _ordered_chunks(runtime: SpecialistRuntime) -> list[dict[str, Any]]:
    return [runtime.source_chunks[key] for key in sorted(runtime.source_chunks)]


def _metric_label(requirements: QuestionRequirements, metric_id: str) -> str:
    return next((metric.display_name for metric in requirements.metrics if metric.metric_id == metric_id), metric_id.replace("_", " "))


def _numeric_source_record(
    *,
    runtime: SpecialistRuntime,
    base: EvidenceRecord,
    fact: Any,
    requirement_id: str,
) -> EvidenceRecord:
    try:
        number = Decimal(str(fact.numeric_value))
    except (InvalidOperation, TypeError):
        number = Decimal(0)
    scale_factor = {
        "unit": Decimal(1),
        "thousand": Decimal(1000),
        "million": Decimal(1_000_000),
        "billion": Decimal(1_000_000_000),
    }.get(fact.scale or "unit", Decimal(1))
    normalized = number * scale_factor
    if fact.value_kind == "percent":
        unit = "%"
    elif fact.currency:
        unit = fact.currency
    else:
        unit = "unknown"
    supporting_tasks = {
        task.task_id for task in (runtime.plan.tasks if runtime.plan else ())
        if requirement_id in task.requirement_ids
    }
    return EvidenceRecord.from_source(
        request_id=runtime.request_id,
        document_id=base.document_id,
        chunk_id=base.chunk_id,
        company=base.company,
        ticker=base.ticker,
        cik=base.cik,
        form_type=base.form_type,
        filing_date=base.filing_date,
        fiscal_period=fact.period or base.fiscal_period,
        section=base.section,
        page=base.page,
        table_id=base.table_id,
        metric=_metric_label(runtime.requirements, fact.metric_id),
        metric_id=fact.metric_id,
        raw_value=fact.value,
        normalized_value=str(normalized.normalize()),
        unit=unit,
        currency=fact.currency,
        source_type=base.source_type,
        source_url=base.source_url,
        retrieval_method=base.retrieval_method,
        retrieval_rank=base.retrieval_rank,
        retrieval_observations=base.retrieval_observations,
        discovered_by=base.discovered_by,
        source_revision=base.source_revision,
        evidence_status=base.evidence_status,
        task_ids=tuple(sorted(set(base.task_ids) | supporting_tasks)),
        requirement_ids=(requirement_id,) if supporting_tasks else (),
    )


def _period_parts(period: str | None) -> tuple[int | None, int | None]:
    if not period:
        return None, None
    year_match = re.search(r"(?:19|20)\d{2}", period)
    quarter_match = re.search(r"\bQ([1-4])\b", period, re.I)
    return (
        int(year_match.group(0)) if year_match else None,
        int(quarter_match.group(1)) if quarter_match else None,
    )


def _xbrl_period_matches(
    row: dict[str, Any], *, target_year: int | None, target_quarter: int | None
) -> bool:
    if target_year is None:
        return True
    if row.get("fy") is not None:
        try:
            if int(row["fy"]) != target_year:
                return False
        except (TypeError, ValueError):
            return False
    else:
        end_year, _ = _period_parts(str(row.get("end") or ""))
        if end_year != target_year:
            return False
    if target_quarter is None:
        return str(row.get("fp") or "").upper() in {"FY", "Q4", ""}
    return str(row.get("fp") or "").upper() == f"Q{target_quarter}"


def _format_xbrl_period(row: dict[str, Any], fallback: str | None) -> str | None:
    fp = str(row.get("fp") or "").upper()
    fy = row.get("fy")
    if fy is None:
        _, quarter = _period_parts(str(row.get("end") or ""))
        year, _ = _period_parts(str(row.get("end") or ""))
        if year is None:
            return fallback
        return f"Q{quarter} FY{year}" if quarter else f"FY{year}"
    try:
        year = int(fy)
    except (TypeError, ValueError):
        return fallback
    return f"{fp} FY{year}" if fp.startswith("Q") else f"FY{year}"


def _resolve_ticker(company: str | None, lookup: dict[str, str]) -> str | None:
    if not company:
        return None
    normalized = " ".join(company.casefold().split())
    if normalized in lookup:
        return lookup[normalized].upper()
    if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", company.upper()):
        return company.upper()
    return None


def _estimated_sec_requests(client: Any, ticker: str) -> int:
    estimate = getattr(client, "estimated_company_facts_requests", None)
    if callable(estimate):
        try:
            return max(1, int(estimate(ticker)))
        except Exception:
            return 2
    return 2 if hasattr(client, "get_cik") else 1


def _consensus_fact(
    facts: list[FinancialFact],
) -> tuple[Decimal, str | None, str | None, tuple[str, ...]] | None:
    values: set[tuple[Decimal, str | None, str | None]] = set()
    evidence_ids: set[str] = set()
    for fact in facts:
        if fact.normalized_value is None:
            return None
        try:
            number = Decimal(fact.normalized_value)
        except InvalidOperation:
            return None
        if not number.is_finite():
            return None
        values.add((number, fact.unit, fact.currency))
        evidence_ids.update(fact.evidence_ids)
    if len(values) != 1:
        return None
    value, unit, currency = next(iter(values))
    if not evidence_ids:
        return None
    return value, unit, currency, tuple(sorted(evidence_ids))


def _period_order(period: str) -> tuple[int, int, str]:
    year, quarter = _period_parts(period)
    quarter_index = quarter or 5
    return year or 0, quarter_index, period


def _elapsed_ms(started: float) -> float:
    return max(0.0, (time.perf_counter() - started) * 1000)


__all__ = [
    "EvidenceAnalyst",
    "FilingResearchWorker",
    "FinancialReasoner",
    "SpecialistObservation",
    "SpecialistRuntime",
    "SpecialistTaskAssignment",
    "SpecialistStatus",
    "SpecialistTaskResult",
    "StructuredFinancialDataWorker",
    "TableEvidenceWorker",
]
