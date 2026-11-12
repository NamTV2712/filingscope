"""Provisional Q4 judgments from fixed, unchanged filing pages and chunks."""

from dataclasses import dataclass

from configs.multi_agent_ablation import AblationCase, GoldClaim
from src.agent.complexity_router import ExecutionPath


@dataclass(frozen=True)
class PageJudgment:
    document: str
    page: int
    chunk: int
    supports_slot: bool
    rationale: str

    @property
    def locator(self) -> str:
        return f"{self.document}#p{self.page}"


@dataclass(frozen=True)
class PolicyCase:
    gold: AblationCase
    issuer: str
    pages: tuple[PageJudgment, ...]
    claims: tuple[tuple[int, str, bool], ...]
    retrieve: bool = True
    retrieve_more: bool = False


def _lookup(case_id, split, issuer, metric, year, value, good, distractor, other_value):
    question = f"What was {issuer}'s FY{year} {metric}?"
    return PolicyCase(
        AblationCase(case_id, split, "contested_lookup", question, ExecutionPath.RESEARCH, (
            GoldClaim(value, (issuer, metric), ((good.locator,),), (f"FY{year}",)),
        )),
        issuer, (good, distractor), (
            (0, f"{issuer}'s FY{year} {metric} was {value}.", True),
            (1, f"{issuer}'s FY{year} {metric} was {other_value}.", False),
        ),
    )


def _withhold(case_id, issuer, category, question, page, draft):
    path = ExecutionPath.RESEARCH if page else ExecutionPath.UNSUPPORTED
    return PolicyCase(
        AblationCase(case_id, "validation", category, question, path, ()),
        issuer, (page,) if page else (), ((0, draft, False),) if draft else (),
        retrieve=page is not None, retrieve_more=page is not None,
    )


PAYPAL = "PAYPAL_2022_10K"
WATER = "AMERICANWATERWORKS_2022_10K"
AES = "AES_2022_10K"
ACTIVISION = "ACTIVISIONBLIZZARD_2019_10K"

CASES = (
    _lookup("amcor_guarantors", "development", "Amcor", "revenue", 2023, "USD 14,694 million",
            PageJudgment("AMCOR_2023_10K", 49, 0, True, "Consolidated net sales"),
            PageJudgment("AMCOR_2023_10K", 104, 0, False, "Deed of Cross Guarantee subgroup"), "USD 377 million"),
    _lookup("costco_membership", "development", "Costco", "revenue", 2021, "USD 195,929 million",
            PageJudgment("COSTCO_2021_10K", 35, 0, True, "Total revenue including membership fees"),
            PageJudgment("COSTCO_2021_10K", 23, 0, False, "Membership fee component only"), "USD 3,877 million"),
    _lookup("adobe_market_value", "development", "Adobe", "revenue", 2022, "USD 17,606 million",
            PageJudgment("ADOBE_2022_10K", 53, 0, True, "Consolidated revenue"),
            PageJudgment("ADOBE_2022_10K", 0, 2, False, "Market value of stock held by non-affiliates"), "USD 159 billion"),
    _lookup("paypal_change", "validation", "PayPal", "revenue", 2022, "USD 27,518 million",
            PageJudgment(PAYPAL, 61, 0, True, "Consolidated net revenues"),
            PageJudgment(PAYPAL, 34, 0, False, "Year-over-year increase in net revenues"), "USD 2.1 billion"),
    _lookup("aes_equity_investments", "validation", "AES", "total assets", 2022, "USD 38,363 million",
            PageJudgment(AES, 129, 0, True, "Consolidated total assets"),
            PageJudgment(AES, 152, 1, False, "Summary financial information for equity method investments"), "USD 1,269 million"),
    _lookup("water_quarterly", "validation", "American Water Works", "operating income", 2022, "USD 1,273 million",
            PageJudgment(WATER, 82, 0, True, "Consolidated annual operating income"),
            PageJudgment(WATER, 133, 0, False, "Unaudited quarterly results"), "USD 246 million"),
    _lookup("activision_liquidity", "validation", "Activision Blizzard", "cash and cash equivalents", 2019, "USD 5,794 million",
            PageJudgment(ACTIVISION, 68, 0, True, "Consolidated year-end cash and cash equivalents"),
            PageJudgment(ACTIVISION, 48, 1, False, "Credit facility availability and investments"), "USD 1.5 billion"),
    _withhold("water_issuer_mismatch", "American Water Works", "company_mismatch",
              "What was American Water Works' FY2022 total assets?",
              PageJudgment(AES, 129, 0, False, "Financial statement belongs to AES"),
              "American Water Works' FY2022 total assets were USD 38,363 million."),
    _withhold("paypal_quarter_mismatch", "PayPal", "period_mismatch",
              "What was PayPal's Q2 FY2022 revenue?",
              PageJudgment(PAYPAL, 61, 0, False, "Annual duration does not establish the second quarter"),
              "PayPal's Q2 FY2022 revenue was USD 27,518 million."),
    _withhold("aes_unit_mismatch", "AES", "unit_mismatch",
              "What was AES's FY2022 total assets in EUR?",
              PageJudgment(AES, 129, 0, False, "USD consolidated statement; no conversion evidence"),
              "AES's FY2022 total assets were EUR 38,363 million."),
    _withhold("paypal_revision_unavailable", "PayPal", "revision_mismatch",
              "What was PayPal's restated FY2022 revenue?",
              PageJudgment(PAYPAL, 61, 0, False, "Original 10-K does not establish a restated value"),
              "PayPal's restated FY2022 revenue was USD 27,518 million."),
    PolicyCase(
        AblationCase("water_missing_operand", "validation", "calculation_gap",
                     "Calculate American Water Works' total assets growth from FY2019 to FY2022.",
                     ExecutionPath.FAST, ()),
        "American Water Works",
        (PageJudgment(WATER, 80, 0, True, "Total assets only; no income statement"),),
        (), retrieve_more=True,
    ),
    _withhold("activision_forecast", "Activision Blizzard", "unsupported_intent",
              "Forecast Activision Blizzard's FY2035 cash and cash equivalents.", None, None),
)
