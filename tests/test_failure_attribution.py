from collections import Counter
from decimal import Decimal

from configs.multi_agent_ablation import CASES
from src.decision.period_value_parser import extract_period_value_pairs
from src.evaluation.failure_attribution import FailureSignal, FailureStage, attribution, summarize_failures
from src.evaluation.m13_failure_replay import expected_slots, normalized_table, prepare_page_oracles
from src.retrieval.parent_context import PageParent


def test_primary_failure_is_ordered_and_secondary_causes_are_retained():
    signals = [
        FailureSignal(FailureStage.CLAIM_VERIFICATION, "claim blocked"),
        FailureSignal(FailureStage.CANDIDATE_RETRIEVAL, "expected page was absent", "revenue:2024"),
        FailureSignal(FailureStage.CLAIM_VERIFICATION, "claim blocked"),
    ]
    row = attribution(reversed(signals), failed=True)
    assert row == attribution(signals, failed=True)
    assert row["first_failure_stage"] == FailureStage.CANDIDATE_RETRIEVAL
    assert row["contributing_failure_stages"] == [FailureStage.CLAIM_VERIFICATION]
    assert len(row["failure_signals"]) == 2
    assert attribution(signals, failed=False)["first_failure_stage"] is None


def test_accounting_keeps_unassessed_oracles_out_of_unrecoverable_failures():
    shared = {"query_class": "simple_lookup", "unsupported_released_claims": 0}
    rows = [
        {**shared, "answerable": True, "answered": False, "oracle_recoverable": True,
         **attribution([FailureSignal(FailureStage.CANDIDATE_RETRIEVAL, "missing page")], failed=True)},
        {**shared, "answerable": True, "answered": False, "oracle_recoverable": None,
         **attribution([], failed=True)},
        {**shared, "answerable": False, "answered": False, "oracle_recoverable": None,
         **attribution([], failed=False)},
    ]
    summary = summarize_failures(rows)
    assert summary["failures_by_first_stage"] == Counter({
        FailureStage.CANDIDATE_RETRIEVAL: 1, FailureStage.UNDETERMINED: 1,
    })
    assert summary["total_failures"] == summary["false_abstentions"] == 2
    assert summary["attributed_fraction"] == 0.5
    assert summary["recoverable_failures"] == summary["oracle_unassessed_failures"] == 1
    assert summary["unrecoverable_failures"] == 0
    assert summary["correct_abstentions"] == 1


def test_oracle_page_is_raw_and_normalized_value_comes_from_source():
    case = next(item for item in CASES if item.case_id == "amcor_annual_revenue")
    slots = expected_slots(case)
    source = slots[0].sources[0]
    # Deliberately disagree with the answer label to detect leaking it into
    # the inputs of either oracle.
    text = "Consolidated Statements of Income\n($ in millions)\n2023 2022\nRevenue $42 $10"
    parent = PageParent("AMCOR_2023_10K", 49, text, ("child",), 20)
    raw, normalized = prepare_page_oracles(slots, {source: ({
        "doc_name": parent.document, "document_id": parent.document, "page_number": 49,
        "company": "Amcor", "source_url": "https://example.com/filing", "doc_type": "10k",
        "reporting_periods": ["2023"],
    }, parent)})
    assert raw[0]["text"] == text
    assert Decimal(normalized[0]["normalized_amount"]) == Decimal(42_000_000)
    assert Decimal(normalized[0]["normalized_amount"]) != slots[0].amount
    assert normalized[0]["period"] == "FY2023"


def test_normalized_oracle_chunk_preserves_quarter_and_base_units():
    text = normalized_table("Sample Corp", "revenue", "Q2 FY2024", "USD", Decimal("90753000000"))
    observations = extract_period_value_pairs(text, metric_aliases=("revenue",))
    assert any(
        item.period == "Q2 FY2024" and Decimal(item.numeric_value) == Decimal("90753000000")
        and item.currency == "USD" and item.scale == "unit"
        for item in observations
    )
    assert all(item.period != "FY2024" for item in observations)
