"""Source-checked Q7 comparisons and filing disclosures for architecture replay."""

from dataclasses import dataclass
from decimal import Decimal

from configs.multi_agent_ablation import AblationCase
from configs.retrieval_utility import Filing, fact
from src.agent.complexity_router import ExecutionPath


DEV, VALIDATION = "development", "validation"
AES = Filing("AES", "AES_2022_10K", DEV)
WATER = Filing("American Water Works", "AMERICANWATERWORKS_2022_10K", DEV)
ADOBE = Filing("Adobe", "ADOBE_2022_10K", DEV)
PAYPAL = Filing("PayPal", "PAYPAL_2022_10K", DEV)
COSTCO = Filing("Costco", "COSTCO_2021_10K", VALIDATION)
NIKE = Filing("Nike", "NIKE_2021_10K", VALIDATION)
ACTIVISION = Filing("Activision Blizzard", "ACTIVISIONBLIZZARD_2019_10K", VALIDATION)
KRAFT = Filing("Kraft Heinz", "KRAFTHEINZ_2019_10K", VALIDATION)
BLOCK = Filing("Block", "BLOCK_2020_10K", VALIDATION)
GENERAL = Filing("General Mills", "GENERALMILLS_2020_10K", VALIDATION)
BOEING = Filing("Boeing", "BOEING_2022_10K", VALIDATION)
MGM = Filing("MGM Resorts", "MGMRESORTS_2022_10K", VALIDATION)


def _case(name, split, category, question, *claims):
    return AblationCase(name, split, category, question, ExecutionPath.RESEARCH, claims)


CASES = (
    _case("aes_water_assets", DEV, "cross_company", "Compare AES and American Water Works total assets in FY2022.",
          fact(AES, 129, "total assets", "FY2022", 38363), fact(WATER, 80, "total assets", "FY2022", 27787)),
    _case("aes_water_two_statements", DEV, "cross_company_multi_statement",
          "Compare AES and American Water Works revenue and total assets for FY2022.",
          fact(AES, 131, "revenue", "FY2022", 12617), fact(AES, 129, "total assets", "FY2022", 38363),
          fact(WATER, 82, "revenue", "FY2022", 3792), fact(WATER, 80, "total assets", "FY2022", 27787)),
    _case("adobe_paypal_revenue", DEV, "cross_company", "Compare Adobe and PayPal FY2022 revenue.",
          fact(ADOBE, 53, "revenue", "FY2022", 17606), fact(PAYPAL, 61, "revenue", "FY2022", 27518)),
    _case("adobe_paypal_two_statements", DEV, "cross_company_multi_statement",
          "Compare Adobe and PayPal revenue and total assets for FY2022.",
          fact(ADOBE, 53, "revenue", "FY2022", 17606), fact(ADOBE, 52, "total assets", "FY2022", 27165),
          fact(PAYPAL, 61, "revenue", "FY2022", 27518), fact(PAYPAL, 60, "total assets", "FY2022", 78717)),
    _case("costco_nike_revenue", VALIDATION, "cross_company", "Compare Costco and Nike FY2021 revenue.",
          fact(COSTCO, 35, "revenue", "FY2021", 195929), fact(NIKE, 58, "revenue", "FY2021", 44538,
               alternatives=("sec:0000320187-21-000028",))),
    _case("costco_nike_two_statements", VALIDATION, "cross_company_multi_statement",
          "Compare Costco and Nike revenue and total assets for FY2021.",
          fact(COSTCO, 35, "revenue", "FY2021", 195929), fact(COSTCO, 37, "total assets", "FY2021", 59268),
          fact(NIKE, 58, "revenue", "FY2021", 44538, alternatives=("sec:0000320187-21-000028",)),
          fact(NIKE, 60, "total assets", "FY2021", 37740, alternatives=("sec:0000320187-21-000028",))),
    _case("activision_kraft_assets", VALIDATION, "cross_company",
          "Compare Activision Blizzard and Kraft Heinz total assets for FY2019.",
          fact(ACTIVISION, 68, "total assets", "FY2019", 19845), fact(KRAFT, 51, "total assets", "FY2019", 101450)),
    _case("activision_kraft_two_statements", VALIDATION, "cross_company_multi_statement",
          "Compare Activision Blizzard and Kraft Heinz total assets and operating income for FY2019.",
          fact(ACTIVISION, 68, "total assets", "FY2019", 19845), fact(ACTIVISION, 69, "operating income", "FY2019", 1607),
          fact(KRAFT, 51, "total assets", "FY2019", 101450), fact(KRAFT, 49, "operating income", "FY2019", 3070)),
    _case("block_general_mills_assets", VALIDATION, "cross_company",
          "Compare Block and General Mills total assets for FY2020.",
          fact(BLOCK, 84, "total assets", "FY2020", 9869550, scale="thousand"),
          fact(GENERAL, 49, "total assets", "FY2020", Decimal("30806.7"), alternatives=("sec:0001193125-20-186469",))),
    _case("block_general_mills_two_statements", VALIDATION, "cross_company_multi_statement",
          "Compare Block and General Mills total assets and revenue for FY2020.",
          fact(BLOCK, 84, "total assets", "FY2020", 9869550, scale="thousand"),
          fact(BLOCK, 85, "revenue", "FY2020", 9497578, scale="thousand"),
          fact(GENERAL, 49, "total assets", "FY2020", Decimal("30806.7"), alternatives=("sec:0001193125-20-186469",)),
          fact(GENERAL, 47, "revenue", "FY2020", Decimal("17626.6"), alternatives=("sec:0001193125-20-186469",))),
    _case("boeing_mgm_revenue", VALIDATION, "cross_company", "Compare Boeing and MGM Resorts FY2022 revenue.",
          fact(BOEING, 54, "revenue", "FY2022", 66608, alternatives=("sec:0000012927-23-000007",)),
          fact(MGM, 59, "revenue", "FY2022", 13127485, scale="thousand", alternatives=("sec:0000789570-23-000008",))),
    _case("boeing_mgm_two_periods", VALIDATION, "cross_company_multi_period",
          "Compare Boeing and MGM Resorts revenue in FY2021 and FY2022.",
          fact(BOEING, 54, "revenue", "FY2021", 62286, alternatives=("sec:0000012927-22-000010",)),
          fact(BOEING, 54, "revenue", "FY2022", 66608, alternatives=("sec:0000012927-23-000007",)),
          fact(MGM, 59, "revenue", "FY2021", 9680140, scale="thousand", alternatives=("sec:0000789570-22-000005",)),
          fact(MGM, 59, "revenue", "FY2022", 13127485, scale="thousand", alternatives=("sec:0000789570-23-000008",))),
)

ISSUERS = {case.case_id: {claim.terms[0] for claim in case.claims} for case in CASES}


@dataclass(frozen=True)
class NarrativeCase:
    case_id: str
    question: str
    statement: str
    sources: frozenset[str]


NARRATIVE_CASES = (
    NarrativeCase("general_mills_industry", "What industry did General Mills operate in according to its FY2019 10-K?",
                  "General Mills operates in the packaged foods industry", frozenset({"GENERALMILLS_2019_10K#p99"})),
    NarrativeCase("coca_cola_industry", "What industry did Coca-Cola operate in according to its FY2022 10-K?",
                  "Coca-Cola operates in the highly competitive commercial beverage industry",
                  frozenset({"COCACOLA_2022_10K#p14", "COCACOLA_2022_10K#p35"})),
)
