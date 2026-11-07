import json
from pathlib import Path

import scripts.run_financebench_retrieval as runner


class _FakeEmbedder:
    device = "cpu"
    dimension = 2
    normalize_embeddings = False

    def __init__(self):
        self.calls = 0

    def embed_documents(self, texts, batch_size, show_progress_bar):
        assert show_progress_bar is False
        self.calls += len(texts)
        return [[float(len(text)), 1.0] for text in texts]


class _FailIfCalledEmbedder(_FakeEmbedder):
    def embed_documents(self, *_args, **_kwargs):
        raise AssertionError("verified embedding cache should be reused")


def test_embedding_cache_streams_and_reuses_verified_jsonl(tmp_path: Path) -> None:
    chunks = [
        {"chunk_id": f"chunk-{index}", "text": f"Text {index}"}
        for index in range(5)
    ]
    corpus_fingerprint = runner._corpus_fingerprint(chunks)
    embedder = _FakeEmbedder()

    manifest = runner._load_or_build_embeddings(
        chunks,
        run_dir=tmp_path,
        corpus_fingerprint=corpus_fingerprint,
        embedder=embedder,
    )

    output_path = tmp_path / "embedded_chunks.jsonl"
    embedded = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert manifest["point_count"] == len(chunks)
    assert embedder.calls == len(chunks)
    assert [item["chunk_id"] for item in embedded] == [item["chunk_id"] for item in chunks]
    assert all(len(item["embedding"]) == 2 for item in embedded)

    cached = runner._load_or_build_embeddings(
        chunks,
        run_dir=tmp_path,
        corpus_fingerprint=corpus_fingerprint,
        embedder=_FailIfCalledEmbedder(),
    )
    assert cached == manifest


def test_qdrant_index_upserts_embedded_jsonl_in_bounded_batches(tmp_path, monkeypatch) -> None:
    chunks = [
        {
            "chunk_id": f"chunk-{index}",
            "company": "Synthetic Co",
            "doc_name": "SYNTHETIC_10K",
            "page_number": index,
            "section": "document",
            "text": f"Evidence {index}",
            "token_count": 2,
        }
        for index in range(260)
    ]
    embedded_path = tmp_path / "embedded_chunks.jsonl"
    embedded_path.write_text(
        "".join(
            json.dumps({**chunk, "embedding": [0.1, 0.2]}) + "\n"
            for chunk in chunks
        ),
        encoding="utf-8",
    )

    class _FakeStore:
        def __init__(self, **_kwargs):
            self.client = type(
                "Client",
                (),
                {"get_collections": lambda _self: type("Collections", (), {"collections": []})()},
            )()
            self.batches = []
            self.payloads = []

        def create_collection(self, embedding_dim):
            assert embedding_dim == 2

        def upsert_chunks(self, batch):
            self.batches.append(len(batch))
            self.payloads.extend(
                {key: value for key, value in item.items() if key != "embedding"}
                for item in batch
            )

        def get_collection_info(self):
            return {"points_count": len(self.payloads), "status": "green"}

        def load_all_chunks(self):
            return self.payloads

        def close(self):
            pass

    monkeypatch.setattr(runner, "VectorStore", _FakeStore)
    manifest = {
        "corpus_fingerprint": runner._corpus_fingerprint(chunks),
        "vector_dimension": 2,
    }
    store, index_manifest = runner._ensure_index(
        embedded_path=embedded_path,
        chunks=chunks,
        run_dir=tmp_path,
        index_id="a" * 64,
        embedding_manifest=manifest,
    )

    assert index_manifest["point_count"] == 260
    assert store.batches == [128, 128, 4]
