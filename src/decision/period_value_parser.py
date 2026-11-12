"""Conservative metric/period/value parsing adapted from source contracts.

The table-header and nearby-row scan follows the tested parser in
``Enterprise_Document_QA/src/generation/period_value_completeness.py`` at
``2ac043347f57e257dac4e2947a57dfced8709d97``. P2 uses the parser to return
source facts; P4 also uses its answer-side numeric occurrence helper. Claim
support and citation decisions live in ``src/verification``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from src.ingestion.company_facts import MONETARY_CURRENCIES
from src.ingestion.period_identity import PeriodMention, period_mentions


_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_CURRENCY_TOKEN = "|".join((*sorted(MONETARY_CURRENCIES), r"\$", "€", "£"))
_VALUE_RE = re.compile(
    rf"(?<![\w.])(?P<currency>{_CURRENCY_TOKEN})?\s*"
    r"(?P<number>\(?-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?)"
    r"\s*(?P<percent>%|percent\b)?\s*"
    r"(?P<scale>(?:billion|million|thousand|bn|mm|m)\b)?",
    re.I,
)
_STRICT_NUMBER_RE = re.compile(
    rf"^(?P<currency>{_CURRENCY_TOKEN})?\s*"
    r"(?P<number>\(?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?|\(?-?\d+(?:\.\d+)?\)?)"
    r"\s*(?P<percent>%|percent)?\s*"
    r"(?P<scale>billion|million|thousand|bn|mm|m)?$",
    re.I,
)
_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP"}
_SCALE = {
    "billion": "billion", "bn": "billion", "million": "million",
    "mm": "million", "m": "million", "thousand": "thousand",
}


@dataclass(frozen=True)
class PeriodValuePair:
    period: str | None
    value: str
    numeric_value: str
    currency: str | None
    scale: str | None
    value_kind: str


@dataclass(frozen=True)
class PeriodValueMention:
    """A numeric mention with its character offsets in generated prose."""

    start: int
    end: int
    pair: PeriodValuePair


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _period_at(text: str, start: int, end: int) -> str | None:
    periods = {item.label for item in period_mentions(text) if item.start < end and item.end > start}
    return next(iter(periods)) if len(periods) == 1 else None


def _nearest_period(periods: tuple[PeriodMention, ...], start: int, end: int) -> str | None:
    if not periods:
        return None
    distances = [(min(abs(item.start - end), abs(start - item.end)), item.label) for item in periods]
    distance = min(item[0] for item in distances)
    nearest = {label for offset, label in distances if offset == distance}
    return next(iter(nearest)) if len(nearest) == 1 else None


def _value_matches_and_periods(
    text: str, *, allow_unmarked_attached: bool = False,
) -> tuple[list[re.Match], tuple[PeriodMention, ...]]:
    values = []
    for match in _VALUE_RE.finditer(text):
        number_end = match.end("number")
        attached_letter = text[number_end:number_end + 1].isalpha()
        has_unit = bool(match["percent"] or match["scale"])
        attached_amount = match["scale"] and (match["currency"] or allow_unmarked_attached)
        if attached_letter and not (match["percent"] or attached_amount):
            continue
        if _YEAR_RE.fullmatch(match["number"]) and not (match["currency"] or has_unit):
            continue
        values.append(match)
    periods = tuple(
        item for item in period_mentions(text)
        if not any(match.start() <= item.start and item.end <= match.end() for match in values)
    )
    return values, periods


def period_matches(required_period: str | None, evidence_period: str | None) -> bool:
    if required_period is None:
        return True
    if evidence_period is None:
        return False
    required = _normalize(required_period)
    observed = _normalize(evidence_period)
    if required.startswith(("q", "cy")) or observed.startswith(("q", "cy")):
        return required == observed
    required_year = _YEAR_RE.search(required)
    observed_year = _YEAR_RE.search(observed)
    return bool(
        required_year
        and observed_year
        and required_year.group(0) == observed_year.group(0)
    )


def _parse_value(raw: str, context: str = "") -> PeriodValuePair | None:
    match = _STRICT_NUMBER_RE.fullmatch(raw.strip())
    if match is None:
        return None
    numeric = match.group("number").replace(",", "").replace("(", "-").replace(")", "")
    try:
        amount = Decimal(numeric)
    except InvalidOperation:
        return None
    currency_token = match.group("currency")
    currency = _CURRENCY.get(currency_token, currency_token.upper() if currency_token else None)
    if currency is None:
        if re.search(r"\bUSD\b|\$|\bdollars?\b", context, re.I):
            currency = "USD"
        elif re.search(r"\bEUR\b|€|\beuros?\b", context, re.I):
            currency = "EUR"
        elif re.search(r"\bGBP\b|£|\bpounds?\b", context, re.I):
            currency = "GBP"
    scale_token = match.group("scale")
    scale = _SCALE.get(scale_token.casefold()) if scale_token else None
    if scale is None:
        if re.search(r"\b(?:in|dollars? in)\s+millions?\b", context, re.I):
            scale = "million"
        elif re.search(r"\b(?:in|dollars? in)\s+billions?\b", context, re.I):
            scale = "billion"
        elif re.search(r"\b(?:in|dollars? in)\s+thousands?\b", context, re.I):
            scale = "thousand"
        elif currency is not None:
            scale = "unit"
    value_kind = "percent" if match.group("percent") else "amount"
    if value_kind == "amount" and re.search(r"\bper share\b", context, re.I):
        value_kind = "currency_per_share"
    return PeriodValuePair(
        period="",
        value=raw.strip(),
        numeric_value=str(amount.normalize()),
        currency=currency,
        scale=scale,
        value_kind=value_kind,
    )


def _matches_alias(label: str, aliases: tuple[str, ...]) -> bool:
    normalized = _normalize(label)
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(_normalize(alias))}(?![a-z0-9])", normalized)
        for alias in aliases
    )


def _table_pairs(text: str, aliases: tuple[str, ...]) -> list[PeriodValuePair]:
    pairs: list[PeriodValuePair] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Markdown tables are used by the SEC table extractor. Preserve explicit
    # column-to-period alignment and exact canonical row labels.
    headers: list[str] = []
    for line in lines:
        if not line.startswith("|"):
            headers = []
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        periods = [_period_at(cell, 0, len(cell)) for cell in cells[1:]]
        if len(periods) > 0 and all(period is not None for period in periods):
            headers = [period for period in periods if period is not None]
            continue
        if headers and cells and _matches_alias(cells[0], aliases) and len(cells[1:]) == len(headers):
            for period, raw in zip(headers, cells[1:], strict=True):
                parsed = _parse_value(raw, text)
                if parsed is not None:
                    pairs.append(PeriodValuePair(**{**parsed.__dict__, "period": period}))

    # pypdf layout extraction often presents a multi-year header, row label,
    # then one numeric value per line. This bounded scan is based on the
    # original period/value completeness parser.
    index = 0
    while index < len(lines):
        if not _YEAR_RE.fullmatch(lines[index]):
            index += 1
            continue
        years: list[str] = []
        cursor = index
        while cursor < len(lines) and _YEAR_RE.fullmatch(lines[cursor]):
            years.append(lines[cursor])
            cursor += 1
        index = cursor
        if not years:
            continue
        for row_index in range(cursor, min(len(lines), cursor + 40)):
            if not _matches_alias(lines[row_index], aliases):
                continue
            values: list[PeriodValuePair] = []
            value_cursor = row_index + 1
            while value_cursor < len(lines) and len(values) < len(years):
                candidate = lines[value_cursor].replace("$", "").strip()
                parsed = _parse_value(candidate, text)
                if parsed is not None and parsed.value_kind != "percent":
                    values.append(parsed)
                elif re.search(r"[A-Za-z]", candidate):
                    break
                value_cursor += 1
            if len(values) != len(years):
                continue
            pairs.extend(
                PeriodValuePair(**{**value.__dict__, "period": f"FY{year}"})
                for year, value in zip(years, values, strict=True)
            )
    return pairs


def extract_period_value_pairs(
    text: str,
    *,
    metric_aliases: tuple[str, ...],
) -> tuple[PeriodValuePair, ...]:
    """Return numeric metric observations bound to explicit evidence periods."""
    if not text.strip() or not metric_aliases:
        return ()
    pairs = _table_pairs(text, metric_aliases)

    # Prose and one-line tables bind a value to the nearest explicit period in
    # the same sentence/line. Ambiguous values with no nearby period are not
    # promoted to a financial fact.
    segments = re.split(r"(?<=[.;])\s+|\n+", text)
    for segment in segments:
        if not _matches_alias(segment, metric_aliases):
            continue
        value_matches, periods = _value_matches_and_periods(segment)
        for match in value_matches:
            parsed = _parse_value(match.group(0), segment)
            if parsed is None:
                continue
            period = _nearest_period(periods, match.start(), match.end())
            pairs.append(PeriodValuePair(**{**parsed.__dict__, "period": period}))

    unique: dict[tuple[str, str, str, str | None, str | None, str], PeriodValuePair] = {}
    for pair in pairs:
        key = (
            pair.period or "",
            pair.numeric_value,
            pair.value,
            pair.currency,
            pair.scale,
            pair.value_kind,
        )
        unique.setdefault(key, pair)
    return tuple(unique.values())


def extract_period_value_mentions(
    text: str, *, allow_unmarked_attached: bool = False,
) -> tuple[PeriodValueMention, ...]:
    """Extract individual answer-side values while retaining their locations.

    This uses the same conservative value and period parser as evidence facts.
    Bare years are excluded because they describe periods rather than claimed
    financial values.
    """
    mentions: list[PeriodValueMention] = []
    values, periods = _value_matches_and_periods(text, allow_unmarked_attached=allow_unmarked_attached)
    for match in values:
        pair = _parse_value(match.group(0), text)
        if pair is None:
            continue
        period = _nearest_period(periods, match.start(), match.end())
        mentions.append(
            PeriodValueMention(
                start=match.start(),
                end=match.end(),
                pair=PeriodValuePair(**{**pair.__dict__, "period": period}),
            )
        )
    return tuple(mentions)


def extract_filing_assertions(
    text: str, *, metric_aliases: tuple[str, ...], issuer_aliases: tuple[str, ...],
) -> tuple[PeriodValuePair, ...]:
    """Read a single amount asserted for the metric in an explicitly named period."""
    issuer = "|".join(re.escape(alias) for alias in issuer_aliases)
    metric = "|".join(re.escape(alias) for alias in metric_aliases)
    subject = rf"(?:(?:{issuer})(?:['’]s?)? |our |the company['’]s )?" if issuer else r"(?:our |the company['’]s )?"
    name = rf"(?:consolidated )?(?:{metric})"
    relation = r"(?:was|were|is|totaled|amounted to)"
    scope = r"(?:for|in|during) <period>"
    assertion = re.compile(
        rf"(?:<period> {subject}{name} {relation} <value>|"
        rf"(?:in|for|during) <period>,? {subject}{name} {relation} <value>|"
        rf"{subject}{name} (?:{scope} {relation} <value>|{relation} <value> {scope}))[.!]?",
        re.I,
    )
    pairs = []
    for line in re.split(r"(?<=[.;!?])\s+|\n+", text):
        sentence = " ".join(line.split())
        if not _matches_alias(sentence, metric_aliases):
            continue
        values, periods = _value_matches_and_periods(sentence)
        if len(periods) != 1 or len(values) != 1:
            continue
        period, value = periods[0], values[0]
        if not re.match(r"(?:Q[1-4]|FY|CY|fiscal year|calendar year)", sentence[period.start:period.end], re.I):
            continue
        raw = _STRICT_NUMBER_RE.fullmatch(value.group(0).strip())
        if raw is None or not (raw['currency'] not in (None, '$') or raw['percent']):
            continue
        # Do not inherit a unit, a period, or a subject from a neighboring clause.
        for start, end, marker in sorted(((period.start, period.end, '<period>'),
                                          (value.start(), value.end(), '<value>')), reverse=True):
            sentence = sentence[:start] + f" {marker} " + sentence[end:]
        frame = re.sub(r"\s+([,.!?])", r"\1", " ".join(sentence.split()))
        if assertion.fullmatch(frame):
            pair = _parse_value(value.group(0))
            if pair is not None:
                pairs.append(PeriodValuePair(period.label, pair.value, pair.numeric_value,
                                             pair.currency, pair.scale, pair.value_kind))
    return tuple(pairs)
