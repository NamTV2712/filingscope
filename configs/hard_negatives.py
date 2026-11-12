"""M12 offline judgments on the frozen P1 corpus. Page indexes are zero-based."""

from configs.financebench import P1_CORPUS_FINGERPRINT, P1_EMBEDDING_REVISION, P1_INDEX_ID
from src.evaluation.hard_negative_retrieval import HardNegative, HardNegativeCase, NegativeType, Passage


M2_SEED_CASES = (
    "financebench_id_01928", "financebench_id_01930", "financebench_id_01912",
    "financebench_id_04417", "financebench_id_00685", "financebench_id_01275", "financebench_id_01902",
)


def _passage(document: str, page: int, chunk: int, *anchors: str) -> Passage:
    return Passage(document, page, chunk, anchors)


_amcor20 = _passage("AMCOR_2020_10K", 49, 0, "Cash and cash equivalents $ 742.6", "Trade receivables, net 1,615.9")
_amcor23_balance = _passage("AMCOR_2023_10K", 51, 0, "Cash and cash equivalents $ 689 $ 775")
_amcor23_income = _passage("AMCOR_2023_10K", 49, 0, "Consolidated Statements of Income", "Net sales $ 14,694 $ 14,544")
_amcor23_release_sales = _passage("AMCOR_2023Q4_EARNINGS", 9, 0, "Twelve Months Ended", "11,154 3,540 14,694")
_amcor23_release_header = _passage("AMCOR_2023Q4_EARNINGS", 11, 0, "Twelve Months Ended June 30, 2023", "EBITDA EBIT")
_amcor23_release_ebitda = _passage("AMCOR_2023Q4_EARNINGS", 11, 1, "Adjusted EBITDA, EBIT, Net income and EPS", "2,018 1,608 1,089")
_mgm20_cash_flow_header = _passage("MGMRESORTS_2020_10K", 66, 0, "Consolidated Statements of Cash Flows", "December 31, 2020 2019 2018")
_mgm20_investing = _passage("MGMRESORTS_2020_10K", 66, 2, "investing activities 2,159,304 3,519,434")
_mgm20_operating = _passage("MGMRESORTS_2020_10K", 66, 1, "operating activities (1,493,043) 1,810,401")
_mgm20_financing = _passage("MGMRESORTS_2020_10K", 66, 4, "financing activities 2,103,427")
_mgm22_revenue = _passage("MGMRESORTS_2022_10K", 59, 0, "Consolidated Statements of Operations", "13,127,485 9,680,140")
_mgm22_release_revenue = _passage("MGMRESORTS_2022Q4_EARNINGS", 12, 0, "Supplemental Data", "13,127,485")
_mgm22_vegas = _passage("MGMRESORTS_2022Q4_EARNINGS", 13, 1, "Las Vegas Strip Resorts Adjusted Property EBITDAR", "2022 2021 2022 2021", "3,142,308")
_mgm22_company_reconciliation = _passage("MGMRESORTS_2022Q4_EARNINGS", 13, 0, "reconciliation of net income", "1,473,093")
_boeing18 = _passage("BOEING_2018_10K", 51, 0, "December 31, 2018 2017", "$117,359 $112,362")
_boeing17_revision = _passage("BOEING_2018_10K", 70, 0, "December 31, 2017 Impact of New", "$92,333 $20,029 $112,362")
_boeing22_income = _passage("BOEING_2022_10K", 54, 0, "Consolidated Statements of Operations", "Total revenues 66,608")
_boeing22_segments = _passage("BOEING_2022_10K", 61, 0, "Summary of Business Segment", "Total revenues $66,608")

