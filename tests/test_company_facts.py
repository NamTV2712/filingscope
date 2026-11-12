"""Offline Company Facts selection against filing values and adversarial rows."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.ingestion.company_facts import CompanyFactsResolver, RevisionKind, RevisionPolicy


REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"


def row(
    value, *, start="2023-10-01", end="2024-09-28", accession="0000320193-24-000123",
    filed="2024-11-01", form="10-K", fy=2024, fp="FY",
):
    result = {"val": value, "end": end, "accn": accession, "filed": filed, "form": form, "fy": fy, "fp": fp}
    if start is not None:
        result["start"] = start
    return result


def node(rows, unit="USD"):
    return {"units": {unit: rows}}


def payload(facts, *, cik=320193, name="Apple Inc."):
    return {"cik": cik, "entityName": name, "facts": facts}


@pytest.fixture
def apple():
    # Amounts in original filing base units. Comparative rows carry the later
    # filing's FY/FP, as they do in Company Facts.
    fy_2023 = row(
        383_285_000_000, start="2022-09-25", end="2023-09-30",
        accession="0000320193-23-000106", filed="2023-11-03", fy=2023,
    )
    q2_2023 = row(
        94_836_000_000, start="2023-01-01", end="2023-04-01",
        accession="0000320193-23-000064", filed="2023-05-05", form="10-Q", fy=2023, fp="Q2",
    )
    q2_filing = {
        "end": "2024-03-30", "accession": "0000320193-24-000069",
        "filed": "2024-05-03", "form": "10-Q", "fp": "Q2",
    }
    return payload({"us-gaap": {
        REVENUE: node([
            fy_2023,
            {**fy_2023, "accn": "0000320193-24-000123", "filed": "2024-11-01", "fy": 2024},
            row(391_035_000_000),
            q2_2023,
            {**q2_2023, "accn": q2_filing["accession"], "filed": q2_filing["filed"], "fy": 2024},
            row(210_328_000_000, **q2_filing),
            row(90_753_000_000, start="2023-12-31", **q2_filing),
        ]),
        "Assets": node([
            row(352_583_000_000, start=None, end="2023-09-30"),
            row(364_980_000_000, start=None),
        ]),
        "Liabilities": node([row(308_030_000_000, start=None)]),
    }})


@pytest.mark.parametrize(("metric", "period", "value", "end", "accession"), [
    ("revenue", "FY2023", 383_285_000_000, "2023-09-30", "0000320193-23-000106"),
    ("revenue", "FY2024", 391_035_000_000, "2024-09-28", "0000320193-24-000123"),
    ("revenue", "Q2 FY2023", 94_836_000_000, "2023-04-01", "0000320193-23-000064"),
    ("revenue", "Q2 FY2024", 90_753_000_000, "2024-03-30", "0000320193-24-000069"),
    ("revenue", "Q2 YTD FY2024", 210_328_000_000, "2024-03-30", "0000320193-24-000069"),
    ("total_assets", "FY2024", 364_980_000_000, "2024-09-28", "0000320193-24-000123"),
    ("total_liabilities", "FY2024", 308_030_000_000, "2024-09-28", "0000320193-24-000123"),
])
def test_apple_filing_values(apple, metric, period, value, end, accession):
    result = CompanyFactsResolver(apple, expected_cik="0000320193").resolve(metric, period)
    fact = result.fact
    assert fact is not None
    assert (fact.value, fact.fiscal_period, fact.currency) == (Decimal(value), period, "USD")
    assert (fact.provenance.period_end, fact.provenance.accession) == (end, accession)
    assert fact.filing_url.endswith(f"/{accession.replace('-', '')}/{accession}-index.html")
    assert (fact.provenance.period_start is None) == (metric != "revenue")
    assert fact.period_identity.label == period


@pytest.mark.parametrize(("metric", "value"), [
    ("revenue", 245_122_000_000),
    ("total_assets", 512_163_000_000),
])
def test_microsoft_filing_values_with_filing_agent_accession(metric, value):
    metadata = {"end": "2024-06-30", "accession": "0000950170-24-087843", "filed": "2024-07-30"}
    microsoft = payload({"us-gaap": {
        REVENUE: node([row(245_122_000_000, start="2023-07-01", **metadata)]),
        "Assets": node([row(512_163_000_000, start=None, **metadata)]),
    }}, cik=789019, name="MICROSOFT CORP")
    resolver = CompanyFactsResolver(microsoft, expected_cik=789019)
    fact = resolver.resolve(metric, "FY2024").fact
    assert fact is not None and fact.value == Decimal(value)
    assert fact.provenance.accession == metadata["accession"]


@pytest.mark.parametrize(("observation", "metric", "period"), [
    (row(100, start="2022-09-25", end="2023-09-30"), "revenue", "FY2024"),
    (row(100, start=None), "revenue", "FY2024"),
    (row(100), "total_assets", "FY2024"),
    (row(100, start="2024-01-01", end="2024-06-30", filed="2024-07-30", form="10-Q", fp="Q2"),
     "revenue", "Q2 FY2024"),
    (row(100, fp="Q4"), "revenue", "Q4 FY2024"),
    (row(100, accession="unknown"), "revenue", "FY2024"),
    (row(100, form="10-K/A"), "revenue", "FY2024"),
    (row(100, form="8-K"), "revenue", "FY2024"),
])
def test_ineligible_rows_leave_the_slot_unknown(observation, metric, period):
    tag = "Assets" if metric == "total_assets" else REVENUE
    resolver = CompanyFactsResolver(payload({"us-gaap": {tag: node([observation])}}), expected_cik=320193)
    assert resolver.resolve(metric, period).reason == "original_period_unavailable"


def test_cik_mismatch_rejects_the_whole_payload(apple):
    with pytest.raises(ValueError, match="CIK mismatch"):
        CompanyFactsResolver(apple, expected_cik=789019)


def test_equal_values_with_two_original_accessions_are_still_ambiguous():
    facts = payload({"us-gaap": {REVENUE: node([
        row(391_035_000_000),
        row(391_035_000_000, accession="0000320193-24-000124"),
    ])}})
    result = CompanyFactsResolver(facts, expected_cik=320193).resolve("revenue", "FY2024")
    assert result.fact is None
    assert result.reason == "ambiguous_original_accession"


def test_explicit_report_date_rejects_nearby_wrong_instant():
    wrong = row(10, start=None, end="2024-06-29", filed="2024-07-26", fp="Q3", form="10-Q")
    resolver = CompanyFactsResolver(
        payload({"us-gaap": {"Assets": node([wrong])}}), expected_cik=320193,
        report_dates={wrong["accn"]: "2024-06-30"},
    )
    assert resolver.resolve("total_assets", "Q3 FY2024").fact is None


def test_q1_can_end_in_previous_calendar_year():
    q1 = row(119_575_000_000, end="2023-12-30", filed="2024-02-02", form="10-Q", fp="Q1")
    fact = CompanyFactsResolver(
        payload({"us-gaap": {REVENUE: node([q1])}}), expected_cik=320193,
    ).resolve("revenue", "Q1 FY2024").fact
    assert fact is not None and fact.provenance.period_end == "2023-12-30"


def test_currencies_are_normalized_and_incompatible_units_stay_unknown():
    resolver = CompanyFactsResolver(payload({"us-gaap": {
        REVENUE: {"units": {"iso4217:cad": [row("101.125")], "USD": [row(80)], "USD-per-shares": [row(2)]}},
    }}), expected_cik=320193)
    assert resolver.resolve("revenue", "FY2024").reason == "ambiguous_currency"
    fact = resolver.resolve("revenue", "FY2024", currency="CAD").fact
    assert fact is not None
    assert (fact.currency, fact.value, fact.provenance.raw_unit) == ("CAD", Decimal("101.125"), "iso4217:cad")
    assert resolver.resolve("revenue", "FY2024", currency="EUR").fact is None


def test_tag_drift_requires_a_reviewed_taxonomy_and_unambiguous_original():
    older = row(83, start="2022-09-25", end="2023-09-30", filed="2023-11-03", fy=2023)
    resolver = CompanyFactsResolver(payload({
        "us-gaap": {"SalesRevenueNet": node([older]), REVENUE: node([row(95)])},
        "aapl": {REVENUE: node([row(999)])},
    }), expected_cik=320193)
    historical = resolver.resolve("revenue", "FY2023").fact
    current = resolver.resolve("revenue", "FY2024").fact
    assert historical is not None and historical.provenance.tag == "SalesRevenueNet"
    assert current is not None and current.value == Decimal(95)
    only_extension = CompanyFactsResolver(
        payload({"aapl": {REVENUE: node([row(999)])}}), expected_cik=320193,
    )
    assert only_extension.resolve("revenue", "FY2024").fact is None
    conflicting = CompanyFactsResolver(payload({"us-gaap": {
        "SalesRevenueNet": node([row(83)]), REVENUE: node([row(95)]),
    }}), expected_cik=320193)
    assert conflicting.resolve("revenue", "FY2024").reason == "conflicting_original_values"


def test_ifrs_taxonomy_and_january_year_end_keep_original_fiscal_label():
    observation = row(80, start="2024-02-04", end="2025-02-01", filed="2025-03-20", form="20-F")
    resolver = CompanyFactsResolver(
        payload({"ifrs-full": {"Revenue": node([observation], "EUR")}}), expected_cik=320193,
    )
    fact = resolver.resolve("revenue", "FY2024").fact
    assert fact is not None and fact.fiscal_period == "FY2024"
    assert fact.provenance.taxonomy == "ifrs-full"
    assert resolver.resolve("revenue", "FY2025").fact is None


@pytest.mark.parametrize(("revised_form", "revised_focus", "revised_kind"), [
    ("10-K/A", 2024, RevisionKind.AMENDMENT),
    ("10-K", 2025, RevisionKind.COMPARATIVE_REVISION),
])
def test_as_reported_and_latest_revision_stay_separate(revised_form, revised_focus, revised_kind):
    original = row(100)
    revised = row(
        94, accession="0000320193-25-000111", filed="2025-10-31",
        form=revised_form, fy=revised_focus,
    )
    resolver = CompanyFactsResolver(
        payload({"us-gaap": {REVENUE: node([revised, original])}}), expected_cik=320193,
    )
    reported = resolver.resolve("revenue", "FY2024").fact
    latest = resolver.resolve("revenue", "FY2024", revision=RevisionPolicy.LATEST).fact
    assert reported is not None and latest is not None
    assert (reported.value, reported.provenance.revision_kind) == (Decimal(100), RevisionKind.ORIGINAL)
    assert (latest.value, latest.provenance.revision_kind) == (Decimal(94), revised_kind)
    assert latest.provenance.original_accession == original["accn"]
    assert [item.accession for item in latest.provenance.history] == [original["accn"], revised["accn"]]


def test_latest_disagrees_on_same_filing_day():
    resolver = CompanyFactsResolver(payload({"us-gaap": {REVENUE: node([
        row(100),
        row(90, accession="0000320193-25-000110", filed="2025-10-31", fy=2025),
        row(95, accession="0000320193-25-000111", filed="2025-10-31", fy=2025),
    ])}}), expected_cik=320193)
    assert resolver.resolve("revenue", "FY2024", revision=RevisionPolicy.LATEST).reason == "conflicting_latest_values"
    assert resolver.resolve("revenue", None).reason == "explicit_fiscal_period_required"
