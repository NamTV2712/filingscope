"""PDF-transcribed development questions for the SEC 2025 source-track replay."""

from dataclasses import dataclass

from src.agent.complexity_router import ExecutionPath

# Git stores LF while the original Windows replay wrote CRLF.
SEC_MANIFEST_SHA256 = frozenset({
    "sha256:94a662436a8773346af71b0513e8dfcdab83d2d2a71b7139b709c22ed122ab5e",
    "sha256:e83b3df4910e5572e81535a5c72e8a5c6011e83e4e11e56ba1bb0b6e61ea3e9f",
})
STATUS = "PROVISIONAL_NOT_INDEPENDENT"


@dataclass(frozen=True)
class FilingPDF:
    name: str
    company: str
    accession: str
    fiscal_year: int
    url: str
    sha256: str


APPLE = FilingPDF(
    "AAPL_2025_10K", "Apple", "0000320193-25-000079", 2025,
    "https://d18rn0p25nwr6d.cloudfront.net/CIK-0000320193/c24e7a28-5254-4dfa-9447-62aaa3c24bb1.pdf",
    "108590052c3ba5400c63660d787fe7ed4e43868292946d7a7facebe9ab7d1aab",
)
APPLE_Q3 = FilingPDF(
    "AAPL_2025Q3_10Q", "Apple", "0000320193-25-000073", 2025,
    "https://d18rn0p25nwr6d.cloudfront.net/CIK-0000320193/a411a029-368f-4479-b416-25c404acca3d.pdf",
    "51c39794365ed81a580913cc95f4a16c94a468703d3908a03ac6ca6c587ccd12",
)
NVIDIA = FilingPDF(
    "NVDA_2025_10K", "NVIDIA", "0001045810-25-000023", 2025,
    "https://s201.q4cdn.com/141608511/files/doc_financials/2025/annual/NVIDIA-2025-Annual-Report.pdf",
    "757b344ab62ba282f6e44e0702e8ce5f190d88fb23b5e0a2beaf4cb277a395cc",
)
TESLA = FilingPDF(
    "TSLA_2024_10K", "Tesla", "0001628280-25-003063", 2024,
    "https://ir.tesla.com/_flysystem/s3/sec/000162828025003063/tsla-20241231-gen.pdf",
    "2957d89daa2066035df5cf56f3586dd3c25a20a8e366fcf4da866e7e48c1a504",
)
WALMART = FilingPDF(
    "WMT_2025_10K", "Walmart", "0000104169-25-000021", 2025,
    "https://corporate.walmart.com/content/dam/corporate/documents/newsroom/2025/04/24/"
    "walmart-releases-2025-annual-report-and-proxy-statement/walmart-inc-2025-annual-report.pdf",
    "fa0c3438e4753271469b6d75b837e1a5dd8129d4bb7532fb0b3b4dd2dda20a48",
)
PDFS = (APPLE, APPLE_Q3, NVIDIA, TESLA, WALMART)


@dataclass(frozen=True)
class StatementCell:
    pdf: FilingPDF
    page: int
    row: str
    column: int
    metric: str
    period: str
    millions_usd: int
    sec_concept: str | None
    start: str | None
    end: str
    original_accession: str | None = None


@dataclass(frozen=True)
class PilotCase:
    case_id: str
    category: str
    question: str
    intended_path: ExecutionPath
    cells: tuple[StatementCell, ...]


AAPL_REVENUE = StatementCell(APPLE, 31, "Total net sales", 0, "revenue", "FY2025", 416_161,
                             "RevenueFromContractWithCustomerExcludingAssessedTax", "2024-09-29", "2025-09-27")
AAPL_PRIOR_REVENUE = StatementCell(APPLE, 31, "Total net sales", 1, "revenue", "FY2024", 391_035,
                                   "RevenueFromContractWithCustomerExcludingAssessedTax", "2023-10-01", "2024-09-28",
                                   "0000320193-24-000123")
AAPL_OPERATING = StatementCell(APPLE, 31, "Operating income", 0, "operating income", "FY2025", 133_050,
                               "OperatingIncomeLoss", "2024-09-29", "2025-09-27")
