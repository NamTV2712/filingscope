"""FinanceBench evaluation labels, kept separate from runtime retrieval code."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from configs.financebench import (
    FINANCEBENCH_EXPECTED_CASES,
    SPLIT_SEED,
    SPLIT_TARGETS,
)


@dataclass(frozen=True)
class FinanceBenchCase:
    case_id: str
    company: str
    doc_name: str
    question: str
    gold_pages: tuple[int, ...]
    question_type: str
    split: str


def normalize_document_metadata(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Merge repeated document rows without discarding conflicting values."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        doc_name = row.get("doc_name")
        if not isinstance(doc_name, str) or not doc_name:
            raise ValueError("Document metadata contains an invalid doc_name")
        grouped[doc_name].append(row)

    normalized: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for doc_name in sorted(grouped):
        records = grouped[doc_name]
        value_sets = {
            field: sorted(
                {
                    str(record[field]).strip()
                    for record in records
                    if record.get(field) is not None and str(record[field]).strip()
                }
            )
            for field in ("company", "doc_type", "doc_period", "doc_link", "gics_sector")
        }
        doc_conflicts = [
            {"field": field, "values": values}
            for field, values in value_sets.items()
            if len(values) > 1
        ]
        if doc_conflicts:
            conflicts.append({"doc_name": doc_name, "conflicts": doc_conflicts})
        normalized[doc_name] = {
            "doc_name": doc_name,
            "company": value_sets["company"][0] if len(value_sets["company"]) == 1 else None,
            "company_values": value_sets["company"],
            "doc_type": value_sets["doc_type"][0] if len(value_sets["doc_type"]) == 1 else None,
            "doc_type_values": value_sets["doc_type"],
            "reporting_periods": value_sets["doc_period"],
            "doc_links": value_sets["doc_link"],
            "doc_link": value_sets["doc_link"][0] if len(value_sets["doc_link"]) == 1 else None,
            "gics_sector_values": value_sets["gics_sector"],
            "metadata_conflicts": doc_conflicts,
        }
    return normalized, conflicts


def _select_company_groups(
    group_counts: dict[str, int],
    target_count: int,
    *,
    seed: str,
) -> set[str]:
    """Select a deterministic exact-size company subset using subset sum."""
    ordered = sorted(
        group_counts,
        key=lambda company: (
            hashlib.sha256(f"{seed}:{company}".encode("utf-8")).hexdigest(),
            company,
        ),
    )
    reachable: dict[int, tuple[str, ...]] = {0: ()}
    for company in ordered:
        group_size = group_counts[company]
        for current_total, selected in sorted(
            list(reachable.items()), reverse=True
        ):
            next_total = current_total + group_size
            if next_total <= target_count and next_total not in reachable:
                reachable[next_total] = (*selected, company)
        if target_count in reachable:
            break
    if target_count not in reachable:
        raise ValueError(
            f"Cannot form an exact {target_count}-case company-grouped split"
        )
    return set(reachable[target_count])


def build_company_splits(
    cases: list[dict[str, Any]],
    *,
    targets: dict[str, int] | None = None,
    seed: str = SPLIT_SEED,
) -> dict[str, str]:
    """Assign whole companies to stable, exact-count data splits."""
    split_targets = dict(targets or SPLIT_TARGETS)
    if set(split_targets) != {"development", "validation", "held_out"}:
        raise ValueError("Split targets must define development, validation, and held_out")
    if sum(split_targets.values()) != len(cases):
        raise ValueError("Split targets must sum to the number of cases")

    counts = Counter(case["company"] for case in cases)
    if any(not isinstance(company, str) or not company for company in counts):
        raise ValueError("Every case must have a non-empty company")
    development = _select_company_groups(
        dict(counts), split_targets["development"], seed=seed
    )
    remaining = set(counts) - development
    validation_counts = {company: counts[company] for company in remaining}
    validation = _select_company_groups(
        validation_counts,
        split_targets["validation"],
        seed=f"{seed}:validation",
    )
    assignments = {
        company: "development" for company in development
    }
    assignments.update({company: "validation" for company in validation})
    assignments.update(
        {company: "held_out" for company in set(counts) - development - validation}
    )
    actual = Counter(assignments[case["company"]] for case in cases)
    if actual != Counter(split_targets):
        raise ValueError(f"Split assignment counts do not match targets: {actual}")
    return assignments


def validate_case_records(
    records: list[dict[str, Any]],
    *,
    expected_count: int | None = FINANCEBENCH_EXPECTED_CASES,
) -> None:
    if expected_count is not None and len(records) != expected_count:
        raise ValueError(f"Expected {expected_count} FinanceBench cases, found {len(records)}")
    seen_ids: set[str] = set()
    for row in records:
        case_id = row.get("financebench_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen_ids:
            raise ValueError("FinanceBench cases must have unique non-empty financebench_id values")
        seen_ids.add(case_id)
        if not all(isinstance(row.get(key), str) and row[key] for key in ("company", "doc_name", "question")):
            raise ValueError(f"FinanceBench case {case_id!r} is missing required text fields")
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"FinanceBench case {case_id!r} has no evidence list")
        for item in evidence:
            page = item.get("evidence_page_num") if isinstance(item, dict) else None
            if (
                not isinstance(page, int)
                or isinstance(page, bool)
                or page < 0
                or item.get("doc_name") != row["doc_name"]
            ):
                raise ValueError(f"FinanceBench case {case_id!r} has invalid evidence page metadata")


def load_financebench_cases(
    path: Path,
    *,
    expected_count: int | None = FINANCEBENCH_EXPECTED_CASES,
) -> list[FinanceBenchCase]:
    """Load only question/evidence labels for offline evaluation.

    Gold answers and justifications are intentionally not copied into the
    runtime corpus or the returned case objects.
    """
    records = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            records.append(record)
    validate_case_records(records, expected_count=expected_count)
    split_by_company = build_company_splits(records)
    cases = []
    for record in records:
        pages = tuple(
            sorted(
                {
                    item["evidence_page_num"]
                    for item in record["evidence"]
                }
            )
        )
        cases.append(
            FinanceBenchCase(
                case_id=record["financebench_id"],
                company=record["company"],
                doc_name=record["doc_name"],
                question=record["question"],
                gold_pages=pages,
                question_type=str(record.get("question_type") or "unknown"),
                split=split_by_company[record["company"]],
            )
        )
    return cases


def evidence_alignment_stats(
    records: list[dict[str, Any]],
    page_text_by_document: dict[str, dict[int, str]],
) -> dict[str, Any]:
    """Measure evidence-text token overlap with extracted PDF pages.

    This is a parser-quality diagnostic only. It never changes case eligibility.
    """
    evidence_count = 0
    nonempty_extractions = 0
    overlap_scores: list[float] = []
    for record in records:
        for evidence in record["evidence"]:
            evidence_count += 1
            page = evidence["evidence_page_num"]
            extracted = page_text_by_document.get(record["doc_name"], {}).get(page, "")
            full_page = str(evidence.get("evidence_text_full_page") or "")
            gold_tokens = set(full_page.casefold().split())
            extracted_tokens = set(extracted.casefold().split())
            if extracted.strip():
                nonempty_extractions += 1
            overlap = len(gold_tokens & extracted_tokens) / max(1, len(gold_tokens))
            overlap_scores.append(overlap)
    sorted_scores = sorted(overlap_scores)
    median = sorted_scores[len(sorted_scores) // 2] if sorted_scores else 0.0
    return {
        "evidence_record_count": evidence_count,
        "evidence_pages_with_extracted_text": nonempty_extractions,
        "evidence_page_text_nonempty_rate": round(
            nonempty_extractions / max(1, evidence_count), 4
        ),
        "median_full_page_token_overlap": round(median, 4),
        "mean_full_page_token_overlap": round(
            sum(overlap_scores) / max(1, len(overlap_scores)), 4
        ),
    }
