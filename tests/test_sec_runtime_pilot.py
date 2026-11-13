"""Offline controls for the SEC pilot's labels and source inventory."""

from dataclasses import replace
from pathlib import Path

import pytest

from configs.sec_runtime_pilot import AAPL_PRIOR_REVENUE, AAPL_Q_REVENUE, AAPL_YTD_REVENUE, CASES, PDFS
from scripts.run_sec_runtime_pilot import (
    _check_pdf_cell,
    _eligible_sec_locators,
    _load_manifest,
    _prepare_sec,
    _validate_track,
)
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.multi_agent_ablation import AblationObservation
from src.ingestion.sec_corpus import SourceCache
from src.ingestion.sec_client import SECEdgarClient
from src.retrieval.canonical_json import canonical_json_bytes


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
