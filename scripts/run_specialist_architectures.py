"""Paired offline comparison of SEC, adaptive and specialist execution."""

from __future__ import annotations

import argparse
import re
import time
from dataclasses import replace
from pathlib import Path

from configs.financebench import P1_EMBEDDING_REVISION, P1_INDEX_ID, P1_PAGE_CACHE, P1_RUN
from configs.multi_agent_ablation import CASES as M13_CASES
from configs.offline_guard import offline_socket_guard
from configs.sec_snapshots import COMPANY_TICKERS, SEC_CUTOFF, SEC_ISSUERS
from configs.source_routing import CASES as DIRECT_CASES
from configs.specialist_architectures import CASES as COMPLEX_CASES, ISSUERS, NARRATIVE_CASES
from scripts.run_multi_agent_ablation import (
    _evidence_tokens, _ledger_key, _missing, _pdf_key, _planned, _PolicyLayer, _RecordingRetriever,
    _specialist_observation, _task_counts,
)
from src.agent.adaptive_retrieval import AdaptiveRetrievalBudget, AdaptiveRetrievalController
from src.agent.complexity_router import (
    FAST_BUDGET, ComplexityRouter, CorpusMap, ExecutionPath, SourceCapability, requires_statement_source,
)
from src.agent.specialist_graph import SpecialistResearchGraph, _approved_report_input
from src.agent.specialists import (
    EvidenceAnalyst, FinancialReasoner, SpecialistRuntime, StructuredFinancialDataWorker,
    _chunk_mapping, _compatible_xbrl_periods, _in_filing_scope, _normalize_filing_statements, _source_record,
)
from src.decision.models import CoverageStatus
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.company_facts_replay import CompanyFactsReplay
from src.evaluation.multi_agent_ablation import AblationObservation, evaluate_observation, paired_grounded_exact, summarize_ablation
from src.evaluation.post_m15_manifest import build_manifest
from src.generation.grounded_writer import DeterministicWriter
from src.ingestion.company_facts import RevisionPolicy, requested_revision_policies
from src.ledger.evidence_ledger import EvidenceLedger
from src.ledger.models import EvidenceSourceType
from src.retrieval.canonical_json import sha256_file
from src.retrieval.embedder import Embedder
from src.retrieval.financial_statement_ranker import FinancialStatementRanker
from src.retrieval.frozen_artifacts import load_frozen_corpus, load_frozen_vectors
from src.retrieval.frozen_dense import FrozenDenseRetriever
from src.retrieval.pdf_page_cache import FrozenPdfPages
from src.verification.atomic_claim_verifier import AtomicClaimVerifier
from src.verification.response_policy import verify_and_release


RUNS = Path("data/financebench/ablation_runs")
ARCHITECTURES = ("A_sec", "B_adaptive", "C_routed", "D_forced")


class FaultReplayRetriever(_RecordingRetriever):
    """Inject a timeout on any lookup that includes one source document."""

    blocked_document: str | None = None
    remaining_faults: int | None = 0
    fault_attempts = 0

    def reset(self):
        super().reset()
        self.fault_attempts = 0

    def _check_scope(self, document_ids):
        with self.lock:
            if not self.blocked_document or self.remaining_faults == 0:
                return
            if document_ids and self.blocked_document not in document_ids:
                return
            self.fault_attempts += 1
            if self.remaining_faults is not None:
                self.remaining_faults -= 1
        raise TimeoutError("injected filing scope timeout")

    def retrieve(self, query, top_k=10, *, document_ids=()):
        try:
            self._check_scope(document_ids)
        except TimeoutError:
            with self.lock:
                self.calls.append((" ".join(query.casefold().split()), document_ids, ()))
            raise
        return super().retrieve(query, top_k=top_k, document_ids=document_ids)

    def retrieve_statement_candidates(self, document_ids, kind, *, top_k):
        self._check_scope(document_ids)
        return super().retrieve_statement_candidates(document_ids, kind, top_k=top_k)

def _resolved_slots(coverage):
    return sorted(finding.requirement_id for finding in coverage.findings if finding.status == CoverageStatus.FOUND) if coverage else []


