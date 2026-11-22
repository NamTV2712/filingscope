"""Deterministic financial-question requirement extraction for P2."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from src.decision.company_catalog import CompanyCatalog, normalize_entity
from src.decision.filing_disclosures import (
    AMENDMENT_SCOPE_METRIC, business_disclosure_issuer_text, requested_amendment_scope,
)
from src.decision.filing_tables import DISCLOSURE_METRICS, commodity_split_question
from src.decision.models import (
    EvidenceEntity,
    EvidenceRequirement,
    MetricRequirement,
    OperationRequirement,
    QuestionRequirements,
)
from src.decision.percentages import percentage_operands, requested_statement_date, requests_percentage
from src.ingestion.company_facts import (
    CONSOLIDATED_METRIC_CONCEPTS, INSTANT_METRICS, requested_currencies, requested_revision_policies,
)
from src.ingestion.period_identity import (
    FilingInstant, PeriodScope, mask_reported_as_of_dates, period_mentions, requested_filing_instants, requested_fiscal_year_pair,
    requested_quarter_ytd, requested_reporting_interval,
)
from src.ingestion.segment_revenue import ENERGY_ALIASES, ENERGY_FILING, ENERGY_LABEL, ENERGY_METRIC


_AMENDMENT_SCOPE = MetricRequirement(
    metric_id=AMENDMENT_SCOPE_METRIC, display_name="explanatory note", aliases=("explanatory note",),
    quantitative=False, expected_value_kind="topic",
)


_METRIC_DEFINITIONS: tuple[MetricRequirement, ...] = (
    *DISCLOSURE_METRICS,
    MetricRequirement(metric_id=ENERGY_METRIC, display_name=ENERGY_LABEL, aliases=ENERGY_ALIASES),
    MetricRequirement(metric_id="revenue", display_name="revenue", aliases=(
        "total net sales", "total revenue", "net sales", "revenues", "revenue", "sales",
    )),
    MetricRequirement(metric_id="contract_revenue", display_name="revenue from contracts with customers", aliases=(
        "revenue from contracts with customers", "revenues from contracts with customers", "revenue from contract with customer",
        "revenue from contract with customer, excluding assessed tax",
        "revenue from contract with customer excluding assessed tax",
    )),
    MetricRequirement(metric_id="operating_income", display_name="operating income", aliases=(
        "operating income", "income from operations",
    )),
    MetricRequirement(metric_id="operating_expenses", display_name="operating expenses", aliases=("operating expenses",)),
    MetricRequirement(metric_id="net_income", display_name="net income", aliases=(
        "net income", "net earnings",
    )),
    MetricRequirement(metric_id="gross_profit", display_name="gross profit", aliases=("gross profit",)),
    MetricRequirement(metric_id="cost_of_revenue", display_name="cost of revenue", aliases=(
        "cost of revenue", "cost of revenues",
    )),
    MetricRequirement(metric_id="income_tax_expense", display_name="income tax expense", aliases=(
        "income tax expense", "provision for income taxes",
    )),
    MetricRequirement(
        metric_id="continuing_operations_pretax_income",
        display_name="income from continuing operations before income taxes",
        aliases=(
            "income from continuing operations before income taxes",
            "income (loss) from continuing operations before income taxes",
        ),
    ),
    MetricRequirement(metric_id="research_and_development_expense", display_name="research and development expense", aliases=(
        "research and development expense", "research and development expenses", "r&d expense", "r&d expenses",
    )),
    MetricRequirement(
        metric_id="selling_general_administrative_expense",
        display_name="selling, general and administrative expense",
        aliases=("selling, general and administrative expense", "selling, general and administrative expenses",
                 "selling general and administrative expense", "selling general and administrative expenses",
                 "sg&a expense", "sg&a expenses"),
    ),
    MetricRequirement(metric_id="investing_cash_flow", display_name="net cash from investing activities", aliases=(
        "net cash from investing activities", "net cash provided by (used in) investing activities",
    )),
    MetricRequirement(metric_id="financing_cash_flow", display_name="net cash from financing activities", aliases=(
        "net cash from financing activities", "net cash provided by (used in) financing activities",
    )),
    MetricRequirement(metric_id="capital_expenditures", display_name="capital expenditures", aliases=(
        "capital expenditures", "capital expenditure", "capex",
        "payments to acquire property, plant and equipment", "payments to acquire property, plant, and equipment",
    )),
    MetricRequirement(metric_id="operating_cash_flow", display_name="operating cash flow", aliases=(
        "cash flow from operations", "operating cash flow", "net cash from operating activities",
    )),
    MetricRequirement(metric_id="free_cash_flow", display_name="free cash flow", aliases=(
        "free cash flow", "free cashflow",
    )),
    MetricRequirement(metric_id="cash_and_equivalents", display_name="cash and cash equivalents", aliases=(
        "cash and cash equivalents", "cash and equivalents", "cash equivalents",
    )),
    MetricRequirement(metric_id="total_assets", display_name="total assets", aliases=("total assets",)),
    MetricRequirement(metric_id="total_liabilities", display_name="total liabilities", aliases=("total liabilities",)),
    MetricRequirement(
        metric_id="current_net_accounts_receivable", display_name="current net accounts receivable",
        aliases=("current net accounts receivable", "net current accounts receivable"),
    ),
    MetricRequirement(metric_id="current_assets", display_name="current assets", aliases=("current assets",)),
    MetricRequirement(metric_id="noncurrent_assets", display_name="noncurrent assets", aliases=("noncurrent assets",)),
    MetricRequirement(metric_id="current_liabilities", display_name="current liabilities", aliases=("current liabilities",)),
    MetricRequirement(metric_id="net_inventory", display_name="net inventory", aliases=("net inventory",)),
    MetricRequirement(
        metric_id="net_property_plant_equipment", display_name="net property, plant and equipment",
        aliases=("net property, plant and equipment", "net property, plant, and equipment"),
    ),
    MetricRequirement(
        metric_id="stockholders_equity", display_name="stockholders' equity",
        aliases=("stockholders' equity", "stockholders equity", "equity attributable to the parent"),
    ),
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
    MetricRequirement(metric_id="business_lines", display_name="lines of business", aliases=("lines of business",),
                      quantitative=False, expected_value_kind="topic"),
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
_COST_OF_REVENUE = re.compile(r"\bcost of (?:revenues?|sales)\b", re.I)
_CONTRACT_REVENUE = re.compile(r"\brevenues? from contracts? with customers?(?:,? excluding assessed tax)?\b", re.I)
_CONTRACT_REVENUE_OTHER_BASIS = re.compile(r"\bincluding (?:assessed |sales )?tax(?:es)?\b", re.I)
_COMPONENT_SCOPE = re.compile(
    r"\b(?:excluding|adjusted|discontinued operations|domestic|foreign|federal|state|deferred|subsidiar(?:y|ies))\b"
    r"|\b(?:products?|services?) cost of revenues?\b",
    re.I,
)
_CURRENT_TAX_COMPONENT = re.compile(
    r"\b(?:current|cash)\s+(?:income tax expense|provision for income taxes)\b"
    r"|\b(?:income tax expense|provision for income taxes)\s*\((?:current|cash)\)",
    re.I,
)
_SEGMENT_BASIS = re.compile(
    r"\b(?:energy generation and storage|(?:business |reportable )?segments?)\b",
    re.I,
)
_ENERGY_METRIC_RE = re.compile(r"\b(?:" + "|".join(map(re.escape, ENERGY_ALIASES)) + r")\b", re.I)
_ENERGY_ACCESSION_RE = re.compile(r"\b\d{10}-\d{2}-\d{6}\b")
_ENERGY_LOOKUP_WORDS = frozenset({
    "what", "was", "is", "the", "how", "much", "did", "report", "reported", "total", "tesla", "tsla",
    "inc", "s", "for", "in", "from", "of", "its", "according", "to", "form", "filing", "sec", "accession",
    "as", "filed", "originally", "dollars", "usd", "million", "millions", "billion", "billions",
})
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


def mask_contract_revenue(text: str) -> str:
    return _CONTRACT_REVENUE.sub(lambda match: " " * len(match[0]), text)


def requires_nonstandard_reporting_basis(
    question: str, metrics: tuple[MetricRequirement, ...] = (), *, consolidated_only: bool = False,
) -> bool:
    if _NONSTANDARD_BASIS.search(question) or _SEGMENT_BASIS.search(question):
        return True
    consolidated_metric = consolidated_only or any(metric.metric_id in CONSOLIDATED_METRIC_CONCEPTS for metric in metrics)
    contract_revenue = any(metric.metric_id == "contract_revenue" for metric in metrics)
    if contract_revenue and _CONTRACT_REVENUE_OTHER_BASIS.search(question):
        return True
    scope = mask_contract_revenue(question) if contract_revenue else question
    return consolidated_metric and bool(_COMPONENT_SCOPE.search(scope) or _CURRENT_TAX_COMPONENT.search(question))


def mask_cost_of_revenue(text: str) -> str:
    """Keep offsets stable when resolving embedded issuer and revenue aliases."""
    return _COST_OF_REVENUE.sub(lambda match: " " * len(match[0]), text)


def mask_revenue_components(text: str) -> str:
    return mask_contract_revenue(mask_cost_of_revenue(text))


def permits_energy_segment_lookup(question: str, *, assertion: bool = False) -> bool:
    """Admit a plain segment-total lookup or assertion with recognized qualifiers."""
    if not _ENERGY_METRIC_RE.search(question) or any(
        accession != ENERGY_FILING.accession_number for accession in _ENERGY_ACCESSION_RE.findall(question)
    ):
        return False
    remainder = _ENERGY_METRIC_RE.sub(" ", question)
    remainder = _ENERGY_ACCESSION_RE.sub(" ", remainder)
    remainder = re.sub(r"\b(?:fy\s*)?2024\b|\b10-?k\b", " ", remainder, flags=re.I)
    if assertion:
        remainder = re.sub(r"\b\d[\d,.]*\b", " ", remainder)
    return set(re.findall(r"\w+", remainder.casefold())) <= _ENERGY_LOOKUP_WORDS


def _metrics(question: str) -> tuple[MetricRequirement, ...]:
    from src.decision.filing_bounds import CUSTOMER_CONCENTRATION, customer_concentration_question

    if customer_concentration_question(question):
        return (CUSTOMER_CONCENTRATION,)
    folded = question.casefold().replace("’", "'")
    revenue_text = mask_revenue_components(folded)
    for metric in DISCLOSURE_METRICS:
        for alias in sorted(metric.aliases, key=len, reverse=True):
            revenue_text = re.sub(rf"(?<![\w]){re.escape(alias)}(?![\w])", " ", revenue_text, flags=re.I)
    if commodity_split_question(question):
        revenue_text = re.sub(r"\b(?:sales|revenues?)\s+(?:split|breakdown)\s+by\s+commodity\b", " ", revenue_text)
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
        text = revenue_text if metric.metric_id in {"revenue", "customers"} else folded
        match = pattern.search(text)
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
    if ENERGY_METRIC in found and "revenue" in found:
        remainder = _ENERGY_METRIC_RE.sub(" ", folded)
        if not re.search(r"\brevenues?\b|\bsales\b", remainder):
            ordered_ids.remove("revenue")
    if commodity_split_question(question):
        ordered_ids = list(dict.fromkeys((*ordered_ids, "oil_sales", "gas_sales", "ngl_sales")))
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

        # COST is also an issuer ticker. Preserve explicit issuer mentions
        # outside the recognized financial line item.
        amendment = requested_amendment_scope(question)
        metrics: tuple[MetricRequirement, ...]
        if amendment is not None:
            issuer = amendment[0]
            matches = tuple(match for match in self.catalog.identify(issuer)
                            if normalize_entity(match.matched_alias) == normalize_entity(issuer))
            metrics = (_AMENDMENT_SCOPE,)
        else:
            matches = self.catalog.identify(mask_cost_of_revenue(business_disclosure_issuer_text(question)))
            metrics = _metrics(question)
        entities = tuple(
            EvidenceEntity(
                entity_id=match.entity_id,
                canonical_name=match.canonical_name,
                matched_alias=match.matched_alias,
            )
            for match in matches
        )
        interval_error = None
        interval = quarter_ytd = fiscal_year_pair = None
        instant_parts = ()
        try:
            interval = requested_reporting_interval(question)
            quarter_ytd = requested_quarter_ytd(question)
            fiscal_year_pair = requested_fiscal_year_pair(question)
            instant_parts = requested_filing_instants(question)
        except ValueError as error:
            interval_error = str(error)
        periods = () if interval or quarter_ytd or fiscal_year_pair or instant_parts or interval_error else _periods(
            mask_reported_as_of_dates(question),
        )
        cumulative = None if quarter_ytd is not None else _CUMULATIVE_RE.search(question)
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
            period = periods[0]
            prior_period = f"{period[:-4]}{int(period[-4:]) - 1}"
            periods = (prior_period, period)
        relative_period = bool(_RELATIVE_PERIOD_RE.search(question))

        percentage = percentage_operands(question, metrics)
        statement_date = requested_statement_date(question) if metrics and all(
            metric.metric_id in INSTANT_METRICS for metric in metrics
        ) else None
        operations: list[str] = []
        quantitative = any(metric.quantitative for metric in metrics)
        if _GROWTH_RE.search(question):
            operations.append("growth")
        if (len(entities) > 1 and not instant_parts) or _COMPARE_RE.search(question):
            operations.append("compare")
        for name, pattern in _OPERATION_RE.items():
            if pattern.search(question):
                operations.append(name)
        if not operations:
            operations.append("lookup")
        operations = list(dict.fromkeys(operations))
        if percentage is not None:
            operations = ["percentage"]

        unsupported_reasons: list[str] = []
        if not entities:
            unsupported_reasons.append("company_not_resolved")
        if not metrics:
            unsupported_reasons.append("metric_not_recognized")
        if any(metric in DISCLOSURE_METRICS for metric in metrics) and re.search(
            r"\bsources?\s*\?|\b(?:what|which)\s+(?:are|were)\s+the\s+sources?\s+of\b", question, re.I,
        ):
            unsupported_reasons.append("revenue_sources_require_separate_disclosure")
        if relative_period:
            unsupported_reasons.append("relative_period_not_supported")
        if cumulative_unresolved:
            unsupported_reasons.append("cumulative_period_scope_unresolved")
        if interval_error:
            unsupported_reasons.append(interval_error)
        if interval is not None and (
            len(entities) != 1 or len(metrics) != 1 or not quantitative or operations != ["lookup"]
        ):
            unsupported_reasons.append("explicit_reporting_interval_scope_unresolved")
        if quarter_ytd is not None and (
            len(entities) != 1 or len(metrics) != 1 or not quantitative or operations != ["lookup"] or interval is not None
        ):
            unsupported_reasons.append("quarter_ytd_lookup_scope_unresolved")
        if fiscal_year_pair is not None and (
            len(entities) != 1 or len(metrics) != 1 or not quantitative or operations != ["lookup"]
            or interval is not None or quarter_ytd is not None or requested_revision_policies(question)
            or requires_nonstandard_reporting_basis(question, metrics, consolidated_only=True)
        ):
            unsupported_reasons.append("fiscal_year_pair_scope_unresolved")
        instant_by_entity: dict[str, FilingInstant] = {}
        for prefix, instant in instant_parts:
            owners = self.catalog.identify(mask_cost_of_revenue(prefix))
            if len(owners) == 1:
                instant_by_entity[owners[0].entity_id] = instant
        if instant_parts and (
            len(instant_by_entity) != len(instant_parts) or set(instant_by_entity) != {entity.entity_id for entity in entities}
            or len(metrics) != 1 or metrics[0].metric_id not in INSTANT_METRICS or operations != ["lookup"]
            or interval is not None or quarter_ytd is not None or fiscal_year_pair is not None
            or requested_revision_policies(question)
            or requires_nonstandard_reporting_basis(question, metrics, consolidated_only=True)
        ):
            unsupported_reasons.append("as_of_filing_scope_unresolved")
        if percentage is not None and (len(entities) != 1 or len(periods) != 1):
            unsupported_reasons.append("percentage_requires_one_entity_and_period")
        if percentage is None and quantitative and operations == ["lookup"] and requests_percentage(question):
            unsupported_reasons.append("percentage_operands_unresolved")
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
                    if instant := instant_by_entity.get(entity.entity_id):
                        evidence.append(EvidenceRequirement(
                            requirement_id=f"{entity.entity_id}:{metric.metric_id}:{instant.end}",
                            entity_id=entity.entity_id, metric_id=metric.metric_id, filing_instant=instant,
                        ))
                    elif fiscal_year_pair is not None:
                        for end in fiscal_year_pair.ends:
                            evidence.append(EvidenceRequirement(
                                requirement_id=f"{entity.entity_id}:{metric.metric_id}:{end}",
                                entity_id=entity.entity_id, metric_id=metric.metric_id, period_end=end,
                            ))
                    elif quarter_ytd is not None:
                        for scope in (PeriodScope.QUARTER, PeriodScope.YEAR_TO_DATE):
                            evidence.append(EvidenceRequirement(
                                requirement_id=f"{entity.entity_id}:{metric.metric_id}:{scope.value}",
                                entity_id=entity.entity_id, metric_id=metric.metric_id, period_scope=scope,
                            ))
                    elif periods:
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
                metric_id=percentage[0] if operation == "percentage" else metrics[0].metric_id if len(metrics) == 1 else None,
                numerator_metric_id=percentage[0] if operation == "percentage" else None,
                denominator_metric_id=percentage[1] if operation == "percentage" else None,
                requires_period_alignment=(
                    quantitative and (operation == "compare" or operation in {"growth", "difference", "ratio", "average", "percentage"})
                ),
                requires_unit_compatibility=(
                    quantitative and operation in {"compare", "growth", "difference", "ratio", "average", "percentage"}
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
            reporting_interval=interval,
            quarter_ytd=quarter_ytd,
            fiscal_year_pair=fiscal_year_pair,
            statement_date=statement_date,
        )
