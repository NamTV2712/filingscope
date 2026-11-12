"""Bounded specialist graph over the existing router, ledger, and P2/P4 APIs."""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send
from pydantic import BaseModel, ConfigDict, Field

from src.agent.complexity_router import ComplexityRouter, ExecutionPath, RouteBudget, RouterExecution
from src.agent.specialists import (
    EvidenceAnalyst,
    FilingResearchWorker,
    FinancialReasoner,
    SpecialistObservation,
    SpecialistRuntime,
    SpecialistStatus,
    SpecialistTaskAssignment,
    SpecialistTaskResult,
    StructuredFinancialDataWorker,
    TableEvidenceWorker,
)
from src.decision.models import DecisionResult, EvidenceCoverage
from src.decision.company_catalog import DEFAULT_COMPANY_ALIASES
from src.generation.answer_generator import (
    AnswerGenerationResult,
    AnswerGenerator,
    build_generation_messages,
    estimate_prompt_tokens,
    is_fallback_answer,
)
from src.ingestion.sec_client import SECEdgarClient
from src.ingestion.company_facts import RevisionKind, RevisionPolicy, requested_revision_policies
from src.ledger.evidence_ledger import EvidenceLedger, LedgerConflictError, LedgerReferenceError
from src.ledger.models import (
    DerivedCalculation,
    GeneratedClaim,
    LedgerSnapshot,
)
from src.research.planner import ResearchPlan, ResearchTask
from src.verification.atomic_claim_verifier import AtomicClaimVerifier
from src.verification.claim_verifier import ClaimLevelVerifier
from src.verification.models import ClaimAssessment, ResponseDisposition, VerificationResult
from src.verification.response_policy import INSUFFICIENT_EVIDENCE_ANSWER, verify_and_release


SpecialistExecutionStatus = Literal[
    "VERIFIED", "PARTIAL", "REJECTED", "ABSTAIN", "UNSUPPORTED"
]


class SpecialistUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    graph_steps: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    retrieval_calls: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    correction_passes: int = Field(default=0, ge=0, le=1)
    candidate_chunks: int = Field(ge=0)
    parallel_task_count: int = Field(default=0, ge=0)
    max_concurrency: int = Field(default=0, ge=0)
    peak_parallel_tasks: int = Field(default=0, ge=0)
    deduplicated_query_tasks: int = Field(default=0, ge=0)
    duplicate_candidate_chunks: int = Field(default=0, ge=0)
    context_tokens: int = Field(ge=0)
    wall_time_ms: float = Field(ge=0, allow_inf_nan=False)


class SpecialistExecution(BaseModel):
    """Inspectable M7 result with source text omitted from the public state."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request_id: str = Field(min_length=1)
    question: str
    selected_path: ExecutionPath
    status: SpecialistExecutionStatus
    route: RouterExecution
    graph_trace: tuple[str, ...]
    specialist_results: tuple[SpecialistTaskResult, ...]
    usage: SpecialistUsage
    evidence_ids: tuple[str, ...]
    answer: str
    generation: AnswerGenerationResult | None = None
    coverage: EvidenceCoverage | None = None
    decision: DecisionResult | None = None
    verification: VerificationResult | None = None
    calculations: tuple[DerivedCalculation, ...] = ()
    ledger_snapshot: LedgerSnapshot


class ParallelFilingReceipt(BaseModel):
    """Metadata-only result from one isolated retrieval worker."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    assignment_id: str = Field(min_length=1)
    task_result: SpecialistTaskResult
    ledger_snapshot: LedgerSnapshot


def _merge_filing_receipts(
    current: dict[str, ParallelFilingReceipt],
    incoming: dict[str, ParallelFilingReceipt],
) -> dict[str, ParallelFilingReceipt]:
    """Associative, commutative reducer for disjoint or identical task writes."""
    merged = dict(current)
    for assignment_id, receipt in incoming.items():
        existing = merged.get(assignment_id)
        if existing is not None and existing != receipt:
            raise ValueError(f"conflicting parallel filing receipt: {assignment_id}")
        merged[assignment_id] = receipt
    return {key: merged[key] for key in sorted(merged)}


class _SpecialistGraphState(TypedDict, total=False):
    request_id: str
    question: str
    route: RouterExecution
    plan: ResearchPlan | None
    trace: list[str]
    specialist_results: list[SpecialistTaskResult]
    evidence_ids: list[str]
    answer: str
    generation: AnswerGenerationResult | None
    verification: VerificationResult | None
    status: str
    filing_assignments: list[SpecialistTaskAssignment]
    filing_pre_results: list[SpecialistTaskResult]
    filing_assignment: SpecialistTaskAssignment
    filing_receipts: Annotated[dict[str, ParallelFilingReceipt], _merge_filing_receipts]


