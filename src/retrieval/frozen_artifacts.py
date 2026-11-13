"""Load a verified frozen corpus without importing evaluation labels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from configs.financebench import P1_CORPUS_FINGERPRINT, P1_EMBEDDING_REVISION, P1_INDEX_ID
from src.retrieval.canonical_json import canonical_sha256, sha256_file


def corpus_fingerprint(chunks: list[dict[str, Any]]) -> str:
    fields = ("chunk_id", "company", "doc_name", "page_number", "section", "text", "token_count")
    return canonical_sha256([
        {key: chunk.get(key) for key in fields} for chunk in sorted(chunks, key=lambda item: item["chunk_id"])
    ])


def load_frozen_corpus(
    directory: Path, *, index_id: str = P1_INDEX_ID, fingerprint: str = P1_CORPUS_FINGERPRINT,
) -> list[dict[str, Any]]:
    manifest = json.loads((directory / "index_manifest.json").read_text(encoding="utf-8"))
    if manifest["index_id"] != index_id or manifest["corpus_fingerprint"] != fingerprint:
        raise ValueError("Index manifest does not match the frozen corpus identity")
    with (directory / "corpus_chunks.jsonl").open(encoding="utf-8") as handle:
        chunks = [json.loads(line) for line in handle if line.strip()]
    if len(chunks) != manifest["point_count"] or corpus_fingerprint(chunks) != fingerprint:
        raise ValueError("Chunk content or metadata differs from the frozen corpus")
    return sorted(chunks, key=lambda row: row["chunk_id"])


def load_frozen_vectors(
    directory: Path, chunks: list[dict[str, Any]], *, fingerprint: str = P1_CORPUS_FINGERPRINT,
    embedding_revision: str = P1_EMBEDDING_REVISION,
) -> np.ndarray:
    path = directory / "embedded_chunks.jsonl"
    manifest = json.loads((directory / "embedding_manifest.json").read_text(encoding="utf-8"))
    index = json.loads((directory / "index_manifest.json").read_text(encoding="utf-8"))
    if (
        manifest["corpus_fingerprint"] != fingerprint
        or manifest["embedding_model_revision"] != embedding_revision
        or index["embedding_manifest_sha256"] != canonical_sha256(manifest)
        or manifest["embedded_file_sha256"] != sha256_file(path)
    ):
        raise ValueError("Embedding artifacts do not match the frozen index")
    positions = {row["chunk_id"]: position for position, row in enumerate(chunks)}
    vectors = np.empty((len(chunks), manifest["vector_dimension"]), dtype=np.float32)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            position = positions.pop(row["chunk_id"])
            vectors[position] = row["embedding"]
    if positions or not np.isfinite(vectors).all():
        raise ValueError("Missing or invalid frozen vectors")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError("The frozen index contains a zero-length vector")
    vectors /= norms
    return vectors
