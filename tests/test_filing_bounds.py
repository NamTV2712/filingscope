"""Changing a disclosed comparator changes the supported financial claim."""

from decimal import Decimal

import pytest

from src.decision.filing_bounds import asserted_customer_bound, filing_customer_bounds


@pytest.mark.parametrize("relation,expected", [
    ("less than", "<"), ("no more than", "<="), ("more than", ">"),
    ("at least", ">="), ("approximately", "~"), ("exactly", "="),
])
def test_customer_relation_keeps_meaning(relation, expected):
    bound, = filing_customer_bounds(
        f"For the year ended December 31, 2024, the largest customer accounted for {relation} 12% of total revenue."
    )
    assert (bound.period, bound.relation, bound.value) == ("FY2024", expected, Decimal(12))
    assert asserted_customer_bound(bound.sentence("Example")) == ("FY2024", expected, Decimal(12), "total revenue")


def test_negated_threshold_and_adjacent_years_are_distinct():
    bounds = filing_customer_bounds(
        "Customers\n  For the year ended December 31, 2024, no customer accounted for more than 10% of Example's sales revenue. "
        "For the year ended December 31, 2023, the largest customer accounted for exactly 14% of total revenue."
    )
    assert [(b.period, b.relation, b.value) for b in bounds] == [
        ("FY2024", "<=", Decimal(10)), ("FY2023", "=", Decimal(14)),
    ]
    assert filing_customer_bounds("No customer accounted for more than 10% of sales revenue.") == ()
    assert filing_customer_bounds("For the year ended 2024, no customer accounted for less than 10% of sales.") == ()


def test_foreign_issuer_component_basis_and_single_customer_are_not_promoted_to_a_largest_share():
    lead = "For the year ended December 31, 2024, "
    assert filing_customer_bounds(lead + "the largest customer accounted for exactly 12% of Rival's sales revenue.", ("Example Corporation",)) == ()
    assert filing_customer_bounds(lead + "the largest customer accounted for exactly 12% of domestic sales revenue.") == ()
    assert filing_customer_bounds(lead + "a single customer accounted for less than 12% of total revenue.") == ()
    bound, = filing_customer_bounds(lead + "no customer accounted for more than 10% of Example's sales revenue.", ("Example Corporation",))
    assert bound.basis == "sales revenue"
    assert bound.scope == "no customer"
    assert "largest customer accounted for at most 10% of sales revenue" in bound.sentence("Example")


def test_bound_passes_graph_and_exact_or_wrong_period_claim_is_rejected():
    from src.agent.complexity_router import ComplexityRouter
    from src.agent.specialist_graph import SpecialistResearchGraph
    from src.research.corpus_map import CorpusMap
    from src.verification.atomic_claim_verifier import AtomicClaimVerifier

    row = {"chunk_id": "example-note", "company": "Example Corporation", "ticker": "EXAM",
           "doc_name": "EXAM_2024_10K", "document_id": "EXAM_2024_10K", "doc_type": "10-K",
           "reporting_periods": [2024], "page_number": 2,
           "source_url": "https://example.com/2024.pdf", "score": 1.0,
           "text": "For the year ended December 31, 2024, no customer accounted for more than 10% of Example's sales revenue."}

    class Retriever:
        def retrieve(self, query, top_k=10, **filters):
            return [row]

    question = "What was Example Corporation's customer sales concentration in FY2024?"
    router = ComplexityRouter(CorpusMap.from_chunks([row], index_generation_id="fixture"))
    graph = SpecialistResearchGraph(router=router, retriever=Retriever())
    result = graph.run(question)
    assert result.status == "VERIFIED", result
    assert "at most 10%" in result.answer and "[Source 1]" in result.answer
    verifier = AtomicClaimVerifier(catalog=router.extractor.catalog)
    for text in (result.answer.replace("at most", "exactly"), result.answer.replace("FY2024", "FY2023")):
        assert verifier.verify(question, text, [row]).disposition == "REJECTED"
    for text in (result.answer.replace("[Source 1]", ""), result.answer.replace("[Source 1]", "[Source 2]")):
        assert verifier.verify(question, text, [row]).disposition not in {"VERIFIED", "PARTIAL"}
    assert verifier.verify(question, result.answer.replace("sales revenue", "total revenue"), [row]).disposition == "REJECTED"
    assert verifier.verify(question, result.answer.replace("Example Corporation", "Other Corporation"), [row]).disposition == "REJECTED"
    assert verifier.verify(question, result.answer.replace(" at most", " less than"), [row]).disposition == "REJECTED"
    wrong_source = {**row, "company": "Other Corporation", "ticker": "OTHER", "doc_name": "OTHER_2024_10K", "document_id": "OTHER_2024_10K"}
    assert verifier.verify(question, result.answer, [wrong_source]).disposition == "REJECTED"
