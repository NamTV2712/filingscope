"""Conservative claim and citation verification over supplied evidence only."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from src.decision.company_catalog import CompanyCatalog
from src.decision.models import EvidenceFact
from src.decision.period_value_parser import (
    PeriodValueMention,
    extract_period_value_mentions,
    period_matches,
)
from src.ingestion.period_identity import intervals_agree
from src.decision.policy import EvidenceDecisionLayer
from src.verification.models import (
    CalculationOperand,
    CalculationOperation,
    CalculationRequest,
    ClaimAssessment,
    ClaimDraft,
    ClaimStatus,
    ClaimValue,
    CitationStatus,
    ResponseDisposition,
    VerificationResult,
)
from src.verification.numerical_verifier import NumericalOperationVerifier


_BRACKET_RE = re.compile(r"[\[【]([^\]】]*)[\]】]")
_CANONICAL_RE = re.compile(r"^\s*source\s+(\d+)\s*$", re.I)
_LEGACY_LINE_RE = re.compile(r"^\s*\d+\s*†\s*L", re.I)
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?![\[【]\s*source\b)|\s*;\s*|\n+", re.I)
_SCALE_FACTORS = {
    "unit": Decimal("1"),
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
}
_CURRENCY_CUES = (
    ("USD", re.compile(r"\bUSD\b|\$|\bdollars?\b", re.I)),
    ("EUR", re.compile(r"\bEUR\b|€|\beuros?\b", re.I)),
    ("GBP", re.compile(r"\bGBP\b|£|\bpounds?\b", re.I)),
)
_SCALE_CUES = (
    ("billion", re.compile(r"\b(?:billion|bn)\b", re.I)),
    ("million", re.compile(r"\bmillion\b", re.I)),
    ("thousand", re.compile(r"\bthousand\b", re.I)),
)
_GROWTH_RE = re.compile(
    r"\b(?:growth|grew|grow|increased|increase|rose|risen|declined|decreased|"
    r"decrease|fell|dropped|year.over.year|yoy)\b",
    re.I,
)
_DIFFERENCE_RE = re.compile(
    r"\b(?:difference|increased? by|rose by|grew by|decreased? by|declined by|"
    r"fell by|dropped by|reduced by)\b",
    re.I,
)
_DECLINE_RE = re.compile(r"\b(?:declin(?:e|ed|ing)|decreas(?:e|ed|ing)|fell|fall(?:en|ing)?|dropped|reduced|contracted)\b", re.I)
_FALLBACK_RE = re.compile(
    r"could not find sufficient information|insufficient (?:information|evidence)|"
    r"unable to verify|cannot determine from (?:the )?(?:available )?evidence",
    re.I,
)
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by", "for",
    "from", "had", "has", "have", "in", "into", "is", "it", "its", "of", "on",
    "or", "that", "the", "their", "there", "these", "this", "those", "to", "was",
    "were", "which", "with", "would", "will", "than", "then", "also", "company",
    "reported", "reports", "report", "fiscal", "year", "years", "revenue", "revenues",
    "income", "sales", "assets", "liabilities", "margin", "cash", "flow", "profit",
    "grew", "grow", "increased", "increase", "decreased", "decrease", "declined", "rose",
    "fell", "was", "were", "total", "net", "operating", "gross", "financial",
}


def _as_mapping(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, Mapping):
        return dict(chunk)
    if hasattr(chunk, "model_dump"):
        return chunk.model_dump()
    if hasattr(chunk, "__dict__"):
        return dict(vars(chunk))
    raise TypeError("Evidence chunks must be mappings or structured objects")


def _deduplicate_chunks(chunks: Iterable[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in chunks:
        record = _as_mapping(chunk)
        chunk_id = record.get("chunk_id")
        if isinstance(chunk_id, str) and chunk_id:
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
        records.append(record)
    return records


def _split_clauses(answer: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_SPLIT_RE.split(answer) if part.strip()]


def _citation_details(
    statement: str,
    evidence_count: int,
) -> tuple[tuple[int, ...], int, int, CitationStatus, tuple[str, ...]]:
    valid: list[int] = []
    marker_count = 0
    malformed = 0
    out_of_range = 0
    reasons: list[str] = []
    for match in _BRACKET_RE.finditer(statement):
        content = match.group(1).strip()
        canonical = _CANONICAL_RE.fullmatch(content)
        if canonical is not None:
            marker_count += 1
            source_number = int(canonical.group(1))
            if 1 <= source_number <= evidence_count:
                valid.append(source_number)
            else:
                out_of_range += 1
            continue
        if content.casefold().startswith("source") or _LEGACY_LINE_RE.match(content):
            marker_count += 1
            malformed += 1
    if malformed:
        status = CitationStatus.MALFORMED
        reasons.append("malformed_citation")
    elif out_of_range:
        status = CitationStatus.OUT_OF_RANGE
        reasons.append("citation_out_of_range")
    elif valid:
        status = CitationStatus.VALID
    else:
        status = CitationStatus.MISSING
        reasons.append("missing_citation")
    return tuple(dict.fromkeys(valid)), marker_count, malformed + out_of_range, status, tuple(reasons)


def _context_unit(text: str, currency: str | None, scale: str | None) -> tuple[str | None, str | None]:
    if currency is None:
        found = [name for name, pattern in _CURRENCY_CUES if pattern.search(text)]
        if len(found) == 1:
            currency = found[0]
    if scale is None:
        found_scales = [name for name, pattern in _SCALE_CUES if pattern.search(text)]
        if len(found_scales) == 1:
            scale = found_scales[0]
    return currency, scale


def _find_spans(text: str, aliases: Iterable[str]) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for alias in aliases:
        if not alias:
            continue
        for match in re.finditer(rf"(?<![\w]){re.escape(alias)}(?![\w])", text, re.I):
            spans.append((match.start(), match.end(), alias))
    return spans


def _nearest_id(
    position: int,
    hits: list[tuple[int, int, str]],
    fallback: str | None,
) -> str | None:
    if len(hits) == 1:
        return hits[0][2]
    if not hits:
        return fallback
    return min(hits, key=lambda hit: min(abs(hit[0] - position), abs(hit[1] - position)))[2]


def _value_from_mention(
    mention: PeriodValueMention,
    *,
    metric_id: str,
    entity_id: str | None,
    metric_kind: str,
    question: str,
    claim_periods: tuple[str, ...],
    question_periods: tuple[str, ...],
) -> ClaimValue:
    pair = mention.pair
    currency, scale = _context_unit(f"{question} {pair.value}", pair.currency, pair.scale)
    period = pair.period
    if period is None and len(claim_periods) == 1:
        period = claim_periods[0]
    elif period is None and len(question_periods) == 1:
        period = question_periods[0]
    value_kind = pair.value_kind
    if metric_kind == "currency_per_share" and value_kind == "amount":
        value_kind = "currency_per_share"
    return ClaimValue(
        metric_id=metric_id,
        entity_id=entity_id,
        raw_value=pair.value,
        numeric_value=Decimal(pair.numeric_value),
        currency=currency,
        scale=scale,
        value_kind=value_kind if value_kind in {"amount", "percent", "currency_per_share"} else "amount",
        period=period,
    )


class ClaimLevelVerifier:
    """Verify explicitly cited numeric and topical claims conservatively.

    This verifier is deterministic. It never calls a language model and only
    analyzes the evidence chunks passed to ``verify``. Topical support uses
    lexical anchors, so paraphrases may remain unverified.
    """

    def __init__(
        self,
        *,
        catalog: CompanyCatalog | None = None,
        numerical_verifier: NumericalOperationVerifier | None = None,
    ):
        self._provided_catalog = catalog
        self._numerical_verifier = numerical_verifier or NumericalOperationVerifier()

    def _claim_statements(self, answer: str, layer: EvidenceDecisionLayer) -> list[str]:
        return _split_clauses(answer)

    @staticmethod
    def _is_fallback(answer: str) -> bool:
        return bool(_FALLBACK_RE.search(answer))

    def _describe_assessment(
        self,
        draft: ClaimDraft,
        assessment: ClaimAssessment,
        question_requirements: Any,
        layer: EvidenceDecisionLayer,
        catalog: CompanyCatalog,
        cited_chunks: list[dict[str, Any]],
    ) -> ClaimAssessment:
        return assessment

    def verify(
        self,
        question: str,
        answer: str,
        evidence_chunks: Iterable[Any],
    ) -> VerificationResult:
        chunks = _deduplicate_chunks(evidence_chunks)
        rows = [
            {key: chunk.get(key) for key in ("company", "ticker", "doc_name")}
            for chunk in chunks
        ]
        catalog = self._provided_catalog or CompanyCatalog.from_document_rows(rows)
        layer = EvidenceDecisionLayer(catalog=catalog)
        question_requirements = layer.extractor.extract(question)
        if self._is_fallback(answer):
            return VerificationResult(
                disposition=ResponseDisposition.ABSTAIN,
                reason_codes=("fallback_answer",),
                valid_citation_count=0,
                invalid_citation_count=0,
                supported_claim_count=0,
                partial_claim_count=0,
                unsupported_claim_count=0,
                contradicted_claim_count=0,
                unverifiable_claim_count=0,
            )

        assessments: list[ClaimAssessment] = []
        valid_citation_count = invalid_citation_count = 0
        for index, statement in enumerate(self._claim_statements(answer, layer), start=1):
            citations, marker_count, invalid_count, citation_status, citation_reasons = _citation_details(
                statement,
                len(chunks),
            )
            valid_citation_count += sum(1 for number in citations if number <= len(chunks))
            invalid_citation_count += invalid_count
            cited_chunks = [chunks[number - 1] for number in citations]
            cited_ids = tuple(
                str(chunk["chunk_id"])
                for chunk in cited_chunks
                if isinstance(chunk.get("chunk_id"), str)
            )
            draft, _ = self._draft(
                claim_id=f"claim_{index}",
                statement=statement,
                question=question,
                question_requirements=question_requirements,
                catalog=catalog,
                citation_numbers=citations,
                citation_marker_count=marker_count,
                malformed_citation_count=invalid_count,
                cited_chunks=cited_chunks,
            )
            if citation_status != CitationStatus.VALID:
                assessment = ClaimAssessment(
                    claim_id=draft.claim_id,
                    statement=statement,
                    status=ClaimStatus.UNVERIFIABLE,
                    citation_status=citation_status,
                    citations=citations,
                    evidence_ids=cited_ids,
                    reason_codes=citation_reasons,
                )
            else:
                assessment = self._assess_claim(
                    draft=draft,
                    question=question,
                    question_requirements=question_requirements,
                    layer=layer,
                    catalog=catalog,
                    cited_chunks=cited_chunks,
                    evidence_ids=cited_ids,
                )
            assessments.append(self._describe_assessment(
                draft, assessment, question_requirements, layer, catalog, cited_chunks,
            ))

        supported = sum(item.status == ClaimStatus.SUPPORTED for item in assessments)
        partial = sum(item.status == ClaimStatus.PARTIALLY_SUPPORTED for item in assessments)
        unsupported = sum(item.status == ClaimStatus.UNSUPPORTED for item in assessments)
        contradicted = sum(item.status == ClaimStatus.CONTRADICTED for item in assessments)
        unverifiable = sum(item.status == ClaimStatus.UNVERIFIABLE for item in assessments)
        if not assessments:
            disposition = ResponseDisposition.ABSTAIN
            reasons = ("no_verifiable_claims",)
        elif contradicted or unsupported:
            disposition = ResponseDisposition.REJECTED
            reason_list = []
            if contradicted:
                reason_list.append("contradicted_claim")
            if unsupported:
                reason_list.append("unsupported_claim")
            reasons = tuple(reason_list)
        elif unverifiable:
            disposition = ResponseDisposition.ABSTAIN if not supported and not partial else ResponseDisposition.PARTIAL
            reasons = ("unverifiable_claim",)
        elif partial:
            disposition = ResponseDisposition.PARTIAL
            reasons = ("partially_supported_claim",)
        else:
            disposition = ResponseDisposition.VERIFIED
            reasons = ("all_claims_supported",)
        return VerificationResult(
            disposition=disposition,
            claims=tuple(assessments),
            reason_codes=reasons,
            valid_citation_count=valid_citation_count,
            invalid_citation_count=invalid_citation_count,
            supported_claim_count=supported,
            partial_claim_count=partial,
            unsupported_claim_count=unsupported,
            contradicted_claim_count=contradicted,
            unverifiable_claim_count=unverifiable,
        )

    def _draft(
        self,
        *,
        claim_id: str,
        statement: str,
        question: str,
        question_requirements: Any,
        catalog: CompanyCatalog,
        citation_numbers: tuple[int, ...],
        citation_marker_count: int,
        malformed_citation_count: int,
        cited_chunks: list[dict[str, Any]],
    ) -> tuple[ClaimDraft, tuple[PeriodValueMention, ...]]:
        claim_requirements = EvidenceDecisionLayer(catalog=catalog).extractor.extract(statement)
        claim_entities = [entity.entity_id for entity in claim_requirements.entities]
        question_entities = [entity.entity_id for entity in question_requirements.entities]
        known_cited_entities = {
            entity_id
            for chunk in cited_chunks
            if (entity_id := catalog.metadata_entity_id(
                chunk.get("ticker"), chunk.get("company"), chunk.get("doc_name"), chunk.get("document_id")
            )) is not None
        }
        fallback_entity = (
            claim_entities[0] if len(claim_entities) == 1
            else question_entities[0] if len(question_entities) == 1
            else next(iter(known_cited_entities)) if len(known_cited_entities) == 1
            else None
        )
        entity_context = claim_entities or (
            [fallback_entity]
            if fallback_entity is not None and len(question_entities) != 1
            else question_entities
        )
        metrics = claim_requirements.metrics or question_requirements.metrics
        metric_ids = tuple(metric.metric_id for metric in metrics)
        periods = claim_requirements.periods
        statement_for_values = _BRACKET_RE.sub(
            lambda match: " " * len(match.group(0)),
            statement,
        )
        mentions = extract_period_value_mentions(statement_for_values)
        metric_hits: list[tuple[int, int, str]] = []
        for metric in metrics:
            metric_hits.extend((start, end, metric.metric_id) for start, end, _ in _find_spans(statement, metric.aliases))
        entity_hits: list[tuple[int, int, str]] = []
        possible_entity_ids = list(dict.fromkeys((*claim_entities, *question_entities)))
        for entity_id in possible_entity_ids:
            entity_hits.extend((start, end, entity_id) for start, end, _ in _find_spans(statement, catalog.aliases_for(entity_id)))
        values: list[ClaimValue] = []
        for mention in mentions:
            metric_id = _nearest_id(mention.start, metric_hits, metrics[0].metric_id if len(metrics) == 1 else None)
            if metric_id is None:
                continue
            metric = next((candidate for candidate in metrics if candidate.metric_id == metric_id), None)
            if metric is None:
                continue
            entity_id = _nearest_id(mention.start, entity_hits, fallback_entity)
            values.append(_value_from_mention(
                mention,
                metric_id=metric_id,
                entity_id=entity_id,
                metric_kind=metric.expected_value_kind,
                question=question,
                claim_periods=periods,
                question_periods=question_requirements.periods,
            ))
        has_unparsed_numeric = bool(mentions) and (
            len(values) < len(mentions) or len(values) > 32
        )
        period_scope = periods or question_requirements.periods
        operation = (
            "percentage_growth"
            if any(value.value_kind == "percent" for value in values) and _GROWTH_RE.search(statement)
            else "difference"
            if len(period_scope) >= 2 and _DIFFERENCE_RE.search(statement)
            else None
        )
        draft = ClaimDraft(
            claim_id=claim_id,
            statement=statement,
            citations=citation_numbers,
            citation_marker_count=min(citation_marker_count, 32),
            malformed_citation_count=min(malformed_citation_count, 32),
            entity_ids=tuple(dict.fromkeys(entity_context))[:8],
            metric_ids=metric_ids[:8],
            periods=periods[:8],
            values=tuple(values[:32]),
            has_unparsed_numeric_value=has_unparsed_numeric,
            operation=operation,
        )
        return draft, mentions

    def _assess_claim(
        self,
        *,
        draft: ClaimDraft,
        question: str,
        question_requirements: Any,
        layer: EvidenceDecisionLayer,
        catalog: CompanyCatalog,
        cited_chunks: list[dict[str, Any]],
        evidence_ids: tuple[str, ...],
    ) -> ClaimAssessment:
        if not draft.metric_ids or not draft.entity_ids and not draft.values:
            return self._qualitative_assessment(draft, layer, catalog, cited_chunks, evidence_ids)

        if draft.operation == "percentage_growth" and len(draft.periods or question_requirements.periods) >= 2 and len(draft.values) == 1:
            return self._growth_assessment(
                draft=draft,
                question_requirements=question_requirements,
                layer=layer,
                cited_chunks=cited_chunks,
                evidence_ids=evidence_ids,
            )
        if draft.operation == "difference" and len(draft.periods or question_requirements.periods) >= 2 and len(draft.values) == 1:
            return self._difference_assessment(
                draft=draft,
                question_requirements=question_requirements,
                layer=layer,
                cited_chunks=cited_chunks,
                evidence_ids=evidence_ids,
            )

        if not draft.values:
            if draft.has_unparsed_numeric_value:
                return ClaimAssessment(
                    claim_id=draft.claim_id,
                    statement=draft.statement,
                    status=ClaimStatus.UNVERIFIABLE,
                    citation_status=CitationStatus.VALID,
                    citations=draft.citations,
                    evidence_ids=evidence_ids,
                    reason_codes=("numeric_claim_not_mapped",),
                )
            if _GROWTH_RE.search(draft.statement) and len(draft.periods or question_requirements.periods) >= 2:
                direction = self._direction_assessment(draft, question_requirements, layer, cited_chunks)
                if direction is not None:
                    return ClaimAssessment(
                        claim_id=draft.claim_id,
                        statement=draft.statement,
                        status=direction[0],
                        citation_status=CitationStatus.VALID,
                        citations=draft.citations,
                        evidence_ids=evidence_ids,
                        reason_codes=(direction[1],),
                    )
            return self._qualitative_assessment(draft, layer, catalog, cited_chunks, evidence_ids)

        statuses: list[ClaimStatus] = []
        supported_values: list[str] = []
        unsupported_values: list[str] = []
        reasons: list[str] = []
        for value in draft.values:
            if value.entity_id is None:
                statuses.append(ClaimStatus.UNVERIFIABLE)
                unsupported_values.append(value.raw_value)
                reasons.append("claim_entity_not_resolved")
                continue
            metric = next((metric for metric in layer.extractor.extract(question).metrics if metric.metric_id == value.metric_id), None)
            if metric is None:
                metric = next((metric for metric in layer.extractor.extract(draft.statement).metrics if metric.metric_id == value.metric_id), None)
            if metric is None:
                statuses.append(ClaimStatus.UNVERIFIABLE)
                unsupported_values.append(value.raw_value)
                reasons.append("claim_metric_not_resolved")
                continue
            facts = self._facts_for(
                entity_id=value.entity_id,
                metric=metric,
                periods=(value.period,) if value.period else (),
                layer=layer,
                chunks=cited_chunks,
            )
            value_status, value_reason = self._compare_value(value, facts)
            statuses.append(value_status)
            reasons.append(value_reason)
            if value_status == ClaimStatus.SUPPORTED:
                supported_values.append(value.raw_value)
            else:
                unsupported_values.append(value.raw_value)

        if draft.has_unparsed_numeric_value:
            statuses.append(ClaimStatus.UNVERIFIABLE)
            reasons.append("numeric_claim_not_mapped")

        status = self._combine_statuses(statuses)
        return ClaimAssessment(
            claim_id=draft.claim_id,
            statement=draft.statement,
            status=status,
            citation_status=CitationStatus.VALID,
            citations=draft.citations,
            supported_values=tuple(supported_values),
            unsupported_values=tuple(unsupported_values),
            evidence_ids=evidence_ids,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

    def _facts_for(
        self,
        *,
        entity_id: str,
        metric: Any,
        periods: tuple[str, ...],
        layer: EvidenceDecisionLayer,
        chunks: list[dict[str, Any]],
    ) -> tuple[EvidenceFact, ...]:
        period_text = " ".join(periods)
        query = f"{entity_id} {metric.display_name} {period_text}".strip()
        coverage = layer.assess(query, chunks)
        facts = [
            fact
            for finding in coverage.findings
            for fact in finding.facts
            if fact.entity_id == entity_id
            and fact.metric_id == metric.metric_id
            and (fact.value is not None or not metric.quantitative)
        ]
        unique: dict[tuple[Any, ...], EvidenceFact] = {}
        for fact in facts:
            unique[(fact.evidence_id, fact.period, fact.numeric_value, fact.currency, fact.scale, fact.value_kind)] = fact
        return tuple(unique.values())

    @staticmethod
    def _compare_value(value: ClaimValue, facts: tuple[EvidenceFact, ...]) -> tuple[ClaimStatus, str]:
        if value.period:
            facts = tuple(fact for fact in facts if period_matches(value.period, fact.period))
        if not facts:
            return ClaimStatus.UNSUPPORTED, "cited_evidence_does_not_contain_claimed_fact"
        if not intervals_agree(fact.period_identity for fact in facts if fact.period_identity is not None):
            return ClaimStatus.UNVERIFIABLE, "cited_observation_periods_conflict"
        signatures = {
            (fact.numeric_value, fact.currency, fact.scale, fact.value_kind)
            for fact in facts
        }
        if len(signatures) > 1:
            return ClaimStatus.UNVERIFIABLE, "cited_sources_conflict"
        fact = facts[0]
        try:
            source_value = Decimal(str(fact.numeric_value))
        except Exception:
            return ClaimStatus.UNVERIFIABLE, "evidence_value_not_parseable"
        if not source_value.is_finite():
            return ClaimStatus.UNVERIFIABLE, "evidence_value_not_finite"
        if value.value_kind != fact.value_kind:
            return ClaimStatus.CONTRADICTED, "claimed_value_kind_conflicts_with_evidence"
        claim_scale = value.scale or ("unit" if value.value_kind == "percent" else None)
        fact_scale = fact.scale or ("unit" if fact.value_kind == "percent" else None)
        if claim_scale not in _SCALE_FACTORS or fact_scale not in _SCALE_FACTORS:
            if value.numeric_value != source_value:
                return ClaimStatus.CONTRADICTED, "claimed_value_conflicts_with_evidence"
            return ClaimStatus.PARTIALLY_SUPPORTED, "claim_unit_incomplete"
        if value.value_kind != "percent" and value.currency and fact.currency and value.currency != fact.currency:
            return ClaimStatus.CONTRADICTED, "claimed_currency_conflicts_with_evidence"
        claim_base = value.numeric_value * _SCALE_FACTORS[claim_scale]
        fact_base = source_value * _SCALE_FACTORS[fact_scale]
        if claim_base != fact_base:
            return ClaimStatus.CONTRADICTED, "claimed_value_conflicts_with_evidence"
        if value.value_kind != "percent" and (not value.currency or not fact.currency):
            return ClaimStatus.PARTIALLY_SUPPORTED, "currency_not_fully_specified"
        if value.value_kind != "percent" and (value.scale is None or fact.scale is None):
            return ClaimStatus.PARTIALLY_SUPPORTED, "scale_not_fully_specified"
        return ClaimStatus.SUPPORTED, "numeric_claim_matches_cited_fact"

    def _growth_assessment(
        self,
        *,
        draft: ClaimDraft,
        question_requirements: Any,
        layer: EvidenceDecisionLayer,
        cited_chunks: list[dict[str, Any]],
        evidence_ids: tuple[str, ...],
    ) -> ClaimAssessment:
        entity_id = draft.values[0].entity_id
        metric_id = draft.values[0].metric_id
        periods = draft.periods or question_requirements.periods
        if entity_id is None or len(periods) < 2:
            return ClaimAssessment(
                claim_id=draft.claim_id, statement=draft.statement,
                status=ClaimStatus.UNVERIFIABLE, citation_status=CitationStatus.VALID,
                citations=draft.citations, evidence_ids=evidence_ids,
                unsupported_values=(draft.values[0].raw_value,), reason_codes=("growth_scope_unresolved",),
            )
        metric = next((metric for metric in (*question_requirements.metrics, *layer.extractor.extract(draft.statement).metrics) if metric.metric_id == metric_id), None)
        if metric is None:
            return ClaimAssessment(
                claim_id=draft.claim_id, statement=draft.statement,
                status=ClaimStatus.UNVERIFIABLE, citation_status=CitationStatus.VALID,
                citations=draft.citations, evidence_ids=evidence_ids,
                unsupported_values=(draft.values[0].raw_value,), reason_codes=("growth_metric_unresolved",),
            )
        facts = self._facts_for(entity_id=entity_id, metric=metric, periods=periods, layer=layer, chunks=cited_chunks)
        by_period: dict[str, list[EvidenceFact]] = {}
        for period in periods:
            matches = [fact for fact in facts if period_matches(period, fact.period)]
            signatures = {(fact.numeric_value, fact.currency, fact.scale, fact.value_kind) for fact in matches}
            if len(signatures) != 1 or not matches:
                return ClaimAssessment(
                    claim_id=draft.claim_id, statement=draft.statement,
                    status=ClaimStatus.UNVERIFIABLE, citation_status=CitationStatus.VALID,
                    citations=draft.citations, evidence_ids=evidence_ids,
                    unsupported_values=(draft.values[0].raw_value,), reason_codes=("growth_inputs_missing_or_conflicted",),
                )
            by_period[period] = matches
        first, second = by_period[periods[0]][0], by_period[periods[-1]][0]
        if (
            first.value_kind != "amount"
            or second.value_kind != "amount"
            or first.currency is None
            or first.currency != second.currency
            or first.scale not in _SCALE_FACTORS
            or second.scale not in _SCALE_FACTORS
        ):
            return ClaimAssessment(
                claim_id=draft.claim_id, statement=draft.statement,
                status=ClaimStatus.UNVERIFIABLE, citation_status=CitationStatus.VALID,
                citations=draft.citations, evidence_ids=evidence_ids,
                unsupported_values=(draft.values[0].raw_value,), reason_codes=("growth_input_units_incompatible",),
            )
        reported = draft.values[0]
        reported_number = reported.numeric_value
        if _DECLINE_RE.search(draft.statement) and reported_number >= 0:
            reported_number = -reported_number
        decimal_places = max(0, -reported_number.as_tuple().exponent)
        request = CalculationRequest(
            operation=CalculationOperation.PERCENTAGE_GROWTH,
            operands=(
                CalculationOperand(value=Decimal(str(first.numeric_value)), currency=first.currency, scale=first.scale),
                CalculationOperand(value=Decimal(str(second.numeric_value)), currency=second.currency, scale=second.scale),
            ),
            reported_value=reported_number,
            reported_kind="percent",
            rounding_precision=min(8, max(2, decimal_places)),
        )
        calculation = self._numerical_verifier.verify(request)
        status = ClaimStatus.SUPPORTED if calculation.passed else (
            ClaimStatus.CONTRADICTED if calculation.status == "mismatch" else ClaimStatus.UNVERIFIABLE
        )
        reason = calculation.reason_code
        return ClaimAssessment(
            claim_id=draft.claim_id, statement=draft.statement, status=status,
            citation_status=CitationStatus.VALID, citations=draft.citations,
            supported_values=(reported.raw_value,) if status == ClaimStatus.SUPPORTED else (),
            unsupported_values=() if status == ClaimStatus.SUPPORTED else (reported.raw_value,),
            evidence_ids=evidence_ids, calculation=calculation, reason_codes=(reason,),
        )

    def _difference_assessment(
        self,
        *,
        draft: ClaimDraft,
        question_requirements: Any,
        layer: EvidenceDecisionLayer,
        cited_chunks: list[dict[str, Any]],
        evidence_ids: tuple[str, ...],
    ) -> ClaimAssessment:
        reported = draft.values[0]
        periods = draft.periods or question_requirements.periods
        entity_id = reported.entity_id
        metric = next((
            candidate
            for candidate in (*question_requirements.metrics, *layer.extractor.extract(draft.statement).metrics)
            if candidate.metric_id == reported.metric_id
        ), None)
        if entity_id is None or metric is None or len(periods) < 2:
            return ClaimAssessment(
                claim_id=draft.claim_id, statement=draft.statement,
                status=ClaimStatus.UNVERIFIABLE, citation_status=CitationStatus.VALID,
                citations=draft.citations, evidence_ids=evidence_ids,
                unsupported_values=(reported.raw_value,), reason_codes=("difference_scope_unresolved",),
            )
        facts = self._facts_for(entity_id=entity_id, metric=metric, periods=periods, layer=layer, chunks=cited_chunks)
        endpoints: list[EvidenceFact] = []
        for period in (periods[0], periods[-1]):
            matches = [fact for fact in facts if period_matches(period, fact.period)]
            signatures = {(fact.numeric_value, fact.currency, fact.scale, fact.value_kind) for fact in matches}
            if len(signatures) != 1 or not matches:
                return ClaimAssessment(
                    claim_id=draft.claim_id, statement=draft.statement,
                    status=ClaimStatus.UNVERIFIABLE, citation_status=CitationStatus.VALID,
                    citations=draft.citations, evidence_ids=evidence_ids,
                    unsupported_values=(reported.raw_value,), reason_codes=("difference_inputs_missing_or_conflicted",),
                )
            endpoints.append(matches[0])
        first, last = endpoints
        if (
            reported.value_kind != "amount"
            or first.value_kind != "amount"
            or last.value_kind != "amount"
            or first.currency is None
            or first.currency != last.currency
            or first.scale not in _SCALE_FACTORS
            or last.scale not in _SCALE_FACTORS
        ):
            return ClaimAssessment(
                claim_id=draft.claim_id, statement=draft.statement,
                status=ClaimStatus.UNVERIFIABLE, citation_status=CitationStatus.VALID,
                citations=draft.citations, evidence_ids=evidence_ids,
                unsupported_values=(reported.raw_value,), reason_codes=("difference_input_units_incompatible",),
            )
        first_base = Decimal(str(first.numeric_value)) * _SCALE_FACTORS[first.scale]
        last_base = Decimal(str(last.numeric_value)) * _SCALE_FACTORS[last.scale]
        if re.search(r"\b(?:decreased?|declined|fell|dropped|reduced)\s+by\b", draft.statement, re.I):
            direction_matches = last_base < first_base
        elif re.search(r"\b(?:increased?|rose|grew)\s+by\b", draft.statement, re.I):
            direction_matches = last_base > first_base
        else:
            direction_matches = True
        if not direction_matches:
            return ClaimAssessment(
                claim_id=draft.claim_id, statement=draft.statement,
                status=ClaimStatus.CONTRADICTED, citation_status=CitationStatus.VALID,
                citations=draft.citations, evidence_ids=evidence_ids,
                unsupported_values=(reported.raw_value,), reason_codes=("difference_direction_conflicts_with_cited_values",),
            )
        decimal_places = max(0, -reported.numeric_value.as_tuple().exponent)
        request = CalculationRequest(
            operation=CalculationOperation.DIFFERENCE,
            operands=(
                CalculationOperand(value=Decimal(str(first.numeric_value)), currency=first.currency, scale=first.scale),
                CalculationOperand(value=Decimal(str(last.numeric_value)), currency=last.currency, scale=last.scale),
            ),
            reported_value=reported.numeric_value,
            reported_currency=reported.currency,
            reported_scale=reported.scale,
            reported_kind="amount",
            rounding_precision=min(8, max(2, decimal_places)),
        )
        calculation = self._numerical_verifier.verify(request)
        status = ClaimStatus.SUPPORTED if calculation.passed else (
            ClaimStatus.CONTRADICTED if calculation.status == "mismatch" else ClaimStatus.UNVERIFIABLE
        )
        return ClaimAssessment(
            claim_id=draft.claim_id, statement=draft.statement, status=status,
            citation_status=CitationStatus.VALID, citations=draft.citations,
            supported_values=(reported.raw_value,) if status == ClaimStatus.SUPPORTED else (),
            unsupported_values=() if status == ClaimStatus.SUPPORTED else (reported.raw_value,),
            evidence_ids=evidence_ids, calculation=calculation,
            reason_codes=(calculation.reason_code,),
        )

    def _qualitative_assessment(
        self,
        draft: ClaimDraft,
        layer: EvidenceDecisionLayer,
        catalog: CompanyCatalog,
        chunks: list[dict[str, Any]],
        evidence_ids: tuple[str, ...],
    ) -> ClaimAssessment:
        if not draft.metric_ids:
            return ClaimAssessment(
                claim_id=draft.claim_id, statement=draft.statement,
                status=ClaimStatus.UNVERIFIABLE, citation_status=CitationStatus.VALID,
                citations=draft.citations, evidence_ids=evidence_ids,
                reason_codes=("claim_metric_not_recognized",),
            )
        metric_candidates = layer.extractor.extract(draft.statement).metrics
        metric = next((item for item in metric_candidates if item.metric_id == draft.metric_ids[0]), None)
        if metric is None:
            metric = next((item for item in layer.extractor.extract(" ".join(draft.metric_ids)).metrics), None)
        if metric is None or not draft.entity_ids:
            return ClaimAssessment(
                claim_id=draft.claim_id, statement=draft.statement,
                status=ClaimStatus.UNVERIFIABLE, citation_status=CitationStatus.VALID,
                citations=draft.citations, evidence_ids=evidence_ids,
                reason_codes=("claim_context_not_resolved",),
            )
        entity_id = draft.entity_ids[0]
        facts = self._facts_for(entity_id=entity_id, metric=metric, periods=draft.periods, layer=layer, chunks=chunks)
        if not facts:
            return ClaimAssessment(
                claim_id=draft.claim_id, statement=draft.statement,
                status=ClaimStatus.UNSUPPORTED, citation_status=CitationStatus.VALID,
                citations=draft.citations, evidence_ids=evidence_ids,
                reason_codes=("cited_evidence_does_not_contain_claimed_topic",),
            )
        cited_text = " ".join(str(chunk.get("text", "")) for chunk in chunks).casefold()
        entity_aliases = {alias.casefold() for alias in catalog.aliases_for(entity_id)}
        metric_aliases = {alias.casefold() for alias in metric.aliases}
        topical_statement = _BRACKET_RE.sub(" ", draft.statement).casefold()
        anchors = [
            token for token in re.findall(r"[a-z0-9]+", topical_statement)
            if token not in _STOPWORDS and len(token) > 2
            and not token.isdigit() and token not in entity_aliases and token not in metric_aliases
        ]
        anchors = list(dict.fromkeys(anchors))
        if not anchors:
            status, reason = ClaimStatus.UNVERIFIABLE, "no_topical_anchors"
        else:
            matched = [anchor for anchor in anchors if re.search(rf"(?<![a-z0-9]){re.escape(anchor)}(?![a-z0-9])", cited_text)]
            if len(matched) == len(anchors):
                status, reason = ClaimStatus.SUPPORTED, "topical_anchors_match_cited_text"
            elif matched:
                status, reason = ClaimStatus.PARTIALLY_SUPPORTED, "some_topical_anchors_match_cited_text"
            else:
                status, reason = ClaimStatus.UNSUPPORTED, "topical_anchors_not_found_in_cited_text"
        return ClaimAssessment(
            claim_id=draft.claim_id, statement=draft.statement,
            status=status, citation_status=CitationStatus.VALID,
            citations=draft.citations, evidence_ids=evidence_ids,
            reason_codes=(reason,),
        )

    def _direction_assessment(
        self,
        draft: ClaimDraft,
        question_requirements: Any,
        layer: EvidenceDecisionLayer,
        chunks: list[dict[str, Any]],
    ) -> tuple[ClaimStatus, str] | None:
        periods = draft.periods or question_requirements.periods
        if len(periods) < 2 or not draft.entity_ids or not draft.metric_ids:
            return None
        metric_candidates = (*question_requirements.metrics, *layer.extractor.extract(draft.statement).metrics)
        metric = next((item for item in metric_candidates if item.metric_id in draft.metric_ids), None)
        if metric is None:
            return None
        facts = self._facts_for(entity_id=draft.entity_ids[0], metric=metric, periods=periods, layer=layer, chunks=chunks)
        first = self._direction_operand(facts, periods[0])
        last = self._direction_operand(facts, periods[-1])
        if first is None or last is None or first.scale not in _SCALE_FACTORS or last.scale not in _SCALE_FACTORS:
            return ClaimStatus.UNVERIFIABLE, "growth_direction_inputs_missing"
        if first.currency != last.currency or first.currency is None:
            return ClaimStatus.UNVERIFIABLE, "growth_input_units_incompatible"
        difference = (
            Decimal(str(last.numeric_value)) * _SCALE_FACTORS[last.scale]
            - Decimal(str(first.numeric_value)) * _SCALE_FACTORS[first.scale]
        )
        expected_positive = not bool(_DECLINE_RE.search(draft.statement))
        matches = difference < 0 if not expected_positive else difference > 0
        return (ClaimStatus.SUPPORTED, "growth_direction_matches_cited_values") if matches else (
            ClaimStatus.CONTRADICTED, "growth_direction_conflicts_with_cited_values"
        )

    @staticmethod
    def _direction_operand(facts: tuple[EvidenceFact, ...], period: str) -> EvidenceFact | None:
        return next((fact for fact in facts if period_matches(period, fact.period)), None)

    @staticmethod
    def _combine_statuses(statuses: list[ClaimStatus]) -> ClaimStatus:
        if not statuses:
            return ClaimStatus.UNVERIFIABLE
        if ClaimStatus.CONTRADICTED in statuses:
            return ClaimStatus.CONTRADICTED
        if all(status == ClaimStatus.SUPPORTED for status in statuses):
            return ClaimStatus.SUPPORTED
        if ClaimStatus.SUPPORTED in statuses or ClaimStatus.PARTIALLY_SUPPORTED in statuses:
            return ClaimStatus.PARTIALLY_SUPPORTED
        if ClaimStatus.UNSUPPORTED in statuses:
            return ClaimStatus.UNSUPPORTED
        return ClaimStatus.UNVERIFIABLE
