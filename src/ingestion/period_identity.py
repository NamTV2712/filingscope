"""Financial observation periods, independent of a filing's publication date."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class YearBasis(StrEnum):
    FISCAL = "fiscal"
    CALENDAR = "calendar"


class PeriodKind(StrEnum):
    INSTANT = "instant"
    DURATION = "duration"


class PeriodScope(StrEnum):
    ANNUAL = "annual"
    QUARTER = "quarter"
    YEAR_TO_DATE = "year_to_date"


_PERIOD_LABEL = re.compile(r"(?:(Q[1-4]) (YTD )?)?(FY|CY)((?:19|20)[0-9]{2})")
_PERIOD_MENTION = re.compile(
    r"(?<!\w)(?:(Q[1-4])\s*(?:(YTD|year.to.date)\s*)?)?"
    r"(?:(FY|CY|fiscal\s+year|calendar\s+year)\s*)?((?:19|20)[0-9]{2})(?!\d)",
    re.I,
)

_ISO_RANGE = re.compile(r"\bfrom\s+(\d{4}-\d{2}-\d{2})\s+(?:to|through)\s+(\d{4}-\d{2}-\d{2})\b", re.I)
_RANGE_START = re.compile(r"\bfrom\s+(\d{4}-\d{2}-\d{2})\s+(?:to|through)\b", re.I)
_ACCESSION = re.compile(r"\b[0-9]{10}-[0-9]{2}-[0-9]{6}\b")
_QUARTER_AND_YTD = re.compile(
    r"\b(?:standalone|discrete)\s+quarter\s+and\s+(?:fiscal\s+)?(?:year[- ]to[- ]date|YTD)\s+ended\s+"
    r"(\d{4}-\d{2}-\d{2})\s+in\s+(?:its\s+)?10-Q\s+([0-9]{10}-[0-9]{2}-[0-9]{6})\b", re.I,
)


class QuarterYtdLookup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    end: date
    accession: str

    def matches(self, period: PeriodIdentity | None, accession: object, scope: PeriodScope | None) -> bool:
        if (period is None or period.year_basis != YearBasis.FISCAL or period.kind != PeriodKind.DURATION
                or period.scope != scope or period.quarter not in {2, 3} or period.end != self.end
                or period.start is None or accession != self.accession):
            return False
        minimum, maximum = ((70, 110) if scope == PeriodScope.QUARTER else
                            (155, 210) if period.quarter == 2 else (240, 300))
        return minimum <= (period.end - period.start).days + 1 <= maximum


def requested_quarter_ytd(question: str) -> QuarterYtdLookup | None:
    match = _QUARTER_AND_YTD.search(question)
    if match is None:
        return None
    remainder = question[:match.start()] + " " + question[match.end():]
    if _ACCESSION.search(remainder) or period_mentions(remainder):
        raise ValueError("ambiguous_quarter_ytd_lookup")
    try:
        end = date.fromisoformat(match[1])
    except ValueError as exc:
        raise ValueError("invalid_quarter_ytd_lookup") from exc
    return QuarterYtdLookup(end=end, accession=match[2])


def quarter_ytd_pair_matches(quarter: PeriodIdentity, cumulative: PeriodIdentity) -> bool:
    return bool(quarter.start and cumulative.start and quarter.end and cumulative.end == quarter.end
                and cumulative.start < quarter.start and quarter.year == cumulative.year
                and quarter.quarter == cumulative.quarter and quarter.scope == PeriodScope.QUARTER
                and cumulative.scope == PeriodScope.YEAR_TO_DATE)


class ReportingInterval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start: date
    end: date
    accession: str | None = None

    def matches(self, period: PeriodIdentity | None, accession: object) -> bool:
        return bool(period and period.kind == PeriodKind.DURATION and period.start == self.start
                    and period.end == self.end and (self.accession is None or self.accession == accession))


def requested_reporting_interval(question: str) -> ReportingInterval | None:
    matches = list(_ISO_RANGE.finditer(question))
    if not matches:
        if _RANGE_START.search(question):
            raise ValueError("invalid_explicit_reporting_interval")
        return None
    match = matches[0]
    remainder = question[:match.start()] + " " + question[match.end():]
    accessions = set(_ACCESSION.findall(remainder))
    if (len(matches) != 1 or len(accessions) > 1 or _RANGE_START.search(remainder)
            or period_mentions(_ACCESSION.sub(" ", remainder))):
        raise ValueError("ambiguous_explicit_reporting_interval")
    try:
        start, end = (date.fromisoformat(value) for value in match.groups())
    except ValueError as exc:
        raise ValueError("invalid_explicit_reporting_interval") from exc
    if start > end:
        raise ValueError("invalid_explicit_reporting_interval")
    return ReportingInterval(start=start, end=end, accession=next(iter(accessions), None))


@dataclass(frozen=True)
class PeriodMention:
    label: str
    start: int
    end: int


def period_mentions(text: str) -> tuple[PeriodMention, ...]:
    mentions = []
    for match in _PERIOD_MENTION.finditer(text):
        quarter, cumulative, basis, year = match.groups()
        basis = "CY" if basis and basis.casefold().startswith(("cy", "calendar")) else "FY"
        prefix = f"{quarter.upper()} " if quarter else ""
        if cumulative:
            prefix += "YTD "
        mentions.append(PeriodMention(f"{prefix}{basis}{year}", match.start(), match.end()))
    return tuple(mentions)


def intervals_agree(periods: Iterable[PeriodIdentity]) -> bool:
    periods = tuple(periods)
    return all(
        len({value for period in periods if (value := getattr(period, attribute)) is not None}) <= 1
        for attribute in ("label", "start", "end", "kind")
    )


class PeriodIdentity(BaseModel):
    """A reporting period with its own time basis, scope and optional dates."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    year_basis: YearBasis
    year: int = Field(ge=1900, le=2099)
    scope: PeriodScope
    kind: PeriodKind
    quarter: int | None = Field(default=None, ge=1, le=4)
    start: date | None = None
    end: date | None = None
    filing_fiscal_year: int | None = Field(default=None, ge=1900, le=2099)
    filing_fiscal_period: str | None = None

    @model_validator(mode="after")
    def validate_period(self) -> PeriodIdentity:
        if (self.quarter is None) != (self.scope == PeriodScope.ANNUAL):
            raise ValueError("quarter and year-to-date scopes require a quarter number")
        if self.kind == PeriodKind.INSTANT and (self.start is not None or self.scope == PeriodScope.YEAR_TO_DATE):
            raise ValueError("an instant cannot have a start or cumulative duration")
        if self.start is not None and (self.end is None or self.start > self.end):
            raise ValueError("the observation start must precede its end")
        return self

    @classmethod
    def from_label(
        cls, label: str, *, kind: PeriodKind, start: date | None = None, end: date | None = None,
        filing_fiscal_year: int | None = None, filing_fiscal_period: str | None = None,
    ) -> PeriodIdentity:
        match = _PERIOD_LABEL.fullmatch(label)
        if match is None:
            raise ValueError("unsupported reporting period label")
        quarter, cumulative, basis, year = match.groups()
        return cls(
            year_basis=YearBasis.FISCAL if basis == "FY" else YearBasis.CALENDAR,
            year=int(year),
            scope=(PeriodScope.YEAR_TO_DATE if cumulative else PeriodScope.QUARTER if quarter else PeriodScope.ANNUAL),
            kind=kind, quarter=int(quarter[1]) if quarter else None, start=start, end=end,
            filing_fiscal_year=filing_fiscal_year, filing_fiscal_period=filing_fiscal_period,
        )

    @property
    def label(self) -> str:
        basis = "FY" if self.year_basis == YearBasis.FISCAL else "CY"
        prefix = f"Q{self.quarter} " if self.quarter else ""
        if self.scope == PeriodScope.YEAR_TO_DATE:
            prefix += "YTD "
        return f"{prefix}{basis}{self.year}"

    @property
    def comparative(self) -> bool:
        return (
            self.year_basis == YearBasis.FISCAL and self.filing_fiscal_year is not None
            and self.year != self.filing_fiscal_year
        )