AAPL_NET = StatementCell(APPLE, 31, "Net income", 0, "net income", "FY2025", 112_010,
                         "NetIncomeLoss", "2024-09-29", "2025-09-27")
AAPL_ASSETS = StatementCell(APPLE, 33, "Total assets", 0, "total assets", "FY2025", 359_241,
                            "Assets", None, "2025-09-27")
AAPL_Q_REVENUE = StatementCell(APPLE_Q3, 3, "Total net sales", 0, "revenue", "Q3 FY2025", 94_036,
                                "RevenueFromContractWithCustomerExcludingAssessedTax", "2025-03-30", "2025-06-28")
AAPL_YTD_REVENUE = StatementCell(APPLE_Q3, 3, "Total net sales", 2, "revenue", "Q3 YTD FY2025", 313_695,
                                  "RevenueFromContractWithCustomerExcludingAssessedTax", "2024-09-29", "2025-06-28")
AAPL_Q_OPERATING = StatementCell(APPLE_Q3, 3, "Operating income", 0, "operating income", "Q3 FY2025", 28_202,
                                  "OperatingIncomeLoss", "2025-03-30", "2025-06-28")
AAPL_YTD_OPERATING = StatementCell(APPLE_Q3, 3, "Operating income", 2, "operating income", "Q3 YTD FY2025", 100_623,
                                    "OperatingIncomeLoss", "2024-09-29", "2025-06-28")
AAPL_Q_ASSETS = StatementCell(APPLE_Q3, 5, "Total assets", 0, "total assets", "Q3 FY2025", 331_495,
                               "Assets", None, "2025-06-28")
NVDA_REVENUE = StatementCell(NVIDIA, 143, "Revenue", 0, "revenue", "FY2025", 130_497,
                             "Revenues", "2024-01-29", "2025-01-26")
NVDA_PRIOR_REVENUE = StatementCell(NVIDIA, 143, "Revenue", 1, "revenue", "FY2024", 60_922,
                                   "Revenues", "2023-01-30", "2024-01-28", "0001045810-24-000029")
NVDA_OPERATING = StatementCell(NVIDIA, 143, "Operating income", 0, "operating income", "FY2025", 81_453,
                               "OperatingIncomeLoss", "2024-01-29", "2025-01-26")
NVDA_NET = StatementCell(NVIDIA, 143, "Net income", 0, "net income", "FY2025", 72_880,
                         "NetIncomeLoss", "2024-01-29", "2025-01-26")
NVDA_ASSETS = StatementCell(NVIDIA, 145, "Total assets", 0, "total assets", "FY2025", 111_601,
                            "Assets", None, "2025-01-26")
TSLA_REVENUE = StatementCell(TESLA, 51, "Total revenues", 0, "revenue", "FY2024", 97_690,
                             "RevenueFromContractWithCustomerExcludingAssessedTax", "2024-01-01", "2024-12-31")
TSLA_OPERATING = StatementCell(TESLA, 51, "Income from operations", 0, "operating income", "FY2024", 7_076,
                               "OperatingIncomeLoss", "2024-01-01", "2024-12-31")
TSLA_ASSETS = StatementCell(TESLA, 50, "Total assets", 0, "total assets", "FY2024", 122_070,
                            "Assets", None, "2024-12-31")
TSLA_ENERGY = StatementCell(TESLA, 39, "Energy generation and storage segment revenue", 0, "revenue", "FY2024", 10_086,
                            None, "2024-01-01", "2024-12-31")
WMT_REVENUE = StatementCell(WALMART, 54, "Total revenues", 0, "revenue", "FY2025", 680_985,
                            "Revenues", "2024-02-01", "2025-01-31")
WMT_OPERATING = StatementCell(WALMART, 54, "Operating income", 0, "operating income", "FY2025", 29_348,
                              "OperatingIncomeLoss", "2024-02-01", "2025-01-31")
WMT_ASSETS = StatementCell(WALMART, 56, "Total assets", 0, "total assets", "FY2025", 260_823,
                           "Assets", None, "2025-01-31")