_bestbuy17_original = _passage("BESTBUY_2017_10K", 40, 0, "Non-GAAP operating income $ 1,759 $ 1,566")
_bestbuy17_cash_flow = _passage("BESTBUY_2017_10K", 57, 0, "cash provided by operating activities 2,545")
_bestbuy19_header = _passage("BESTBUY_2019_10K", 38, 0, "Fiscal Year 2019 2018 2017 (1)")
_bestbuy19_recast = _passage("BESTBUY_2019_10K", 38, 1, "Non-GAAP operating income $ 1,988 $ 1,953 $ 1,733")
_bestbuy19_basis = _passage("BESTBUY_2019_10K", 38, 3, "we have recast fiscal 2017 balances")
_bestbuy19_balance = _passage("BESTBUY_2019_10K", 51, 0, "Total current assets 8,870 9,829")
_bestbuy19_cash_flow = _passage("BESTBUY_2019_10K", 54, 0, "cash provided by operating activities 2,408")
_bestbuy23_cash_flow = _passage("BESTBUY_2023_10K", 41, 0, "cash provided by operating activities 1,824")
_bestbuy24_q2_segment = _passage("BESTBUY_2024Q2_10Q", 17, 2, "Operating income $ 19 $ 28 $ 40 $ 61")
_bestbuy24_q2_non_gaap = _passage("BESTBUY_2024Q2_10Q", 19, 0, "Non-GAAP operating income $ 362 $ 427 $ 684 $ 912")
_bestbuy24_q2_cash = _passage("BESTBUY_2024Q2_10Q", 2, 0, "Consolidated Balance Sheets", "Cash and cash equivalents $ 1,093")
_bestbuy24_q2_liquidity = _passage("BESTBUY_2024Q2_10Q", 19, 2, "Liquidity and Capital Resources", "Cash and cash equivalents $ 1,093")
_bestbuy24_q2_cash_note = _passage("BESTBUY_2024Q2_10Q", 7, 2, "Consolidated Statements of Cash Flows", "Restricted cash included in Other current assets")
_nike19_balance = _passage("NIKE_2019_10K", 53, 0, "Total current assets 16,525 15,134")
_nike21_balance = _passage("NIKE_2021_10K", 60, 0, "Total current assets 26,291 20,556")
_nike21_income = _passage("NIKE_2021_10K", 58, 0, "Consolidated Statements of Income", "Net income $ 5,727 $ 2,539")
_nike21_cash_flow = _passage("NIKE_2021_10K", 61, 0, "Consolidated Statements of Cash Flows", "Net income $ 5,727 $ 2,539")
_nike21_mda = _passage("NIKE_2021_10K", 32, 0, "Results of Operations", "Net income $ 5,727 $ 2,539")

_general19_income = _passage("GENERALMILLS_2019_10K", 52, 0, "Cost of sales 11,108.4 10,304.8")
_general20_balance = _passage("GENERALMILLS_2020_10K", 49, 0, "Total current assets 5,121.3 4,186.5")
_general20_segments = _passage("GENERALMILLS_2020_10K", 89, 0, "North America Retail $ 10,750.5", "North America Retail $ 2,627.0")
_general20_income = _passage("GENERALMILLS_2020_10K", 47, 0, "Consolidated Statements of Earnings", "Net earnings attributable to General Mills $ 2,181.2")
_general20_cash_flow = _passage("GENERALMILLS_2020_10K", 51, 0, "Consolidated Statements of Cash Flows", "3,676.2 2,807.0 2,841.0")
_general20_eps = _passage("GENERALMILLS_2020_10K", 77, 0, "Note 13. Earnings Per Share", "Net earnings attributable to General Mills $ 2,181.2")
_general22_balance = _passage("GENERALMILLS_2022_10K", 46, 0, "Total current assets 5,089.8 5,754.5")
_general22_income = _passage("GENERALMILLS_2022_10K", 44, 0, "Cost of sales 12,590.6 11,678.7 11,496.7")
_general22_recast = _passage("GENERALMILLS_2022_10K", 83, 1, "11,572.0 $ 11,250.0 $ 10,978.1", "2,699.7 $ 2,725.9 $ 2,708.9")
_general22_basis = _passage("GENERALMILLS_2022_10K", 82, 1, "We have restated our net sales by segment and segment operating profit")
_corning20_balance = _passage("CORNING_2020_10K", 71, 0, "Total current assets 8,004 7,463")
_corning20_income = _passage("CORNING_2020_10K", 69, 0, "Operating income 509 1,306 1,575")
_corning21_income = _passage("CORNING_2021_10K", 64, 0, "Operating income 2,112 509 1,306")
_corning21_eps = _passage("CORNING_2021_10K", 64, 1, "Net income attributable to Corning Incorporated $ 1,906 $ 512")
_corning22_balance = _passage("CORNING_2022_10K", 59, 0, "Total current assets 7,453 7,659")


def _case(case_id, split, question, positives, *negatives) -> HardNegativeCase:
    return HardNegativeCase(case_id, split, question, positives, tuple(HardNegative(*pair) for pair in negatives))


D, V, H = "development", "validation", "held_out"
COMPANY, PERIOD, METRIC, DISCLOSURE, REVISION = NegativeType

