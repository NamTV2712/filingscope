"""Finite query planning with and without a runtime Corpus Map."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.decision.models import QuestionRequirements
from src.decision.requirement_extractor import EvidenceRequirementExtractor
from src.research.corpus_map import (
    CorpusDocument,
    CorpusMap,
    MetadataCoverage,
    SourceAvailability,
)
from src.retrieval.query_shaper import shape_retrieval_query

PLANNER_VERSION = "1.0.0"
DEFAULT_MAX_TASKS = 12
_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_QUARTER_RE = re.compile(r"\bQ([1-4])\s*(?:YTD\s+)?(?:FY\s*)?((?:19|20)\d{2})\b", re.I)
_FORM_PATTERNS = (
    ("10k", re.compile(r"\b(?:10\s*[-–]?\s*k|annual report|10-k)\b", re.I)),
    ("10q", re.compile(r"\b(?:10\s*[-–]?\s*q|quarterly report|10-q)\b", re.I)),
    ("8k", re.compile(r"\b(?:8\s*[-–]?\s*k|current report|8-k)\b", re.I)),
    ("earnings", re.compile(r"\bearnings\s+(?:release|report|call)\b", re.I)),
)
_FORM_LABELS = {
    "10k": "10-K annual filing",
    "10q": "10-Q quarterly filing",
    "8k": "8-K current filing",
    "earnings": "earnings release",
}


class PlanningMode(StrEnum):
    QUESTION_ONLY = "QUESTION_ONLY"
    CORPUS_AWARE = "CORPUS_AWARE"


class ResearchTask(BaseModel):
    """One bounded retrieval task tied to a requirement and existing source IDs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str = Field(min_length=1)
    requirement_ids: tuple[str, ...] = ()
    entity_id: str | None = None
    company_name: str | None = None
    metric_id: str | None = None
    period: str | None = None
    form_types: tuple[str, ...] = ()
    source_availability: SourceAvailability
    availability_reason: str
    query: str | None = None
    target_document_ids: tuple[str, ...] = ()


class ResearchPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str
    planning_mode: PlanningMode
    planner_version: str = PLANNER_VERSION
    index_generation_id: str | None = None
    requirements_supported: bool = True
    unsupported_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    tasks: tuple[ResearchTask, ...] = ()

    @property
    def retrieval_call_count(self) -> int:
        return sum(task.query is not None for task in self.tasks)


class QuestionOnlyPlanner:
    """Question-only baseline; no corpus inventory is supplied to this planner."""

    planner_id = "question-only"

    def __init__(self, *, max_tasks: int = DEFAULT_MAX_TASKS):
        if max_tasks < 1:
            raise ValueError("max_tasks must be positive")
        self.max_tasks = max_tasks
        self.extractor = EvidenceRequirementExtractor()

    def plan(self, question: str) -> ResearchPlan:
        requirements = self.extractor.extract(question)
        tasks: list[ResearchTask] = []
        if requirements.evidence:
            entities = {entity.entity_id: entity for entity in requirements.entities}
            metrics = {metric.metric_id: metric for metric in requirements.metrics}
            for requirement in requirements.evidence[: self.max_tasks]:
                entity = entities.get(requirement.entity_id)
                metric = metrics.get(requirement.metric_id)
                query = _requirement_query(
                    question,
                    company=entity.canonical_name if entity else None,
                    metric=metric.display_name if metric else requirement.metric_id,
                    period=requirement.period,
                    forms=(),
                    sections=(),
                )
                tasks.append(ResearchTask(
                    task_id=f"task-{len(tasks) + 1:02d}",
                    requirement_ids=(requirement.requirement_id,),
                    entity_id=requirement.entity_id,
                    company_name=entity.canonical_name if entity else None,
                    metric_id=requirement.metric_id,
                    period=requirement.period,
                    source_availability=SourceAvailability.UNKNOWN,
                    availability_reason="question_only_baseline_has_no_corpus_inventory",
                    query=query,
                ))
        else:
            tasks.append(ResearchTask(
                task_id="task-01",
                source_availability=SourceAvailability.UNKNOWN,
                availability_reason="question_only_baseline_has_no_corpus_inventory",
                query=shape_retrieval_query(question).retrieval_query.strip() or None,
            ))

        warnings = list(requirements.unsupported_reasons)
        if len(requirements.evidence) > self.max_tasks:
            warnings.append(f"task_limit_reached:{self.max_tasks}")
        return ResearchPlan(
            question=question,
            planning_mode=PlanningMode.QUESTION_ONLY,
            requirements_supported=requirements.supported,
            unsupported_reasons=requirements.unsupported_reasons,
            warnings=tuple(warnings),
            tasks=tuple(tasks),
        )


