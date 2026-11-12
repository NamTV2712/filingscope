"""Compare solo and specialist workflows on fixed financial questions."""

from __future__ import annotations

import argparse
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from configs.hard_negatives import P1_CORPUS_FINGERPRINT, P1_EMBEDDING_REVISION, P1_INDEX_ID
from configs.multi_agent_ablation import CASES, COMPANY_TICKERS, SEC_CUTOFF, SEC_ISSUERS
from scripts.run_hard_negative_retrieval import DEFAULT_RUN, SPLITS, _load_corpus, _load_vectors, _peak_memory_bytes, _QueryFilters
from scripts.run_retrieval_diagnostics import _write_json_atomic
from src.agent.adaptive_retrieval import AdaptiveRetrievalBudget, AdaptiveRetrievalController
from src.agent.complexity_router import RESEARCH_BUDGET, ComplexityRouter, ExecutionPath, RouterExecution
from src.agent.specialist_graph import SpecialistExecution, SpecialistResearchGraph, _ordered_report_chunks, _render_calculations, _render_lookup
from src.agent.specialists import EvidenceAnalyst, FinancialReasoner, SpecialistRuntime
from src.decision.models import CoverageStatus, DecisionBudget
from src.decision.policy import EvidenceDecisionLayer
from src.evaluation.company_facts_replay import CompanyFactsReplay, acquire_company_facts
from src.evaluation.multi_agent_ablation import AblationObservation, evaluate_observation, summarize_ablation
from src.ingestion.chunker import count_tokens
from src.ledger.evidence_ledger import EvidenceLedger
from src.ledger.models import EvidenceRecord, EvidenceSourceType
from src.policy.candidate_gate import CandidateEvidenceGate
from src.policy.evidence_policy import CandidateDisposition
from src.research.corpus_map import CorpusMap
from src.retrieval.frozen_dense import FrozenDenseRetriever
from src.retrieval.pdf_page_cache import FrozenPdfPages
from src.verification.atomic_claim_verifier import AtomicClaimVerifier
from src.verification.claim_verifier import ClaimLevelVerifier
from src.verification.response_policy import INSUFFICIENT_EVIDENCE_ANSWER, verify_and_release


VARIANTS = {
    "A0": "dense plus deterministic report writer",
    "A1": "A0 with query metadata mask",
    "A2": "A0 with P2 evidence sufficiency",
    "A3": "A2 with P3 adaptive retrieval",
    "A4": "A3 with candidate policy and M11 release",
    "B0": "finite router with candidate policy and bounded solo adaptive retrieval",
    "B1": "forced RESEARCH specialists with ledger and question-only planner",
    "B2": "B1 with Corpus Map and planner document scopes",
    "B3": "B2 with SEC Company Facts replay",
    "B4": "B3 with M11 release",
    "B5": "B4 with FAST/RESEARCH selection",
}


