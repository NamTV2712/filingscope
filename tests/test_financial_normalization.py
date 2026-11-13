from datetime import date
from decimal import Decimal

from src.decision.period_value_parser import extract_period_value_mentions, period_matches
from src.decision.requirement_extractor import EvidenceRequirementExtractor
from src.decision.statement_columns import parse_statement_columns, statement_report_date
from src.ingestion.period_identity import PeriodIdentity, PeriodKind, PeriodScope, YearBasis


def test_calendar_quarter_and_year_to_date_remain_distinct():
    fiscal = PeriodIdentity.from_label("Q2 FY2024", kind=PeriodKind.DURATION, end=date(2024, 3, 30))
    cumulative = PeriodIdentity.from_label("Q2 YTD FY2024", kind=PeriodKind.DURATION, end=date(2024, 3, 30))
    calendar = PeriodIdentity.from_label("CY2024", kind=PeriodKind.DURATION)
    assert fiscal.scope == PeriodScope.QUARTER
    assert cumulative.scope == PeriodScope.YEAR_TO_DATE
    assert calendar.year_basis == YearBasis.CALENDAR
    assert not period_matches(fiscal.label, cumulative.label)
    assert not period_matches("FY2024", calendar.label)
    extractor = EvidenceRequirementExtractor()
    assert extractor.extract("Apple's year-to-date revenue in Q2 FY2024?").periods == (cumulative.label,)
    assert not extractor.extract("Apple's six months ended in Q3 FY2024 revenue?").supported
    assert extractor.extract("Apple's calendar year 2024 revenue?").periods == (calendar.label,)


def test_claim_period_stays_quarterly_and_ungrouped_numbers_are_not_truncated():
    mentions = extract_period_value_mentions("Apple reported USD 90753000000 for Q2 FY2024.")
    assert len(mentions) == 1
    assert mentions[0].pair.period == "Q2 FY2024"
    assert Decimal(mentions[0].pair.numeric_value) == Decimal(90_753_000_000)
    value, = extract_period_value_mentions("Apple reported USD 2024 for FY2025.")
    assert (value.pair.numeric_value, value.pair.period) == ("2024", "FY2025")


def test_company_identifier_is_not_parsed_as_part_of_a_financial_claim():
    value, = extract_period_value_mentions("3M reported revenue of USD 8,325 million for Q2 FY2023.")
    assert (Decimal(value.pair.numeric_value), value.pair.scale, value.pair.period) == (Decimal(8325), "million", "Q2 FY2023")
    assert not extract_period_value_mentions("3M and product SKU 3P12")
    amount, = extract_period_value_mentions("The contract totaled USD 3M.")
    assert (amount.pair.numeric_value, amount.pair.currency, amount.pair.scale) == ("3", "USD", "million")


def test_multirow_quarter_columns_keep_ytd_negatives_missing_cells_and_footnotes():
    text = """Condensed Consolidated Statements of Income
    Three Months Ended September 30, Nine Months Ended September 30,
    (USD in thousands, except per share data) 2024 2023 2024 2023 Change
    Net sales $ 105 — $ 305 $ 291 4.8%
    Operating income (15) (20) -31 45(a) 20%
    """
    result = parse_statement_columns(text, form="10-Q", fiscal_year=2024, quarter=3)
    values = {(item.metric_id, item.period): item for item in result.values}
    assert not result.ambiguous_rows
    assert ("revenue", "Q3 FY2023") not in values
    assert values["revenue", "Q3 YTD FY2024"].column_index == 2
    assert values["revenue", "Q3 YTD FY2024"].base_amount == Decimal(305_000)
    assert values["operating_income", "Q3 FY2024"].base_amount == Decimal(-15_000)
    assert values["operating_income", "Q3 YTD FY2024"].base_amount == Decimal(-31_000)
    assert values["operating_income", "Q3 YTD FY2023"].raw_cell == "45(a)"


def test_row_with_a_collapsed_blank_remains_ambiguous():
    text = """Consolidated Statements of Income
    Years Ended December 31
    (USD in millions) 2024 2023 2022
    Revenue $ 109              $ 70
    """
    result = parse_statement_columns(text, form="10-K", fiscal_year=2024)
    assert result.recognized and not result.values
    assert result.ambiguous_rows[0].reason == "row_or_column_ownership_ambiguous"


def test_january_period_end_needs_a_fiscal_anchor():
    text = """Consolidated Statements of Income
    Fiscal Years Ended
    January 28, January 29,
    (USD in millions) 2023 2022
    Revenue $ 100 $ 90
    """
    ambiguous = parse_statement_columns(text, form="10-K", fiscal_year=2022)
    aligned = parse_statement_columns(
        text, form="10-K", fiscal_year=2022, confirmed_period_end=date(2023, 1, 28),
    )
    assert ambiguous.recognized and not ambiguous.values
    assert [(item.period, item.period_identity.end) for item in aligned.values] == [
        ("FY2022", date(2023, 1, 28)), ("FY2021", date(2022, 1, 29)),
    ]


