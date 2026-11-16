"""Build the final evaluation's label-free corpus from local filing PDFs."""

from __future__ import annotations

import argparse
import json
from datetime import date
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import Field, TypeAdapter

from configs.financebench import P1_EMBEDDING_REVISION
from configs.offline_guard import offline_socket_guard
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.company_facts_replay import CompanyFactsReplay
from src.evaluation.independent_final import Corpus, Filing, Nonempty
from src.ingestion.pdf_ingestion import chunk_pdf_pages, extract_pdf_pages
from src.retrieval.canonical_json import canonical_json_bytes, canonical_sha256, sha256_file
from src.retrieval.frozen_artifacts import corpus_fingerprint


class FilingInput(Filing):
    company: Nonempty
    ticker: Nonempty | None = None
    fiscal_year: int = Field(ge=1900, le=2199)


def _write_rows(path: Path, rows) -> None:
    with path.open("wb") as output:
        for row in rows:
            output.write(canonical_json_bytes(row) + b"\n")


def _make_index(staging: Path, chunks: list[dict], embedder) -> tuple[str, str]:
    index = staging / "index"
    index.mkdir()
    fingerprint = corpus_fingerprint(chunks)
    _write_rows(index / "corpus_chunks.jsonl", chunks)

    def embedded_rows():
        import numpy as np

        for offset in range(0, len(chunks), 8):
            batch = chunks[offset:offset + 8]
            vectors = embedder.embed_documents([row["text"] for row in batch], batch_size=8, show_progress_bar=False)
            matrix = np.asarray(vectors, dtype=np.float32)
            if (matrix.shape != (len(batch), embedder.dimension) or not np.isfinite(matrix).all()
                    or (np.linalg.norm(matrix, axis=1) == 0).any()):
                raise ValueError("The pinned model returned invalid document vectors")
            for row, vector in zip(batch, matrix.tolist(), strict=True):
                yield {"chunk_id": row["chunk_id"], "embedding": vector}

    vector_path = index / "embedded_chunks.jsonl"
    _write_rows(vector_path, embedded_rows())
    embedding = {
        "corpus_fingerprint": fingerprint, "point_count": len(chunks),
        "embedding_model_id": embedder.model_name, "embedding_model_revision": embedder.model_revision,
        "vector_dimension": embedder.dimension, "document_prefix": "search_document: ",
        "normalize_embeddings": False, "compute_device": embedder.device,
        "embedded_file_sha256": sha256_file(vector_path),
        "sentence_transformers_version": version("sentence-transformers"), "torch_version": version("torch"),
    }
    write_json_atomic(index / "embedding_manifest.json", embedding)
    manifest = {"schema_version": 1, "point_count": len(chunks), "distance_metric": "cosine",
                "corpus_fingerprint": fingerprint, "embedding_manifest_sha256": canonical_sha256(embedding)}
    index_id = canonical_sha256(manifest).removeprefix("sha256:")
    write_json_atomic(index / "index_manifest.json", {**manifest, "index_id": index_id})
    return index_id, fingerprint


def prepare(bundle: Path, filings: list[FilingInput], cutoff: date, embedder) -> Corpus:
    if not filings or len({row.document_id for row in filings}) != len(filings) or len({row.accession for row in filings}) != len(filings):
        raise ValueError("Supply a nonempty, unique filing inventory")
    if any(row.filed > cutoff for row in filings):
        raise ValueError("A filing date exceeds the snapshot cutoff")
    if any((bundle / name).exists() for name in ("index", "pages.jsonl", "corpus.json", "freeze.json")):
        raise ValueError("Use a fresh bundle directory for generated artifacts")
    sec_dir = bundle / "sec"
    sec_manifest = sec_dir / "manifest.json"
    if sec_dir.exists() and not sec_manifest.is_file():
        raise ValueError("The existing SEC directory requires a Company Facts manifest")
    if sec_manifest.is_file():
        sec = json.loads(sec_manifest.read_text(encoding="utf-8"))
        issuers = {ticker: record["cik"] for ticker, record in sec["issuers"].items()}
        if set(issuers.values()) - {row.cik for row in filings}:
            raise ValueError("SEC snapshots include issuers outside the filing inventory")
        CompanyFactsReplay(sec_dir, issuers, latest_filed=cutoff.isoformat())

    chunks = []
    pages = []
    for filing in sorted(filings, key=lambda row: row.document_id):
        path = bundle / "filings" / f"{filing.document_id}.pdf"
        if sha256_file(path) != filing.document_sha256:
            raise ValueError(f"PDF does not match the source inventory: {filing.document_id}")
        extracted = extract_pdf_pages(path)
        source_chunks, _ = chunk_pdf_pages(extracted, document_metadata={
            "doc_name": filing.document_id, "company": filing.company, "doc_type": filing.form,
            "doc_link": filing.source_url, "reporting_periods": [filing.fiscal_year],
        })
        if not source_chunks:
            raise ValueError(f"No extractable text for {filing.document_id}")
        pages.extend({"doc_name": filing.document_id, **page} for page in extracted)
        chunks.extend({**row, "dataset_id": "independent_final", "cik": str(filing.cik),
                       "filing_date": filing.filed.isoformat(), "accession_number": filing.accession,
                       **({"ticker": filing.ticker} if filing.ticker else {})} for row in source_chunks)

    with TemporaryDirectory(prefix=".corpus-", dir=bundle) as temporary:
        staging = Path(temporary)
        index_id, fingerprint = _make_index(staging, sorted(chunks, key=lambda row: row["chunk_id"]), embedder)
        pages_path = staging / "pages.jsonl"
        _write_rows(pages_path, pages)
        if not sec_manifest.is_file():
            (staging / "sec").mkdir()
            sec_manifest = staging / "sec/manifest.json"
            write_json_atomic(sec_manifest, {"latest_filed": cutoff.isoformat(), "issuers": {}})
        corpus = Corpus(index_id=index_id, fingerprint=fingerprint,
                        index_manifest_sha256=sha256_file(staging / "index/index_manifest.json"),
                        embedding_manifest_sha256=sha256_file(staging / "index/embedding_manifest.json"),
                        chunks_sha256=sha256_file(staging / "index/corpus_chunks.jsonl"), pages_sha256=sha256_file(pages_path),
                        sec_manifest_sha256=sha256_file(sec_manifest),
                        filings=tuple(Filing.model_validate(row.model_dump(exclude={"company", "ticker", "fiscal_year"}))
                                      for row in sorted(filings, key=lambda item: item.document_id)))
        if (staging / "sec").exists():
            (staging / "sec").rename(sec_dir)
        (staging / "index").rename(bundle / "index")
        pages_path.rename(bundle / "pages.jsonl")
        write_json_atomic(bundle / "corpus.json", corpus.model_dump(mode="json"))
    return corpus


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--cutoff", type=date.fromisoformat, required=True)
    parser.add_argument("--threads", type=int, default=6, choices=range(1, 17))
    args = parser.parse_args()
    with offline_socket_guard():
        import torch

        from src.retrieval.embedder import Embedder

        filings = TypeAdapter(list[FilingInput]).validate_json((args.bundle / "filing-inventory.json").read_bytes())
        torch.set_num_threads(args.threads)
        corpus = prepare(args.bundle, filings, args.cutoff, Embedder(device="cpu", revision=P1_EMBEDDING_REVISION))
        print(f"Indexed {len(corpus.filings)} filings. corpus_sha256={sha256_file(args.bundle / 'corpus.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
