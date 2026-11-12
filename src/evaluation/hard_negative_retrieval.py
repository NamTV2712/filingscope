"""Provenance-sensitive passage judgments and retrieval scoring."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from statistics import mean
from typing import Any


class NegativeType(StrEnum):
    WRONG_COMPANY = "wrong_company"
    WRONG_PERIOD = "wrong_period"
    WRONG_METRIC = "wrong_metric"
    WRONG_DISCLOSURE = "wrong_disclosure"
    WRONG_REVISION = "wrong_revision"


@dataclass(frozen=True)
class Passage:
    document: str
    page: int
    chunk: int
    anchors: tuple[str, ...]

    @property
    def locator(self) -> tuple[str, int, int]:
        return self.document, self.page, self.chunk


@dataclass(frozen=True)
class HardNegative:
    kind: NegativeType
    passage: Passage


@dataclass(frozen=True)
class HardNegativeCase:
    case_id: str
    split: str
    question: str
    evidence: tuple[Passage, ...]
    negatives: tuple[HardNegative, ...]


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def resolve_passages(
    cases: Sequence[HardNegativeCase], chunks: Sequence[Mapping[str, Any]],
) -> dict[Passage, int]:
    index = {
        (chunk["doc_name"], chunk["page_number"], chunk["chunk_index"]): position
        for position, chunk in enumerate(chunks)
    }
    if len(index) != len(chunks) or len({chunk["chunk_id"] for chunk in chunks}) != len(chunks):
        raise ValueError("Corpus contains duplicate passage identifiers")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Hard-negative case IDs must be unique")
    result: dict[Passage, int] = {}
    document_splits = {}
    for case in cases:
        if not case.evidence or not case.negatives or not case.question.strip():
            raise ValueError(f"Incomplete judgments for {case.case_id}")
        if case.split not in {"development", "validation", "held_out"}:
            raise ValueError(f"Unknown split for {case.case_id}")
        references = (*case.evidence, *(negative.passage for negative in case.negatives))
        if len({passage.locator for passage in references}) != len(references):
            raise ValueError(f"Duplicate or overlapping judgments for {case.case_id}")
        for passage in references:
            if document_splits.setdefault(passage.document, case.split) != case.split:
                raise ValueError(f"Document appears in multiple judgment splits: {passage.document}")
            position = index.get(passage.locator)
            if position is None:
                raise ValueError(f"Passage locator is missing: {passage.locator}")
            row = chunks[position]
            if not row.get("source_url"):
                raise ValueError(f"Passage lacks a source URL: {passage.locator}")
            text = _normalized(row["text"])
            if not passage.anchors or any(_normalized(anchor) not in text for anchor in passage.anchors):
                raise ValueError(f"Passage anchor changed: {passage.locator} {passage.anchors}")
            result[passage] = position
        company = chunks[result[case.evidence[0]]]["company"]
        for negative in case.negatives:
            other = chunks[result[negative.passage]]["company"]
            if (other != company) != (negative.kind == NegativeType.WRONG_COMPANY):
                raise ValueError(f"Unexpected company for {case.case_id} {negative.passage.locator}")
    return result


def score_case(
    case: HardNegativeCase,
    passages: Mapping[Passage, int],
    ranking: Sequence[int],
    scores: Sequence[float],
    *,
    random_negatives: Sequence[int] = (),
) -> dict[str, Any]:
    gold = {passages[ref] for ref in case.evidence}
    negatives = {passages[negative.passage]: negative.kind for negative in case.negatives}
    ranks = {item: rank for rank, item in enumerate(ranking, start=1)}
    gold_ranks = sorted(ranks[item] for item in gold if item in ranks)
    negative_ranks = sorted(ranks[item] for item in negatives if item in ranks)

    def comparisons(items: Sequence[int]) -> dict[str, int]:
        wins = ties = losses = missing = 0
        for item in items:
            for positive in gold:
                if not math.isfinite(scores[positive]):
                    missing += 1
                elif scores[positive] > scores[item]:
                    wins += 1
                elif scores[positive] == scores[item]:
                    ties += 1
                else:
                    losses += 1
        return {"wins": wins, "ties": ties, "losses": losses, "filtered_positive_pairs": missing}

    dcg = sum(1 / math.log2(rank + 1) for rank in gold_ranks if rank <= 5)
    idcg = sum(1 / math.log2(rank + 1) for rank in range(1, min(5, len(gold)) + 1))
    return {
        "case_id": case.case_id,
        "split": case.split,
        "gold_ranks": gold_ranks,
        "known_negative_ranks": {str(ranks[item]): kind.value for item, kind in negatives.items() if item in ranks},
        "recall_at_5": sum(rank <= 5 for rank in gold_ranks) / len(gold),
        "recall_at_10": sum(rank <= 10 for rank in gold_ranks) / len(gold),
        "recall_at_50": sum(rank <= 50 for rank in gold_ranks) / len(gold),
        "full_at_10": sum(rank <= 10 for rank in gold_ranks) == len(gold),
        "mrr_at_10": 1 / gold_ranks[0] if gold_ranks and gold_ranks[0] <= 10 else 0.0,
        "ndcg_at_5": dcg / idcg,
        "known_negative_at_10": bool(negative_ranks and negative_ranks[0] <= 10),
        "known_negative_above_all_gold_at_50": bool(negative_ranks and (not gold_ranks or negative_ranks[0] < gold_ranks[0])),
        "pairs": {
            kind.value: comparisons([index for index, category in negatives.items() if category == kind])
            for kind in sorted(set(negatives.values()))
        },
        "random_pairs": comparisons(random_negatives),
    }


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = (
        "recall_at_5", "recall_at_10", "recall_at_50", "full_at_10", "mrr_at_10", "ndcg_at_5",
        "known_negative_at_10", "known_negative_above_all_gold_at_50",
    )
    pair_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        for category, counts in {**row["pairs"], "random_control": row["random_pairs"]}.items():
            for outcome, count in counts.items():
                pair_counts[category][outcome] += count

    def pair_metrics(counts: Mapping[str, int]) -> dict[str, int | float | None]:
        evaluated = counts["wins"] + counts["ties"] + counts["losses"]
        return {
            **counts,
            "accuracy": round((counts["wins"] + 0.5 * counts["ties"]) / evaluated, 4) if evaluated else None,
        }

    hard = {outcome: sum(counts[outcome] for category, counts in pair_counts.items() if category != "random_control")
            for outcome in ("wins", "ties", "losses", "filtered_positive_pairs")}
    return {
        "case_count": len(rows),
        **{metric: round(mean(row[metric] for row in rows), 4) if rows else None for metric in metrics},
        "pairwise_hard": pair_metrics(hard),
        "pairwise_by_type": {category: pair_metrics(counts) for category, counts in sorted(pair_counts.items())},
    }