class _RecordingRetriever:
    supports_concurrent_retrieval = True
    supports_document_scope = True

    def __init__(self, index: FrozenDenseRetriever, *, use_metadata: bool = False):
        self.index = index
        self.filters = _QueryFilters(index.chunks) if use_metadata else None
        self.calls: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
        self.chunks: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def reset(self) -> None:
        self.calls.clear()
        self.chunks.clear()

    def get_source_page(self, document: str, page_number: int) -> str | None:
        return self.index.get_source_page(document, page_number)

    def retrieve(self, query: str, top_k: int = 10, *, document_ids: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        eligible = self.filters.mask(query)[1] if self.filters is not None else None
        chunks = self.index.retrieve(query, top_k, document_ids=document_ids, eligible=eligible)
        with self.lock:
            self.calls.append((" ".join(query.casefold().split()), document_ids, tuple(row["chunk_id"] for row in chunks)))
            self.chunks.update((row["chunk_id"], row) for row in chunks)
        return chunks

    def usage(self) -> dict[str, int]:
        return {
            "retrieval_calls": len(self.calls),
            "duplicate_retrievals": len(self.calls) - len({(query, scope) for query, scope, _ in self.calls}),
            "duplicate_candidates": sum(len(ids) for _, _, ids in self.calls) - len(self.chunks),
        }


class _PolicyLayer(EvidenceDecisionLayer):
    def __init__(self, extractor):
        super().__init__(extractor=extractor)
        self.gate = CandidateEvidenceGate()

    def assess(self, question, chunks):
        requirements = self.extractor.extract(question)
        retained, _ = self.gate.screen(requirements, list(chunks), self)
        return self.analyzer.analyze(requirements, retained)


def _pdf_key(row: dict[str, Any]) -> str:
    return f"{row['doc_name']}#p{row['page_number']}"


def _ledger_key(record: EvidenceRecord) -> str | None:
    if record.xbrl_provenance is not None:
        return f"sec:{record.xbrl_provenance.accession}"
    if record.document_id and record.page is not None:
        return f"{record.document_id}#p{record.page - 1}"
    return None


def _missing(coverage) -> tuple[str, ...]:
    if coverage is None:
        return ()
    return tuple(sorted({*coverage.missing_requirement_ids, *coverage.conflicted_requirement_ids}))


def _planned(route: RouterExecution | None) -> tuple[str, ...]:
    if route is None or route.research_plan is None:
        return ()
    return tuple(sorted({item for task in route.research_plan.tasks for item in task.requirement_ids}))


def _task_counts(route: RouterExecution | None, coverage) -> tuple[int, int]:
    if route is None or route.research_plan is None:
        return 0, 0
    found = {item.requirement_id for item in coverage.findings if item.status == CoverageStatus.FOUND} if coverage else set()
    tasks = [item for item in route.research_plan.tasks if item.requirement_ids]
    return len(tasks), sum(found.issuperset(item.requirement_ids) for item in tasks)


def _evidence_tokens(chunks) -> int:
    return sum(chunk.get("token_count") or count_tokens(chunk["text"]) for chunk in chunks)


def _render_solo(question, requirements, decision_layer, coverage, chunks, *, require_sufficiency):
    if require_sufficiency and not coverage.sufficient:
        return INSUFFICIENT_EVIDENCE_ANSWER
    ledger = EvidenceLedger("solo-renderer")
    runtime = SpecialistRuntime("solo-renderer", ledger, RESEARCH_BUDGET, requirements, None, decision_layer=decision_layer)
    runtime.source_chunks.update((row["chunk_id"], row) for row in chunks)
    runtime.coverage = coverage
    if any(op.operation in {"growth", "difference"} for op in requirements.operations) and coverage.sufficient:
        for row in chunks:
            record = ledger.add_evidence(EvidenceRecord.from_source(
                request_id=runtime.request_id, document_id=row["document_id"], chunk_id=row["chunk_id"],
                page=row["page_number"] + 1, company=row["company"], source_url=row["source_url"],
                source_type=EvidenceSourceType.TEXT_EVIDENCE,
            ))
            runtime.preferred_evidence_by_chunk_id[row["chunk_id"]] = record.evidence_id
        EvidenceAnalyst().run(question, runtime)
        FinancialReasoner().run(runtime)
        if calculated := _render_calculations(runtime):
            return calculated
        if require_sufficiency:
            return INSUFFICIENT_EVIDENCE_ANSWER
    return _render_lookup(runtime) or INSUFFICIENT_EVIDENCE_ANSWER


def _solo(
    variant: str, question: str, retriever: _RecordingRetriever, layer: EvidenceDecisionLayer,
    route: RouterExecution | None,
) -> AblationObservation:
    requirements = layer.extractor.extract(question)
    requested = tuple(item.requirement_id for item in requirements.evidence)
    if route is not None and route.selected_path == ExecutionPath.UNSUPPORTED:
        return AblationObservation(disposition="UNSUPPORTED", execution_path=route.selected_path, requested_requirements=requested,
                                   graph_steps=route.graph_steps_used, trace=route.route_trace)
    adaptive = variant in {"A3", "A4", "B0"}
    budget = route.budget if route else RESEARCH_BUDGET
    initial = retriever.retrieve(question, top_k=min(10, budget.max_candidate_chunks))
    initial_decision = layer.decide(question, initial, budget=DecisionBudget(remaining_retrieval_attempts=int(adaptive)))
    coverage = initial_decision.coverage
    retained = initial
    trace = [*(route.route_trace if route else ()), "dense_retrieval"]
    if adaptive:
        result = AdaptiveRetrievalController(retriever, decision_layer=layer).run(
            question, initial, budget=AdaptiveRetrievalBudget(
                max_rounds=min(2, budget.max_retrieval_calls - 1), max_queries=min(2, budget.max_retrieval_calls - 1),
                max_evidence_tokens=budget.max_context_tokens, top_k=5,
            ),
        )
        retained = list(result.evidence_chunks)
        coverage = result.final_decision.coverage
        trace.extend(f"adaptive:{entry.outcome}" for entry in result.trace)
    decisions = ()
    if isinstance(layer, _PolicyLayer):
        retained, decisions = layer.gate.screen(requirements, retained, layer)
    chunks = sorted(retained, key=lambda row: row["chunk_id"])
    answer = _render_solo(question, requirements, layer, coverage, chunks, require_sufficiency=variant not in {"A0", "A1"})
    passes = 0
    if variant == "A4":
        release = verify_and_release(AtomicClaimVerifier(catalog=layer.catalog), question, answer, chunks, requirements)
        answer, verification, passes = release.answer, release.result, release.correction_passes
    else:
        verification = ClaimLevelVerifier(catalog=layer.catalog).verify(question, answer, chunks)
    planned_tasks, completed_tasks = _task_counts(route, coverage)
    return AblationObservation(
        answer=answer, disposition=verification.disposition.value, citation_sources=tuple(map(_pdf_key, chunks)),
        retrieved_sources=frozenset(map(_pdf_key, retriever.chunks.values())),
        execution_path=route.selected_path if route else None, planned_requirements=_planned(route), requested_requirements=requested,
        initially_missing=_missing(initial_decision.coverage), finally_missing=_missing(coverage),
        graph_steps=route.graph_steps_used if route else 0, tool_calls=len(retriever.calls), **retriever.usage(),
        evidence_tokens=_evidence_tokens(chunks), screened_slots=len(decisions),
        rejected_slots=sum(item.disposition == CandidateDisposition.REJECT for item in decisions),
        verified_claims=verification.supported_claim_count, correction_passes=passes,
        planned_tasks=planned_tasks, completed_tasks=completed_tasks,
        trace=(*trace, "report_writer", "claim_verifier"),
    )


def _specialist_observation(
    result: SpecialistExecution, retriever: _RecordingRetriever, sec_calls: int, policy_layer: _PolicyLayer,
) -> AblationObservation:
    snapshot = result.ledger_snapshot
    records = {record.evidence_id: record for record in snapshot.evidence_records}
    retrieved = {_ledger_key(item) for item in records.values()}
    retrieved.update(map(_pdf_key, retriever.chunks.values()))
    requirements = snapshot.question_requirements
    filing_ids = {record.chunk_id for record in records.values() if "filing_research_worker" in record.discovered_by}
    initial_coverage = policy_layer.assess(
        result.question, [retriever.chunks[item] for item in sorted(filing_ids.intersection(retriever.chunks))],
    ) if result.selected_path != ExecutionPath.UNSUPPORTED else None
    planned_tasks, completed_tasks = _task_counts(result.route, result.coverage)
    verification_links = tuple(
        evidence_id for claim in result.verification.claims for evidence_id in claim.evidence_ids
    ) if result.verification else ()
    return AblationObservation(
        answer=result.answer, disposition=result.status,
        citation_sources=tuple(_ledger_key(records[evidence_id]) for evidence_id in result.citation_evidence_ids),
        retrieved_sources=frozenset(item for item in retrieved if item is not None),
        execution_path=result.selected_path, planned_requirements=_planned(result.route),
        requested_requirements=tuple(item.requirement_id for item in requirements.evidence) if requirements else (),
        initially_missing=_missing(initial_coverage), finally_missing=_missing(result.coverage),
        graph_steps=result.route.graph_steps_used + result.usage.graph_steps,
        tool_calls=result.usage.tool_calls, sec_calls=sec_calls, **retriever.usage(),
        evidence_tokens=result.usage.evidence_tokens, llm_calls=result.usage.llm_calls,
        screened_slots=len(result.candidate_decisions),
        rejected_slots=sum(item.disposition == CandidateDisposition.REJECT for item in result.candidate_decisions),
        verified_claims=result.verification.supported_claim_count if result.verification else 0,
        planned_tasks=planned_tasks, completed_tasks=completed_tasks,
        handoff_links=len(verification_links),
        resolved_handoff_links=sum(evidence_id in records for evidence_id in verification_links),
        correction_passes=result.usage.correction_passes, trace=(*result.route.route_trace, *result.graph_trace),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p1-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--statement-pages", type=Path, help="Use the pinned physical PDF pages for financial normalization")
    parser.add_argument("--sec-dir", type=Path, default=Path("data/financebench/ablation_runs/m13-sec"))
    parser.add_argument("--acquire-sec", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--split", choices=SPLITS)
    parser.add_argument("--variants", nargs="+", choices=tuple(VARIANTS), default=list(VARIANTS))
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.threads <= 16:
        parser.error("threads must be between 1 and 16")
    if args.acquire_sec:
        from configs.settings import settings

        acquire_company_facts(args.sec_dir, SEC_ISSUERS, latest_filed=SEC_CUTOFF, user_agent=settings.sec_user_agent)
        if args.output is None:
            return
    if args.output is None:
        parser.error("--output is required for scoring")

    import torch

    from src.retrieval.embedder import Embedder

    torch.set_num_threads(args.threads)
    started = time.perf_counter()
    chunks = _load_corpus(args.p1_run)
    vectors = _load_vectors(args.p1_run, chunks)
    embedder = Embedder(device="cpu", revision=P1_EMBEDDING_REVISION)
    pages = FrozenPdfPages.from_run(args.statement_pages, args.p1_run) if args.statement_pages else None
    index = FrozenDenseRetriever(chunks, vectors, embedder, pdf_pages=pages)
    corpus = CorpusMap.from_chunks(chunks, index_generation_id=P1_INDEX_ID)
    basic_router, aware_router = ComplexityRouter(), ComplexityRouter(corpus)
    sec = CompanyFactsReplay(args.sec_dir, SEC_ISSUERS, latest_filed=SEC_CUTOFF) if set(args.variants) & {"B3", "B4", "B5"} else None
    setup_seconds = time.perf_counter() - started
    cases = [case for case in CASES if args.split is None or case.split == args.split]
    rows_by_variant = {}
    for variant in dict.fromkeys(args.variants):
        print(f"running {variant} on {len(cases)} cases", flush=True)
        retriever = _RecordingRetriever(index, use_metadata=variant == "A1")
        router = basic_router if variant in {"B0", "B1"} else aware_router
        extractor = router.extractor
        layer = _PolicyLayer(extractor) if variant in {"A4", "B0"} else EvidenceDecisionLayer(extractor=extractor)
        specialist_policy = _PolicyLayer(extractor)
        graph = None
        use_sec = sec if variant in {"B3", "B4", "B5"} else None
        if variant in {"B1", "B2", "B3", "B4", "B5"}:
            graph = SpecialistResearchGraph(
                router=router, retriever=retriever, sec_client=use_sec, ticker_by_company=COMPANY_TICKERS,
                verifier=ClaimLevelVerifier(catalog=extractor.catalog) if variant in {"B1", "B2", "B3"} else None,
            )
        rows = []
        for case in cases:
            retriever.reset()
            started = time.perf_counter()
            if graph is None:
                route = router.route(case.question) if variant == "B0" else None
                observed = _solo(variant, case.question, retriever, layer, route)
                latency_ms = (time.perf_counter() - started) * 1000
            else:
                route = router.route(case.question, force_research=variant != "B5")
                before = use_sec.request_count if use_sec else 0
                result = graph.run(case.question, route=route, request_id=f"{variant}-{case.case_id}")
                latency_ms = (time.perf_counter() - started) * 1000
                observed = _specialist_observation(result, retriever, use_sec.request_count - before if use_sec else 0, specialist_policy)
            row = evaluate_observation(case, observed, latency_ms=latency_ms)
            row["retrieval_trace"] = sorted(retriever.calls)
            rows.append(row)
        rows_by_variant[variant] = rows

    report = {
        "benchmark": "filingscope-multi-agent-ablation-v1", "p1_index_id": P1_INDEX_ID,
        "corpus_fingerprint": P1_CORPUS_FINGERPRINT, "embedding_revision": P1_EMBEDDING_REVISION,
        "case_counts": dict(Counter(case.split for case in cases)), "threads": args.threads,
        "physical_page_normalization": pages is not None,
        "sec_replay": sec.manifest if sec else None, "provider_calls": 0, "timed_sec_http_calls": 0,
        "setup_seconds": round(setup_seconds, 3), "peak_memory_bytes": _peak_memory_bytes(),
        "variants": {
            variant: {
                "description": VARIANTS[variant], "overall": summarize_ablation(rows),
                "by_split": {split: summarize_ablation([row for row in rows if row["split"] == split]) for split in SPLITS},
                "by_category": {category: summarize_ablation([row for row in rows if row["category"] == category])
                                for category in sorted({row["category"] for row in rows})},
                "per_case": rows,
            }
            for variant, rows in rows_by_variant.items()
        },
    }
    _write_json_atomic(args.output, report)
    print(args.output, flush=True)


if __name__ == "__main__":
    main()