class SpecialistResearchGraph:
    """Execute a fixed FAST or RESEARCH sequence with route-specific ceilings.

    FAST has four execution stages and RESEARCH has eight. Concurrent-safe
    retrievers can fan out the RESEARCH filing stage. UNSUPPORTED terminates
    without downstream calls.
    """

    def __init__(
        self,
        *,
        router: ComplexityRouter | None = None,
        retriever: Any | None = None,
        sec_client: SECEdgarClient | None = None,
        generator: AnswerGenerator | None = None,
        verifier: ClaimLevelVerifier | None = None,
        ticker_by_company: dict[str, str] | None = None,
        retriever_concurrency_safe: bool | None = None,
    ):
        self.router = router or ComplexityRouter()
        self.retriever = retriever
        self.sec_client = sec_client
        self.generator = generator
        self.verifier = verifier or AtomicClaimVerifier()
        self.ticker_by_company = _ticker_lookup(self.router, ticker_by_company or {})
        self.retriever_concurrency_safe = (
            retriever is not None
            and (
                getattr(retriever, "supports_concurrent_retrieval", False) is True
                if retriever_concurrency_safe is None
                else retriever_concurrency_safe
            )
        )
        self.graph = self._build_graph()

    def run(
        self,
        question: str,
        *,
        request_id: str | None = None,
        route: RouterExecution | None = None,
        ledger: EvidenceLedger | None = None,
    ) -> SpecialistExecution:
        request_id = request_id or f"request-{uuid.uuid4().hex}"
        route = route or self.router.route(question)
        if route.question != question:
            raise ValueError("router execution belongs to a different question")
        if route.selected_path == ExecutionPath.UNSUPPORTED:
            allowed_steps = route.budget.max_graph_steps
        else:
            allowed_steps = route.budget.max_graph_steps
            if route.research_plan is None:
                raise ValueError("supported routes must include a bounded research plan")
            if len(route.research_plan.tasks) > route.budget.max_planned_tasks:
                raise ValueError("research plan exceeds the selected planned-task budget")
            if route.research_plan.retrieval_call_count > route.budget.max_retrieval_calls:
                raise ValueError("research plan exceeds the selected retrieval-call budget")
        if ledger is not None and ledger.request_id != request_id:
            raise ValueError("ledger request_id must match the specialist run")
        revisions = requested_revision_policies(question)
        runtime = SpecialistRuntime(
            request_id=request_id,
            ledger=ledger or EvidenceLedger(request_id=request_id),
            budget=route.budget,
            requirements=self.router.extractor.extract(question),
            plan=route.research_plan,
            retriever=self.retriever,
            sec_client=self.sec_client,
            ticker_by_company=self.ticker_by_company,
            generator=self.generator,
            verifier=self.verifier,
            xbrl_revision_policy=next(iter(revisions), RevisionPolicy.AS_REPORTED),
            require_structured_facts=bool(revisions),
        )
        concurrency = 1
        if route.selected_path == ExecutionPath.RESEARCH and self.retriever_concurrency_safe:
            concurrency = max(1, route.budget.max_concurrency)
        initial: _SpecialistGraphState = {
            "request_id": request_id,
            "question": question,
            "route": route,
            "plan": route.research_plan,
            "trace": [],
            "specialist_results": [],
            "evidence_ids": [],
            "answer": "",
            "generation": None,
            "verification": None,
            "status": "ABSTAIN",
            "filing_assignments": [],
            "filing_pre_results": [],
            "filing_receipts": {},
        }
        state = self.graph.invoke(
            initial,
            context=runtime,
            config={
                "recursion_limit": max(2, allowed_steps + 3),
                "max_concurrency": concurrency,
            },
        )
        steps = len(state.get("trace", ()))
        if steps > allowed_steps:
            raise RuntimeError("specialist graph exceeded its route step budget")
        snapshot = runtime.ledger.snapshot()
        usage = SpecialistUsage(
            graph_steps=steps,
            tool_calls=runtime.budget_tracker.tool_calls,
            retrieval_calls=runtime.budget_tracker.retrieval_calls,
            llm_calls=runtime.budget_tracker.llm_calls,
            correction_passes=runtime.correction_passes,
            candidate_chunks=runtime.budget_tracker.candidate_chunks,
            parallel_task_count=runtime.parallel_task_count,
            max_concurrency=runtime.effective_max_concurrency,
            peak_parallel_tasks=runtime.parallel_task_tracker.peak,
            deduplicated_query_tasks=runtime.deduplicated_query_count,
            duplicate_candidate_chunks=runtime.duplicate_candidate_chunks,
            context_tokens=runtime.budget_tracker.context_tokens,
            wall_time_ms=max(0.0, (time.perf_counter() - runtime.budget_tracker.started) * 1000),
        )
        evidence_ids = set(state.get("evidence_ids", ()))
        evidence_ids.update(record.evidence_id for record in snapshot.evidence_records)
        status = _execution_status(state.get("status", "ABSTAIN"), runtime.verification)
        return SpecialistExecution(
            request_id=request_id,
            question=question,
            selected_path=route.selected_path,
            status=status,
            route=route,
            graph_trace=tuple(state.get("trace", ())),
            specialist_results=tuple(state.get("specialist_results", ())),
            usage=usage,
            evidence_ids=tuple(sorted(evidence_ids)),
            answer=state.get("answer", ""),
            generation=runtime.generation,
            coverage=runtime.coverage,
            decision=runtime.decision,
            verification=runtime.verification,
            calculations=tuple(runtime.calculations),
            ledger_snapshot=snapshot,
        )

    def _build_graph(self):
        graph = StateGraph(_SpecialistGraphState, context_schema=SpecialistRuntime)
        graph.add_node("supervisor", self._supervisor_node)
        graph.add_node("filing_worker", self._filing_node)
        graph.add_node("parallel_filing_worker", self._parallel_filing_node)
        graph.add_node("structured_data_worker", self._structured_node)
        graph.add_node("table_worker", self._table_node)
        graph.add_node("evidence_analyst", self._analyst_node)
        graph.add_node("financial_reasoner", self._reasoner_node)
        graph.add_node("report_writer", self._writer_node)
        graph.add_node("claim_verifier", self._verifier_node)
        graph.add_node("unsupported_path", self._unsupported_node)
        graph.add_conditional_edges(
            START,
            self._entry,
            {
                ExecutionPath.FAST.value: "filing_worker",
                ExecutionPath.RESEARCH.value: "supervisor",
                ExecutionPath.UNSUPPORTED.value: "unsupported_path",
            },
        )
        graph.add_conditional_edges("supervisor", self._fan_out_filing_tasks)
        graph.add_edge("parallel_filing_worker", "structured_data_worker")
        graph.add_conditional_edges(
            "filing_worker",
            lambda state: state["route"].selected_path.value,
            {"FAST": "evidence_analyst", "RESEARCH": "structured_data_worker"},
        )
        graph.add_edge("structured_data_worker", "table_worker")
        graph.add_edge("table_worker", "evidence_analyst")
        graph.add_edge("financial_reasoner", "report_writer")
        graph.add_edge("report_writer", "claim_verifier")
        graph.add_edge("claim_verifier", END)
        graph.add_conditional_edges(
            "evidence_analyst",
            self._after_analyst,
            {
                "fast": "report_writer",
                "research": "financial_reasoner",
            },
        )
        graph.add_edge("unsupported_path", END)
        return graph.compile()

    @staticmethod
    def _entry(state: _SpecialistGraphState) -> str:
        return state["route"].selected_path.value

    @staticmethod
    def _after_analyst(state: _SpecialistGraphState) -> str:
        return "fast" if state["route"].selected_path == ExecutionPath.FAST else "research"

    def _supervisor_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime]
    ) -> dict[str, Any]:
        context = runtime.context
        context.register_plan()
        assignments: list[SpecialistTaskAssignment] = []
        pre_results: list[SpecialistTaskResult] = []
        if self.retriever_concurrency_safe:
            groups = _filing_query_groups(state.get("plan"))
            context.deduplicated_query_count = sum(len(group) - 1 for group in groups.values())
            assignments, pre_results = _build_filing_assignments(
                plan=state.get("plan"),
                groups=groups,
                budget=state["route"].budget,
                wall_time_remaining=self._remaining_wall_time(context),
            )
        context.parallel_task_count = len(assignments)
        context.effective_max_concurrency = min(context.budget.max_concurrency, len(assignments))
        result = SpecialistTaskResult(
            worker_id="research_supervisor",
            status=SpecialistStatus.COMPLETE,
            task_ids=tuple(task.task_id for task in (state.get("plan").tasks if state.get("plan") else ())),
            observations=(SpecialistObservation(
                key="planned_tasks",
                value=str(len(state.get("plan").tasks if state.get("plan") else ())),
            ), *(
                (SpecialistObservation(
                    key="planning_warnings",
                    value=",".join(state["plan"].warnings),
                ),) if state.get("plan") and state["plan"].warnings else ()
            ), SpecialistObservation(
                key="retrieval_assignments",
                value=str(len(assignments)),
            ), SpecialistObservation(
                key="deduplicated_query_tasks",
                value=str(context.deduplicated_query_count),
            ), SpecialistObservation(
                key="max_concurrency",
                value=str(context.effective_max_concurrency),
            )),
        )
        context.save_result(result)
        return {
            "trace": [*state.get("trace", ()), "supervisor"],
            "specialist_results": [*state.get("specialist_results", ()), result],
            "filing_assignments": assignments,
            "filing_pre_results": pre_results,
        }

    def _fan_out_filing_tasks(
        self,
        state: _SpecialistGraphState,
    ) -> list[Send] | str:
        if not self.retriever_concurrency_safe:
            return "filing_worker"
        assignments = state.get("filing_assignments", ())
        if not assignments:
            return "structured_data_worker"
        return [
            Send(
                "parallel_filing_worker",
                {"filing_assignment": assignment},
            )
            for assignment in assignments
        ]

    def _filing_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime]
    ) -> dict[str, Any]:
        context = runtime.context
        task_result = FilingResearchWorker().run(
            tuple(state.get("plan").tasks if state.get("plan") else ()),
            context,
        )
        return {
            "trace": [*state.get("trace", ()), "filing_worker"],
            "specialist_results": [*state.get("specialist_results", ()), task_result],
            "evidence_ids": sorted(set(state.get("evidence_ids", ())) | set(task_result.evidence_ids)),
        }

    def _parallel_filing_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime]
    ) -> dict[str, Any]:
        context = runtime.context
        assignment = state["filing_assignment"]
        budget = assignment.budget.model_copy(update={
            "max_wall_time_seconds": min(
                assignment.budget.max_wall_time_seconds, self._remaining_wall_time(context)
            ),
        })
        worker_runtime = SpecialistRuntime(
            request_id=context.request_id,
            ledger=EvidenceLedger(request_id=context.request_id),
            budget=budget,
            requirements=context.requirements,
            plan=context.plan,
            retriever=context.retriever,
            ticker_by_company=context.ticker_by_company,
        )
        started = time.perf_counter()
        snapshot = LedgerSnapshot(request_id=context.request_id)
        context.parallel_task_tracker.enter()
        try:
            task_result = FilingResearchWorker().run(assignment.tasks, worker_runtime).model_copy(
                update={"task_ids": assignment.task_ids},
            )
            snapshot = worker_runtime.ledger.snapshot()
            context.stage_retrieval_artifacts(assignment.task_id, worker_runtime)
        except Exception as error:
            task_result = SpecialistTaskResult(
                worker_id="filing_research_worker",
                status=SpecialistStatus.FAILED,
                task_ids=assignment.task_ids,
                missing_requirement_ids=assignment.evidence_requirement_ids,
                observations=(SpecialistObservation(
                    key="isolated_worker_failure",
                    value=type(error).__name__,
                ),),
                tool_calls=worker_runtime.budget_tracker.tool_calls,
                retrieval_calls=worker_runtime.budget_tracker.retrieval_calls,
                candidate_chunks=worker_runtime.budget_tracker.candidate_chunks,
                elapsed_ms=max(0.0, (time.perf_counter() - started) * 1000),
                error_code=type(error).__name__,
            )
        finally:
            context.parallel_task_tracker.exit()
        receipt = ParallelFilingReceipt(
            assignment_id=assignment.task_id,
            task_result=task_result,
            ledger_snapshot=snapshot,
        )
        return {"filing_receipts": {assignment.task_id: receipt}}

    @staticmethod
    def _remaining_wall_time(context: SpecialistRuntime) -> float:
        return max(0.0, context.budget.max_wall_time_seconds - context.budget_tracker.elapsed_seconds)

    def _structured_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime]
    ) -> dict[str, Any]:
        context = runtime.context
        filing_results, filing_evidence = self._merge_parallel_filing_results(state, context)
        task_result = StructuredFinancialDataWorker(context.sec_client).run(
            tuple(state.get("plan").tasks if state.get("plan") else ()),
            context,
        )
        trace = list(state.get("trace", ()))
        if self.retriever_concurrency_safe:
            trace.append("filing_worker")
        return {
            "trace": [*trace, "structured_data_worker"],
            "specialist_results": [
                *state.get("specialist_results", ()),
                *filing_results,
                task_result,
            ],
            "evidence_ids": sorted(
                set(state.get("evidence_ids", ()))
                | filing_evidence
                | set(task_result.evidence_ids)
            ),
        }

    @staticmethod
    def _merge_parallel_filing_results(
        state: _SpecialistGraphState,
        context: SpecialistRuntime,
    ) -> tuple[list[SpecialistTaskResult], set[str]]:
        receipts = state.get("filing_receipts", {})
        assignments = {item.task_id: item for item in state.get("filing_assignments", ())}
        workers = {
            key: context.take_retrieval_artifacts(key)
            for key, receipt in receipts.items()
            if receipt.task_result.status != SpecialistStatus.FAILED
        }
        chunk_versions: dict[str, tuple[str, Any]] = {}
        conflicted_chunks: set[str] = set()
        for worker in workers.values():
            for chunk_id, chunk in worker.source_chunks.items():
                version = (worker.evidence_id_by_chunk_id[chunk_id], chunk.get("text"))
                if chunk_versions.setdefault(chunk_id, version) != version:
                    conflicted_chunks.add(chunk_id)
        results = list(state.get("filing_pre_results", ()))
        evidence_ids: set[str] = set()
        candidate_ids: set[str] = set()
        total_candidates = 0
        for assignment_id in sorted(receipts):
            receipt = receipts[assignment_id]
            result = receipt.task_result
            context.budget_tracker.tool_calls += result.tool_calls
            context.budget_tracker.retrieval_calls += result.retrieval_calls
            context.budget_tracker.candidate_chunks += result.candidate_chunks
            if result.status != SpecialistStatus.FAILED:
                worker = workers[assignment_id]
                try:
                    if conflicted_chunks.intersection(worker.source_chunks):
                        raise LedgerConflictError("retrieval workers disagreed on chunk identity")
                    context.ledger.merge(receipt.ledger_snapshot)
                except (LedgerConflictError, LedgerReferenceError) as error:
                    assignment = assignments[assignment_id]
                    result = result.model_copy(update={
                        "status": SpecialistStatus.FAILED,
                        "task_ids": assignment.task_ids,
                        "evidence_ids": (),
                        "missing_requirement_ids": assignment.evidence_requirement_ids,
                        "error_code": type(error).__name__,
                    })
                else:
                    context.merge_retrieval_artifacts(worker)
                    candidate_ids.update(worker.source_chunks)
                    total_candidates += len(worker.source_chunks)
            results.append(result)
            evidence_ids.update(result.evidence_ids)
        context.duplicate_candidate_chunks = total_candidates - len(candidate_ids)
        results.sort(key=lambda item: (item.worker_id, item.task_ids, item.status.value))
        return results, evidence_ids

    def _table_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime]
    ) -> dict[str, Any]:
        task_result = TableEvidenceWorker().run(runtime.context)
        return {
            "trace": [*state.get("trace", ()), "table_worker"],
            "specialist_results": [*state.get("specialist_results", ()), task_result],
            "evidence_ids": sorted(set(state.get("evidence_ids", ())) | set(task_result.evidence_ids)),
        }

    def _analyst_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime]
    ) -> dict[str, Any]:
        context = runtime.context
        task_result = EvidenceAnalyst().run(state["question"], context)
        task_results = [task_result]
        if (
            state["route"].selected_path == ExecutionPath.FAST
            and any(
                item.operation in {"growth", "difference"}
                for item in context.requirements.operations
            )
        ):
            task_results.append(FinancialReasoner().run(context))
        return {
            "trace": [*state.get("trace", ()), "evidence_analyst"],
            "specialist_results": [*state.get("specialist_results", ()), *task_results],
            "evidence_ids": sorted(
                set(state.get("evidence_ids", ()))
                | {evidence_id for result in task_results for evidence_id in result.evidence_ids}
            ),
        }

    def _reasoner_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime]
    ) -> dict[str, Any]:
        task_result = FinancialReasoner().run(runtime.context)
        return {
            "trace": [*state.get("trace", ()), "financial_reasoner"],
            "specialist_results": [*state.get("specialist_results", ()), task_result],
            "evidence_ids": sorted(set(state.get("evidence_ids", ())) | set(task_result.evidence_ids)),
        }

    def _writer_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime]
    ) -> dict[str, Any]:
        context = runtime.context
        tools_before = context.budget_tracker.tool_calls
        llm_before = context.budget_tracker.llm_calls
        answer = self._write_report(state["question"], context)
        result = SpecialistTaskResult(
            worker_id="report_writer",
            status=SpecialistStatus.PARTIAL if is_fallback_answer(answer.answer) else SpecialistStatus.COMPLETE,
            task_ids=tuple(task.task_id for task in (state.get("plan").tasks if state.get("plan") else ())),
            evidence_ids=tuple(sorted(context.evidence_id_by_chunk_id.values())),
            observations=(SpecialistObservation(
                key="writer",
                value="fallback" if is_fallback_answer(answer.answer) else answer.model_id,
            ),),
            tool_calls=context.budget_tracker.tool_calls - tools_before,
            llm_calls=context.budget_tracker.llm_calls - llm_before,
            context_tokens=context.budget_tracker.context_tokens,
        )
        context.save_result(result)
        return {
            "trace": [*state.get("trace", ()), "report_writer"],
            "specialist_results": [*state.get("specialist_results", ()), result],
            "answer": answer.answer,
            "generation": answer,
        }

    def _verifier_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime]
    ) -> dict[str, Any]:
        context = runtime.context
        answer = state.get("answer", "")
        chunks = _ordered_report_chunks(context)
        verifier = context.verifier
        if isinstance(verifier, AtomicClaimVerifier):
            release = verify_and_release(
                verifier, state["question"], answer, chunks, context.requirements,
                can_correct=lambda: context.budget_tracker.can_start(tools=0),
            )
            context.correction_passes = release.correction_passes
            if release.correction_passes:
                self._record_verification(release.initial, context, "M11-draft")
            answer = release.answer
            verification = self._record_verification(release.result, context, "M11")
        else:
            verification = self._record_verification(verifier.verify(state["question"], answer, chunks), context, "P4")
        context.verification = verification
        generation = state.get("generation")
        if generation is not None:
            context.generation = generation.model_copy(update={"answer": answer})
        result = SpecialistTaskResult(
            worker_id="claim_verifier",
            status=(
                SpecialistStatus.COMPLETE
                if verification.disposition == ResponseDisposition.VERIFIED
                else SpecialistStatus.PARTIAL
                if verification.disposition == ResponseDisposition.PARTIAL
                else SpecialistStatus.UNKNOWN
            ),
            evidence_ids=tuple(sorted({item for claim in verification.claims for item in claim.evidence_ids})),
            observations=(
                SpecialistObservation(key="disposition", value=verification.disposition.value),
                SpecialistObservation(key="correction_passes", value=str(context.correction_passes)),
            ),
        )
        context.save_result(result)
        return {
            "trace": [*state.get("trace", ()), "claim_verifier"],
            "specialist_results": [*state.get("specialist_results", ()), result],
            "status": verification.disposition.value,
            "answer": answer,
        }

    def _record_verification(
        self, verification: VerificationResult, context: SpecialistRuntime, version: str,
    ) -> VerificationResult:
        linked = self._link_verification_to_ledger(verification, context)
        rendered_calculations = {
            statement: calculation.calculation_id
            for calculation, statement in _render_calculation_entries(context)
        }
        assessments = []
        for assessment in linked.claims:
            legacy = assessment.claim_type is None
            claim = GeneratedClaim.create(
                claim_id=assessment.claim_id if legacy else None,
                request_id=context.request_id,
                claim_text=assessment.statement,
                claim_type=assessment.claim_type or assessment.status.value,
                supporting_evidence_ids=assessment.evidence_ids if legacy else assessment.supporting_evidence_ids,
                cited_evidence_ids=None if legacy else assessment.evidence_ids,
                calculation_id=rendered_calculations.get(assessment.statement),
                requirement_ids=(
                    tuple(item.requirement_id for item in context.requirements.evidence)
                    if legacy else assessment.requirement_ids
                ),
            )
            context.ledger.add_claim(claim)
            assessments.append(assessment.model_copy(update={"claim_id": claim.claim_id}))
        linked = linked.model_copy(update={"claims": tuple(assessments)})
        context.ledger.add_verification(linked, verifier_id="claim-level-verifier", verifier_version=version)
        return linked

    @staticmethod
    def _unsupported_node(
        state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime]
    ) -> dict[str, Any]:
        context = runtime.context
        result = SpecialistTaskResult(
            worker_id="unsupported_route",
            status=SpecialistStatus.SKIPPED,
            observations=(SpecialistObservation(
                key="route_reason",
                value=",".join(state["route"].decision.reason_codes) or "unsupported_request",
            ),),
        )
        context.save_result(result)
        return {
            "trace": [*state.get("trace", ()), "unsupported_path"],
            "specialist_results": [*state.get("specialist_results", ()), result],
            "status": "UNSUPPORTED",
        }

    def _write_report(self, question: str, runtime: SpecialistRuntime) -> AnswerGenerationResult:
        started = time.perf_counter()
        coverage = runtime.coverage
        if coverage is None or not coverage.sufficient:
            return _fallback_result()
        chunks = _ordered_report_chunks(runtime)
        arithmetic = {
            operation.operation for operation in runtime.requirements.operations
            if operation.operation in {"growth", "difference", "ratio", "average"}
        }
        if arithmetic:
            requested = {
                (operation, entity.canonical_name, metric.metric_id)
                for operation in arithmetic
                for entity in runtime.requirements.entities
                for metric in runtime.requirements.metrics if metric.quantitative
            }
            calculated = {(item.operation, item.company, item.metric_id) for item in runtime.calculations}
            if not requested or not requested.issubset(calculated):
                return _fallback_result()
        if runtime.calculations:
            answer = _render_calculations(runtime)
            if answer:
                return AnswerGenerationResult(
                    answer=answer,
                    model_id="filingscope-deterministic-report-writer",
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=max(0.0, (time.perf_counter() - started) * 1000),
                )
        if runtime.generator is None or runtime.require_structured_facts:
            answer = _render_lookup(runtime)
            if answer:
                return AnswerGenerationResult(
                    answer=answer,
                    model_id="filingscope-deterministic-report-writer",
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=max(0.0, (time.perf_counter() - started) * 1000),
                )
            return _fallback_result()
        messages = build_generation_messages(question, chunks)
        estimated_tokens = estimate_prompt_tokens(messages)
        runtime.budget_tracker.context_tokens = estimated_tokens
        if estimated_tokens > runtime.budget.max_context_tokens:
            return _fallback_result()
        if not runtime.budget_tracker.can_start(llm=True):
            return _fallback_result()
        runtime.budget_tracker.charge(llm=True)
        try:
            generated = runtime.generator.generate(question, chunks)
        except Exception:
            return _fallback_result()
        if not generated.answer.strip():
            return _fallback_result()
        if is_fallback_answer(generated.answer):
            return generated
        runtime.budget_tracker.context_tokens = max(
            estimated_tokens,
            generated.prompt_tokens or 0,
        )
        return generated

    @staticmethod
    def _link_verification_to_ledger(
        verification: VerificationResult,
        runtime: SpecialistRuntime,
    ) -> VerificationResult:
        def ledger_ids(chunk_ids: tuple[str, ...]) -> tuple[str, ...]:
            return tuple(sorted({
                ledger_id for chunk_id in chunk_ids
                if (ledger_id := runtime.preferred_evidence_by_chunk_id.get(chunk_id)
                    or runtime.evidence_id_by_chunk_id.get(chunk_id)) is not None
            }))

        linked_claims: list[ClaimAssessment] = []
        for claim in verification.claims:
            linked_claims.append(claim.model_copy(update={
                "evidence_ids": ledger_ids(claim.evidence_ids),
                "supporting_evidence_ids": ledger_ids(claim.supporting_evidence_ids),
            }))
        return verification.model_copy(update={"claims": tuple(linked_claims)})


