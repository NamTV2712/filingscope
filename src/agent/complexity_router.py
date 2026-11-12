"""Deterministic complexity routing on a finite LangGraph state graph."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from src.decision.requirement_extractor import EvidenceRequirementExtractor, requires_nonstandard_reporting_basis
from src.ingestion.company_facts import METRIC_CONCEPTS, requested_revision_policies
from src.research.corpus_map import CorpusMap
from src.research.planner import (
    CorpusAwarePlanner,
    QuestionOnlyPlanner,
    ResearchPlan,
)

ROUTER_VERSION = "1.1.0"

_DEEP_RE = re.compile(
    r"\b(?:comprehensive|thorough|in[- ]depth|deep research|full financial profile|"
    r"every available filing|all available filings|across all filings)\b",
    re.I,
)
_MULTI_HOP_RE = re.compile(
    r"\b(?:why|explain|cause[sd]?|drove|drive[sn]?|affect(?:ed|s)?|impact(?:ed|s)?|"
    r"influenc(?:e[sd]?|ing)|relationship|trace|reconcile)\b",
    re.I,
)
_COMPARATIVE_RE = re.compile(
    r"\b(?:compare|versus|vs\.?|which company|which (?:one|firm)|faster|slower)\b",
    re.I,
)
_SINGLE_DOCUMENT_RE = re.compile(
    r"\b(?:10\s*[-–]?\s*[kq]|annual report|filing|earnings release)\b",
    re.I,
)
_NUMERICAL_RE = re.compile(
    r"\b(?:calculate|compute|growth|grow(?:s|th|ing)?|increase[sd]?|decrease[sd]?|"
    r"difference|ratio|average|mean|cagr|higher|lower)\b",
    re.I,
)
_PREDICTIVE_RE = re.compile(
    r"\b(?:predict(?:s|ed|ions?)?|forecast(?:s|ed|ing)?|recommend|investment advice|should i buy|should i sell|"
    r"stock price|share price|market price)\b",
    re.I,
)
_FUTURE_PERIOD_RE = re.compile(
    r"\b(?:next|upcoming|future)\s+(?:fiscal\s+)?(?:year|quarter|month)\b",
    re.I,
)
_STATEMENT_SOURCE_RE = re.compile(
    r"\b(?:consolidated\s+(?:statement|balance sheet)|income statements?|balance sheets?|"
    r"cash flow statements?|statement of (?:income|operations|earnings|cash flows|financial position))\b",
    re.I,
)
_SPECIAL_BASIS_RE = re.compile(
    r"\b(?:segment|continuing operations|discontinued operations|excluding|in the notes|restatement)\b",
    re.I,
)
_XBRL_PERIOD_RE = re.compile(r"(?:Q[1-4] (?:YTD )?)?FY(?:19|20)\d{2}")


class ComplexityClass(StrEnum):
    SIMPLE_LOOKUP = "SIMPLE_LOOKUP"
    SINGLE_DOCUMENT = "SINGLE_DOCUMENT"
    NUMERICAL = "NUMERICAL"
    COMPARATIVE = "COMPARATIVE"
    MULTI_HOP = "MULTI_HOP"
    DEEP_RESEARCH = "DEEP_RESEARCH"
    UNSUPPORTED = "UNSUPPORTED"


class ExecutionPath(StrEnum):
    FAST = "FAST"
    RESEARCH = "RESEARCH"
    UNSUPPORTED = "UNSUPPORTED"


class SourceCapability(StrEnum):
    DIRECT_XBRL = "DIRECT_XBRL"
    DIRECT_TABLE = "DIRECT_TABLE"
    TEXT_RAG = "TEXT_RAG"
    COMPOSITE = "COMPOSITE"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class SourceInventory:
    xbrl_entities: frozenset[str] = frozenset()
    statement_documents: frozenset[str] = frozenset()


class RouteBudget(BaseModel):
    """Hard per-request ceilings used when later milestones execute a route."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    max_graph_steps: int = Field(ge=0, le=16)
    max_tool_calls: int = Field(ge=0, le=24)
    max_retrieval_calls: int = Field(ge=0, le=16)
    max_llm_calls: int = Field(ge=0, le=8)
    max_candidate_chunks: int = Field(ge=0, le=100)
    max_context_tokens: int = Field(ge=0, le=100_000)
    max_concurrency: int = Field(ge=0, le=8)
    max_wall_time_seconds: float = Field(ge=0, le=300, allow_inf_nan=False)
    max_planned_tasks: int = Field(ge=0, le=16)


