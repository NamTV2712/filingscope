"""Replay all M13 cases through the specialist graph and offline A–G probes."""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import defaultdict
from dataclasses import asdict, replace
from pathlib import Path

from configs.hard_negatives import P1_EMBEDDING_REVISION, P1_INDEX_ID
from configs.multi_agent_ablation import CASES, COMPANY_TICKERS, SEC_CUTOFF, SEC_ISSUERS
from configs.offline_guard import offline_socket_guard
from scripts.run_context_expansion import DEFAULT_PAGES, _read_parents
from scripts.run_financebench_retrieval import _sha256_file
from scripts.run_hard_negative_retrieval import DEFAULT_RUN, RANDOM_SEED, _load_corpus, _load_vectors, _peak_memory_bytes
from scripts.run_multi_agent_ablation import _PolicyLayer, _RecordingRetriever, _ledger_key, _specialist_observation
from scripts.run_retrieval_diagnostics import _write_json_atomic
from src.agent.complexity_router import ComplexityRouter, ExecutionPath
from src.evaluation.company_facts_replay import CompanyFactsReplay
from src.evaluation.failure_attribution import FailureSignal, FailureStage, attribution, summarize_failures
from src.evaluation.m13_failure_replay import (
    RequirementsOracleRouter, corrected_requirements, downstream_signals, expected_slots,
    lost_slots, prepare_page_oracles, quarterly_xbrl_overrides, resolution_signals, slot_supported, source_key, trace_row,
)
from src.evaluation.multi_agent_ablation import evaluate_observation, summarize_ablation
from src.evaluation.oracle_interventions import DiagnosticGraph, Oracle, OracleResult, draft_exists
from src.evaluation.post_m15_manifest import build_manifest
from src.research.corpus_map import CorpusMap
from src.retrieval.frozen_dense import FrozenDenseRetriever
from src.retrieval.parent_context import page_key


_DATA = Path("data/financebench")
_RUNS = _DATA / "ablation_runs"
_RANKING_PROBE_K = 50
_BOOTSTRAP_SAMPLES = 10_000


class DiagnosticRetriever(_RecordingRetriever):
    """Keep the original query in memory for a same-scope rank cutoff probe."""

    def __init__(self, index):
        super().__init__(index)
        self.requests = []

    def retrieve(self, query, top_k=10, *, document_ids=()):
        rows = super().retrieve(query, top_k, document_ids=document_ids)
        with self.lock:
            self.requests.append((query, top_k, document_ids))
        return rows

    def deeper_ranks(self, sources: set[str]) -> dict[str, int]:
        ranks = {}
        for query, top_k, scope in sorted(set(self.requests)):
            eligible = {source for source in sources if not scope or source.split("#p", 1)[0] in scope}
            if not eligible or top_k >= _RANKING_PROBE_K:
                continue
            for rank, row in enumerate(self.index.retrieve(query, _RANKING_PROBE_K, document_ids=scope), 1):
                source = source_key(row)
                if source in eligible and rank > top_k:
                    ranks[source] = min(ranks.get(source, rank), rank)
        return ranks


def _read_pages(chunks, path):
    locations = {source for case in CASES for slot in expected_slots(case) for source in slot.sources}
    children = defaultdict(list)
    for chunk in chunks:
        if source_key(chunk) in locations:
            children[page_key(chunk)].append(chunk)
    parents = _read_parents(path, set(children), children)
    return {source_key(children[key][0]): (children[key][0], page) for key, page in parents.items()}


def _run(case, variant, router, index, sec, *, oracle=None, injected=(), source_text_overrides=None):
    retriever = DiagnosticRetriever(index)
    graph = DiagnosticGraph(
        router=router, retriever=retriever, sec_client=sec, ticker_by_company=COMPANY_TICKERS,
        oracle=oracle, injected=injected, source_text_overrides=source_text_overrides,
    )
    started = time.perf_counter()
    before = sec.request_count
    result = graph.run(
        case.question, force_research=variant == "B4",
        request_id=f"{variant}-{case.case_id}" + (f"-oracle-{oracle}" if oracle else ""),
    )
    latency = (time.perf_counter() - started) * 1000
    observation = _specialist_observation(result, retriever, sec.request_count - before, _PolicyLayer(router.extractor))
    score = evaluate_observation(case, observation, latency_ms=latency)
    sources = {
        item.chunk_id: key for item in result.ledger_snapshot.evidence_records
        if item.chunk_id and (key := _ledger_key(item)) is not None
    }
    discovered = set(sources.values()) | {source_key(row) for row in retriever.chunks.values()}
    return graph, result, observation, score, sources, discovered, retriever


