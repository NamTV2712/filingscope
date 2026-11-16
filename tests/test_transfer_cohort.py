from __future__ import annotations

import json
from copy import deepcopy

import pytest

from scripts.prepare_transfer_cohort import cohort_rows
from scripts.run_transfer_cohort import load_inputs, score_predictions
from src.evaluation.independent_final import ARMS, Question
from src.retrieval.canonical_json import canonical_sha256, sha256_file


def test_authored_cohort_has_balanced_source_bound_operands():
    questions, labels = cohort_rows()
    assert len(questions) == len(labels) == 24
    assert len({q["case_id"] for q in questions}) == 24
    for prefix in ("F-", "CVX-"):
        selected = [row for row in labels if row["case_id"].startswith(prefix)]
        assert sum(row["category"] == "lookup" for row in selected) == 4
        assert sum(row["category"] == "percentage" for row in selected) == 4
        assert sum(not row["answerable"] for row in selected) == 4
        for row in selected:
            if row["category"] == "percentage":
                assert {fact["role"] for fact in row["evidence"]} == {"numerator", "denominator"}
                assert len({(fact["accession"], fact["column"], fact["currency"], fact["scale"]) for fact in row["evidence"]}) == 1


def test_label_free_loading_never_opens_the_missing_label_file(tmp_path):
    filing = {"document_id": "fixture", "cik": 1, "filed": "2025-02-01", "form": "10-K",
              "accession": "0000000001-25-000001", "source_url": "https://www.sec.gov/Archives/edgar/data/1/000000000125000001/fixture.htm",
              "document_sha256": "sha256:" + "a" * 64}
    corpus = {key: "sha256:" + "a" * 64 for key in ("fingerprint", "index_manifest_sha256", "embedding_manifest_sha256", "chunks_sha256", "pages_sha256", "sec_manifest_sha256")}
    corpus.update(index_id="fixture", filings=[filing])
    (tmp_path / "corpus.json").write_text(json.dumps(corpus))
    (tmp_path / "filing-inventory.json").write_text("[]")
    question = {"case_id": "fixture", "category": "lookup", "question": "What were Fixture assets?", "issuer_ciks": [1]}
    (tmp_path / "questions.jsonl").write_text(json.dumps(question))
    files = {name: sha256_file(tmp_path / name) for name in ("corpus.json", "filing-inventory.json", "questions.jsonl")}
    files["labels.jsonl"] = "sha256:" + "b" * 64
    freeze = {"files": files, "cases": 1}
    (tmp_path / "transfer-freeze.json").write_text(json.dumps(freeze))
    _, _, questions = load_inputs(tmp_path, sha256_file(tmp_path / "transfer-freeze.json"))
    assert questions[0].case_id == "fixture"
    assert not (tmp_path / "labels.jsonl").exists()
    with pytest.raises(ValueError, match="hash mismatch"):
        load_inputs(tmp_path, "sha256:" + "c" * 64)


def test_scoring_requires_complete_membership_and_real_citation_markers():
    question = Question(case_id="fixture", category="lookup", question="What were Fixture assets?", issuer_ciks=(1,))
    label = {"case_id": "fixture", "category": "lookup", "answerable": True, "value": "12000000", "kind": "amount", "evidence": [{"source": "fixture#p0"}]}
    observed = {"answer": "Assets were USD 12 million. [Source 1]", "disposition": "VERIFIED", "citation_sources": ["fixture#p0"], "latency_ms": 1.0}
    predictions = {arm: {"fixture": dict(observed)} for arm in ARMS}
    assert score_predictions([question], [label], predictions)["results"][ARMS[0]]["overall"]["numeric_and_locator_correct"] == 1
    predictions[ARMS[0]]["fixture"]["answer"] = "Assets were USD 12 million. [Source 2]"
    assert score_predictions([question], [label], predictions)["results"][ARMS[0]]["overall"]["numeric_and_locator_correct"] == 0
    predictions[ARMS[0]] = {}
    with pytest.raises(ValueError, match="all frozen IDs"):
        score_predictions([question], [label], predictions)


def test_grounded_review_binds_answer_and_both_operand_cells():
    question = Question(case_id="fixture", category="percentage", question="What percentage were assets?", issuer_ciks=(1,))
    evidence = [{"source": "fixture#p0", "role": role, "raw_value": value, "row": row}
                for role, value, row in (("numerator", "3", "cash"), ("denominator", "12", "assets"))]
    label = {"case_id": "fixture", "category": "percentage", "answerable": True, "value": "25", "kind": "percent", "evidence": evidence}
    observed = {"answer": "Cash was 25% of assets. [Source 1]", "disposition": "VERIFIED", "citation_sources": ["fixture#p0"], "latency_ms": 1.0}
    predictions = {arm: {"fixture": dict(observed)} for arm in ARMS}
    review = {"reviewer": "internal source reviewer", "answer_sha256": canonical_sha256(observed["answer"]),
              "grounded_correct": True, "all_atomic_claims_supported": True, "checked_evidence": deepcopy(evidence)}
    reviews = {ARMS[0]: {"fixture": review}}
    report = score_predictions([question], [label], predictions, reviews=reviews)
    assert report["results"][ARMS[0]]["overall"]["source_reviewed_grounded_correct"] == 1
    assert report["results"][ARMS[1]]["overall"]["unreviewed_releases"] == 1
    review["checked_evidence"][0]["role"] = "denominator"
    with pytest.raises(ValueError, match="every frozen source cell"):
        score_predictions([question], [label], predictions, reviews=reviews)
    review["checked_evidence"] = evidence
    review["answer_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="bind the released answer"):
        score_predictions([question], [label], predictions, reviews=reviews)
