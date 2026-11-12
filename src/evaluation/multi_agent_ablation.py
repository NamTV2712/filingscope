"""Score comparable research runs against filing values and citation provenance."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean
from typing import Any

from configs.multi_agent_ablation import AblationCase
from src.agent.complexity_router import ExecutionPath
from src.evaluation.answer_metrics import numeric_fact_signatures
from src.generation.answer_generator import is_fallback_answer


_CITATION = re.compile(r"\[Source ([1-9]\d*)\]", re.I)
_CLAUSE = re.compile(r"(?<=\])\s+(?!\[)|(?<=[.!?])\s+(?!\[)|\n+")


@dataclass(frozen=True)
class AblationObservation:
    answer: str = ""
    disposition: str = "ABSTAIN"
    citation_sources: tuple[str | None, ...] = ()
    retrieved_sources: frozenset[str] = frozenset()
    execution_path: ExecutionPath | None = None
    planned_requirements: tuple[str, ...] = ()
    requested_requirements: tuple[str, ...] = ()
    initially_missing: tuple[str, ...] = ()
    finally_missing: tuple[str, ...] = ()
    graph_steps: int = 0
    tool_calls: int = 0
    retrieval_calls: int = 0
    duplicate_retrievals: int = 0
    duplicate_candidates: int = 0
    sec_calls: int = 0
    evidence_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    cost_usd: float = 0
    screened_slots: int = 0
    rejected_slots: int = 0
    verified_claims: int = 0
    correction_passes: int = 0
    planned_tasks: int = 0
    completed_tasks: int = 0
    handoff_links: int = 0
    resolved_handoff_links: int = 0
    trace: tuple[str, ...] = ()


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _source_key_set(citations: Sequence[int], sources: Sequence[str | None]) -> set[str]:
    return {source for number in citations if number <= len(sources) and (source := sources[number - 1]) is not None}


def evaluate_observation(case: AblationCase, run: AblationObservation, *, latency_ms: float) -> dict[str, Any]:
    answered = bool(run.answer.strip()) and not is_fallback_answer(run.answer)
    clauses = [part.strip() for part in _CLAUSE.split(run.answer) if part.strip()] if answered else []
    parsed = [
        (_normalized(statement), [item[:4] for item in numeric_fact_signatures(statement)],
         [int(value) for value in _CITATION.findall(statement)])
        for statement in clauses
    ]
    expected_slots = [slot for claim in case.claims for slot in claim.source_slots]
    claimed_values = sum(len(values) for _, values, _ in parsed)
    matched: set[int] = set()
    grounded_claims = supported_citations = 0
    claim_checks = []
    for claim in case.claims:
        gold_value = numeric_fact_signatures(claim.value)
        if len(gold_value) != 1 or not claim.source_slots:
            raise ValueError(f"Invalid labeled claim in {case.case_id}")
        terms = tuple(_normalized(term) for term in (*claim.terms, *claim.periods))
        target = gold_value[0][:4]
        match = next((
            index for index, (statement, values, _) in enumerate(parsed)
            if index not in matched and target in values
            and all(re.search(rf"\b{re.escape(term)}\b", statement) for term in terms)
        ), None)
        grounded = False
        if match is not None:
            matched.add(match)
            citations = parsed[match][2]
            allowed = {source for slot in claim.source_slots for source in slot}
            observed = _source_key_set(citations, run.citation_sources)
            supported = sum(
                number <= len(run.citation_sources) and run.citation_sources[number - 1] in allowed
                for number in citations
            )
            supported_citations += supported
            grounded = bool(citations) and supported == len(citations) and all(observed.intersection(slot) for slot in claim.source_slots)
            grounded_claims += int(grounded)
        claim_checks.append({"value": claim.value, "matched": match is not None, "grounded": grounded})

    numeric_exact = answered and claimed_values == len(matched) == len(case.claims)
    exact = bool(numeric_exact) if case.claims else not answered
    grounded_exact = exact and grounded_claims == len(case.claims)
    planned = set(run.planned_requirements)
    requested = set(run.requested_requirements)
    return {
        "case_id": case.case_id, "split": case.split, "category": case.category,
        "answerable": bool(case.claims), "answered": answered, "exact": exact,
        "grounded_exact": grounded_exact, "numeric_exact": numeric_exact if case.claims else None,
        "unsupported_released_claims": max(claimed_values, len(clauses)) - grounded_claims,
        "claim_checks": claim_checks, "matched_claims": len(matched), "grounded_claims": grounded_claims,
        "expected_claims": len(case.claims), "claimed_values": claimed_values,
        "supported_citations": supported_citations, "citations": sum(len(citations) for _, _, citations in parsed),
        "retrieved_source_coverage": (
            sum(bool(run.retrieved_sources.intersection(slot)) for slot in expected_slots) / len(expected_slots)
            if expected_slots else None
        ),
        "execution_path": run.execution_path, "intended_path": case.intended_path,
        "unnecessary_research": run.execution_path == ExecutionPath.RESEARCH and case.intended_path == ExecutionPath.FAST,
        "incorrect_fast_path": run.execution_path == ExecutionPath.FAST and case.intended_path == ExecutionPath.RESEARCH,
        "planned_slot_coverage": len(planned.intersection(requested)) / len(requested) if requested and run.execution_path else None,
        "initial_gaps": len(run.initially_missing),
        "resolved_gaps": len(set(run.initially_missing) - set(run.finally_missing)),
        "unnecessary_calls": run.tool_calls if case.intended_path == ExecutionPath.UNSUPPORTED else 0,
        "disposition": run.disposition, "answer": run.answer, "trace": run.trace,
        "latency_ms": round(latency_ms, 3), "graph_steps": run.graph_steps,
        "retrieval_calls": run.retrieval_calls, "tool_calls": run.tool_calls, "sec_calls": run.sec_calls,
        "duplicate_retrievals": run.duplicate_retrievals, "duplicate_candidates": run.duplicate_candidates,
        "evidence_tokens": run.evidence_tokens, "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens, "llm_calls": run.llm_calls, "cost_usd": run.cost_usd,
        "screened_slots": run.screened_slots, "rejected_slots": run.rejected_slots,
        "verified_claims": run.verified_claims, "correction_passes": run.correction_passes,
        "planned_tasks": run.planned_tasks, "completed_tasks": run.completed_tasks,
        "handoff_links": run.handoff_links, "resolved_handoff_links": run.resolved_handoff_links,
    }


def summarize_ablation(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"case_count": 0}
    answerable = [row for row in rows if row["answerable"]]
    unanswerable = [row for row in rows if not row["answerable"]]
    answered = [row for row in rows if row["answered"]]
    expected_claims = sum(row["expected_claims"] for row in rows)
    citations = sum(row["citations"] for row in rows)
    planned = [row["planned_slot_coverage"] for row in rows if row["planned_slot_coverage"] is not None]
    times = sorted(row["latency_ms"] for row in rows)

    def ratio(numerator, denominator):
        return round(numerator / denominator, 4) if denominator else None

    return {
        "case_count": len(rows), "answerable_cases": len(answerable), "unanswerable_cases": len(unanswerable),
        "coverage": ratio(len(answered), len(rows)), "answer_accuracy": ratio(sum(row["exact"] for row in rows), len(rows)),
        "grounded_exact_answers": sum(row["grounded_exact"] for row in answerable),
        "grounded_answer_accuracy": ratio(sum(row["grounded_exact"] for row in answerable), len(answerable)),
        "numeric_exact_accuracy": ratio(sum(row["numeric_exact"] for row in answerable), len(answerable)),
        "claim_support": ratio(sum(row["grounded_claims"] for row in rows), expected_claims),
        "citation_support": ratio(sum(row["supported_citations"] for row in rows), citations),
        "unsupported_answer_rate": ratio(sum(row["unsupported_released_claims"] > 0 for row in answered), len(answered)),
        "risk_at_coverage": ratio(sum(not row["grounded_exact"] for row in answered), len(answered)),
        "correct_abstention": ratio(sum(not row["answered"] for row in unanswerable), len(unanswerable)),
        "false_abstention": ratio(sum(not row["answered"] for row in answerable), len(answerable)),
        "retrieved_source_coverage": ratio(sum(row["retrieved_source_coverage"] for row in answerable), len(answerable)),
        "mean_planned_slot_coverage": round(mean(planned), 4) if planned else None,
        "task_success": ratio(sum(row["completed_tasks"] for row in rows), sum(row["planned_tasks"] for row in rows)),
        "resolved_handoff_links": ratio(sum(row["resolved_handoff_links"] for row in rows), sum(row["handoff_links"] for row in rows)),
        "unnecessary_research": sum(row["unnecessary_research"] for row in rows),
        "incorrect_fast_path": sum(row["incorrect_fast_path"] for row in rows),
        "routing_distribution": dict(Counter(row["execution_path"] for row in rows if row["execution_path"])),
        "latency_ms_p50": times[math.ceil(len(times) * .5) - 1],
        "latency_ms_p95": times[math.ceil(len(times) * .95) - 1],
        "mean_retrieval_calls": round(mean(row["retrieval_calls"] for row in rows), 4),
        "mean_tool_calls": round(mean(row["tool_calls"] for row in rows), 4),
        "mean_evidence_tokens": round(mean(row["evidence_tokens"] for row in rows), 4),
        "total_llm_calls": sum(row["llm_calls"] for row in rows),
        "mean_input_tokens": round(mean(row["input_tokens"] for row in rows), 4),
        "mean_output_tokens": round(mean(row["output_tokens"] for row in rows), 4),
        "estimated_cost_usd": sum(row["cost_usd"] for row in rows),
        "duplicate_retrievals": sum(row["duplicate_retrievals"] for row in rows),
        "duplicate_candidates": sum(row["duplicate_candidates"] for row in rows),
        "unnecessary_calls": sum(row["unnecessary_calls"] for row in rows),
        "initial_gaps": sum(row["initial_gaps"] for row in rows),
        "resolved_gaps": sum(row["resolved_gaps"] for row in rows),
    }
