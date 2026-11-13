"""Replay fixed real-filing candidates through the local evidence and release policy."""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path

from configs.evidence_policy_validation import CASES, PolicyCase
from configs.financebench import P1_INDEX_ID
from configs.multi_agent_ablation import CASES as M13_CASES
from configs.offline_guard import offline_socket_guard
from scripts.run_completion_evaluation import risk_coverage_points
from scripts.run_hard_negative_retrieval import DEFAULT_RUN
from src.agent.complexity_router import ComplexityRouter, CorpusMap
from src.decision.models import CoverageStatus, DecisionAction, DecisionBudget
from src.evaluation.benchmark_io import wilson_rate, write_json_atomic
from src.evaluation.m13_failure_replay import expected_slots
from src.evaluation.multi_agent_ablation import AblationObservation, evaluate_observation, paired_grounded_exact
from src.evaluation.oracle_interventions import DiagnosticGraph
from src.evaluation.post_m15_manifest import build_manifest
from src.policy.evidence_policy import CandidateDisposition
from src.retrieval.canonical_json import sha256_file
from src.retrieval.frozen_artifacts import load_frozen_corpus
from src.retrieval.pdf_page_cache import FrozenPdfPages
from src.verification.models import ResponseDisposition


class FixedCandidates:
    def __init__(self, chunks: tuple[dict, ...], pages: FrozenPdfPages):
        self.chunks = chunks
        self.get_source_page = pages.get

    def retrieve(self, query: str, top_k: int = 10, **filters) -> list[dict]:
        return list(self.chunks[:top_k])


def _page_key(chunk: dict) -> str:
    return f"{chunk['doc_name']}#p{chunk['page_number']}"


def replay(case: PolicyCase, router, chunks, pages) -> dict:
    gold = case.gold
    inputs = tuple(chunks[(label.document, label.page, label.chunk)] for label in case.pages)
    graph = DiagnosticGraph(router=router, retriever=FixedCandidates(inputs, pages))
    started = time.perf_counter()
    result = graph.run(gold.question, request_id=f"q4-{gold.case_id}")
    elapsed = (time.perf_counter() - started) * 1000
    runtime = graph.runtime
    records = {record.evidence_id: record for record in result.ledger_snapshot.evidence_records}
    sources = tuple(
        f"{records[key].document_id}#p{records[key].page - 1}" for key in result.citation_evidence_ids
    )
    row = evaluate_observation(gold, AblationObservation(
        answer=result.answer, disposition=result.status, citation_sources=sources,
        execution_path=result.selected_path, tool_calls=result.usage.tool_calls,
        retrieval_calls=result.usage.retrieval_calls, llm_calls=result.usage.llm_calls,
        evidence_tokens=result.usage.evidence_tokens, trace=result.graph_trace,
    ), latency_ms=elapsed)
    row['source_locators'] = sources
    sufficient = bool(result.coverage and result.coverage.sufficient)
    retrieve_more = False
    candidate_checks, claim_checks = [], []
    if runtime is not None:
        source_chunks = list(runtime.source_chunks.values())
        eligible = [chunk for chunk in source_chunks if chunk['chunk_id'] not in runtime.rejected_chunk_ids
                    and (not runtime.require_structured_facts or chunk['chunk_id'] in runtime.xbrl_chunk_ids)]
        layer = runtime.decision_layer
        retry = layer.decide(gold.question, eligible, budget=DecisionBudget(remaining_retrieval_attempts=1))
        retrieve_more = retry.action == DecisionAction.RETRIEVE_MORE
        for label in case.pages:
            candidates = [chunk for chunk in eligible if _page_key(chunk) == label.locator]
            single = layer.analyzer.analyze(runtime.requirements, candidates)
            decisions = [item.model_dump(mode="json") for item in result.candidate_decisions
                         if _page_key(runtime.source_chunks[item.candidate_id]) == label.locator]
            candidate_checks.append({
                'expected': label.supports_slot, 'rationale': label.rationale, 'source': label.locator,
                'observed': any(finding.status == CoverageStatus.FOUND for finding in single.findings),
                'gate_decisions': decisions,
                'retained': any(item['disposition'] != CandidateDisposition.REJECT for item in decisions),
            })
        for index, draft, expected in case.claims:
            label = case.pages[index]
            evidence = [chunk for chunk in source_chunks if _page_key(chunk) == label.locator]
            evidence.sort(key=lambda chunk: (not bool(chunk.get('normalized_facts')), chunk['chunk_id']))
            verification = graph.verifier.verify(gold.question, f"{draft.rstrip('.')} [Source 1].", evidence[:1])
            claim_checks.append({
                'source': label.locator, 'draft': draft, 'expected': expected,
                'observed': verification.disposition == ResponseDisposition.VERIFIED,
                'disposition': verification.disposition, 'reasons': verification.reason_codes,
            })
    row['set_evidence'] = result.coverage.model_dump(mode='json', exclude={'requirements'}) if result.coverage else None
    row['calculation_requirements'] = [item.model_dump(mode='json') for item in runtime.requirements.operations] if runtime else []
    row['decisions'] = {
        'ShouldRetrieve': [{'expected': case.retrieve, 'observed': result.usage.retrieval_calls > 0}],
        'CandidateAccept': candidate_checks,
        'EvidenceSufficient': [{'expected': bool(gold.claims), 'observed': sufficient}],
        'ShouldRetrieveMore': [{'expected': case.retrieve_more, 'observed': retrieve_more}],
        'ClaimSupported': claim_checks,
        'ShouldRelease': [{'expected': bool(gold.claims), 'observed': row['answered']}],
        'ShouldAbstain': [{'expected': not gold.claims, 'observed': not row['answered']}],
    }
    return row


