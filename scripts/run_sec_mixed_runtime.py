"""Run the routed QA graph on the frozen SEC mixed cohorts and three source inventories."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from configs.financebench import P1_EMBEDDING_REVISION
from configs.offline_guard import offline_socket_guard
from scripts.run_multi_agent_ablation import _RecordingRetriever
from scripts.run_sec_ixbrl_evaluation import LIMITS, MEMBERSHIP
from scripts.run_sec_runtime_pilot import TRACKS, _load_manifest, _load_pilot_vectors, _prepare_sec
from src.agent.complexity_router import ComplexityRouter
from src.agent.specialist_graph import SpecialistResearchGraph
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.sec_html_documents import read_filing
from src.evaluation.sec_mixed_cohorts import assert_mixed_cohorts_disjoint
from src.evaluation.sec_mixed_runtime import is_author_excerpt_present, score_mixed_release
from src.ingestion.sec_corpus import SourceCache
from src.research.corpus_map import CorpusMap
from src.retrieval.canonical_json import canonical_json_bytes, canonical_sha256, sha256_file
from src.retrieval.financial_statement_ranker import FinancialStatementRanker
from src.retrieval.frozen_dense import FrozenDenseRetriever
from src.retrieval.pdf_page_cache import FrozenPdfPages


CASE_HASHES = {
    "pilot": "sha256:9b15c9c564dd500da8029fcea95d6ec9b12a944b205d476ceda797526c97285b",
    "development": "sha256:400a885d20761a189eb81c00e875d791f2fd650b38f42b6d82374ee2035c1bf6",
    "validation": "sha256:82db2c40dcdff67f67775a5d5c2ec63bb78f82d517966682f68f814f30744840",
}


def _load_cases(directory: Path, manifest_path: Path) -> dict:
    cohorts = {}
    for name, expected in CASE_HASHES.items():
        payload = json.loads((directory / f"{name}.json").read_bytes())
        cases = payload["cases"]
        if (payload["schema"] != "filingscope-sec-mixed-cohort-v1"
                or payload["status"] != "PROVISIONAL_NOT_INDEPENDENT"
                or payload["corpus_manifest_sha256"] != sha256_file(manifest_path)
                or payload["cases_sha256"] != expected or canonical_sha256(cases) != expected
                or len(cases) != LIMITS[name]
                or {doc["ticker"] for case in cases for doc in case["documents"]} != MEMBERSHIP[name]):
            raise ValueError(f"Cohort differs from the frozen mixed benchmark: {name}")
        cohorts[name] = cases
    assert_mixed_cohorts_disjoint(cohorts)
    return cohorts


def _predictions(cases, router, index, sec, track):
    use_document, use_sec = TRACKS[track]
    retriever = _RecordingRetriever(index) if use_document else None
    graph = SpecialistResearchGraph(router=router, retriever=retriever, sec_client=sec if use_sec else None,
                                    ticker_by_company={ticker.casefold(): ticker for ticker in sec.issuers})
    for case in cases:
        if retriever:
            retriever.reset()
        before = sec.request_count
        start = time.perf_counter()
        execution = graph.run(case["question"], request_id=f"mixed-{track}-{case['case_id']}")
        latency = (time.perf_counter() - start) * 1000
        sec_calls = sec.request_count - before
        if (not use_sec and sec_calls) or execution.usage.llm_calls:
            raise RuntimeError(f"Unexpected provider use in {track}")
        evidence = execution.ledger_snapshot.evidence_records
        if any((not use_document and item.xbrl_provenance is None)
               or (not use_sec and item.xbrl_provenance is not None) for item in evidence):
            raise RuntimeError(f"Unexpected evidence source in {track}")
        claims = execution.verification.claims if execution.verification else ()
        requirements = execution.ledger_snapshot.question_requirements
        yield {
            "case_id": case["case_id"], "category": case["category"], "question": case["question"],
            "answer": execution.answer, "disposition": execution.status, "route": execution.selected_path,
            "source_capability": execution.route.source_capability, "latency_ms": round(latency, 3),
            "tool_calls": execution.usage.tool_calls, "sec_calls": sec_calls,
            "evidence_tokens": execution.usage.evidence_tokens,
            "retrieval_calls": len(retriever.calls) if retriever else 0,
            "statement_calls": retriever.statement_calls if retriever else 0,
            "requirements": requirements.model_dump(mode="json") if requirements else None,
            "ranked_document_blocks": retriever.ranked_pdf_pages() if retriever else None,
            "citations": execution.citation_evidence_ids,
            "claims": [item.model_dump(mode="json") for item in claims],
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }


def _score(cases, predictions, chunks_by_id):
    outcomes, metrics = [], defaultdict(Counter)
    for case, row in zip(cases, predictions, strict=True):
        if case["case_id"] != row["case_id"]:
            raise ValueError("Prediction case order differs from frozen questions")
        scored = score_mixed_release(case, row["answer"], row["disposition"], row["claims"], row["evidence"], row["citations"])
        if reference := case.get("narrative_evidence"):
            scored["retrieved_reference_excerpt"] = any(
                evidence["source_url"] == reference["source_url"]
                and is_author_excerpt_present(chunk["text"], reference["excerpt"])
                for evidence in row["evidence"] if (chunk := chunks_by_id.get(evidence["chunk_id"])) is not None
            )
        outcomes.append({"case_id": case["case_id"], "category": case["category"], **scored})
        for counter in (metrics[case["category"]], metrics["overall"]):
            counter["cases"] += 1
            counter["numeric_answerable"] += bool(case["required_facts"])
            counter["released"] += scored["released"]
            counter[scored["outcome"]] += 1
            counter["retrieved_reference_excerpt"] += scored.get("retrieved_reference_excerpt", False)
            for field in ("tool_calls", "sec_calls", "evidence_tokens", "retrieval_calls", "statement_calls"):
                counter[field] += row[field]
    latencies = [row["latency_ms"] for row in predictions]
    summary = dict(metrics)
    summary["overall"]["latency_p50_ms"] = round(statistics.median(latencies), 3)
    summary["overall"]["latency_p95_ms"] = round(statistics.quantiles(latencies, n=20, method="inclusive")[18], 3)
    return {"summary": summary, "cases": outcomes}


def _run(args):
    import numpy as np
    import torch

    from src.retrieval.embedder import Embedder

    started = time.perf_counter()
    manifest = _load_manifest(args.manifest)
    cohorts = _load_cases(args.cohorts, args.manifest)
    cache = SourceCache(args.cache, None)
    torch.set_num_threads(args.threads)
    embedder = Embedder(device="cpu", revision=P1_EMBEDDING_REVISION)
    prior = json.loads((args.reuse_vectors / "report.json").read_bytes()) if args.reuse_vectors else None
    summaries = {}
    for name, cases in cohorts.items():
        setup_start = time.perf_counter()
        directory = args.output / name
        directory.mkdir(parents=True)
        chunks, pages, metadata = [], [], []
        for filing in manifest["filings"]:
            if filing["ticker"] in MEMBERSHIP[name]:
                extracted, blocks, document = read_filing(filing, cache)
                chunks.extend(extracted)
                pages.extend(blocks)
                metadata.append(document)
        page_file = directory / "html-blocks.jsonl"
        with page_file.open("wb") as stream:
            for page in pages:
                stream.write(canonical_json_bytes(page) + b"\n")
        page_hash = sha256_file(page_file)
        chunk_hash = canonical_sha256(chunks)
        pages_cache = FrozenPdfPages(page_file, expected_sha256=page_hash)
        router = ComplexityRouter(CorpusMap.from_chunks(chunks, index_generation_id=chunk_hash))
        if prior is None:
            print(f"{name}: embedding {len(chunks)} chunks", flush=True)
            vectors = np.asarray(embedder.embed_documents([item["text"] for item in chunks], show_progress_bar=False),
                                 dtype=np.float32)
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            if not np.all(np.isfinite(norms) & (norms > 0)):
                raise ValueError("Document embeddings must be finite and nonzero")
            vectors /= norms
        else:
            source = args.reuse_vectors / name
            print(f"{name}: reusing vectors for {len(chunks)} chunks", flush=True)
            vector_receipt = {**prior["cohorts"][name], "embedding_revision": prior["embedding_revision"]}
            vectors = _load_pilot_vectors(source, chunks_hash=chunk_hash, rows=len(chunks), dimension=embedder.dimension,
                                          report=vector_receipt)
        vector_file = directory / "normalized-vectors.npy"
        np.save(vector_file, vectors, allow_pickle=False)
        index = FrozenDenseRetriever(chunks, vectors, embedder, pdf_pages=pages_cache,
                                     statement_ranker=FinancialStatementRanker(pages_cache, router.extractor))
        tickers = {item["ticker"]: int(item["cik"]) for item in metadata}
        sec = _prepare_sec(manifest, args.cache, directory / "company-facts", tickers)
        cohort_summary = {"setup_seconds": round(time.perf_counter() - setup_start, 3), "documents": metadata,
                          "blocks": len(pages), "chunks": len(chunks), "chunks_sha256": chunk_hash,
                          "blocks_sha256": page_hash, "vectors_sha256": sha256_file(vector_file),
                          "reference_sha256": CASE_HASHES[name], "tracks": {}}
        chunks_by_id = {item["chunk_id"]: item for item in chunks}
        for track in TRACKS:
            print(f"{name}: {track}", flush=True)
            predictions = list(_predictions(cases, router, index, sec, track))
            path = directory / f"{track}-predictions.json"
            write_json_atomic(path, {"rows": predictions})
            scored = _score(cases, predictions, chunks_by_id)
            write_json_atomic(directory / f"{track}-scores.json", scored)
            cohort_summary["tracks"][track] = {**scored["summary"], "predictions_sha256": sha256_file(path)}
        summaries[name] = cohort_summary
    write_json_atomic(args.output / "report.json", {
        "schema": "filingscope.sec-mixed-runtime.v1", "status": "PROVISIONAL_NOT_INDEPENDENT",
        "sec_manifest_sha256": sha256_file(args.manifest), "embedding_model": embedder.model_name,
        "embedding_revision": embedder.model_revision, "cohorts": summaries, "threads": args.threads,
        "wall_seconds": round(time.perf_counter() - started, 3), "peak_memory_bytes": peak_memory_bytes(),
        "provider_calls": 0, "provider_tokens": 0, "provider_cost_usd": 0,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--cohorts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-vectors", type=Path, help="Reuse hash-checked vectors from a prior mixed replay")
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()
    if args.threads < 1 or args.output.exists() and any(args.output.iterdir()):
        parser.error("Use a fresh output directory and positive thread count")
    with offline_socket_guard():
        _run(args)


if __name__ == "__main__":
    main()
