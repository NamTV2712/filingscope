"""Read annual revenue tables while retaining row groups and physical cells."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

from src.decision.models import MetricRequirement
from src.decision.statement_columns import StatementParse, StatementValue, _cell_amount, _statement_cells
from src.ingestion.period_identity import PeriodIdentity, PeriodKind


DISCLOSURE_METRICS = (
    MetricRequirement(metric_id="oil_sales", display_name="oil sales", aliases=("oil sales", "oil revenue")),
    MetricRequirement(metric_id="gas_sales", display_name="gas sales", aliases=("gas sales", "natural gas sales")),
    MetricRequirement(metric_id="ngl_sales", display_name="NGL sales", aliases=("ngl sales", "natural gas liquids sales")),
    MetricRequirement(metric_id="marketing_midstream_revenue", display_name="marketing and midstream revenue", aliases=(
        "marketing and midstream revenues", "marketing and midstream revenue", "midstream revenue", "midstream sales",
    )),
)
DISCLOSURE_METRIC_IDS = frozenset(item.metric_id for item in DISCLOSURE_METRICS) | {"contract_revenue"}
_COMMODITY_SPLIT = re.compile(r"\b(?:sales|revenues?)\s+(?:split|breakdown)\s+by\s+commodity\b", re.I)
_YEARS = re.compile(r"^\s*((?:(?:19|20)\d{2}\s+){1,3}(?:19|20)\d{2})\s*$")
_ROW = re.compile(r"^(?P<label>.+?\S)\s{2,}(?P<cells>(?:[$€£]?\s*[\d(−–—-]).*)$")
_TITLE = re.compile(r"\b(?:disaggregation|disaggregated|breakdown)\s+of\s+revenues?\b", re.I)
_CONTRACT_TOTAL = re.compile(r"^total revenues? from contracts? with customers?$", re.I)
_COMMODITY_TOTAL = re.compile(r"^oil,?\s+gas and (?:ngls?|natural gas liquids) sales$", re.I)
_MIDSTREAM_TOTAL = re.compile(r"^(?:marketing and midstream|midstream and marketing) revenues?$", re.I)
_GLOBAL_UNIT = re.compile(
    r"all monetary (?:values|amounts)[^.]{0,180}?stated in (thousands|millions|billions) of "
    r"(U\.?S\.? dollars|United States dollars|USD|Canadian dollars|CAD)", re.I,
)
_LOCAL_UNIT = re.compile(r"\b(?:in )?(thousands|millions|billions)\b", re.I)


@dataclass(frozen=True)
class MonetaryDeclaration:
    currency: str
    scale: str
    page: int


def monetary_declarations(text: str, page: int) -> tuple[MonetaryDeclaration, ...]:
    """Accept a document-wide declaration only when both amount scale and currency are explicit."""
    result = []
    for match in _GLOBAL_UNIT.finditer(" ".join(text.split())):
        currency = "CAD" if match[2].casefold() in {"canadian dollars", "cad"} else "USD"
        result.append(MonetaryDeclaration(currency, match[1].casefold(), page))
    return tuple(result)


def commodity_split_question(question: str) -> bool:
    return bool(_COMMODITY_SPLIT.search(question))


def filing_identity_matches(chunk: dict) -> bool:
    """Require the accession and CIK in the chunk to identify the same SEC source."""
    accession = chunk.get("accession_number") or chunk.get("accession")
    if not isinstance(accession, str) or re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) is None:
        return False
    try:
        cik = int(chunk.get("cik", ""))
        source = urlsplit(str(chunk.get("source_url", "")))
    except (ValueError, TypeError):
        return False
    prefix = f"/archives/edgar/data/{cik}/{accession.replace('-', '')}/"
    return source.scheme == "https" and source.hostname == "www.sec.gov" and source.path.casefold().startswith(prefix)


def disclosure_cell_matches(fact) -> bool:
    """Retain the label and subtotal identity that authorized a normalized cell."""
    if not fact.table_title or not _TITLE.search(fact.table_title) or not fact.row_label:
        return False
    if fact.metric_id == "contract_revenue":
        return bool(_CONTRACT_TOTAL.fullmatch(fact.row_label))
    if fact.metric_id == "marketing_midstream_revenue":
        return bool(_MIDSTREAM_TOTAL.fullmatch(fact.row_label))
    label_metrics = {"oil": "oil_sales", "gas": "gas_sales", "natural gas": "gas_sales", "ngl": "ngl_sales",
                     "ngls": "ngl_sales", "natural gas liquids": "ngl_sales"}
    return bool(fact.row_group and _COMMODITY_TOTAL.fullmatch(fact.row_group)
                and label_metrics.get(fact.row_label.casefold()) == fact.metric_id)


def _local_units(header: str, declaration: MonetaryDeclaration | None) -> tuple[str, str, int | None] | None:
    scales = {value.casefold() for value in _LOCAL_UNIT.findall(header)}
    currencies = {code for cue, code in ((r"\bUSD\b|U\.?S\.? dollars", "USD"),
                                        (r"\bCAD\b|Canadian dollars", "CAD"), (r"€|\bEUR\b", "EUR"),
                                        (r"£|\bGBP\b", "GBP")) if re.search(cue, header, re.I)}
    if len(scales) > 1 or len(currencies) > 1:
        return None
    if scales and currencies:
        return next(iter(currencies)), next(iter(scales)), None
    if declaration is None:
        return None
    if currencies and declaration.currency not in currencies or scales and declaration.scale not in scales:
        return None
    return declaration.currency, declaration.scale, declaration.page


def parse_revenue_table(
    text: str, *, form: str, fiscal_year: int, declaration: MonetaryDeclaration | None = None,
) -> StatementParse:
    """Parse a bounded annual disaggregation table, including rows repeated in different subtotals."""
    if form.upper() != "10-K":
        return StatementParse(False)
    lines = text.splitlines()
    title = next((index for index, line in enumerate(lines) if _TITLE.search(line)), None)
    if title is None:
        return StatementParse(False)
    header_index = next((index for index in range(title + 1, min(len(lines), title + 10))
                         if _YEARS.fullmatch(lines[index])), None)
    if header_index is None:
        return StatementParse(True)
    years = tuple(int(value) for value in re.findall(r"(?:19|20)\d{2}", lines[header_index]))
    if len(set(years)) != len(years) or max(years) != fiscal_year:
        return StatementParse(True)
    header = " ".join(lines[title:header_index + 1])
    units = _local_units(header, declaration)
    if units is None or re.search(r"years? ended", header, re.I) is None:
        return StatementParse(True)
    currency, scale, unit_page = units
    month_day = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})", header, re.I)
    month = None
    if month_day is not None:
        from datetime import datetime

        month = datetime.strptime(month_day[1], "%B").month
    rows = []
    for index in range(header_index + 1, min(len(lines), header_index + 50)):
        line = lines[index].rstrip()
        if not line.strip():
            continue
        match = _ROW.fullmatch(line.lstrip())
        if match is None:
            if rows:
                break
            continue
        cells = _statement_cells(match["cells"])
        if len(cells) != len(years):
            return StatementParse(True)
        if any(mark in match["cells"] and code != currency for mark, code in (("€", "EUR"), ("£", "GBP"))):
            return StatementParse(True)
        try:
            values = tuple(_cell_amount(cell) for cell in cells)
        except ValueError:
            return StatementParse(True)
        if any(value is None for value in values):
            return StatementParse(True)
        rows.append((index, match["label"].strip(), cells, values))
    groups: dict[int, str] = {}
    pending = []
    for index, label, cells, values in rows:
        if _COMMODITY_TOTAL.fullmatch(label) or _MIDSTREAM_TOTAL.fullmatch(label):
            if pending and all(sum(row[3][column] for row in pending) == values[column]
                               for column in range(len(years))):
                groups.update((row[0], label) for row in pending)
            pending = []
        elif not _CONTRACT_TOTAL.fullmatch(label):
            pending.append((index, label, cells, values))
    results = []
    for index, label, cells, values in rows:
        group = groups.get(index)
        metric = None
        if _CONTRACT_TOTAL.fullmatch(label):
            metric = "contract_revenue"
        elif _MIDSTREAM_TOTAL.fullmatch(label):
            metric = "marketing_midstream_revenue"
        elif group and _COMMODITY_TOTAL.fullmatch(group):
            metric = {"oil": "oil_sales", "gas": "gas_sales", "natural gas": "gas_sales", "ngl": "ngl_sales",
                      "ngls": "ngl_sales", "natural gas liquids": "ngl_sales"}.get(label.casefold())
        if metric is None:
            continue
        for column, (year, cell, value) in enumerate(zip(years, cells, values, strict=True)):
            try:
                end = date(year, month, int(month_day[2])) if month is not None else None
                period = PeriodIdentity.from_label(f"FY{year}", kind=PeriodKind.DURATION, end=end,
                                                   filing_fiscal_year=fiscal_year)
            except ValueError:
                return StatementParse(True)
            results.append(StatementValue(metric, period.label, value, currency, scale, lines[index],
                                          lines[header_index], period_identity=period, row_index=index,
                                          column_index=column, raw_cell=cell, table_title=lines[title].strip(),
                                          row_label=label, row_group=group, unit_source_page=unit_page))
    return StatementParse(True, tuple(results))