def _oracle_results(case, variant, baseline, paired, router, index, sec, slots, raw, aligned, xbrl_overrides):
    graph, result, observation, score, sources, _, _ = baseline
    if not case.claims or score["grounded_exact"]:
        return [OracleResult(oracle, False, "baseline did not fail") for oracle in Oracle]
    requirements = router.extractor.extract(case.question)
    defects = resolution_signals(case, requirements, slots)
    discovered_pages = {source_key(chunk) for chunk in graph.pre_policy if chunk.get("page_number") is not None}
    normalized = tuple(row for row in aligned if source_key(row) in discovered_pages)
    checks = []

    def record(oracle, reason, evaluated=None, *, bypass=False):
        checks.append(OracleResult(
            oracle, evaluated is not None, reason,
            (evaluated["grounded_exact"] and evaluated["unsupported_released_claims"] == 0)
            if evaluated is not None else None,
            evaluated["answered"] if evaluated is not None else None,
            ("DIAGNOSTIC_BYPASS" if bypass else evaluated["disposition"]) if evaluated is not None else None,
        ))

    if defects:
        corrected = corrected_requirements(case, router, slots)
        rerouted = RequirementsOracleRouter(router.corpus_map, corrected)
        record(Oracle.REQUIREMENTS, "independently labeled requirements", _run(
            case, variant, rerouted, index, sec, oracle=Oracle.REQUIREMENTS,
        )[3])
    else:
        record(Oracle.REQUIREMENTS, "issuer, metric, period and operation already agree with labels")
    if result.selected_path == ExecutionPath.FAST and paired[1].selected_path == ExecutionPath.RESEARCH:
        record(Oracle.ROUTE, "paired B4 route with SEC and table workers", paired[3])
    else:
        record(Oracle.ROUTE, "no missing research branch to add")
    if raw and graph.runtime is not None and not graph.runtime.require_structured_facts:
        record(Oracle.LOCATION, "supply full labeled PDF pages to existing extraction", _run(
            case, variant, router, index, sec, oracle=Oracle.LOCATION, injected=raw,
        )[3])
    else:
        record(Oracle.LOCATION, "no applicable labeled PDF page; SEC accession pins require a separate resolver probe")
    if normalized or xbrl_overrides:
        record(Oracle.NORMALIZED_FACTS, "supply source-aligned PDF or SEC observations already located by the run", _run(
            case, variant, router, index, sec, oracle=Oracle.NORMALIZED_FACTS, injected=normalized,
            source_text_overrides=xbrl_overrides,
        )[3])
    else:
        record(Oracle.NORMALIZED_FACTS, "no header-aligned observation on a retained labeled page")
    if result.coverage and not result.coverage.sufficient:
        record(Oracle.SUFFICIENCY, "force coverage decision; keep the production final verifier and independent scorer", _run(
            case, variant, router, index, sec, oracle=Oracle.SUFFICIENCY,
        )[3])
    else:
        record(Oracle.SUFFICIENCY, "no failing coverage decision to bypass")
    if result.coverage and result.coverage.sufficient:
        record(Oracle.CONSTRUCTION, "reference formatting of approved observations", _run(
            case, variant, router, index, sec, oracle=Oracle.CONSTRUCTION,
        )[3])
    else:
        record(Oracle.CONSTRUCTION, "reference formatter requires sufficient approved facts")
    if draft_exists(graph.draft):
        draft_sources = tuple(sources.get(chunk["chunk_id"]) for chunk in graph.draft_chunks)
        draft = replace(observation, answer=graph.draft, citation_sources=draft_sources)
        record(Oracle.VERIFICATION, "independent scoring of unreleased draft without final verifier",
               evaluate_observation(case, draft, latency_ms=0), bypass=True)
    else:
        record(Oracle.VERIFICATION, "writer emitted no draft")
    return checks