def _ticker_lookup(router: ComplexityRouter, explicit: dict[str, str]) -> dict[str, str]:
    lookup = {
        alias.casefold(): ticker
        for ticker, aliases in DEFAULT_COMPANY_ALIASES.items()
        for alias in (ticker, *aliases)
    }
    corpus_map = getattr(router, "corpus_map", None)
    if corpus_map is not None:
        ticker_sets: dict[str, set[str]] = defaultdict(set)
        for document in corpus_map.documents:
            for company in document.company_names:
                ticker_sets[" ".join(company.casefold().split())].update(document.tickers)
        for company, tickers in ticker_sets.items():
            if len(tickers) == 1:
                lookup[company] = next(iter(tickers)).upper()
            elif len(tickers) > 1:
                lookup.pop(company, None)
    lookup.update({" ".join(key.casefold().split()): value.upper() for key, value in explicit.items()})
    return lookup


def _task_specific_query(task: ResearchTask) -> str:
    if not (task.company_name and task.metric_id and task.period):
        return (task.query or "").strip()
    metric = task.metric_id.replace("_", " ")
    return " ".join((task.company_name, metric, task.period, *task.form_types))


def _filing_query_groups(
    plan: ResearchPlan | None,
) -> dict[str, tuple[ResearchTask, ...]]:
    grouped: dict[str, list[ResearchTask]] = defaultdict(list)
    if plan is None:
        return {}
    for task in plan.tasks:
        if task.query is None or task.source_availability.value == "MISSING":
            continue
        query = _task_specific_query(task)
        normalized = " ".join(query.casefold().split())
        if normalized:
            grouped[normalized].append(task.model_copy(update={"query": query}))
    return {
        key: tuple(sorted(grouped[key], key=lambda item: item.task_id))
        for key in sorted(grouped)
    }


