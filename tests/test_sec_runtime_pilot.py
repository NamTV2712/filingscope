"""Offline controls for the SEC pilot's labels and source inventory."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from configs.financebench import P1_EMBEDDING_REVISION
from configs.sec_runtime_pilot import AAPL_PRIOR_REVENUE, AAPL_Q_REVENUE, AAPL_YTD_REVENUE, CASES, PDFS
from scripts.run_sec_runtime_pilot import (
    _check_pdf_cell,
    _eligible_sec_locators,
    _load_manifest,
    _load_pilot_vectors,
    _pdf_ranking_metrics,
    _prepare_sec,
    _validate_track,
)
from scripts.score_sec_ranking_review import _score as score_ranking_review
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.multi_agent_ablation import AblationObservation
from src.ingestion.sec_corpus import SourceCache
from src.ingestion.sec_client import SECEdgarClient
from src.retrieval.canonical_json import canonical_json_bytes, sha256_file


def test_pilot_is_pinned_to_frozen_2025_filings():
    manifest = _load_manifest(Path(__file__).resolve().parents[1] / "docs/G2_SEC_CORPUS_MANIFEST.json")
    filings = {filing["accession_number"]: filing for filing in manifest["filings"]}
    assert len(CASES) == len({case.case_id for case in CASES}) == 26
    assert {cell.pdf for case in CASES for cell in case.cells} == set(PDFS)
    assert all("2025-01-01" <= filings[pdf.accession]["filing_date"] <= manifest["cutoff"] for pdf in PDFS)


def test_pdf_cell_checks_column_and_rejects_ambiguous_row():
    row = "Total net sales $ 94,036 $ 85,777 $ 313,695 $ 296,105"
    _check_pdf_cell(AAPL_Q_REVENUE, row)
    _check_pdf_cell(AAPL_YTD_REVENUE, row)
    with pytest.raises(ValueError, match="PDF cell differs"):
        _check_pdf_cell(replace(AAPL_Q_REVENUE, column=2), row)
    with pytest.raises(ValueError, match="PDF cell differs"):
        _check_pdf_cell(AAPL_Q_REVENUE, f"{row}\n{row}")


def test_pilot_reuse_requires_matching_ordered_chunks_and_vector_hash(tmp_path):
    path = tmp_path / "normalized-vectors.npy"
    vectors = np.array([[1., 0.], [0., 1.]], dtype=np.float32)
    np.save(path, vectors, allow_pickle=False)
    write_json_atomic(tmp_path / "report.json", {
        "chunks_sha256": "verified-order", "embedding_revision": P1_EMBEDDING_REVISION,
        "vectors_sha256": sha256_file(path),
    })
    assert np.array_equal(_load_pilot_vectors(tmp_path, chunks_hash="verified-order", rows=2, dimension=2), vectors)
    with pytest.raises(ValueError, match="reconstructed chunks"):
        _load_pilot_vectors(tmp_path, chunks_hash="changed-order", rows=2, dimension=2)
    with pytest.raises(ValueError, match="expected shape"):
        _load_pilot_vectors(tmp_path, chunks_hash="verified-order", rows=2, dimension=3)
    np.save(path, vectors[::-1], allow_pickle=False)
    with pytest.raises(ValueError, match="Frozen vector bytes differ"):
        _load_pilot_vectors(tmp_path, chunks_hash="verified-order", rows=2, dimension=2)


def test_ranking_retains_original_cutoff_and_counts_each_cell_target():
    case = replace(CASES[0], cells=(AAPL_Q_REVENUE, AAPL_YTD_REVENUE))
    locator = f"{AAPL_Q_REVENUE.pdf.name}#p{AAPL_Q_REVENUE.page}"
    misses = _pdf_ranking_metrics((case,), {case.case_id: ("other#p1",) * 10 + (locator,)})
    hits = _pdf_ranking_metrics((case,), {case.case_id: ("other#p1",) * 9 + (locator,)})
    assert misses["gold_evidence_recall_at_10"]["numerator"] == 0
    assert hits["gold_evidence_recall_at_10"]["numerator"] == hits["gold_evidence_recall_at_10"]["denominator"] == 2
    precision = hits["gold_locator_precision_at_10"]
    assert (precision["numerator"], precision["denominator"]) == (1, 2)


def test_ranking_review_rejects_unreviewed_pages_and_scores_a_valid_alternative():
    locator = f"{AAPL_Q_REVENUE.pdf.name}#p{AAPL_Q_REVENUE.page}"
    alternative = f"{AAPL_Q_REVENUE.pdf.name}#p8"
    case_id = "apple_quarter_revenue"
    row = {"case_id": case_id, "ranked_pages": [alternative]}
    sources = {"reference_sha256": "reference", "pages_sha256": "pages"}
    report = {**sources, "ranking_controls": {"ranking_only": {"dense": {"per_case": [row]}}}}
    review = {**sources, "cases": {case_id: {
        "targets": {"quarter_revenue": [locator, alternative]}, "reviewed_pages": [locator, alternative],
    }}}
    result = score_ranking_review(report, review)["results"]["dense"]
    assert result["context_precision_at_10"]["value"] == result["gold_evidence_recall_at_10"]["value"] == 1
    row["ranked_pages"].append("unreviewed#p1")
    with pytest.raises(ValueError, match="does not cover every ranked page"):
        score_ranking_review(report, review)


def test_sec_locators_require_matching_identity_and_unambiguous_value():
    cell = AAPL_PRIOR_REVENUE
    row = {"start": cell.start, "end": cell.end, "val": cell.millions_usd * 1_000_000,
           "accn": cell.pdf.accession, "form": "10-K", "filed": "2025-10-31"}
    original = {**row, "accn": cell.original_accession, "filed": "2024-11-01"}
    wrong_source = {**row, "accn": "unlabeled", "filed": "2024-12-31"}
    conflict = {**row, "val": row["val"] + 1}
    rows = [row, original, wrong_source, conflict, {**original, "start": "2024-01-01", "val": 1},
            {**original, "filed": "2026-01-01", "val": 2}]
    payload = {"facts": {"us-gaap": {cell.sec_concept: {"units": {"USD": rows}}}}}
    assert _eligible_sec_locators(cell, payload, "2025-12-31") == (f"sec:{cell.original_accession}",)


def test_sec_snapshot_matches_cache_and_excludes_later_observations(tmp_path):
    cik = 320193
    url = SECEdgarClient.COMPANY_FACTS_URL_TEMPLATE.format(cik=f"{cik:010d}")
    payload = {"cik": cik, "facts": {"us-gaap": {"Assets": {"units": {"USD": [
        {"filed": "2025-12-31", "val": 1}, {"filed": "2026-01-01", "val": 2}, {"val": 3},
    ]}}}}}

    class LocalSource:
        def fetch_bounded(self, url, *, max_bytes):
            return canonical_json_bytes(payload)

    cache_dir = tmp_path / "cache"
    _, receipt = SourceCache(cache_dir, LocalSource()).source(url, 4096)
    manifest = {"cutoff": "2025-12-31",
                "issuers": [{"ticker": "AAPL", "cik": str(cik), "company_facts": receipt}]}
    output = tmp_path / "snapshot"
    replay = _prepare_sec(manifest, cache_dir, output, {"AAPL": cik})
    assert replay.get_company_facts(cik)["facts"]["us-gaap"]["Assets"]["units"]["USD"] == [
        {"filed": "2025-12-31", "val": 1},
    ]
    with pytest.raises(ValueError, match="receipt or issuer differs"):
        _prepare_sec(manifest, cache_dir, output, {"AAPL": 1})
    write_json_atomic(output / f"CIK{cik:010d}.json", payload)
    with pytest.raises(ValueError, match="snapshot hash differs"):
        type(replay)(output, {"AAPL": cik}, latest_filed="2025-12-31")


@pytest.mark.parametrize(("track", "observation", "statements", "message"), [
    ("document_only", AblationObservation(sec_calls=1), 0, "structured"),
    ("document_only", AblationObservation(citation_sources=("sec:accession",)), 0, "structured"),
    ("structured_only", AblationObservation(retrieval_calls=1), 0, "PDF"),
    ("structured_only", AblationObservation(), 1, "PDF"),
    ("structured_only", AblationObservation(retrieved_sources=frozenset({"doc#p0"})), 0, "PDF"),
    ("hybrid", AblationObservation(llm_calls=1), 0, "hosted"),
])
def test_tracks_detect_disallowed_sources(track, observation, statements, message):
    with pytest.raises(RuntimeError, match=message):
        _validate_track(track, observation, statements)