def _paired_comparison(scores):
    """Bootstrap issuer groups, merging the issuers in cross-company cases."""
    import numpy as np

    groups = []
    for case in CASES:
        if not case.claims:
            continue
        issuers = {slot.entity for slot in expected_slots(case)}
        overlapping = [group for group in groups if group.intersection(issuers)]
        groups = [group for group in groups if group not in overlapping]
        groups.append(issuers.union(*overlapping))
    group_by_issuer = {issuer: index for index, group in enumerate(groups) for issuer in group}
    totals, changes = [0] * len(groups), [0] * len(groups)
    differences = []
    for case, b4, b5 in zip(CASES, scores["B4"], scores["B5"], strict=True):
        if not case.claims:
            continue
        group = group_by_issuer[expected_slots(case)[0].entity]
        change = int(b4["grounded_exact"]) - int(b5["grounded_exact"])
        totals[group] += 1
        changes[group] += change
        if change:
            differences.append({"case_id": case.case_id, "difference": change})
    rng = random.Random(RANDOM_SEED)
    replicates = []
    for _ in range(_BOOTSTRAP_SAMPLES):
        drawn = rng.choices(range(len(groups)), k=len(groups))
        replicates.append(sum(changes[index] for index in drawn) / sum(totals[index] for index in drawn))
    return {
        "direction": "B4 minus B5",
        "grounded_exact_delta": sum(changes) / sum(totals),
        "grounded_exact_delta_ci95": np.percentile(replicates, [2.5, 97.5]).tolist(),
        "answerable_pairs": sum(totals),
        "issuer_groups": len(groups),
        "changed_cases": differences,
    }


