"""Rerank frozen dense pools with local neural or filing-graph variants."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import time
from pathlib import Path

import numpy as np

from configs.hard_negatives import CASES, P1_CORPUS_FINGERPRINT, P1_INDEX_ID
from scripts.run_context_expansion import DEFAULT_RANKINGS
from scripts.run_financebench_retrieval import _sha256_file
from scripts.run_hard_negative_retrieval import DEFAULT_RUN, SPLITS, _load_corpus, _peak_memory_bytes
from scripts.run_retrieval_diagnostics import _nearest_rank, _write_json_atomic
from src.evaluation.hard_negative_retrieval import resolve_passages, score_case, summarize


COLBERT_MODEL = "colbert-ir/colbertv2.0"
COLBERT_REVISION = "c1e84128e85ef755c096a95bdb06b47793b13acf"
COLBERT_FILES = {
    "config.json": "sha256:cbdcc01dc7772fd0e5e1d85d5de695faf8c4935ae3c7ea3fdb6c24397b284f3c",
    "model.onnx": "sha256:bfe81fa313c4c2a12319ec9ef0cdf1c995daad051e9c5a1fcabcb90feb3c8286",
    "special_tokens_map.json": "sha256:303df45a03609e4ead04bc3dc1536d0ab19b5358db685b6f3da123d05ec200e3",
    "tokenizer.json": "sha256:5fd1c882abbd30517dced455a2c9768945ec726b96727927e4959348d9de550b",
    "tokenizer_config.json": "sha256:a16a31c8d474339d7a46afe7eb8583b24f8b74806af6e25294506523f9d0acfb",
    "vocab.txt": "sha256:07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
}
DEFAULT_MODEL = Path("data/financebench/advanced_runs/m14-colbert-model")
DEFAULT_VECTOR_CACHE = Path("data/financebench/advanced_runs/m14-colbert-vectors.npz")


def _load_pool(directory, rankings):
    chunks = _load_corpus(directory)
    resolved = resolve_passages(CASES, chunks)
    position = {row["chunk_id"]: index for index, row in enumerate(chunks)}
    replay = json.loads(rankings.read_text(encoding="utf-8"))
    if replay["p1_index_id"] != P1_INDEX_ID or replay["corpus_fingerprint"] != P1_CORPUS_FINGERPRINT:
        raise ValueError("Dense rankings do not match the P1 corpus")
    pools = {row["case_id"]: [position[item] for item in row["ranking"]]
             for row in replay["variants"]["dense"]["per_case"]}
    if set(pools) != {case.case_id for case in CASES} or any(len(set(pool)) != 50 for pool in pools.values()):
        raise ValueError("Dense rankings do not contain the fixed 50-candidate pools")
    return chunks, resolved, pools


def _evaluate(chunks, resolved, pools, scores_by_case, latencies):
    rows = []
    for case in CASES:
        pool = pools[case.case_id]
        scores = scores_by_case[case.case_id]
        if scores.keys() != set(pool) or not all(np.isfinite(value) for value in scores.values()):
            raise ValueError(f"Variant scores do not cover the frozen pool for {case.case_id}")
        ranking = sorted(scores, key=lambda item: (-scores[item], chunks[item]["chunk_id"]))
        values = np.full(len(chunks), -np.inf)
        for item, score in scores.items():
            values[item] = score
        result = score_case(case, resolved, ranking, values)
        # Quality is measured globally at top k. Pairwise discrimination is
        # restricted to comparisons for which both candidates entered the pool.
        result.pop("pairs")
        result.pop("random_pairs")
        comparisons = [
            (scores[resolved[positive]], scores[resolved[negative.passage]])
            for positive in case.evidence for negative in case.negatives
            if resolved[positive] in scores and resolved[negative.passage] in scores
        ]
        result.update(
            ranking=[chunks[index]["chunk_id"] for index in ranking],
            latency_ms=round(latencies.get(case.case_id, 0.0), 3),
            pair_wins=sum(left > right for left, right in comparisons),
            pair_ties=sum(left == right for left, right in comparisons),
            pair_count=len(comparisons),
        )
        rows.append(result)

    def aggregate(group):
        normalized = [{**row, "pairs": {}, "random_pairs": {"wins": 0, "ties": 0, "losses": 0,
                                                            "filtered_positive_pairs": 0}} for row in group]
        measures = summarize(normalized)
        measures.pop("pairwise_by_type")
        measures.pop("pairwise_hard")
        pairs = sum(row["pair_count"] for row in group)
        wins = sum(row["pair_wins"] + 0.5 * row["pair_ties"] for row in group)
        return {**measures, "within_pool_pair_count": pairs, "within_pool_pairwise": round(wins / pairs, 4) if pairs else None,
                "p50_ms": _nearest_rank([row["latency_ms"] for row in group], .5),
                "p95_ms": _nearest_rank([row["latency_ms"] for row in group], .95)}

    return {"overall": aggregate(rows), "by_split": {split: aggregate([row for row in rows if row["split"] == split]) for split in SPLITS},
            "per_case": rows}


def _colbert(chunks, pools, model_path, vector_cache, threads):
    from fastembed import LateInteractionTextEmbedding
    from qdrant_client import QdrantClient, models

    model_files = {name: _sha256_file(model_path / name) for name in COLBERT_FILES}
    if model_files != COLBERT_FILES:
        raise ValueError("Model or tokenizer files do not match the pinned ColBERT checkpoint")
    setup_started = time.perf_counter()
    embedder = LateInteractionTextEmbedding(
        COLBERT_MODEL, threads=threads, providers=["CPUExecutionProvider"],
        specific_model_path=str(model_path.resolve()), local_files_only=True,
    )
    unique = sorted({item for pool in pools.values() for item in pool})
    keys = [chunks[item]["chunk_id"] for item in unique]
    identity = json.dumps({"index": P1_INDEX_ID, "model": COLBERT_FILES["model.onnx"],
                           "fastembed": importlib.metadata.version("fastembed"),
                           "onnxruntime": importlib.metadata.version("onnxruntime"), "chunks": keys}, sort_keys=True)
    if vector_cache.is_file():
        with np.load(vector_cache, allow_pickle=False) as cache:
            if cache["identity"].item() != identity:
                raise ValueError("Cached ColBERT vectors belong to another experiment")
            embedding_seconds = float(cache["embedding_seconds"].item())
            vectors = {item: cache[f"p{index}"] for index, item in enumerate(unique)}
    else:
        started = time.perf_counter()
        vectors = dict(zip(unique, embedder.passage_embed([chunks[item]["text"] for item in unique], batch_size=8), strict=True))
        embedding_seconds = time.perf_counter() - started
        vector_cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = vector_cache.with_suffix(".tmp")
        with temporary.open("wb") as handle:
            np.savez(handle, identity=identity, embedding_seconds=embedding_seconds,
                     **{f"p{index}": vectors[item] for index, item in enumerate(unique)})
        temporary.replace(vector_cache)
    dimension = next(iter(vectors.values())).shape[1]
    if any(value.ndim != 2 or value.shape[1] != dimension or not value.shape[0] or not np.isfinite(value).all()
           for value in vectors.values()):
        raise ValueError("ColBERT returned invalid passage vectors")

    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name="rerank",
        vectors_config=models.VectorParams(
            size=dimension, distance=models.Distance.COSINE,
            multivector_config=models.MultiVectorConfig(comparator=models.MultiVectorComparator.MAX_SIM),
            hnsw_config=models.HnswConfigDiff(m=0),
        ),
    )
    started = time.perf_counter()
    for start in range(0, len(unique), 24):
        client.upsert("rerank", [models.PointStruct(id=item, vector=vectors[item].tolist()) for item in unique[start:start + 24]])
    qdrant_setup_seconds = time.perf_counter() - started

    numpy_scores, qdrant_scores, numpy_time, qdrant_time = {}, {}, {}, {}
    max_error = 0.0
    for case in CASES:
        started = time.perf_counter()
        query = next(iter(embedder.query_embed(case.question)))
        query_ms = (time.perf_counter() - started) * 1000
        pool = pools[case.case_id]
        started = time.perf_counter()
        direct = {item: float(np.max(query @ vectors[item].T, axis=1).sum()) for item in pool}
        numpy_time[case.case_id] = query_ms + (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        hits = client.query_points(
            collection_name="rerank", query=query.tolist(),
            query_filter=models.Filter(must=[models.HasIdCondition(has_id=pool)]),
            limit=len(pool), with_payload=False,
        ).points
        qdrant_time[case.case_id] = query_ms + (time.perf_counter() - started) * 1000
        qdrant = {int(hit.id): hit.score for hit in hits}
        if qdrant.keys() != direct.keys():
            raise ValueError(f"Qdrant candidate mismatch for {case.case_id}")
        max_error = max(max_error, max(abs(direct[key] - qdrant[key]) for key in direct))
        numpy_scores[case.case_id] = direct
        qdrant_scores[case.case_id] = qdrant
    client.close()
    if max_error > 0.002:
        raise ValueError(f"Qdrant and NumPy MaxSim differ by {max_error:.6f}")
    return {"colbert_maxsim": (numpy_scores, numpy_time), "qdrant_multivector": (qdrant_scores, qdrant_time)}, {
        "model": COLBERT_MODEL, "revision": COLBERT_REVISION, "model_files_sha256": model_files,
        "fastembed": importlib.metadata.version("fastembed"), "qdrant_client": importlib.metadata.version("qdrant-client"),
        "onnxruntime": importlib.metadata.version("onnxruntime"), "model_disk_bytes": sum((model_path / file).stat().st_size for file in model_files),
        "passage_count": len(vectors), "vector_count": sum(value.shape[0] for value in vectors.values()),
        "vector_bytes": sum(value.nbytes for value in vectors.values()), "dimension": dimension,
        "passage_embedding_seconds": round(embedding_seconds, 3), "qdrant_setup_seconds": round(qdrant_setup_seconds, 3),
        "elapsed_seconds": round(time.perf_counter() - setup_started, 3), "max_score_error": max_error,
    }


def _cross_encoder(chunks, pools, directory, threads):
    import torch
    from sentence_transformers import CrossEncoder

    config = json.loads((directory / "run_manifest.json").read_text(encoding="utf-8"))["reranker_model"]
    torch.set_num_threads(threads)
    started = time.perf_counter()
    model = CrossEncoder(config["id"], revision=config["revision"], device="cpu")
    setup = time.perf_counter() - started
    scores, times = {}, {}
    for case in CASES:
        pool = pools[case.case_id]
        started = time.perf_counter()
        values = model.predict([(case.question, chunks[item]["text"]) for item in pool], batch_size=12, show_progress_bar=False)
        times[case.case_id] = (time.perf_counter() - started) * 1000
        scores[case.case_id] = dict(zip(pool, map(float, values), strict=True))
    return {"cross_encoder": (scores, times)}, {**config, "model_setup_seconds": round(setup, 3)}


def _graphs(chunks, pools):
    from src.retrieval.provenance_graph import FilingPassageGraph

    started = time.perf_counter()
    graph = FilingPassageGraph(chunks)
    setup = time.perf_counter() - started
    variants = {}
    for name, ranker in (
        ("graphrag_local", graph.local_search), ("hipporag_pagerank", graph.personalized_pagerank),
        ("lightrag_dual_level", graph.dual_level),
    ):
        scores, times = {}, {}
        for case in CASES:
            started = time.perf_counter()
            cues = graph.cues(case.question)
            scores[case.case_id] = ranker(cues, pools[case.case_id])
            times[case.case_id] = (time.perf_counter() - started) * 1000
        variants[name] = scores, times
    return variants, {
        "graph_setup_seconds": round(setup, 3), "passage_nodes": len(graph.units),
        "filing_nodes": len(graph.units_by_filing), "entity_nodes": len(graph.filings_by_company),
        "entity_topic_relationships": len(graph.units_by_relationship), "pagerank_iterations": 20,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p1-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--rankings", type=Path, default=DEFAULT_RANKINGS)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--vector-cache", type=Path, default=DEFAULT_VECTOR_CACHE)
    parser.add_argument("--backend", choices=("colbert", "cross-encoder", "graphs"), required=True)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.threads <= 16:
        parser.error("threads must be between 1 and 16")
    chunks, resolved, pools = _load_pool(args.p1_run, args.rankings)
    if args.backend == "colbert":
        variants, metadata = _colbert(chunks, pools, args.model, args.vector_cache, args.threads)
    elif args.backend == "cross-encoder":
        variants, metadata = _cross_encoder(chunks, pools, args.p1_run, args.threads)
    else:
        variants, metadata = _graphs(chunks, pools)
    variants["dense"] = ({key: {item: -rank for rank, item in enumerate(pool)} for key, pool in pools.items()}, {})
    report = {
        "benchmark": "filingscope-fixed-pool-reranking-v1", "p1_index_id": P1_INDEX_ID,
        "ranking_report_sha256": _sha256_file(args.rankings), "metadata": metadata, "threads": args.threads,
        "peak_memory_bytes": _peak_memory_bytes(), "provider_calls": 0,
        "variants": {name: _evaluate(chunks, resolved, pools, scores, times) for name, (scores, times) in variants.items()},
    }
    _write_json_atomic(args.output, report)
    print(args.output)


if __name__ == "__main__":
    main()
