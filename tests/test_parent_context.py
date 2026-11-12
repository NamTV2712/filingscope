from decimal import Decimal

import pytest

from src.decision.statement_columns import extract_annual_statement_values
from src.retrieval.parent_context import PageParent, expand_contexts


def _chunk(chunk_id, page):
    return {"doc_name": "report", "page_number": page, "chunk_id": chunk_id, "token_count": 8,
            "text": chunk_id, "source_url": "https://example.org/annual.pdf"}


def test_expansion_preserves_page_and_child_provenance_under_token_budget():
    first, duplicate_page, later = _chunk("first", 1), _chunk("second", 1), _chunk("later", 2)
    parents = {("report", 1): PageParent("report", 1, "full table", ("first", "second", "header"), 20)}
    result = expand_contexts([first, duplicate_page, later], parents, mode="selective", token_budget=24)
    assert len(result) == 1 and result[0].expanded
    assert result[0].source_url == first["source_url"]
    assert result[0].chunk_ids == ("first", "second", "header")
    fallback = expand_contexts([first, duplicate_page], parents, mode="parents", token_budget=12)
    assert len(fallback) == 1 and not fallback[0].expanded
    assert fallback[0].chunk_ids == ("first",)


def test_expansion_rejects_parent_without_child_lineage():
    parent = PageParent("report", 1, "unrelated", ("other",), 12)
    with pytest.raises(ValueError, match="does not contain its ranked child"):
        expand_contexts([_chunk("child", 1)], {("report", 1): parent}, mode="parents")


def test_statement_parser_binds_exact_labels_to_ordered_years_and_units():
    statement = """Consolidated Statements of Income
    ($ in millions, except per share data)
    Fiscal Years Ended January 28, 2023 January 29, 2022 January 30, 2021
    Net sales $ 46,298 $ 51,761 $ 47,262
    Sales of products 10,000 20,000 30,000
    Operating income 1,795 (3,039) —
    """
    rows = extract_annual_statement_values(statement, form="10-K", filing_year="2023")
    assert [(item.metric_id, item.period, item.base_amount) for item in rows] == [
        ("revenue", "FY2023", Decimal(46298000000)), ("revenue", "FY2022", Decimal(51761000000)),
        ("revenue", "FY2021", Decimal(47262000000)), ("operating_income", "FY2023", Decimal(1795000000)),
        ("operating_income", "FY2022", Decimal(-3039000000)),
    ]
    assert all(item.currency == "USD" and "January 28" in item.header for item in rows)
    assert not extract_annual_statement_values(statement, form="10-Q", filing_year="2023")
    assert not extract_annual_statement_values(statement, form="10-K", filing_year="2024")
    assert not extract_annual_statement_values(statement.replace("in millions", "in CAD millions"), form="10-K", filing_year="2023")