def test_restated_header_and_percent_cells_preserve_their_own_units():
    text = """Consolidated Statements of Income
    Years Ended December 31
    (USD in millions, restated) 2024 2023
    Operating margin 16% 15%
    Net sales $ 900 $ 800
    """
    result = parse_statement_columns(text, form="10-K", fiscal_year=2024)
    assert len(result.values) == 4 and all(item.restated for item in result.values)
    margin = next(item for item in result.values if item.metric_id == "operating_margin")
    revenue = next(item for item in result.values if item.metric_id == "revenue")
    assert (margin.currency, margin.scale, margin.base_amount) == ("%", "units", Decimal(16))
    assert (revenue.currency, revenue.scale, revenue.base_amount) == ("USD", "millions", Decimal(900_000_000))


def test_incompatible_currency_marks_withhold_table_observations():
    text = """Consolidated Statements of Income
    Years Ended December 31
    (EUR in millions) 2024 2023
    Net sales $ 900 $ 800
    """
    result = parse_statement_columns(text, form="10-K", fiscal_year=2024)
    assert result.recognized and not result.values
    assert result.ambiguous_rows[0].reason == "period_or_unit_unresolved"


def test_january_statement_preserves_total_revenue_and_requires_matching_anchor():
    text = """Walmart Inc.
    Consolidated Statements of Income
    Fiscal Years Ended January 31,
    (Amounts in millions, except per share data) 2025 2024
    Revenues:
    Net sales $ 674,538 $ 642,637
    Membership and other income 6,447 5,488
    Total revenues 680,985 648,125
    Costs and expenses:
    Operating income 29,348 27,012
    """
    report_end = statement_report_date({"accession": "0000104169-25-000021", "report_date": "2025-01-31"})
    assert report_end == date(2025, 1, 31)
    assert statement_report_date({"report_date": "2025-01-31"}) is None
    assert statement_report_date({"accession": "0000104169-25-000021", "report_date": "2025-02-30"}) is None
    valid = parse_statement_columns(text, form="10-K", fiscal_year=2025, confirmed_period_end=report_end)
    assert [(item.period, item.amount) for item in valid.values if item.metric_id == "revenue"] == [
        ("FY2025", Decimal(680_985)), ("FY2024", Decimal(648_125)),
    ]
    for anchor in (None, date(2025, 1, 30)):
        invalid = parse_statement_columns(text, form="10-K", fiscal_year=2025, confirmed_period_end=anchor)
        assert invalid.recognized and not invalid.values


def test_abbreviated_months_preserve_exact_annual_dates():
    text = """NVIDIA Corporation and Subsidiaries
    Consolidated Statements of Income
    (In millions, except per share data)
    Year Ended
    Jan 26, 2025 Jan. 28, 2024 Jan 29, 2023
    Revenue $ 130,497 $ 60,922 $ 26,974
    """
    args = {"form": "10-K", "fiscal_year": 2025, "confirmed_period_end": date(2025, 1, 26)}
    result = parse_statement_columns(text, **args)
    assert [(value.amount, value.period_identity.end) for value in result.values] == [
        (Decimal(130_497), date(2025, 1, 26)),
        (Decimal(60_922), date(2024, 1, 28)),
        (Decimal(26_974), date(2023, 1, 29)),
    ]
    assert not parse_statement_columns(text.replace("Jan 26", "NotJan 26"), **args).values


def test_separate_share_count_scale_keeps_dollars_and_quarter_columns():
    text = """Condensed Consolidated Statements of Operations (Unaudited)
    (In millions, except number of shares, which are reflected in thousands, and per-share amounts)
    Three Months Ended Nine Months Ended
    June 28, June 29, June 28, June 29,
    2025 2024 2025 2024
    Total net sales $ 94,036 $ 85,777 $ 313,695 $ 296,105
    """
    args = {"form": "10-Q", "fiscal_year": 2025, "quarter": 3, "confirmed_period_end": date(2025, 6, 28)}
    result = parse_statement_columns(text, **args)
    values = {value.period: value.base_amount for value in result.values}
    assert values == {"Q3 FY2025": Decimal(94_036_000_000), "Q3 FY2024": Decimal(85_777_000_000),
                      "Q3 YTD FY2025": Decimal(313_695_000_000), "Q3 YTD FY2024": Decimal(296_105_000_000)}
    assert not parse_statement_columns(text.replace("number of shares", "other financial data"), **args).values
    assert not parse_statement_columns(text, **{**args, "confirmed_period_end": date(2025, 6, 29)}).values