class CorpusAwarePlanner:
    """Condition finite retrieval tasks on indexed source metadata only."""

    planner_id = "corpus-aware"

    def __init__(
        self,
        corpus_map: CorpusMap,
        *,
        max_tasks: int = DEFAULT_MAX_TASKS,
        fallback_document_limit: int = 3,
    ):
        if max_tasks < 1:
            raise ValueError("max_tasks must be positive")
        if fallback_document_limit < 1:
            raise ValueError("fallback_document_limit must be positive")
        self.corpus_map = corpus_map
        self.max_tasks = max_tasks
        self.fallback_document_limit = fallback_document_limit
        rows = [
            {"company": company, "ticker": ticker}
            for document in corpus_map.documents
            for company in document.company_names
            for ticker in (document.tickers or (None,))
        ]
        self.extractor = EvidenceRequirementExtractor.from_document_rows(rows)

    def plan(self, question: str) -> ResearchPlan:
        requirements = self.extractor.extract(question)
        tasks: list[ResearchTask] = []
        warnings = list(requirements.unsupported_reasons)

        if requirements.evidence:
            entities = {entity.entity_id: entity for entity in requirements.entities}
            metrics = {metric.metric_id: metric for metric in requirements.metrics}
            requested_forms = _requested_forms(question)
            for requirement in requirements.evidence[: self.max_tasks]:
                entity = entities.get(requirement.entity_id)
                metric = metrics.get(requirement.metric_id)
                task = self._plan_requirement(
                    question,
                    requirement_id=requirement.requirement_id,
                    entity_id=requirement.entity_id,
                    company_name=entity.canonical_name if entity else None,
                    metric_id=requirement.metric_id,
                    metric_name=metric.display_name if metric else requirement.metric_id,
                    period=requirement.period,
                    requested_forms=requested_forms,
                    task_number=len(tasks) + 1,
                )
                tasks.append(task)
        elif requirements.entities:
            requested_forms = _requested_forms(question)
            for entity in requirements.entities[: self.max_tasks]:
                company_docs = self.corpus_map.documents_for_company(entity.entity_id)
                form_docs = _documents_for_forms(company_docs, requested_forms)
                if company_docs and requested_forms and not form_docs:
                    availability = _missing_or_unknown(
                        self.corpus_map.metadata_coverage.get("form_type", MetadataCoverage.UNKNOWN)
                    )
                    candidates = company_docs if availability == SourceAvailability.UNKNOWN else ()
                    reason = "requested_filing_type_not_indexed" if not candidates else "filing_type_metadata_incomplete"
                elif company_docs:
                    availability = SourceAvailability.AVAILABLE
                    candidates = form_docs or company_docs
                    reason = "company_source_available"
                else:
                    availability = _missing_or_unknown(
                        self.corpus_map.metadata_coverage.get("company", MetadataCoverage.UNKNOWN)
                    )
                    candidates = ()
                    reason = "company_source_not_found" if availability == SourceAvailability.MISSING else "company_source_state_unknown"
                doc_ids = _document_ids(candidates)
                query = None if availability == SourceAvailability.MISSING and not doc_ids else _requirement_query(
                    question,
                    company=entity.canonical_name,
                    metric=None,
                    period=None,
                    forms=_forms_in_documents(candidates),
                    sections=_sections_in_documents(candidates),
                )
                tasks.append(ResearchTask(
                    task_id=f"task-{len(tasks) + 1:02d}",
                    entity_id=entity.entity_id,
                    company_name=entity.canonical_name,
                    form_types=requested_forms,
                    source_availability=availability,
                    availability_reason=reason,
                    query=query,
                    target_document_ids=doc_ids,
                ))
        else:
            # The map cannot safely resolve the source. Keep a broad query but
            # make the uncertainty visible instead of claiming local coverage.
            tasks.append(ResearchTask(
                task_id="task-01",
                source_availability=SourceAvailability.UNKNOWN,
                availability_reason="question_requirements_or_company_unresolved",
                query=shape_retrieval_query(question).retrieval_query.strip() or None,
            ))

        planned_task_count = len(requirements.evidence) or len(requirements.entities)
        if planned_task_count > self.max_tasks:
            warnings.append(f"task_limit_reached:{self.max_tasks}")
        return ResearchPlan(
            question=question,
            planning_mode=PlanningMode.CORPUS_AWARE,
            index_generation_id=self.corpus_map.index_generation_id,
            requirements_supported=requirements.supported,
            unsupported_reasons=requirements.unsupported_reasons,
            warnings=tuple(warnings),
            tasks=tuple(tasks),
        )

    def _plan_requirement(
        self,
        question: str,
        *,
        requirement_id: str,
        entity_id: str,
        company_name: str | None,
        metric_id: str,
        metric_name: str,
        period: str | None,
        requested_forms: tuple[str, ...],
        task_number: int,
    ) -> ResearchTask:
        company_docs = self.corpus_map.documents_for_company(entity_id)
        if not company_docs:
            availability = _missing_or_unknown(
                self.corpus_map.metadata_coverage.get("company", MetadataCoverage.UNKNOWN)
            )
            if availability == SourceAvailability.UNKNOWN:
                return self._task(
                    question,
                    task_number,
                    requirement_id,
                    entity_id,
                    company_name,
                    metric_id,
                    metric_name,
                    period,
                    availability,
                    "company_inventory_incomplete",
                    (),
                    requested_forms,
                )
            return ResearchTask(
                task_id=f"task-{task_number:02d}",
                requirement_ids=(requirement_id,),
                entity_id=entity_id,
                company_name=company_name,
                metric_id=metric_id,
                period=period,
                form_types=requested_forms,
                source_availability=availability,
                availability_reason=(
                    "company_absent_from_complete_runtime_inventory"
                    if availability == SourceAvailability.MISSING
                    else "company_inventory_incomplete"
                ),
            )

        if any("company" in document.metadata_conflicts for document in company_docs):
            return self._task(
                question,
                task_number,
                requirement_id,
                entity_id,
                company_name,
                metric_id,
                metric_name,
                period,
                SourceAvailability.UNKNOWN,
                "company_identity_metadata_conflicted",
                company_docs,
                requested_forms,
            )

        form_docs = _documents_for_forms(company_docs, requested_forms)
        if requested_forms and not form_docs:
            availability = _missing_or_unknown(
                self.corpus_map.metadata_coverage.get("form_type", MetadataCoverage.UNKNOWN)
            )
            candidates = company_docs if availability == SourceAvailability.UNKNOWN else ()
            return self._task(
                question,
                task_number,
                requirement_id,
                entity_id,
                company_name,
                metric_id,
                metric_name,
                period,
                availability,
                "requested_filing_type_not_indexed" if not candidates else "filing_type_metadata_incomplete",
                candidates,
                requested_forms,
            )

        candidates = form_docs or company_docs
        if period:
            period_matches, period_unknown = _documents_for_period(candidates, period)
            if period_matches:
                if any(
                    "filing_period" in document.metadata_conflicts
                    for document in period_matches
                ):
                    return self._task(
                        question,
                        task_number,
                        requirement_id,
                        entity_id,
                        company_name,
                        metric_id,
                        metric_name,
                        period,
                        SourceAvailability.UNKNOWN,
                        "filing_period_metadata_conflicted",
                        period_matches,
                        requested_forms,
                    )
                return self._task(
                    question,
                    task_number,
                    requirement_id,
                    entity_id,
                    company_name,
                    metric_id,
                    metric_name,
                    period,
                    SourceAvailability.AVAILABLE,
                    "matching_filing_period_available",
                    period_matches,
                    requested_forms,
                )

            if period_unknown:
                year_docs, _ = _documents_for_period(candidates, period, allow_year_only=True)
                return self._task(
                    question,
                    task_number,
                    requirement_id,
                    entity_id,
                    company_name,
                    metric_id,
                    metric_name,
                    period,
                    SourceAvailability.UNKNOWN,
                    "filing_period_granularity_or_metadata_incomplete",
                    year_docs or candidates,
                    requested_forms,
                )

            availability = _missing_or_unknown(
                self.corpus_map.metadata_coverage.get("filing_period", MetadataCoverage.UNKNOWN)
            )
            fallback = _nearest_documents(candidates, period, self.fallback_document_limit)
            return self._task(
                question,
                task_number,
                requirement_id,
                entity_id,
                company_name,
                metric_id,
                metric_name,
                period,
                availability,
                "exact_filing_period_not_indexed; fallback_targets_are_local"
                if fallback and availability == SourceAvailability.MISSING
                else "filing_period_inventory_incomplete",
                fallback,
                requested_forms,
            )

        return self._task(
            question,
            task_number,
            requirement_id,
            entity_id,
            company_name,
            metric_id,
            metric_name,
            period,
            SourceAvailability.AVAILABLE,
            "company_filings_available_period_unspecified",
            candidates,
            requested_forms,
        )

    def _task(
        self,
        question: str,
        task_number: int,
        requirement_id: str,
        entity_id: str,
        company_name: str | None,
        metric_id: str,
        metric_name: str,
        period: str | None,
        availability: SourceAvailability,
        reason: str,
        documents: tuple[CorpusDocument, ...],
        requested_forms: tuple[str, ...],
    ) -> ResearchTask:
        target_ids = _document_ids(documents)
        query = None
        if target_ids:
            query = _requirement_query(
                question,
                company=company_name,
                metric=metric_name,
                period=period,
                forms=_forms_in_documents(documents) or requested_forms,
                sections=_sections_in_documents(documents),
            )
        elif availability == SourceAvailability.UNKNOWN:
            # An incomplete map can still justify a search, but the task makes
            # that uncertainty explicit and carries no fabricated document ID.
            query = _requirement_query(
                question,
                company=company_name,
                metric=metric_name,
                period=period,
                forms=requested_forms,
                sections=(),
            )
        return ResearchTask(
            task_id=f"task-{task_number:02d}",
            requirement_ids=(requirement_id,),
            entity_id=entity_id,
            company_name=company_name,
            metric_id=metric_id,
            period=period,
            form_types=requested_forms,
            source_availability=availability,
            availability_reason=reason,
            query=query,
            target_document_ids=target_ids,
        )