CASES = (
    _case("amcor_fy2020_cash", D, "What cash and cash equivalents did Amcor report on its FY2020 balance sheet?",
          (_amcor20,), (PERIOD, _amcor23_balance)),
    _case("amcor_fy2023_audited_sales", D, "What were Amcor's FY2023 net sales in its audited consolidated income statement?",
          (_amcor23_income,), (DISCLOSURE, _amcor23_release_sales)),
    _case("amcor_fy2023_ebitda", D, "What was Amcor's adjusted EBITDA for the twelve months ended June 30, 2023, in its Q4 earnings release?",
          (_amcor23_release_header, _amcor23_release_ebitda), (METRIC, _amcor23_release_sales)),
    _case("mgm_fy2020_investing", D, "What net cash did MGM Resorts obtain from investing activities in its FY2020 statement of cash flows?",
          (_mgm20_cash_flow_header, _mgm20_investing), (METRIC, _mgm20_operating), (METRIC, _mgm20_financing)),
    _case("mgm_fy2022_audited_revenue", D, "What consolidated net revenue did MGM Resorts report for FY2022 in its audited statement of operations?",
          (_mgm22_revenue,), (DISCLOSURE, _mgm22_release_revenue), (COMPANY, _boeing22_income)),
    _case("mgm_fy2022_vegas_ebitdar", D, "What was full-year FY2022 Las Vegas Strip Resorts adjusted property EBITDAR in MGM Resorts' table-games hold reconciliation?",
          (_mgm22_vegas,), (METRIC, _mgm22_company_reconciliation)),
    _case("boeing_fy2022_audited_revenue", D, "What total revenue did Boeing report for FY2022 on the face of its consolidated statement of operations?",
          (_boeing22_income,), (DISCLOSURE, _boeing22_segments), (COMPANY, _mgm22_revenue)),
    _case("boeing_fy2018_assets", D, "How much were Boeing's consolidated total assets at December 31, 2018, in its statement of financial position?",
          (_boeing18,), (PERIOD, _boeing17_revision)),

    _case("bestbuy_fy2017_original", V, "What non-GAAP operating income did Best Buy originally report for FY2017 in its FY2017 10-K?",
          (_bestbuy17_original,), (REVISION, _bestbuy19_recast)),
    _case("bestbuy_fy2017_recast", V, "What was Best Buy's recast FY2017 non-GAAP operating income under the revised presentation in its FY2019 10-K?",
          (_bestbuy19_header, _bestbuy19_recast, _bestbuy19_basis), (REVISION, _bestbuy17_original)),
    _case("bestbuy_fy2019_current_assets", V, "What were Best Buy's total current assets at its FY2019 year end?",
          (_bestbuy19_balance,), (COMPANY, _nike19_balance)),
    _case("nike_fy2019_current_assets", V, "What total current assets did Nike report in its FY2019 balance sheet?",
          (_nike19_balance,), (COMPANY, _bestbuy19_balance), (PERIOD, _nike21_balance)),
    _case("nike_fy2021_income", V, "What was Nike's net income in the audited FY2021 consolidated statement of income?",
          (_nike21_income,), (DISCLOSURE, _nike21_cash_flow), (DISCLOSURE, _nike21_mda)),
    _case("bestbuy_fy2024_q2_adjusted_income", V, "What was Best Buy's consolidated non-GAAP operating income for the three months ended July 29, 2023 (FY2024 Q2)?",
          (_bestbuy24_q2_non_gaap,), (METRIC, _bestbuy24_q2_segment)),
    _case("bestbuy_fy2024_q2_balance_cash", V, "What cash and cash equivalents did Best Buy show on its July 29, 2023 balance sheet?",
          (_bestbuy24_q2_cash,), (DISCLOSURE, _bestbuy24_q2_liquidity), (DISCLOSURE, _bestbuy24_q2_cash_note)),
    _case("bestbuy_fy2023_operating_cash", V, "What cash was provided by Best Buy's operating activities in the FY2023 consolidated cash flow statement?",
          (_bestbuy23_cash_flow,), (PERIOD, _bestbuy19_cash_flow), (PERIOD, _bestbuy17_cash_flow)),

    _case("general_mills_fy2020_segment_sales_original", H, "What FY2020 net sales did General Mills originally report for North America Retail in its FY2020 annual report?",
          (_general20_segments,), (REVISION, _general22_recast)),
    _case("general_mills_fy2020_segment_sales_recast", H, "What FY2020 net sales did General Mills disclose for North America Retail after the segment reorganization in its FY2022 10-K?",
          (_general22_recast, _general22_basis), (REVISION, _general20_segments)),
    _case("general_mills_fy2020_current_assets", H, "What were General Mills' total current assets at its FY2020 year end?",
          (_general20_balance,), (PERIOD, _general22_balance), (COMPANY, _corning20_balance)),
    _case("general_mills_fy2020_earnings", H, "What net earnings attributable to General Mills appeared in the consolidated statement of earnings for FY2020?",
          (_general20_income,), (DISCLOSURE, _general20_eps), (METRIC, _general20_cash_flow)),
    _case("general_mills_fy2019_cost_of_sales", H, "What cost of sales did General Mills report in its original FY2019 consolidated earnings statement?",
          (_general19_income,), (PERIOD, _general22_income)),
    _case("corning_fy2021_operating_income", H, "What operating income did Corning record in its FY2021 consolidated income statement?",
          (_corning21_income,), (PERIOD, _corning20_income), (METRIC, _corning21_eps)),
    _case("corning_fy2022_current_assets", H, "What were Corning's total current assets at the FY2022 balance sheet date?",
          (_corning22_balance,), (PERIOD, _corning20_balance), (COMPANY, _general22_balance)),
    _case("general_mills_fy2020_segment_profit_recast", H, "What was General Mills' FY2020 North America Retail segment operating profit on the reorganized basis disclosed in the FY2022 annual report?",
          (_general22_recast, _general22_basis), (REVISION, _general20_segments)),
)
