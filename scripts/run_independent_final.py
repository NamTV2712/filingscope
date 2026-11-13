"""Run sealed questions on a frozen corpus, then score after the labels are released."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path

from configs.financebench import P1_EMBEDDING_REVISION
from configs.offline_guard import offline_socket_guard
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.independent_final import (
    ARMS, Corpus, Freeze, Label, Membership, Question, check_membership, read_pinned, read_rows, score_cohort,
)
from src.retrieval.canonical_json import sha256_file


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()


def _dependencies() -> dict[str, str]:
    return dict(sorted((dist.metadata["Name"], dist.version) for dist in distributions()))


def _predict(bundle: Path, freeze: Freeze, corpus: Corpus, questions: list[Question]) -> dict:
    import torch

    from scripts.run_multi_agent_ablation import _PolicyLayer, _RecordingRetriever
    from scripts.run_specialist_architectures import observe
    from src.agent.complexity_router import ComplexityRouter
    from src.agent.specialist_graph import SpecialistResearchGraph
    from src.evaluation.company_facts_replay import CompanyFactsReplay
    from src.research.corpus_map import CorpusMap
    from src.retrieval.embedder import MODEL_NAME, Embedder
    from src.retrieval.financial_statement_ranker import FinancialStatementRanker
    from src.retrieval.frozen_artifacts import load_frozen_corpus, load_frozen_vectors
    from src.retrieval.frozen_dense import FrozenDenseRetriever
    from src.retrieval.pdf_page_cache import FrozenPdfPages

    started = time.perf_counter()
    torch.set_num_threads(freeze.threads)
    index = bundle / "index"
    read_pinned(index / "index_manifest.json", corpus.index_manifest_sha256)
    embedding = json.loads(read_pinned(index / "embedding_manifest.json", corpus.embedding_manifest_sha256))
    if embedding["embedding_model_id"] != MODEL_NAME:
        raise ValueError("The final corpus must use the frozen Nomic embedding model")
    if sha256_file(index / "corpus_chunks.jsonl") != corpus.chunks_sha256:
        raise ValueError("Corpus chunk file differs from the reviewer freeze")
    chunks = load_frozen_corpus(index, index_id=corpus.index_id, fingerprint=corpus.fingerprint)
    documents = {item.document_id: item for item in corpus.filings}
    if {chunk["document_id"] for chunk in chunks} != documents.keys():
        raise ValueError("Indexed documents must match the frozen filing inventory")
    for chunk in chunks:
        filing = documents[chunk["document_id"]]
        if chunk["doc_name"] != filing.document_id or int(chunk["cik"]) != filing.cik or chunk["source_url"] != filing.source_url:
            raise ValueError("Indexed chunk provenance disagrees with the frozen filing inventory")
    for filing in corpus.filings:
        if sha256_file(bundle / "filings" / f"{filing.document_id}.pdf") != filing.document_sha256:
            raise ValueError("A source PDF differs from the frozen filing inventory")
    pages = FrozenPdfPages(bundle / "pages.jsonl", expected_sha256=corpus.pages_sha256)
    vectors = load_frozen_vectors(index, chunks, fingerprint=corpus.fingerprint)
    sec_manifest = json.loads(read_pinned(bundle / "sec/manifest.json", corpus.sec_manifest_sha256))
    issuers = {ticker: item["cik"] for ticker, item in sec_manifest["issuers"].items()}
    if not set(issuers.values()) <= {filing.cik for filing in corpus.filings}:
        raise ValueError("SEC snapshots include issuers outside the frozen corpus")
    sec = CompanyFactsReplay(bundle / "sec", issuers, latest_filed=freeze.filing_through.isoformat())
    ticker_by_cik = {cik: ticker for ticker, cik in issuers.items()}
    tickers = {chunk["company"]: ticker_by_cik[int(chunk["cik"])] for chunk in chunks if int(chunk["cik"]) in ticker_by_cik}
    router = ComplexityRouter(CorpusMap.from_chunks(chunks, index_generation_id=corpus.index_id))
    retriever = _RecordingRetriever(FrozenDenseRetriever(
        chunks, vectors, Embedder(device="cpu", revision=P1_EMBEDDING_REVISION), pdf_pages=pages,
        statement_ranker=FinancialStatementRanker(pages, router.extractor),
    ))
    graph = SpecialistResearchGraph(router=router, retriever=retriever, sec_client=sec, ticker_by_company=tickers)
    policy = _PolicyLayer(router.extractor)
    setup_ms = (time.perf_counter() - started) * 1000
    predictions = {arm: {} for arm in ARMS}
    for position, question in enumerate(questions):
        # Alternate the first arm to reduce systematic warm-up effects.
        for arm in ARMS if position % 2 == 0 else reversed(ARMS):
            observation, elapsed, _ = observe(question.question, question.case_id, arm, graph, None, retriever, sec, policy)
            row = asdict(observation)
            row["retrieved_sources"] = sorted(observation.retrieved_sources)
            predictions[arm][question.case_id] = dict(row, latency_ms=round(elapsed, 3))
    return {
        "git_sha": freeze.git_sha,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": _dependencies(),
        "setup_ms": round(setup_ms, 3),
        "peak_working_set_bytes": peak_memory_bytes(),
        "predictions": predictions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "predict", "score"))
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True, help="Reviewer-supplied sha256:<hex> before opening the question file")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--predictions-sha256", help="Prediction hash recorded before label release")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode in ("predict", "score") and args.output is None:
        parser.error("--output is required for predict and score")
    if args.mode == "score" and (args.predictions is None or not args.predictions_sha256):
        parser.error("--predictions and --predictions-sha256 are required for score")
    if args.output is not None:
        # Require a fresh local result file and avoid overwriting sealed inputs.
        root = Path(_git("rev-parse", "--show-toplevel"))
        output = args.output.resolve()
        if (output.exists() or not output.is_relative_to(root / "data") or not _git("check-ignore", "--", str(output))):
            parser.error("--output must be a new file under the repository's ignored data directory")
    with offline_socket_guard():
        bundle = args.bundle
        freeze = Freeze.model_validate_json(read_pinned(bundle / "freeze.json", args.freeze_sha256))
        if _git("rev-parse", "HEAD") != freeze.git_sha or _git("status", "--porcelain"):
            parser.error("Check out the exact frozen revision with a clean worktree")
        corpus = Corpus.model_validate_json(read_pinned(bundle / "corpus.json", freeze.corpus_sha256))
        exposed = read_rows(bundle / "exposed.jsonl", freeze.exposed_membership_sha256, Membership)
        questions = read_rows(bundle / "questions.jsonl", freeze.questions_sha256, Question)
        check_membership(freeze, exposed, corpus, questions)
        if args.mode == "preflight":
            print(f"Frozen cohort metadata passed for {len(questions)} cases. Labels were not opened.")
            return 0
        if args.mode == "predict":
            if platform.python_version() != freeze.python_version or _dependencies() != freeze.dependencies:
                raise ValueError("Python or installed dependency versions differ from the reviewer freeze")
            report = _predict(bundle, freeze, corpus, questions)
        else:
            predictions = json.loads(read_pinned(args.predictions, args.predictions_sha256))
            if predictions["git_sha"] != freeze.git_sha or predictions["freeze_sha256"] != args.freeze_sha256:
                raise ValueError("Prediction provenance differs from the reviewer freeze")
            if predictions["python"] != freeze.python_version or predictions["dependencies"] != freeze.dependencies:
                raise ValueError("Prediction dependency provenance differs from the reviewer freeze")
            labels = read_rows(bundle / "labels.jsonl", freeze.labels_sha256, Label)
            report = score_cohort(freeze, corpus, questions, labels, predictions["predictions"])
            report["predictions_sha256"] = args.predictions_sha256
            report["runtime"] = {key: value for key, value in predictions.items() if key != "predictions"}
        report["freeze_sha256"] = args.freeze_sha256
        report["corpus"] = corpus.model_dump(mode="json")
        report["configuration"] = freeze.model_dump(mode="json")
        write_json_atomic(output, report)
        print(sha256_file(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
