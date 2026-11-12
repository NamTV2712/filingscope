"""Public evidence view of a completed local research request."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from src.agent.specialist_graph import SpecialistExecution
from src.ledger.models import EvidenceRecord, EvidenceSourceType
from src.verification.models import ClaimStatus
from src.verification.response_policy import INSUFFICIENT_EVIDENCE_ANSWER


def _public_url(value: str | None) -> str | None:
    if not value or any(ord(char) < 33 or char == "\\" for char in value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme in {"http", "https"} and url.hostname and url.username is None and url.password is None:
            return value
    except ValueError:
        pass
    return None


def _source(record: EvidenceRecord, citation: int | None) -> dict[str, Any]:
    xbrl = record.xbrl_provenance
    return {
        "id": record.evidence_id,
        "citation": citation,
        "company": record.company,
        "document": record.document_id,
        "type": record.source_type,
        "form": record.form_type,
        "page": record.page,
        "period": record.fiscal_period,
        "filed": record.filing_date,
        "section": record.section,
        "metric": record.metric,
        "value": record.raw_value,
        "unit": record.unit,
        "url": _public_url(record.source_url),
        "accession": xbrl.accession if xbrl else None,
        "revision": xbrl.revision_kind if xbrl else None,
        "revision_policy": xbrl.revision_policy if xbrl else None,
        "tag": xbrl.tag if xbrl else None,
        "start": xbrl.period_start if xbrl else None,
        "end": xbrl.period_end if xbrl else None,
        "facts_url": _public_url(xbrl.company_facts_url) if xbrl else None,
    }


_SEARCH_WORKERS = {
    "filing_research_worker": "Filings",
    "structured_financial_data_worker": "Structured facts",
    "table_evidence_worker": "Financial tables",
}
_SEARCH_ISSUES = {
    "retrieval": "Filing retrieval is unavailable.",
    "retrieval_error": "A filing search failed.",
    "budget": "A research limit was reached.",
    "xbrl": "Structured facts are unavailable.",
    "xbrl_error": "A structured fact lookup failed.",
    "xbrl_unavailable": "A requested structured fact was unavailable.",
    "table_budget": "The table search had no remaining budget or retriever.",
    "table_retrieval_error": "A table search failed.",
    "table_query": "A table search returned no matching table evidence.",
}
_STRUCTURED_GAPS = {
    "original_period_unavailable": "The SEC snapshot has no original filing fact for the requested fiscal period.",
    "changed_revision_unavailable": "The SEC snapshot has no changed revision for the requested fact.",
    "conflicting_original_values": "Original filing observations disagree.",
    "conflicting_latest_values": "Latest filing observations disagree.",
    "ambiguous_period": "Multiple fiscal intervals matched the structured fact.",
    "ambiguous_currency": "Multiple currencies matched the structured fact.",
    "ambiguous_taxonomy": "Multiple taxonomies matched the structured fact.",
    "unsupported_concept": "The requested metric has no supported structured concept.",
}


def _search_issue(key: str, value: str) -> str | None:
    if key == "xbrl_unavailable":
        return _STRUCTURED_GAPS.get(value.rsplit(":", 1)[-1], _SEARCH_ISSUES[key])
    return _SEARCH_ISSUES.get(key)


def public_result(result: SpecialistExecution) -> dict[str, Any]:
    snapshot = result.ledger_snapshot
    coverage = result.coverage
    requirements = coverage.requirements if coverage else snapshot.question_requirements
    findings = {item.requirement_id: item for item in coverage.findings} if coverage else {}
    entities = {item.entity_id: item.canonical_name for item in requirements.entities} if requirements else {}
    metrics = {item.metric_id: item.display_name for item in requirements.metrics} if requirements else {}
    numbers = {item: index for index, item in enumerate(result.citation_evidence_ids, 1)}
    primary = [record for record in snapshot.evidence_records if record.source_type != EvidenceSourceType.DERIVED_FACT]
    primary.sort(key=lambda record: (numbers.get(record.evidence_id, float("inf")), record.evidence_id))
    primary_ids = {record.evidence_id for record in primary}
    supported_answer = result.status in {"VERIFIED", "PARTIAL"}
    verification = result.verification
    final_claims = verification.claims if verification else ()
    ledger_claims = {claim.claim_id: claim for claim in snapshot.claims}
    claims = [{
        "id": claim.claim_id,
        "statement": claim.statement if supported_answer and claim.status == ClaimStatus.SUPPORTED else None,
        "status": claim.status,
        "type": claim.claim_type,
        "citation_status": claim.citation_status,
        "source_ids": [item for item in claim.supporting_evidence_ids if item in primary_ids],
        "requirement_ids": claim.requirement_ids,
        "calculation_id": ledger_claims[claim.claim_id].calculation_id if claim.claim_id in ledger_claims else None,
        "reason_codes": claim.reason_codes,
    } for claim in final_claims]
    checked_calculations = {
        ledger_claims[claim.claim_id].calculation_id: claim.calculation.status
        for claim in final_claims if claim.calculation and claim.claim_id in ledger_claims
    }
    source_ids_by_chunk: dict[str, str] = {}
    for record in primary:
        if record.chunk_id:
            source_ids_by_chunk.setdefault(record.chunk_id, record.evidence_id)
    rows = []
    for item in requirements.evidence if requirements else ():
        finding = findings.get(item.requirement_id)
        reason = finding.missing_reason if finding else None
        if reason == "entity_mismatch" and not result.usage.candidate_chunks:
            reason = "no_candidate_evidence"
        rows.append({
            "id": item.requirement_id,
            "company": entities.get(item.entity_id, item.entity_id),
            "metric": metrics.get(item.metric_id, item.metric_id),
            "period": item.period,
            "status": finding.status if finding else "not_evaluated",
            "reason": reason,
            "source_ids": list(dict.fromkeys(
                source_ids_by_chunk[chunk_id] for chunk_id in (finding.evidence_ids if finding else ())
                if chunk_id in source_ids_by_chunk
            )),
        })
    return {
        "status": result.status,
        "route": result.selected_path,
        "answer": result.answer if supported_answer else INSUFFICIENT_EVIDENCE_ANSWER,
        "sources": [_source(record, numbers.get(record.evidence_id)) for record in primary],
        "coverage": rows,
        "coverage_sufficient": coverage.sufficient if coverage else None,
        "coverage_issues": tuple(dict.fromkeys((
            *(coverage.operation_gaps if coverage else ()),
            *(result.decision.gap_codes if result.decision else ()),
            *(requirements.unsupported_reasons if requirements else ()),
            *(result.route.decision.reason_codes if result.status == "UNSUPPORTED" else ()),
        ))),
        "calculations": [{
            "id": calculation.calculation_id,
            "operation": calculation.operation,
            "formula": calculation.formula,
            "result": str(calculation.result),
            "unit": calculation.unit,
            "period": calculation.fiscal_period,
            "status": checked_calculations.get(calculation.calculation_id, calculation.validation_status),
            "rounding": calculation.rounding_policy,
            "inputs": [
                {"value": value, "source_id": evidence_id}
                for value, evidence_id in zip(calculation.normalized_inputs, calculation.input_evidence_ids, strict=True)
            ],
        } for calculation in result.calculations],
        "verification": {
            "disposition": verification.disposition,
            "reason_codes": verification.reason_codes,
            "claims": claims,
        } if verification else None,
        "attempts": [{
            "stage": _SEARCH_WORKERS[receipt.worker_id],
            "status": receipt.status,
            "searches": receipt.retrieval_calls,
            "tools": receipt.tool_calls,
            "candidates": receipt.candidate_chunks,
            "issues": list(dict.fromkeys(
                issue for item in receipt.observations if (issue := _search_issue(item.key, item.value))
            )),
        } for receipt in result.specialist_results if receipt.worker_id in _SEARCH_WORKERS],
        "scopes": [{
            "company": task.company_name,
            "metric": metrics.get(task.metric_id, task.metric_id),
            "period": task.period,
            "availability": task.source_availability,
            "documents": len(task.target_document_ids),
        } for task in (result.route.research_plan.tasks if result.route.research_plan else ())],
        "usage": {
            "retrieval_calls": result.usage.retrieval_calls,
            "tool_calls": result.usage.tool_calls,
            "llm_calls": result.usage.llm_calls,
            "wall_time_ms": result.usage.wall_time_ms,
        },
    }