class ScopedSearch:
    """One serial retrieval tool, using the same document inventory as the graph."""

    def __init__(self, retriever, runtime):
        self.retriever = retriever
        self.runtime = runtime

    def retrieve(self, query, top_k=10):
        runtime = self.runtime
        runtime.budget_tracker.charge(retrieval=True)
        focus = runtime.decision_layer.extractor.extract(query.partition(" question context:")[0])
        slots = {item.requirement_id for item in focus.evidence}
        tasks = [task for task in runtime.plan.tasks if slots.intersection(task.requirement_ids)]
        scope = tuple(sorted({doc for task in tasks for doc in task.target_document_ids})) if tasks and all(
            task.target_document_ids for task in tasks) else ()
        rows = self.retriever.retrieve(query, top_k=top_k, document_ids=scope)
        return [row for raw in rows if _in_filing_scope(row := _chunk_mapping(raw), scope)]


class NormalizedAdaptivePolicy(_PolicyLayer):
    def __init__(self, runtime):
        super().__init__(runtime.decision_layer.extractor)
        self.runtime = runtime

    def assess(self, question, chunks):
        runtime = self.runtime
        runtime.source_chunks = {chunk["chunk_id"]: runtime.source_chunks.get(chunk["chunk_id"], dict(chunk)) for chunk in chunks}
        _normalize_filing_statements(runtime)
        return super().assess(question, runtime.source_chunks.values())