def _build_filing_assignments(
    *,
    plan: ResearchPlan | None,
    groups: dict[str, tuple[ResearchTask, ...]],
    budget: RouteBudget,
    wall_time_remaining: float,
) -> tuple[list[SpecialistTaskAssignment], list[SpecialistTaskResult]]:
    tasks = plan.tasks if plan else ()
    if not tasks:
        return [], []
    max_assignments = min(
        len(groups),
        budget.max_tool_calls,
        budget.max_retrieval_calls,
    )
    if wall_time_remaining <= 0 or budget.max_concurrency == 0:
        max_assignments = 0
    selected_groups = list(groups.items())[:max_assignments]
    selected_task_ids = {
        task.task_id for _, grouped_tasks in selected_groups for task in grouped_tasks
    }
    omitted_tasks = [
        task for task in tasks
        if task.task_id not in selected_task_ids
    ]
    pre_results: list[SpecialistTaskResult] = []
    if omitted_tasks:
        reason = "worker_budget_or_wall_time_reached" if groups else "task_has_no_retrieval_query"
        pre_results.append(SpecialistTaskResult(
            worker_id="filing_research_worker",
            status=SpecialistStatus.PARTIAL,
            task_ids=tuple(sorted(task.task_id for task in omitted_tasks)),
            missing_requirement_ids=tuple(sorted({req for task in omitted_tasks for req in task.requirement_ids})),
            observations=(SpecialistObservation(key="skipped_tasks", value=reason),),
        ))

    if not selected_groups:
        return [], pre_results

    base_candidates, extra_candidates = divmod(
        budget.max_candidate_chunks,
        len(selected_groups),
    )
    assignments: list[SpecialistTaskAssignment] = []
    for index, (normalized_query, grouped_tasks) in enumerate(selected_groups):
        candidate_limit = min(10, base_candidates + int(index < extra_candidates))
        if candidate_limit <= 0:
            pre_results.append(SpecialistTaskResult(
                worker_id="filing_research_worker",
                status=SpecialistStatus.PARTIAL,
                task_ids=tuple(task.task_id for task in grouped_tasks),
                missing_requirement_ids=tuple(sorted({req for task in grouped_tasks for req in task.requirement_ids})),
                observations=(SpecialistObservation(key="budget", value="candidate_budget_exhausted"),),
            ))
            continue
        task_ids = tuple(sorted(task.task_id for task in grouped_tasks))
        requirement_ids = tuple(sorted({req for task in grouped_tasks for req in task.requirement_ids}))
        assignment_id = f"query-{hashlib.sha256(normalized_query.encode('utf-8')).hexdigest()[:16]}"
        representative = grouped_tasks[0]
        metric = (representative.metric_id or "financial fact").replace("_", " ")
        objective = (
            f"Find {metric} for {representative.company_name or 'the requested company'}"
            + (f" in {representative.period}" if representative.period else "")
        )
        worker_budget = RouteBudget(
            max_graph_steps=1,
            max_tool_calls=1,
            max_retrieval_calls=1,
            max_llm_calls=0,
            max_candidate_chunks=candidate_limit,
            max_context_tokens=0,
            max_concurrency=1,
            max_wall_time_seconds=max(0.0, min(budget.max_wall_time_seconds, wall_time_remaining)),
            max_planned_tasks=len(grouped_tasks),
        )
        assignments.append(SpecialistTaskAssignment(
            task_id=assignment_id,
            task_ids=task_ids,
            objective=objective,
            allowed_tools=("filing_retriever.retrieve",),
            evidence_requirement_ids=requirement_ids,
            budget=worker_budget,
            tasks=grouped_tasks,
        ))
    return assignments, pre_results


