"""Bind reviewer adjudications to frozen predictions and score G1 outcomes."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.evaluation.benchmark_io import wilson_rate
from src.evaluation.independent_final import ARMS, Freeze, Hash, Label, Question, ReleaseRiskCriteria
from src.evaluation.multi_agent_ablation import paired_grounded_exact
from src.evaluation.primary_metrics import (
    Adjudication, Identifier, RetrievalAdjudication, ScoredCase, score_primary_metrics,
)
from src.generation.answer_generator import is_fallback_answer

_CITATION = re.compile(r"\[Source ([1-9]\d*)\]", re.I)


class ReviewedPredictions(Adjudication):
    schema_version: Literal["filingscope-reviewed-predictions-v1"]
    freeze_sha256: Hash
    predictions_sha256: Hash
    reviewers: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    arms: dict[Literal["B_adaptive", "C_routed"], tuple[ScoredCase, ...]]

    @model_validator(mode="after")
    def check_review(self) -> ReviewedPredictions:
        if len(set(self.reviewers)) != len(self.reviewers):
            raise ValueError("Duplicate semantic reviewer identity")
        if set(self.arms) != set(ARMS):
            raise ValueError("Both frozen arms need an adjudication")
        return self


def _validate_retrieval(review: RetrievalAdjudication | None, prediction: dict) -> None:
    if review is None:
        return
    ranked = prediction.get("pdf_ranked_pages")
    if ranked is None or review.granularity != "page" or tuple(ranked) != review.ranked_ids:
        raise ValueError("Retrieval judgment differs from the frozen PDF ranking")
    if review.relevant_ids is not None and not review.relevant_ids <= set(ranked[:10]):
        raise ValueError("Relevance judgments must refer to frozen top-ten pages")


def _validate_claims(review: ScoredCase, prediction: dict) -> None:
    if review.claims is None:
        return
    markers = {int(number) for number in _CITATION.findall(prediction["answer"])}
    judged_markers = set()
    sources = prediction["citation_sources"]
    for claim in review.claims:
        for citation in claim.citations:
            marker = re.fullmatch(r"Source ([1-9]\d*)", citation.citation_id)
            if marker is None or (number := int(marker[1])) not in markers:
                raise ValueError("Citation judgment refers to a marker absent from the frozen answer")
            if citation.supports_claim and (number > len(sources) or sources[number - 1] is None):
                raise ValueError("An unresolved citation cannot support a claim")
            judged_markers.add(number)
    if judged_markers != markers:
        raise ValueError("Claim adjudication must account for every frozen answer citation")


def _release_risk_gate(report: dict, criteria: ReleaseRiskCriteria) -> dict:
    coverage = report["primary"]["answer_coverage"]["value"]
    bounds = report["diagnostics"]["release_risk_missing_label_bounds"]
    interval = report["release_risk_intervals"]["all_releases_worst_case"]["wilson_95"]
    upper = interval[1] if interval is not None else None
    best_case_risk = bounds["lower"]
    coverage_met = coverage is not None and coverage >= criteria.minimum_coverage
    if not coverage_met or (best_case_risk is not None and best_case_risk > criteria.maximum_incorrect_release):
        status = "DOES_NOT_MEET"
    elif upper is not None and upper <= criteria.maximum_incorrect_release:
        status = "MEETS_DESCRIPTIVE_BOUND"
    else:
        status = "INCONCLUSIVE"
    return {
        "status": status, "criteria": criteria.model_dump(mode="json"), "coverage_met": coverage_met,
        "best_case_risk": best_case_risk, "worst_case_risk": bounds["upper"],
        "worst_case_wilson_95_upper": upper,
    }


def score_reviewed_predictions(
    freeze: Freeze, questions: list[Question], labels: list[Label], predictions: dict, reviewed: ReviewedPredictions,
    *, freeze_sha256: str, predictions_sha256: str,
) -> dict:
    if reviewed.freeze_sha256 != freeze_sha256 or reviewed.predictions_sha256 != predictions_sha256:
        raise ValueError("Semantic adjudication refers to a different freeze or prediction receipt")
    labels_by_id = {label.case_id: label for label in labels}
    case_ids = {question.case_id for question in questions}
    if labels_by_id.keys() != case_ids or len(labels_by_id) != len(labels):
        raise ValueError("Reviewer-held question and label IDs must match exactly")
    if predictions.keys() != set(ARMS) or any(arm.keys() != case_ids for arm in predictions.values()):
        raise ValueError("Both prediction arms must contain the complete cohort")
    reports = {}
    for arm in ARMS:
        cases = {row.case_id: row for row in reviewed.arms[arm]}
        if cases.keys() != case_ids or len(cases) != len(reviewed.arms[arm]):
            raise ValueError(f"Semantic adjudication IDs must match the frozen questions for {arm}")
        ordered = []
        for question in questions:
            row = cases[question.case_id]
            prediction = predictions[arm][question.case_id]
            label = labels_by_id[question.case_id]
            answerable = bool(label.claims)
            numeric = answerable and all(claim.value is not None for claim in label.claims)
            released = bool(prediction["answer"].strip()) and not is_fallback_answer(prediction["answer"])
            if (row.answerable, row.numeric_applicable, row.released) != (answerable, numeric, released):
                raise ValueError(f"Semantic applicability differs for {arm}/{question.case_id}")
            _validate_retrieval(row.retrieval, prediction)
            _validate_claims(row, prediction)
            ordered.append(row)
        report = score_primary_metrics(ordered)
        risk = report["primary"]["incorrect_or_unsupported_release_risk"]
        bounds = report["diagnostics"]["release_risk_missing_label_bounds"]
        report["release_risk_intervals"] = {
            "judged_releases": wilson_rate(risk["numerator"], risk["denominator"]),
            "all_releases_worst_case": wilson_rate(bounds["maximum_errors"], bounds["denominator"]),
        }
        if freeze.release_risk_criteria is not None:
            report["release_risk_gate"] = _release_risk_gate(report, freeze.release_risk_criteria)
        reports[arm] = report
    left, right = (reports[arm]["per_case"] for arm in ARMS)
    pairs = [
        (base, candidate)
        for base, candidate in zip(left, right, strict=True)
        if base["answerable"] and base["grounded_exact"] is not None and candidate["grounded_exact"] is not None
    ]
    paired = paired_grounded_exact(
        [candidate for _, candidate in pairs], [base for base, _ in pairs],
        {q.case_id: set(map(str, q.issuer_ciks)) for q in questions if labels_by_id[q.case_id].claims},
        seed=freeze.bootstrap_seed,
    )
    paired["eligible_answerable_pairs"] = sum(bool(label.claims) for label in labels)
    return {
        "adjudication_schema": reviewed.schema_version, "reviewers": reviewed.reviewers, "arms": reports,
        "paired_grounded_exact": paired,
    }
