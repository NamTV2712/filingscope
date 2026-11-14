"""Confirm released answers against frozen mixed-cohort references."""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from itertools import product

from src.evaluation.answer_metrics import numeric_fact_signatures
from src.generation.answer_generator import is_fallback_answer
from src.ingestion.company_facts import METRIC_CONCEPTS, normalize_cik


_CONCEPT_METRIC = {concept: metric for metric, concepts in METRIC_CONCEPTS.items() for concept in concepts}


def _signature(value: str, currency: str) -> tuple:
    return "amount", currency, format(Decimal(value).normalize(), "f"), "base"


def _matches_record(record: dict, slot: dict) -> bool:
    provenance = record.get("xbrl_provenance")
    period = record.get("period_identity") or {}
    concept = f"us-gaap:{slot['tag']}"
    if provenance is not None:
        source_ok = (provenance["accession"] == slot["accession"] and not provenance.get("dimensions")
                     and f"{provenance['taxonomy']}:{provenance['tag']}" == concept)
    else:
        metric = _CONCEPT_METRIC.get(concept)
        source_ok = (record.get("source_revision") == slot["accession"] and record.get("table_row") is not None
                     and metric is not None and metric == record.get("metric_id"))
    return bool(
        source_ok and record.get("cik") and normalize_cik(record["cik"]) == slot["cik"]
        and period.get("start") == slot["start"] and period.get("end") == slot["end"]
        and record.get("currency") == slot["currency"] and record.get("normalized_value") is not None
        and Decimal(record["normalized_value"]) == Decimal(slot["value"])
    )


def score_mixed_release(
    case: dict, answer: str, disposition: str, claims: list[dict], records: list[dict], citation_ids: list[str],
) -> dict:
    answered = bool(answer.strip()) and not is_fallback_answer(answer)
    outcome = {"released": answered, "outcome": "withheld"}
    if not case["answerable"]:
        outcome["outcome"] = "unexpected_release" if answered else "correct_abstention"
        return outcome
    if not answered:
        return outcome
    slots = case["required_facts"]
    if not slots:
        outcome["outcome"] = "narrative_release_pending_review"
        return outcome
    actual = [tuple(item[:4] for item in numeric_fact_signatures(claim["statement"])) for claim in claims]
    expected = [_signature(slot["value"], slot["currency"]) for slot in slots]
    if len(claims) != len(slots) or Counter(item for group in actual for item in group) != Counter(expected):
        outcome["outcome"] = "incomplete_or_incorrect_numeric_release"
        return outcome

    by_id = {record["evidence_id"]: record for record in records}
    options = []
    for slot, signature in zip(slots, expected, strict=True):
        matched = []
        for index, claim in enumerate(claims):
            if claim["status"] != "SUPPORTED" or actual[index] != (signature,):
                continue
            numbers = claim["citations"]
            if any(not 1 <= number <= len(citation_ids) for number in numbers):
                continue
            cited = {citation_ids[number - 1] for number in numbers}
            if not cited or not cited.issubset(claim["supporting_evidence_ids"]):
                continue
            matching_sources = set()
            for evidence_id in cited:
                record = by_id[evidence_id]
                supporting_rows = [record] if record.get("xbrl_provenance") else [
                    row for row in records if row.get("chunk_id") == record.get("chunk_id")
                    and row.get("table_row") is not None and set(row["requirement_ids"]).intersection(claim["requirement_ids"])
                ]
                if any(_matches_record(row, slot) for row in supporting_rows):
                    matching_sources.add(evidence_id)
            if matching_sources == cited:
                matched.append(index)
        options.append(matched)
    confirmed = disposition == "VERIFIED" and any(len(set(group)) == len(slots) for group in product(*options))
    outcome["outcome"] = "confirmed_numeric_release" if confirmed else "numeric_release_identity_unconfirmed"
    return outcome


def is_author_excerpt_present(text: str, excerpt: str) -> bool:
    def normalize(value: str) -> str:
        return " ".join(re.findall(r"\w+", value.casefold()))

    return f" {normalize(excerpt)} " in f" {normalize(text)} "
