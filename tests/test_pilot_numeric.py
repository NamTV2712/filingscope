import pytest

from configs.sec_runtime_pilot import AAPL_Q_REVENUE, AAPL_REVENUE, AAPL_YTD_REVENUE, CASES, TSLA_ENERGY, WMT_REVENUE
from src.evaluation.pilot_numeric import matches_cell, score_claims


@pytest.mark.parametrize(("cell", "statement"), [
    (AAPL_REVENUE, "Apple Inc. total net sales were $416,161 million for the fiscal year ended September 27, 2025."),
    (AAPL_REVENUE, "AAPL reported revenue of USD 416.161 billion for FY2025 (ended 2025-09-27)."),
    (AAPL_Q_REVENUE, "Apple Inc. net sales were $94,036 million for the three months ended June 28, 2025."),
    (AAPL_YTD_REVENUE, "Apple revenue was $313,695 million for the nine months ended June 28, 2025."),
    (TSLA_ENERGY, "Tesla, Inc. reported energy generation and storage revenue of $10,086 million for fiscal year 2024."),
    (WMT_REVENUE, "Walmart Inc. total revenue for fiscal year 2025 was $680,985 million."),
])
def test_pilot_accepts_equivalent_exact_financial_claims(cell, statement):
    assert matches_cell(statement, cell)


@pytest.mark.parametrize(("cell", "statement"), [
    (AAPL_REVENUE, "Apple Inc. revenue was $416,161 million for the fiscal year ended September 28, 2025."),
    (AAPL_REVENUE, "Apple Inc. revenue was $416,161 million for FY2024, ending September 27, 2025."),
    (AAPL_REVENUE, "Apple Inc. revenue was $416,161 million in CY2025."),
    (AAPL_REVENUE, "Apple and NVIDIA revenue was $416,161 million for FY2025."),
    (AAPL_REVENUE, "Apple Inc. revenue was €416,161 million for FY2025."),
    (AAPL_REVENUE, "Apple Inc. revenue was $416.2 billion for FY2025."),
    (AAPL_REVENUE, "Apple's iPhone revenue was $416,161 million in FY2025."),
    (AAPL_REVENUE, "Apple Inc. restated revenue was $416,161 million for FY2025."),
    (AAPL_REVENUE, "Apple Inc. did not report $416,161 million of revenue for FY2025."),
    (AAPL_Q_REVENUE, "Apple reported Q3 FY2025 revenue of $94,036 million for the nine months ended June 28, 2025."),
    (AAPL_YTD_REVENUE, "Apple reported revenue of $313,695 million for the three months ended June 28, 2025."),
    (TSLA_ENERGY, "Tesla reported consolidated revenue of $10,086 million for FY2024."),
    (TSLA_ENERGY, "Tesla reported energy generation and storage leasing revenue of $10,086 million for FY2024."),
    (WMT_REVENUE, "Walmart reported net sales of $680,985 million for FY2025."),
])
def test_pilot_rejects_financial_identity_changes(cell, statement):
    assert not matches_cell(statement, cell)


def test_claim_completeness_and_exact_locator_are_separate():
    case = next(case for case in CASES if case.case_id == "apple_nvidia_revenue")
    apple = ("Apple Inc. revenue for FY2025 was $416,161 million.", "AAPL_2025_10K#p31")
    nvidia = ("NVIDIA Corporation revenue for FY2025 was $130,497 million.", "NVDA_2025_10K#p143")
    assert score_claims(case, [nvidia, apple])["grounded_exact"]
    assert not score_claims(case, [apple, apple])["exact"]
    assert not score_claims(case, [apple, nvidia, apple])["exact"]
    wrong = score_claims(case, [apple, (nvidia[0], "NVDA_2025_10K#p145")])
    assert wrong["exact"] and not wrong["grounded_exact"] and wrong["matching_locators"] == 1
