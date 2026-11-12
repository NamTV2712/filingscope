"""Evidence-to-requirement alignment with provenance and value consistency."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from typing import Any

from src.decision.company_catalog import CompanyCatalog
from src.decision.models import (
    CoverageStatus,
    EvidenceCoverage,
    EvidenceFact,
    EvidenceFinding,
    MetricRequirement,
    QuestionRequirements,
)
from src.decision.period_value_parser import (
    PeriodValuePair,
    extract_filing_assertions,
    extract_period_value_pairs,
    period_matches,
)
from src.decision.requirement_extractor import requires_nonstandard_reporting_basis
from src.ingestion.company_facts import matches_requested_revision, requested_revision_policies
from src.ingestion.period_identity import intervals_agree
from src.retrieval.structured_lookup import structured_lookup


_NUMBER_RE = re.compile(r"(?<![\w.])(?:\$|€|£)?\s*\(?-?\d[\d,]*(?:\.\d+)?\)?\s*(?:%|percent)?", re.I)
_STRUCTURED_METRICS = {
    "total_assets": "total assets",
    "total_liabilities": "total liabilities",
    "revenue": "total revenue",
    "net_income": "net income",
}


def _mapping(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, Mapping):
        return dict(chunk)
    if is_dataclass(chunk):
        return asdict(chunk)
    if hasattr(chunk, "model_dump"):
        return chunk.model_dump()
    if hasattr(chunk, "__dict__"):
        return dict(vars(chunk))
    raise TypeError("Evidence chunks must be mappings or structured objects")


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _contains_alias(text: str, aliases: tuple[str, ...]) -> bool:
    normalized = _normalized(text)
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(_normalized(alias))}(?![a-z0-9])", normalized)
        for alias in aliases
    )


def _has_provenance(chunk: Mapping[str, Any]) -> bool:
    document_id = chunk.get("doc_name") or chunk.get("document_id")
    locator = (
        chunk.get("source_url")
        or chunk.get("source_repository_url")
        or chunk.get("filing_url")
        or chunk.get("citation")
        or chunk.get("page_number") is not None
    )
    return isinstance(document_id, str) and bool(document_id.strip()) and bool(locator)


def _entity_ids(chunk: Mapping[str, Any], catalog: CompanyCatalog) -> set[str]:
    resolved = {
        entity_id
        for value in (
            chunk.get("ticker"),
            chunk.get("company"),
            chunk.get("doc_name"),
            chunk.get("document_id"),
        )
        if (entity_id := catalog.metadata_entity_id(value)) is not None
    }
    return resolved


def _period_from_metadata(chunk: Mapping[str, Any]) -> str | None:
    values = chunk.get("reporting_periods")
    if isinstance(values, str):
        values = [values]
    if isinstance(values, Iterable) and not isinstance(values, (bytes, dict)):
        normalized = sorted({
            f"FY{match.group(0)}"
            for value in values
            if (match := re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", str(value)))
        })
        if len(normalized) == 1:
            return normalized[0]
    fiscal_year = chunk.get("fiscal_year")
    match = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", str(fiscal_year or ""))
    return f"FY{match.group(0)}" if match else None


def _source_metadata_conflict(chunk: Mapping[str, Any]) -> bool:
    conflicts = chunk.get("metadata_conflicts")
    if not isinstance(conflicts, (list, tuple)):
        return False
    for conflict in conflicts:
        if isinstance(conflict, Mapping) and conflict.get("field") in {"company", "doc_type"}:
            return True
    return False


def _kind_matches(pair: PeriodValuePair | EvidenceFact, metric: MetricRequirement) -> bool:
    expected = metric.expected_value_kind
    if expected == "topic":
        return False
    if expected == "percent":
        return pair.value_kind == "percent"
    if expected == "currency_per_share":
        return pair.value_kind in {"amount", "currency_per_share"}
    return pair.value_kind == "amount"


def _normalized_facts(
    chunk: Mapping[str, Any], metric: MetricRequirement, entity_id: str,
) -> tuple[EvidenceFact, ...] | None:
    if not metric.quantitative and chunk.get("source_type") != "XBRL_FACT":
        return None
    approved = chunk.get("approved_facts")
    values = approved if approved is not None else chunk.get("normalized_facts")
    if values is None and chunk.get("source_type") != "XBRL_FACT":
        return None
    if not isinstance(values, tuple):
        return ()
    source_url = chunk.get("source_url") or chunk.get("source_repository_url") or chunk.get("filing_url")
    return tuple(
        fact for fact in values
        if isinstance(fact, EvidenceFact)
        and fact.evidence_id == chunk.get("chunk_id")
        and fact.document_id == (chunk.get("doc_name") or chunk.get("document_id"))
        and fact.source_url == source_url
        and fact.entity_id == entity_id
        and fact.metric_id == metric.metric_id
        and (approved is not None and fact.period_identity is None
             or fact.period_identity is not None and fact.period_identity.label == fact.period)
        and _kind_matches(fact, metric)
    )


def _exact_structured_block(text: str, matched_line: str) -> str:
    """Keep the exact SEC row and the nearest explicit period header."""
    lines = text.splitlines()
    row_index = next(
        (index for index, line in enumerate(lines) if line.strip() == matched_line),
        None,
    )
    if row_index is None:
        return ""
    start = row_index
    while start > 0 and lines[start - 1].strip().startswith("|"):
        start -= 1
    period_header: str | None = None
    for line in lines[start:row_index]:
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) > 1 and all(
            re.fullmatch(
                r"(?:(?:Q[1-4]\s*)?(?:FY\s*)?)(?:19|20)\d{2}",
                cell,
                re.I,
            )
            for cell in cells[1:]
        ):
            period_header = line
    if period_header is None:
        return ""
    return "\n".join((period_header, lines[row_index]))


def _facts_from_chunk(
    chunk: Mapping[str, Any],
    *,
    question: str,
    metric: MetricRequirement,
    entity_id: str,
    issuer_aliases: tuple[str, ...] = (),
) -> tuple[EvidenceFact, ...]:
    chunk_id = chunk.get("chunk_id")
    text = chunk.get("text")
    if not isinstance(chunk_id, str) or not chunk_id or not isinstance(text, str):
        return ()
    document_id = str(chunk.get("doc_name") or chunk.get("document_id") or "")
    if not document_id:
        return ()
    page_number = chunk.get("page_number")
    if isinstance(page_number, bool) or not isinstance(page_number, int):
        page_number = None
    source_url = (
        chunk.get("source_url")
        or chunk.get("source_repository_url")
        or chunk.get("filing_url")
    )
    observations: list[PeriodValuePair] = []
    if metric.quantitative:
        # Reuse the migrated exact SEC table-row matcher for canonical total
        # rows. It only sees this retrieved chunk, never the complete corpus.
        ticker = chunk.get("ticker")
        structured_match = None
        if isinstance(ticker, str) and metric.metric_id in _STRUCTURED_METRICS:
            canonical_query = f"{question} {_STRUCTURED_METRICS[metric.metric_id]}"
            structured_match = structured_lookup(canonical_query, ticker, [dict(chunk)])
        if structured_match is not None:
            exact_block = _exact_structured_block(text, structured_match.line)
            observations.extend(
                extract_period_value_pairs(
                    exact_block,
                    metric_aliases=metric.aliases,
                )
            )
        elif chunk.get("filing_page_checked") is True:
            observations.extend(extract_filing_assertions(text, metric_aliases=metric.aliases, issuer_aliases=issuer_aliases))
        else:
            observations.extend(
                extract_period_value_pairs(text, metric_aliases=metric.aliases)
            )

    facts: list[EvidenceFact] = []
    if metric.quantitative:
        period_metadata = None if chunk.get("filing_page_checked") is True else _period_from_metadata(chunk)
        for pair in observations:
            if not _kind_matches(pair, metric):
                continue
            period = pair.period or period_metadata
            fact = EvidenceFact(
                evidence_id=chunk_id,
                entity_id=entity_id,
                metric_id=metric.metric_id,
                period=period,
                value=pair.value,
                numeric_value=pair.numeric_value,
                currency=pair.currency,
                scale=pair.scale,
                value_kind=(
                    "currency_per_share"
                    if metric.expected_value_kind == "currency_per_share"
                    else pair.value_kind
                ),
                document_id=document_id,
                page_number=page_number,
                source_url=str(source_url) if source_url else None,
            )
            facts.append(fact)
    else:
        if _contains_alias(text, metric.aliases):
            facts.append(
                EvidenceFact(
                    evidence_id=chunk_id,
                    entity_id=entity_id,
                    metric_id=metric.metric_id,
                    period=_period_from_metadata(chunk),
                    document_id=document_id,
                    page_number=page_number,
                    source_url=str(source_url) if source_url else None,
                    value_kind="topic",
                )
            )
    return tuple(facts)


_SCALE_EXPONENTS = {"unit": 0, "thousand": 3, "million": 6, "billion": 9}


def _value_signature(fact: EvidenceFact) -> tuple[str, str | None, str | None, str | None]:
    scale = fact.scale
    try:
        value = Decimal(str(fact.numeric_value or fact.value))
        if scale in _SCALE_EXPONENTS:
            value = value.scaleb(_SCALE_EXPONENTS[scale])
            scale = "unit"
        normalized = str(value.normalize())
    except Exception:
        normalized = str(fact.value)
    return normalized, fact.currency, scale, fact.value_kind


class EvidenceCoverageAnalyzer:
    """Match evidence to every required entity/metric/period slot."""

    def __init__(self, catalog: CompanyCatalog | None = None):
        self.catalog = catalog or CompanyCatalog()

    def analyze(
        self,
        requirements: QuestionRequirements,
        chunks: Iterable[Any],
    ) -> EvidenceCoverage:
        records = [_mapping(chunk) for chunk in chunks]
        deduplicated: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for record in records:
            chunk_id = record.get("chunk_id")
            if not isinstance(chunk_id, str) or not chunk_id or chunk_id in seen_ids:
                continue
            seen_ids.add(chunk_id)
            deduplicated.append(record)

        metric_by_id = {metric.metric_id: metric for metric in requirements.metrics}
        findings: list[EvidenceFinding] = []
        metric_seen: dict[str, bool] = defaultdict(bool)
        period_seen: dict[str, bool] = defaultdict(bool)
        number_seen: dict[str, bool] = defaultdict(bool)
        source_conflict_ids: dict[str, set[str]] = defaultdict(set)
        nonstandard_basis = requires_nonstandard_reporting_basis(requirements.question)
        revisions = requested_revision_policies(requirements.question)
        issuer_aliases = {
            entity.entity_id: tuple(dict.fromkeys((entity.matched_alias, entity.canonical_name)))
            for entity in requirements.entities
        }

        for requirement in requirements.evidence:
            metric = metric_by_id[requirement.metric_id]
            if requirement.quantitative and nonstandard_basis:
                findings.append(EvidenceFinding(
                    requirement_id=requirement.requirement_id, entity_id=requirement.entity_id,
                    metric_id=requirement.metric_id, period=requirement.period, status=CoverageStatus.MISSING,
                    missing_reason="nonstandard_reporting_basis_not_verified",
                ))
                continue
            candidate_facts: list[EvidenceFact] = []
            entity_chunks = 0
            usable_chunks = 0
            revision_mismatch = False
            unit_mismatch = False
            for chunk in deduplicated:
                entity_ids = _entity_ids(chunk, self.catalog)
                if requirement.entity_id not in entity_ids:
                    continue
                entity_chunks += 1
                if not _has_provenance(chunk):
                    continue
                if not matches_requested_revision(chunk.get("revision_kind"), revisions):
                    revision_mismatch = True
                    continue
                usable_chunks += 1
                if len(entity_ids) > 1 or _source_metadata_conflict(chunk):
                    source_conflict_ids[requirement.requirement_id].add(str(chunk["chunk_id"]))
                    continue
                normalized = _normalized_facts(chunk, metric, requirement.entity_id)
                if normalized is not None:
                    if normalized:
                        metric_seen[requirement.requirement_id] = True
                    for fact in normalized:
                        if not period_matches(requirement.period, fact.period):
                            continue
                        period_seen[requirement.requirement_id] = True
                        number_seen[requirement.requirement_id] = True
                        if requirements.requested_currency is None or fact.currency == requirements.requested_currency:
                            candidate_facts.append(fact)
                        elif fact.currency is not None:
                            unit_mismatch = True
                    continue
                text = chunk.get("text")
                if not isinstance(text, str):
                    continue
                if not _contains_alias(text, metric.aliases):
                    continue
                metric_seen[requirement.requirement_id] = True
                text_periods = [
                    *(f"FY{year}" for year in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text)),
                    *(f"Q{quarter} FY{year}" for quarter, year in re.findall(
                        r"\bQ([1-4])\s*(?:FY\s*)?((?<!\d)(?:19|20)\d{2})(?!\d)", text, re.I
                    )),
                ]
                if requirement.period is not None and any(
                    period_matches(requirement.period, evidence_period)
                    for evidence_period in text_periods
                ):
                    period_seen[requirement.requirement_id] = True
                if any(
                    match is not None
                    and not re.fullmatch(r"(?:19|20)\d{2}", match.group(0).replace(",", "").strip())
                    for match in _NUMBER_RE.finditer(text)
                ):
                    number_seen[requirement.requirement_id] = True
                for fact in _facts_from_chunk(
                    chunk,
                    question=requirements.question,
                    metric=metric,
                    entity_id=requirement.entity_id,
                    issuer_aliases=issuer_aliases.get(requirement.entity_id, ()),
                ):
                    if not period_matches(requirement.period, fact.period):
                        continue
                    if not requirement.quantitative or requirements.requested_currency in (None, fact.currency):
                        candidate_facts.append(fact)
                    elif fact.currency is not None:
                        unit_mismatch = True

            candidate_facts = list({
                (
                    fact.evidence_id, fact.entity_id, fact.metric_id,
                    fact.period, fact.value, fact.currency, fact.scale,
                    fact.value_kind, fact.document_id, fact.page_number, fact.period_identity,
                    fact.table_row, fact.table_column,
                ): fact
                for fact in candidate_facts
            }.values())
            distinct_values = {_value_signature(fact) for fact in candidate_facts if fact.value is not None}
            distinct_periods = {fact.period for fact in candidate_facts if fact.period is not None}
            incompatible_periods = len(distinct_periods) == 1 and not intervals_agree(
                fact.period_identity for fact in candidate_facts if fact.period_identity is not None
            )
            conflicted_source = bool(source_conflict_ids[requirement.requirement_id])
            contradictory_values = len(distinct_values) > 1

            if conflicted_source or incompatible_periods or contradictory_values:
                status = CoverageStatus.CONFLICTED
                reason = (
                    "source_metadata_conflict" if conflicted_source else
                    "incompatible_observation_periods" if incompatible_periods else
                    "contradictory_values_or_units"
                )
            elif (
                len(candidate_facts) >= 1
                and (
                    len(candidate_facts) >= requirement.minimum_observations
                    if requirement.minimum_observations == 1
                    else len(distinct_periods) >= requirement.minimum_observations
                )
            ):
                status = CoverageStatus.FOUND
                reason = None
            elif candidate_facts:
                status = CoverageStatus.MISSING
                reason = "insufficient_period_observations"
            elif entity_chunks == 0:
                status = CoverageStatus.MISSING
                reason = "entity_mismatch"
            elif usable_chunks == 0:
                status = CoverageStatus.MISSING
                reason = "source_revision_mismatch" if revision_mismatch else "source_provenance_missing"
            elif not metric_seen[requirement.requirement_id]:
                status = CoverageStatus.MISSING
                reason = "metric_mismatch"
            elif requirement.period is not None and not period_seen[requirement.requirement_id]:
                status = CoverageStatus.MISSING
                reason = "period_mismatch"
            elif metric.quantitative and not number_seen[requirement.requirement_id]:
                status = CoverageStatus.MISSING
                reason = "numerical_value_missing"
            elif unit_mismatch:
                status = CoverageStatus.MISSING
                reason = "unit_mismatch"
            else:
                status = CoverageStatus.MISSING
                reason = "numerical_value_or_period_alignment_missing"

            findings.append(
                EvidenceFinding(
                    requirement_id=requirement.requirement_id,
                    entity_id=requirement.entity_id,
                    metric_id=requirement.metric_id,
                    period=requirement.period,
                    status=status,
                    evidence_ids=tuple(sorted({fact.evidence_id for fact in candidate_facts})),
                    facts=tuple(sorted(candidate_facts, key=lambda fact: (
                        fact.period or "", fact.document_id, fact.evidence_id, fact.value or ""
                    ))),
                    missing_reason=reason,
                )
            )

        missing_ids = tuple(
            finding.requirement_id
            for finding in findings
            if finding.status == CoverageStatus.MISSING
        )
        conflicted_ids = tuple(
            finding.requirement_id
            for finding in findings
            if finding.status == CoverageStatus.CONFLICTED
        )
        operation_gaps = self._operation_gaps(requirements, findings)
        sufficient = bool(requirements.supported) and not missing_ids and not conflicted_ids and not operation_gaps
        return EvidenceCoverage(
            requirements=requirements,
            findings=tuple(findings),
            missing_requirement_ids=missing_ids,
            conflicted_requirement_ids=conflicted_ids,
            operation_gaps=operation_gaps,
            sufficient=sufficient,
        )

    @staticmethod
    def _operation_gaps(
        requirements: QuestionRequirements,
        findings: list[EvidenceFinding],
    ) -> tuple[str, ...]:
        gaps: list[str] = []
        found = [finding for finding in findings if finding.status == CoverageStatus.FOUND]
        for operation in requirements.operations:
            if not operation.requires_period_alignment and not operation.requires_unit_compatibility:
                continue
            selected = [
                finding for finding in found
                if operation.metric_id is None or finding.metric_id == operation.metric_id
            ]
            facts = [fact for finding in selected for fact in finding.facts if fact.value is not None]
            fact_operands = {
                (fact.entity_id, fact.period, _value_signature(fact))
                for fact in facts
            }
            can_use_multiple_periods_from_one_slot = (
                operation.operation in {"growth", "difference", "ratio", "average"}
                and len(fact_operands) >= 2
            )
            if len(selected) < 2 and not can_use_multiple_periods_from_one_slot:
                gaps.append(f"{operation.operation}:insufficient_operands")
                continue
            if operation.requires_unit_compatibility:
                units = {_value_signature(fact)[1:] for fact in facts}
                if len(units) > 1:
                    gaps.append(f"{operation.operation}:unit_mismatch")
                    continue
                if not facts or not all(
                    fact.value_kind == "percent"
                    or (fact.currency is not None and fact.scale is not None)
                    for fact in facts
                ):
                    gaps.append(f"{operation.operation}:unit_unknown")
                    continue
            if operation.requires_period_alignment:
                periods_by_entity: dict[str, set[str]] = defaultdict(set)
                for fact in facts:
                    if fact.period:
                        periods_by_entity[fact.entity_id].add(fact.period)
                if len(periods_by_entity) > 1 and len({tuple(sorted(value)) for value in periods_by_entity.values()}) > 1:
                    gaps.append(f"{operation.operation}:period_mismatch")
                elif not periods_by_entity or any(not periods for periods in periods_by_entity.values()):
                    gaps.append(f"{operation.operation}:period_unknown")
        return tuple(dict.fromkeys(gaps))
