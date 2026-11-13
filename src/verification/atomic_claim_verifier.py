"""Verify individual filing assertions and record the evidence that supports them."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from src.decision.company_catalog import CompanyCatalog
from src.decision.filing_disclosures import filing_industry_relations, industry_relation
from src.decision.models import EvidenceFact, MetricRequirement, QuestionRequirements
from src.decision.period_value_parser import extract_period_value_mentions, period_matches
from src.decision.policy import EvidenceDecisionLayer
from src.ingestion.company_facts import matches_requested_revision, requested_revision_policies
from src.verification.claim_verifier import ClaimLevelVerifier, _BRACKET_RE, _FALLBACK_RE, _GROWTH_RE, _split_clauses
from src.verification.models import (
    CitationStatus, ClaimAssessment, ClaimDraft, ClaimStatus, ResponseDisposition, VerificationResult,
)


_CONJUNCTION = re.compile(r",?\s+\b(?:and|but|while|whereas)\s+", re.I)
_COORDINATED_PREDICATE = re.compile(
    r"\b(?:is|are|was|were|has|have|had|operates?|serves?|sells?|supplies|reported|announced|"
    r"increased|decreased|grew|fell|led|acquired|expects?)\b", re.I,
)
_TRAILING_CITATIONS = re.compile(r"((?:\s*\[Source \d+\])+)\s*[.!?]?\s*$", re.I)
_CITED_SENTENCE_END = re.compile(r"([.!?][ \t]+(?:\[(?i:Source) \d+\][ \t]*)+)(?=[A-Za-z])")
_UNVERIFIED_QUALIFIER = re.compile(
    r"\b(?:not|never|only|solely|except|excluding|because|due to|approximately|"
    r"at least|at most|more than|less than|may|might|could|would)\b", re.I,
)
_QUALIFIED_EVIDENCE = re.compile(
    r"\b(?:did not|does not|do not|not reported|will not|(?:may|might|could)\s+(?:be|reach|report|increase|decline)|expects?|"
    r"expected to|forecasts?|projected|assuming|guidance)\b", re.I,
)
_SOURCE_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=\S)|\s*;\s*|\n")
_INCREASE = re.compile(r"\b(?:grew|increased|rose|gained)\b", re.I)
_UNCERTAINTY = re.compile(r"\b(?:insufficient evidence|not enough evidence|cannot determine|unable to verify|could not verify)\b", re.I)
_SPECULATION = re.compile(r"\b(?:may|might|could|would|expects?|forecasts?|projects?)\b", re.I)


class _ClaimLimitExceeded(ValueError):
    pass


def _text(statement: str) -> str:
    return _BRACKET_RE.sub(" ", statement).strip().rstrip(" .?!")


def _words(statement: str) -> str:
    return " ".join(re.findall(r"\w+", statement.casefold()))


def _split_atomic(statement: str, layer: EvidenceDecisionLayer) -> list[str]:
    """Split coordinated assertions while retaining their local citations."""
    parts: list[str] = []
    cursor = 0
    for match in _CONJUNCTION.finditer(statement):
        left = statement[cursor:match.start()]
        right = _CONJUNCTION.split(statement[match.end():], maxsplit=1)[0]
        left_text, right_text = _text(left), _text(right)
        coordinated_values = bool(extract_period_value_mentions(left_text) and extract_period_value_mentions(right_text))
        coordinated_values = coordinated_values and bool(layer.extractor.extract(right_text).metrics)
        coordinated_predicates = _COORDINATED_PREDICATE.search(left_text) and _COORDINATED_PREDICATE.search(right_text)
        if not (coordinated_values or coordinated_predicates):
            continue
        parts.append(left.strip())
        cursor = match.end()
    if not parts:
        return [statement]
    parts.append(statement[cursor:].strip())
    scopes = [layer.extractor.extract(_text(part)) for part in parts]
    shared = _TRAILING_CITATIONS.search(parts[-1])
    if any(_BRACKET_RE.search(previous) for previous in parts[:-1]):
        shared = None
    entity = None
    periods = {period for scope in scopes for period in scope.periods}
    result = []
    for part, scope in zip(parts, scopes, strict=True):
        if scope.entities:
            entity = scope.entities[0].matched_alias if len(scope.entities) == 1 else None
        elif entity:
            part = f"{entity} {part}"
        if not _BRACKET_RE.search(part) and shared:
            if not scope.periods and len(periods) == 1 and scopes[-1].periods:
                part = f"{part.rstrip('.')} for {next(iter(periods))}"
            part = f"{part} {shared.group(1).strip()}"
        result.append(part)
    return result


class AtomicClaimVerifier(ClaimLevelVerifier):
    """Use P4 numeric checks and require statement-local qualitative support."""

    def verify(self, question: str, answer: str, evidence_chunks: Iterable[Any]) -> VerificationResult:
        try:
            if len(answer) > 16_000:
                raise _ClaimLimitExceeded
            return super().verify(question, answer, evidence_chunks)
        except _ClaimLimitExceeded:
            return VerificationResult(
                disposition=ResponseDisposition.ABSTAIN, reason_codes=("claim_input_limit_exceeded",),
                claims=(ClaimAssessment(
                    claim_id="claim_1", statement=answer[:2000], status=ClaimStatus.UNVERIFIABLE,
                    citation_status=CitationStatus.MISSING, claim_type="unclassified",
                    reason_codes=("claim_input_limit_exceeded",),
                ),),
                valid_citation_count=0, invalid_citation_count=0, supported_claim_count=0,
                partial_claim_count=0, unsupported_claim_count=0, contradicted_claim_count=0,
                unverifiable_claim_count=1,
            )

    def _claim_statements(self, answer: str, layer: EvidenceDecisionLayer) -> list[str]:
        sentences = _CITED_SENTENCE_END.sub(r"\1\n", answer)
        statements = [part for clause in _split_clauses(sentences) for part in _split_atomic(clause, layer)]
        if len(statements) > 64 or any(len(part) > 2000 or len(_BRACKET_RE.findall(part)) > 32 for part in statements):
            raise _ClaimLimitExceeded
        return statements

    @staticmethod
    def _is_fallback(answer: str) -> bool:
        return (
            bool(_FALLBACK_RE.search(answer)) and not _BRACKET_RE.search(answer)
            and len(_split_clauses(answer)) == 1 and not extract_period_value_mentions(answer)
        )

    def _assess_claim(
        self, *, draft: ClaimDraft, question: str, question_requirements: QuestionRequirements,
        layer: EvidenceDecisionLayer, catalog: CompanyCatalog, cited_chunks: list[dict[str, Any]],
        evidence_ids: tuple[str, ...],
    ) -> ClaimAssessment:
        statement = _text(draft.statement)
        explicit_metrics = layer.extractor.extract(statement).metrics
        if draft.values and (
            _UNVERIFIED_QUALIFIER.search(statement) or len(draft.values) != 1 or len(draft.entity_ids) != 1
            or len(explicit_metrics) != 1
            or (draft.operation is None and (len(draft.periods) > 1 or _GROWTH_RE.search(statement)))
        ):
            return ClaimAssessment(
                claim_id=draft.claim_id, statement=draft.statement, status=ClaimStatus.UNVERIFIABLE,
                citation_status=CitationStatus.VALID, citations=draft.citations, evidence_ids=evidence_ids,
                reason_codes=("numeric_claim_scope_unresolved",),
            )
        revisions = requested_revision_policies(question) | requested_revision_policies(statement)
        if draft.values and any(not matches_requested_revision(chunk.get("revision_kind"), revisions)
                                for chunk in cited_chunks):
            return ClaimAssessment(
                claim_id=draft.claim_id, statement=draft.statement, status=ClaimStatus.UNSUPPORTED,
                citation_status=CitationStatus.VALID, citations=draft.citations, evidence_ids=evidence_ids,
                reason_codes=("cited_source_revision_does_not_match_claim",),
            )
        assessment = super()._assess_claim(
            draft=draft, question=question, question_requirements=question_requirements,
            layer=layer, catalog=catalog, cited_chunks=cited_chunks, evidence_ids=evidence_ids,
        )
        if assessment.status != ClaimStatus.SUPPORTED or assessment.calculation is None:
            return assessment
        if draft.operation == "difference":
            if "absolute" not in statement.casefold() and _GROWTH_RE.search(statement):
                direction = self._direction_assessment(draft, question_requirements, layer, cited_chunks)
                if direction is not None and direction[0] != ClaimStatus.SUPPORTED:
                    return assessment.model_copy(update={
                        "status": direction[0], "reason_codes": (direction[1],), "supported_values": (),
                        "unsupported_values": assessment.supported_values,
                    })
        elif (assessment.calculation.expected_value is not None and assessment.calculation.expected_value < 0
              and _INCREASE.search(statement)):
            return assessment.model_copy(update={
                "status": ClaimStatus.CONTRADICTED, "supported_values": (),
                "unsupported_values": assessment.supported_values, "reason_codes": ("growth_direction_mismatch",),
                "calculation": assessment.calculation.model_copy(update={
                    "passed": False, "status": "mismatch", "reason_code": "growth_direction_mismatch",
                }),
            })
        return assessment

    def _facts_for(
        self, *, entity_id: str, metric: MetricRequirement, periods: tuple[str, ...],
        layer: EvidenceDecisionLayer, chunks: list[dict[str, Any]],
    ) -> tuple[EvidenceFact, ...]:
        sources = []
        for chunk in chunks:
            text = str(chunk.get("text", ""))
            if not _QUALIFIED_EVIDENCE.search(text):
                sources.append(chunk)
                continue
            pieces = _SOURCE_SENTENCE_BOUNDARY.split(text)
            removed = False
            for index, piece in enumerate(pieces):
                if _QUALIFIED_EVIDENCE.search(piece) and extract_period_value_mentions(piece):
                    pieces[index] = ""
                    removed = True
            sources.append({**chunk, "text": "\n".join(pieces)} if removed else chunk)
        return super()._facts_for(entity_id=entity_id, metric=metric, periods=periods, layer=layer, chunks=sources)

    @staticmethod
    def _direction_operand(facts: tuple[EvidenceFact, ...], period: str) -> EvidenceFact | None:
        matches = [fact for fact in facts if period_matches(period, fact.period)]
        signatures = {(fact.numeric_value, fact.currency, fact.scale, fact.value_kind) for fact in matches}
        if len(signatures) != 1:
            return None
        return matches[0]

    def _qualitative_assessment(
        self, draft: ClaimDraft, layer: EvidenceDecisionLayer, catalog: CompanyCatalog,
        chunks: list[dict[str, Any]], evidence_ids: tuple[str, ...],
    ) -> ClaimAssessment:
        statement = _text(draft.statement)
        supports: set[str] = set()
        refutes: set[str] = set()
        if len(draft.entity_ids) == 1 and len(draft.metric_ids) == 1:
            entity_id = draft.entity_ids[0]
            aliases = {_words(alias) for alias in catalog.aliases_for(entity_id)}
            relation = industry_relation(statement, aliases) if draft.metric_ids == ("industry",) else None
            explicit_topic = bool(layer.extractor.extract(statement).metrics)
            for chunk in chunks:
                if catalog.metadata_entity_id(
                    chunk.get("ticker"), chunk.get("company"), chunk.get("doc_name"), chunk.get("document_id"),
                ) != entity_id:
                    continue
                chunk_id = chunk.get("chunk_id")
                if not isinstance(chunk_id, str) or not chunk_id:
                    continue
                text = str(chunk.get("text", ""))
                if "approved_facts" in chunk and not any(
                    isinstance(fact, EvidenceFact) and fact.entity_id == entity_id and fact.metric_id in draft.metric_ids
                    and (not draft.periods or any(period_matches(period, fact.period) for period in draft.periods))
                    for fact in chunk["approved_facts"]
                ):
                    continue
                if relation is not None:
                    for industry, positive in filing_industry_relations(text, aliases):
                        if industry == relation[0]:
                            target = supports if positive == relation[1] else refutes
                            target.add(chunk_id)
                elif "approved_facts" not in chunk and explicit_topic and any(_words(statement) and _words(statement) == _words(sentence)
                                            for sentence in _split_clauses(text)):
                    supports.add(chunk_id)
        if supports and refutes:
            status, reason = ClaimStatus.UNVERIFIABLE, "cited_sources_conflict"
        elif refutes:
            status, reason = ClaimStatus.CONTRADICTED, "cited_statement_refutes_claim"
        elif supports:
            status, reason = ClaimStatus.SUPPORTED, "cited_statement_entails_claim"
        elif not draft.entity_ids or not draft.metric_ids:
            status, reason = ClaimStatus.UNVERIFIABLE, "claim_context_not_resolved"
        else:
            status, reason = ClaimStatus.UNSUPPORTED, "cited_statement_support_missing"
        return ClaimAssessment(
            claim_id=draft.claim_id, statement=draft.statement, status=status,
            citation_status=CitationStatus.VALID, citations=draft.citations,
            evidence_ids=evidence_ids, supporting_evidence_ids=tuple(sorted(supports)) if status == ClaimStatus.SUPPORTED else (),
            reason_codes=(reason,),
        )

    def _describe_assessment(
        self, draft: ClaimDraft, assessment: ClaimAssessment, question_requirements: QuestionRequirements,
        layer: EvidenceDecisionLayer, catalog: CompanyCatalog, cited_chunks: list[dict[str, Any]],
    ) -> ClaimAssessment:
        calculation = draft.operation is not None or assessment.calculation is not None
        comparison = "growth_direction_matches_cited_values" in assessment.reason_codes
        if assessment.status != ClaimStatus.SUPPORTED and _UNCERTAINTY.search(draft.statement):
            claim_type = "uncertainty"
        elif assessment.status != ClaimStatus.SUPPORTED and _SPECULATION.search(draft.statement):
            claim_type = "speculation"
        elif calculation:
            claim_type = "calculation"
        elif comparison:
            claim_type = "comparison"
        elif draft.values or draft.has_unparsed_numeric_value:
            claim_type = "financial_fact"
        elif draft.metric_ids:
            claim_type = "qualitative"
        else:
            claim_type = "unclassified"
        if assessment.status != ClaimStatus.SUPPORTED:
            return assessment.model_copy(update={"claim_type": claim_type})

        sources = assessment.supporting_evidence_ids
        if claim_type == "financial_fact":
            value = draft.values[0]
            metric = next(metric for metric in (
                *question_requirements.metrics, *layer.extractor.extract(draft.statement).metrics,
            ) if metric.metric_id == value.metric_id)
            facts = self._facts_for(
                entity_id=value.entity_id, metric=metric, periods=(value.period,) if value.period else (),
                layer=layer, chunks=cited_chunks,
            )
            sources = tuple(sorted({fact.evidence_id for fact in facts if
                self._compare_value(value, (fact,))[0] == ClaimStatus.SUPPORTED}))
        elif calculation or comparison:
            sources = self._calculation_sources(draft, question_requirements, layer, cited_chunks)

        uses_endpoints = calculation or comparison
        periods = (draft.periods or question_requirements.periods) if uses_endpoints else draft.periods
        if uses_endpoints and len(periods) >= 2:
            periods = (periods[0], periods[-1])
        if not uses_endpoints and draft.values and draft.values[0].period:
            periods = (draft.values[0].period,)
        if claim_type == "qualitative":
            approved_periods = {
                fact.period for chunk in cited_chunks if chunk.get("chunk_id") in sources
                for fact in chunk.get("approved_facts", ()) if isinstance(fact, EvidenceFact)
                and fact.entity_id in draft.entity_ids and fact.metric_id in draft.metric_ids and fact.period
            }
            if not periods:
                periods = tuple(sorted(approved_periods))
        requirements = tuple(item.requirement_id for item in question_requirements.evidence if
            item.entity_id in draft.entity_ids and item.metric_id in draft.metric_ids
            and (item.period is None or any(period_matches(item.period, period) for period in periods)))
        return assessment.model_copy(update={
            "claim_type": claim_type, "supporting_evidence_ids": sources, "requirement_ids": requirements,
        })

    def _calculation_sources(
        self, draft: ClaimDraft, question_requirements: QuestionRequirements,
        layer: EvidenceDecisionLayer, cited_chunks: list[dict[str, Any]],
    ) -> tuple[str, ...]:
        metrics = (*question_requirements.metrics, *layer.extractor.extract(draft.statement).metrics)
        metric = next((item for item in metrics if item.metric_id in draft.metric_ids), None)
        periods = draft.periods or question_requirements.periods
        if metric is None or not draft.entity_ids or len(periods) < 2:
            return ()
        facts = self._facts_for(
            entity_id=draft.entity_ids[0], metric=metric, periods=periods, layer=layer, chunks=cited_chunks,
        )
        return tuple(sorted({fact.evidence_id for fact in facts if
            any(period_matches(period, fact.period) for period in (periods[0], periods[-1]))}))
