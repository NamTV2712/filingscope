"""Finite M7 specialist graph over the existing router, ledger, and P2/P4 APIs."""

from __future__ import annotations

import re
import time
import uuid
from decimal import Decimal
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict, Field

from src.agent.complexity_router import ComplexityRouter, ExecutionPath, RouterExecution
from src.agent.specialists import (
    EvidenceAnalyst,
    FilingResearchWorker,
    FinancialReasoner,
    SpecialistObservation,
    SpecialistRuntime,
    SpecialistStatus,
    SpecialistTaskResult,
    StructuredFinancialDataWorker,
    TableEvidenceWorker,
)
from src.decision.models import DecisionResult, EvidenceCoverage
from src.generation.answer_generator import (
    AnswerGenerationResult,
    AnswerGenerator,
    build_generation_messages,
    estimate_prompt_tokens,
    is_fallback_answer,
)
from src.ingestion.sec_client import SECEdgarClient
from src.ledger.evidence_ledger import EvidenceLedger
from src.ledger.models import (
    DerivedCalculation,
    GeneratedClaim,
    LedgerSnapshot,
)
from src.research.planner import ResearchPlan
from src.verification.claim_verifier import ClaimLevelVerifier
from src.verification.models import ClaimAssessment, ResponseDisposition, VerificationResult


SpecialistExecutionStatus = Literal[
    "VERIFIED", "PARTIAL", "REJECTED", "ABSTAIN", "UNSUPPORTED"
]


class SpecialistUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    graph_steps: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    retrieval_calls: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    candidate_chunks: int = Field(ge=0)
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


