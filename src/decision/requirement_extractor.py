"""Deterministic financial-question requirement extraction for P2."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from src.decision.company_catalog import CompanyCatalog
from src.decision.models import (
    EvidenceEntity,
    EvidenceRequirement,
    MetricRequirement,
    OperationRequirement,
    QuestionRequirements,
)
from src.ingestion.company_facts import requested_currencies
from src.ingestion.period_identity import period_mentions


_METRIC_DEFINITIONS: tuple[MetricRequirement, ...] = (
    MetricRequirement(metric_id="revenue", display_name="revenue", aliases=(
        "total net sales", "total revenue", "net sales", "revenues", "revenue", "sales",
    )),
    MetricRequirement(metric_id="operating_income", display_name="operating income", aliases=(
        "operating income", "income from operations",
    )),
    MetricRequirement(metric_id="net_income", display_name="net income", aliases=(
        "net income", "net earnings",
    )),
    MetricRequirement(metric_id="gross_profit", display_name="gross profit", aliases=("gross profit",)),
    MetricRequirement(metric_id="capital_expenditures", display_name="capital expenditures", aliases=(
        "capital expenditures", "capital expenditure", "capex",
    )),
    MetricRequirement(metric_id="operating_cash_flow", display_name="operating cash flow", aliases=(
        "cash flow from operations", "operating cash flow",
    )),
    MetricRequirement(metric_id="free_cash_flow", display_name="free cash flow", aliases=(
        "free cash flow", "free cashflow",
    )),
    MetricRequirement(metric_id="cash_and_equivalents", display_name="cash and cash equivalents", aliases=(
        "cash and cash equivalents", "cash and equivalents", "cash equivalents",
    )),
    MetricRequirement(metric_id="total_assets", display_name="total assets", aliases=("total assets",)),
    MetricRequirement(metric_id="total_liabilities", display_name="total liabilities", aliases=("total liabilities",)),
    MetricRequirement(metric_id="total_debt", display_name="total debt", aliases=(
        "total debt", "long term debt", "long-term debt",
    )),
    MetricRequirement(metric_id="earnings_per_share", display_name="earnings per share", aliases=(
        "earnings per share", "diluted eps", "basic eps", "eps",
    ), expected_value_kind="currency_per_share"),
    MetricRequirement(metric_id="operating_margin", display_name="operating margin", aliases=(
        "operating margin",
    ), expected_value_kind="percent"),
    MetricRequirement(metric_id="gross_margin", display_name="gross margin", aliases=(
        "gross margin",
    ), expected_value_kind="percent"),
    MetricRequirement(metric_id="dividends", display_name="dividends", aliases=(
        "dividend distributions", "dividend payments", "dividends", "dividend",
    )),
    MetricRequirement(metric_id="industry", display_name="industry", aliases=("industry",), quantitative=False, expected_value_kind="topic"),
    MetricRequirement(metric_id="business_segments", display_name="business segments", aliases=(
        "business segments", "reportable segments", "segments",
    ), quantitative=False, expected_value_kind="topic"),
    MetricRequirement(metric_id="customers", display_name="customers", aliases=(
        "primary customers", "customer base", "customers", "customer",
    ), quantitative=False, expected_value_kind="topic"),
    MetricRequirement(metric_id="risk_factors", display_name="risk factors", aliases=(
        "risk factors", "risk exposure", "risks", "risk",
    ), quantitative=False, expected_value_kind="topic"),
    MetricRequirement(metric_id="products", display_name="products", aliases=(
        "product categories", "products and services", "products", "product portfolio",
    ), quantitative=False, expected_value_kind="topic"),
)

_RELATIVE_PERIOD_RE = re.compile(
    r"\b(?:last|past|previous|prior|latest|current|most recent)\s+(?:\d+\s+)?"
    r"(?:fiscal\s+)?years?\b",
    re.I,
)
_CUMULATIVE_RE = re.compile(r"\b(?:YTD|year[- ]to[- ]date|six months ended|nine months ended)\b", re.I)
_DISCRETE_RE = re.compile(r"\b(?:discrete[- ]quarter|three months ended)\b", re.I)
_NONSTANDARD_BASIS = re.compile(
    r"\b(?:non[- ]gaap|non[- ]ifrs|pro forma|constant[- ]currency|"
    r"adjusted\s+(?:revenue|net income|operating income|margin|eps|earnings|profit))\b",
    re.I,
)
_GROWTH_RE = re.compile(
    r"\b(?:growth|grow(?:s|th|ing)?|increas(?:e|ed|ing)|decreas(?:e|ed|ing)|"
    r"trend|year.over.year|yoy|cagr)\b",
    re.I,
)
_COMPARE_RE = re.compile(
    r"\b(?:compar(?:e|es|ed|ing)|versus|vs\.?|which\s+(?:company|one)|"
    r"faster|slower|higher|lower)\b",
    re.I,
)
_OPERATION_RE = {
    "difference": re.compile(r"\b(?:difference|differ by|how much more|how much less)\b", re.I),
    "ratio": re.compile(r"\b(?:ratio|times as much|multiple)\b", re.I),
    "average": re.compile(r"\b(?:average|mean)\b", re.I),
    "explain": re.compile(r"\b(?:why|what drove|what caused|explain)\b", re.I),
}


def _periods(question: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.label for item in period_mentions(question)))


def requires_nonstandard_reporting_basis(question: str) -> bool:
    return bool(_NONSTANDARD_BASIS.search(question))


def _metrics(question: str) -> tuple[MetricRequirement, ...]:
    folded = question.casefold().replace("’", "'")
    found: dict[str, tuple[int, int]] = {}
    aliases = sorted(
        [
            (alias, metric)
            for metric in _METRIC_DEFINITIONS
            for alias in metric.aliases
        ],
        key=lambda pair: (-len(pair[0]), pair[0]),
    )
    for alias, metric in aliases:
        pattern = re.compile(rf"(?<![\w]){re.escape(alias)}(?![\w])", re.I)
        match = pattern.search(folded)
        if match is None:
            continue
        current = found.get(metric.metric_id)
        candidate = (match.start(), -len(alias))
        if current is None or candidate < current:
            found[metric.metric_id] = candidate
    ordered_ids = [
        metric_id
        for metric_id, _ in sorted(found.items(), key=lambda item: (item[1], item[0]))
    ]
    return tuple(
        next(metric for metric in _METRIC_DEFINITIONS if metric.metric_id == metric_id)
        for metric_id in ordered_ids
    )


class EvidenceRequirementExtractor:
    """Extract explicit entities, metrics, periods, operations, and evidence slots.

    The default path is intentionally rule-based and bounded. Callers can pass
    company aliases from a verified corpus so supported entities are not
    limited to the small source-project alias catalog.
    """

    def __init__(self, catalog: CompanyCatalog | None = None):
        self.catalog = catalog or CompanyCatalog()

    @classmethod
    def from_document_rows(
        cls,
        rows: Iterable[Mapping[str, object]],
        *,
        base_aliases: Mapping[str, Iterable[str]] | None = None,
    ) -> "EvidenceRequirementExtractor":
        return cls(CompanyCatalog.from_document_rows(rows, base=base_aliases))

    def extract(self, question: str) -> QuestionRequirements:
        if not question.strip():
            return QuestionRequirements(
                question=question,
                supported=False,
                unsupported_reasons=("empty_question",),
            )

        matches = self.catalog.identify(question)
        entities = tuple(
            EvidenceEntity(
                entity_id=match.entity_id,
                canonical_name=match.canonical_name,
                matched_alias=match.matched_alias,
            )
            for match in matches
        )
        metrics = _metrics(question)
        periods = _periods(question)
        cumulative = _CUMULATIVE_RE.search(question)
        cumulative_unresolved = bool(cumulative and (not periods or any(not period.startswith("Q") for period in periods)))
        if cumulative and (quarter := {"six": "Q2", "nine": "Q3"}.get(cumulative[0].casefold().split()[0])):
            cumulative_unresolved |= any(not period.startswith(quarter) for period in periods)
        if cumulative and not cumulative_unresolved and not _DISCRETE_RE.search(question):
            periods = tuple(
                period if " YTD " in period else period.replace(" ", " YTD ", 1) for period in periods
            )
        if cumulative and _DISCRETE_RE.search(question) and not any(" YTD " in period for period in periods):
            cumulative_unresolved = True
        if len(periods) == 1 and re.search(r"\b(?:year.over.year|yoy)\b", question, re.I):
            period_year = re.search(r"\d{4}", periods[0])
            if period_year is not None:
                year = int(period_year.group(0))
                prior_period = (
                    f"{periods[0].split()[0]} FY{year - 1}"
                    if periods[0].startswith("Q")
                    else f"FY{year - 1}"
                )
                periods = (prior_period, periods[0])
        relative_period = bool(_RELATIVE_PERIOD_RE.search(question))

        operations: list[str] = []
        quantitative = any(metric.quantitative for metric in metrics)
        if _GROWTH_RE.search(question):
            operations.append("growth")
        if len(entities) > 1 or _COMPARE_RE.search(question):
            operations.append("compare")
        for name, pattern in _OPERATION_RE.items():
            if pattern.search(question):
                operations.append(name)
        if not operations:
            operations.append("lookup")
        operations = list(dict.fromkeys(operations))

        unsupported_reasons: list[str] = []
        if not entities:
            unsupported_reasons.append("company_not_resolved")
        if not metrics:
            unsupported_reasons.append("metric_not_recognized")
        if relative_period:
            unsupported_reasons.append("relative_period_not_supported")
        if cumulative_unresolved:
            unsupported_reasons.append("cumulative_period_scope_unresolved")
        currencies = requested_currencies(question)
        if len(currencies) > 1:
            unsupported_reasons.append("multiple_requested_currencies")
        if any(operation in {"growth", "difference", "ratio", "average"} for operation in operations) and len(periods) == 1:
            unsupported_reasons.append("insufficient_period_scope")

        evidence: list[EvidenceRequirement] = []
        if not unsupported_reasons:
            minimum_observations = (
                2 if any(operation in {"growth", "difference", "ratio", "average"} for operation in operations) else 1
            )
            for entity in entities:
                for metric in metrics:
                    if periods:
                        for period in periods:
                            evidence.append(
                                EvidenceRequirement(
                                    requirement_id=f"{entity.entity_id}:{metric.metric_id}:{period.replace(' ', '_')}",
                                    entity_id=entity.entity_id,
                                    metric_id=metric.metric_id,
                                    period=period,
                                    quantitative=metric.quantitative,
                                )
                            )
                    else:
                        evidence.append(
                            EvidenceRequirement(
                                requirement_id=f"{entity.entity_id}:{metric.metric_id}:observations",
                                entity_id=entity.entity_id,
                                metric_id=metric.metric_id,
                                minimum_observations=minimum_observations,
                                quantitative=metric.quantitative,
                            )
                        )

        operation_requirements = tuple(
            OperationRequirement(
                operation=operation,
                metric_id=metrics[0].metric_id if len(metrics) == 1 else None,
                requires_period_alignment=(
                    quantitative and (operation == "compare" or operation in {"growth", "difference", "ratio", "average"})
                ),
                requires_unit_compatibility=(
                    quantitative and operation in {"compare", "growth", "difference", "ratio", "average"}
                ),
            )
            for operation in operations
        )
        return QuestionRequirements(
            question=question,
            entities=entities,
            companies=tuple(entity.entity_id for entity in entities),
            metrics=metrics,
            periods=periods,
            requested_currency=next(iter(currencies)) if len(currencies) == 1 else None,
            operations=operation_requirements,
            evidence=tuple(evidence),
            supported=not unsupported_reasons,
            unsupported_reasons=tuple(unsupported_reasons),
        )