def _requirement_query(
    question: str,
    *,
    company: str | None,
    metric: str | None,
    period: str | None,
    forms: tuple[str, ...],
    sections: tuple[str, ...],
) -> str:
    shaped = shape_retrieval_query(question).retrieval_query.strip()
    additions: list[str] = []
    for value in (company, metric, period):
        if value and value.casefold() not in shaped.casefold():
            additions.append(value)
    for form in forms:
        label = _FORM_LABELS.get(form.casefold(), form)
        if label.casefold() not in shaped.casefold():
            additions.append(label)
    meaningful_sections = tuple(
        section for section in sections if section.casefold() not in {"document", "filing"}
    )
    for section in meaningful_sections:
        if section.casefold() not in shaped.casefold():
            additions.append(section.replace("_", " "))
    return " ".join([shaped, *additions]).strip()


def _requested_forms(question: str) -> tuple[str, ...]:
    return tuple(form for form, pattern in _FORM_PATTERNS if pattern.search(question))


def _documents_for_forms(
    documents: tuple[CorpusDocument, ...],
    forms: tuple[str, ...],
) -> tuple[CorpusDocument, ...]:
    if not forms:
        return documents
    requested = {form.casefold() for form in forms}
    return tuple(
        document
        for document in documents
        if requested.intersection(form.casefold() for form in document.form_types)
    )