class SpecialistResearchGraph:
    """Execute a fixed FAST or RESEARCH sequence with route-specific ceilings.

    The graph runs no worker fan-out, checkpointing, or autonomous loops. FAST
    has four execution nodes; RESEARCH has eight. UNSUPPORTED has one terminal
    node and performs no downstream retrieval, SEC, or model call.
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
    ):
        self.router = router or ComplexityRouter()
        self.retriever = retriever
        self.sec_client = sec_client
        self.generator = generator
        self.verifier = verifier or ClaimLevelVerifier()
        self.ticker_by_company = _ticker_lookup(self.router, ticker_by_company or {})
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
        )
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
        }
        state = self.graph.invoke(
            initial,
            context=runtime,
            config={"recursion_limit": max(2, allowed_steps + 3)},
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
            candidate_chunks=runtime.budget_tracker.candidate_chunks,
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
        graph.add_edge("supervisor", "filing_worker")
        graph.add_edge("structured_data_worker", "table_worker")
        graph.add_edge("table_worker", "evidence_analyst")
        graph.add_edge("financial_reasoner", "report_writer")
        graph.add_edge("report_writer", "claim_verifier")
        graph.add_edge("claim_verifier", END)
        # FAST branches around the RESEARCH-only specialists.
        graph.add_conditional_edges(
            "filing_worker",
            self._after_filing,
            {
                "fast": "evidence_analyst",
                "research": "structured_data_worker",
            },
        )
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
    def _after_filing(state: _SpecialistGraphState) -> str:
        return "fast" if state["route"].selected_path == ExecutionPath.FAST else "research"

    @staticmethod
    def _after_analyst(state: _SpecialistGraphState) -> str:
        return "fast" if state["route"].selected_path == ExecutionPath.FAST else "research"

    def _supervisor_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime]
    ) -> dict[str, Any]:
        context = runtime.context
        context.register_plan()
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
            )),
        )
        context.save_result(result)
        return {
            "trace": [*state.get("trace", ()), "supervisor"],
            "specialist_results": [*state.get("specialist_results", ()), result],
        }

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

    def _structured_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime]
    ) -> dict[str, Any]:
        task_result = StructuredFinancialDataWorker(runtime.context.sec_client).run(
            tuple(state.get("plan").tasks if state.get("plan") else ()),
            runtime.context,
        )
        return {
            "trace": [*state.get("trace", ()), "structured_data_worker"],
            "specialist_results": [*state.get("specialist_results", ()), task_result],
            "evidence_ids": sorted(set(state.get("evidence_ids", ())) | set(task_result.evidence_ids)),
        }

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
        verification = context.verifier.verify(
            state["question"],
            state.get("answer", ""),
            _ordered_report_chunks(context),
        )
        verification = self._link_verification_to_ledger(verification, context)
        for assessment in verification.claims:
            calculation_id = _calculation_for_claim(assessment, context)
            claim = GeneratedClaim.create(
                claim_id=assessment.claim_id,
                request_id=context.request_id,
                claim_text=assessment.statement,
                claim_type=assessment.status.value,
                supporting_evidence_ids=assessment.evidence_ids,
                calculation_id=calculation_id,
                requirement_ids=tuple(item.requirement_id for item in context.requirements.evidence),
            )
            context.ledger.add_claim(claim)
        context.verification = verification
        context.ledger.add_verification(
            verification,
            verifier_id="claim-level-verifier",
            verifier_version="P4",
        )
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
            observations=(SpecialistObservation(key="disposition", value=verification.disposition.value),),
        )
        context.save_result(result)
        return {
            "trace": [*state.get("trace", ()), "claim_verifier"],
            "specialist_results": [*state.get("specialist_results", ()), result],
            "status": verification.disposition.value,
        }

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
        if runtime.generator is None:
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
        linked_claims: list[ClaimAssessment] = []
        for claim in verification.claims:
            evidence_ids = tuple(sorted({
                runtime.preferred_evidence_by_chunk_id.get(chunk_id)
                or runtime.evidence_id_by_chunk_id.get(chunk_id)
                for chunk_id in claim.evidence_ids
                if runtime.preferred_evidence_by_chunk_id.get(chunk_id)
                or runtime.evidence_id_by_chunk_id.get(chunk_id)
            }))
            linked_claims.append(claim.model_copy(update={"evidence_ids": evidence_ids}))
        return verification.model_copy(update={"claims": tuple(linked_claims)})


def _ticker_lookup(router: ComplexityRouter, explicit: dict[str, str]) -> dict[str, str]:
    lookup = {" ".join(key.casefold().split()): value.upper() for key, value in explicit.items()}
    corpus_map = getattr(router, "corpus_map", None)
    if corpus_map is None:
        return lookup
    for document in corpus_map.documents:
        tickers = tuple(value.upper() for value in document.tickers)
        for company in document.company_names:
            if company and tickers:
                lookup.setdefault(" ".join(company.casefold().split()), tickers[0])
    return lookup


def _ordered_report_chunks(runtime: SpecialistRuntime) -> list[dict[str, Any]]:
    return [runtime.source_chunks[key] for key in sorted(runtime.source_chunks)]


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
            sentences.append(f"{entity} reported {metric} of {fact.value}{period}. {markers}")
    return " ".join(sentences)


def _render_calculations(runtime: SpecialistRuntime) -> str:
    chunks = _ordered_report_chunks(runtime)
    order = {str(item["chunk_id"]): index for index, item in enumerate(chunks, start=1)}
    sentences: list[str] = []
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
        if calculation.operation == "growth":
            sentence = (
                f"{calculation.company or 'The company'} {calculation.metric_id.replace('_', ' ')} "
                f"growth was {value}% from {calculation.fiscal_period}. {marker_text}"
            )
        else:
            unit = calculation.currency or calculation.unit or "units"
            sentence = (
                f"The absolute {calculation.metric_id.replace('_', ' ')} difference was "
                f"{unit} {value} across {calculation.fiscal_period}. {marker_text}"
            )
        sentences.append(sentence)
    return " ".join(sentences)


def _calculation_for_claim(
    claim: ClaimAssessment,
    runtime: SpecialistRuntime,
) -> str | None:
    cited = set(claim.evidence_ids)
    for calculation in runtime.calculations:
        input_chunks = {
            runtime.ledger.evidence(evidence_id).chunk_id
            for evidence_id in calculation.input_evidence_ids
        }
        supporting = {
            runtime.preferred_evidence_by_chunk_id.get(str(chunk_id))
            or runtime.evidence_id_by_chunk_id.get(str(chunk_id))
            for chunk_id in input_chunks if chunk_id
        }
        supporting.discard(None)
        if supporting and supporting.issubset(cited):
            return calculation.calculation_id
    return None


def _fallback_result() -> AnswerGenerationResult:
    return AnswerGenerationResult(
        answer="I could not find sufficient information in the available documents to answer this question with confidence.",
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
