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
