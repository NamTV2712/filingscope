"""Attribute a frozen public replay and test raw-page location interventions."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from pydantic import TypeAdapter

from configs.financebench import P1_EMBEDDING_REVISION
from configs.offline_guard import offline_socket_guard
from scripts.prepare_independent_corpus import FilingInput
from scripts.run_finrank_external import DATA_SHA256, _cases, _gold_pages, _normalize
from scripts.run_multi_agent_ablation import _PolicyLayer, _RecordingRetriever
from scripts.run_specialist_architectures import observe
from src.agent.complexity_router import ComplexityRouter
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.company_facts_replay import CompanyFactsReplay
from src.evaluation.failure_attribution import FailureSignal, FailureStage, attribution
from src.evaluation.independent_final import ARMS, Corpus, read_pinned
from src.evaluation.oracle_interventions import DiagnosticGraph, Oracle
from src.ingestion.chunker import count_tokens
from src.research.corpus_map import CorpusMap
from src.retrieval.canonical_json import sha256_file
from src.retrieval.embedder import Embedder
from src.retrieval.financial_statement_ranker import FinancialStatementRanker
from src.retrieval.frozen_artifacts import load_frozen_corpus, load_frozen_vectors
from src.retrieval.frozen_dense import FrozenDenseRetriever
from src.retrieval.pdf_page_cache import FrozenPdfPages


def failure_signals(reasons: tuple[str, ...], observation: dict, gold_pages: tuple[str, ...] | None) -> list[FailureSignal]:
    """Attribute only boundaries with observed evidence of a loss."""
    stages = {
        "company_not_resolved": FailureStage.ENTITY_RESOLUTION,
        "metric_not_recognized": FailureStage.METRIC_RESOLUTION,
        "insufficient_period_scope": FailureStage.PERIOD_RESOLUTION,
    }
    signals = [FailureSignal(stages[reason], reason) for reason in reasons if reason in stages]
    if observation["disposition"] == "UNSUPPORTED":
        signals.extend(FailureSignal(FailureStage.COMPLEXITY_ROUTING, reason) for reason in reasons if reason not in stages)
    elif gold_pages and not set(gold_pages) <= set(observation["retrieved_sources"]):
        signals.append(FailureSignal(FailureStage.CANDIDATE_RETRIEVAL, "mapped_reference_page_not_retrieved"))
    elif observation["finally_missing"]:
        signals.append(FailureSignal(FailureStage.EVIDENCE_SET_SUFFICIENCY, "required_slots_unresolved_after_retrieval"))
    elif observation["disposition"] == "REJECTED":
        signals.append(FailureSignal(FailureStage.CLAIM_VERIFICATION, "final_verifier_rejected_answer"))
    return signals


class PageInterventionRetriever(_RecordingRetriever):
    """Supply unmodified mapped page text through the normal retrieval interface."""

    def __init__(self, index, chunks: tuple[dict, ...]):
        super().__init__(index)
        self.injected = chunks

    def retrieve(self, query: str, top_k: int = 10, *, document_ids: tuple[str, ...] = ()) -> list[dict]:
        rows = [row for row in self.injected if not document_ids or row["doc_name"] in document_ids][:top_k]
        with self.lock:
            self.calls.append((" ".join(query.casefold().split()), document_ids, tuple(row["chunk_id"] for row in rows)))
            self.chunks.update((row["chunk_id"], row) for row in rows)
        return rows

    def retrieve_statement_candidates(self, document_ids, kind, *, top_k):
        self.statement_calls += 1
        return self.retrieve("oracle statement pages", top_k=top_k, document_ids=tuple(document_ids))


class CaptureGraph(DiagnosticGraph):
    def run(self, *args, **kwargs):
        self.execution = super().run(*args, **kwargs)
        return self.execution


def diagnose(bundle: Path, dataset: Path, baseline_path: Path, baseline_sha256: str, *, cutoff: str, threads: int) -> dict:
    import torch

    torch.set_num_threads(threads)
    source_paths = subprocess.check_output(["git", "ls-files", "src", "scripts", "configs"], text=True).splitlines()
    source_hashes = {path: sha256_file(Path(path)) for path in source_paths}
    source_hashes[__file__] = sha256_file(Path(__file__))
    corpus = Corpus.model_validate_json((bundle / "corpus.json").read_bytes())
    inventory = TypeAdapter(list[FilingInput]).validate_json((bundle / "filing-inventory.json").read_bytes())
    filings = {row.ticker: row for row in inventory}
    items = sorted(_cases(dataset, filings, 2025), key=lambda row: row["id"])
    saved = json.loads(read_pinned(baseline_path, baseline_sha256))["predictions"]
    case_ids = {item["id"] for item in items}
    if set(saved) != set(ARMS) or any(set(rows) != case_ids for rows in saved.values()):
        raise ValueError("Baseline membership differs from the pinned public slice")
    pages = defaultdict(dict)
    for line in read_pinned(bundle / "pages.jsonl", corpus.pages_sha256).splitlines():
        page = json.loads(line)
        pages[page["doc_name"]][page["page_number"]] = page["text"]
    normalized = {document: {number: _normalize(text) for number, text in rows.items()} for document, rows in pages.items()}
    index_dir = bundle / "index"
    read_pinned(index_dir / "index_manifest.json", corpus.index_manifest_sha256)
    chunks = load_frozen_corpus(index_dir, index_id=corpus.index_id, fingerprint=corpus.fingerprint)
    vectors = load_frozen_vectors(index_dir, chunks, fingerprint=corpus.fingerprint)
    router = ComplexityRouter(CorpusMap.from_chunks(chunks, index_generation_id=corpus.index_id))
    pdf_pages = FrozenPdfPages(bundle / "pages.jsonl", expected_sha256=corpus.pages_sha256)
    index = FrozenDenseRetriever(chunks, vectors, Embedder(device="cpu", revision=P1_EMBEDDING_REVISION),
                                 pdf_pages=pdf_pages, statement_ranker=FinancialStatementRanker(pdf_pages, router.extractor))
    sec_manifest = json.loads(read_pinned(bundle / "sec/manifest.json", corpus.sec_manifest_sha256))
    sec = CompanyFactsReplay(bundle / "sec", {ticker: row["cik"] for ticker, row in sec_manifest["issuers"].items()}, latest_filed=cutoff)
    policy = _PolicyLayer(router.extractor)
    recording = _RecordingRetriever(index)
    graph = CaptureGraph(router=router, retriever=recording, sec_client=sec)
    rows, oracle_rows = [], []
    for item in items:
        filing = filings[item["ticker"]]
        question = f"{item['question']} Filing context: {filing.company} ({filing.ticker}), Form 10-K for FY{filing.fiscal_year}."
        gold = _gold_pages(item["passages"], normalized[filing.document_id], filing.document_id)
        for arm in ARMS:
            route = router.route(question, force_research=arm == "B_adaptive", source_inventory=graph.source_inventory)
            requirements = router.extractor.extract(question)
            reasons = tuple(dict.fromkeys((*requirements.unsupported_reasons, *route.decision.reason_codes)))
            observed, _, details = observe(question, item["id"], arm, graph, None, recording, sec, policy)
            current = asdict(observed)
            current["retrieved_sources"] = sorted(observed.retrieved_sources)
            stable = ("answer", "disposition", "retrieved_sources", "citation_sources", "tool_calls", "llm_calls")
            for key in stable:
                value = list(current[key]) if isinstance(current[key], tuple) else current[key]
                if value != saved[arm][item["id"]][key]:
                    raise ValueError(f"Baseline changed for {arm}/{item['id']}/{key}")
            verification = None
            coverage = None
            if arm == "C_routed":
                result = graph.execution
                verification = result.verification.model_dump(mode="json") if result.verification else None
                coverage = result.coverage.model_dump(mode="json") if result.coverage else None
            row = {"case_id": item["id"], "arm": arm, "ticker": item["ticker"], "route": route.selected_path,
                   "reason_codes": reasons, "routing_reason_codes": route.decision.reason_codes,
                   "requirement_reason_codes": requirements.unsupported_reasons, "gold_pages": gold, "observation": current,
                   "coverage": coverage, "verification": verification,
                   "verification_note": "captured_routed_result" if arm == "C_routed" else "adaptive_observation_has_no_claim_adjudication_payload",
                   "details": details, **attribution(failure_signals(reasons, current, gold), failed=True)}
            rows.append(row)
        if gold is not None:
            raw = []
            for source in gold:
                document, number = source.rsplit("#p", 1)
                original = next(row for row in chunks if row["doc_name"] == document and row["page_number"] == int(number))
                text = pages[document][int(number)]
                raw.append({**original, "chunk_id": f"oracle-location:{document}:{number}", "text": text,
                            "token_count": count_tokens(text)})
            injected = PageInterventionRetriever(index, tuple(raw))
            intervention_graph = CaptureGraph(oracle=Oracle.LOCATION, router=router, retriever=injected, sec_client=sec)
            for arm in ARMS:
                observed, _, details = observe(question, item["id"], arm, intervention_graph, None, injected, sec, policy)
                data = asdict(observed)
                data["retrieved_sources"] = sorted(observed.retrieved_sources)
                verification = intervention_graph.execution.verification if arm == "C_routed" else None
                oracle_rows.append({"case_id": item["id"], "arm": arm, "oracle": Oracle.LOCATION,
                                    "supplied_pages": gold, "reader_invoked": bool(observed.tool_calls),
                                    "verification": verification.model_dump(mode="json") if verification else None,
                                    "observation": data, "details": details})
        print(item["id"], flush=True)
    if any(sha256_file(Path(path)) != expected for path, expected in source_hashes.items()):
        raise ValueError("Source files changed during the diagnostic replay")
    return {"configuration": {"git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                               "baseline_sha256": baseline_sha256, "corpus_sha256": sha256_file(bundle / "corpus.json"),
                               "dataset_sha256": DATA_SHA256, "threads": threads, "cutoff": cutoff,
                               "source_sha256": source_hashes,
                               "oracle": "raw full mapped page substitution; unchanged requirements, routing, readers and verification",
                               "providers": [], "oracle_changes_route": False},
            "summary": {arm: {"cases": sum(row["arm"] == arm for row in rows),
                              "first_failure_stages": dict(Counter(row["first_failure_stage"] for row in rows if row["arm"] == arm)),
                              "dispositions": dict(Counter(row["observation"]["disposition"] for row in rows if row["arm"] == arm)),
                              "native_routing_rejections": dict(Counter(reason for row in rows if row["arm"] == arm
                                                                         and row["observation"]["disposition"] == "UNSUPPORTED"
                                                                         for reason in row["routing_reason_codes"])),
                              "oracle_cases": sum(row["arm"] == arm for row in oracle_rows),
                              "oracle_dispositions": dict(Counter(row["observation"]["disposition"] for row in oracle_rows if row["arm"] == arm)),
                              "oracle_reader_invoked": sum(row["reader_invoked"] for row in oracle_rows if row["arm"] == arm)} for arm in ARMS},
            "per_case": rows, "location_interventions": oracle_rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--baseline-sha256", required=True)
    parser.add_argument("--cutoff", default="2025-12-31")
    parser.add_argument("--threads", type=int, choices=range(1, 17), default=6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    if args.output.exists() or not args.output.resolve().is_relative_to(root / "data"):
        parser.error("Use a new output under ignored data")
    with offline_socket_guard():
        report = diagnose(args.bundle, args.dataset, args.baseline, args.baseline_sha256, cutoff=args.cutoff, threads=args.threads)
    write_json_atomic(args.output, report)
    print(json.dumps(report["summary"], indent=2))
    print(sha256_file(args.output))


if __name__ == "__main__":
    main()
