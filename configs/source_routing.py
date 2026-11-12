"""Source-checked provisional Q3 routing labels kept out of runtime."""

from configs.multi_agent_ablation import AblationCase, GoldClaim
from src.agent.complexity_router import ExecutionPath


def _direct(case_id, split, company, metric, period, amount, *sources, category="simple_lookup", question=None):
    return AblationCase(
        case_id, split, category, question or f"What was {company}'s {period} {metric}?", ExecutionPath.FAST,
        (GoldClaim(f"USD {amount}", (company, metric), (sources,), (period,)),),
    )


D, V = "development", "validation"
# Source adjudication confirmed these original statement pages after
# inspecting the controls' unchanged answers and citation positions.
ADJUDICATED_PDF_LOCATORS = {
    "best_buy_assets_2023": "BESTBUY_2023_10K#p38",
    "nike_assets_2021": "NIKE_2021_10K#p60",
}
CASES = (
    _direct("apple_assets_2024", D, "Apple", "total assets", "FY2024", "364,980 million", "sec:0000320193-24-000123"),
    _direct("apple_net_income_2024", D, "Apple", "net income", "FY2024", "93,736 million", "sec:0000320193-24-000123"),
    _direct("apple_ytd_revenue_2024", D, "Apple", "revenue", "Q2 YTD FY2024", "210,328 million", "sec:0000320193-24-000069"),
    _direct("boeing_net_income_2022", D, "Boeing", "net income", "FY2022", "-4,935 million",
            "sec:0000012927-23-000007", "BOEING_2022_10K#p54"),
    _direct("general_mills_revenue_2022", D, "General Mills", "revenue", "FY2022", "18,992.8 million",
            "GENERALMILLS_2022_10K#p44", "sec:0001193125-22-185257", category="missing_xbrl"),
    _direct("msft_assets_2024", V, "Microsoft", "total assets", "FY2024", "512,163 million", "sec:0000950170-24-087843"),
    _direct("msft_net_income_2024", V, "Microsoft", "net income", "FY2024", "88,136 million", "sec:0000950170-24-087843"),
    _direct("msft_operating_income_2024", V, "Microsoft", "operating income", "FY2024", "109,433 million",
            "sec:0000950170-24-087843"),
    _direct("nike_assets_2021", V, "Nike", "total assets", "FY2021", "37,740 million",
            "sec:0000320187-21-000028", ADJUDICATED_PDF_LOCATORS["nike_assets_2021"]),
    _direct("nike_net_income_2021", V, "Nike", "net income", "FY2021", "5,727 million",
            "sec:0000320187-21-000028", "NIKE_2021_10K#p58"),
    _direct("best_buy_assets_2023", V, "Best Buy", "total assets", "FY2023", "15,803 million",
            "sec:0000764478-23-000006", ADJUDICATED_PDF_LOCATORS["best_buy_assets_2023"]),
    _direct("best_buy_net_income_2023", V, "Best Buy", "net income", "FY2023", "1,419 million",
            "sec:0000764478-23-000006", "BESTBUY_2023_10K#p39"),
    _direct("mgm_assets_2022", V, "MGM Resorts", "total assets", "FY2022", "45,692,206 thousand",
            "sec:0000789570-23-000008", "MGMRESORTS_2022_10K#p58"),
    _direct("costco_operating_income_2021", V, "Costco", "operating income", "FY2021", "6,708 million",
            "COSTCO_2021_10K#p35", category="table_lookup",
            question="What was Costco's FY2021 operating income in its consolidated statement of income?"),
    AblationCase(
        "costco_unknown_future", V, "unanswerable", "Forecast Costco's FY2035 total assets.",
        ExecutionPath.UNSUPPORTED, (),
    ),
)
