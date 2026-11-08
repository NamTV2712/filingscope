"""Hand-labeled synthetic candidate cases, separate from policy code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.policy.evidence_features import EvidenceCandidateFeatures, ScoreObservation
from src.policy.evidence_policy import CandidateDisposition

BENCHMARK_ID = "filingscope-evidence-policy-synthetic-v1"
BENCHMARK_VERSION = "1.0.0"


@dataclass(frozen=True)
class EvidencePolicyScenario:
    case_id: str
    split: str
    failure_group: str
    features: EvidenceCandidateFeatures
    expected_disposition: CandidateDisposition
    expected_reason_codes: tuple[str, ...]


_BASE: dict[str, Any] = {
    "requirement_id": "req-revenue-fy2024",
    "entity_match": "EXACT",
    "metric_match": "EXACT",
    "period_match": "EXACT",
    "filing_type_match": "NOT_APPLICABLE",
    "support_level": "FULL",
    "source_quality": "PRIMARY",
    "table_context_integrity": "INTACT",
    "requires_table_context": True,
    "numeric_consistency": "CONSISTENT",
    "requires_numeric_consistency": True,
    "contradiction_flag": False,
    "provenance_validity": "VALID",
    "source_revision_validity": "VALID",
}


def _split(index: int) -> str:
    if index < 8:
        return "development"
    if index < 14:
        return "validation"
    return "held_out"


def _scenarios_for_disposition(
    *,
    disposition: CandidateDisposition,
    cases: tuple[tuple[str, dict[str, Any], float, float, tuple[str, ...]], ...],
) -> list[EvidencePolicyScenario]:
    output = []
    for index, (group, overrides, semantic_score, retrieval_score, reasons) in enumerate(cases):
        case_id = f"{disposition.value.lower()}_{index + 1:02d}"
        row = {**_BASE, **overrides}
        candidate = EvidenceCandidateFeatures(
            candidate_id=case_id,
            semantic_relevance=ScoreObservation(
                score=semantic_score,
                observer_id="synthetic-relevance-observer",
                observer_version="1.0.0",
            ),
            retrieval_confidence=ScoreObservation(
                score=retrieval_score,
                observer_id="synthetic-retrieval-observer",
                observer_version="1.0.0",
            ),
            **row,
        )
        output.append(EvidencePolicyScenario(
            case_id=case_id,
            split=_split(index),
            failure_group=group,
            features=candidate,
            expected_disposition=disposition,
            expected_reason_codes=reasons,
        ))
    return output


def evidence_policy_scenarios() -> tuple[EvidencePolicyScenario, ...]:
    """Return 60 fixed cases: 20 ACCEPT, 20 WEAK, and 20 REJECT.

    Cases are synthetic feature observations with hand-authored labels. The
    held-out partition checks deterministic replay only; it is not a
    statistically representative or externally annotated financial corpus.
    """
    accepted = (
        ("primary_exact", {}, .98, .93, ("CANDIDATE_ACCEPTED",)),
        ("primary_exact", {}, .64, .44, ("CANDIDATE_ACCEPTED",)),
        ("verified_alias", {"entity_match": "ALIAS"}, .57, .32, ("CANDIDATE_ACCEPTED",)),
        ("derived_with_provenance", {"source_quality": "DERIVED"}, .75, .65, ("CANDIDATE_ACCEPTED",)),
        ("narrative_fact", {
            "requires_table_context": False,
            "table_context_integrity": "NOT_APPLICABLE",
            "requires_numeric_consistency": False,
            "numeric_consistency": "NOT_APPLICABLE",
        }, .67, .52, ("CANDIDATE_ACCEPTED",)),
        ("verified_alias", {"entity_match": "ALIAS", "source_quality": "DERIVED"}, .86, .66, ("CANDIDATE_ACCEPTED",)),
        ("primary_exact", {}, .55, .28, ("CANDIDATE_ACCEPTED",)),
        ("primary_exact", {}, .82, .73, ("CANDIDATE_ACCEPTED",)),
        ("primary_exact", {}, .62, .45, ("CANDIDATE_ACCEPTED",)),
        ("primary_exact", {}, .73, .54, ("CANDIDATE_ACCEPTED",)),
        ("narrative_fact", {
            "requires_table_context": False,
            "table_context_integrity": "NOT_APPLICABLE",
            "requires_numeric_consistency": False,
            "numeric_consistency": "NOT_APPLICABLE",
        }, .91, .86, ("CANDIDATE_ACCEPTED",)),
        ("primary_exact", {}, .69, .57, ("CANDIDATE_ACCEPTED",)),
        ("derived_with_provenance", {"source_quality": "DERIVED"}, .84, .72, ("CANDIDATE_ACCEPTED",)),
        ("primary_exact", {}, .58, .34, ("CANDIDATE_ACCEPTED",)),
        ("verified_alias", {"entity_match": "ALIAS"}, .72, .56, ("CANDIDATE_ACCEPTED",)),
        ("primary_exact", {}, .95, .88, ("CANDIDATE_ACCEPTED",)),
        ("primary_exact", {}, .56, .31, ("CANDIDATE_ACCEPTED",)),
        ("narrative_fact", {
            "requires_table_context": False,
            "table_context_integrity": "NOT_APPLICABLE",
            "requires_numeric_consistency": False,
            "numeric_consistency": "NOT_APPLICABLE",
        }, .98, .91, ("CANDIDATE_ACCEPTED",)),
        ("derived_with_provenance", {"source_quality": "DERIVED"}, .78, .62, ("CANDIDATE_ACCEPTED",)),
        ("verified_alias", {"entity_match": "ALIAS"}, .88, .74, ("CANDIDATE_ACCEPTED",)),
    )
    weak = (
        ("low_semantic_relevance", {}, .42, .82, ("LOW_SEMANTIC_RELEVANCE",)),
        ("low_retrieval_confidence", {}, .84, .15, ("LOW_RETRIEVAL_CONFIDENCE",)),
        ("entity_unknown", {"entity_match": "UNKNOWN"}, .90, .82, ("ENTITY_ALIGNMENT_UNKNOWN",)),
        ("metric_compatible", {"metric_match": "COMPATIBLE"}, .90, .82, ("METRIC_ALIGNMENT_COMPATIBLE",)),
        ("period_compatible", {"period_match": "COMPATIBLE"}, .90, .82, ("PERIOD_ALIGNMENT_COMPATIBLE",)),
        ("partial_support", {"support_level": "PARTIAL"}, .90, .82, ("PARTIAL_SUPPORT",)),
        ("secondary_source", {"source_quality": "SECONDARY"}, .90, .82, ("SECONDARY_SOURCE",)),
        ("unknown_contradiction_status", {"contradiction_flag": None}, .99, .82, ("CONTRADICTION_STATUS_UNKNOWN",)),
        ("filing_type_compatible", {"filing_type_match": "COMPATIBLE"}, .94, .82, ("FILING_TYPE_COMPATIBLE",)),
        ("source_quality_unknown", {"source_quality": "UNKNOWN"}, .94, .82, ("SOURCE_QUALITY_UNKNOWN",)),
        ("table_context_partial", {"table_context_integrity": "PARTIAL"}, .94, .82, ("TABLE_CONTEXT_PARTIAL",)),
        ("table_context_unknown", {"table_context_integrity": "UNKNOWN"}, .94, .82, ("TABLE_CONTEXT_UNKNOWN",)),
        ("numeric_consistency_unknown", {"numeric_consistency": "UNKNOWN"}, .94, .82, ("NUMERIC_CONSISTENCY_UNKNOWN",)),
        ("provenance_unknown", {"provenance_validity": "UNKNOWN"}, .94, .82, ("PROVENANCE_UNKNOWN",)),
        ("source_revision_unknown", {"source_revision_validity": "UNKNOWN"}, .94, .82, ("SOURCE_REVISION_UNKNOWN",)),
        ("metric_unknown", {"metric_match": "UNKNOWN"}, .94, .82, ("METRIC_ALIGNMENT_UNKNOWN",)),
        ("period_unknown", {"period_match": "UNKNOWN"}, .94, .82, ("PERIOD_ALIGNMENT_UNKNOWN",)),
        ("filing_type_unknown", {"filing_type_match": "UNKNOWN"}, .94, .82, ("FILING_TYPE_UNKNOWN",)),
        ("multiple_soft_gaps", {"period_match": "COMPATIBLE", "support_level": "PARTIAL"}, .99, .82, ("PERIOD_ALIGNMENT_COMPATIBLE", "PARTIAL_SUPPORT")),
        ("multiple_soft_gaps", {"source_quality": "SECONDARY", "provenance_validity": "UNKNOWN"}, .99, .82, ("SECONDARY_SOURCE", "PROVENANCE_UNKNOWN")),
    )
    rejected = (
        ("wrong_company", {"entity_match": "MISMATCH"}, .93, .92, ("ENTITY_MISMATCH",)),
        ("wrong_metric", {"metric_match": "MISMATCH"}, .93, .92, ("METRIC_MISMATCH",)),
        ("wrong_period", {"period_match": "MISMATCH"}, .93, .92, ("PERIOD_MISMATCH",)),
        ("wrong_filing_type", {"filing_type_match": "MISMATCH"}, .93, .92, ("FILING_TYPE_MISMATCH",)),
        ("invalid_provenance", {"provenance_validity": "INVALID"}, .93, .92, ("INVALID_PROVENANCE",)),
        ("superseded_revision", {"source_revision_validity": "SUPERSEDED"}, .93, .92, ("SUPERSEDED_SOURCE_REVISION",)),
        ("no_support", {"support_level": "NONE"}, .93, .92, ("NO_SUPPORT",)),
        ("contradicted_support", {"support_level": "CONTRADICTED"}, .93, .92, ("CONTRADICTED_SUPPORT",)),
        ("explicit_contradiction", {"contradiction_flag": True}, .93, .92, ("CONTRADICTION_DETECTED",)),
        ("numeric_inconsistency", {"numeric_consistency": "INCONSISTENT"}, .93, .92, ("NUMERIC_INCONSISTENCY",)),
        ("broken_table_context", {"table_context_integrity": "BROKEN"}, .93, .92, ("BROKEN_TABLE_CONTEXT",)),
        ("wrong_company", {"entity_match": "MISMATCH"}, .99, .96, ("ENTITY_MISMATCH",)),
        ("wrong_metric", {"metric_match": "MISMATCH"}, .92, .91, ("METRIC_MISMATCH",)),
        ("wrong_period", {"period_match": "MISMATCH"}, .92, .91, ("PERIOD_MISMATCH",)),
        ("invalid_provenance", {"provenance_validity": "INVALID", "support_level": "PARTIAL"}, .92, .91, ("INVALID_PROVENANCE",)),
        ("superseded_and_contradicted", {"source_revision_validity": "SUPERSEDED", "contradiction_flag": True}, .92, .91, ("SUPERSEDED_SOURCE_REVISION", "CONTRADICTION_DETECTED")),
        ("no_support", {"support_level": "NONE"}, .92, .91, ("NO_SUPPORT",)),
        ("numeric_inconsistency", {"numeric_consistency": "INCONSISTENT"}, .92, .91, ("NUMERIC_INCONSISTENCY",)),
        ("broken_table_context", {"table_context_integrity": "BROKEN", "source_quality": "SECONDARY"}, .92, .91, ("BROKEN_TABLE_CONTEXT",)),
        ("wrong_metric_and_period", {"metric_match": "MISMATCH", "period_match": "MISMATCH"}, .92, .91, ("METRIC_MISMATCH", "PERIOD_MISMATCH")),
    )

    return tuple((
        *_scenarios_for_disposition(
            disposition=CandidateDisposition.ACCEPT,
            cases=accepted,
        ),
        *_scenarios_for_disposition(
            disposition=CandidateDisposition.WEAK,
            cases=weak,
        ),
        *_scenarios_for_disposition(
            disposition=CandidateDisposition.REJECT,
            cases=rejected,
        ),
    ))


__all__ = [
    "BENCHMARK_ID",
    "BENCHMARK_VERSION",
    "EvidencePolicyScenario",
    "evidence_policy_scenarios",
]
