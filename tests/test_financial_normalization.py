from datetime import date
from decimal import Decimal

from src.decision.period_value_parser import extract_period_value_mentions, period_matches
from src.decision.requirement_extractor import EvidenceRequirementExtractor
from src.decision.statement_columns import parse_statement_columns
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