def _documents_for_period(
    documents: tuple[CorpusDocument, ...],
    period: str,
    *,
    allow_year_only: bool = False,
) -> tuple[tuple[CorpusDocument, ...], bool]:
    requested_quarter = _QUARTER_RE.search(period)
    requested_years = set(_YEAR_RE.findall(period))
    if not requested_years:
        return documents, False

    matches = []
    quarter_granularity_unknown = False
    for document in documents:
        if "filing_period" in document.metadata_conflicts:
            continue
        period_values = document.filing_periods
        observed_years = {year for value in period_values for year in _YEAR_RE.findall(value)}
        if not requested_years.intersection(observed_years):
            continue
        if not requested_quarter:
            matches.append(document)
            continue
        quarter_values = [
            quarter
            for value in period_values
            for quarter in _QUARTER_RE.finditer(value)
        ]
        if not quarter_values and not allow_year_only:
            quarter_granularity_unknown = True
            continue
        if any(
            item.group(1) == requested_quarter.group(1)
            and item.group(2) == requested_quarter.group(2)
            for item in quarter_values
        ) or (allow_year_only and not quarter_values):
            matches.append(document)
    return tuple(matches), quarter_granularity_unknown


def _nearest_documents(
    documents: tuple[CorpusDocument, ...],
    period: str,
    limit: int,
) -> tuple[CorpusDocument, ...]:
    years = [int(year) for year in _YEAR_RE.findall(period)]
    if not years:
        return tuple(sorted(documents, key=lambda doc: doc.document_id)[:limit])
    target_year = years[-1]

    def key(document: CorpusDocument) -> tuple[int, int, str]:
        observed = [
            int(year)
            for value in document.filing_periods
            for year in _YEAR_RE.findall(value)
        ]
        nearest = min((abs(year - target_year) for year in observed), default=9999)
        return nearest, -max(observed, default=0), document.document_id

    return tuple(sorted(documents, key=key)[:limit])


def _forms_in_documents(documents: tuple[CorpusDocument, ...]) -> tuple[str, ...]:
    values = {form.casefold() for document in documents for form in document.form_types}
    return tuple(sorted(values))


def _sections_in_documents(documents: tuple[CorpusDocument, ...]) -> tuple[str, ...]:
    values = {section for document in documents for section in document.sections}
    return tuple(sorted(values, key=str.casefold))


def _document_ids(documents: tuple[CorpusDocument, ...]) -> tuple[str, ...]:
    return tuple(sorted({document.document_id for document in documents}))


def _missing_or_unknown(coverage: MetadataCoverage) -> SourceAvailability:
    # Only a complete inventory can establish absence. If a field was never
    # indexed, the planner has no basis for claiming the source is missing.
    return SourceAvailability.MISSING if coverage == MetadataCoverage.COMPLETE else SourceAvailability.UNKNOWN


__all__ = [
    "DEFAULT_MAX_TASKS",
    "PLANNER_VERSION",
    "CorpusAwarePlanner",
    "PlanningMode",
    "QuestionOnlyPlanner",
    "ResearchPlan",
    "ResearchTask",
]