def _lookup(case_id: str, category: str, question: str, cell: StatementCell) -> PilotCase:
    return PilotCase(case_id, category, question, ExecutionPath.FAST, (cell,))


CASES = (
    _lookup("apple_revenue", "lookup", "What was Apple's FY2025 revenue?", AAPL_REVENUE),
    _lookup("apple_operating", "lookup", "What was Apple's FY2025 operating income?", AAPL_OPERATING),
    _lookup("apple_net", "lookup", "What was Apple's FY2025 net income?", AAPL_NET),
    _lookup("apple_assets", "lookup", "What were Apple's total assets at FY2025 year end?", AAPL_ASSETS),
    _lookup("apple_quarter_revenue", "quarter_ytd", "What was Apple's discrete-quarter revenue in Q3 FY2025?",
            AAPL_Q_REVENUE),
    _lookup("apple_ytd_revenue", "quarter_ytd", "What was Apple's revenue for Q3 YTD FY2025?", AAPL_YTD_REVENUE),
    _lookup("apple_quarter_operating", "quarter_ytd", "What was Apple's operating income in Q3 FY2025?",
            AAPL_Q_OPERATING),
    _lookup("apple_ytd_operating", "quarter_ytd", "What was Apple's operating income for Q3 YTD FY2025?",
            AAPL_YTD_OPERATING),
    _lookup("apple_quarter_assets", "quarter_ytd", "What were Apple's total assets at the end of Q3 FY2025?",
            AAPL_Q_ASSETS),
    _lookup("nvidia_revenue", "lookup", "What was NVIDIA's FY2025 revenue?", NVDA_REVENUE),
    _lookup("nvidia_operating", "lookup", "What was NVIDIA's FY2025 operating income?", NVDA_OPERATING),
    _lookup("nvidia_net", "lookup", "What was NVIDIA's FY2025 net income?", NVDA_NET),
    _lookup("nvidia_assets", "lookup", "What were NVIDIA's total assets at FY2025 year end?", NVDA_ASSETS),
    _lookup("tesla_revenue", "lookup", "What was Tesla's FY2024 revenue?", TSLA_REVENUE),
    _lookup("tesla_operating", "lookup", "What was Tesla's FY2024 operating income?", TSLA_OPERATING),
    _lookup("tesla_assets", "lookup", "What were Tesla's total assets at FY2024 year end?", TSLA_ASSETS),
    _lookup("tesla_energy", "hard_negative", "What was Tesla's FY2024 energy generation and storage revenue?", TSLA_ENERGY),
    _lookup("walmart_revenue", "lookup", "What was Walmart's FY2025 revenue?", WMT_REVENUE),
    _lookup("walmart_operating", "lookup", "What was Walmart's FY2025 operating income?", WMT_OPERATING),
    _lookup("walmart_assets", "lookup", "What were Walmart's total assets at FY2025 year end?", WMT_ASSETS),
    PilotCase("apple_revenue_two_years", "multi_period", "What was Apple's revenue in FY2024 and FY2025?",
              ExecutionPath.RESEARCH, (AAPL_PRIOR_REVENUE, AAPL_REVENUE)),
    PilotCase("nvidia_revenue_two_years", "multi_period", "What was NVIDIA's revenue in FY2024 and FY2025?",
              ExecutionPath.RESEARCH, (NVDA_PRIOR_REVENUE, NVDA_REVENUE)),
    PilotCase("apple_nvidia_revenue", "multi_company", "What were Apple's and NVIDIA's respective FY2025 revenues?",
              ExecutionPath.RESEARCH, (AAPL_REVENUE, NVDA_REVENUE)),
    PilotCase("apple_eur_revenue", "hard_negative", "What revenue did Apple report in EUR in FY2025?",
              ExecutionPath.RESEARCH, ()),
    PilotCase("nvidia_future_revenue", "unanswerable", "What was NVIDIA's FY2035 revenue?",
              ExecutionPath.RESEARCH, ()),
    PilotCase("tesla_restated_revenue", "revision", "What was Tesla's restated FY2024 revenue as of December 31, 2025?",
              ExecutionPath.RESEARCH, ()),
)
