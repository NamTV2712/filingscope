from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from datetime import date

import pytest
import numpy as np

from scripts import run_independent_final
from src.evaluation.independent_final import (
    ARMS, CATEGORIES, Corpus, Filing, Freeze, Label, Membership, Question, ReleaseRiskCriteria,
    check_membership, score_cohort,
)
from src.evaluation.independent_primary import ReviewedPredictions, score_reviewed_predictions
from src.evaluation.multi_agent_ablation import AblationObservation
from src.evaluation.prediction_receipt import PredictionReceipt
from src.retrieval.canonical_json import canonical_sha256, sha256_file
from src.retrieval.frozen_artifacts import corpus_fingerprint


CIK = 1234567
OTHER_CIK = 2345678
CHECKSUM = "sha256:" + "a" * 64
GIT_SHA = "b" * 40
DATE = date(2025, 3, 1)
LOCATOR = "fixture_filing#p0"


@pytest.fixture
def bundle(tmp_path):
    filing = Filing(document_id="fixture_filing", cik=CIK, filed=DATE, form="10-K", accession="0001234567-25-000001",
                    source_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456725000001/fixture.htm",
                    document_sha256=CHECKSUM)
    corpus = Corpus(index_id="fixture_index", fingerprint=CHECKSUM, index_manifest_sha256=CHECKSUM,
                    embedding_manifest_sha256=CHECKSUM, chunks_sha256=CHECKSUM, pages_sha256=CHECKSUM,
                    sec_manifest_sha256=CHECKSUM, filings=(filing,))
    exposed = [Membership(cohort="fixture_exposed", issuer_ciks=(99,), document_ids=("exposed",), through=date(2024, 12, 31))]
    questions = [Question(case_id=category, category=category, question="What did Fixture report?",
                          issuer_ciks=(CIK, OTHER_CIK) if category == "multi_company" else (CIK,))
                 for category in sorted(CATEGORIES)]
    other = Filing(document_id="second_filing", cik=OTHER_CIK, filed=DATE, form="10-K", accession="0002345678-25-000001",
                   source_url="https://www.sec.gov/Archives/edgar/data/2345678/000234567825000001/fixture.htm",
                   document_sha256=CHECKSUM)
    corpus = corpus.model_copy(update={"filings": (filing, other)})
    labels = [Label.model_validate({"case_id": q.case_id, "reviewers": ["first", "second"], "adjudication": "fixture",
                                   "intended_path": "FAST", "claims": [] if q.category == "unanswerable" else [{
                                       **({"statement": "Fixture operates in the electronics industry"}
                                          if q.category == "narrative" else {"value": "USD 10 million", "terms": ["fixture", "revenue"]}),
                                       "source_slots": [[LOCATOR]], "provenance": "fixture only",
                                   }]}) for q in questions]
    for name, rows in (("exposed", exposed), ("questions", questions), ("labels", labels)):
        (tmp_path / f"{name}.jsonl").write_text("\n".join(row.model_dump_json() for row in rows), encoding="utf-8")
    (tmp_path / "corpus.json").write_text(corpus.model_dump_json(), encoding="utf-8")
    freeze = Freeze(reviewer="fixture reviewer", git_sha=GIT_SHA, selection_seed=1, bootstrap_seed=2,
                    filing_from=date(2025, 1, 1), filing_through=date(2025, 12, 31), forms=("10-K",),
                    category_minimums=dict.fromkeys(CATEGORIES, 1), dataset_license="fixture",
                    adjudication="fixture", success_criteria="fixture",
                    exposed_membership_sha256=sha256_file(tmp_path / "exposed.jsonl"),
                    corpus_sha256=sha256_file(tmp_path / "corpus.json"), questions_sha256=sha256_file(tmp_path / "questions.jsonl"),
                    labels_sha256=sha256_file(tmp_path / "labels.jsonl"), python_version="3.12.7",
                    dependencies={"numpy": "fixture"})
    (tmp_path / "freeze.json").write_text(freeze.model_dump_json(), encoding="utf-8")
    return tmp_path, freeze, exposed, corpus, questions, labels


