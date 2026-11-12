"""Use frozen M13 labels and live specialist receipts for offline diagnosis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from configs.multi_agent_ablation import COMPANY_TICKERS, AblationCase
from src.agent.complexity_router import ComplexityRouter, ExecutionPath
from src.agent.specialist_graph import SpecialistExecution
from src.decision.models import CoverageStatus, EvidenceCoverage, OperationRequirement, QuestionRequirements
from src.decision.statement_columns import StatementValue, extract_annual_statement_values
from src.evaluation.answer_metrics import numeric_fact_signatures
from src.evaluation.failure_attribution import FailureSignal, FailureStage
from src.evaluation.oracle_interventions import DiagnosticGraph, FixedRequirements, draft_exists
from src.ledger.models import EvidenceSourceType
from src.policy.evidence_policy import CandidateDisposition
from src.research.planner import CorpusAwarePlanner
from src.retrieval.parent_context import PageParent
from src.verification.models import ClaimStatus


_SCALES = {"unit": 0, "thousand": 3, "million": 6, "billion": 9}
_OPERATIONS = {"growth", "difference", "ratio", "average", "compare", "lookup"}


@dataclass(frozen=True)
class ExpectedSlot:
    entity: str
    metric: str
    period: str
    sources: tuple[str, ...]
    amount: Decimal | None
    currency: str | None

    @property
    def key(self) -> str:
        return f"{self.entity}:{self.metric}:{self.period}"


_METRICS = {
    "revenue": "revenue", "operating income": "operating_income", "total assets": "total_assets",
    "cash and cash equivalents": "cash_and_equivalents",
}

# Annual-duration USD operands read from the labeled 10-K accessions in the
# frozen Company Facts snapshots. These are inputs, distinct from M13's
# rounded expected outputs for growth and difference.
_M13_OPERANDS = {
    ("boeing", "FY2020"): 58_158_000_000, ("boeing", "FY2022"): 66_608_000_000,
    ("nike", "FY2018"): 36_397_000_000, ("nike", "FY2019"): 39_117_000_000,
    ("corning", "FY2020"): 11_303_000_000, ("corning", "FY2021"): 14_082_000_000,
    ("apple", "FY2023"): 383_285_000_000, ("apple", "FY2024"): 391_035_000_000,
    ("microsoft", "FY2023"): 211_915_000_000, ("microsoft", "FY2024"): 245_122_000_000,
}


def expected_slots(case: AblationCase) -> tuple[ExpectedSlot, ...]:
    slots = []
    for claim in case.claims:
        company = next((term for term in claim.terms if term in COMPANY_TICKERS), None)
        if company is None and case.case_id == "boeing_revenue_difference":
            company = "boeing"
        if company is None:
            raise ValueError(f"M13 claim has no annotated issuer: {case.case_id}")
        metric = next(_METRICS[term] for term in claim.terms if term in _METRICS)
        amount = currency = None
        if len(claim.periods) == 1:
            _, currency, value, _, _ = numeric_fact_signatures(claim.value)[0]
            amount = Decimal(value)
        for period, sources in zip(claim.periods, claim.source_slots, strict=True):
            if len(claim.periods) > 1:
                amount, currency = Decimal(_M13_OPERANDS[(company, period)]), "USD"
            slots.append(ExpectedSlot(company, metric, period, sources, amount, currency))
    return tuple(slots)


def expected_operations(case: AblationCase) -> set[str]:
    if case.category == "multi_company_multi_hop":
        return {"compare", "growth"}
    if case.category == "multi_document":
        return {"compare"}
    if case.category == "numerical":
        return {next(term for term in case.claims[0].terms if term in _OPERATIONS)}
    return {"lookup"}


def resolution_signals(
    case: AblationCase, requirements: QuestionRequirements, slots: tuple[ExpectedSlot, ...],
) -> list[FailureSignal]:
    if not slots:
        return []
    expected = (
        ({item.entity for item in slots}, {item.canonical_name.casefold() for item in requirements.entities},
         FailureStage.ENTITY_RESOLUTION, "issuer"),
        ({item.metric for item in slots}, {item.metric_id for item in requirements.metrics},
         FailureStage.METRIC_RESOLUTION, "metric"),
        ({item.period for item in slots}, set(requirements.periods),
         FailureStage.PERIOD_RESOLUTION, "fiscal period"),
    )
    failures = [
        FailureSignal(stage, f"resolved {name} set differs from annotated requirements")
        for gold, actual, stage, name in expected if gold != actual
    ]
    if expected_operations(case) != {item.operation for item in requirements.operations}:
        failures.append(FailureSignal(FailureStage.METRIC_RESOLUTION, "metric operation requirement was resolved incorrectly"))
    entities = {item.entity_id: item.canonical_name.casefold() for item in requirements.entities}
    expected_keys = {(slot.entity, slot.metric, slot.period) for slot in slots}
    actual_keys = {(entities[item.entity_id], item.metric_id, item.period) for item in requirements.evidence}
    if not failures and expected_keys != actual_keys:
        failures.append(FailureSignal(FailureStage.METRIC_RESOLUTION, "resolved entity/metric/period slots differ from labels"))
    return failures


class RequirementsOracleRouter(ComplexityRouter):
    """Bind independently annotated requirements into classification and planning."""

    def __init__(self, corpus, requirements: QuestionRequirements):
        super().__init__(corpus)
        self.extractor = FixedRequirements(self.extractor, requirements)

    def _prepare_execution(self, state, path, budget, node_name):
        planner = CorpusAwarePlanner(
            self.corpus_map, max_tasks=min(budget.max_planned_tasks, budget.max_retrieval_calls),
        )
        planner.extractor = self.extractor
        plan = planner.plan(state["question"])
        return {
            "selected_path": path.value, "budget": budget, "research_plan": plan,
            "planned_task_count": len(plan.tasks), "planned_retrieval_calls": plan.retrieval_call_count,
            "route_trace": [*state["route_trace"], node_name],
        }


def corrected_requirements(
    case: AblationCase, router: ComplexityRouter, slots: tuple[ExpectedSlot, ...],
) -> QuestionRequirements:
    companies = dict.fromkeys(slot.entity for slot in slots)
    metric_ids = {slot.metric for slot in slots}
    labels = [label for label, metric in _METRICS.items() if metric in metric_ids]
    periods = dict.fromkeys(slot.period for slot in slots)
    parsed = router.extractor.extract(f"{' and '.join(companies)} {' and '.join(labels)} {' and '.join(periods)}")
    operations = expected_operations(case)
    requirement_keys = {(slot.entity, slot.metric, slot.period) for slot in slots}
    entities = {item.entity_id: item.canonical_name.casefold() for item in parsed.entities}
    evidence = tuple(item for item in parsed.evidence
                     if (entities[item.entity_id], item.metric_id, item.period) in requirement_keys)
    if len(evidence) != len(requirement_keys):
        raise ValueError(f"Cannot construct independent requirement override for {case.case_id}")
    return parsed.model_copy(update={
        "question": case.question,
        "requested_currency": router.extractor.extract(case.question).requested_currency,
        "evidence": evidence,
        "operations": tuple(OperationRequirement(
            operation=operation, metric_id=next(iter(metric_ids)) if len(metric_ids) == 1 else None,
            requires_period_alignment=operation != "lookup", requires_unit_compatibility=operation != "lookup",
        ) for operation in sorted(operations)),
    })


def source_key(row: dict) -> str:
    return f"{row['doc_name']}#p{row['page_number']}"


@dataclass(frozen=True)
class ReviewedTableRow:
    """Column labels checked against the pinned page, including its scale."""

    metric: str
    header: str
    row: str
    periods: tuple[str, ...]
    scale: str


_REVIEWED_ROWS = {
    "MGMRESORTS_2022_10K#p59": ReviewedTableRow(
        "revenue", "2022 2021 2020", r"^([\d, ]+)\nExpenses$",
        ("FY2022", "FY2021", "FY2020"), "thousands",
    ),
    "NIKE_2018_10K#p45": ReviewedTableRow(
        "revenue", "2018 2017 2016", r"^Revenues (.+)$", ("FY2018", "FY2017", "FY2016"), "millions",
    ),
    "NIKE_2019_10K#p51": ReviewedTableRow(
        "revenue", "2019 2018 2017", r"^Revenues (.+)$", ("FY2019", "FY2018", "FY2017"), "millions",
    ),
    "NIKE_2021_10K#p58": ReviewedTableRow(
        "revenue", "2021 2020 2019", r"^Revenues (.+)$", ("FY2021", "FY2020", "FY2019"), "millions",
    ),
    "CORNING_2020_10K#p69": ReviewedTableRow(
        "revenue", "2020 2019 2018", r"^Net sales (.+)$", ("FY2020", "FY2019", "FY2018"), "millions",
    ),
    "CORNING_2021_10K#p64": ReviewedTableRow(
        "revenue", "2021 2020 2019", r"^Net sales (.+)$", ("FY2021", "FY2020", "FY2019"), "millions",
    ),
    "BESTBUY_2024Q2_10Q#p2": ReviewedTableRow(
        "cash_and_equivalents", "July 29, 2023 January 28, 2023 July 30, 2022",
        r"^Cash and cash equivalents (.+)$", ("Q2 FY2024", "", ""), "millions",
    ),
}


def _reviewed_values(source: str, text: str) -> tuple[StatementValue, ...]:
    spec = _REVIEWED_ROWS.get(source)
    if spec is None:
        return ()
    normalized = "\n".join(" ".join(line.replace("\ufffd", " ").split()) for line in text.splitlines())
    header_at = normalized.find(spec.header)
    if header_at < 0 or f"in {spec.scale}" not in normalized[:header_at].casefold():
        raise ValueError(f"Reviewed header or scale changed on {source}")
    rows = re.findall(spec.row, normalized[header_at:], flags=re.M)
    cells = re.findall(r"\d[\d,]*(?:\.\d+)?", rows[0]) if len(rows) == 1 else []
    if len(cells) != len(spec.periods):
        raise ValueError(f"Reviewed source cell count changed on {source}")
    return tuple(
        StatementValue(spec.metric, period, Decimal(cell.replace(",", "")), "USD", spec.scale, rows[0], spec.header)
        for period, cell in zip(spec.periods, cells, strict=True) if period
    )


def normalized_table(company: str, metric: str, period: str, currency: str, amount: Decimal) -> str:
    return f"{company}\n| Metric | {period} |\n| --- | --- |\n| {metric} | {currency} {amount:,f} |"


def prepare_page_oracles(
    slots: tuple[ExpectedSlot, ...],
    page_rows: dict[str, tuple[dict, PageParent]],
) -> tuple[tuple[dict, ...], tuple[dict, ...]]:
    """Return raw physical pages and M14 header-aligned observations separately."""
    raw = []
    normalized = []
    for source in sorted({source for slot in slots for source in slot.sources}.intersection(page_rows)):
        metadata, parent = page_rows[source]
        base = {key: metadata[key] for key in (
            "doc_name", "document_id", "page_number", "company", "source_url", "doc_type",
        )}
        if metadata.get("ticker"):
            base["ticker"] = metadata["ticker"]
        raw.append({**base, "chunk_id": f"oracle-page:{source}", "text": parent.text})
        annual_values = extract_annual_statement_values(
            parent.text, form=metadata["doc_type"], filing_year=metadata["reporting_periods"][0],
        )
        reviewed = _reviewed_values(source, parent.text)
        reviewed_keys = {(value.metric_id, value.period) for value in reviewed}
        values = (*reviewed, *(value for value in annual_values if (value.metric_id, value.period) not in reviewed_keys))
        for value in values:
            if not any(slot.metric == value.metric_id and slot.period == value.period
                       and source in slot.sources for slot in slots):
                continue
            label = next(label for label, metric in _METRICS.items() if metric == value.metric_id)
            normalized.append({
                **base, "chunk_id": f"oracle-normalized:{source}:{value.metric_id}:{value.period}",
                "metric_id": value.metric_id, "period": value.period,
                "text": normalized_table(
                    metadata["company"], label, value.period, value.currency, value.base_amount,
                ),
                "normalized_amount": str(value.base_amount), "currency": value.currency,
            })
    return tuple(raw), tuple(normalized)


def quarterly_xbrl_overrides(
    graph: DiagnosticGraph, result: SpecialistExecution, slots: tuple[ExpectedSlot, ...],
) -> dict[str, str]:
    """Re-encode a source-verified SEC observation for the existing table parser."""
    if graph.runtime is None:
        return {}
    normalized = {}
    candidates = {row["chunk_id"]: row for row in graph.pre_policy}
    for record in result.ledger_snapshot.evidence_records:
        provenance = record.xbrl_provenance
        if provenance is None or record.chunk_id not in candidates or not record.fiscal_period:
            continue
        slot = next((slot for slot in slots if slot.period.startswith("Q") and slot.period == record.fiscal_period
                     and slot.metric == record.metric_id and f"sec:{provenance.accession}" in slot.sources
                     and record.currency == slot.currency and record.normalized_value is not None
                     and Decimal(record.normalized_value) == slot.amount), None)
        if slot is not None:
            label = next(label for label, metric in _METRICS.items() if metric == slot.metric)
            normalized[record.chunk_id] = normalized_table(
                candidates[record.chunk_id]["company"], label, slot.period, record.currency,
                Decimal(record.normalized_value),
            )
    return normalized


def _findings_for(coverage: EvidenceCoverage | None, slot: ExpectedSlot) -> tuple:
    if coverage is None:
        return ()
    entities = {item.entity_id for item in coverage.requirements.entities
                if item.canonical_name.casefold() == slot.entity}
    return tuple(finding for finding in coverage.findings
                 if (finding.entity_id in entities and finding.metric_id == slot.metric
                     and finding.period == slot.period))


def _fact_matches(fact, slot: ExpectedSlot) -> bool:
    if fact.numeric_value is None or fact.scale not in _SCALES or not fact.currency:
        return False
    return slot.amount is None or (
        fact.currency == slot.currency and Decimal(fact.numeric_value).scaleb(_SCALES[fact.scale]) == slot.amount
    )


def slot_supported(coverage: EvidenceCoverage | None, slot: ExpectedSlot, source_ids: dict) -> bool:
    return any(
        finding.status == CoverageStatus.FOUND and any(
            source_ids.get(fact.evidence_id) in slot.sources and _fact_matches(fact, slot)
            for fact in finding.facts
        ) for finding in _findings_for(coverage, slot)
    )


def lost_slots(
    slots: tuple[ExpectedSlot, ...], graph: DiagnosticGraph, result: SpecialistExecution,
    source_ids: dict[str, str], discovered_sources: set[str],
    raw_pages: tuple[dict, ...], aligned: tuple[dict, ...], alternate_sec_slots: set[str],
    xbrl_overrides: dict[str, str],
) -> tuple[list[FailureSignal], list[dict]]:
    runtime = graph.runtime
    if runtime is None:
        return [], []
    analyzer = runtime.decision_layer.analyzer
    before = analyzer.analyze(runtime.requirements, graph.pre_policy)
    gold_page_coverage = analyzer.analyze(runtime.requirements, raw_pages)
    raw_sources = {row["chunk_id"]: source_key(row) for row in raw_pages}
    xbrl_probe = analyzer.analyze(runtime.requirements, [
        {**row, "text": xbrl_overrides[row["chunk_id"]]}
        for row in graph.pre_policy if row["chunk_id"] in xbrl_overrides
    ])
    registered = set(source_ids.values())
    signals, details = [], []
    for slot in slots:
        if slot_supported(result.coverage, slot, source_ids):
            continue
        gold = set(slot.sources)
        stage = None
        reason = ""
        aligned_exact = any(
            source_key(row) in gold and row["metric_id"] == slot.metric and row["period"] == slot.period
            and row["currency"] == slot.currency and Decimal(row["normalized_amount"]) == slot.amount
            for row in aligned
        )
        page_exact = slot_supported(gold_page_coverage, slot, raw_sources)
        findings = _findings_for(result.coverage, slot)
        facts = [fact for finding in findings for fact in finding.facts]
        pdf_facts = [fact for fact in facts if not source_ids.get(fact.evidence_id, "").startswith("sec:")]
        wrong_pdf = any(not _fact_matches(fact, slot) for fact in pdf_facts)
        correct_fact_seen = any(
            _fact_matches(fact, slot) and source_ids.get(fact.evidence_id) in gold for fact in facts
        )
        exact_before = slot_supported(before, slot, source_ids)
        xbrl_exact = slot_supported(xbrl_probe, slot, source_ids)
        details.append({
            "slot": slot.key, "gold_discovered": sorted(gold & discovered_sources),
            "gold_registered": sorted(gold & registered), "exact_before_policy": exact_before,
            "exact_in_conflicted_set": correct_fact_seen, "raw_page_exact": page_exact,
            "aligned_page_exact": aligned_exact, "normalized_xbrl_exact": xbrl_exact,
            "has_mismatched_pdf_value": wrong_pdf,
            "observations": [
                {"candidate_id": fact.evidence_id, "source_id": source_ids.get(fact.evidence_id),
                 "value": fact.value, "matches_expected_value": _fact_matches(fact, slot)}
                for fact in facts
            ],
        })
        if exact_before:
            stage, reason = FailureStage.CANDIDATE_POLICY, "exact sourced slot disappeared after screening"
        elif result.selected_path == ExecutionPath.FAST and (
            (slot.key in alternate_sec_slots and not correct_fact_seen)
            or all(source.startswith("sec:") for source in gold)
        ):
            stage, reason = FailureStage.SOURCE_CAPABILITY_ROUTING, "FAST omitted the SEC capability needed for this slot"
        elif not gold.intersection(discovered_sources):
            if any(source in raw_sources.values() for source in gold):
                stage, reason = FailureStage.CANDIDATE_RETRIEVAL, "indexed labeled page absent from bounded retrieval results"
        elif not gold.intersection(registered):
            stage, reason = FailureStage.CANDIDATE_RETRIEVAL, "labeled candidate returned by retriever but absent from worker handoff"
        elif any(item.missing_reason in {"source_provenance_missing", "source_metadata_conflict"} for item in findings):
            stage, reason = FailureStage.SOURCE_PROVENANCE, "coverage recorded unusable or inconsistent source metadata"
        elif xbrl_exact and not correct_fact_seen:
            stage, reason = (
                FailureStage.XBRL_FACT_NORMALIZATION,
                "SEC worker resolved the discrete quarter; coverage dropped it when reparsing its text as annual",
            )
        elif aligned_exact and gold.intersection(registered) and not any(
            source_ids.get(fact.evidence_id) in gold for fact in pdf_facts
        ) and not correct_fact_seen:
            stage, reason = FailureStage.TABLE_CELL_EXTRACTION, "the retrieved labeled row produced no fact"
        elif wrong_pdf and any(item.status == CoverageStatus.CONFLICTED for item in findings):
            if aligned_exact or correct_fact_seen:
                stage = FailureStage.TABLE_HEADER_ALIGNMENT
                reason = "a PDF parse associated an incompatible amount or unit with the required slot"
        elif gold.intersection(raw_sources.values()) and not correct_fact_seen:
            if aligned_exact or page_exact:
                stage = FailureStage.TABLE_HEADER_ALIGNMENT
                reason = "labeled page recovers the period and value when header context is supplied"
            elif not facts and gold.intersection(registered):
                stage = FailureStage.TABLE_CELL_EXTRACTION
                reason = "labeled PDF reached extraction without a usable observation for the slot"
        if stage is not None:
            signals.append(FailureSignal(stage, reason, slot.key))
    return signals, details


def downstream_signals(
    graph: DiagnosticGraph, result: SpecialistExecution, draft_grounded: bool, all_slots_supported: bool,
) -> list[FailureSignal]:
    if all_slots_supported and result.coverage and not result.coverage.sufficient:
        return [FailureSignal(FailureStage.EVIDENCE_SET_SUFFICIENCY, "sourced slots were found but the set did not pass coverage")]
    if all_slots_supported and not draft_exists(graph.draft):
        arithmetic = {"growth", "difference", "ratio", "average"}
        operations = {item.operation for item in result.coverage.requirements.operations} if result.coverage else set()
        if operations.intersection(arithmetic) and not result.calculations:
            return [FailureSignal(FailureStage.FINANCIAL_REASONING, "complete inputs did not produce a validated calculation")]
        return [FailureSignal(FailureStage.ANSWER_GENERATION, "covered facts did not produce a draft")]
    if draft_grounded:
        claims = result.verification.claims if result.verification else ()
        if not claims or any(claim.status != ClaimStatus.SUPPORTED for claim in claims):
            return [FailureSignal(FailureStage.CLAIM_VERIFICATION, "independently grounded draft did not pass claim checks")]
        return [FailureSignal(FailureStage.FINAL_RELEASE_POLICY, "supported grounded draft was withheld or truncated")]
    if all_slots_supported and draft_exists(graph.draft):
        return [FailureSignal(FailureStage.ANSWER_GENERATION, "draft was independently incorrect despite covered source slots")]
    return []


def trace_row(
    case: AblationCase, graph: DiagnosticGraph, result: SpecialistExecution, scored: dict,
    slots: tuple[ExpectedSlot, ...], candidate_ids: tuple[str, ...],
) -> dict[str, Any]:
    runtime = graph.runtime
    req = runtime.requirements if runtime else graph.router.extractor.extract(case.question)
    coverage = result.coverage
    workers = [
        {"worker": receipt.worker_id, "status": receipt.status, "tasks": receipt.task_ids,
         "missing_requirements": receipt.missing_requirement_ids, "evidence_ids": receipt.evidence_ids,
         "observations": {key: [item.value for item in receipt.observations if item.key == key]
                          for key in sorted({item.key for item in receipt.observations})},
         "tool_calls": receipt.tool_calls}
        for receipt in result.specialist_results
    ]
    return {
        "request_id": result.request_id, "case_id": case.case_id, "split": case.split,
        "query_class": case.category, "original_question": case.question,
        "answerable": scored["answerable"], "answered": scored["answered"],
        "grounded_exact": scored["grounded_exact"], "numeric_exact": scored["numeric_exact"],
        "unsupported_released_claims": scored["unsupported_released_claims"],
        "supported_citations": scored["supported_citations"], "citations": scored["citations"],
        "actual_route": result.selected_path, "expected_route": case.intended_path,
        "route_reason_codes": result.route.decision.reason_codes,
        "expected_source_capabilities": {
            slot.key: sorted({"DIRECT_XBRL" if source.startswith("sec:") else "DIRECT_TABLE"
                              for source in slot.sources}) for slot in slots
        },
        "resolved_entities": tuple(item.canonical_name for item in req.entities),
        "resolved_metrics": tuple(item.metric_id for item in req.metrics),
        "resolved_periods": req.periods,
        "required_fact_slots": {slot.key: slot.sources for slot in slots},
        "runtime_requirement_ids": tuple(item.requirement_id for item in req.evidence),
        "operations": tuple(item.operation for item in req.operations),
        "resolved_fact_slots": tuple(item.requirement_id for item in coverage.findings
                                     if item.status == CoverageStatus.FOUND) if coverage else (),
        "retrieved_candidate_ids": candidate_ids,
        "accepted_evidence_ids": result.citation_evidence_ids,
        "rejected_candidate_reasons": [
            {"candidate_id": item.candidate_id, "requirement_id": item.requirement_id, "reasons": item.reason_codes}
            for item in result.candidate_decisions if item.disposition == CandidateDisposition.REJECT
        ],
        "coverage_result": {
            "sufficient": coverage.sufficient, "operation_gaps": coverage.operation_gaps,
            "findings": [{"requirement_id": item.requirement_id, "status": item.status,
                          "reason": item.missing_reason, "candidate_ids": item.evidence_ids}
                         for item in coverage.findings],
        } if coverage else None,
        "missing_requirements": coverage.missing_requirement_ids if coverage else (),
        "detected_contradictions": coverage.conflicted_requirement_ids if coverage else (),
        "generation_status": "draft" if draft_exists(graph.draft) else "fallback" if graph.draft else "not_run",
        "verification_status": result.verification.disposition if result.verification else "not_run",
        "verification_reasons": result.verification.reason_codes if result.verification else (),
        "claim_statuses": [{"status": claim.status, "reasons": claim.reason_codes}
                           for claim in result.verification.claims] if result.verification else [],
        "release_disposition": result.status,
        "workers": workers, "latency_ms": scored["latency_ms"],
        "tool_calls": result.usage.tool_calls, "llm_calls": result.usage.llm_calls,
        "retrieval_calls": result.usage.retrieval_calls, "evidence_tokens": result.usage.evidence_tokens,
    }
