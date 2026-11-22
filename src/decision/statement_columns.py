"""Read financial statement columns from one physical filing page."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import islice

from src.ingestion.company_facts import INSTANT_METRICS, MONETARY_CURRENCIES
from src.ingestion.period_identity import PeriodIdentity, PeriodKind, period_mentions


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
    period_identity: PeriodIdentity | None = None
    row_index: int | None = None
    column_index: int | None = None
    value_kind: str = "amount"
    raw_cell: str | None = None
    restated: bool = False
    table_title: str | None = None
    row_label: str | None = None
    row_group: str | None = None
    unit_source_page: int | None = None

    @property
    def base_amount(self) -> Decimal:
        exponent = {"units": 0, "thousands": 3, "millions": 6, "billions": 9}[self.scale]
        sign, digits, power = self.amount.as_tuple()
        return Decimal((sign, digits, power + exponent))


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


_FINANCIAL_TITLE = re.compile(
    r"(?:(?:condensed )?consolidated )?(?:statements? of (?:income|earnings|operations|"
    r"financial position|cash flows)|balance sheets?|income statements)\b", re.I,
)
_ISSUER_NAME = re.compile(r"\b(?:inc|incorporated|corporation|company|plc|limited|llc|ltd)\b", re.I)
_TABLE_SCALE = re.compile(r"\b(?:in )?(thousands|millions|billions)(?=\s*[,)]|\s+except|\s+of dollars\b|\s*$|\s+(?:19|20)\d{2})", re.I)
_MONTHS = "January February March April May June July August September October November December".split()
_MONTH_NUMBERS = {
    alias.casefold(): number
    for number, month in enumerate(_MONTHS, 1)
    for alias in (month, month[:3])
}
_MONTH_NAME = "|".join(sorted(_MONTH_NUMBERS, key=len, reverse=True))
_MONTH_DAY = rf"\b({_MONTH_NAME})\.?\s+([1-9]|[12]\d|3[01])(?!\d)"
_DATE = re.compile(rf"{_MONTH_DAY},?\s*((?:19|20)\d{{2}})\b", re.I)
_PARTIAL_DATE = re.compile(_MONTH_DAY, re.I)
_SHARE_COUNT_SCALE = re.compile(
    r"\b(?:except )?(?:the )?number of shares(?:,? which are (?:reflected|stated|presented) in| in)"
    r"\s+(?:thousands|millions|billions)\b", re.I,
)
_DURATION = re.compile(r"\b(three|six|nine|twelve)\s+months\s+ended\b", re.I)
_ANNUAL_HEADER = re.compile(r"\b(?:years?\s+ended|(?:52|53)\s+weeks\s+ended|fiscal\s+years?(?!\s+ended))\b", re.I)
_CHANGE = re.compile(r"\b(?:percent\s+|%\s*)?(?:year.over.year\s+)?change\s*$", re.I)
_REVISION = re.compile(r"\b(?:restated|revised)\b", re.I)
_GUARANTOR_SCOPE = re.compile(r"\b(?:deed of cross guarantee|guarantor (?:group|subsidiaries))\b", re.I)
_FOOTNOTE = r"(?:\([a-z]\)|\[[\da-z]+\])"
_CURRENCY_CODE = "|".join(sorted(MONETARY_CURRENCIES))
_DOLLAR_CURRENCIES = frozenset({"USD", "CAD", "AUD", "HKD", "NZD", "SGD", "MXN", "TWD"})
_CELL_VALUE = re.compile(
    rf"(?:{_CURRENCY_CODE}|[$€£])?\s*(?:\(\s*[$€£]?\s*{_AMOUNT}\s*\)|[−-]?{_AMOUNT}|[–—-])"
    rf"(?:\s*%)?(?:\s*{_FOOTNOTE})?(?=\s|$)", re.I,
)
_ALIGNED_LABELS = {
    **_LABELS, "total net revenue": "revenue", "total operating revenues": "revenue",
    "net revenues": "revenue", "operating revenues": "revenue",
    "operating income (loss)": "operating_income", "operating income/(loss)": "operating_income",
    "net income (loss)": "net_income", "net income/(loss)": "net_income",
    "operating margin": "operating_margin", "gross margin": "gross_margin",
    "diluted earnings per share": "earnings_per_share", "diluted eps": "earnings_per_share",
}
_ALIGNED_ROW = re.compile(
    rf"^({'|'.join(re.escape(label) for label in sorted(_ALIGNED_LABELS, key=len, reverse=True))})"
    rf"(?:\d{{1,2}}(?=\s+[$€£]))?\s*(?:{_FOOTNOTE}|\(Note\s+\d+\)|\(\d{{1,2}}\)(?=\s+[$€£]))?\s+(.+)$", re.I,
)
_VALUE_START = re.compile(rf"^(?:{_CURRENCY_CODE}\b|[$€£]|[−–—-]|\(\s*[$€£]?\s*\d|\d)", re.I)
_BALANCE_LABELS = {
    "accounts receivable, net": "current_net_accounts_receivable",
    "receivables, net": "current_net_accounts_receivable",
    "total current assets": "current_assets",
    "total noncurrent assets": "noncurrent_assets",
    "total non-current assets": "noncurrent_assets",
    "total current liabilities": "current_liabilities",
    "inventories": "net_inventory",
    "inventory": "net_inventory",
    "property, plant and equipment, net": "net_property_plant_equipment",
    "property and equipment, net": "net_property_plant_equipment",
    "total shareholders' equity": "stockholders_equity",
    "total stockholders' equity": "stockholders_equity",
}
_BALANCE_ROW = re.compile(
    rf"^({'|'.join(re.escape(label) for label in sorted(_BALANCE_LABELS, key=len, reverse=True))})\s+(.+)$", re.I,
)
_BALANCE_NOTE_AMOUNTS = rf"\$\s*{_AMOUNT} and \$\s*{_AMOUNT}(?:, respectively)?(?=\s)"
_RECEIVABLE_ALLOWANCES = re.compile(
    rf"^(?:trade accounts receivable, less allowances of|accounts receivable, net of allowance for doubtful accounts of) "
    rf"{_BALANCE_NOTE_AMOUNTS}", re.I,
)
_ACCUMULATED_DEPRECIATION = re.compile(
    rf"^(property, plant and equipment|property and equipment), net of accumulated depreciation of {_BALANCE_NOTE_AMOUNTS}",
    re.I,
)
_NONCONTROLLING_INTEREST = re.compile(r"\b(?:non[- ]?controlling|minority) interests?\b", re.I)
_QUARTER_MONTHS = {"three": 3, "six": 6, "nine": 9, "twelve": 12}


@dataclass(frozen=True)
class AmbiguousStatementRow:
    metric_id: str | None
    row_index: int
    reason: str


@dataclass(frozen=True)
class StatementParse:
    recognized: bool
    values: tuple[StatementValue, ...] = ()
    ambiguous_rows: tuple[AmbiguousStatementRow, ...] = ()


def _statement_kind(line: str) -> PeriodKind | None:
    match = _FINANCIAL_TITLE.search(line)
    if match is None:
        return None
    prefix = line[:match.start()].strip()
    suffix = re.sub(r"\((?:loss|unaudited)\)", "", line[match.end():], flags=re.I).strip(" :")
    if suffix.casefold() == "financial table of contents":
        suffix = ""
    if prefix and (len(prefix) > 65 or not _ISSUER_NAME.search(prefix)):
        return None
    if suffix and (len(suffix) > 65 or not _ISSUER_NAME.search(suffix)):
        return None
    title = match.group().casefold()
    return PeriodKind.INSTANT if "balance sheet" in title or "financial position" in title else PeriodKind.DURATION


def _statement_lines(text: str):
    for line in text.splitlines():
        if normalized := " ".join(line.replace("\ufffd", " ").split()):
            yield normalized


def _statement_heading(lines):
    return next(
        ((index, kind) for index, line in enumerate(islice(lines, 12)) if (kind := _statement_kind(line)) is not None),
        None,
    )


def statement_period_kind(text: str) -> PeriodKind | None:
    """Classify a physical page for lookup, without inspecting any cell."""
    lines = list(islice(_statement_lines(text), 12))
    heading = _statement_heading(lines)
    if heading is None or any(_GUARANTOR_SCOPE.search(line) for line in lines[:heading[0] + 1]):
        return None
    return heading[1]


def statement_report_date(metadata: Mapping[str, object]) -> date | None:
    """Read the report date from accession-bound filing metadata."""
    accession = metadata.get("accession_number") or metadata.get("accession")
    report_date = metadata.get("report_date")
    if (not isinstance(accession, str) or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession)
            or not isinstance(report_date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", report_date)):
        return None
    try:
        return date.fromisoformat(report_date)
    except ValueError:
        return None


def _parse_dates(header: list[str], years: list[int]) -> list[date | None]:
    joined = " ".join(header)
    matches = list(_DATE.finditer(joined))
    if len(matches) == len(years):
        pairs = [(match[1], match[2]) for match in matches]
    else:
        partial = list(_PARTIAL_DATE.finditer(joined))
        if len(partial) == len(years):
            pairs = [(match[1], match[2]) for match in partial]
        elif len(partial) == 1:
            pairs = [(partial[0][1], partial[0][2])] * len(years)
        elif partial and len(years) % len(partial) == 0:
            pairs = [(match[1], match[2]) for match in partial for _ in range(len(years) // len(partial))]
        else:
            return [None] * len(years)
    try:
        return [date(year, _MONTH_NUMBERS[month.casefold()], int(day))
                for year, (month, day) in zip(years, pairs, strict=True)]
    except ValueError:
        return [None] * len(years)


def _column_periods(
    header: list[str], *, kind: PeriodKind, fiscal_year: int, quarter: int | None,
    confirmed_period_end: date | None, infer_annual_starts: bool = False,
    exact_balance_sheet: bool = False,
) -> tuple[PeriodIdentity | None, ...]:
    current = header[-1]
    year_labels = period_mentions(current)
    years = [int(item.label[-4:]) for item in year_labels]
    if not years or len(years) > 8:
        return ()
    dates = _parse_dates(header, years)
    ascending_balance = bool(
        exact_balance_sheet and len(years) == 2 and dates[1] is not None
        and years[1] == years[0] + 1 and (confirmed_period_end is None or dates[1] == confirmed_period_end),
    )
    if confirmed_period_end and dates[0] and dates[0] != confirmed_period_end and not ascending_balance:
        return ()
    body = " ".join(header)
    months = [_QUARTER_MONTHS[match.casefold()] for match in _DURATION.findall(body)]
    if any(item.label.startswith(("Q", "CY")) or current[item.start:item.end].upper().startswith("FY")
           for item in year_labels):
        # Explicit labels must occupy every value column.
        if any(current[item.start:item.end].isdigit() for item in year_labels):
            return ()
        try:
            return tuple(PeriodIdentity.from_label(item.label, kind=kind, end=end, filing_fiscal_year=fiscal_year)
                         for item, end in zip(year_labels, dates, strict=True))
        except ValueError:
            return ()
    if quarter is None:
        if (not ascending_balance and any(left <= right for left, right in zip(years, years[1:]))) or months and months != [12]:
            return ()
        anniversary_dates = all(
            left is not None and right is not None and 350 <= (left - right).days <= 380
            for left, right in zip(dates, dates[1:])
        )
        if kind == PeriodKind.DURATION and not (
            _ANNUAL_HEADER.search(body) or months == [12] or len(dates) > 1 and anniversary_dates
        ):
            return ()
        current_column = -1 if ascending_balance else 0
        current_end, current_year = dates[current_column], years[current_column]
        if (current_year != fiscal_year or current_end and current_end.month <= 2) and (
            confirmed_period_end is None or current_end != confirmed_period_end
        ):
            return ()
        if abs(current_year - fiscal_year) > 1:
            return ()
        starts = [None] * len(dates)
        if (infer_annual_starts and kind == PeriodKind.DURATION and confirmed_period_end is not None
                and dates[0] == confirmed_period_end and anniversary_dates and not _REVISION.search(body)
                and (_ANNUAL_HEADER.search(body) or months == [12])):
            for index, preceding_end in enumerate(dates[1:]):
                if preceding_end is not None:
                    starts[index] = preceding_end + timedelta(days=1)
        return tuple(PeriodIdentity.from_label(
            f"FY{fiscal_year + year - current_year}", kind=kind, start=start, end=end, filing_fiscal_year=fiscal_year,
        ) for year, start, end in zip(years, starts, dates, strict=True))
    if abs(years[0] - fiscal_year) > 1:
        return ()
    if kind == PeriodKind.INSTANT:
        # Date-based balance-sheet columns can include a prior year-end and
        # a same-quarter comparative. Require date ownership for both.
        if not dates[0] or any(end is None for end in dates[1:]):
            return ()
        periods = []
        for end in dates:
            elapsed = (dates[0] - end).days
            if elapsed == 0:
                label = f"Q{quarter} FY{fiscal_year}"
            elif 350 <= elapsed <= 380:
                label = f"Q{quarter} FY{fiscal_year - 1}"
            else:
                label = None
            periods.append(PeriodIdentity.from_label(
                label, kind=kind, end=end, filing_fiscal_year=fiscal_year,
            ) if label else None)
        return tuple(periods)
    groups = [0, *(index for index in range(1, len(years)) if years[index] >= years[index - 1]), len(years)]
    if len(months) != len(groups) - 1 or any(month not in {3, quarter * 3} for month in months):
        return ()
    periods = []
    for month, start, stop in zip(months, groups, groups[1:]):
        if years[start:stop] != years[:groups[1]]:
            return ()
        for index in range(start, stop):
            year = fiscal_year + years[index] - years[0]
            label = f"Q{quarter} {'YTD ' if month != 3 else ''}FY{year}"
            periods.append(PeriodIdentity.from_label(
                label, kind=kind, end=dates[index], filing_fiscal_year=fiscal_year,
            ))
    return tuple(periods)


def _statement_cells(text: str) -> tuple[str, ...]:
    # Match placeholders as cells. A silently shifted row has the wrong
    # number of values and is handled as ambiguous by the caller.
    values = tuple(match.group().strip() for match in _CELL_VALUE.finditer(text))
    return values if not _CELL_VALUE.sub("", text).strip() else ()


def _period_header(line: str) -> bool:
    mentions = period_mentions(line)
    if not mentions or len(mentions) == 1 and line[mentions[0].start:mentions[0].end].isdigit():
        return False
    remaining = line
    for mention in reversed(mentions):
        remaining = remaining[:mention.start] + remaining[mention.end:]
    remaining = re.sub(r"\([^)]*(?:millions|thousands|billions)[^)]*\)", "", remaining, flags=re.I)
    remaining = re.sub(r"\b(?:in )?(?:millions|thousands|billions)\b.*?\b(?:amounts|data)\b", "", remaining, flags=re.I)
    remaining = _PARTIAL_DATE.sub("", remaining)
    remaining = _CHANGE.sub("", _REVISION.sub("", _DURATION.sub("", _ANNUAL_HEADER.sub("", remaining))))
    remaining = _HEADER_WORD.sub("", re.sub(r"\b(?:at|dollars|amounts|in|USD|EUR|GBP)\b", "", remaining, flags=re.I))
    return not remaining.strip(" ,.;:()$€£%-")


def _cell_amount(cell: str) -> Decimal | None:
    value = re.sub(_FOOTNOTE, "", cell, flags=re.I)
    value = re.sub(rf"\b(?:{_CURRENCY_CODE})\b", "", value, flags=re.I)
    value = value.translate(str.maketrans("−", "-", "$€£ ,%")).replace("(", "-").replace(")", "")
    if value in {"-", "–", "—"}:
        return None
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        raise ValueError("invalid financial cell")
    return Decimal(value)


def _subtotal(body: list[str], columns: int) -> tuple[int, str] | None:
    """Recognize a consolidated revenue subtotal by its row boundaries and sum."""
    revenue = next((index for index, row in enumerate(body) if re.fullmatch(r"revenues?:?", row, re.I)), None)
    if revenue is None:
        return None
    expense = next((index for index in range(revenue + 3, len(body))
                    if re.fullmatch(r"(?:operating )?(?:costs and )?expenses:?", body[index], re.I)), None)
    if expense is None:
        return None
    lines = body[revenue + 1:expense]
    cells = [
        _statement_cells(re.split(r"\s(?=[$€£(]?\s*[-−]?\d)", row, maxsplit=1)[-1])
        for row in lines[:-1]
    ]
    cells.append(_statement_cells(lines[-1]))
    if any(len(row) != columns for row in cells):
        return None
    try:
        amounts = [[_cell_amount(cell) for cell in row] for row in cells]
    except ValueError:
        return None
    if any(amount is None for row in amounts for amount in row):
        return None
    if any(sum(column[:-1]) != column[-1] for column in zip(*amounts, strict=True)):
        return None
    return expense - 1, lines[-1]


def _balance_rows(body: list[str]) -> list[tuple[int, str, str]]:
    current_assets = False
    current_assets_complete = False
    assets_complete = False
    has_noncontrolling = any(_NONCONTROLLING_INTEREST.search(row) for row in body)
    rows = []
    for index, row in enumerate(body):
        if _statement_kind(row) is not None:
            break
        if re.fullmatch(r"current assets:?", row, re.I) and not assets_complete:
            current_assets = True
        elif re.match(r"^total current assets\s", row, re.I):
            current_assets = False
            current_assets_complete = True
        elif re.match(r"^total assets\s", row, re.I):
            current_assets = False
            assets_complete = True
        label_text = re.sub(r"^(.+?) [–—] net ", r"\1, net ", row, flags=re.I).replace("’", "'")
        label_text = _RECEIVABLE_ALLOWANCES.sub("Accounts receivable, net", label_text)
        label_text = _ACCUMULATED_DEPRECIATION.sub(r"\1, net", label_text)
        match = _BALANCE_ROW.fullmatch(label_text)
        if match is None or not _VALUE_START.search(match[2]):
            continue
        metric = _BALANCE_LABELS[match[1].casefold()]
        if metric in {"current_net_accounts_receivable", "net_inventory"} and not current_assets:
            continue
        if metric in {"current_assets", "noncurrent_assets", "net_property_plant_equipment"} and assets_complete:
            continue
        if metric in {"noncurrent_assets", "net_property_plant_equipment"} and not current_assets_complete:
            continue
        if metric == "current_liabilities" and not assets_complete:
            continue
        if metric == "stockholders_equity" and (not assets_complete or has_noncontrolling):
            continue
        rows.append((index, metric, match[2]))
    return rows


def parse_statement_columns(
    text: str, *, form: str, fiscal_year: int, quarter: int | None = None,
    confirmed_period_end: date | None = None,
    infer_annual_starts: bool = False,
    exact_balance_sheet: bool = False,
    scoped_balance_sheet: bool = False,
) -> StatementParse:
    """Return sourced values and report rows whose column ownership is uncertain."""
    amended = form.upper().endswith("/A")
    form = form.upper().replace("-", "").removesuffix("/A")
    if form not in {"10K", "10Q", "20F", "40F"} or (form == "10Q") != (quarter is not None):
        return StatementParse(False)
    lines = list(_statement_lines(text))
    physical_rows: list[int] = []
    if scoped_balance_sheet:
        # Overprinted PDF text can duplicate each line without adding another cell.
        lines = []
        for page_row, raw in enumerate(text.splitlines()):
            normalized = " ".join(raw.replace("\ufffd", " ").split())
            if normalized and (not lines or lines[-1] != normalized):
                lines.append(normalized)
                physical_rows.append(page_row)
    heading = _statement_heading(lines)
    if heading is None:
        return StatementParse(False)
    title, kind = heading
    if scoped_balance_sheet and (kind != PeriodKind.INSTANT or "consolidated" not in lines[title].casefold()):
        return StatementParse(False)
    exact_balance_sheet = exact_balance_sheet and form == "10K" and kind == PeriodKind.INSTANT and not amended
    if any(_GUARANTOR_SCOPE.search(line) for line in lines[:title + 1]):
        return StatementParse(True, ambiguous_rows=(AmbiguousStatementRow(None, title, "nonregistrant_scope"),))
    header_index = None
    body_start = None
    for index in range(title + 1, min(len(lines), title + 12)):
        line = lines[index]
        if _period_header(line):
            header_index, body_start = index, index + 1
        elif header_index is not None:
            if _TABLE_SCALE.search(line) or re.fullmatch(r"\(unaudited\)", line, re.I):
                body_start = index + 1
            else:
                break
    if header_index is None:
        return StatementParse(True, ambiguous_rows=(AmbiguousStatementRow(None, title, "period_header_missing"),))
    header = lines[title + 1:header_index + 1]
    periods = _column_periods(
        header, kind=kind, fiscal_year=fiscal_year, quarter=quarter,
        confirmed_period_end=confirmed_period_end,
        infer_annual_starts=infer_annual_starts,
        exact_balance_sheet=exact_balance_sheet,
    )
    heading_lines = lines[title + 1:body_start]
    top = " ".join(heading_lines)
    scales = {item.casefold() for line in heading_lines
              for item in _TABLE_SCALE.findall(_SHARE_COUNT_SCALE.sub("", line))}
    body = lines[body_start:]
    if scoped_balance_sheet:
        final_row = next((index for index, line in enumerate(body)
                          if re.match(r"total liabilities and (?:stockholders['’]? |shareholders['’]? )?equity\b", line, re.I)), None)
        if final_row is None:
            return StatementParse(True, ambiguous_rows=(AmbiguousStatementRow(None, title, "statement_total_missing"),))
        body = body[:final_row + 1]
    context = " ".join((top, *body[:18]))
    codes = set(re.findall(rf"\b(?:{_CURRENCY_CODE})\b", context))
    marks = {code for mark, code in _CURRENCY_MARKS.items() if mark in context}
    # An explicit ISO code on a dollar-denominated report disambiguates "$".
    currencies = codes | (marks - {"USD"} if codes and codes.issubset(_DOLLAR_CURRENCIES) else marks)
    if not periods or len(scales) != 1 or len(currencies) != 1:
        return StatementParse(True, ambiguous_rows=(AmbiguousStatementRow(None, header_index, "period_or_unit_unresolved"),))
    scale, currency = next(iter(scales)), next(iter(currencies))
    if re.search(r"(?<!\w)[A-Z]{1,2}\$", context) and not codes:
        return StatementParse(True, ambiguous_rows=(AmbiguousStatementRow(None, header_index, "currency_unresolved"),))
    change = bool(_CHANGE.search(header[-1]))
    restated = bool(_REVISION.search(top)) or amended
    candidates: list[tuple[int, str, str]] = []
    for row_index, row in enumerate(body):
        if _statement_kind(row) is not None:
            break
        if match := _ALIGNED_ROW.fullmatch(row):
            if _VALUE_START.search(match[2]):
                candidates.append((row_index, match[1].casefold(), match[2]))
    if exact_balance_sheet:
        candidates.extend(_balance_rows(body))
    if kind == PeriodKind.DURATION and not any(_ALIGNED_LABELS[label] == "revenue" for _, label, _ in candidates):
        if subtotal := _subtotal(body, len(periods)):
            candidates.append((subtotal[0], "total revenue", subtotal[1]))
    results = []
    ambiguous = []
    by_metric: dict[str, list[tuple[int, str, str]]] = {}
    for candidate in candidates:
        label = candidate[1]
        by_metric.setdefault(_ALIGNED_LABELS.get(label, label), []).append(candidate)
    for metric, rows in by_metric.items():
        totals = [item for item in rows if item[1].startswith("total ")]
        rows = totals or rows
        for row_index, label, raw in rows:
            source_row = body_start + row_index
            cells = _statement_cells(raw)
            if len(rows) != 1 or len(cells) != len(periods) + int(change):
                ambiguous.append(AmbiguousStatementRow(metric, source_row, "row_or_column_ownership_ambiguous"))
                continue
            try:
                amounts = [_cell_amount(cell) for cell in cells[:len(periods)]]
            except ValueError:
                ambiguous.append(AmbiguousStatementRow(metric, source_row, "invalid_financial_cell"))
                continue
            for column, (period, amount, cell) in enumerate(zip(periods, amounts, cells)):
                if period is None or amount is None:
                    continue
                expected_kind = PeriodKind.INSTANT if metric in INSTANT_METRICS else PeriodKind.DURATION
                if kind != expected_kind:
                    continue
                percent = "%" in cell
                margin = metric.endswith("_margin")
                if percent != margin:
                    ambiguous.append(AmbiguousStatementRow(metric, source_row, "cell_unit_mismatch"))
                    continue
                explicit_codes = set(re.findall(rf"\b(?:{_CURRENCY_CODE})\b", cell, flags=re.I))
                mismatched_mark = any(
                    mark in cell and (currency not in _DOLLAR_CURRENCIES if mark == "$" else currency != code)
                    for mark, code in _CURRENCY_MARKS.items()
                )
                if mismatched_mark or explicit_codes and {code.upper() for code in explicit_codes} != {currency}:
                    ambiguous.append(AmbiguousStatementRow(metric, source_row, "cell_currency_mismatch"))
                    continue
                value_kind = "percent" if percent else "currency_per_share" if metric == "earnings_per_share" else "amount"
                results.append(StatementValue(
                    metric, period.label, amount, "%" if percent else currency, scale if value_kind == "amount" else "units",
                    body[row_index], top, period, physical_rows[source_row] if scoped_balance_sheet else source_row,
                    column, value_kind, cell, restated,
                    table_title=lines[title] if scoped_balance_sheet else None,
                    row_label=label if scoped_balance_sheet else None,
                ))
    return StatementParse(True, tuple(results), tuple(ambiguous))