def _predictions(questions):
    results = {}
    for q in questions:
        answer = "Fixture reported revenue of USD 10 million. [Source 1]"
        if q.category == "narrative":
            answer = "Fixture operates in the electronics industry. [Source 1]"
        elif q.category == "unanswerable":
            answer = ""
        observation = AblationObservation(answer=answer, disposition="VERIFIED" if answer else "ABSTAIN",
                                          citation_sources=(LOCATOR,) if answer else ())
        results[q.case_id] = {**asdict(observation), "retrieved_sources": [LOCATOR] if answer else [], "latency_ms": 10}
    return {arm: {case_id: dict(row) for case_id, row in results.items()} for arm in ARMS}


def test_final_membership_rejects_leakage(bundle):
    _, freeze, exposed, corpus, questions, _ = bundle
    check_membership(freeze, exposed, corpus, questions)
    with pytest.raises(ValueError, match="overlaps an exposed issuer"):
        check_membership(freeze, [exposed[0].model_copy(update={"issuer_ciks": (CIK,)})], corpus, questions)
    with pytest.raises(ValueError, match="form or date window"):
        old = corpus.filings[0].model_copy(update={"filed": date(2024, 12, 31)})
        check_membership(freeze, exposed, corpus.model_copy(update={"filings": (old, *corpus.filings[1:])}), questions)


def test_blind_preflight_leaves_labels_unopened(bundle, monkeypatch):
    root, _, _, _, _, _ = bundle
    (root / "labels.jsonl").rename(root / "held-by-reviewer.jsonl")
    monkeypatch.setattr(run_independent_final, "_git", lambda *args: GIT_SHA if args == ("rev-parse", "HEAD") else "")
    monkeypatch.setattr("sys.argv", ["runner", "preflight", "--bundle", str(root), "--freeze-sha256", sha256_file(root / "freeze.json")])
    assert run_independent_final.main() == 0
    (root / "questions.jsonl").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="questions.jsonl"):
        run_independent_final.main()


def test_score_verifies_committed_receipt_before_reading_labels(bundle, monkeypatch):
    bundle_root, freeze, _, _, questions, _ = bundle
    repo = bundle_root / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    def git(*args):
        return subprocess.check_output(["git", *args], encoding="utf-8").strip()

    git("init", "--quiet")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.com")
    (repo / ".gitignore").write_text("data/\n", encoding="utf-8")
    git("add", ".gitignore")
    git("commit", "-qm", "Freeze runtime")
    frozen_git = git("rev-parse", "HEAD")
    freeze = freeze.model_copy(update={"git_sha": frozen_git, "require_committed_prediction_receipt": True})
    freeze_path = bundle_root / "freeze.json"
    freeze_path.write_text(freeze.model_dump_json(), encoding="utf-8")
    freeze_hash = sha256_file(freeze_path)
    predictions = bundle_root / "predictions.json"
    predictions.write_text(json.dumps({"git_sha": frozen_git, "freeze_sha256": freeze_hash,
                                       "python": freeze.python_version, "dependencies": freeze.dependencies,
                                       "predictions": _predictions(questions)}), encoding="utf-8")
    prediction_hash = sha256_file(predictions)
    receipt = PredictionReceipt(git_sha=frozen_git, freeze_sha256=freeze_hash, predictions_sha256=prediction_hash)
    labels = bundle_root / "labels.jsonl"
    held = bundle_root / "held.jsonl"
    labels.rename(held)
    common = ["--bundle", str(bundle_root), "--freeze-sha256", freeze_hash,
              "--predictions", str(predictions), "--predictions-sha256", prediction_hash]
    monkeypatch.setattr("sys.argv", ["runner", "receipt", *common])
    assert run_independent_final.main() == 0
    git("add", receipt.git_path)
    git("commit", "-qm", "Record prediction hash before label release")
    receipt_commit = git("rev-parse", "HEAD")
    score_args = ["runner", "score", *common, "--output", "data/scored.json"]
    git("checkout", "--quiet", "--detach", frozen_git)
    monkeypatch.setattr("sys.argv", score_args)
    with pytest.raises(SystemExit, match="2"):
        run_independent_final.main()

    (repo / receipt.git_path).parent.mkdir(exist_ok=True)
    (repo / receipt.git_path).write_text(receipt.model_dump_json(), encoding="utf-8")
    (repo / "unrelated.txt").write_text("changed code", encoding="utf-8")
    git("add", receipt.git_path, "unrelated.txt")
    git("commit", "-qm", "Receipt with an unrelated change")
    monkeypatch.setattr("sys.argv", [*score_args, "--prediction-receipt-commit", git("rev-parse", "HEAD")])
    with pytest.raises(ValueError, match="must add only the hash receipt"):
        run_independent_final.main()

    git("checkout", "--quiet", "--detach", frozen_git)
    wrong = receipt.model_copy(update={"predictions_sha256": CHECKSUM})
    (repo / receipt.git_path).parent.mkdir(exist_ok=True)
    (repo / receipt.git_path).write_text(wrong.model_dump_json(), encoding="utf-8")
    git("add", receipt.git_path)
    git("commit", "-qm", "Receipt for different prediction bytes")
    monkeypatch.setattr("sys.argv", [*score_args, "--prediction-receipt-commit", git("rev-parse", "HEAD")])
    with pytest.raises(ValueError, match="differs from the supplied hashes"):
        run_independent_final.main()

    git("checkout", "--quiet", "--detach", receipt_commit)
    held.rename(labels)
    monkeypatch.setattr("sys.argv", [*score_args, "--prediction-receipt-commit", receipt_commit])
    assert run_independent_final.main() == 0
    scored = json.loads((repo / "data/scored.json").read_bytes())
    assert scored["prediction_receipt_commit"] == receipt_commit and scored["predictions_sha256"] == prediction_hash
    assert scored["arms"]["C_routed"]["overall"]["grounded_exact_answers"] == 7