FAST_BUDGET = RouteBudget(
    max_graph_steps=4,
    max_tool_calls=3,
    max_retrieval_calls=2,
    max_llm_calls=1,
    max_candidate_chunks=10,
    max_context_tokens=8_000,
    max_concurrency=1,
    max_wall_time_seconds=15.0,
    max_planned_tasks=2,
)
RESEARCH_BUDGET = RouteBudget(
    max_graph_steps=8,
    max_tool_calls=10,
    max_retrieval_calls=6,
    max_llm_calls=3,
    max_candidate_chunks=50,
    max_context_tokens=24_000,
    max_concurrency=3,
    max_wall_time_seconds=60.0,
    max_planned_tasks=6,
)
UNSUPPORTED_BUDGET = RouteBudget(
    max_graph_steps=2,
    max_tool_calls=0,
    max_retrieval_calls=0,
    max_llm_calls=0,
    max_candidate_chunks=0,
    max_context_tokens=0,
    max_concurrency=0,
    max_wall_time_seconds=0.0,
    max_planned_tasks=0,
)


class ComplexityDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    router_version: str = ROUTER_VERSION
    complexity: ComplexityClass
    path: ExecutionPath
    reason_codes: tuple[str, ...] = ()
    entity_count: int = Field(ge=0)
    metric_count: int = Field(ge=0)
    period_count: int = Field(ge=0)
    requirements_supported: bool
    requires_clarification: bool = False


