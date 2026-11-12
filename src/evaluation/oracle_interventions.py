"""Diagnostic-only interventions around the existing specialist graph."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from langgraph.runtime import Runtime

from src.agent.complexity_router import ExecutionPath
from src.agent.specialist_graph import SpecialistResearchGraph, _SpecialistGraphState, _ordered_report_chunks
from src.agent.specialists import FinancialReasoner, SpecialistRuntime
from src.decision.models import CoverageStatus, QuestionRequirements
from src.generation.answer_generator import is_fallback_answer
from src.ledger.models import EvidenceRecord, EvidenceSourceType


class Oracle(StrEnum):
    REQUIREMENTS = "A"
    ROUTE = "B"
    LOCATION = "C"
    NORMALIZED_FACTS = "D"
    SUFFICIENCY = "E"
    CONSTRUCTION = "F"
    VERIFICATION = "G"


@dataclass(frozen=True)
class OracleResult:
    intervention: Oracle
    executed: bool
    reason: str
    independently_grounded_exact: bool | None = None
    answered: bool | None = None
    release_disposition: str | None = None


class FixedRequirements:
    """Request-local override used only by the evaluation router and analyst."""

    def __init__(self, extractor, requirements: QuestionRequirements):
        self.extractor = extractor
        self.catalog = extractor.catalog
        self.requirements = requirements

    def extract(self, question: str) -> QuestionRequirements:
        if question == self.requirements.question:
            return self.requirements
        return self.extractor.extract(question)


class DiagnosticGraph(SpecialistResearchGraph):
    """Inspect a real replay or change one boundary for a labeled experiment."""

    def __init__(
        self, *, oracle: Oracle | None = None, injected: tuple[dict, ...] = (),
        source_text_overrides: dict[str, str] | None = None, **kwargs,
    ):
        self.oracle = oracle
        self.injected = injected
        self.source_text_overrides = source_text_overrides or {}
        self.runtime: SpecialistRuntime | None = None
        self.pre_policy: tuple[dict, ...] = ()
        self.draft = ""
        self.draft_chunks: tuple[dict, ...] = ()
        super().__init__(**kwargs)

    def _analyst_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime],
    ) -> dict[str, Any]:
        context = runtime.context
        self.runtime = context
        if self.oracle == Oracle.NORMALIZED_FACTS:
            # Replace competing parses of these physical pages only.
            replaced = {(row["doc_name"], row["page_number"]) for row in self.injected}
            for key, chunk in tuple(context.source_chunks.items()):
                if (chunk.get("doc_name"), chunk.get("page_number")) in replaced:
                    del context.source_chunks[key]
            for key, text in self.source_text_overrides.items():
                if key in context.source_chunks:
                    context.source_chunks[key] = {**context.source_chunks[key], "text": text}
        for row in self.injected:
            chunk_id = row["chunk_id"]
            record = context.ledger.add_evidence(EvidenceRecord.from_source(
                request_id=context.request_id, document_id=row["doc_name"], chunk_id=chunk_id,
                company=row["company"], ticker=row.get("ticker"), form_type=row.get("doc_type"),
                page=row["page_number"] + 1, source_url=row["source_url"],
                source_type=EvidenceSourceType.TABLE_EVIDENCE, table_id=chunk_id,
                discovered_by=("offline_oracle",),
            ))
            context.source_chunks[chunk_id] = row
            context.evidence_id_by_chunk_id[chunk_id] = record.evidence_id
            context.preferred_evidence_by_chunk_id[chunk_id] = record.evidence_id
        self.pre_policy = tuple(
            chunk for key, chunk in sorted(context.source_chunks.items())
            if not context.require_structured_facts or key in context.xbrl_chunk_ids
        )
        result = super()._analyst_node(state, runtime)
        if self.oracle == Oracle.SUFFICIENCY and context.coverage is not None:
            context.coverage = context.coverage.model_copy(update={"sufficient": True})
            # FAST can run the reasoner inside the analyst. The evaluation
            # harness repeats it after applying the sufficiency intervention.
            if state["route"].selected_path == ExecutionPath.FAST and any(
                item.operation in {"growth", "difference"} for item in context.requirements.operations
            ):
                FinancialReasoner().run(context)
        return result

    def _writer_node(
        self, state: _SpecialistGraphState, runtime: Runtime[SpecialistRuntime],
    ) -> dict[str, Any]:
        result = super()._writer_node(state, runtime)
        context = runtime.context
        if self.oracle == Oracle.CONSTRUCTION and (reference := reference_answer(context)):
            result["answer"] = reference
            result["generation"] = result["generation"].model_copy(update={"answer": reference})
        self.draft = result["answer"]
        self.draft_chunks = tuple(_ordered_report_chunks(context))
        return result


def reference_answer(runtime: SpecialistRuntime) -> str:
    """Render only consensus facts or validated calculations, without labels."""
    coverage = runtime.coverage
    if coverage is None or not coverage.sufficient:
        return ""
    chunks = _ordered_report_chunks(runtime)
    citation_order = {row["chunk_id"]: number for number, row in enumerate(chunks, 1)}
    entities = {item.entity_id: item.canonical_name for item in runtime.requirements.entities}
    metrics = {item.metric_id: item.display_name for item in runtime.requirements.metrics}
    statements = []
    if any(item.operation in {"growth", "difference", "ratio", "average"}
           for item in runtime.requirements.operations):
        for calculation in runtime.calculations:
            chunk_ids = {runtime.ledger.evidence(item).chunk_id for item in calculation.input_evidence_ids}
            if not chunk_ids.issubset(citation_order):
                return ""
            markers = " ".join(f"[Source {number}]" for number in sorted(citation_order[item] for item in chunk_ids))
            value = format(calculation.result.normalize(), ",f")
            unit = calculation.currency or calculation.unit or ""
            if calculation.operation == "growth":
                amount = f"{value}%"
            else:
                amount = f"{unit} {value}"
            statements.append(
                f"{calculation.company} {metrics[calculation.metric_id]} {calculation.operation} "
                f"was {amount} across {calculation.fiscal_period}. {markers}"
            )
        return " ".join(statements)
    for slot in coverage.findings:
        eligible = [fact for fact in slot.facts if fact.value and fact.evidence_id in citation_order]
        if slot.status != CoverageStatus.FOUND or not eligible:
            return ""
        fact = min(eligible, key=lambda item: (
            chunks[citation_order[item.evidence_id] - 1].get("source_type") != EvidenceSourceType.XBRL_FACT,
            citation_order[item.evidence_id],
        ))
        statements.append(
            f"{entities[fact.entity_id]} reported {metrics[fact.metric_id]} "
            f"of {fact.value} for {fact.period}. [Source {citation_order[fact.evidence_id]}]"
        )
    return " ".join(statements)


def draft_exists(draft: str) -> bool:
    return bool(draft.strip()) and not is_fallback_answer(draft)
