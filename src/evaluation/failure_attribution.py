"""Typed first-failure accounting for offline financial question replays."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class FailureStage(StrEnum):
    ENTITY_RESOLUTION = "ENTITY_RESOLUTION"
    METRIC_RESOLUTION = "METRIC_RESOLUTION"
    PERIOD_RESOLUTION = "PERIOD_RESOLUTION"
    FILING_REVISION = "FILING_REVISION"
    COMPLEXITY_ROUTING = "COMPLEXITY_ROUTING"
    SOURCE_CAPABILITY_ROUTING = "SOURCE_CAPABILITY_ROUTING"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    CANDIDATE_RETRIEVAL = "CANDIDATE_RETRIEVAL"
    RANKING = "RANKING"
    SOURCE_PROVENANCE = "SOURCE_PROVENANCE"
    TABLE_HEADER_ALIGNMENT = "TABLE_HEADER_ALIGNMENT"
    TABLE_CELL_EXTRACTION = "TABLE_CELL_EXTRACTION"
    XBRL_FACT_NORMALIZATION = "XBRL_FACT_NORMALIZATION"
    CANDIDATE_POLICY = "CANDIDATE_POLICY"
    EVIDENCE_SET_SUFFICIENCY = "EVIDENCE_SET_SUFFICIENCY"
    FINANCIAL_REASONING = "FINANCIAL_REASONING"
    ANSWER_GENERATION = "ANSWER_GENERATION"
    CLAIM_VERIFICATION = "CLAIM_VERIFICATION"
    FINAL_RELEASE_POLICY = "FINAL_RELEASE_POLICY"
    UNDETERMINED = "UNDETERMINED"


# Declaration order follows the evidence flow. Availability is checked before
# candidate retrieval. A missing observation must never outrank a measured loss.
STAGE_ORDER = {stage: index for index, stage in enumerate(FailureStage)}


@dataclass(frozen=True)
class FailureSignal:
    stage: FailureStage
    reason: str
    slot: str | None = None


def attribution(signals: Iterable[FailureSignal], *, failed: bool) -> dict:
    if not failed:
        return {
            "first_failure_stage": None, "contributing_failure_stages": [],
            "failure_reason": None, "failure_signals": [],
        }
    observed = sorted(
        set(signals) or {FailureSignal(FailureStage.UNDETERMINED, "no demonstrated loss")},
        key=lambda item: (STAGE_ORDER[item.stage], item.slot or "", item.reason),
    )
    first = observed[0]
    return {
        "first_failure_stage": first.stage,
        "contributing_failure_stages": list(dict.fromkeys(
            item.stage for item in observed if item.stage != first.stage
        )),
        "failure_reason": first.reason,
        "failure_signals": [
            {"stage": item.stage, "reason": item.reason, "slot": item.slot} for item in observed
        ],
    }


def summarize_failures(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    failed = [row for row in rows if row["first_failure_stage"] is not None]
    stages = Counter(row["first_failure_stage"] for row in failed)
    assessed = [row for row in failed if row["oracle_recoverable"] is not None]
    recoverable = sum(row["oracle_recoverable"] for row in assessed)
    attributed = len(failed) - stages[FailureStage.UNDETERMINED]
    return {
        "total_failures": len(failed),
        "attributed_failures": attributed,
        "attributed_fraction": attributed / len(failed) if failed else None,
        "failures_by_first_stage": dict(stages),
        "failures_by_query_class": dict(Counter(row["query_class"] for row in failed)),
        "false_abstentions": sum(row["answerable"] and not row["answered"] for row in rows),
        "correct_abstentions": sum(not row["answerable"] and not row["answered"] for row in rows),
        "unsupported_releases": sum(row["unsupported_released_claims"] > 0 for row in rows),
        "recoverable_failures": recoverable,
        "unrecoverable_failures": len(assessed) - recoverable,
        "oracle_unassessed_failures": len(failed) - len(assessed),
    }
