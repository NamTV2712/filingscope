"""Recognize narrow, issuer-bound factual disclosures in filing text."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit


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
_SEGMENT_COUNT = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
_COUNT = "|".join(_SEGMENT_COUNT)
_SEGMENT_SCOPE = r"[A-Za-z][A-Za-z &-]{0,49}"
_SEGMENT_HEADER = re.compile(
    rf"(?P<subject>.+?) (?:(?P<verb>operate as|operations comprise|reports|have organized our operations into) )?"
    rf"(?P<count>{_COUNT}) (?P<kind>(?:(?:reportable|operating|business) )?segments|lines of business)"
    rf"(?: for (?P<scope>{_SEGMENT_SCOPE}))?(?P<separator>:| are) (?P<names>.+)", re.I,
)
_CONSIST_OF = re.compile(r"(?:the company['’]s|our) reportable segments consist of (?:the )?(?P<names>.+)", re.I)
_BUSINESS_LINES = re.compile(rf"our company operates in (?P<count>{_COUNT}) lines of business: (?P<names>.+)", re.I)
_SUBSIDIARY_LIST = re.compile(
    rf"we report (?P<scope>{_SEGMENT_SCOPE}?) in (?P<count>{_COUNT}) segments, (?P<names>.+?)"
    rf"(?:; we also report all non-(?P=scope) businesses collectively as .+"
    rf"|, and all non-(?P=scope) businesses collectively as .+)?", re.I,
)
_FINANCIAL_PERFORMANCE_LIST = re.compile(
    rf"we operate our business and report our financial performance using (?P<count>{_COUNT}) segments: (?P<names>.+)",
    re.I,
)
_SEGMENT_NAME = re.compile(r"[A-Za-z][A-Za-z &'’/-]{0,60}(?: U\.S\.?)?", re.I)
_SEGMENT_ENUMERATION = re.compile(r"^\(i\) (.+) and \(ii\) (.+)$", re.I)
_SEGMENT_QUALIFIER = re.compile(
    r"\b(?:but|including|excluding|is|are|was|were|will|would|may|only|except|ignore|follow|override|instructions?)\b", re.I,
)
_SEGMENT_FORM = re.compile(r"\b(?:10-K|10-Q|8-K)(?:/A)?\b", re.I)
_SEGMENT_PERIOD = re.compile(r"FY(?:19|20)\d{2}")
_ACCESSION = re.compile(r"\b[0-9]{10}-[0-9]{2}-[0-9]{6}\b")
_ANNUAL_PREAMBLE = re.compile(r"^\s*according to [^?\n,]+?\b10-K(?:/A)?(?:\s+[0-9]{10}-[0-9]{2}-[0-9]{6})?,\s*", re.I)
_SUBSIDIARY_QUESTION = re.compile(
    rf"which businesses are reported in (?P<scope>{_SEGMENT_SCOPE}?)['’]s (?P<count>{_COUNT}) segments\b", re.I,
)
_SEGMENT_QUESTION = re.compile(
    rf"^\s*(?:what|which)\s+(?:(?:are|were)\s+)?(?:[^?]+?['’]s\s+)?(?:the\s+)?"
    rf"(?:(?:{_COUNT})\s+)?(?:(?:reportable|operating)\s+)?(?:business\s+)?(?:segments|lines of business)\b", re.I,
)
_SEGMENT_ORGANIZATION_QUESTION = re.compile(r"how does the company organize its operations into segments\b", re.I)
_ANNUAL_LIST_QUESTION = re.compile(
    rf"(?:what (?:are|were) the (?:(?:{_COUNT}) )?(?:(?:reportable|operating|business) )?segments"
    rf"|what (?:are|were) the (?:(?:{_COUNT}) )?lines of business"
    rf"|which (?:{_COUNT}) segments does the company use to report financial performance)", re.I,
)
BUSINESS_DISCLOSURE_METRICS = frozenset({"business_segments", "business_lines"})
AMENDMENT_SCOPE_METRIC = "amendment_scope"
_AMENDMENT_QUESTION = re.compile(
    r"which items of (?P<issuer>[^?\n]+?)['’]s original (?:Form )?10-K did the explanatory note in (?:Form )?10-K/A "
    r"(?P<accession>[0-9]{10}-[0-9]{2}-[0-9]{6}) say it amended\??", re.I,
)
_ITEM_NUMBER = r"[1-9][0-9]?"
_ITEM_LIST = rf"{_ITEM_NUMBER}(?: through {_ITEM_NUMBER}|(?:, {_ITEM_NUMBER})*,? and {_ITEM_NUMBER})?"
_AMENDMENT_ITEMS = rf"Part (?P<part>IV|III|II|I), (?P<label>Items?) (?P<items>{_ITEM_LIST})"
_EXPLANATORY_NOTE = re.compile(r"explanatory note[.]?", re.I)
_AMENDMENT_SOURCE = re.compile(
    rf"(?:[·•]\s*amend|this amendment amends) {_AMENDMENT_ITEMS} of the original Form 10-K"
    r"(?: to include the information required by such items)?[.;]", re.I,
)
_AMENDMENT_CLAIM = re.compile(
    rf"the explanatory note states that (?P<issuer>.+?) amended {_AMENDMENT_ITEMS} of its original Form 10-K[.]?",
    re.I,
)
AmendmentScope = tuple[str, tuple[int, ...]]


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


def _segment_names(text: str, count: int | None) -> tuple[str, ...]:
    text = text.rstrip(".")
    if text.startswith('"'):
        names = re.findall(r'"([^"\n]+)"', text)
        if not re.fullmatch(r'"[^"\n]+"(?:, "[^"\n]+")*,? and "[^"\n]+"', text):
            return ()
    elif enumeration := _SEGMENT_ENUMERATION.fullmatch(text):
        names = list(enumeration.groups())
    elif count == 2:
        names = text.split(" and ")
    elif count is not None and text.count(",") == count - 1:
        pieces = text.split(",")
        names = [*pieces[:-1], pieces[-1].strip().removeprefix("and ")]
    else:
        names = re.split(r",\s*(?:and )?| and ", text)
    names = [name.strip().rstrip(".") for name in names]
    if count is None:
        count = len(names)
        if count not in _SEGMENT_COUNT.values():
            return ()
    if len(names) != count or any(not _SEGMENT_NAME.fullmatch(name) or _SEGMENT_QUALIFIER.search(name) for name in names):
        return ()
    normalized = tuple(name + "." if name.upper().endswith(" U.S") else name for name in names)
    return normalized if len(segment_signature(normalized)) == count else ()


def _segment_kind(label: str, scope: str | None) -> str:
    if scope is not None:
        return f"business:{_words(scope)}"
    if label.casefold() == "lines of business":
        return "lines"
    return label.casefold().removesuffix("segments").strip() or "segments"


def segment_disclosure(statement: str, aliases: Iterable[str], *, source: bool = False) -> tuple[str, tuple[str, ...]] | None:
    text = " ".join(statement.split())
    if source:
        if match := _CONSIST_OF.fullmatch(text):
            names = _segment_names(match["names"], None)
            return ("reportable", names) if names else None
        if match := _BUSINESS_LINES.fullmatch(text):
            names = _segment_names(match["names"], _SEGMENT_COUNT[match["count"].casefold()])
            return ("lines", names) if names else None
        if match := _FINANCIAL_PERFORMANCE_LIST.fullmatch(text):
            names = _segment_names(match["names"], _SEGMENT_COUNT[match["count"].casefold()])
            return ("segments", names) if names else None
        if match := _SUBSIDIARY_LIST.fullmatch(text):
            names = _segment_names(match["names"], _SEGMENT_COUNT[match["count"].casefold()])
            return (_segment_kind("segments", match["scope"]), names) if names else None
    frame = _SEGMENT_HEADER.fullmatch(text)
    if frame is None:
        return None
    subject = _words(frame["subject"])
    subjects = {_words(alias) for alias in aliases}
    verb = (frame["verb"] or "").casefold()
    if verb == "reports":
        valid_frame = subject in subjects and frame["separator"] == ":"
    elif source and verb in {"operate as", "have organized our operations into"}:
        valid_frame = subject == "we" and frame["separator"] == ":"
    elif source and verb == "operations comprise":
        valid_frame = subject in {"our", "the company s"} and frame["separator"] == ":"
    else:
        valid_frame = source and not verb and subject == "our" and frame["separator"].casefold() == " are"
    if not valid_frame:
        return None
    if frame["scope"] and (verb != "reports" or frame["kind"].casefold() != "segments"):
        return None
    names = _segment_names(frame["names"], _SEGMENT_COUNT[frame["count"].casefold()])
    return (_segment_kind(frame["kind"], frame["scope"]), names) if names else None


def filing_segment_disclosures(text: str, aliases: Iterable[str]) -> set[tuple[str, tuple[str, ...]]]:
    subjects = tuple(aliases)
    return {
        disclosure for sentence in _SEGMENT_SENTENCE_BOUNDARY.split(text)
        if sentence.rstrip().endswith((".", '."'))
        and (disclosure := segment_disclosure(sentence, subjects, source=True)) is not None
    }


def business_disclosure_sentence(issuer: str, kind: str, names: tuple[str, ...]) -> str:
    count = next(word for word, size in _SEGMENT_COUNT.items() if size == len(names))
    label = (f"segments for {kind.split(':', 1)[1].title()}" if kind.startswith("business:") else
             "lines of business" if kind == "lines" else
             "segments" if kind == "segments" else f"{kind} segments")
    quoted = [f'"{name}"' for name in names]
    listing = f"{', '.join(quoted[:-1])} and {quoted[-1]}"
    return f"{issuer} reports {count} {label}: {listing}."


def segment_signature(names: tuple[str, ...]) -> frozenset[str]:
    return frozenset(name.casefold().replace("’", "'") for name in names)


def _disclosure_body(question: str) -> str:
    return _ANNUAL_PREAMBLE.sub("", question, count=1).partition("?")[0].strip()


def segment_kind_matches(question: str, kind: str, count: int) -> bool:
    body = _disclosure_body(question)
    counts = {_SEGMENT_COUNT[word.casefold()] for word in re.findall(rf"\b({_COUNT}) (?=(?:(?:reportable|operating|business) )?(?:segments|lines of business)\b)", body, re.I)}
    if counts and counts != {count}:
        return False
    if match := _SUBSIDIARY_QUESTION.fullmatch(body):
        return kind == f"business:{_words(match['scope'])}"
    if re.search(r"\blines of business\b", body, re.I):
        return kind == "lines"
    if kind == "lines" or kind.startswith("business:"):
        return False
    kinds = set(re.findall(r"\b(reportable|operating) (?:business )?segments\b", body.casefold()))
    return not kinds or kinds == {kind}


def is_segment_list_question(question: str) -> bool:
    body = _disclosure_body(question)
    if _ANNUAL_PREAMBLE.match(question):
        return bool(_ANNUAL_LIST_QUESTION.fullmatch(body) or _SUBSIDIARY_QUESTION.fullmatch(body)
                    or _SEGMENT_ORGANIZATION_QUESTION.fullmatch(body))
    return bool(_SEGMENT_QUESTION.match(body))


def business_disclosure_issuer_text(question: str) -> str:
    preamble = _ANNUAL_PREAMBLE.match(question)
    if preamble is not None and _SUBSIDIARY_QUESTION.fullmatch(_disclosure_body(question)):
        return preamble[0]
    frame = _SEGMENT_HEADER.fullmatch(" ".join(question.split()))
    if frame is not None and (frame["verb"] or "").casefold() == "reports":
        return frame["subject"]
    return question


def segment_form_matches(question: str, *forms: object) -> bool:
    requested = {form.upper() for form in _SEGMENT_FORM.findall(question)} or {"10-K"}
    observed = {form.upper() for form in forms if isinstance(form, str) and form}
    return len(requested) == 1 and observed == requested and requested <= {"10-K", "10-K/A"}


def segment_period_matches(requested: str | None, observed: str | None) -> bool:
    return bool(requested and requested == observed and _SEGMENT_PERIOD.fullmatch(requested))


def business_disclosure_source_matches(
    question: str, period: str | None, observed_period: str | None, chunk: Mapping[str, object],
) -> bool:
    if not segment_form_matches(question, chunk.get("doc_type"), chunk.get("filing_type"), chunk.get("form_type")):
        return False
    if not observed_period or not _SEGMENT_PERIOD.fullmatch(observed_period):
        return False
    requested = {match[0] for match in _ACCESSION.finditer(question)}
    if not requested:
        return segment_period_matches(period, observed_period)
    return (len(requested) == 1 and (period is None or period == observed_period)
            and _sec_accession_matches(next(iter(requested)), chunk))


def _sec_accession_matches(accession: str, chunk: Mapping[str, object]) -> bool:
    supplied = {value for key in ("accession", "accession_number") if isinstance(value := chunk.get(key), str) and value}
    if supplied != {accession}:
        return False
    source_url = chunk.get("source_url") or chunk.get("source_repository_url") or chunk.get("filing_url")
    if not isinstance(source_url, str):
        return False
    try:
        locator = urlsplit(source_url)
    except ValueError:
        return False
    path = re.fullmatch(r"/Archives/edgar/data/([0-9]{1,10})/" + accession.replace("-", "") + r"/[^/]+", locator.path)
    cik = chunk.get("cik")
    return bool(locator.scheme == "https" and locator.netloc == "www.sec.gov" and path
                and (cik is None or str(cik).lstrip("0") == path[1].lstrip("0")))


def requested_amendment_scope(question: str) -> tuple[str, str] | None:
    if frame := _AMENDMENT_QUESTION.fullmatch(question.strip()):
        return frame["issuer"], frame["accession"]
    return None


def amendment_source_matches(accession: str, period: str | None, chunk: Mapping[str, object]) -> bool:
    forms = {form.upper() for key in ("doc_type", "filing_type", "form_type")
             if isinstance(form := chunk.get(key), str) and form}
    return (forms == {"10-K/A"} and period is not None and bool(_SEGMENT_PERIOD.fullmatch(period))
            and bool(chunk.get("cik")) and _sec_accession_matches(accession, chunk))


def _amendment_items(frame: re.Match[str]) -> AmendmentScope | None:
    items = tuple(int(value) for value in re.findall(r"[0-9]+", frame["items"]))
    if items != tuple(sorted(set(items))):
        return None
    if " through " in frame["items"].casefold():
        items = tuple(range(items[0], items[-1] + 1))
    if (len(items) == 1) != (frame["label"].casefold() == "item"):
        return None
    return frame["part"].upper(), items


def filing_amendment_scopes(text: str) -> set[AmendmentScope]:
    """Read explicit item lists at the start of an explanatory note block."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not _EXPLANATORY_NOTE.fullmatch(lines[0]):
        return set()
    scopes = set()
    for line in lines[1:]:
        frame = _AMENDMENT_SOURCE.fullmatch(" ".join(line.split()))
        if frame is not None and (scope := _amendment_items(frame)) is not None:
            scopes.add(scope)
        elif re.match(r"(?:[·•]\s*amend\b|this amendment amends\b)", line, re.I):
            return set()
        elif not scopes:
            return set()
    return scopes


def amendment_scope_claim(statement: str) -> tuple[str, AmendmentScope] | None:
    frame = _AMENDMENT_CLAIM.fullmatch(" ".join(statement.split()))
    if frame is not None and (scope := _amendment_items(frame)) is not None:
        return frame["issuer"], scope
    return None


def amendment_scope_sentence(issuer: str, scope: AmendmentScope) -> str:
    part, items = scope
    numbers = [str(item) for item in items]
    listing = numbers[0] if len(items) == 1 else f"{', '.join(numbers[:-1])} and {numbers[-1]}"
    label = "Item" if len(items) == 1 else "Items"
    return f"The explanatory note states that {issuer} amended Part {part}, {label} {listing} of its original Form 10-K."
