"""Provisional source-checked labels for the Q2 offline evaluation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StatementCells:
    split: str
    document: str
    page: int
    metric: str
    scale: str
    kind: str
    columns: tuple[tuple[int, str, str], ...]


def _cells(split, document, page, metric, kind, scale, *cells):
    return StatementCells(
        split, document, page, metric, scale, kind,
        tuple((index, period, amount) for index, (period, amount) in enumerate(cells)),
    )


D, V = "development", "validation"
AMOUNT, INSTANT = "duration", "instant"
M, T = "millions", "thousands"

STATEMENT_CELLS = (
    _cells(D, "3M_2023Q2_10Q", 2, "revenue", AMOUNT, M,
           ("Q2 FY2023", "8325"), ("Q2 FY2022", "8702"), ("Q2 YTD FY2023", "16356"), ("Q2 YTD FY2022", "17531")),
    _cells(D, "3M_2023Q2_10Q", 2, "operating_income", AMOUNT, M,
           ("Q2 FY2023", "-8958"), ("Q2 FY2022", "110"), ("Q2 YTD FY2023", "-7717"), ("Q2 YTD FY2022", "1751")),
    _cells(D, "3M_2023Q2_10Q", 4, "total_assets", INSTANT, M, ("Q2 FY2023", "48880")),
    _cells(D, "ADOBE_2022_10K", 52, "cash_and_equivalents", INSTANT, M, ("FY2022", "4236"), ("FY2021", "3844")),
    _cells(D, "ADOBE_2022_10K", 53, "revenue", AMOUNT, M,
           ("FY2022", "17606"), ("FY2021", "15785"), ("FY2020", "12868")),
    _cells(D, "COSTCO_2021_10K", 35, "revenue", AMOUNT, M,
           ("FY2021", "195929"), ("FY2020", "166761"), ("FY2019", "152703")),
    _cells(D, "COSTCO_2021_10K", 37, "total_assets", INSTANT, M, ("FY2021", "59268"), ("FY2020", "55556")),
    _cells(D, "JPMORGAN_2022Q2_10Q", 87, "revenue", AMOUNT, M,
           ("Q2 FY2022", "30715"), ("Q2 FY2021", "30479"), ("Q2 YTD FY2022", "61432"), ("Q2 YTD FY2021", "62745")),
    _cells(D, "Pfizer_2023Q2_10Q", 7, "revenue", AMOUNT, M,
           ("Q2 FY2023", "12734"), ("Q2 FY2022", "27742"), ("Q2 YTD FY2023", "31015"), ("Q2 YTD FY2022", "53402")),
    _cells(V, "AES_2022_10K", 129, "total_assets", INSTANT, M, ("FY2022", "38363"), ("FY2021", "32963")),
    _cells(V, "AES_2022_10K", 131, "revenue", AMOUNT, M, ("FY2022", "12617"), ("FY2021", "11141"), ("FY2020", "9660")),
    _cells(V, "ACTIVISIONBLIZZARD_2019_10K", 68, "cash_and_equivalents", INSTANT, M,
           ("FY2019", "5794"), ("FY2018", "4225")),
    _cells(V, "ACTIVISIONBLIZZARD_2019_10K", 69, "operating_income", AMOUNT, M,
           ("FY2019", "1607"), ("FY2018", "1988"), ("FY2017", "1309")),
    _cells(V, "AMERICANWATERWORKS_2022_10K", 80, "total_assets", INSTANT, M,
           ("FY2022", "27787"), ("FY2021", "26075")),
    _cells(V, "AMERICANWATERWORKS_2022_10K", 82, "operating_income", AMOUNT, M,
           ("FY2022", "1273"), ("FY2021", "1196"), ("FY2020", "1248")),
    _cells(V, "BLOCK_2020_10K", 84, "total_assets", INSTANT, T, ("FY2020", "9869550"), ("FY2019", "4551258")),
    _cells(V, "BLOCK_2020_10K", 85, "operating_income", AMOUNT, T,
           ("FY2020", "-18815"), ("FY2019", "26557"), ("FY2018", "-36614")),
    _cells(V, "KRAFTHEINZ_2019_10K", 49, "operating_income", AMOUNT, M,
           ("FY2019", "3070"), ("FY2018", "-10205"), ("FY2017", "6057")),
    _cells(V, "KRAFTHEINZ_2019_10K", 51, "total_assets", INSTANT, M,
           ("FY2019", "101450"), ("FY2018", "103461")),
    _cells(V, "PAYPAL_2022_10K", 60, "cash_and_equivalents", INSTANT, M,
           ("FY2022", "7776"), ("FY2021", "5197")),
    _cells(V, "PAYPAL_2022_10K", 61, "revenue", AMOUNT, M, ("FY2022", "27518"), ("FY2021", "25371"), ("FY2020", "21454")),
)

# Unsupported mappings. They test abstention, separately from recoverable cells.
AMBIGUOUS_PAGES = (
    ("ACTIVISIONBLIZZARD_2019_10K", 36, "revenue"),
    ("ULTABEAUTY_2023_10K", 54, "revenue"),
    ("AMERICANEXPRESS_2022_10K", 95, "revenue"),
)


@dataclass(frozen=True)
class CompanyFactCell:
    ticker: str
    metric: str
    period: str
    amount: str
    accession: str
    start: str | None
    end: str


COMPANY_FACT_CELLS = (
    CompanyFactCell("AAPL", "revenue", "Q2 FY2024", "90753000000", "0000320193-24-000069", "2023-12-31", "2024-03-30"),
    CompanyFactCell("AAPL", "revenue", "Q2 YTD FY2024", "210328000000", "0000320193-24-000069", "2023-10-01", "2024-03-30"),
    CompanyFactCell("AAPL", "revenue", "FY2024", "391035000000", "0000320193-24-000123", "2023-10-01", "2024-09-28"),
    CompanyFactCell("MSFT", "revenue", "FY2024", "245122000000", "0000950170-24-087843", "2023-07-01", "2024-06-30"),
    CompanyFactCell("BBY", "cash_and_equivalents", "Q2 FY2024", "1093000000", "0000764478-23-000041", None, "2023-07-29"),
    CompanyFactCell("BA", "total_assets", "FY2018", "117359000000", "0000012927-19-000010", None, "2018-12-31"),
    CompanyFactCell("NKE", "revenue", "FY2021", "44538000000", "0000320187-21-000028", "2020-06-01", "2021-05-31"),
    CompanyFactCell("GLW", "revenue", "FY2021", "14082000000", "0001437749-22-003247", "2021-01-01", "2021-12-31"),
    CompanyFactCell("MGM", "revenue", "FY2022", "13127485000", "0000789570-23-000008", "2022-01-01", "2022-12-31"),
)