class RouterExecution(BaseModel):
    """Inspectable route decision and bounded task plan, without executing tools."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    question: str
    decision: ComplexityDecision
    selected_path: ExecutionPath
    source_capability: SourceCapability = SourceCapability.TEXT_RAG
    budget: RouteBudget
    research_plan: ResearchPlan | None = None
    route_trace: tuple[str, ...] = ()
    graph_steps_used: int = Field(ge=0)
    planned_task_count: int = Field(ge=0)
    planned_retrieval_calls: int = Field(ge=0)
    actual_retrieval_calls: int = Field(default=0, ge=0)
    planned_llm_calls: int = Field(default=0, ge=0)
    actual_llm_calls: int = Field(default=0, ge=0)
    actual_tool_calls: int = Field(default=0, ge=0)
    actual_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    routing_latency_ms: float = Field(ge=0, allow_inf_nan=False)


class _RouterGraphState(TypedDict, total=False):
    question: str
    force_research: bool
    source_inventory: SourceInventory | None
    decision: ComplexityDecision
    selected_path: str
    budget: RouteBudget
    research_plan: ResearchPlan | None
    planned_retrieval_calls: int
    planned_task_count: int
    source_capability: SourceCapability
    route_trace: list[str]


class ComplexityRouter:
    """Classify a question and select a bounded fast or research path.

    The LangGraph graph performs deterministic routing and task planning only.
    It does not call a retriever, model, provider, or agent.
    """

    def __init__(
        self,
        corpus_map: CorpusMap | None = None,
        *,
        fast_budget: RouteBudget = FAST_BUDGET,
        research_budget: RouteBudget = RESEARCH_BUDGET,
    ):
        for budget, default in ((fast_budget, FAST_BUDGET), (research_budget, RESEARCH_BUDGET)):
            if budget.max_graph_steps < default.max_graph_steps:
                raise ValueError(f"the route requires {default.max_graph_steps} graph steps")
            if min(budget.max_planned_tasks, budget.max_retrieval_calls) < 1:
                raise ValueError("supported routes require a positive planning and retrieval limit")
        self.corpus_map = corpus_map
        self.fast_budget = fast_budget
        self.research_budget = research_budget
        if corpus_map is None:
            self.extractor = EvidenceRequirementExtractor()
        else:
            rows = [
                {"company": company, "ticker": ticker}
                for document in corpus_map.documents
                for company in document.company_names
                for ticker in (document.tickers or (None,))
            ]
            self.extractor = EvidenceRequirementExtractor.from_document_rows(rows)
        self.graph = self._build_graph()

    def classify(self, question: str) -> ComplexityDecision:
        requirements = self.extractor.extract(question)
        entities = len(requirements.entities)
        metrics = len(requirements.metrics)
        periods = len(requirements.periods)
        reason_codes: list[str] = []
        unsupported = set(requirements.unsupported_reasons)

        predictive = bool(_PREDICTIVE_RE.search(question))
        future_period = bool(_FUTURE_PERIOD_RE.search(question))
        unresolved = bool(
            unsupported.intersection({"company_not_resolved", "metric_not_recognized"})
        )
        insufficient_scope = "insufficient_period_scope" in unsupported
        revisions = requested_revision_policies(question)
        if predictive:
            complexity = ComplexityClass.UNSUPPORTED
            path = ExecutionPath.UNSUPPORTED
            reason_codes.append("predictive_or_advisory_request_unsupported")
        elif future_period:
            complexity = ComplexityClass.UNSUPPORTED
            path = ExecutionPath.UNSUPPORTED
            reason_codes.append("future_reporting_period_requires_clarification")
        elif insufficient_scope:
            complexity = ComplexityClass.UNSUPPORTED
            path = ExecutionPath.UNSUPPORTED
            reason_codes.append("operation_missing_required_period_scope")
        elif unresolved or not requirements.supported:
            complexity = ComplexityClass.UNSUPPORTED
            path = ExecutionPath.UNSUPPORTED
            reason_codes.extend(sorted(unsupported or {"question_requirements_unsupported"}))
        elif len(revisions) > 1:
            complexity = ComplexityClass.UNSUPPORTED
            path = ExecutionPath.UNSUPPORTED
            reason_codes.append("mixed_filing_revision_request")
        elif revisions:
            complexity = ComplexityClass.MULTI_HOP
            path = ExecutionPath.RESEARCH
            reason_codes.append("explicit_filing_revision_requested")
        elif _DEEP_RE.search(question) or (metrics >= 3 and periods >= 3):
            complexity = ComplexityClass.DEEP_RESEARCH
            path = ExecutionPath.RESEARCH
            reason_codes.append("broad_or_multi_year_scope")
        elif _MULTI_HOP_RE.search(question):
            complexity = ComplexityClass.MULTI_HOP
            path = ExecutionPath.RESEARCH
            reason_codes.append("causal_or_cross_requirement_reasoning")
        elif entities > 1 or _COMPARATIVE_RE.search(question):
            complexity = ComplexityClass.COMPARATIVE
            path = ExecutionPath.RESEARCH
            reason_codes.append("cross_entity_or_explicit_comparison")
        elif _NUMERICAL_RE.search(question) or any(
            operation.operation in {"growth", "difference", "ratio", "average"}
            for operation in requirements.operations
        ):
            complexity = ComplexityClass.NUMERICAL
            if entities == 1 and metrics <= 2 and periods <= 2:
                path = ExecutionPath.FAST
                reason_codes.append("bounded_single_entity_calculation")
            else:
                path = ExecutionPath.RESEARCH
                reason_codes.append("calculation_scope_exceeds_fast_profile")
        elif entities == 1 and metrics > 0 and _SINGLE_DOCUMENT_RE.search(question):
            complexity = ComplexityClass.SINGLE_DOCUMENT
            path = ExecutionPath.FAST
            reason_codes.append("explicit_single_filing_scope")
        elif entities == 1 and metrics == 1 and periods == 1:
            complexity = ComplexityClass.SIMPLE_LOOKUP
            path = ExecutionPath.FAST
            reason_codes.append("single_metric_single_period_lookup")
        elif entities == 1 and metrics > 0 and periods <= 1 and metrics <= 2:
            complexity = ComplexityClass.SINGLE_DOCUMENT
            path = ExecutionPath.FAST
            reason_codes.append("bounded_single_company_request")
        elif entities == 1 and metrics > 0:
            complexity = ComplexityClass.MULTI_HOP
            path = ExecutionPath.RESEARCH
            reason_codes.append("multi_period_or_multi_metric_research")
        else:
            complexity = ComplexityClass.UNSUPPORTED
            path = ExecutionPath.UNSUPPORTED
            reason_codes.append("question_requirements_unresolved")

        return ComplexityDecision(
            complexity=complexity,
            path=path,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            entity_count=entities,
            metric_count=metrics,
            period_count=periods,
            requirements_supported=requirements.supported and not predictive and not future_period,
            requires_clarification=(
                future_period
                or bool(
                    unsupported.intersection(
                        {
                            "company_not_resolved",
                            "metric_not_recognized",
                            "insufficient_period_scope",
                            "relative_period_not_supported",
                        }
                    )
                )
            ),
        )

    def route(
        self, question: str, *, force_research: bool = False, source_inventory: SourceInventory | None = None,
    ) -> RouterExecution:
        started = time.perf_counter()
        state = self.graph.invoke({
            "question": question, "route_trace": [], "force_research": force_research,
            "source_inventory": source_inventory,
        })
        elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000)
        decision = state["decision"]
        budget = state["budget"]
        graph_steps_used = len(state.get("route_trace", ()))
        planned_retrieval_calls = state.get("planned_retrieval_calls", 0)
        planned_task_count = state.get("planned_task_count", 0)
        if graph_steps_used > budget.max_graph_steps:
            raise RuntimeError("router graph steps exceed the selected route budget")
        if planned_task_count > budget.max_planned_tasks:
            raise RuntimeError("planned research tasks exceed the selected route budget")
        if planned_retrieval_calls > budget.max_retrieval_calls:
            raise RuntimeError("planned retrieval calls exceed the selected route budget")
        return RouterExecution(
            question=question,
            decision=decision,
            selected_path=ExecutionPath(state["selected_path"]),
            source_capability=state.get("source_capability", SourceCapability.TEXT_RAG),
            budget=budget,
            research_plan=state.get("research_plan"),
            route_trace=tuple(state.get("route_trace", ())),
            graph_steps_used=graph_steps_used,
            planned_task_count=planned_task_count,
            planned_retrieval_calls=planned_retrieval_calls,
            actual_retrieval_calls=0,
            planned_llm_calls=0,
            actual_llm_calls=0,
            routing_latency_ms=elapsed_ms,
        )

    def _build_graph(self):
        graph = StateGraph(_RouterGraphState)
        graph.add_node("classify_request", self._classify_node)
        graph.add_node("fast_path", self._fast_path_node)
        graph.add_node("research_path", self._research_path_node)
        graph.add_node("unsupported_path", self._unsupported_path_node)
        graph.add_edge(START, "classify_request")
        graph.add_conditional_edges(
            "classify_request",
            self._dispatch,
            {
                ExecutionPath.FAST.value: "fast_path",
                ExecutionPath.RESEARCH.value: "research_path",
                ExecutionPath.UNSUPPORTED.value: "unsupported_path",
            },
        )
        graph.add_edge("fast_path", END)
        graph.add_edge("research_path", END)
        graph.add_edge("unsupported_path", END)
        return graph.compile()

    def _classify_node(self, state: _RouterGraphState) -> dict[str, Any]:
        decision = self.classify(state["question"])
        if state.get("force_research") and decision.path == ExecutionPath.FAST:
            decision = decision.model_copy(update={
                "path": ExecutionPath.RESEARCH,
                "reason_codes": (*decision.reason_codes, "research_route_requested"),
            })
        return {
            "decision": decision,
            "route_trace": ["classify_request"],
        }

    @staticmethod
    def _dispatch(state: _RouterGraphState) -> str:
        return state["decision"].path.value

    def _fast_path_node(self, state: _RouterGraphState) -> dict[str, Any]:
        return self._prepare_execution(state, ExecutionPath.FAST, self.fast_budget, "fast_path")

    def _research_path_node(self, state: _RouterGraphState) -> dict[str, Any]:
        return self._prepare_execution(state, ExecutionPath.RESEARCH, self.research_budget, "research_path")

    @staticmethod
    def _unsupported_path_node(state: _RouterGraphState) -> dict[str, Any]:
        return {
            "selected_path": ExecutionPath.UNSUPPORTED.value,
            "source_capability": SourceCapability.UNSUPPORTED,
            "budget": UNSUPPORTED_BUDGET,
            "research_plan": None,
            "planned_task_count": 0,
            "planned_retrieval_calls": 0,
            "route_trace": [*state.get("route_trace", ()), "unsupported_path"],
        }

    def _prepare_execution(
        self,
        state: _RouterGraphState,
        path: ExecutionPath,
        budget: RouteBudget,
        node_name: str,
    ) -> dict[str, Any]:
        question = state["question"]
        max_tasks = min(budget.max_planned_tasks, budget.max_retrieval_calls)
        if self.corpus_map is None:
            plan = QuestionOnlyPlanner(max_tasks=max_tasks).plan(question)
        else:
            plan = CorpusAwarePlanner(
                self.corpus_map,
                max_tasks=max_tasks,
            ).plan(question)
        if len(plan.tasks) > budget.max_planned_tasks:
            raise RuntimeError("planned research tasks exceed the selected route budget")
        if plan.retrieval_call_count > budget.max_retrieval_calls:
            raise RuntimeError("planned retrieval calls exceed the selected route budget")
        return {
            "selected_path": path.value,
            "source_capability": self._source_capability(state, path, plan),
            "budget": budget,
            "research_plan": plan,
            "planned_task_count": len(plan.tasks),
            "planned_retrieval_calls": plan.retrieval_call_count,
            "route_trace": [*state.get("route_trace", ()), node_name],
        }

    def _source_capability(self, state: _RouterGraphState, path: ExecutionPath, plan: ResearchPlan) -> SourceCapability:
        if path == ExecutionPath.RESEARCH:
            return SourceCapability.COMPOSITE
        inventory = state.get("source_inventory")
        if inventory is None:
            return SourceCapability.TEXT_RAG
        question = state["question"]
        requirements = self.extractor.extract(question)
        if len(requirements.evidence) > 1:
            return SourceCapability.COMPOSITE
        if (
            len(requirements.evidence) != 1 or not requirements.evidence[0].quantitative
            or requirements.evidence[0].period is None
            or any(item.operation != "lookup" for item in requirements.operations)
            or _SPECIAL_BASIS_RE.search(question) or requires_nonstandard_reporting_basis(question)
        ):
            return SourceCapability.TEXT_RAG
        slot = requirements.evidence[0]
        task = next((task for task in plan.tasks if slot.requirement_id in task.requirement_ids), None)
        has_table = bool(task and inventory.statement_documents.intersection(task.target_document_ids))
        if _STATEMENT_SOURCE_RE.search(question):
            return SourceCapability.DIRECT_TABLE if has_table else SourceCapability.TEXT_RAG
        supported_forms = {"10k", "10q", "20f", "40f"}
        if (
            task is not None and slot.entity_id in inventory.xbrl_entities
            and slot.metric_id in METRIC_CONCEPTS and _XBRL_PERIOD_RE.fullmatch(slot.period or "")
            and (not task.form_types or supported_forms.intersection(task.form_types))
        ):
            return SourceCapability.DIRECT_XBRL
        return SourceCapability.DIRECT_TABLE if has_table else SourceCapability.TEXT_RAG


__all__ = [
    "ComplexityClass",
    "ComplexityDecision",
    "ComplexityRouter",
    "ExecutionPath",
    "FAST_BUDGET",
    "RESEARCH_BUDGET",
    "ROUTER_VERSION",
    "RouteBudget",
    "RouterExecution",
    "SourceCapability",
    "SourceInventory",
    "UNSUPPORTED_BUDGET",
]
