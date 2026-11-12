"""Deterministic selection of entity-wide facts from SEC Company Facts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from src.ingestion.period_identity import PeriodIdentity, PeriodKind


COMPANY_FACTS_POLICY_VERSION = "sec-company-facts-v2"
MONETARY_CURRENCIES = frozenset(
    "AUD BRL CAD CHF CNY DKK EUR GBP HKD ILS INR JPY KRW MXN NOK NZD SEK SGD TWD USD ZAR".split()
)
_ANNUAL_FORMS = frozenset({"10-K", "20-F", "40-F"})
_PERIODIC_FORMS = _ANNUAL_FORMS | {"10-Q"}
_ACCESSION = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")
_PERIOD = re.compile(r"(?:(Q[1-4]) (YTD )?)?FY((?:19|20)[0-9]{2})")

# Entries are ordered only to pick a label when the original rows agree.
# A newer tag never supersedes a different tag for the same period.
METRIC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:Revenues",
        "us-gaap:SalesRevenueNet",
        "ifrs-full:Revenue",
    ),
    "net_income": ("us-gaap:NetIncomeLoss", "ifrs-full:ProfitLoss"),
    "operating_income": ("us-gaap:OperatingIncomeLoss", "ifrs-full:ProfitLossFromOperatingActivities"),
    "gross_profit": ("us-gaap:GrossProfit", "ifrs-full:GrossProfit"),
    "total_assets": ("us-gaap:Assets", "ifrs-full:Assets"),
    "total_liabilities": ("us-gaap:Liabilities", "ifrs-full:Liabilities"),
    "cash_and_equivalents": (
        "us-gaap:CashAndCashEquivalentsAtCarryingValue", "ifrs-full:CashAndCashEquivalents",
    ),
    "operating_cash_flow": (
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
        "ifrs-full:CashFlowsFromUsedInOperatingActivities",
    ),
    "capital_expenditures": (
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        "ifrs-full:PurchaseOfPropertyPlantAndEquipment",
    ),
}
_INSTANT_METRICS = frozenset({"total_assets", "total_liabilities", "cash_and_equivalents"})


class RevisionPolicy(StrEnum):
    AS_REPORTED = "AS_REPORTED"
    LATEST = "LATEST"


class RevisionKind(StrEnum):
    ORIGINAL = "ORIGINAL"
    REFILED = "REFILED"
    AMENDMENT = "AMENDMENT"
    COMPARATIVE_REVISION = "COMPARATIVE_REVISION"


def requested_revision_policies(question: str) -> frozenset[RevisionPolicy]:
    policies = set()
    if re.search(r"\b(?:as[- ]reported|originally reported|original filing)\b", question, re.I):
        policies.add(RevisionPolicy.AS_REPORTED)
    if re.search(r"\b(?:restated|revised|latest revision)\b", question, re.I):
        policies.add(RevisionPolicy.LATEST)
    return frozenset(policies)


class FactRevision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    accession: str
    filing_date: str
    form: str
    raw_value: str


class XbrlProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    policy_version: str = COMPANY_FACTS_POLICY_VERSION
    taxonomy: str
    tag: str
    label: str
    period_start: str | None
    period_end: str
    period_alignment: str
    raw_unit: str
    accession: str
    filing_fiscal_year: int
    filing_fiscal_period: str
    company_facts_url: str
    revision_policy: RevisionPolicy
    revision_kind: RevisionKind
    original_accession: str
    history: tuple[FactRevision, ...]


@dataclass(frozen=True)
class ResolvedCompanyFact:
    value: Decimal
    raw_value: str
    currency: str
    fiscal_period: str
    filing_date: str
    form: str
    filing_url: str
    provenance: XbrlProvenance

    @property
    def period_identity(self) -> PeriodIdentity:
        provenance = self.provenance
        start = date.fromisoformat(provenance.period_start) if provenance.period_start else None
        return PeriodIdentity.from_label(
            self.fiscal_period,
            kind=PeriodKind.DURATION if start is not None else PeriodKind.INSTANT,
            start=start,
            end=date.fromisoformat(provenance.period_end),
            filing_fiscal_year=provenance.filing_fiscal_year,
            filing_fiscal_period=provenance.filing_fiscal_period,
        )


@dataclass(frozen=True)
class CompanyFactResolution:
    reason: str
    fact: ResolvedCompanyFact | None = None


@dataclass(frozen=True)
class _Observation:
    concept: str
    label: str
    raw_unit: str
    currency: str
    raw_value: str
    value: Decimal
    start: date | None
    end: date
    filed: date
    accession: str
    form: str
    fiscal_year: int
    fiscal_focus: str

    @property
    def interval(self) -> tuple[date | None, date]:
        return self.start, self.end


def normalize_cik(value: object) -> str:
    raw = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,10}", raw) or int(raw) == 0:
        raise ValueError("invalid CIK")
    return raw.zfill(10)


def normalize_currency(unit: str) -> str | None:
    currency = unit.strip().upper().removeprefix("ISO4217:")
    return currency if currency in MONETARY_CURRENCIES else None


def requested_currencies(question: str) -> frozenset[str]:
    return frozenset(re.findall(r"\b[A-Z]{3}\b", question)) & MONETARY_CURRENCIES


def _date(value: Any) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("invalid SEC date")
    return date.fromisoformat(value)


def _parse_row(concept: str, label: str, unit: str, row: Mapping[str, Any]) -> _Observation | None:
    currency = normalize_currency(unit)
    if currency is None:
        return None
    try:
        start = None if row.get("start") is None else _date(row["start"])
        end = _date(row["end"])
        filed = _date(row["filed"])
        raw_value = str(row["val"])
        value = Decimal(raw_value)
        accession = str(row["accn"])
        form = str(row["form"]).upper()
        year_text = str(row["fy"])
        if not re.fullmatch(r"(?:19|20)[0-9]{2}", year_text):
            return None
        fiscal_year = int(year_text)
        fiscal_focus = str(row["fp"]).upper()
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
        return None
    if (
        not value.is_finite() or abs(value.adjusted()) > 32 or len(value.as_tuple().digits) > 34
        or not _ACCESSION.fullmatch(accession)
        or form.removesuffix("/A") not in _PERIODIC_FORMS
        or fiscal_focus not in {"FY", "Q1", "Q2", "Q3", "Q4"}
        or not 1900 <= fiscal_year <= 2099
        or filed < end or (start is not None and start > end)
    ):
        return None
    return _Observation(
        concept, label, unit, currency, raw_value, value, start, end, filed,
        accession, form, fiscal_year, fiscal_focus,
    )


def _revision_order(row: _Observation) -> tuple:
    return (
        row.filed, row.accession, row.raw_unit, row.raw_value,
        row.form, row.fiscal_year, row.fiscal_focus, row.start or row.end, row.end,
    )


class CompanyFactsResolver:
    """Resolve one explicit fiscal slot, with a distinct filing revision policy."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        expected_cik: int | str,
        report_dates: Mapping[str, str] | None = None,
    ):
        self.cik = normalize_cik(expected_cik)
        if normalize_cik(payload.get("cik")) != self.cik:
            raise ValueError("Company Facts CIK mismatch")
        self.company = str(payload.get("entityName") or "").strip()
        self.facts = payload.get("facts")
        if not self.company or not isinstance(self.facts, Mapping):
            raise ValueError("invalid Company Facts payload")
        self.report_dates = report_dates or {}
        self._cache: dict[str, tuple[_Observation, ...]] = {}

    def _observations(self, concept: str) -> tuple[_Observation, ...]:
        if concept in self._cache:
            return self._cache[concept]
        namespace, tag = concept.split(":")
        taxonomy = self.facts.get(namespace)
        node = taxonomy.get(tag) if isinstance(taxonomy, Mapping) else None
        units = node.get("units") if isinstance(node, Mapping) else None
        rows: set[_Observation] = set()
        if isinstance(units, Mapping):
            label = str(node.get("label") or tag)
            for unit, values in units.items():
                if not isinstance(unit, str) or not isinstance(values, list):
                    continue
                for item in values:
                    if isinstance(item, Mapping):
                        row = _parse_row(concept, label, unit, item)
                        if row is not None:
                            rows.add(row)
        self._cache[concept] = tuple(sorted(rows, key=_revision_order))
        return self._cache[concept]

    def _original_period(
        self, row: _Observation, year: int, quarter: str | None, instant: bool, *, year_to_date: bool = False,
    ) -> bool:
        annual_filing = quarter is None or quarter == "Q4"
        forms = _ANNUAL_FORMS if annual_filing else {"10-Q"}
        focus = {"FY", "Q4"} if quarter == "Q4" else {quarter or "FY"}
        if row.form not in forms or row.fiscal_year != year or row.fiscal_focus not in focus:
            return False
        if instant != (row.start is None):
            return False
        if row.start is not None:
            days = (row.end - row.start).days + 1
            if year_to_date:
                minimum, maximum = {"Q1": (70, 110), "Q2": (155, 210), "Q3": (240, 300), "Q4": (330, 400)}[quarter]
            else:
                minimum, maximum = (330, 400) if quarter is None else (70, 110)
            if not minimum <= days <= maximum:
                return False
        report_end = self.report_dates.get(row.accession)
        if report_end is not None:
            return row.end.isoformat() == report_end
        if quarter == "Q4":
            return any(
                annual.accession == row.accession and annual.end == row.end
                and self._original_period(annual, year, None, instant)
                for annual in self._observations(row.concept)
            )
        # FY/FP describe the filing. Its prior-year comparative rows have the
        # same FY/FP, so require the observation to end near the filing date.
        if not 0 <= (row.filed - row.end).days <= (180 if annual_filing else 75):
            return False
        return (
            row.end.year == year
            or (row.end.year == year + 1 and row.end.month <= 2)
            or (not annual_filing and row.end.year == year - 1)
        )

    def resolve(
        self,
        metric_id: str,
        period: str | None,
        *,
        currency: str | None = None,
        revision: RevisionPolicy = RevisionPolicy.AS_REPORTED,
        form_types: tuple[str, ...] = (),
    ) -> CompanyFactResolution:
        concepts = METRIC_CONCEPTS.get(metric_id)
        if concepts is None:
            return CompanyFactResolution("unsupported_concept")
        match = _PERIOD.fullmatch(period or "")
        if match is None:
            return CompanyFactResolution("explicit_fiscal_period_required")
        quarter, cumulative, year_text = match.groups()
        instant = metric_id in _INSTANT_METRICS
        if cumulative and instant:
            return CompanyFactResolution("cumulative_scope_inapplicable_to_instant")
        requested_currency = normalize_currency(currency) if currency else None
        if currency and requested_currency is None:
            return CompanyFactResolution("unsupported_currency")
        requested_forms = {item.upper().replace("-", "") for item in form_types}
        rows = tuple(row for concept in concepts for row in self._observations(concept))
        originals = [
            row for row in rows
            if self._original_period(row, int(year_text), quarter, instant, year_to_date=bool(cumulative))
            and (requested_currency is None or row.currency == requested_currency)
            and (not requested_forms or row.form.replace("-", "") in requested_forms)
        ]
        if not originals:
            return CompanyFactResolution("original_period_unavailable")
        if len({row.interval for row in originals}) != 1:
            return CompanyFactResolution("ambiguous_period")
        if len({row.currency for row in originals}) != 1:
            return CompanyFactResolution("ambiguous_currency")
        if len({row.concept.split(":")[0] for row in originals}) != 1:
            return CompanyFactResolution("ambiguous_taxonomy")

        first_date = min(row.filed for row in originals)
        first_rows = [row for row in originals if row.filed == first_date]
        if len({row.value for row in first_rows}) != 1:
            return CompanyFactResolution("conflicting_original_values")
        if len({row.accession for row in first_rows}) != 1:
            return CompanyFactResolution("ambiguous_original_accession")
        original = min(first_rows, key=lambda row: (concepts.index(row.concept), _revision_order(row)))
        history = sorted({
            row for row in rows
            if row.interval == original.interval and row.currency == original.currency
            and row.concept == original.concept and row.filed >= original.filed
            and (not requested_forms or row.form.removesuffix("/A").replace("-", "") in requested_forms)
        }, key=_revision_order)
        selected = original
        if revision == RevisionPolicy.LATEST:
            last_rows = [row for row in history if row.filed == history[-1].filed]
            if len({row.value for row in last_rows}) != 1:
                return CompanyFactResolution("conflicting_latest_values")
            # Equivalent rows on the same filing day do not prove a revision.
            if last_rows[-1].filed > original.filed:
                if len({row.accession for row in last_rows}) != 1:
                    return CompanyFactResolution("ambiguous_latest_accession")
                selected = last_rows[-1]

        kind = RevisionKind.ORIGINAL
        if selected != original:
            if selected.value == original.value:
                kind = RevisionKind.REFILED
            elif selected.form.endswith("/A"):
                kind = RevisionKind.AMENDMENT
            else:
                kind = RevisionKind.COMPARATIVE_REVISION
        taxonomy, tag = selected.concept.split(":")
        accession_path = selected.accession.replace("-", "")
        return CompanyFactResolution("resolved", ResolvedCompanyFact(
            value=selected.value,
            raw_value=selected.raw_value,
            currency=selected.currency,
            fiscal_period=period,
            filing_date=selected.filed.isoformat(),
            form=selected.form,
            filing_url=(
                f"https://www.sec.gov/Archives/edgar/data/{int(self.cik)}/"
                f"{accession_path}/{selected.accession}-index.html"
            ),
            provenance=XbrlProvenance(
                taxonomy=taxonomy, tag=tag, label=selected.label,
                period_start=selected.start.isoformat() if selected.start else None,
                period_end=selected.end.isoformat(),
                period_alignment=(
                    "filing_report_date" if original.accession in self.report_dates else "filing_focus_and_dates"
                ),
                raw_unit=selected.raw_unit,
                accession=selected.accession,
                filing_fiscal_year=selected.fiscal_year,
                filing_fiscal_period=selected.fiscal_focus,
                company_facts_url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{self.cik}.json",
                revision_policy=revision,
                revision_kind=kind,
                original_accession=original.accession,
                history=tuple(FactRevision(
                    accession=row.accession, filing_date=row.filed.isoformat(), form=row.form,
                    raw_value=row.raw_value,
                ) for row in history),
            ),
        ))