def _ordered_report_chunks(runtime: SpecialistRuntime) -> list[dict[str, Any]]:
    return [
        runtime.source_chunks[key] for key in sorted(runtime.source_chunks)
        if not runtime.require_structured_facts
        or key in runtime.xbrl_chunk_ids
    ]


def _citation_number(runtime: SpecialistRuntime, chunk_id: str, order: dict[str, int]) -> int | None:
    index = order.get(chunk_id)
    if index is not None:
        return index
    record_id = runtime.preferred_evidence_by_chunk_id.get(chunk_id) or runtime.evidence_id_by_chunk_id.get(chunk_id)
    if record_id is None:
        try:
            record_id = runtime.ledger.evidence(chunk_id).evidence_id
        except Exception:
            return None
    record = runtime.ledger.evidence(record_id)
    return order.get(record.chunk_id or "")


def _render_lookup(runtime: SpecialistRuntime) -> str:
    coverage = runtime.coverage
    if coverage is None:
        return ""
    chunks = _ordered_report_chunks(runtime)
    order = {str(item["chunk_id"]): index for index, item in enumerate(chunks, start=1)}
    sentences: list[str] = []
    for finding in coverage.findings:
        value_facts = [fact for fact in finding.facts if fact.value]
        for fact in value_facts[:1]:
            citation_number = _citation_number(runtime, fact.evidence_id, order)
            citations = [citation_number] if citation_number is not None else []
            if not citations:
                continue
            entity = next(
                (item.canonical_name for item in coverage.requirements.entities if item.entity_id == fact.entity_id),
                fact.entity_id,
            )
            metric = next(
                (item.display_name for item in coverage.requirements.metrics if item.metric_id == fact.metric_id),
                fact.metric_id.replace("_", " "),
            )
            period = f" for {fact.period}" if fact.period else ""
            markers = " ".join(f"[Source {number}]" for number in citations)
            evidence_id = runtime.preferred_evidence_by_chunk_id.get(fact.evidence_id)
            provenance = runtime.ledger.evidence(evidence_id).xbrl_provenance if evidence_id else None
            basis = ""
            if provenance is not None and runtime.require_structured_facts:
                basis = {
                    RevisionKind.ORIGINAL: " in the original filing",
                    RevisionKind.REFILED: " in a later filing with the same value",
                    RevisionKind.AMENDMENT: " in the amended filing",
                    RevisionKind.COMPARATIVE_REVISION: " as revised in a later comparative filing",
                }[provenance.revision_kind]
            sentences.append(f"{entity} reported {metric} of {fact.value}{period}{basis}. {markers}")
    return " ".join(sentences)


