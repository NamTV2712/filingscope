"""Frozen M11 claim and response labels for the controlled verifier replay."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from src.decision.policy import EvidenceDecisionLayer
from src.evaluation.verification_evaluation import _financial_chunk, _industry_chunk
from src.verification.atomic_claim_verifier import AtomicClaimVerifier
from src.verification.claim_verifier import ClaimLevelVerifier
from src.verification.models import ClaimStatus, ResponseDisposition
from src.verification.response_policy import verify_and_release


@dataclass(frozen=True)
class AdvancedVerificationCase:
    case_id: str
    question: str
    answer: str
    evidence: tuple[dict[str, Any], ...]
    claim_statuses: tuple[ClaimStatus, ...]
    release: ResponseDisposition
    corrections: int = 0


def advanced_verification_cases() -> tuple[AdvancedVerificationCase, ...]:
    s = ClaimStatus.SUPPORTED
    u = ClaimStatus.UNSUPPORTED
    c = ClaimStatus.CONTRADICTED
    v = ClaimStatus.UNVERIFIABLE
    verified = ResponseDisposition.VERIFIED
    partial = ResponseDisposition.PARTIAL
    rejected = ResponseDisposition.REJECTED
    abstain = ResponseDisposition.ABSTAIN
    revenue = _financial_chunk(chunk_id="apple-revenue")
    income = _financial_chunk(chunk_id="apple-income", label="Net income", values=(("2024", "$25 billion"),))
    profile = _industry_chunk()
    excluded = {**profile, "text": "Amcor plc does not operate in the aerospace industry."}
    unrelated = {**profile, "text": (
        "Amcor plc operates in the packaging industry. The aerospace industry is a third-party market."
    )}
    conditional = {**profile, "text": "Amcor plc may operate in the aerospace industry in the future."}
    lookup = "What was Apple's revenue in FY2024?"
    both = "What were Apple's revenue and net income in FY2024?"
    growth = "Did Apple's revenue grow from FY2023 to FY2024?"
    industry = "What industry does Amcor operate in?"
    return (
        AdvancedVerificationCase("direct_value", lookup,
            "Apple revenue was $110 billion in FY2024 [Source 1].", (revenue,), (s,), verified),
        AdvancedVerificationCase("wrong_value", lookup,
            "Apple revenue was $109 billion in FY2024 [Source 1].", (revenue,), (c,), rejected),
        AdvancedVerificationCase("wrong_metric", lookup,
            "Apple net income was $25 billion in FY2024 [Source 1].", (income,), (s,), abstain),
        AdvancedVerificationCase("compound_shared_sources", both,
            "Apple revenue was $110 billion and net income was $25 billion in FY2024 [Source 1] [Source 2].",
            (revenue, income), (s, s), verified),
        AdvancedVerificationCase("compound_mixed_support", both,
            "Apple revenue was $110 billion and net income was $29 billion in FY2024 [Source 1] [Source 2].",
            (revenue, income), (s, c), partial, 1),
        AdvancedVerificationCase("compound_local_sources", both,
            "Apple revenue was $110 billion in FY2024 [Source 1], and Apple net income was $25 billion in FY2024 [Source 2].",
            (revenue, income), (s, s), verified),
        AdvancedVerificationCase("citation_does_not_carry_right", both,
            "Apple revenue was $110 billion in FY2024 [Source 1], and Apple net income was $25 billion in FY2024.",
            (revenue, income), (s, v), partial, 1),
        AdvancedVerificationCase("growth_verified", growth,
            "Apple revenue grew 10% from FY2023 to FY2024 [Source 1].", (revenue,), (s,), verified),
        AdvancedVerificationCase("growth_correctable", growth,
            "Apple revenue grew 15% from FY2023 to FY2024 [Source 1].", (revenue,), (c,), verified, 1),
        AdvancedVerificationCase("growth_direction_correctable", growth,
            "Apple revenue fell 10% from FY2023 to FY2024 [Source 1].", (revenue,), (c,), verified, 1),
        AdvancedVerificationCase("industry_paraphrase", industry,
            "Amcor is in the packaging sector [Source 1].", (profile,), (s,), verified),
        AdvancedVerificationCase("industry_refuted", industry,
            "Amcor operates in the aerospace industry [Source 1].", (excluded,), (c,), rejected),
        AdvancedVerificationCase("industry_irrelevant_mention", industry,
            "Amcor operates in the aerospace industry [Source 1].", (unrelated,), (u,), rejected),
        AdvancedVerificationCase("industry_conditional", industry,
            "Amcor operates in the aerospace industry [Source 1].", (conditional,), (u,), rejected),
        AdvancedVerificationCase("no_citation", lookup,
            "Apple revenue was $110 billion in FY2024.", (revenue,), (v,), abstain),
        AdvancedVerificationCase("no_answer", lookup,
            "I could not find sufficient information to answer.", (revenue,), (), abstain),
    )


def evaluate_advanced_verification(*, repeats: int = 20) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    cases = advanced_verification_cases()
    baseline, atomic = ClaimLevelVerifier(), AtomicClaimVerifier()
    extractor = EvidenceDecisionLayer().extractor
    timings = {"P4": [], "M11": []}
    rows = []
    for case in cases:
        requirements = extractor.extract(case.question)
        chunks = list(case.evidence)
        for _ in range(repeats):
            started = time.perf_counter_ns()
            previous = baseline.verify(case.question, case.answer, chunks)
            timings["P4"].append((time.perf_counter_ns() - started) / 1e6)
            started = time.perf_counter_ns()
            release = verify_and_release(atomic, case.question, case.answer, chunks, requirements)
            timings["M11"].append((time.perf_counter_ns() - started) / 1e6)
        rows.append({
            "case_id": case.case_id,
            "expected": {"claim_statuses": case.claim_statuses, "release": case.release, "passes": case.corrections},
            "P4": {"claim_statuses": tuple(item.status for item in previous.claims),
                   "release": previous.disposition, "initial": previous.disposition, "passes": 0},
            "M11": {"claim_statuses": tuple(item.status for item in release.initial.claims),
                    "release": release.result.disposition, "initial": release.initial.disposition,
                    "passes": release.correction_passes, "answer": release.answer},
        })
    summary = {}
    for variant, times in timings.items():
        times.sort()
        summary[variant] = {
            "exact_draft_claim_status_sequences": sum(
                row[variant]["claim_statuses"] == row["expected"]["claim_statuses"] for row in rows
            ),
            "expected_release_dispositions": sum(row[variant]["release"] == row["expected"]["release"] for row in rows),
            "expected_correction_counts": sum(row[variant]["passes"] == row["expected"]["passes"] for row in rows),
            "verified_drafts_with_non_supported_claims": sum(
                row[variant]["initial"] == ResponseDisposition.VERIFIED
                and any(status != ClaimStatus.SUPPORTED for status in row["expected"]["claim_statuses"])
                for row in rows
            ),
            "p50_ms": round(times[math.ceil(len(times) * 0.5) - 1], 3),
            "p95_ms": round(times[math.ceil(len(times) * 0.95) - 1], 3),
        }
    return {"case_count": len(cases), "timing_repeats_per_case": repeats, "summary": summary, "cases": rows}
