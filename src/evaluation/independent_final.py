"""Validate a reviewer-held final cohort and score frozen predictions offline."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from configs.multi_agent_ablation import AblationCase, GoldClaim
from configs.sec_snapshots import SEC_CUTOFF, SEC_ISSUERS
from src.agent.complexity_router import ExecutionPath
from src.evaluation.answer_metrics import numeric_fact_signatures
from src.evaluation.benchmark_io import wilson_rate
from src.evaluation.multi_agent_ablation import (
    AblationObservation, evaluate_observation, paired_grounded_exact, summarize_ablation,
)


Hash = Annotated[str, StringConstraints(pattern=r"^sha256:[a-f0-9]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")]
Cik = Annotated[int, Field(gt=0, le=9_999_999_999)]
Nonempty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ARMS = ("B_adaptive", "C_routed")
CATEGORIES = frozenset({"lookup", "revision", "quarter_ytd", "hard_negative", "multi_company", "multi_period", "narrative", "unanswerable"})


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Freeze(_Record):
    reviewer: Nonempty
    git_sha: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40}$")]
    selection_seed: int
    bootstrap_seed: int
    filing_from: date
    filing_through: date
    forms: tuple[Nonempty, ...] = Field(min_length=1)
    category_minimums: dict[str, Annotated[int, Field(gt=0)]]
    dataset_license: Nonempty
    adjudication: Nonempty
    success_criteria: Nonempty
    exposed_membership_sha256: Hash
    corpus_sha256: Hash
    questions_sha256: Hash
    labels_sha256: Hash
    threads: int = Field(default=6, ge=1, le=16)
    python_version: Nonempty
    dependencies: dict[Nonempty, Nonempty] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_protocol(self):
        if self.filing_from <= date.fromisoformat(SEC_CUTOFF) or self.filing_from > self.filing_through:
            raise ValueError("Final filings must be in a declared window after the development cutoff")
        if set(self.category_minimums) != CATEGORIES:
            raise ValueError("Declare a positive quota for every final category")
        return self


class Membership(_Record):
    """Reviewer crosswalk of previously exposed cohorts, including historical P1/P5."""

    cohort: Nonempty
    issuer_ciks: tuple[Cik, ...] = Field(min_length=1)
    document_ids: tuple[Identifier, ...]
    through: date


class Filing(_Record):
    document_id: Identifier
    cik: Cik
    filed: date
    form: Nonempty
    accession: Annotated[str, StringConstraints(pattern=r"^\d{10}-\d{2}-\d{6}$")]
    source_url: Annotated[str, StringConstraints(pattern=r"^https://www\.sec\.gov/Archives/")]
    document_sha256: Hash

    @model_validator(mode="after")
    def validate_locator(self):
        accession = self.accession.replace("-", "")
        expected = f"https://www.sec.gov/Archives/edgar/data/{self.cik}/{accession}/"
        if not self.source_url.startswith(expected) or not self.source_url.removeprefix(expected):
            raise ValueError("SEC URL must identify the frozen registrant and accession")
        return self


class Corpus(_Record):
    index_id: Identifier
    fingerprint: Hash
    index_manifest_sha256: Hash
    embedding_manifest_sha256: Hash
    chunks_sha256: Hash
    pages_sha256: Hash
    sec_manifest_sha256: Hash
    filings: tuple[Filing, ...] = Field(min_length=1)


class Question(_Record):
    case_id: Identifier
    category: str
    question: Nonempty = Field(max_length=1000)
    issuer_ciks: tuple[Cik, ...] = Field(min_length=1)


class Claim(_Record):
    value: Nonempty | None = None
    statement: Nonempty | None = None
    terms: tuple[Nonempty, ...] = ()
    periods: tuple[Nonempty, ...] = ()
    source_slots: tuple[tuple[Nonempty, ...], ...] = Field(min_length=1)
    provenance: Nonempty

    @model_validator(mode="after")
    def validate_claim(self):
        if (self.value is None) == (self.statement is None) or any(not slot for slot in self.source_slots):
            raise ValueError("Each claim needs one numeric value or narrative statement and nonempty source alternatives")
        if self.value is not None and (not self.terms or len(numeric_fact_signatures(self.value)) != 1):
            raise ValueError("Numeric labels need one parseable value and explicit matching terms")
        return self


class Label(_Record):
    case_id: Identifier
    reviewers: tuple[Nonempty, ...] = Field(min_length=1)
    adjudication: Nonempty
    intended_path: ExecutionPath
    claims: tuple[Claim, ...]


def read_pinned(path: Path, expected: str) -> str:
    content = path.read_bytes()
    if f"sha256:{hashlib.sha256(content).hexdigest()}" != expected:
        raise ValueError(f"Frozen input hash mismatch for {path.name}")
    return content.decode("utf-8")


def read_rows(path: Path, expected: str, model):
    return [model.model_validate_json(line) for line in read_pinned(path, expected).splitlines() if line.strip()]


def check_membership(freeze: Freeze, exposed: list[Membership], corpus: Corpus, questions: list[Question]) -> None:
    if not exposed or any(row.through >= freeze.filing_from for row in exposed):
        raise ValueError("Supply the exposed membership and freeze a later filing window")
    excluded_ciks = {*SEC_ISSUERS.values(), *(cik for row in exposed for cik in row.issuer_ciks)}
    excluded_docs = {doc for row in exposed for doc in row.document_ids}
    filings = corpus.filings
    if len({row.document_id for row in filings}) != len(filings) or len({row.accession for row in filings}) != len(filings):
        raise ValueError("Duplicate filing identity in final corpus")
    if any(row.cik in excluded_ciks or row.document_id in excluded_docs for row in filings):
        raise ValueError("Final corpus overlaps an exposed issuer or filing")
    if any(not freeze.filing_from <= row.filed <= freeze.filing_through or row.form not in freeze.forms for row in filings):
        raise ValueError("Final corpus includes a filing outside the frozen form or date window")
    if len({row.case_id for row in questions}) != len(questions):
        raise ValueError("Duplicate question ID")
    if any(excluded_ciks.intersection(row.issuer_ciks) or len(set(row.issuer_ciks)) != len(row.issuer_ciks) for row in questions):
        raise ValueError("A question overlaps an exposed issuer or lists the same issuer twice")
    available_ciks = {row.cik for row in filings}
    if any(row.category != "unanswerable" and not set(row.issuer_ciks) <= available_ciks for row in questions):
        raise ValueError("Answerable-category questions must refer to issuers in the frozen corpus")
    if any(row.category == "multi_company" and len(row.issuer_ciks) < 2 for row in questions):
        raise ValueError("A multi-company case requires at least two distinct issuers")
    counts = Counter(row.category for row in questions)
    if counts.keys() - CATEGORIES or any(counts[key] < minimum for key, minimum in freeze.category_minimums.items()):
        raise ValueError("Final question category quotas were not satisfied")


def _summary(rows: list[dict]) -> dict:
    released = [row for row in rows if row["answered"]]
    unsupported = sum(row["unsupported_released_claims"] > 0 for row in released)
    return {**summarize_ablation(rows), "unsupported_release": wilson_rate(unsupported, len(released)),
            "numeric_answerable_cases": sum(row["numeric_exact"] is not None for row in rows)}


def score_cohort(freeze: Freeze, corpus: Corpus, questions: list[Question], labels: list[Label], predictions: dict) -> dict:
    label_by_id = {row.case_id: row for row in labels}
    question_ids = {row.case_id for row in questions}
    if len(label_by_id) != len(labels) or question_ids != label_by_id.keys():
        raise ValueError("Question and label IDs must match exactly")
    if predictions.keys() != set(ARMS) or any(arm.keys() != question_ids for arm in predictions.values()):
        raise ValueError("Both prediction arms must contain the complete cohort")
    by_document = {row.document_id: row.cik for row in corpus.filings}
    by_accession = {row.accession: row.cik for row in corpus.filings}
    rows = {arm: [] for arm in ARMS}
    for question in questions:
        label = label_by_id[question.case_id]
        if bool(label.claims) == (question.category == "unanswerable"):
            raise ValueError(f"Answerability label differs from the frozen category for {question.case_id}")
        if question.category in {"revision", "hard_negative", "multi_company", "quarter_ytd"} and len(set(label.reviewers)) < 2:
            raise ValueError(f"High-risk case requires two distinct reviewers: {question.case_id}")
        for claim in label.claims:
            for slot in claim.source_slots:
                for locator in slot:
                    document, marker, page = locator.rpartition("#p")
                    cik = by_accession.get(locator.removeprefix("sec:")) if locator.startswith("sec:") else (
                        by_document.get(document) if marker and page.isascii() and page.isdecimal() else None
                    )
                    if cik not in question.issuer_ciks:
                        raise ValueError(f"Source locator is outside the case's frozen issuer scope: {question.case_id}")
        case = AblationCase(question.case_id, "independent_final", question.category, question.question, label.intended_path,
                            tuple(GoldClaim(claim.value or "", claim.terms, claim.source_slots, claim.periods, claim.statement)
                                  for claim in label.claims))
        for arm in ARMS:
            observed = dict(predictions[arm][case.case_id])
            latency = observed.pop("latency_ms")
            observed["retrieved_sources"] = frozenset(observed["retrieved_sources"])
            rows[arm].append(evaluate_observation(case, AblationObservation(**observed), latency_ms=latency,
                                                   require_complete_claims=True))
    return {
        "classification": "reviewer-held independent final evaluation",
        "success_criteria": freeze.success_criteria,
        "cohort_counts": dict(Counter(row.category for row in questions)),
        "arms": {arm: {"overall": _summary(items), "per_case": items,
                       "by_category": {category: _summary([row for row in items if row["category"] == category])
                                       for category in sorted(CATEGORIES)}} for arm, items in rows.items()},
        "paired_grounded_exact": paired_grounded_exact(rows["C_routed"], rows["B_adaptive"],
                                                       {q.case_id: set(map(str, q.issuer_ciks)) for q in questions},
                                                       seed=freeze.bootstrap_seed),
    }