def summarize(rows: list[dict]) -> dict:
    answerable = [row for row in rows if row['answerable']]
    released = [row for row in rows if row['answered']]
    confusion = defaultdict(lambda: dict(tp=0, tn=0, fp=0, fn=0))
    for row in rows:
        for decision, checks in row.get('decisions', {}).items():
            for check in checks:
                prefix = 't' if check['expected'] == check['observed'] else 'f'
                confusion[decision][prefix + ('p' if check['observed'] else 'n')] += 1
    points = risk_coverage_points(rows)
    for point in points:
        point['coverage_interval'] = wilson_rate(point['released'], point['case_count'])['wilson_95']
        point['risk_interval'] = wilson_rate(point['errors'], point['released'])['wilson_95']
    return {
        'coverage': wilson_rate(len(released), len(rows)),
        'grounded_exact_answerable': wilson_rate(sum(row['grounded_exact'] for row in answerable), len(answerable)),
        'false_abstention': wilson_rate(sum(not row['answered'] for row in answerable), len(answerable)),
        'false_acceptance': wilson_rate(sum(not row['answerable'] for row in released), len(rows) - len(answerable)),
        'unsupported_release_risk': wilson_rate(sum(row['unsupported_released_claims'] > 0 for row in released), len(released)),
        'release_precision': wilson_rate(sum(row['grounded_exact'] for row in released), len(released)),
        'decision_counts': dict(confusion), 'risk_coverage': points,
        'tools': sum(row['tool_calls'] for row in rows),
        'retrieval_calls': sum(row['retrieval_calls'] for row in rows),
        'llm_calls': sum(row['llm_calls'] for row in rows),
        'cost_usd': sum(row['cost_usd'] for row in rows),
        'latency_ms_p95': sorted(row['latency_ms'] for row in rows)[math.ceil(0.95 * len(rows)) - 1],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--p1-run', type=Path, default=DEFAULT_RUN)
    parser.add_argument('--statement-pages', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--m13-before', type=Path)
    parser.add_argument('--m13-after', type=Path)
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    if bool(args.m13_before) != bool(args.m13_after) or args.manifest and not (args.baseline and args.m13_after):
        parser.error('Supply both M13 runs for a paired comparison and a fixed-candidate baseline for the manifest')
    with offline_socket_guard():
        source = load_frozen_corpus(args.p1_run)
        router = ComplexityRouter(CorpusMap.from_chunks(source, index_generation_id=P1_INDEX_ID))
        chunks = {(chunk['doc_name'], chunk['page_number'], int(chunk['chunk_id'].rsplit('_c', 1)[1])): chunk
                  for chunk in source}
        pages = FrozenPdfPages.from_run(args.statement_pages, args.p1_run)
        rows = [replay(case, router, chunks, pages) for case in CASES]
    validation = [row for row in rows if row['split'] == 'validation']
    report = {
        'method': 'fixed real filing candidates; provisional source-checked labels',
        'configuration': {'providers': [], 'seed': 20261112, 'maximum_new_unsupported_releases': 0},
        'label_sha256': sha256_file(Path('configs/evidence_policy_validation.py')),
        'pages_sha256': sha256_file(args.statement_pages), 'per_case': rows,
        'development': summarize([row for row in rows if row['split'] == 'development']),
        'validation': summarize(validation),
        'validation_by_class': {key: summarize([row for row in validation if row['category'] == key])
                                for key in sorted({row['category'] for row in validation})},
    }
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding='utf-8'))
        for key in ('method', 'label_sha256', 'pages_sha256'):
            if baseline[key] != report[key]:
                raise ValueError(f'Baseline and candidate disagree on {key}')
        old_rows = [row for row in baseline['per_case'] if row['split'] == 'validation']
        report['paired_grounded_exact'] = paired_grounded_exact(
            validation, old_rows, {case.gold.case_id: {case.issuer} for case in CASES}, seed=20261112,
        )
        report['baseline_sha256'] = sha256_file(args.baseline)
        report['gates'] = {
            'validation_false_abstentions_reduced': report['validation']['false_abstention']['numerator']
            < baseline['validation']['false_abstention']['numerator'],
            'no_validation_or_development_unsupported_release': not any(row['unsupported_released_claims'] for row in rows),
            'all_withhold_controls_pass': all(row['answerable'] or not row['answered'] for row in validation),
        }
    if args.m13_after:
        before, after = [json.loads(path.read_text(encoding='utf-8'))['variants']['B6']['per_case']
                         for path in (args.m13_before, args.m13_after)]
        pair = paired_grounded_exact(after, before, {
            case.case_id: {slot.entity for slot in expected_slots(case)} for case in M13_CASES if case.claims
        }, seed=20261112)
        report['m13'] = {'before': summarize(before), 'after': summarize(after), 'paired_grounded_exact': pair}
        report.setdefault('gates', {})['m13_no_safety_or_grounded_regression'] = (
            not any(row['unsupported_released_claims'] for row in after)
            and all(row['difference'] > 0 for row in pair['changed_cases'])
            and all(row['answerable'] or not row['answered'] for row in after)
        )
    write_json_atomic(args.output, report)
    if args.manifest:
        data_root = Path('data/financebench')
        write_json_atomic(args.manifest, build_manifest(
            p1_run=args.p1_run, source_manifest=data_root / 'source_manifest.json',
            sec_manifest=args.m13_before.parent / 'm13-sec/manifest.json', pages=args.statement_pages,
            artifacts={'report': args.output, 'policy_baseline': args.baseline,
                       'm13_before': args.m13_before, 'm13_after': args.m13_after},
            configuration=report['configuration'], code_files=(
                'scripts/run_evidence_policy_validation.py', 'configs/evidence_policy_validation.py',
                'src/agent/specialists.py', 'src/decision/evidence_coverage.py', 'src/decision/models.py',
                'src/decision/period_value_parser.py', 'src/decision/statement_columns.py',
                'src/ingestion/company_facts.py', 'src/policy/candidate_gate.py', 'src/policy/evidence_features.py',
                'src/policy/evidence_policy.py', 'src/verification/atomic_claim_verifier.py',
            ),
        ))
    for row in rows:
        print(row['case_id'], row['disposition'], row['grounded_exact'], row['unsupported_released_claims'])
    if not all(report.get('gates', {}).values()):
        raise SystemExit('An evidence policy acceptance gate failed')


if __name__ == '__main__':
    main()