def test_final_scoring_requires_complete_supported_numeric_and_narrative_claims(bundle):
    _, freeze, _, corpus, questions, labels = bundle
    predictions = _predictions(questions)
    predictions["B_adaptive"]["narrative"]["answer"] += " Fixture is the market leader. [Source 1]"
    predictions["B_adaptive"]["lookup"]["citation_sources"] = ("unrelated#p0",)
    result = score_cohort(freeze, corpus, questions, labels, predictions)
    assert result["arms"]["C_routed"]["overall"]["grounded_exact_answers"] == 7
    assert result["arms"]["C_routed"]["overall"]["numeric_exact_accuracy"] == 1
    assert result["arms"]["B_adaptive"]["overall"]["grounded_exact_answers"] == 5
    assert result["paired_grounded_exact"]["grounded_exact_delta"] == pytest.approx(2 / 7)
    assert result["arms"]["B_adaptive"]["by_category"]["narrative"]["unsupported_answer_rate"] == 1
    assert result["arms"]["C_routed"]["by_category"]["unanswerable"]["unsupported_release"]["value"] is None
    with pytest.raises(ValueError, match="IDs must match"):
        score_cohort(freeze, corpus, questions, labels[:-1], predictions)


def test_predict_runs_both_workflows_without_label_file(bundle, monkeypatch):
    from configs.financebench import P1_EMBEDDING_REVISION
    from src.retrieval import embedder

    root, freeze, _, corpus, _, _ = bundle
    (root / "labels.jsonl").rename(root / "held-by-reviewer.jsonl")
    for name in ("index", "filings", "sec"):
        (root / name).mkdir()

    filings = []
    chunks = []
    for filing, company in zip(corpus.filings, ("Fixture", "Other Issuer"), strict=True):
        pdf = root / "filings" / f"{filing.document_id}.pdf"
        pdf.write_bytes(b"fixture rendition")
        filings.append(filing.model_copy(update={"document_sha256": sha256_file(pdf)}))
        chunks.append({"chunk_id": filing.document_id, "document_id": filing.document_id, "doc_name": filing.document_id,
                       "cik": str(filing.cik), "company": company, "doc_type": "10-K", "reporting_periods": [2024],
                       "source_url": filing.source_url, "text": "We operate in the electronics industry.", "page_number": 0})

    def write(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")
        return sha256_file(path)

    def write_rows(path, rows):
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        return sha256_file(path)

    index = root / "index"
    fingerprint = corpus_fingerprint(chunks)
    chunks_sha = write_rows(index / "corpus_chunks.jsonl", chunks)
    vectors_sha = write_rows(index / "embedded_chunks.jsonl", ({"chunk_id": row["chunk_id"], "embedding": [1, 0]} for row in chunks))
    embedding_manifest = {"embedding_model_id": embedder.MODEL_NAME, "embedding_model_revision": P1_EMBEDDING_REVISION,
                          "corpus_fingerprint": fingerprint, "embedded_file_sha256": vectors_sha, "vector_dimension": 2}
    embed_sha = write(index / "embedding_manifest.json", embedding_manifest)
    index_sha = write(index / "index_manifest.json", {"index_id": corpus.index_id, "corpus_fingerprint": fingerprint,
                     "point_count": 2, "embedding_manifest_sha256": canonical_sha256(embedding_manifest)})
    pages_sha = write_rows(root / "pages.jsonl", ({"doc_name": row["doc_name"], "page_number": 0, "text": row["text"]} for row in chunks))
    sec_sha = write(root / "sec/manifest.json", {"latest_filed": freeze.filing_through.isoformat(), "issuers": {}})
    corpus = corpus.model_copy(update={"filings": tuple(filings), "fingerprint": fingerprint, "chunks_sha256": chunks_sha,
                                        "index_manifest_sha256": index_sha, "embedding_manifest_sha256": embed_sha,
                                        "pages_sha256": pages_sha, "sec_manifest_sha256": sec_sha})

    class FixtureEmbedder:
        def __init__(self, **kwargs):
            assert kwargs == {"device": "cpu", "revision": P1_EMBEDDING_REVISION}

        def embed_query(self, text):
            return np.array([1, 0])

    monkeypatch.setattr(embedder, "Embedder", FixtureEmbedder)
    question = Question(case_id="fixture", category="narrative", issuer_ciks=(CIK,),
                        question="What industry did Fixture operate in according to its FY2024 10-K?")
    report = run_independent_final._predict(root, freeze, corpus, [question])
    assert report["predictions"]["C_routed"]["fixture"]["disposition"] == "VERIFIED"
    assert report["predictions"]["B_adaptive"]["fixture"]["citation_sources"] == (LOCATOR,)
    assert all(arm["fixture"]["llm_calls"] == 0 for arm in report["predictions"].values())
    assert all(arm["fixture"]["pdf_ranked_pages"] == (LOCATOR,) for arm in report["predictions"].values())


def test_semantic_scoring_binds_labels_to_the_frozen_output(bundle, monkeypatch):
    root, freeze, _, corpus, questions, labels = bundle
    criteria = ReleaseRiskCriteria(minimum_coverage=0.5, maximum_incorrect_release=0.05)
    freeze = freeze.model_copy(update={"release_risk_criteria": criteria})
    (root / "freeze.json").write_text(freeze.model_dump_json(), encoding="utf-8")
    predictions = _predictions(questions)
    predictions["C_routed"]["narrative"]["answer"] = "Fixture's business is in electronics. [Source 1]"
    predictions["B_adaptive"]["lookup"]["citation_sources"] = [None]
    for arm in ARMS:
        predictions[arm]["lookup"]["pdf_ranked_pages"] = [LOCATOR] * 2 + ["second_filing#p0"]
    report_path = root / "predictions.json"
    report_path.write_text(json.dumps({
        "git_sha": freeze.git_sha, "freeze_sha256": sha256_file(root / "freeze.json"),
        "python": freeze.python_version, "dependencies": freeze.dependencies, "predictions": predictions,
    }), encoding="utf-8")
    primary = {
        "schema_version": "filingscope-reviewed-predictions-v1", "reviewers": ["semantic reviewer"],
        "freeze_sha256": sha256_file(root / "freeze.json"), "predictions_sha256": sha256_file(report_path),
        "arms": {name: [] for name in ARMS},
    }
    for arm, rows in primary["arms"].items():
        for question, label in zip(questions, labels, strict=True):
            answered = bool(label.claims)
            numeric = answered and question.category != "narrative"
            judgment = {"case_id": question.case_id, "answerable": answered,
                        "released": answered, "numeric_applicable": numeric}
            if answered and question.category != "revision":
                support = arm != "B_adaptive" or question.category != "lookup"
                judgment.update(answer_exact=True, claims=[{
                    "claim_id": "claim-1", "supported_by_context": True, "supported_by_citation_set": support,
                    "citations": [{"citation_id": "Source 1", "supports_claim": support}],
                }])
                if numeric:
                    judgment["numeric_checks"] = {**dict.fromkeys(
                        ["values", "company", "metric", "period", "currency", "scale", "reporting_basis"], True,
                    ), "calculation": None}
            if question.category == "lookup":
                judgment["retrieval"] = {"granularity": "page", "ranked_ids": predictions[arm]["lookup"]["pdf_ranked_pages"],
                                         "relevant_ids": [LOCATOR], "gold_targets": {"target": [LOCATOR]}}
            rows.append(judgment)
    adjudications = root / "adjudications.json"
    adjudications.write_text(json.dumps(primary), encoding="utf-8")
    output = root / "data/report.json"
    monkeypatch.setattr(run_independent_final, "_git", lambda *args: {
        ("rev-parse", "--show-toplevel"): str(root), ("rev-parse", "HEAD"): GIT_SHA,
        ("status", "--porcelain"): "",
    }.get(args, str(output)))
    monkeypatch.setattr("sys.argv", [
        "runner", "score", "--bundle", str(root), "--freeze-sha256", primary["freeze_sha256"],
        "--predictions", str(report_path), "--predictions-sha256", primary["predictions_sha256"],
        "--adjudications", str(adjudications), "--adjudications-sha256", sha256_file(adjudications),
        "--output", str(output),
    ])
    assert run_independent_final.main() == 0
    result = json.loads(output.read_bytes())
    assert result["adjudications_sha256"] == sha256_file(adjudications)
    assert result["arms"]["C_routed"]["overall"]["grounded_exact_answers"] == 6
    strict = result["primary_adjudication"]
    routed = strict["arms"]["C_routed"]
    assert routed["primary"]["grounded_exact_accuracy"]["numerator"] == 6
    assert routed["primary"]["grounded_exact_accuracy"]["denominator"] == 6
    assert routed["primary"]["numeric_exact_accuracy"]["denominator"] == 5
    assert routed["retrieval_by_granularity"]["page"]["context_precision_at_10"]["value"] == 0.5
    assert routed["retrieval_by_granularity"]["page"]["gold_evidence_recall_at_10"]["value"] == 1
    assert routed["release_risk_intervals"]["all_releases_worst_case"]["numerator"] == 1
    assert routed["release_risk_gate"]["status"] == "INCONCLUSIVE"
    assert routed["release_risk_gate"]["best_case_risk"] == 0
    assert routed["release_risk_gate"]["worst_case_risk"] == pytest.approx(1 / 7)
    assert strict["arms"]["B_adaptive"]["release_risk_gate"]["status"] == "DOES_NOT_MEET"
    assert strict["arms"]["B_adaptive"]["primary"]["claim_faithfulness"]["value"] == 1
    assert strict["arms"]["B_adaptive"]["primary"]["citation_support_precision"]["numerator"] == 5
    assert strict["paired_grounded_exact"]["grounded_exact_delta"] == pytest.approx(1 / 6)

    reviewed = ReviewedPredictions.model_validate_json(adjudications.read_bytes())
    kwargs = {"freeze_sha256": primary["freeze_sha256"], "predictions_sha256": primary["predictions_sha256"]}
    with pytest.raises(ValueError, match="different freeze or prediction"):
        score_reviewed_predictions(freeze, questions, labels, predictions, reviewed,
                                   **{**kwargs, "predictions_sha256": CHECKSUM})
    wrong_rank = predictions["C_routed"]["lookup"]
    wrong_rank["pdf_ranked_pages"] = [LOCATOR]
    with pytest.raises(ValueError, match="frozen PDF ranking"):
        score_reviewed_predictions(freeze, questions, labels, predictions, reviewed, **kwargs)
    wrong_rank["pdf_ranked_pages"] = [LOCATOR] * 2 + ["second_filing#p0"]
    predictions["C_routed"]["lookup"]["citation_sources"] = [None]
    with pytest.raises(ValueError, match="unresolved citation"):
        score_reviewed_predictions(freeze, questions, labels, predictions, reviewed, **kwargs)
