"""Read explicit annual statement columns from extracted filing pages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


_TITLE = re.compile(
    r"^(?:consolidated )?(?:statements? of (?:income|earnings|operations|financial position|cash flows)|"
    r"balance sheets?|income statements)$", re.I,
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_HEADER_WORD = re.compile(
    r"\b(?:for|the|fiscal|years?|ended|end|as|of|and|january|february|march|april|may|june|july|"
    r"august|september|october|november|december|\d{1,2})\b", re.I,
)
_SCALE = re.compile(r"\bin (thousands|millions|billions)\b", re.I)
_AMOUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_CELL = re.compile(rf"(?:[$€£]\s*)?(?:\(\s*(?:[$€£]\s*)?{_AMOUNT}\s*\)|-?{_AMOUNT}|[-–—])(?=\s|$)")
_CURRENCY_MARKS = {"$": "USD", "€": "EUR", "£": "GBP"}
_LABELS = {
    "total revenues": "revenue", "total revenue": "revenue", "total net sales": "revenue",
    "net sales": "revenue", "revenues": "revenue", "revenue": "revenue",
    "operating income": "operating_income", "operating profit": "operating_income",
    "income from operations": "operating_income", "net income": "net_income", "net earnings": "net_income",
    "total assets": "total_assets", "total liabilities": "total_liabilities",
    "cash and cash equivalents": "cash_and_equivalents",
    "net cash provided by operating activities": "operating_cash_flow",
    "net cash provided by (used in) operating activities": "operating_cash_flow",
}
_ROW = re.compile(rf"^({'|'.join(re.escape(label) for label in sorted(_LABELS, key=len, reverse=True))})\s+(.+)$", re.I)


@dataclass(frozen=True)
class StatementValue:
    metric_id: str
    period: str
    amount: Decimal
    currency: str
    scale: str
    row: str
    header: str

    @property
    def base_amount(self) -> Decimal:
        return self.amount.scaleb({"thousands": 3, "millions": 6, "billions": 9}[self.scale])


def _year_header(line: str, filing_year: str) -> tuple[str, ...]:
    years = tuple(_YEAR.findall(line))
    if len(years) not in {2, 3} or years[0] != filing_year:
        return ()
    if any(int(previous) - int(current) != 1 for previous, current in zip(years, years[1:])):
        return ()
    remaining = _HEADER_WORD.sub("", _YEAR.sub("", line)).strip(" ,.;:()-")
    return years if not remaining else ()


def _values(text: str) -> tuple[str, ...]:
    values = tuple(match.group() for match in _CELL.finditer(text))
    return values if not _CELL.sub("", text).strip() else ()


def extract_annual_statement_values(text: str, *, form: str, filing_year: str) -> tuple[StatementValue, ...]:
    """Pair unambiguous rows and headers from the same physical page."""
    if form.casefold().replace("-", "") != "10k" or _YEAR.fullmatch(filing_year) is None:
        return ()
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    title = next((index for index, line in enumerate(lines[:16]) if _TITLE.fullmatch(line)), None)
    if title is None:
        return ()
    for index, line in enumerate(lines[title + 1:title + 20], start=title + 1):
        years = _year_header(line, filing_year)
        if years:
            break
    else:
        return ()

    top = " ".join(lines[title + 1:index])
    scales = set(_SCALE.findall(top.casefold()))
    if len(scales) != 1:
        return ()
    scale = scales.pop()
    body = lines[index + 1:]
    currency_context = top + " " + " ".join(body[:10])
    currencies = {code for mark, code in _CURRENCY_MARKS.items() if mark in currency_context}
    if re.search(r"\b(?:CAD|AUD|NZD|HKD|SGD)\b", currency_context):
        return ()
    if len(currencies) != 1:
        return ()
    currency = currencies.pop()

    by_metric: dict[str, list[tuple[StatementValue, ...]]] = {}
    for row in body:
        match = _ROW.fullmatch(row)
        if match is None:
            continue
        metric, contents = _LABELS[match[1].casefold()], match[2]
        values = _values(contents)
        if len(values) != len(years) or any(mark in contents and code != currency for mark, code in _CURRENCY_MARKS.items()):
            continue
        parsed = []
        for year, value in zip(years, values, strict=True):
            cleaned = value.translate(str.maketrans("", "", "$€£ ,")).replace("(", "-").replace(")", "")
            if cleaned in {"-", "–", "—"}:
                continue
            parsed.append(StatementValue(metric, f"FY{year}", Decimal(cleaned), currency, scale, row, line))
        by_metric.setdefault(metric, []).append(tuple(parsed))
    # Duplicate labels may denote different sections, so preserve only unique rows.
    return tuple(value for rows in by_metric.values() if len(rows) == 1 for value in rows[0])
