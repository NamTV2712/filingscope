"""Evidence-to-requirement alignment with provenance and value consistency."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from typing import Any

from src.decision.company_catalog import CompanyCatalog
from src.decision.filing_disclosures import (
    AMENDMENT_SCOPE_METRIC, BUSINESS_DISCLOSURE_METRICS, AmendmentScope, amendment_source_matches,
    business_disclosure_source_matches, filing_amendment_scopes, filing_industry_relations, filing_segment_disclosures,
    is_segment_list_question, requested_amendment_scope, sec_accession_matches, segment_kind_matches, segment_signature,
)
from src.decision.filing_tables import DISCLOSURE_METRIC_IDS, disclosure_cell_matches, filing_identity_matches
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
from src.decision.requirement_extractor import (
    mask_revenue_components, permits_energy_segment_lookup, requires_nonstandard_reporting_basis,
)
from src.decision.statement_columns import statement_report_date
from src.ingestion.company_facts import (
    CONSOLIDATED_METRIC_CONCEPTS, INSTANT_METRICS, METRIC_CONCEPTS, matches_requested_revision, requested_revision_policies,
)
from src.ingestion.period_identity import PeriodScope, fiscal_years_are_consecutive, intervals_agree, quarter_ytd_pair_matches
from src.ingestion.segment_revenue import ENERGY_ENTITY, ENERGY_METRIC, ENERGY_PERIOD, is_energy_evidence
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
    concepts = CONSOLIDATED_METRIC_CONCEPTS.get(metric.metric_id)
    structured = chunk.get("source_type") == "XBRL_FACT"
    statement_balance = (not structured and metric.metric_id in INSTANT_METRICS
                         and chunk.get("filing_page_checked") is True)
    disclosure_table = (not structured and metric.metric_id in DISCLOSURE_METRIC_IDS
                        and chunk.get("filing_page_checked") is True and filing_identity_matches(dict(chunk)))
    if concepts is not None and not statement_balance and not disclosure_table and (not structured or chunk.get("financial_concept") not in concepts):
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
        and (not statement_balance or fact.table_row is not None and fact.table_column is not None)
        and (metric.metric_id not in DISCLOSURE_METRIC_IDS or structured or (
            disclosure_table and fact.table_row is not None and fact.table_column is not None
            and disclosure_cell_matches(fact) and fact.filing_accession == chunk.get("accession_number")
        ))
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
        if metric.metric_id in DISCLOSURE_METRIC_IDS or metric.metric_id in CONSOLIDATED_METRIC_CONCEPTS:
            # These mappings authorize accession-bound structured facts.
            # Unscoped text can contain differently based expense components.
            return ()
        if metric.metric_id == "revenue":
            text = mask_revenue_components(text)
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
        if metric.metric_id == "industry":
            supports_topic = bool(filing_industry_relations(text, issuer_aliases))
        elif metric.metric_id in BUSINESS_DISCLOSURE_METRICS:
            supports_topic = (
                page_number is not None and page_number >= 0 and bool(source_url) and _period_from_metadata(chunk) is not None
                and any(segment_kind_matches(question, kind, len(names))
                        for kind, names in filing_segment_disclosures(text, issuer_aliases))
            )
        elif metric.metric_id == AMENDMENT_SCOPE_METRIC:
            supports_topic = page_number is not None and page_number >= 0 and bool(filing_amendment_scopes(text))
        else:
            supports_topic = _contains_alias(text, metric.aliases)
        if supports_topic:
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
        revisions = requested_revision_policies(requirements.question)
        amendment = requested_amendment_scope(requirements.question)
        interval = requirements.reporting_interval
        quarter_ytd = requirements.quarter_ytd
        fiscal_year_pair = requirements.fiscal_year_pair
        filing_instants = requirements.has_filing_instants
        needs_typed_period = interval is not None or requirements.requires_period_pair or filing_instants
        nonstandard_basis = requires_nonstandard_reporting_basis(
            requirements.question, requirements.metrics, consolidated_only=fiscal_year_pair is not None or filing_instants,
        )
        issuer_aliases = {
            entity.entity_id: tuple(dict.fromkeys((entity.matched_alias, entity.canonical_name)))
            for entity in requirements.entities
        }

        for requirement in requirements.evidence:
            metric = metric_by_id[requirement.metric_id]
            is_segment_list = metric.metric_id in BUSINESS_DISCLOSURE_METRICS
            is_amendment_scope = metric.metric_id == AMENDMENT_SCOPE_METRIC
            energy_segment = (
                metric.metric_id == ENERGY_METRIC and requirement.entity_id == ENERGY_ENTITY
                and requirement.period == ENERGY_PERIOD and len(requirements.evidence) == 1
                and permits_energy_segment_lookup(requirements.question)
            )
            if requirement.quantitative and nonstandard_basis and not energy_segment:
                findings.append(EvidenceFinding(
                    requirement_id=requirement.requirement_id, entity_id=requirement.entity_id,
                    metric_id=requirement.metric_id, period=requirement.period, status=CoverageStatus.MISSING,
                    missing_reason="nonstandard_reporting_basis_not_verified",
                ))
                continue
            if is_segment_list and not is_segment_list_question(requirements.question):
                findings.append(EvidenceFinding(
                    requirement_id=requirement.requirement_id, entity_id=requirement.entity_id,
                    metric_id=requirement.metric_id, period=requirement.period, status=CoverageStatus.MISSING,
                    missing_reason="segment_list_question_not_verified",
                ))
                continue
            candidate_facts: list[EvidenceFact] = []
            segment_lists: set[frozenset[str]] = set()
            amendment_scopes: set[AmendmentScope] = set()
            entity_chunks = 0
            usable_chunks = 0
            revision_mismatch = False
            unit_mismatch = False
            for chunk in deduplicated:
                if energy_segment and not is_energy_evidence(chunk):
                    continue
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
                if is_segment_list and not business_disclosure_source_matches(
                    requirements.question, requirement.period, _period_from_metadata(chunk), chunk,
                ):
                    revision_mismatch = True
                    usable_chunks -= 1
                    continue
                if is_amendment_scope and (
                    amendment is None
                    or not amendment_source_matches(amendment[1], _period_from_metadata(chunk), chunk)
                ):
                    revision_mismatch = True
                    usable_chunks -= 1
                    continue
                normalized = None if is_segment_list or is_amendment_scope else _normalized_facts(
                    chunk, metric, requirement.entity_id,
                )
                if normalized is not None:
                    if normalized:
                        metric_seen[requirement.requirement_id] = True
                    for fact in normalized:
                        if not period_matches(requirement.period, fact.period):
                            continue
                        if needs_typed_period:
                            accessions = {value for key in ("accession", "accession_number")
                                          if isinstance((value := chunk.get(key)), str) and value}
                            if len(accessions) > 1:
                                continue
                            accession = next(iter(accessions), None)
                            if interval and not interval.matches(fact.period_identity, accession):
                                continue
                            if quarter_ytd or fiscal_year_pair or requirement.filing_instant:
                                forms = {chunk[key] for key in ("doc_type", "filing_type", "form_type")
                                         if isinstance(chunk.get(key), str) and chunk[key]}
                                if quarter_ytd and (forms != {"10-Q"} or not quarter_ytd.matches(
                                    fact.period_identity, accession, requirement.period_scope,
                                )):
                                    continue
                                if fiscal_year_pair and (
                                    forms != {"10-K"} or chunk.get("source_type") != "XBRL_FACT"
                                    or chunk.get("financial_concept") not in METRIC_CONCEPTS.get(metric.metric_id, ())
                                    or not fiscal_year_pair.matches(fact.period_identity, accession, requirement.period_end)
                                ):
                                    continue
                                if requirement.filing_instant and (
                                    forms != {"10-K"} or not requirement.filing_instant.matches(fact.period_identity, accession)
                                    or fact.currency is None
                                    or (chunk.get("source_type") == "XBRL_FACT"
                                        and chunk.get("financial_concept") not in METRIC_CONCEPTS.get(metric.metric_id, ()))
                                    or (chunk.get("source_type") != "XBRL_FACT" and (
                                        fact.table_row is None or fact.table_column is None
                                        or statement_report_date(chunk) != requirement.filing_instant.end
                                        or not chunk.get("cik") or not sec_accession_matches(requirement.filing_instant.accession, chunk)
                                    ))
                                ):
                                    continue
                        period_seen[requirement.requirement_id] = True
                        number_seen[requirement.requirement_id] = True
                        if requirements.requested_currency is None or fact.currency == requirements.requested_currency:
                            candidate_facts.append(fact)
                        elif fact.currency is not None:
                            unit_mismatch = True
                    continue
                if needs_typed_period:
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
                        if is_segment_list:
                            for kind, names in filing_segment_disclosures(text, issuer_aliases[requirement.entity_id]):
                                if segment_kind_matches(requirements.question, kind, len(names)):
                                    segment_lists.add(segment_signature(names))
                        if is_amendment_scope:
                            amendment_scopes.update(filing_amendment_scopes(text))
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
            incompatible_periods |= requirements.requires_period_pair and len(distinct_periods) > 1
            conflicted_source = bool(source_conflict_ids[requirement.requirement_id])
            contradictory_values = len(distinct_values) > 1
            contradictory_segments = len(segment_lists) > 1
            contradictory_amendments = len(amendment_scopes) > 1

            if (conflicted_source or incompatible_periods or contradictory_values or contradictory_segments
                    or contradictory_amendments):
                status = CoverageStatus.CONFLICTED
                reason = (
                    "source_metadata_conflict" if conflicted_source else
                    "incompatible_observation_periods" if incompatible_periods else
                    "contradictory_segment_lists" if contradictory_segments else
                    "contradictory_amendment_scopes" if contradictory_amendments else
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
            elif energy_segment and entity_chunks == 0:
                status, reason = CoverageStatus.MISSING, "nonstandard_reporting_basis_not_verified"
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
        if ((quarter_ytd or fiscal_year_pair) and len(findings) == 2
                and all(finding.status == CoverageStatus.FOUND for finding in findings)):
            facts = tuple(fact for finding in findings for fact in finding.facts)
            identities = {fact.period_identity for fact in facts if fact.period_identity is not None}
            currencies = {fact.currency for fact in facts}
            concept_by_chunk = {chunk["chunk_id"]: chunk.get("financial_concept") for chunk in deduplicated}
            concepts = {concept for fact in facts if (concept := concept_by_chunk.get(fact.evidence_id)) is not None}
            if quarter_ytd:
                by_scope = {fact.period_identity.scope: fact.period_identity for fact in facts
                            if fact.period_identity is not None}
                if (set(by_scope) != {PeriodScope.QUARTER, PeriodScope.YEAR_TO_DATE} or len(currencies) != 1
                        or len(concepts) > 1 or not quarter_ytd_pair_matches(
                            by_scope[PeriodScope.QUARTER], by_scope[PeriodScope.YEAR_TO_DATE],
                        )):
                    operation_gaps += ("incompatible_quarter_ytd_pair",)
            elif fiscal_year_pair:
                by_end = {period.end: period for period in identities}
                earlier, later = fiscal_year_pair.ends
                if (len(identities) != 2 or set(by_end) != {earlier, later} or len(currencies) != 1
                        or None in currencies or len(concepts) != 1
                        or not fiscal_years_are_consecutive(by_end[earlier], by_end[later])):
                    operation_gaps += ("incompatible_fiscal_year_pair",)
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
