"""Preserve the relation in issuer-scoped customer concentration disclosures."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from src.decision.models import MetricRequirement


CUSTOMER_CONCENTRATION = MetricRequirement(
    metric_id="customer_concentration", display_name="customer sales concentration",
    aliases=("customer sales concentration", "customer concentration", "top customer", "largest customer"),
    quantitative=False, expected_value_kind="topic",
)
_QUESTION = re.compile(r"\b(?:top|largest) customer\b|\bcustomer (?:sales )?concentration\b", re.I)
_SALES_SHARE = re.compile(r"\b(?:sales|revenues?|concentration|share|percent(?:age)?|proportion)\b", re.I)
_FRAME = re.compile(
    r"(?:^|(?<=[.!?])\s+)(?:for (?:the )?(?:fiscal )?year ended "
    r"(?:(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*)?|in (?:FY)?)"
    r"(?P<year>20\d{2}),?\s+"
    r"(?P<subject>no customer|each customer|every customer|the largest customer|a single customer)\s+"
    r"(?:accounted for|represented|contributed)\s+"
    r"(?P<relation>more than|less than|no more than|at most|at least|approximately|exactly)?\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*%\s+of\s+"
    r"(?:(?P<owner>[A-Za-z][A-Za-z .&-]{0,79})['’]s\s+)?"
    r"(?P<basis>sales revenue|total revenues?|revenues?|sales)(?=\.|\s*$)", re.I,
)
_RELATIONS = {"more than": ">", "less than": "<", "no more than": "<=", "at most": "<=",
              "at least": ">=", "approximately": "~", "exactly": "=", "": "="}


@dataclass(frozen=True)
class CustomerBound:
    period: str
    relation: str
    value: Decimal
    basis: str
    scope: str

    def sentence(self, company: str) -> str:
        words = {"<=": "at most", "<": "less than", ">": "more than", ">=": "at least",
                 "~": "approximately", "=": "exactly"}
        return (f"{company}'s largest customer accounted for {words[self.relation]} "
                f"{self.value}% of {self.basis} for {self.period}.")

    @property
    def signature(self) -> tuple[str, str, Decimal, str]:
        return self.period, self.relation, self.value, self.basis


def customer_concentration_question(question: str) -> bool:
    return bool(_QUESTION.search(question) and _SALES_SHARE.search(question))


def filing_customer_bounds(text: str, issuer_aliases: tuple[str, ...] = ()) -> tuple[CustomerBound, ...]:
    """Read only explicit annual customer-to-sales relations with a local year."""
    paragraphs = re.split(r"\n(?=[ \t]*For (?:the )?(?:fiscal )?year ended\b)", text, flags=re.I)
    result = []
    matches = (match for paragraph in paragraphs for match in _FRAME.finditer(" ".join(paragraph.split())))
    for match in matches:
        relation = _RELATIONS[(match["relation"] or "").casefold()]
        subject = match["subject"].casefold()
        if subject == "no customer":
            if relation != ">":
                continue
            relation = "<="
        elif subject == "a single customer" or (subject in {"each customer", "every customer"} and relation == "~"):
            continue
        owner = match["owner"]
        if owner and issuer_aliases and owner.casefold() not in {"the company", "company"}:
            normalized_owner = " ".join(re.findall(r"\w+", owner.casefold()))
            aliases = (" ".join(re.findall(r"\w+", alias.casefold())) for alias in issuer_aliases)
            if not any(alias == normalized_owner or alias.startswith(normalized_owner + " ") for alias in aliases):
                continue
        value = Decimal(match["value"])
        if not 0 <= value <= 100:
            continue
        result.append(CustomerBound(f"FY{match['year']}", relation, value,
                                    match["basis"].casefold(), subject))
    return tuple(result)


def asserted_customer_bound(text: str) -> tuple[str, str, Decimal, str] | None:
    match = re.fullmatch(
        r".+?['’]s largest customer accounted for (at most|less than|more than|at least|approximately|exactly) "
        r"(\d+(?:\.\d+)?)% of (sales revenue|total revenues?|revenues?|sales) for (FY20\d{2})\.?", text.strip(), re.I,
    )
    if match is None:
        return None
    return match[4].upper(), _RELATIONS[match[1].casefold()], Decimal(match[2]), match[3].casefold()
