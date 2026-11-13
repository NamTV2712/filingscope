"""Recognize narrow, issuer-bound factual disclosures in filing text."""

from __future__ import annotations

import re
from collections.abc import Iterable


_INDUSTRY = re.compile(
    r"^(?P<entity>.+?)\s+(?P<relation>(?:do|does)\s+not\s+operate\s+in|operates?\s+in|is\s+not\s+in|is\s+in)"
    r"\s+(?:the\s+)?(?P<industry>[a-z][a-z -]{0,100}?)\s+(?:industry|sector)\b(?P<tail>.*)$", re.I,
)
_UNVERIFIED_INDUSTRY = re.compile(
    r"\b(?:and|but|while|whereas|not|never|only|solely|except|excluding|because|due to|approximately|"
    r"at least|at most|more than|less than|may|might|could|would)\b", re.I,
)
_INDUSTRY_TAIL = re.compile(r"^(?:\s+and\s+(?:serves|provides|sells|supplies)\b.*)?[.!?]*$", re.I)
_SOURCE_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\s*;\s*|\n\s*\n")


def _words(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def industry_relation(statement: str, aliases: Iterable[str], *, source: bool = False) -> tuple[str, bool] | None:
    frame = _INDUSTRY.fullmatch(" ".join(statement.split()))
    subjects = {_words(alias) for alias in aliases}
    if source:
        subjects.update(("we", "the company"))
    if frame is None or _words(frame["entity"]) not in subjects:
        return None
    tail = frame["tail"].strip(" .?!")
    if tail and (not source or not _INDUSTRY_TAIL.fullmatch(frame["tail"])):
        return None
    industry = _words(frame["industry"])
    if not industry or _UNVERIFIED_INDUSTRY.search(industry):
        return None
    return industry, "not" not in frame["relation"].casefold().split()


def filing_industry_relations(text: str, aliases: Iterable[str]) -> set[tuple[str, bool]]:
    """Extract explicit industry assertions after the source is bound to its issuer."""
    return {
        relation for sentence in _SOURCE_SENTENCE_BOUNDARY.split(text)
        if (relation := industry_relation(sentence, aliases, source=True)) is not None
    }
