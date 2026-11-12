import math
from dataclasses import replace

import pytest

from src.retrieval.provenance_graph import FilingPassageGraph


def _passage(company, document, year, text):
    return {"company": company, "doc_name": document, "document_id": document, "doc_type": "10k",
            "page_number": 0, "reporting_periods": [year], "text": text}


def test_graph_variants_are_deterministic_and_use_only_candidates_from_the_pool():
    passages = [
        _passage("Microsoft", "MSFT_2024", "2024", "Consolidated Statements of Income\nRevenue 100"),
        _passage("Apple", "AAPL_2024", "2024", "Consolidated Statements of Income\nRevenue 100"),
        _passage("Apple", "AAPL_2023", "2023", "Consolidated Statements of Income\nRevenue 100"),
        _passage("Apple", "AAPL_extra", "2024", "Consolidated Statements of Income\nRevenue 100"),
    ]
    graph = FilingPassageGraph(passages)
    query = graph.cues("What was Apple's revenue in its FY2024 10-K income statement?")
    pool = [0, 1, 2]
    assert query.companies == {"AAPL"} and query.years == {"2024"}
    scoped = graph.local_search(query, pool)
    unscoped = graph.local_search(replace(query, companies=frozenset()), pool)
    assert scoped[1] > unscoped[1]
    assert scoped[0] == pytest.approx(unscoped[0])
    for algorithm in (graph.local_search, graph.personalized_pagerank, graph.dual_level):
        scores = algorithm(query, pool)
        assert scores == algorithm(query, pool)
        assert set(scores) == set(pool)
        assert all(math.isfinite(score) for score in scores.values())


def test_calendar_date_does_not_create_a_fiscal_year_cue():
    graph = FilingPassageGraph([_passage("Apple", "AAPL_2024", "2024", "Revenue 100")])
    assert not graph.cues("What was Apple's cash at July 29, 2023?").years
