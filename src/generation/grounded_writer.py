"""Write from the same approved evidence and citation order used for release."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from threading import Lock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from configs.end_to_end import GENERATOR_MAX_INPUT_TOKENS, GENERATOR_MAX_OUTPUT_TOKENS, GENERATOR_MODEL_ID
from src.decision.filing_disclosures import filing_industry_relations
from src.decision.models import EvidenceCoverage, EvidenceFact, QuestionRequirements
from src.generation.answer_generator import (
    AnswerGenerationResult, AnswerGenerator, GroqAnswerGenerator, build_generation_messages, estimate_max_cost_usd,
    estimate_prompt_tokens, estimate_prompt_tokens_with_margin,
)
from src.ingestion.company_facts import RevisionKind, RevisionPolicy
from src.ledger.models import DerivedCalculation, EvidenceRecord
from src.verification.response_policy import INSUFFICIENT_EVIDENCE_ANSWER


@dataclass(frozen=True)
class ApprovedSource:
    chunk: Mapping[str, Any]
    records: tuple[EvidenceRecord, ...]
    facts: tuple[EvidenceFact, ...]


@dataclass(frozen=True)
class GroundedReportInput:
    requirements: QuestionRequirements
    coverage: EvidenceCoverage | None
    sources: tuple[ApprovedSource, ...]
    calculations: tuple[DerivedCalculation, ...]
    revision_policy: RevisionPolicy | None = None
    deterministic_lookup: bool = False

    @property
    def verification_chunks(self) -> list[dict[str, Any]]:
        return [{**source.chunk, "approved_facts": source.facts} for source in self.sources]

    @property
    def source_numbers(self) -> dict[str, int]:
        return {source.chunk["chunk_id"]: number for number, source in enumerate(self.sources, start=1)}

    @property
    def arithmetic(self) -> set[tuple[str, str, str]]:
        return {
            (operation.operation, entity.canonical_name, metric.metric_id)
            for operation in self.requirements.operations
            if operation.operation in {"growth", "difference", "ratio", "average", "cagr"}
            for entity in self.requirements.entities
            for metric in self.requirements.metrics
            if metric.quantitative and operation.metric_id in (None, metric.metric_id)
        }

    @property
    def sufficient(self) -> bool:
        approved = {source.chunk["chunk_id"] for source in self.sources}
        return bool(self.coverage and self.coverage.sufficient and approved and all(
            any(fact.evidence_id in approved for fact in finding.facts) for finding in self.coverage.findings
        ))

    def provider_chunks(self) -> list[dict[str, Any]]:
        """Render numeric observations from accepted facts and preserve citation positions."""
        result = []
        for source in self.sources:
            record = source.records[0]
            lines = [f"Filing: {record.document_id}; source ID: {record.evidence_id}"]
            if record.xbrl_provenance:
                lines.append(f"Accession: {record.xbrl_provenance.accession}")
            for fact in source.facts:
                if fact.value:
                    lines.append(fact_sentence(self.requirements, fact).rstrip("."))
            if any(fact.value_kind == "topic" for fact in source.facts):
                text = source.chunk.get("text", "")
                if isinstance(text, str):
                    lines.append(f"<filing_excerpt>\n{text}\n</filing_excerpt>")
            result.append({"doc_name": record.document_id, "page_number": source.chunk.get("page_number"),
                           "text": "\n".join(lines)})
        return result


def fact_sentence(requirements: QuestionRequirements, fact: EvidenceFact, revision: RevisionKind | None = None) -> str:
    entity = next((item.canonical_name for item in requirements.entities if item.entity_id == fact.entity_id),
                  fact.entity_id).rstrip(".")
    metric = next((item.display_name for item in requirements.metrics if item.metric_id == fact.metric_id),
                  fact.metric_id.replace("_", " "))
    period = f" for {fact.period}" if fact.period else ""
    basis = {
        RevisionKind.ORIGINAL: " in the original filing",
        RevisionKind.REFILED: " in a later filing with the same value",
        RevisionKind.AMENDMENT: " in the amended filing",
        RevisionKind.COMPARATIVE_REVISION: " as revised in a later comparative filing",
    }.get(revision, "")
    return f"{entity} reported {metric} of {fact.value}{period}{basis}."


def calculation_sentence(calculation: DerivedCalculation, citations: list[int], revision: RevisionPolicy | None) -> str:
    value = format(calculation.result, "f")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    markers = " ".join(f"[Source {number}]" for number in citations)
    basis = ""
    if revision is not None:
        basis = " using the revised filing values" if revision == RevisionPolicy.LATEST else " using the original filing values"
    metric = calculation.metric_id.replace("_", " ")
    if calculation.operation == "growth":
        return (f"{calculation.company or 'The company'} {metric} growth was {value}% "
                f"from {calculation.fiscal_period}{basis}. {markers}")
    unit = calculation.currency or calculation.unit or "units"
    return f"The absolute {metric} difference was {unit} {value} across {calculation.fiscal_period}{basis}. {markers}"


def no_answer() -> AnswerGenerationResult:
    return AnswerGenerationResult(answer=INSUFFICIENT_EVIDENCE_ANSWER, model_id="filingscope-no-answer",
                                  prompt_tokens=0, completion_tokens=0, latency_ms=0.0)


class DeterministicWriter:
    def write(self, report: GroundedReportInput) -> AnswerGenerationResult:
        started = time.perf_counter()
        if not report.sufficient:
            return no_answer()
        arithmetic = report.arithmetic
        if arithmetic:
            calculated = {(item.operation, item.company, item.metric_id) for item in report.calculations}
            if not arithmetic.issubset(calculated):
                return no_answer()
        if report.calculations:
            answer = " ".join(statement for _, statement in self.calculation_entries(report))
        else:
            sources = {source.chunk["chunk_id"]: source for source in report.sources}
            numbers = report.source_numbers
            sentences = []
            for finding in report.coverage.findings:
                industries: dict[tuple[str, str, bool], set[int]] = {}
                for fact in finding.facts:
                    if fact.evidence_id not in sources:
                        continue
                    source = sources[fact.evidence_id]
                    if fact.metric_id == "industry" and fact.value_kind == "topic":
                        entity = next(item for item in report.requirements.entities if item.entity_id == fact.entity_id)
                        aliases = (entity.canonical_name,)
                        text = source.chunk.get("text", "")
                        if isinstance(text, str):
                            for industry, positive in filing_industry_relations(text, aliases):
                                industries.setdefault((entity.canonical_name.rstrip("."), industry, positive), set()).add(numbers[fact.evidence_id])
                        continue
                    if not fact.value:
                        continue
                    provenance = source.records[0].xbrl_provenance if report.revision_policy is not None else None
                    revision = provenance.revision_kind if provenance else None
                    sentences.append(f"{fact_sentence(report.requirements, fact, revision)} [Source {numbers[fact.evidence_id]}]")
                    break
                if len(industries) == 1:
                    (company, industry, positive), citations = next(iter(industries.items()))
                    relation = "operates in" if positive else "does not operate in"
                    sentences.append(f"{company} {relation} the {industry} industry. [Source {min(citations)}]")
            answer = " ".join(sentences)
        if not answer:
            return no_answer()
        return AnswerGenerationResult(answer=answer, model_id="filingscope-deterministic-report-writer",
                                      prompt_tokens=0, completion_tokens=0, latency_ms=(time.perf_counter() - started) * 1000)

    @staticmethod
    def calculation_entries(report: GroundedReportInput) -> list[tuple[DerivedCalculation, str]]:
        evidence_numbers = {record.evidence_id: index for index, source in enumerate(report.sources, start=1)
                            for record in source.records}
        entries = []
        for calculation in report.calculations:
            if not all(item in evidence_numbers for item in calculation.input_evidence_ids):
                continue
            citations = sorted({evidence_numbers[item] for item in calculation.input_evidence_ids})
            entries.append((calculation, calculation_sentence(calculation, citations, report.revision_policy)))
        return entries


class ProviderLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    max_calls: int = Field(ge=1)
    max_input_tokens: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    max_cost_usd: Decimal = Field(gt=0, allow_inf_nan=False)


@dataclass(frozen=True)
class ProviderUsage:
    attempted_calls: int = 0
    responses: int = 0
    reserved_input_tokens: int = 0
    reserved_output_tokens: int = 0
    cost_upper_bound_usd: Decimal = Decimal(0)
    observed_input_tokens: int = 0
    observed_output_tokens: int = 0
    reported_cost_usd: Decimal = Decimal(0)
    missing_usage_responses: int = 0
    budget_breached: bool = False


class OptionalProviderWriter:
    """Reuse a P5 provider adapter with a process-wide modeled spending cap."""

    def __init__(self, generator: AnswerGenerator, limits: ProviderLimits | None = None):
        if isinstance(generator, GroqAnswerGenerator) and (limits is None or generator.model_id != GENERATOR_MODEL_ID):
            raise ValueError("The hosted writer requires explicit limits and a model with a configured tariff")
        self.generator = generator
        self.limits = limits
        self.usage = ProviderUsage()
        self.lock = Lock()

    def write(self, report: GroundedReportInput, *, max_context_tokens: int,
              can_attempt: Callable[[], bool], start_attempt: Callable[[int], None]) -> AnswerGenerationResult | None:
        if not report.sufficient or report.arithmetic or report.calculations or report.revision_policy or report.deterministic_lookup:
            return None
        chunks = report.provider_chunks()
        question = report.requirements.question
        prompt_tokens = estimate_prompt_tokens(build_generation_messages(question, chunks))
        if prompt_tokens > min(max_context_tokens, GENERATOR_MAX_INPUT_TOKENS) or not can_attempt():
            return None
        reserved_input = estimate_prompt_tokens_with_margin(prompt_tokens)
        reserved_output = getattr(self.generator, "max_output_tokens", GENERATOR_MAX_OUTPUT_TOKENS)
        cost = estimate_max_cost_usd(prompt_tokens=prompt_tokens, max_output_tokens=reserved_output)
        with self.lock:
            used = self.usage
            if self.limits and (
                used.budget_breached or used.attempted_calls >= self.limits.max_calls
                or used.reserved_input_tokens + reserved_input > self.limits.max_input_tokens
                or used.reserved_output_tokens + reserved_output > self.limits.max_output_tokens
                or used.cost_upper_bound_usd + cost > self.limits.max_cost_usd
            ):
                return None
            self.usage = replace(used, attempted_calls=used.attempted_calls + 1,
                                 reserved_input_tokens=used.reserved_input_tokens + reserved_input,
                                 reserved_output_tokens=used.reserved_output_tokens + reserved_output,
                                 cost_upper_bound_usd=used.cost_upper_bound_usd + cost)
        start_attempt(prompt_tokens)
        try:
            generated = self.generator.generate(question, chunks)
        except Exception:
            return None
        if not isinstance(generated, AnswerGenerationResult):
            return None
        reported_cost = generated.estimated_cost_usd
        cost_valid = reported_cost is not None and reported_cost.is_finite() and reported_cost >= 0
        breached = bool(self.limits and (
            (generated.prompt_tokens or 0) > reserved_input
            or (generated.completion_tokens or 0) > reserved_output
            or (cost_valid and reported_cost > cost)
        ))
        with self.lock:
            used = self.usage
            self.usage = replace(
                used, responses=used.responses + 1,
                observed_input_tokens=used.observed_input_tokens + (generated.prompt_tokens or 0),
                observed_output_tokens=used.observed_output_tokens + (generated.completion_tokens or 0),
                reported_cost_usd=used.reported_cost_usd + (reported_cost if cost_valid else Decimal(0)),
                missing_usage_responses=used.missing_usage_responses + int(
                    generated.prompt_tokens is None or generated.completion_tokens is None or not cost_valid),
                budget_breached=used.budget_breached or breached,
            )
        return generated if generated.answer.strip() and not breached else None
