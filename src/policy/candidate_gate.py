"""Observe runtime candidates before evidence sufficiency and report writing."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from src.decision.evidence_coverage import _has_provenance
from src.decision.models import CoverageStatus, EvidenceFinding, EvidenceRequirement, QuestionRequirements
from src.decision.period_value_parser import period_matches
from src.decision.policy import EvidenceDecisionLayer
from src.policy.decision_backend import DecisionBackend, DeterministicDecisionBackend
from src.policy.evidence_features import (
    Alignment, EntityMatch, EvidenceCandidateFeatures, NumericConsistency, ProvenanceValidity,
    ScoreObservation, SourceQuality, SourceRevisionValidity, SupportLevel,
)
from src.policy.evidence_policy import CandidateDisposition, EvidencePolicyDecision


def _provenance(chunk: Mapping[str, Any]) -> ProvenanceValidity:
    source = chunk.get("source_url") or chunk.get("filing_url") or chunk.get("source_repository_url")
    if source:
        try:
            parsed = urlsplit(source) if isinstance(source, str) else None
            if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return ProvenanceValidity.INVALID
        except ValueError:
            return ProvenanceValidity.INVALID
    return ProvenanceValidity.VALID if _has_provenance(chunk) else ProvenanceValidity.INVALID


def _similarity(chunk: Mapping[str, Any]) -> ScoreObservation:
    value = chunk.get("score")
    if (chunk.get("score_kind") in {"dense", "dense_score"}
            and isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)
            and -1 <= value <= 1):
        return ScoreObservation(score=(value + 1) / 2, observer_id="cosine-linear", observer_version="1")
    return ScoreObservation(score=0, observer_id="unavailable", observer_version="1")


def _alignment(observed: str | None, expected: str | None, *, period: bool = False) -> Alignment:
    if expected is None:
        return Alignment.EXACT
    if observed is None:
        return Alignment.UNKNOWN
    matches = period_matches(expected, observed) if period else expected == observed
    return Alignment.EXACT if matches else Alignment.MISMATCH


class CandidateEvidenceGate:
    """Retain candidates with at least one eligible slot for downstream checks."""

    def __init__(self, backend: DecisionBackend | None = None):
        self.backend = backend or DeterministicDecisionBackend()

    def screen(
        self, requirements: QuestionRequirements, chunks: Sequence[dict[str, Any]], layer: EvidenceDecisionLayer,
    ) -> tuple[list[dict[str, Any]], tuple[EvidencePolicyDecision, ...]]:
        if not requirements.evidence:
            return list(chunks), ()
        retained = []
        decisions = []
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id.strip():
                continue
            observation = layer.analyzer.analyze(requirements, (chunk,))
            findings = {finding.requirement_id: finding for finding in observation.findings}
            entity = layer.catalog.metadata_entity_id(
                chunk.get("ticker"), chunk.get("company"), chunk.get("doc_name"), chunk.get("document_id"),
            )
            per_candidate = [
                self.backend.decide(self._features(chunk, chunk_id, entity, requirement, findings.get(requirement.requirement_id)))
                for requirement in requirements.evidence
            ]
            decisions.extend(per_candidate)
            if any(result.disposition != CandidateDisposition.REJECT for result in per_candidate):
                retained.append(chunk)
        return retained, tuple(decisions)

    @staticmethod
    def _features(
        chunk: Mapping[str, Any], chunk_id: str, entity: str | None, requirement: EvidenceRequirement,
        finding: EvidenceFinding | None,
    ) -> EvidenceCandidateFeatures:
        status = finding.status if finding else CoverageStatus.MISSING
        found = status == CoverageStatus.FOUND
        metric = chunk.get("metric_id")
        period = chunk.get("fiscal_period") or chunk.get("period")
        # The document reporting year describes its publication, while an
        # individual value may belong to a comparative period.
        metric_match = _alignment(metric if isinstance(metric, str) else None, requirement.metric_id)
        period_match = _alignment(period if isinstance(period, str) else None, requirement.period, period=True)
        if found:
            if metric_match == Alignment.UNKNOWN:
                metric_match = Alignment.EXACT
            if period_match == Alignment.UNKNOWN:
                period_match = Alignment.EXACT
        similarity = _similarity(chunk)
        structured = chunk.get("source_type") == "XBRL_FACT"
        form = str(chunk.get("form_type") or chunk.get("doc_type") or "").upper().replace("-", "")
        return EvidenceCandidateFeatures(
            candidate_id=chunk_id, requirement_id=requirement.requirement_id,
            entity_match=(EntityMatch.UNKNOWN if entity is None else
                          EntityMatch.EXACT if entity == requirement.entity_id else EntityMatch.MISMATCH),
            metric_match=metric_match, period_match=period_match,
            support_level=SupportLevel.FULL if found else SupportLevel.PARTIAL,
            source_quality=SourceQuality.PRIMARY if structured or form in {"10K", "10Q", "8K", "20F", "40F"} else SourceQuality.UNKNOWN,
            numeric_consistency=(NumericConsistency.NOT_APPLICABLE if not requirement.quantitative else
                                 NumericConsistency.CONSISTENT if found else NumericConsistency.UNKNOWN),
            requires_numeric_consistency=requirement.quantitative,
            contradiction_flag=False if found else None,
            provenance_validity=_provenance(chunk),
            source_revision_validity=SourceRevisionValidity.UNKNOWN,
            semantic_relevance=similarity, retrieval_confidence=similarity,
        )
