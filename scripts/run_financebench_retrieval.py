"""Build the FinanceBench PDF index and run reproducible retrieval baselines."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any

import pypdf
import sentence_transformers
import torch
import fontTools

from configs.financebench import (
    FINANCEBENCH_EXPECTED_CASES,
    FINANCEBENCH_EXPECTED_DOCUMENTS,
    FINANCEBENCH_GITHUB_REVISION,
    FINANCEBENCH_LICENSE,
    PDF_CHUNK_OVERLAP,
    PDF_CHUNK_SIZE,
    RETRIEVAL_CANDIDATE_POOL,
    RETRIEVAL_TOP_K,
)
from configs.settings import settings
from src.evaluation.financebench_dataset import (
    evidence_alignment_stats,
    load_financebench_cases,
)
from src.evaluation.retrieval_adapter import (
    RETRIEVAL_PRESETS,
    FinanceBenchRetrievalAdapter,
)
from src.evaluation.retrieval_metrics import evaluate_retrieval
from src.ingestion.pdf_ingestion import chunk_pdf_pages, extract_pdf_pages
from src.retrieval.embedder import Embedder
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.vector_store import VectorStore

logger = logging.getLogger(__name__)
DATA_DIR = Path("data/financebench")
SOURCE_CASES = DATA_DIR / "source" / "financebench_open_source.jsonl"
SOURCE_METADATA = DATA_DIR / "source" / "financebench_document_information.jsonl"
SOURCE_MANIFEST = DATA_DIR / "source_manifest.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            records.append(value)
    return records


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            yield value


def _embedding_cache_matches(
    path: Path,
    chunks: list[dict[str, Any]],
    *,
    dimension: int,
) -> bool:
    for item, chunk in itertools.zip_longest(_iter_jsonl(path), chunks):
        if item is None or chunk is None or item.get("chunk_id") != chunk["chunk_id"]:
            return False
        vector = item.get("embedding")
        if not isinstance(vector, list) or len(vector) != dimension:
            return False
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(float(value))
            for value in vector
        ):
            return False
    return True


def _write_jsonl_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            for record in records:
                output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            json.dump(value, output, indent=2, ensure_ascii=False, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _load_or_extract_pages(
    *,
    data_dir: Path,
    document_rows: list[dict[str, Any]],
    source_manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]], Path]:
    pdf_records = source_manifest["files"]["source_pdfs"]
    if len(pdf_records) != FINANCEBENCH_EXPECTED_DOCUMENTS:
        raise ValueError(
            f"Source manifest must cover {FINANCEBENCH_EXPECTED_DOCUMENTS} PDFs"
        )
    for record in pdf_records:
        pdf_path = Path(record["path"])
        if not pdf_path.is_file() or _sha256_file(pdf_path) != record["sha256"]:
            raise ValueError(f"Source PDF is absent or has changed: {record['doc_name']}")
    source_identity = [
        {"doc_name": record["doc_name"], "sha256": record["sha256"]}
        for record in sorted(pdf_records, key=lambda item: item["doc_name"])
    ]
    cache_key = _canonical_sha256(
        {
            "pdfs": source_identity,
            "pypdf_version": pypdf.__version__,
            "fonttools_version": fontTools.__version__,
            "extract_mode": "layout_without_vertical_whitespace",
        }
    ).split(":", 1)[1][:20]
    cache_dir = data_dir / "cache"
    pages_path = cache_dir / f"extracted_pages_{cache_key}.jsonl"
    cache_manifest_path = cache_dir / f"extracted_pages_{cache_key}.json"
    pages: list[dict[str, Any]] | None = None
    stats_by_document: dict[str, dict[str, int]] = {}
    if pages_path.is_file() and cache_manifest_path.is_file():
        cache_manifest = json.loads(cache_manifest_path.read_text(encoding="utf-8"))
        if cache_manifest.get("pages_sha256") == _sha256_file(pages_path):
            cached_pages = _read_jsonl(pages_path)
            cached_documents = {row.get("doc_name") for row in cached_pages}
            if cached_documents == {record["doc_name"] for record in pdf_records}:
                pages = cached_pages
                stats_by_document = cache_manifest.get("document_stats", {})

    if pages is None:
        metadata_by_doc = {
            record["doc_name"]: record for record in pdf_records
        }
        pages = []
        ordered_pdf_records = sorted(pdf_records, key=lambda item: item["doc_name"])
        for pdf_index, record in enumerate(ordered_pdf_records, start=1):
            pdf_path = Path(record["path"])
            if not pdf_path.is_file() or _sha256_file(pdf_path) != record["sha256"]:
                raise ValueError(f"Source PDF is absent or has changed: {record['doc_name']}")
            extracted = extract_pdf_pages(pdf_path)
            stats_by_document[record["doc_name"]] = {
                "page_count": len(extracted),
                "nonempty_page_count": sum(bool(page["text"]) for page in extracted),
                "empty_page_count": sum(not bool(page["text"]) for page in extracted),
                "extracted_char_count": sum(len(page["text"]) for page in extracted),
            }
            pages.extend(
                {"doc_name": record["doc_name"], **page}
                for page in extracted
            )
            if pdf_index % 10 == 0 or pdf_index == len(ordered_pdf_records):
                logger.info(
                    "Extracted text from %d/%d source PDFs",
                    pdf_index,
                    len(ordered_pdf_records),
                )
        _write_jsonl_atomic(pages_path, pages)
        _write_json_atomic(
            cache_manifest_path,
            {
                "cache_key": cache_key,
                "source_pdf_hashes": source_identity,
                "pypdf_version": pypdf.__version__,
                "fonttools_version": fontTools.__version__,
                "layout_mode_space_vertically": False,
                "pages_sha256": _sha256_file(pages_path),
                "document_stats": stats_by_document,
            },
        )

    metadata_by_doc = {row["doc_name"]: row for row in document_rows}
    pdf_metadata_by_doc = {row["doc_name"]: row for row in pdf_records}
    page_text_by_document: dict[str, dict[int, str]] = {}
    for page in pages:
        page_text_by_document.setdefault(page["doc_name"], {})[page["page_number"]] = page["text"]
    for doc_name, pdf_metadata in pdf_metadata_by_doc.items():
        if doc_name not in metadata_by_doc:
            raise ValueError(f"Source metadata is missing for {doc_name}")
        metadata_by_doc[doc_name] = {
            **metadata_by_doc[doc_name],
            **pdf_metadata,
        }
    return pages, stats_by_document, pages_path


def _build_corpus(
    pages: list[dict[str, Any]],
    *,
    source_manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    pdf_metadata = {
        record["doc_name"]: record
        for record in source_manifest["files"]["source_pdfs"]
    }
    pages_by_doc: dict[str, list[dict[str, Any]]] = {}
    for page in pages:
        pages_by_doc.setdefault(page["doc_name"], []).append(
            {"page_number": page["page_number"], "text": page["text"]}
        )

    chunks: list[dict[str, Any]] = []
    stats_by_document: dict[str, dict[str, int]] = {}
    ordered_doc_names = sorted(pdf_metadata)
    for document_index, doc_name in enumerate(ordered_doc_names, start=1):
        metadata = pdf_metadata[doc_name]
        if not metadata.get("company"):
            raise ValueError(f"Source metadata has no company for {doc_name}")
        metadata = {
            **metadata,
            "source_repository_url": (
                "https://github.com/patronus-ai/financebench/blob/"
                f"{source_manifest['dataset']['github_revision']}/pdfs/{doc_name}.pdf"
            ),
        }
        doc_chunks, doc_stats = chunk_pdf_pages(
            pages_by_doc.get(doc_name, []),
            document_metadata=metadata,
            chunk_size=PDF_CHUNK_SIZE,
            overlap=PDF_CHUNK_OVERLAP,
        )
        chunks.extend(doc_chunks)
        stats_by_document[doc_name] = {
            "page_count": len(pages_by_doc.get(doc_name, [])),
            **doc_stats,
        }
        if document_index % 10 == 0 or document_index == len(ordered_doc_names):
            logger.info(
                "Chunked %d/%d source PDFs",
                document_index,
                len(ordered_doc_names),
            )
    chunks.sort(key=lambda chunk: chunk["chunk_id"])
    return chunks, stats_by_document


def _corpus_fingerprint(chunks: list[dict[str, Any]]) -> str:
    stable_records = [
        {
            key: chunk.get(key)
            for key in (
                "chunk_id",
                "company",
                "doc_name",
                "page_number",
                "section",
                "text",
                "token_count",
            )
        }
        for chunk in sorted(chunks, key=lambda item: item["chunk_id"])
    ]
    return _canonical_sha256(stable_records)


def _load_or_build_embeddings(
    chunks: list[dict[str, Any]],
    *,
    run_dir: Path,
    corpus_fingerprint: str,
    embedder: Embedder,
) -> dict[str, Any]:
    embedded_path = run_dir / "embedded_chunks.jsonl"
    manifest_path = run_dir / "embedding_manifest.json"
    expected = {
        "corpus_fingerprint": corpus_fingerprint,
        "embedding_model_id": settings.embedding_model_id,
        "embedding_model_revision": settings.embedding_model_revision,
        "vector_dimension": embedder.dimension,
        "document_prefix": "search_document: ",
        "normalize_embeddings": embedder.normalize_embeddings,
    }
    if embedded_path.is_file() and manifest_path.is_file():
        cached_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if all(cached_manifest.get(key) == value for key, value in expected.items()):
            if cached_manifest.get("embedded_file_sha256") == _sha256_file(embedded_path):
                valid = _embedding_cache_matches(
                    embedded_path,
                    chunks,
                    dimension=embedder.dimension,
                )
                if valid:
                    return cached_manifest

    batch_size = 32 if embedder.device == "cuda" else 8
    temporary_path: Path | None = None
    embedded_count = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=run_dir,
            prefix=".embedded_chunks.",
            suffix=".jsonl.tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            for start in range(0, len(chunks), batch_size):
                batch = chunks[start : start + batch_size]
                vectors = embedder.embed_documents(
                    [item["text"] for item in batch],
                    batch_size=batch_size,
                    show_progress_bar=False,
                )
                if len(vectors) != len(batch):
                    raise ValueError("Embedding count does not match the input chunk count")
                for item, vector in zip(batch, vectors, strict=True):
                    output.write(
                        json.dumps(
                            {**item, "embedding": vector},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
                    output.write("\n")
                embedded_count += len(batch)
                if embedded_count % 1024 < batch_size or embedded_count == len(chunks):
                    output.flush()
                    logger.info("Embedded %d/%d FinanceBench chunks", embedded_count, len(chunks))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, embedded_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    manifest = {
        **expected,
        "point_count": embedded_count,
        "embedded_file_sha256": _sha256_file(embedded_path),
        "compute_device": embedder.device,
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "sentence_transformers_version": sentence_transformers.__version__,
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    _write_json_atomic(manifest_path, manifest)
    return manifest


def _ensure_index(
    *,
    embedded_path: Path,
    chunks: list[dict[str, Any]],
    run_dir: Path,
    index_id: str,
    embedding_manifest: dict[str, Any],
) -> tuple[VectorStore, dict[str, Any]]:
    collection_name = f"financebench_{index_id[:20]}"
    store = VectorStore(
        path=run_dir / "qdrant",
        collection_name=collection_name,
    )
    existing = {
        collection.name
        for collection in store.client.get_collections().collections
    }
    if collection_name not in existing:
        store.create_collection(embedding_dim=embedding_manifest["vector_dimension"])
        batch: list[dict[str, Any]] = []
        for item in _iter_jsonl(embedded_path):
            batch.append(item)
            if len(batch) >= 128:
                store.upsert_chunks(batch)
                batch = []
        if batch:
            store.upsert_chunks(batch)
    info = store.get_collection_info()
    if info.get("points_count") != len(chunks):
        store.close()
        raise ValueError(
            f"FinanceBench Qdrant index count mismatch: expected {len(chunks)}, "
            f"found {info.get('points_count')}"
        )
    stored_payloads = store.load_all_chunks()
    stored_ids = {item["chunk_id"] for item in stored_payloads}
    expected_ids = {item["chunk_id"] for item in chunks}
    if stored_ids != expected_ids:
        store.close()
        raise ValueError("FinanceBench Qdrant index contents do not match the corpus")
    if _corpus_fingerprint(stored_payloads) != embedding_manifest["corpus_fingerprint"]:
        store.close()
        raise ValueError("FinanceBench Qdrant payload fingerprint does not match the corpus")
    index_manifest = {
        "schema_version": 1,
        "index_id": index_id,
        "collection_name": collection_name,
        "corpus_fingerprint": embedding_manifest["corpus_fingerprint"],
        "embedding_manifest_sha256": _canonical_sha256(embedding_manifest),
        "point_count": len(chunks),
        "vector_dimension": embedding_manifest["vector_dimension"],
        "distance_metric": "cosine",
        "status": info.get("status"),
    }
    _write_json_atomic(run_dir / "index_manifest.json", index_manifest)
    return store, index_manifest


def _git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _check_source_files(source_manifest: dict[str, Any]) -> None:
    for source_record in source_manifest["files"]["source_jsonl"].values():
        path = Path(source_record["path"])
        if not path.is_file() or _sha256_file(path) != source_record["sha256"]:
            raise ValueError(f"FinanceBench source JSONL is missing or changed: {path}")


def run_benchmark(
    *,
    data_dir: Path = DATA_DIR,
    top_k: int = RETRIEVAL_TOP_K,
    candidate_pool: int = RETRIEVAL_CANDIDATE_POOL,
) -> dict[str, Any]:
    source_manifest_path = data_dir / "source_manifest.json"
    if not source_manifest_path.is_file():
        raise FileNotFoundError(
            "FinanceBench source manifest is missing; run "
            "python -m scripts.download_financebench first"
        )
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    _check_source_files(source_manifest)
    cases = load_financebench_cases(
        data_dir / "source" / "financebench_open_source.jsonl"
    )
    document_rows = _read_jsonl(data_dir / "source" / "financebench_document_information.jsonl")
    if (
        source_manifest.get("dataset", {}).get("github_revision")
        != FINANCEBENCH_GITHUB_REVISION
        or source_manifest.get("dataset", {}).get("license") != FINANCEBENCH_LICENSE
        or source_manifest.get("dataset", {}).get("case_count") != FINANCEBENCH_EXPECTED_CASES
    ):
        raise ValueError("FinanceBench source manifest does not match the pinned dataset protocol")
    pages, extraction_stats, pages_path = _load_or_extract_pages(
        data_dir=data_dir,
        document_rows=document_rows,
        source_manifest=source_manifest,
    )
    page_text_by_document: dict[str, dict[int, str]] = {}
    for page in pages:
        page_text_by_document.setdefault(page["doc_name"], {})[page["page_number"]] = page["text"]
    raw_cases = _read_jsonl(data_dir / "source" / "financebench_open_source.jsonl")
    parser_quality = evidence_alignment_stats(raw_cases, page_text_by_document)

    doc_page_counts = {
        doc_name: stats["page_count"]
        for doc_name, stats in extraction_stats.items()
    }
    eligible_cases = []
    excluded_cases = []
    for case in cases:
        page_count = doc_page_counts.get(case.doc_name, 0)
        if page_count <= 0:
            excluded_cases.append({"case_id": case.case_id, "reason": "source_pdf_unavailable"})
        elif any(page >= page_count for page in case.gold_pages):
            excluded_cases.append({"case_id": case.case_id, "reason": "evidence_page_out_of_range"})
        else:
            eligible_cases.append(case)
    if not eligible_cases:
        raise ValueError("No FinanceBench cases meet the frozen source/page eligibility rule")

    chunks, corpus_stats = _build_corpus(
        pages,
        source_manifest=source_manifest,
    )
    del pages, page_text_by_document, raw_cases, document_rows
    if not chunks:
        raise ValueError("PDF extraction produced no indexable text chunks")
    corpus_fingerprint = _corpus_fingerprint(chunks)
    if not settings.embedding_model_revision:
        raise ValueError("The embedding model revision must be pinned")
    index_id = _canonical_sha256(
        {
            "corpus_fingerprint": corpus_fingerprint,
            "embedding_model_id": settings.embedding_model_id,
            "embedding_model_revision": settings.embedding_model_revision,
            "chunk_size": PDF_CHUNK_SIZE,
            "chunk_overlap": PDF_CHUNK_OVERLAP,
        }
    ).split(":", 1)[1]
    run_dir = data_dir / "runs" / index_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl_atomic(run_dir / "corpus_chunks.jsonl", chunks)

    embedder = Embedder(
        model_name=settings.embedding_model_id,
        revision=settings.embedding_model_revision,
    )
    embedding_manifest = _load_or_build_embeddings(
        chunks,
        run_dir=run_dir,
        corpus_fingerprint=corpus_fingerprint,
        embedder=embedder,
    )
    store, index_manifest = _ensure_index(
        embedded_path=run_dir / "embedded_chunks.jsonl",
        chunks=chunks,
        run_dir=run_dir,
        index_id=index_id,
        embedding_manifest=embedding_manifest,
    )

    retriever = HybridRetriever(
        embedder=embedder,
        store=store,
        all_chunks=chunks,
        device=embedder.device,
        cross_encoder_model=settings.reranker_model_id,
        cross_encoder_revision=settings.reranker_model_revision,
    )
    adapter = FinanceBenchRetrievalAdapter(
        retriever,
        top_k=top_k,
        candidate_pool=candidate_pool,
    )
    all_predictions: dict[str, dict[str, list[dict[str, Any]]]] = {
        preset: {} for preset in RETRIEVAL_PRESETS
    }
    all_latencies: dict[str, dict[str, float]] = {preset: {} for preset in RETRIEVAL_PRESETS}
    query_embedding_latencies: list[float] = []
    warmup_embedding = retriever.embed_query("FilingScope retrieval benchmark warmup")
    adapter.retrieve(
        "FilingScope retrieval benchmark warmup",
        preset="hybrid_rerank",
        query_embedding=warmup_embedding,
    )
    started_at = datetime.now(UTC).isoformat()
    try:
        for case_number, case in enumerate(eligible_cases, start=1):
            embedding_started = time.perf_counter()
            query_embedding = retriever.embed_query(case.question)
            embedding_ms = (time.perf_counter() - embedding_started) * 1000
            query_embedding_latencies.append(embedding_ms)
            for preset in RETRIEVAL_PRESETS:
                retrieval_started = time.perf_counter()
                predictions = adapter.retrieve(
                    case.question,
                    preset=preset,
                    query_embedding=query_embedding if preset != "bm25" else None,
                )
                retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
                if preset != "bm25":
                    retrieval_ms += embedding_ms
                all_predictions[preset][case.case_id] = predictions
                all_latencies[preset][case.case_id] = retrieval_ms
            if case_number % 10 == 0 or case_number == len(eligible_cases):
                logger.info("Evaluated %d/%d eligible questions", case_number, len(eligible_cases))

        metrics_by_preset = {}
        failure_analysis = {}
        for preset in RETRIEVAL_PRESETS:
            evaluated = evaluate_retrieval(
                eligible_cases,
                all_predictions[preset],
                all_latencies[preset],
            )
            case_metrics = evaluated.pop("case_metrics")
            metrics_by_preset[preset] = evaluated
            failure_analysis[preset] = {
                "case_ids_with_no_evidence_page_in_top_10": [
                    row["case_id"]
                    for row in case_metrics
                    if row["recall_at_10"] == 0
                ],
                "miss_count_by_split": dict(
                    Counter(
                        row["split"]
                        for row in case_metrics
                        if row["recall_at_10"] == 0
                    )
                ),
                "miss_count_by_question_type": dict(
                    Counter(
                        row["question_type"]
                        for row in case_metrics
                        if row["recall_at_10"] == 0
                    )
                ),
            }
            predictions_path = run_dir / f"predictions_{preset}.jsonl"
            _write_jsonl_atomic(
                predictions_path,
                [
                    {
                        "case_id": case.case_id,
                        "split": case.split,
                        "retrieved": all_predictions[preset][case.case_id],
                        "latency_ms": round(all_latencies[preset][case.case_id], 3),
                    }
                    for case in eligible_cases
                ],
            )

        metrics_payload = {
            "schema_version": 1,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "eligible_case_count": len(eligible_cases),
            "excluded_cases": excluded_cases,
            "presets": metrics_by_preset,
        }
        _write_json_atomic(run_dir / "metrics.json", metrics_payload)
        _write_json_atomic(run_dir / "failure_analysis.json", failure_analysis)
        run_manifest = {
            "schema_version": 1,
            "benchmark": "FinanceBench public open-source sample",
            "source_commit": _git_revision(),
            "started_at_utc": started_at,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "dataset_source_manifest_sha256": _sha256_file(source_manifest_path),
            "dataset_revision": source_manifest["dataset"]["github_revision"],
            "case_count": len(cases),
            "eligible_case_count": len(eligible_cases),
            "excluded_cases": excluded_cases,
            "company_split_counts": dict(Counter(case.split for case in eligible_cases)),
            "source_pdf_count": len(source_manifest["files"]["source_pdfs"]),
            "extracted_page_cache_sha256": _sha256_file(pages_path),
            "extraction_stats_by_document": extraction_stats,
            "corpus_stats_by_document": corpus_stats,
            "parser_quality": parser_quality,
            "corpus_fingerprint": corpus_fingerprint,
            "index_id": index_id,
            "index_manifest": index_manifest,
            "embedding_manifest": embedding_manifest,
            "embedding_model": {
                "id": settings.embedding_model_id,
                "revision": settings.embedding_model_revision,
                "query_embedding_latency_ms_mean": round(
                    sum(query_embedding_latencies) / max(1, len(query_embedding_latencies)),
                    3,
                ),
            },
            "reranker_model": {
                "id": settings.reranker_model_id,
                "revision": settings.reranker_model_revision,
            },
            "environment": {
                "python": sys.version.split()[0],
                "torch": torch.__version__,
                "torch_cuda": torch.version.cuda,
                "sentence_transformers": sentence_transformers.__version__,
                "pypdf": pypdf.__version__,
                "fonttools": fontTools.__version__,
                "device": embedder.device,
            },
            "chunking": {"tokenizer": "tiktoken cl100k_base", "chunk_size": PDF_CHUNK_SIZE, "overlap": PDF_CHUNK_OVERLAP},
            "retrieval": {
                "presets": list(RETRIEVAL_PRESETS),
                "top_k": top_k,
                "candidate_pool": candidate_pool,
                "hybrid_uses_lexical_ladder": True,
                "structured_lookup": False,
            },
            "prediction_artifacts_exclude_gold_answers": True,
        }
        _write_json_atomic(run_dir / "run_manifest.json", run_manifest)
        logger.info("FinanceBench results written to %s", run_dir)
        return {"run_dir": str(run_dir), "metrics": metrics_payload, "manifest": run_manifest}
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=RETRIEVAL_TOP_K)
    parser.add_argument("--candidate-pool", type=int, default=RETRIEVAL_CANDIDATE_POOL)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = run_benchmark(top_k=args.top_k, candidate_pool=args.candidate_pool)
    print(json.dumps(result["metrics"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
