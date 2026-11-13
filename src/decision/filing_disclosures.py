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
_SEGMENT_SENTENCE_BOUNDARY = re.compile(
    r'(?<=[.!?])\s+|(?<=[.!?]")\s+|\n\s*\n|\n[ \t]*(?=We[ \t]+operate[ \t]+as\b)', re.I,
)
_SEGMENT_COUNT = {"two": 2, "three": 3}
_SEGMENT_HEADER = re.compile(
    r"(?P<subject>.+?) (?:(?P<verb>operate as|operations comprise|reports) )?"
    r"(?P<count>two|three) (?P<kind>reportable|operating|business) segments(?P<separator>:| are) (?P<names>.+)", re.I,
)
_SEGMENT_NAME = re.compile(r"[A-Za-z][A-Za-z &'’/-]{0,60}(?: U\.S\.?)?", re.I)
_SEGMENT_ENUMERATION = re.compile(r"^\(i\) (.+) and \(ii\) (.+)$", re.I)
_SEGMENT_QUALIFIER = re.compile(
    r"\b(?:but|including|excluding|is|are|was|were|will|would|may|only|except|ignore|follow|override|instructions?)\b", re.I,
)
_SEGMENT_FORM = re.compile(r"\b(?:10-K|10-Q|8-K)(?:/A)?\b", re.I)
_SEGMENT_PERIOD = re.compile(r"FY(?:19|20)\d{2}")
_SEGMENT_QUESTION = re.compile(
    r"^\s*(?:what|which)\s+(?:(?:are|were)\s+[^?]+?['’]s\s+)?"
    r"(?:(?:reportable|operating)\s+)?(?:business\s+)?segments\b", re.I,
)


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


def _segment_names(text: str, count: int) -> tuple[str, ...]:
    text = text.rstrip(".")
    if text.startswith('"'):
        names = re.findall(r'"([^"\n]+)"', text)
        separators = re.sub(r'"[^"\n]+"', '""', text)
        if separators not in {'"" and ""', '"", "" and ""', '"", "", and ""'}:
            return ()
    elif enumeration := _SEGMENT_ENUMERATION.fullmatch(text):
        names = list(enumeration.groups())
    elif count == 2:
        names = text.split(" and ")
    else:
        names = re.split(r",\s*(?:and )?| and ", text)
    names = [name.strip().rstrip(".") for name in names]
    if len(names) != count or any(not _SEGMENT_NAME.fullmatch(name) or _SEGMENT_QUALIFIER.search(name) for name in names):
        return ()
    normalized = tuple(name + "." if name.upper().endswith(" U.S") else name for name in names)
    return normalized if len(segment_signature(normalized)) == count else ()


def segment_disclosure(statement: str, aliases: Iterable[str], *, source: bool = False) -> tuple[str, tuple[str, ...]] | None:
    frame = _SEGMENT_HEADER.fullmatch(" ".join(statement.split()))
    if frame is None:
        return None
    subject = _words(frame["subject"])
    subjects = {_words(alias) for alias in aliases}
    verb = (frame["verb"] or "").casefold()
    if verb == "reports":
        valid_frame = subject in subjects and frame["separator"] == ":"
    elif source and verb == "operate as":
        valid_frame = subject == "we" and frame["separator"] == ":"
    elif source and verb == "operations comprise":
        valid_frame = subject in {"our", "the company s"} and frame["separator"] == ":"
    else:
        valid_frame = source and not verb and subject == "our" and frame["separator"].casefold() == " are"
    if not valid_frame:
        return None
    names = _segment_names(frame["names"], _SEGMENT_COUNT[frame["count"].casefold()])
    return (frame["kind"].casefold(), names) if names else None


def filing_segment_disclosures(text: str, aliases: Iterable[str]) -> set[tuple[str, tuple[str, ...]]]:
    subjects = tuple(aliases)
    return {
        disclosure for sentence in _SEGMENT_SENTENCE_BOUNDARY.split(text)
        if sentence.rstrip().endswith((".", '."'))
        and (disclosure := segment_disclosure(sentence, subjects, source=True)) is not None
    }


def segment_signature(names: tuple[str, ...]) -> frozenset[str]:
    return frozenset(name.casefold().replace("’", "'") for name in names)


def segment_kind_matches(question: str, kind: str) -> bool:
    kinds = set(re.findall(r"\b(reportable|operating) (?:business )?segments\b", question.casefold()))
    return not kinds or kinds == {kind}


def is_segment_list_question(question: str) -> bool:
    return bool(_SEGMENT_QUESTION.match(question))


def segment_form_matches(question: str, *forms: object) -> bool:
    requested = {form.upper() for form in _SEGMENT_FORM.findall(question)} or {"10-K"}
    observed = {form.upper() for form in forms if isinstance(form, str) and form}
    return len(requested) == 1 and observed == requested and requested <= {"10-K", "10-K/A"}


def segment_period_matches(requested: str | None, observed: str | None) -> bool:
    return bool(requested and requested == observed and _SEGMENT_PERIOD.fullmatch(requested))