def _render_calculations(runtime: SpecialistRuntime) -> str:
    return " ".join(statement for _, statement in _render_calculation_entries(runtime))


def _render_calculation_entries(runtime: SpecialistRuntime) -> list[tuple[DerivedCalculation, str]]:
    if not runtime.calculations:
        return []
    chunks = _ordered_report_chunks(runtime)
    order = {str(item["chunk_id"]): index for index, item in enumerate(chunks, start=1)}
    entries: list[tuple[DerivedCalculation, str]] = []
    snapshot = runtime.ledger.snapshot()
    evidence_by_id = {item.evidence_id: item for item in snapshot.evidence_records}
    for calculation in runtime.calculations:
        source_chunk_ids = {
            evidence_by_id[evidence_id].chunk_id
            for evidence_id in calculation.input_evidence_ids
            if evidence_id in evidence_by_id
            and evidence_by_id[evidence_id].chunk_id
        }
        citations = sorted({
            number for chunk_id in source_chunk_ids
            if (number := order.get(str(chunk_id))) is not None
        })
        if not citations:
            continue
        marker_text = " ".join(f"[Source {number}]" for number in citations)
        value = _decimal_text(calculation.result)
        basis = ""
        if runtime.require_structured_facts:
            basis = (
                " using the revised filing values"
                if runtime.xbrl_revision_policy == RevisionPolicy.LATEST
                else " using the original filing values"
            )
        if calculation.operation == "growth":
            sentence = (
                f"{calculation.company or 'The company'} {calculation.metric_id.replace('_', ' ')} "
                f"growth was {value}% from {calculation.fiscal_period}{basis}. {marker_text}"
            )
        else:
            unit = calculation.currency or calculation.unit or "units"
            sentence = (
                f"The absolute {calculation.metric_id.replace('_', ' ')} difference was "
                f"{unit} {value} across {calculation.fiscal_period}{basis}. {marker_text}"
            )
        entries.append((calculation, sentence))
    return entries


def _fallback_result() -> AnswerGenerationResult:
    return AnswerGenerationResult(
        answer=INSUFFICIENT_EVIDENCE_ANSWER,
        model_id="filingscope-no-answer",
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0.0,
    )


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _execution_status(status: str, verification: VerificationResult | None) -> str:
    if status == "UNSUPPORTED":
        return "UNSUPPORTED"
    if verification is None:
        return "ABSTAIN"
    return verification.disposition.value


__all__ = [
    "SpecialistExecution",
    "SpecialistExecutionStatus",
    "SpecialistResearchGraph",
    "SpecialistUsage",
]
