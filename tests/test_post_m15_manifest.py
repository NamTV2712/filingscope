import json
from pathlib import Path

from src.evaluation.post_m15_manifest import build_manifest


def test_manifest_binds_frozen_inputs_and_hashed_outputs(tmp_path):
    def write(name: str, value: dict) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    write("index_manifest.json", {"index_id": "generation", "corpus_fingerprint": "fingerprint"})
    write("embedding_manifest.json", {"embedding_model_revision": "embedding-revision"})
    sources = write("source_manifest.json", {
        "dataset": {"license": "CC BY-NC 4.0"},
        "files": {"source_pdfs": [{"doc_name": "report", "sha256": "sha256:document"}]},
    })
    sec = write("sec_manifest.json", {"latest_filed": "2024-12-31"})
    pages = write("pages.jsonl", {"text": "PRIVATE PAGE TEXT"})
    write("pages.json", {"pages_sha256": "sha256:pages"})
    output = write("results.json", {"case_count": 24})
    args = dict(p1_run=tmp_path, source_manifest=sources, sec_manifest=sec, pages=pages, artifacts={"q1": output})
    baseline = build_manifest(**args, configuration={"threads": 6})
    assert baseline["dataset"]["document_hashes"] == {"report": "sha256:document"}
    assert baseline["dataset"]["m13_split"] == {"development": 8, "validation": 8, "held_out": 8}
    assert baseline["retrieval"]["index"]["index_id"] == "generation"
    assert baseline["embedding"]["embedding_model_revision"] == "embedding-revision"
    assert "PRIVATE PAGE TEXT" not in json.dumps(baseline)
    assert baseline["configuration_sha256"] != build_manifest(**args, configuration={"threads": 4})["configuration_sha256"]
    output.write_text('{"case_count": 21}', encoding="utf-8")
    assert baseline["artifacts"] != build_manifest(**args, configuration={"threads": 6})["artifacts"]
