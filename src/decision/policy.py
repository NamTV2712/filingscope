"""Deterministic answer/retrieve/abstain policy over evidence coverage."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.decision.company_catalog import CompanyCatalog
from src.decision.evidence_coverage import EvidenceCoverageAnalyzer
from src.decision.models import (
    DecisionAction,
    DecisionBudget,
    DecisionResult,
    EvidenceCoverage,
)
from src.decision.requirement_extractor import EvidenceRequirementExtractor


class EvidenceDecisionLayer:
    """Make a structural decision without consulting retrieval scores.

    ``ANSWER`` means all registered evidence inputs are present, attributable,
    numerically complete, period-aligned, and free of detected conflicts. It
    does not generate an answer or validate claims; those are later phases.
    """

    def __init__(
        self,
        *,
        catalog: CompanyCatalog | None = None,
        extractor: EvidenceRequirementExtractor | None = None,
        analyzer: EvidenceCoverageAnalyzer | None = None,
    ):
        self.catalog = catalog or (extractor.catalog if extractor is not None else CompanyCatalog())
        self.extractor = extractor or EvidenceRequirementExtractor(self.catalog)
        self.analyzer = analyzer or EvidenceCoverageAnalyzer(self.catalog)

    def assess(
        self,
        question: str,
        chunks: Iterable[Any],
    ) -> EvidenceCoverage:
        requirements = self.extractor.extract(question)
        return self.analyzer.analyze(requirements, chunks)

    def decide(
        self,
        question: str,
        chunks: Iterable[Any],
        *,
        budget: DecisionBudget | None = None,
    ) -> DecisionResult:
        decision_budget = budget or DecisionBudget()
        coverage = self.assess(question, chunks)
        requirements = coverage.requirements
        gap_requirement_ids = tuple(dict.fromkeys((
            *coverage.missing_requirement_ids,
            *coverage.conflicted_requirement_ids,
        )))

        if not requirements.supported:
            reason = (
                requirements.unsupported_reasons[0]
                if requirements.unsupported_reasons
                else "unsupported_requirement"
            )
            return DecisionResult(
                action=DecisionAction.ABSTAIN,
                reason_code=reason,
                coverage=coverage,
                rationale="The question cannot be mapped to a supported, auditable evidence requirement set.",
            )
        if coverage.sufficient:
            return DecisionResult(
                action=DecisionAction.ANSWER,
                reason_code="requirements_satisfied",
                coverage=coverage,
                rationale="Every required evidence slot is covered with consistent source, period, metric, and value metadata.",
            )
        if decision_budget.remaining_retrieval_attempts > 0:
            reason = (
                "conflicting_evidence"
                if coverage.conflicted_requirement_ids
                else "missing_evidence"
                if coverage.missing_requirement_ids
                else "incomplete_operation_inputs"
                if coverage.operation_gaps
                else "missing_evidence"
            )
            return DecisionResult(
                action=DecisionAction.RETRIEVE_MORE,
                reason_code=reason,
                coverage=coverage,
                gap_requirement_ids=gap_requirement_ids,
                gap_codes=coverage.operation_gaps,
                rationale="At least one required fact is absent, untraceable, inconsistent, or incompatible; a bounded retrieval attempt remains.",
            )
        reason = (
            "conflicting_evidence_after_budget"
            if coverage.conflicted_requirement_ids
            else "incomplete_evidence_after_budget"
        )
        return DecisionResult(
            action=DecisionAction.ABSTAIN,
            reason_code=reason,
            coverage=coverage,
            gap_requirement_ids=gap_requirement_ids,
            gap_codes=coverage.operation_gaps,
            rationale="The evidence requirements remain incomplete or inconsistent after the available retrieval attempts.",
        )
