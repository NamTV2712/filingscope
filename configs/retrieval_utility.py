"""Q5 filing-based answer labels, separate from M12 passage judgments."""

from dataclasses import dataclass

from configs.multi_agent_ablation import AblationCase, GoldClaim
from src.agent.complexity_router import ExecutionPath


@dataclass(frozen=True)
class Filing:
    company: str
    document: str
    split: str


def fact(filing, page, metric, period, amount, *, scale="million", alternatives=()):
    return GoldClaim(f"USD {amount:,} {scale}", (filing.company, metric),
                     ((f"{filing.document}#p{page}", *alternatives),), (period,))


def case(filing, name, category, question, *claims):
    return AblationCase(name, filing.split, category, question, ExecutionPath.RESEARCH, claims)


def lookup(filing, name, page, metric, period, amount, *, scale="million", category="annual_lookup", question=None):
    return case(filing, name, category, question or f"What was {filing.company}'s {period} {metric}?",
                fact(filing, page, metric, period, amount, scale=scale))


D, V = "development", "validation"
ADOBE = Filing("Adobe", "ADOBE_2022_10K", D)
COSTCO = Filing("Costco", "COSTCO_2021_10K", D)
MMM = Filing("3M", "3M_2023Q2_10Q", D)
JPM = Filing("JPMorgan", "JPMORGAN_2022Q2_10Q", D)
PFIZER = Filing("Pfizer", "Pfizer_2023Q2_10Q", D)
AES = Filing("AES", "AES_2022_10K", V)
ACTIVISION = Filing("Activision Blizzard", "ACTIVISIONBLIZZARD_2019_10K", V)
WATER = Filing("American Water Works", "AMERICANWATERWORKS_2022_10K", V)
BLOCK = Filing("Block", "BLOCK_2020_10K", V)
KRAFT = Filing("Kraft Heinz", "KRAFTHEINZ_2019_10K", V)
PAYPAL = Filing("PayPal", "PAYPAL_2022_10K", V)

CASES = (
    lookup(ADOBE, "adobe_sales", 53, "revenue", "FY2022", 17606),
    case(ADOBE, "adobe_two_statements", "multi_statement",
         "What were Adobe's FY2022 revenue and cash and cash equivalents in its 10-K?",
         fact(ADOBE, 53, "revenue", "FY2022", 17606), fact(ADOBE, 52, "cash and cash equivalents", "FY2022", 4236)),
    lookup(COSTCO, "costco_assets", 37, "total assets", "FY2021", 59268),
    lookup(COSTCO, "costco_revenue", 35, "revenue", "FY2021", 195929,
           question="What was Costco's FY2021 revenue including membership fees in the consolidated income statement?"),
    case(COSTCO, "costco_two_statements", "multi_statement", "Compare Costco's FY2021 revenue and total assets.",
         fact(COSTCO, 35, "revenue", "FY2021", 195929), fact(COSTCO, 37, "total assets", "FY2021", 59268)),
    lookup(MMM, "mmm_quarter_revenue", 2, "revenue", "Q2 FY2023", 8325, category="quarter_vs_ytd"),
    lookup(MMM, "mmm_ytd_revenue", 2, "revenue", "Q2 YTD FY2023", 16356, category="quarter_vs_ytd"),
    lookup(MMM, "mmm_quarter_loss", 2, "operating income", "Q2 FY2023", -8958, category="quarter_vs_ytd"),
    lookup(MMM, "mmm_quarter_assets", 4, "total assets", "Q2 FY2023", 48880, category="quarter_lookup"),
    lookup(JPM, "jpm_quarter_revenue", 87, "revenue", "Q2 FY2022", 30715, category="quarter_vs_ytd"),
    lookup(JPM, "jpm_ytd_revenue", 87, "revenue", "Q2 YTD FY2022", 61432, category="quarter_vs_ytd"),
    lookup(PFIZER, "pfizer_quarter_revenue", 7, "revenue", "Q2 FY2023", 12734, category="quarter_vs_ytd"),
    lookup(PFIZER, "pfizer_ytd_revenue", 7, "revenue", "Q2 YTD FY2023", 31015, category="quarter_vs_ytd"),
    lookup(AES, "aes_assets", 129, "total assets", "FY2022", 38363),
    lookup(AES, "aes_sales", 131, "revenue", "FY2022", 12617),
    case(AES, "aes_two_statements", "multi_statement", "What were AES's FY2022 total assets and revenue?",
         fact(AES, 129, "total assets", "FY2022", 38363), fact(AES, 131, "revenue", "FY2022", 12617)),
    lookup(ACTIVISION, "activision_cash", 68, "cash and cash equivalents", "FY2019", 5794),
    lookup(ACTIVISION, "activision_income", 69, "operating income", "FY2019", 1607),
    case(ACTIVISION, "activision_two_statements", "multi_statement",
         "What were Activision Blizzard's FY2019 operating income and cash and cash equivalents in its 10-K?",
         fact(ACTIVISION, 69, "operating income", "FY2019", 1607),
         fact(ACTIVISION, 68, "cash and cash equivalents", "FY2019", 5794)),
    lookup(WATER, "water_assets", 80, "total assets", "FY2022", 27787),
    lookup(WATER, "water_income", 82, "operating income", "FY2022", 1273),
    lookup(BLOCK, "block_assets", 84, "total assets", "FY2020", 9869550, scale="thousand"),
    lookup(BLOCK, "block_operating_loss", 85, "operating income", "FY2020", -18815, scale="thousand"),
    case(BLOCK, "block_two_statements", "multi_statement", "What were Block's FY2020 total assets and operating income?",
         fact(BLOCK, 84, "total assets", "FY2020", 9869550, scale="thousand"),
         fact(BLOCK, 85, "operating income", "FY2020", -18815, scale="thousand")),
    lookup(KRAFT, "kraft_income", 49, "operating income", "FY2019", 3070),
    lookup(KRAFT, "kraft_assets", 51, "total assets", "FY2019", 101450),
    lookup(PAYPAL, "paypal_cash", 60, "cash and cash equivalents", "FY2022", 7776),
    lookup(PAYPAL, "paypal_sales", 61, "revenue", "FY2022", 27518),
    case(PAYPAL, "paypal_two_statements", "multi_statement",
         "What were PayPal's FY2022 revenue and cash and cash equivalents?",
         fact(PAYPAL, 61, "revenue", "FY2022", 27518), fact(PAYPAL, 60, "cash and cash equivalents", "FY2022", 7776)),
    case(WATER, "water_vs_aes", "multi_issuer", "Compare American Water Works and AES total assets in FY2022.",
         fact(WATER, 80, "total assets", "FY2022", 27787), fact(AES, 129, "total assets", "FY2022", 38363)),
    case(PAYPAL, "paypal_missing_restated", "revision_control", "What was PayPal's restated FY2022 revenue?"),
    case(KRAFT, "kraft_currency_mismatch", "currency_control", "What was Kraft Heinz's FY2019 operating income in EUR?"),
    case(AES, "aes_future", "unsupported_intent", "Forecast AES's total assets for FY2035."),
)

ISSUERS = {
    case.case_id: frozenset(claim.terms[0] for claim in case.claims) for case in CASES if case.claims
}
