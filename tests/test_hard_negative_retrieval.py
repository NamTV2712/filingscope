from __future__ import annotations

import pytest

from configs.hard_negatives import CASES
from src.evaluation.hard_negative_retrieval import (
    HardNegative, HardNegativeCase, NegativeType, Passage, resolve_passages, score_case, summarize,
)


def _row(document: str, company: str) -> dict:
    return {
        "doc_name": document, "company": company, "page_number": 0, "chunk_index": 0,
        "text": "Cash   and Cash Equivalents", "chunk_id": document, "source_url": "https://example.org/report",
    }


def _ref(document: str) -> Passage:
    return Passage(document, 0, 0, ("cash and cash equivalents",))


def test_curated_negative_metrics_distinguish_top_k_ties_and_filtered_positives():
    originals = (_ref("original-a"), _ref("original-b"))
    negative = HardNegative(NegativeType.WRONG_REVISION, _ref("revision"))
    case = HardNegativeCase("case-1", "development", "original cash?", originals, (negative,))
    chunks = [_row(document, "Example") for document in ("original-a", "original-b", "revision", "random")]
    positions = resolve_passages((case,), chunks)

    outcome = score_case(case, positions, [2, 0, 1], [0.7, 0.4, 0.7, 0.2], random_negatives=(3,))
    assert outcome["full_at_10"] and outcome["mrr_at_10"] == 0.5
    assert outcome["known_negative_above_all_gold_at_50"]
    aggregate = summarize([outcome])
    assert aggregate["pairwise_hard"]["accuracy"] == 0.25
    assert aggregate["pairwise_by_type"]["random_control"]["accuracy"] == 1.0

    filtered = score_case(case, positions, [0], [0.7, -float("inf"), -float("inf"), 0.2])
    assert filtered["recall_at_10"] == 0.5 and not filtered["full_at_10"]
    assert filtered["pairs"]["wrong_revision"] == {"wins": 1, "ties": 0, "losses": 0, "filtered_positive_pairs": 1}


def test_passage_resolution_refuses_inaccurate_provenance_and_split_overlap():
    original, distractor = _ref("original"), _ref("unrelated")
    negative = HardNegative(NegativeType.WRONG_COMPANY, distractor)
    case = HardNegativeCase("case-1", "development", "cash?", (original,), (negative,))
    chunks = [_row("original", "Example"), _row("unrelated", "Another")]
    changed = [{**chunks[0], "text": "Net income"}, chunks[1]]
    with pytest.raises(ValueError, match="anchor changed"):
        resolve_passages((case,), changed)
    with pytest.raises(ValueError, match="Unexpected company"):
        resolve_passages((case,), [chunks[0], {**chunks[1], "company": "Example"}])
    with pytest.raises(ValueError, match="multiple judgment splits"):
        resolve_passages((case, HardNegativeCase("case-2", "held_out", "cash?", (original,), (negative,))), chunks)


def test_frozen_suite_covers_all_provenance_failures_and_separates_judged_documents():
    assert len(CASES) == 24
    assert {negative.kind for case in CASES for negative in case.negatives} == set(NegativeType)
    documents_by_split: dict[str, set[str]] = {}
    for case in CASES:
        documents = documents_by_split.setdefault(case.split, set())
        documents.update(passage.document for passage in case.evidence)
        documents.update(negative.passage.document for negative in case.negatives)
    assert set(documents_by_split) == {"development", "validation", "held_out"}
    assert sum(map(len, documents_by_split.values())) == len(set.union(*documents_by_split.values()))