def replay(args):
    import numpy as np
    import torch

    from src.retrieval.embedder import Embedder

    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    torch.manual_seed(RANDOM_SEED)
    torch.set_num_threads(args.threads)
    historical = json.loads(args.baseline.read_text(encoding="utf-8"))
    frozen = {
        variant: {row["case_id"]: row for row in historical["variants"][variant]["per_case"]}
        for variant in ("B4", "B5")
    }
    started = time.perf_counter()
    chunks = _load_corpus(args.p1_run)
    vectors = _load_vectors(args.p1_run, chunks)
    index = FrozenDenseRetriever(chunks, vectors, Embedder(device="cpu", revision=P1_EMBEDDING_REVISION))
    router = ComplexityRouter(CorpusMap.from_chunks(chunks, index_generation_id=P1_INDEX_ID))
    sec = CompanyFactsReplay(args.sec_dir, SEC_ISSUERS, latest_filed=SEC_CUTOFF)
    page_manifest = json.loads(args.pages.with_suffix(".json").read_text(encoding="utf-8"))
    if page_manifest["pages_sha256"] != _sha256_file(args.pages):
        raise ValueError("Extracted page cache does not match its manifest")
    source_manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    source_hashes = {row["doc_name"]: row["sha256"] for row in source_manifest["files"]["source_pdfs"]}
    if {row["doc_name"]: row["sha256"] for row in page_manifest["source_pdf_hashes"]} != source_hashes:
        raise ValueError("Extracted page inventory does not match the source PDF inventory")
    pages = _read_pages(chunks, args.pages)
    setup_seconds = time.perf_counter() - started
    traces, scores = {"B4": [], "B5": []}, {"B4": [], "B5": []}
    for case in CASES:
        print(f"replaying {case.case_id}", flush=True)
        slots = expected_slots(case)
        raw, aligned = prepare_page_oracles(slots, pages)
        paired = _run(case, "B4", router, index, sec)
        routed = _run(case, "B5", router, index, sec)
        b4_sec_slots = {
            slot.key for slot in slots
            if slot_supported(paired[1].coverage, slot, {
                key: value for key, value in paired[4].items() if value.startswith("sec:")
            })
        }
        for variant, baseline in (("B4", paired), ("B5", routed)):
            graph, result, _, score, source_ids, discovered, retriever = baseline
            control = frozen[variant][case.case_id]
            changed = {field for field in score if field not in {"latency_ms", "answer"} and score[field] != control[field]}
            # In-memory tuples serialize to arrays in the frozen JSON.
            changed = {field for field in changed if json.loads(json.dumps(score[field])) != control[field]}
            if changed:
                raise ValueError(f"Replay drift for {variant}/{case.case_id}: {sorted(changed)}")
            traces_for_run = trace_row(
                case, graph, result, score, slots, tuple(sorted(set(retriever.chunks) | source_ids.keys())),
            )
            failed = not score["grounded_exact"]
            xbrl_overrides = quarterly_xbrl_overrides(graph, result, slots)
            probes = _oracle_results(case, variant, baseline, paired, router, index, sec, slots, raw, aligned, xbrl_overrides)
            signals = resolution_signals(case, router.extractor.extract(case.question), slots)
            if case.intended_path == ExecutionPath.RESEARCH and result.selected_path != ExecutionPath.RESEARCH:
                signals.append(FailureSignal(FailureStage.COMPLEXITY_ROUTING, "required RESEARCH branch did not run"))
            losses, details = lost_slots(
                slots, graph, result, source_ids, discovered, raw, aligned, b4_sec_slots, xbrl_overrides,
            )
            missing_pages = {source_key(row) for row in raw} - discovered
            deeper_ranks = retriever.deeper_ranks(missing_pages) if failed else {}
            for index_in_losses, signal in enumerate(losses):
                if signal.stage != FailureStage.CANDIDATE_RETRIEVAL:
                    continue
                slot_sources = next(slot.sources for slot in slots if slot.key == signal.slot)
                ranks = {source: deeper_ranks[source] for source in slot_sources if source in deeper_ranks}
                if ranks:
                    losses[index_in_losses] = FailureSignal(
                        FailureStage.RANKING, f"labeled page ranked below production top-k: {ranks}", signal.slot,
                    )
            signals.extend(losses)
            signals.extend(downstream_signals(
                graph, result, any(probe.intervention == Oracle.VERIFICATION
                                   and probe.independently_grounded_exact for probe in probes),
                bool(slots) and all(slot_supported(result.coverage, slot, source_ids) for slot in slots),
            ))
            traces_for_run.update(attribution(signals, failed=failed))
            assessed = [probe for probe in probes if probe.executed]
            traces_for_run.update(
                slot_diagnostics=details,
                exact_supported_slots=[slot.key for slot in slots if slot_supported(result.coverage, slot, source_ids)],
                retrieved_source_ids=sorted(discovered),
                candidate_source_ids=source_ids,
                deeper_pdf_ranks=deeper_ranks,
                oracle_recoverable=any(probe.independently_grounded_exact for probe in assessed) if assessed else None,
                oracle_results=[asdict(probe) for probe in probes],
            )
            traces[variant].append(traces_for_run)
            scores[variant].append(score)
    return {
        "benchmark": "filingscope-post-m15-failure-attribution-v1",
        "configuration": {"variants": list(traces), "threads": args.threads, "random_seed": RANDOM_SEED,
                          "providers": [], "corpus_engine": "FrozenDenseRetriever", "ranking_probe_k": _RANKING_PROBE_K,
                          "bootstrap_samples": _BOOTSTRAP_SAMPLES},
        "baseline_sha256": _sha256_file(args.baseline),
        "setup_seconds": round(setup_seconds, 3), "peak_memory_bytes": _peak_memory_bytes(),
        "provider_calls": 0, "sec_http_calls": 0,
        "paired_comparison": _paired_comparison(scores),
        "variants": {variant: {
            "quality": summarize_ablation(scores[variant]),
            "attribution": summarize_failures(rows),
            "per_case": rows,
        } for variant, rows in traces.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p1-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--sec-dir", type=Path, default=_RUNS / "m13-sec")
    parser.add_argument("--pages", type=Path, default=DEFAULT_PAGES)
    parser.add_argument("--source-manifest", type=Path, default=_DATA / "source_manifest.json")
    parser.add_argument("--baseline", type=Path, default=_RUNS / "post-m15-baseline.json")
    parser.add_argument("--historical", type=Path, default=_RUNS / "m13-results.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.threads <= 16:
        parser.error("threads must be between 1 and 16")
    paths = [args.output, args.manifest, args.baseline, args.historical]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("benchmark inputs and outputs must use distinct paths")
    with offline_socket_guard():
        report = replay(args)
    _write_json_atomic(args.output, report)
    manifest = build_manifest(
        p1_run=args.p1_run, source_manifest=args.source_manifest, sec_manifest=args.sec_dir / "manifest.json",
        pages=args.pages, artifacts={"baseline": args.baseline, "historical_m13": args.historical, "q1": args.output},
        configuration=report["configuration"],
    )
    _write_json_atomic(args.manifest, manifest)
    print(args.output, flush=True)


if __name__ == "__main__":
    main()