def _adaptive(question, route, graph, retriever, sec, request_id):
    if route.selected_path == ExecutionPath.UNSUPPORTED:
        return AblationObservation(disposition="UNSUPPORTED", execution_path=ExecutionPath.UNSUPPORTED), {}
    start_sec = sec.request_count
    revisions = requested_revision_policies(question)
    runtime = SpecialistRuntime(
        request_id, EvidenceLedger(request_id), route.budget, graph.router.extractor.extract(question), route.research_plan,
        retriever=retriever, ticker_by_company=graph.ticker_by_company, candidate_gate=graph.candidate_gate,
        decision_layer=_PolicyLayer(graph.router.extractor), verifier=graph.verifier,
        require_structured_facts=bool(revisions), xbrl_revision_policy=next(iter(revisions), RevisionPolicy.AS_REPORTED),
    )
    runtime.register_plan()
    StructuredFinancialDataWorker(sec).run(runtime.plan.tasks, runtime)
    policy = NormalizedAdaptivePolicy(runtime)
    initial = list(runtime.source_chunks.values())
    search = ScopedSearch(retriever, runtime)
    needs_retrieval = not policy.assess(question, initial).sufficient
    for operation in runtime.requirements.operations:
        if operation.operation not in {"growth", "difference"}:
            continue
        for entity in runtime.requirements.entities:
            facts = [fact for fact in runtime.ledger.snapshot().financial_facts
                     if fact.entity_id == entity.entity_id and fact.metric_id == operation.metric_id]
            if len({fact.fiscal_period for fact in facts}) < 2 or not _compatible_xbrl_periods(facts):
                needs_retrieval = True
    initial_error = None
    if not revisions and needs_retrieval and runtime.budget_tracker.can_start(retrieval=True):
        try:
            initial.extend(search.retrieve(question, top_k=min(10, route.budget.max_candidate_chunks - len(initial))))
        except (OSError, TimeoutError) as exc:
            initial_error = type(exc).__name__
    budget = runtime.budget_tracker
    remaining = min(route.budget.max_retrieval_calls - budget.retrieval_calls, route.budget.max_tool_calls - budget.tool_calls)
    candidate_room = max(0, route.budget.max_candidate_chunks - len(initial))
    remaining = max(0, min(remaining, candidate_room)) if not revisions else 0
    result = AdaptiveRetrievalController(search, decision_layer=policy).run(
        question, initial, budget=AdaptiveRetrievalBudget(
            max_queries=remaining, max_rounds=remaining, top_k=min(10, max(1, candidate_room // max(1, remaining))),
            max_evidence_tokens=route.budget.max_context_tokens,
            time_budget_seconds=max(.001, route.budget.max_wall_time_seconds - budget.elapsed_seconds),
        ),
    )
    policy.assess(question, result.evidence_chunks)
    catalog = graph.router.extractor.catalog
    for rank, chunk in enumerate(runtime.source_chunks.values()):
        key = chunk["chunk_id"]
        if key in runtime.xbrl_chunk_ids:
            continue
        entity = catalog.metadata_entity_id(chunk.get("ticker"), chunk.get("company"), chunk.get("doc_name"))
        for task in runtime.plan.tasks:
            if task.entity_id and task.entity_id != entity:
                continue
            saved = runtime.ledger.add_evidence(_source_record(
                runtime=runtime, chunk=chunk, task=task, rank=rank, source_type=EvidenceSourceType.TEXT_EVIDENCE,
                discovered_by=("adaptive_retrieval",),
            ))
            runtime.preferred_evidence_by_chunk_id.setdefault(key, saved.evidence_id)
    EvidenceAnalyst().run(question, runtime)
    FinancialReasoner().run(runtime)
    report = _approved_report_input(runtime)
    draft = DeterministicWriter().write(report)
    release = verify_and_release(runtime.verifier, question, draft.answer, report.verification_chunks, runtime.requirements)
    citations = tuple(_ledger_key(source.records[0]) for source in report.sources)
    records = {record.evidence_id: record for record in runtime.ledger.snapshot().evidence_records}
    linked_chunks = {record.chunk_id for record in records.values()}
    links = [key for claim in release.result.claims for key in claim.supporting_evidence_ids]
    tasks, completed = _task_counts(route, runtime.coverage)
    usage = retriever.usage()
    usage["retrieval_calls"] = budget.retrieval_calls
    retrieved = {*map(_ledger_key, records.values()), *map(_pdf_key, retriever.chunks.values())}
    return AblationObservation(
        answer=release.answer, disposition=release.result.disposition.value, citation_sources=citations,
        retrieved_sources=frozenset(item for item in retrieved if item is not None), execution_path=route.selected_path,
        planned_requirements=_planned(route), requested_requirements=tuple(item.requirement_id for item in runtime.requirements.evidence),
        initially_missing=_missing(result.initial_decision.coverage), finally_missing=_missing(runtime.coverage),
        tool_calls=budget.tool_calls, sec_calls=sec.request_count - start_sec, **usage,
        evidence_tokens=_evidence_tokens(report.verification_chunks), planned_tasks=tasks, completed_tasks=completed,
        handoff_links=len(links), resolved_handoff_links=sum(key in linked_chunks for key in links),
        correction_passes=release.correction_passes, trace=("single_agent", result.stop_reason.value),
    ), {"adaptive_queries": result.queries_used, "adaptive_stop": result.stop_reason.value,
        "initial_retrieval_error": initial_error, "resolved_slots": _resolved_slots(runtime.coverage)}


def replay(case, architecture, graph, direct, retriever, sec, policy, *, serial=False, evaluator=evaluate_observation):
    observation, elapsed, details = observe(case.question, case.case_id, architecture, graph, direct, retriever, sec, policy,
                                            serial=serial)
    return {**evaluator(case, observation, latency_ms=elapsed), **details, "citation_sources": observation.citation_sources}


def observe(question, case_id, architecture, graph, direct, retriever, sec, policy, *, serial=False):
    retriever.reset()
    started = time.perf_counter()
    prior_sec = sec.request_count
    request_id = f"q7-{architecture}-{case_id}"
    details = {}
    if architecture == "B_adaptive":
        route = graph.router.route(question, force_research=True, source_inventory=graph.source_inventory)
        observation, details = _adaptive(question, route, graph, retriever, sec, request_id)
        elapsed = (time.perf_counter() - started) * 1000
    else:
        engine = direct if architecture == "A_sec" else graph
        route = engine.router.route(question, force_research=architecture == "D_forced", source_inventory=engine.source_inventory)
        if architecture == "A_sec" and route.selected_path != ExecutionPath.UNSUPPORTED and not requires_statement_source(question):
            requirements = engine.router.extractor.extract(question)
            revisions = requested_revision_policies(question)
            if len(revisions) == 1 and len(requirements.evidence) == 1 and not requirements.operations:
                route = route.model_copy(update={"selected_path": ExecutionPath.FAST, "source_capability": SourceCapability.DIRECT_XBRL,
                                                 "budget": FAST_BUDGET})
        if serial:
            route = route.model_copy(update={"budget": route.budget.model_copy(update={"max_concurrency": 1})})
        if architecture == "A_sec" and route.source_capability != SourceCapability.DIRECT_XBRL:
            observation = AblationObservation(disposition="UNSUPPORTED" if route.selected_path == ExecutionPath.UNSUPPORTED else "ABSTAIN")
            elapsed = (time.perf_counter() - started) * 1000
        else:
            result = engine.run(question, route=route, request_id=request_id)
            elapsed = (time.perf_counter() - started) * 1000
            observation = _specialist_observation(result, retriever, sec.request_count - prior_sec, policy)
            receipts = result.specialist_results
            details = {"peak_parallel_tasks": result.usage.peak_parallel_tasks, "filing_assignments": result.usage.parallel_task_count,
                       "coalesced_tasks": result.usage.deduplicated_query_tasks, "statement_lookups": retriever.statement_calls,
                       "retry_calls": sum(r.retrieval_calls for r in receipts if r.worker_id == "table_evidence_worker"
                                          or any(item.key == "recovery" for item in r.observations)),
                       "wasted_tool_calls": sum(r.tool_calls for r in receipts if not r.evidence_ids),
                       "resolved_slots": _resolved_slots(result.coverage)}
    return observation, elapsed, details


def evaluate_narrative(case, observation, *, latency_ms):
    citation_pattern = r"\[Source ([1-9]\d*)\]"
    answer = observation.answer.strip()
    numbers = [int(number) for number in re.findall(citation_pattern, answer)]
    cited_sources = {observation.citation_sources[number - 1] for number in numbers
                     if number <= len(observation.citation_sources)}
    def words(text):
        return re.findall(r"\w+", text.casefold())

    exact = words(re.sub(citation_pattern, "", answer)) == words(case.statement)
    grounded = observation.disposition == "VERIFIED" and exact and bool(cited_sources) and cited_sources <= case.sources
    return {"case_id": case.case_id, "grounded_exact": grounded, "statement_exact": exact,
            "unsupported_release": observation.disposition in {"VERIFIED", "PARTIAL"} and not grounded,
            "answer": answer, "disposition": observation.disposition, "latency_ms": round(latency_ms, 3),
            "tool_calls": observation.tool_calls, "llm_calls": observation.llm_calls, "evidence_tokens": observation.evidence_tokens}


def fault_isolation(graph, direct, retriever, sec, policy):
    """Predefined multi-statement category, both source directions, identical fault schedule."""
    results = {}
    for fault in ("one_timeout", "unavailable_source"):
        rows = {architecture: [] for architecture in ("B_adaptive", "C_routed")}
        issuers = {}
        for case in COMPLEX_CASES:
            if case.category != "cross_company_multi_statement":
                continue
            case = replace(case, question=case.question + " Use the consolidated statement of operations and consolidated balance sheet.")
            plan = graph.router.route(case.question, source_inventory=graph.source_inventory).research_plan
            docs = sorted({document for task in plan.tasks for document in task.target_document_ids})
            if len(docs) != 2 or not all(len(task.target_document_ids) == 1 for task in plan.tasks):
                raise ValueError(f"Unexpected source scope for {case.case_id}")
            for document in docs:
                healthy = {slot for task in plan.tasks if document not in task.target_document_ids for slot in task.requirement_ids}
                fault_case = replace(case, case_id=f"{case.case_id}:{document}")
                issuers[fault_case.case_id] = ISSUERS[case.case_id]
                for architecture in rows:
                    retriever.blocked_document = document
                    retriever.remaining_faults = 1 if fault == "one_timeout" else None
                    try:
                        observed = replay(fault_case, architecture, graph, direct, retriever, sec, policy)
                    finally:
                        retriever.blocked_document = None
                    observed["fault_attempts"] = retriever.fault_attempts
                    observed["healthy_slots"] = sorted(healthy)
                    observed["healthy_slots_preserved"] = bool(healthy) and healthy.issubset(observed["resolved_slots"])
                    rows[architecture].append(observed)
        routed, adaptive = rows["C_routed"], rows["B_adaptive"]
        def health(rows):
            return [dict(row, grounded_exact=row["healthy_slots_preserved"]) for row in rows]
        results[fault] = {
            "paired_grounded_exact": paired_grounded_exact(routed, adaptive, issuers, seed=20261112),
            "paired_healthy_source_preservation": paired_grounded_exact(health(routed), health(adaptive), issuers, seed=20261112),
            "architectures": {arch: {"overall": summarize_ablation(items), "per_case": items} for arch, items in rows.items()},
        }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--complex-only", action="store_true")
    parser.add_argument("--faults", action="store_true")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if not 1 <= args.threads <= 16:
        parser.error("Use 1–16 CPU threads")
    import torch

    torch.set_num_threads(args.threads)
    with offline_socket_guard():
        started = time.perf_counter()
        chunks = load_frozen_corpus(P1_RUN)
        pages = FrozenPdfPages.from_run(P1_PAGE_CACHE, P1_RUN)
        router = ComplexityRouter(CorpusMap.from_chunks(chunks, index_generation_id=P1_INDEX_ID))
        retriever = FaultReplayRetriever(FrozenDenseRetriever(
            chunks, load_frozen_vectors(P1_RUN, chunks), Embedder(device="cpu", revision=P1_EMBEDDING_REVISION),
            pdf_pages=pages, statement_ranker=FinancialStatementRanker(pages, router.extractor),
        ))
        sec = CompanyFactsReplay(RUNS / "m13-sec", SEC_ISSUERS, latest_filed=SEC_CUTOFF)
        graph = SpecialistResearchGraph(router=router, retriever=retriever, sec_client=sec, ticker_by_company=COMPANY_TICKERS)
        direct = SpecialistResearchGraph(router=router, sec_client=sec, ticker_by_company=COMPANY_TICKERS)
        setup_ms = (time.perf_counter() - started) * 1000
        policy = _PolicyLayer(router.extractor)
        cohorts = {"complex": COMPLEX_CASES} if args.complex_only else {"m13": M13_CASES, "direct": DIRECT_CASES, "complex": COMPLEX_CASES}
        report = {"configuration": {"index": P1_INDEX_ID, "embedding_revision": P1_EMBEDDING_REVISION,
                                     "sec_cutoff": SEC_CUTOFF, "providers": [], "threads": args.threads,
                                     "fault_replay": args.faults,
                                     "complex_labels_sha256": sha256_file(Path("configs/specialist_architectures.py"))},
                  "cohorts": {}, "setup_ms": round(setup_ms, 3)}
        for name, cases in cohorts.items():
            rows = {architecture: [] for architecture in ARCHITECTURES}
            for case in cases:
                for architecture in ARCHITECTURES:
                    rows[architecture].append(replay(case, architecture, graph, direct, retriever, sec, policy))
            report["cohorts"][name] = {
                architecture: {"overall": summarize_ablation(items), "per_case": items,
                               "by_class": {key: summarize_ablation([row for row in items if row["category"] == key])
                                            for key in sorted({row["category"] for row in items})}}
                for architecture, items in rows.items()
            }
            if name == "complex":
                report["complex_pairs"] = {arch: paired_grounded_exact(rows[arch], rows["B_adaptive"], ISSUERS, seed=20261112)
                                           for arch in ("C_routed", "D_forced")}
                report["serial_control"] = [replay(case, "C_routed", graph, direct, retriever, sec, policy, serial=True)
                                            for case in cases]
        report["narrative"] = {arch: [replay(case, arch, graph, direct, retriever, sec, policy, evaluator=evaluate_narrative)
                                     for case in NARRATIVE_CASES] for arch in ARCHITECTURES}
        if args.faults:
            report["fault_replay"] = fault_isolation(graph, direct, retriever, sec, policy)
        report["peak_working_set_bytes"] = peak_memory_bytes()
    write_json_atomic(args.output, report)
    if args.manifest:
        write_json_atomic(args.manifest, build_manifest(
            p1_run=P1_RUN, source_manifest=Path("data/financebench/source_manifest.json"),
            sec_manifest=RUNS / "m13-sec/manifest.json", pages=P1_PAGE_CACHE,
            artifacts={"architectures": args.output}, configuration=report["configuration"],
            code_files=("configs/specialist_architectures.py", "scripts/run_specialist_architectures.py",
                        "src/agent/complexity_router.py", "src/agent/specialist_graph.py", "src/agent/specialists.py",
                        "src/decision/evidence_coverage.py", "src/decision/filing_disclosures.py",
                        "src/generation/grounded_writer.py", "src/retrieval/frozen_dense.py",
                        "src/verification/atomic_claim_verifier.py"),
        ))
    for name, cohort in report["cohorts"].items():
        print(name, {arch: (row["overall"]["grounded_exact_answers"], row["overall"]["unsupported_answer_rate"])
                     for arch, row in cohort.items()})
    print(report["complex_pairs"])


if __name__ == "__main__":
    main()
