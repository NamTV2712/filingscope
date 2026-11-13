"""Check structured model drafts against exact financial identity on the SEC pilot."""

from __future__ import annotations

import re
from datetime import date
from itertools import product

from configs.sec_runtime_pilot import PDFS, PilotCase, StatementCell
from src.decision.company_catalog import CompanyCatalog
from src.decision.requirement_extractor import requires_nonstandard_reporting_basis
from src.evaluation.answer_metrics import numeric_fact_signatures
from src.ingestion.company_facts import requested_revision_policies
from src.ingestion.period_identity import period_mentions

CATALOG = CompanyCatalog.from_document_rows(
    {"company": pdf.company, "ticker": pdf.name.split("_", 1)[0]} for pdf in PDFS
)
METRICS = {
    "revenue": r"\b(?:revenues?|(?:total )?net sales)\b",
    "operating income": r"\b(?:operating income|income from operations)\b",
    "net income": r"\b(?:net income|net earnings)\b",
    "total assets": r"\btotal assets\b",
}
_MONTHS = "January February March April May June July August September October November December".split()
_MONTH_NUMBERS = {alias.casefold(): n for n, month in enumerate(_MONTHS, 1) for alias in (month, month[:3])}
_MONTH = "|".join(sorted(_MONTH_NUMBERS, key=len, reverse=True))
_DATE = re.compile(
    rf"\b(?:(?P<month>{_MONTH})\.?\s+(?P<day>\d{{1,2}}),?\s+(?P<year>(?:19|20)\d{{2}})"
    r"|(?P<iso>(?:19|20)\d{2}-\d{2}-\d{2}))\b", re.I,
)
_DURATION = re.compile(r"\b(three|six|nine|twelve|3|6|9|12)\s+months?\s+ended\b", re.I)
_DURATION_MONTHS = {"three": 3, "six": 6, "nine": 9, "twelve": 12, "3": 3, "6": 6, "9": 9, "12": 12}
_FISCAL_YEAR_END = re.compile(r"\bfiscal\s+year\s+end(?:ed|ing)?\b", re.I)
_YTD = re.compile(r"\b(?:ytd|year[- ]to[- ]date)\b", re.I)
_QUARTER = re.compile(r"\bq([1-4])\b|\bq([1-4])\s*(?:fy|ytd)", re.I)
_ENERGY = re.compile(r"\benergy generation and storage\b", re.I)
_ENERGY_SUBSET = re.compile(r"\b(?:sales|leasing|excluding|only|products?|services)\b", re.I)
_UNVERIFIED_SCOPE = re.compile(
    r"\b(?:not|never|excluding|adjusted|estimated|forecast|projected|continuing operations|discontinued operations)\b", re.I,
)
_REVENUE_COMPONENT = re.compile(
    r"\b(?:iphone|ipad|mac|services|gaming|data center|automotive|membership|international|sam.s club)\b", re.I,
)


def _period_matches(text: str, cell: StatementCell) -> tuple[bool, str]:
    dates = []
    for match in _DATE.finditer(text):
        try:
            observed = date.fromisoformat(match["iso"]) if match["iso"] else date(
                int(match["year"]), _MONTH_NUMBERS[match["month"].casefold()], int(match["day"]),
            )
        except ValueError:
            return False, text
        dates.append(observed.isoformat())
    without_dates = _DATE.sub(" ", text)
    durations = {_DURATION_MONTHS[m.casefold()] for m in _DURATION.findall(without_dates)}
    body = _DURATION.sub(" ", without_dates)
    labels = {period.label for period in period_mentions(body)}
    quarter = cell.period.startswith("Q")
    cumulative = " YTD " in cell.period
    year = f"FY{cell.period[-4:]}"
    if dates and set(dates) != {cell.end}:
        return False, body
    if labels - {cell.period, year}:
        return False, body
    quarters = {left or right for left, right in _QUARTER.findall(body)}
    if quarters and (not quarter or quarters != {cell.period[1]}):
        return False, body
    if _YTD.search(body) and not cumulative:
        return False, body
    if durations and (cell.start is None or durations != {int(cell.period[1]) * 3 if cumulative else 3 if quarter else 12}):
        return False, body
    if quarter:
        scope = cell.period in labels or bool(dates and durations and cell.start is not None)
    else:
        scope = year in labels or bool(dates and (_FISCAL_YEAR_END.search(text) or durations == {12} or cell.start is None))
    return scope, body


def matches_cell(statement: str, cell: StatementCell) -> bool:
    ticker = cell.pdf.name.split("_", 1)[0]
    if {match.entity_id for match in CATALOG.identify(statement)} != {ticker}:
        return False
    metrics = {metric for metric, pattern in METRICS.items() if re.search(pattern, statement, re.I)}
    if metrics != {cell.metric} or _UNVERIFIED_SCOPE.search(statement) or requested_revision_policies(statement):
        return False
    if _ENERGY.search(cell.row):
        if not _ENERGY.search(statement) or _ENERGY_SUBSET.search(statement) or re.search(r"\bconsolidated\b", statement, re.I):
            return False
    elif requires_nonstandard_reporting_basis(statement) or (
        cell.metric == "revenue" and _REVENUE_COMPONENT.search(statement)
    ):
        return False
    if ticker == "WMT" and cell.metric == "revenue" and re.search(r"\bnet sales\b", statement, re.I):
        return False
    period_ok, text_without_dates = _period_matches(statement, cell)
    signatures = tuple(item[:4] for item in numeric_fact_signatures(text_without_dates))
    return period_ok and signatures == (("amount", "USD", str(cell.millions_usd * 1_000_000), "base"),)


def score_claims(case: PilotCase, claims: list[tuple[str, str | None]]) -> dict:
    """Count complete exactness and matching locators separately."""
    # This pilot has at most two expected cells. Extra claims fail completeness
    # while still allowing the matching claims to receive locator credit.
    matches = [[(i, locator == f"{cell.pdf.name}#p{cell.page}")
                for i, (statement, locator) in enumerate(claims) if matches_cell(statement, cell)]
               for cell in case.cells]
    best_matched = best_cited = 0
    if matches:
        for chosen in product(*[[(-1, False), *options] for options in matches]):
            indices = [i for i, _ in chosen if i >= 0]
            if len(indices) == len(set(indices)):
                best_matched, best_cited = max((best_matched, best_cited),
                                               (len(indices), sum(valid for _, valid in chosen)))
    exact = len(case.cells) == len(claims) == best_matched
    return {"exact": exact, "grounded_exact": exact and best_cited == best_matched,
            "matched_claims": best_matched, "matching_locators": best_cited}
