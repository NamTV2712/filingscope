"""A local filing workspace and a frozen runner share verified source artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path
from threading import Thread

import numpy as np
import pytest

from configs.financebench import P1_EMBEDDING_REVISION
from scripts.run_local_research import LocalResearchServer
from src.local_research import public_result
from src.retrieval.canonical_json import canonical_sha256, sha256_file
from src.retrieval.frozen_artifacts import corpus_fingerprint
from src.runtime.filing_bundle import load_filing_runtime
from src.runtime.filing_models import Corpus, Filing


def test_runtime_import_does_not_load_benchmark_cases_or_labels():
    code = (
        "import sys; import src.runtime.filing_bundle; "
        "blocked = {'configs.multi_agent_ablation', 'configs.specialist_architectures', "
        "'src.evaluation.independent_final', 'scripts.run_multi_agent_ablation'}; "
        "assert not blocked.intersection(sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return sha256_file(path)


def _rows(path, values):
    path.write_text("\n".join(json.dumps(value) for value in values), encoding="utf-8")
    return sha256_file(path)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    from src.retrieval import embedder

    class FixtureEmbedder:
        def __init__(self, **kwargs):
            assert kwargs == {"device": "cpu", "revision": P1_EMBEDDING_REVISION}

        def embed_query(self, text):
            return np.array([1, 0])

    monkeypatch.setattr(embedder, "Embedder", FixtureEmbedder)
    for directory in ("index", "filings", "sec"):
        (tmp_path / directory).mkdir()
    pdf = tmp_path / "filings/fixture.pdf"
    pdf.write_bytes(b"fixture PDF rendition")
    filing = Filing(document_id="fixture", cik=1234567, filed="2025-02-10", form="10-K",
                    accession="0001234567-25-000001",
                    source_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456725000001/fixture.htm",
                    document_sha256=sha256_file(pdf))
    chunk = {"chunk_id": "fixture_p0", "document_id": "fixture", "doc_name": "fixture", "cik": "1234567",
             "company": "Fixture", "doc_type": "10-K", "reporting_periods": [2024],
             "source_url": filing.source_url, "accession_number": filing.accession,
             "filing_date": "2025-02-10", "page_number": 0, "section": "document", "token_count": 8,
             "text": "We operate in the electronics industry."}
    index = tmp_path / "index"
    chunks_hash = _rows(index / "corpus_chunks.jsonl", [chunk])
    fingerprint = corpus_fingerprint([chunk])
    vectors_hash = _rows(index / "embedded_chunks.jsonl", [{"chunk_id": chunk["chunk_id"], "embedding": [1, 0]}])
    embedding = {"embedding_model_id": embedder.MODEL_NAME, "embedding_model_revision": P1_EMBEDDING_REVISION,
                 "corpus_fingerprint": fingerprint, "embedded_file_sha256": vectors_hash, "vector_dimension": 2}
    embedding_hash = _write(index / "embedding_manifest.json", embedding)
    index_hash = _write(index / "index_manifest.json", {"index_id": "fixture_index", "corpus_fingerprint": fingerprint,
                        "point_count": 1, "embedding_manifest_sha256": canonical_sha256(embedding)})
    pages_hash = _rows(tmp_path / "pages.jsonl", [{"doc_name": "fixture", "page_number": 0, "text": chunk["text"]}])
    sec_hash = _write(tmp_path / "sec/manifest.json", {"latest_filed": "2025-12-31", "issuers": {}})
    corpus = Corpus(index_id="fixture_index", fingerprint=fingerprint, index_manifest_sha256=index_hash,
                    embedding_manifest_sha256=embedding_hash, chunks_sha256=chunks_hash, pages_sha256=pages_hash,
                    sec_manifest_sha256=sec_hash, filings=(filing,))
    _write(tmp_path / "corpus.json", corpus.model_dump(mode="json"))
    return tmp_path, corpus


def test_empty_company_facts_bundle_has_shared_http_and_graph_output(bundle):
    directory, corpus = bundle
    runtime = load_filing_runtime(directory)
    assert runtime.corpus == corpus and runtime.sec.issuers == {}
    assert runtime.cutoff == "2025-12-31"
    assert runtime.documents == {"fixture": directory / "filings/fixture.pdf"}
    question = "What industry did Fixture operate in according to its FY2024 10-K?"
    expected = public_result(runtime.graph.run(question))
    with LocalResearchServer(0, runtime.graph, filing_runtime=runtime) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            request = urllib.request.Request(server.url + "/api/research",
                                            data=json.dumps({"question": question}).encode(),
                                            headers={"Content-Type": "application/json", "Origin": server.url})
            with urllib.request.urlopen(request, timeout=10) as response:
                actual = [json.loads(line) for line in response if line.strip()][-1]["result"]
        finally:
            server.shutdown()
            worker.join(timeout=10)
    assert actual["status"] == expected["status"] == "VERIFIED"
    assert actual["answer"] == expected["answer"]
    fields = ("document", "page", "url", "metric", "value")
    assert [{key: row[key] for key in fields} for row in actual["sources"]] == [
        {key: row[key] for key in fields} for row in expected["sources"]
    ]


@pytest.mark.parametrize("relative", ["filings/fixture.pdf", "pages.jsonl", "index/embedded_chunks.jsonl",
                                    "index/corpus_chunks.jsonl", "index/embedding_manifest.json", "sec/manifest.json"])
def test_changed_source_or_index_artifact_fails_before_research(bundle, relative):
    directory, _ = bundle
    path = directory / relative
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        load_filing_runtime(directory)


def test_requested_cutoff_must_equal_pinned_snapshot(bundle):
    directory, _ = bundle
    with pytest.raises(ValueError, match="cutoff"):
        load_filing_runtime(directory, cutoff="2025-11-30")


def test_rehashed_chunk_with_other_accession_fails_provenance_check(bundle):
    directory, corpus = bundle
    chunk_path = directory / "index/corpus_chunks.jsonl"
    chunk = json.loads(chunk_path.read_text())
    chunk["accession_number"] = "0001234567-25-000002"
    changed_hash = _rows(chunk_path, [chunk])
    # The text fingerprint deliberately omits accession metadata. The loader
    # must therefore check it against the independent filing identity too.
    with pytest.raises(ValueError, match="provenance"):
        load_filing_runtime(directory, corpus=corpus.model_copy(update={"chunks_sha256": changed_hash}))


def test_filing_after_snapshot_cutoff_is_rejected(bundle):
    directory, corpus = bundle
    filing = corpus.filings[0].model_copy(update={"filed": date(2026, 1, 1)})
    with pytest.raises(ValueError):
        load_filing_runtime(directory, corpus=corpus.model_copy(update={"filings": (filing,)}))


def test_inventory_company_and_period_must_match_indexed_metadata(bundle):
    directory, corpus = bundle
    entry = {**corpus.filings[0].model_dump(mode="json"), "company": "Other Issuer", "ticker": None, "fiscal_year": 2024}
    _write(directory / "filing-inventory.json", [entry])
    with pytest.raises(ValueError, match="company or fiscal year"):
        load_filing_runtime(directory)
    entry["company"] = "Fixture"
    entry["fiscal_year"] = 2023
    _write(directory / "filing-inventory.json", [entry])
    with pytest.raises(ValueError, match="company or fiscal year"):
        load_filing_runtime(directory)


def test_pinned_embedding_revision_is_required_even_if_artifact_hashes_match(bundle):
    directory, corpus = bundle
    embedding_path = directory / "index/embedding_manifest.json"
    embedding = json.loads(embedding_path.read_text())
    embedding["embedding_model_revision"] = "different-revision"
    embedding_hash = _write(embedding_path, embedding)
    with pytest.raises(ValueError, match="pinned Nomic"):
        load_filing_runtime(directory, corpus=corpus.model_copy(update={"embedding_manifest_sha256": embedding_hash}))
