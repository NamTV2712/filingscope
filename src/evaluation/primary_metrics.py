"""Score explicit answer, retrieval and claim adjudications."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SCORING_VERSION = "filingscope-primary-metrics-v1"
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Adjudication(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class NumericChecks(Adjudication):
    """Adjudicate a released answer against all required financial values."""

    values: bool
    company: bool
    metric: bool
    period: bool
    currency: bool
    scale: bool
    reporting_basis: bool
    calculation: bool | None

    @property
    def exact(self) -> bool:
        return all(check is not False for check in self.model_dump().values())


class CitationAdjudication(Adjudication):
    citation_id: Identifier
    supports_claim: bool


class ClaimAdjudication(Adjudication):
    claim_id: Identifier
    supported_by_context: bool
    # Several citations can jointly support a claim. Individual labels record
    # whether each source makes a valid contribution to that claim.
    supported_by_citation_set: bool
    citations: tuple[CitationAdjudication, ...]

    @model_validator(mode="after")
    def check_citations(self) -> ClaimAdjudication:
        if self.supported_by_citation_set and not any(c.supports_claim for c in self.citations):
            raise ValueError("A supporting citation set needs at least one contributing source")
        if len({c.citation_id for c in self.citations}) != len(self.citations):
            raise ValueError("Duplicate claim-citation association")
        return self


class RetrievalAdjudication(Adjudication):
    granularity: Literal["page", "chunk", "fact"]
    ranked_ids: tuple[Identifier, ...]
    # None means relevance was not adjudicated. A supplied set judges every
    # returned identity in the top ten, including an explicitly empty set.
    relevant_ids: frozenset[Identifier] | None = None
    # Distinct targets can share a locator. Each target has one or more
    # acceptable identities, all in the declared granularity.
    gold_targets: dict[Identifier, Annotated[frozenset[Identifier], Field(min_length=1)]] | None = None


class ScoredCase(Adjudication):
    case_id: Identifier
    answerable: bool
    released: bool
    answer_exact: bool | None = None
    numeric_applicable: bool = False
    numeric_checks: NumericChecks | None = None
    claims: Annotated[tuple[ClaimAdjudication, ...], Field(min_length=1)] | None = None
    retrieval: RetrievalAdjudication | None = None

    @model_validator(mode="after")
    def check_applicability(self) -> ScoredCase:
        if self.numeric_applicable and not self.answerable:
            raise ValueError("Numeric exactness requires an answerable case")
        if self.numeric_checks is not None and not self.numeric_applicable:
            raise ValueError("Numeric checks require a numeric-applicable case")
        if self.answer_exact is True and not self.answerable:
            raise ValueError("An unanswerable case cannot have an exact substantive answer")
        if not self.released and any(
            label is not None for label in (self.answer_exact, self.numeric_checks, self.claims)
        ):
            raise ValueError("Answer, numeric and claim labels require a release")
        if self.claims is not None and len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("Duplicate atomic claim ID")
        return self


def _rate(numerator: int, denominator: int, applicable_cases: int, eligible_cases: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
        "applicable_cases": applicable_cases,
        "eligible_cases": eligible_cases,
    }


def _binary_rate(results: Sequence[bool | None]) -> dict:
    judged = len(results) - results.count(None)
    return _rate(results.count(True), judged, judged, len(results))


def _numeric_exact(case: ScoredCase) -> bool | None:
    if not case.numeric_applicable:
        return None
    if not case.released:
        return False
    return case.numeric_checks.exact if case.numeric_checks is not None else None


def _grounded(case: ScoredCase) -> bool | None:
    if not case.answerable or not case.released or case.answer_exact is False:
        return False
    if case.numeric_checks is not None and not case.numeric_checks.exact:
        return False
    if case.claims is not None and any(
        not claim.supported_by_context or not claim.supported_by_citation_set
        or any(not citation.supports_claim for citation in claim.citations)
        for claim in case.claims
    ):
        return False
    if case.answer_exact is None or case.claims is None:
        return None
    if case.numeric_applicable and case.numeric_checks is None:
        return None
    return True


def score_primary_metrics(cases: Sequence[ScoredCase]) -> dict:
    """Report micro counts and missing adjudication without imputing labels."""
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Duplicate case ID")
    answerable = [case for case in cases if case.answerable]
    released = [case for case in cases if case.released]
    numeric = [case for case in answerable if case.numeric_applicable]
    grounded_by_case = {case.case_id: _grounded(case) for case in cases}
    grounded = [grounded_by_case[case.case_id] for case in answerable]
    release_results = [grounded_by_case[case.case_id] for case in released]
    claim_cases = [case.claims for case in released if case.claims is not None]
    claims = [claim for group in claim_cases for claim in group]
    citations = [citation for claim in claims for citation in claim.citations]
    unanswerable = len(cases) - len(answerable)
    wrong_releases = release_results.count(False)
    unknown_releases = release_results.count(None)
    release_count = len(released)
    result = {
        "scoring_version": SCORING_VERSION,
        "case_count": len(cases),
        "primary": {
            "grounded_exact_accuracy": _binary_rate(grounded),
            "numeric_exact_accuracy": _binary_rate([_numeric_exact(case) for case in numeric]),
            "answer_coverage": _rate(len(released), len(cases), len(cases), len(cases)),
            "incorrect_or_unsupported_release_risk": _rate(
                wrong_releases, len(released) - unknown_releases,
                len(released) - unknown_releases, len(released),
            ),
            "citation_support_precision": _rate(sum(citation.supports_claim for citation in citations),
                                                len(citations), len(claim_cases), len(released)),
            "claim_faithfulness": _rate(sum(claim.supported_by_context for claim in claims),
                                       len(claims), len(claim_cases), len(released)),
        },
        "diagnostics": {
            "false_abstention": _rate(sum(not case.released for case in answerable),
                                      len(answerable), len(answerable), len(answerable)),
            "correct_abstention": _rate(sum(not case.released and not case.answerable for case in cases),
                                        unanswerable, unanswerable, unanswerable),
            "unjudged_releases": unknown_releases,
            "release_risk_missing_label_bounds": {
                "denominator": release_count,
                "minimum_errors": wrong_releases,
                "maximum_errors": wrong_releases + unknown_releases,
                "lower": wrong_releases / release_count if release_count else None,
                "upper": (wrong_releases + unknown_releases) / release_count if release_count else None,
            },
        },
        "per_case": [
            {"case_id": case.case_id, "answerable": case.answerable, "released": case.released,
             "grounded_exact": grounded_by_case[case.case_id] if case.answerable else None,
             "numeric_exact": _numeric_exact(case),
             "incorrect_or_unsupported_release": (
                 not grounded_by_case[case.case_id] if case.released and grounded_by_case[case.case_id] is not None else None
             )}
            for case in cases
        ],
    }
    result["retrieval_by_granularity"] = score_retrieval(
        [case.retrieval for case in cases if case.retrieval is not None]
    )
    return result


def score_retrieval(cases: Sequence[RetrievalAdjudication]) -> dict:
    result = {}
    for granularity in sorted({case.granularity for case in cases}):
        rows = [case for case in cases if case.granularity == granularity]
        relevant = returned = found = targets = precision_cases = recall_cases = 0
        for case in rows:
            top = set(case.ranked_ids[:10])
            if case.relevant_ids is not None:
                relevant += len(top & case.relevant_ids)
                returned += len(top)
                precision_cases += 1
            if case.gold_targets:
                found += sum(bool(top & alternatives) for alternatives in case.gold_targets.values())
                targets += len(case.gold_targets)
                recall_cases += 1
        result[granularity] = {
            "context_precision_at_10": _rate(relevant, returned, precision_cases, len(rows)),
            "gold_evidence_recall_at_10": _rate(found, targets, recall_cases, len(rows)),
        }
    return result
