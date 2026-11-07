from src.evaluation.answer_metrics import (
    numeric_fact_signatures,
    score_numeric_answer,
    score_text_answer,
)


def test_numeric_answer_score_normalizes_financial_scales_and_ignores_citations() -> None:
    result = score_numeric_answer(
        "Revenue was $1,000 million in FY2024 [Source 1].",
        "Revenue was $1 billion in FY2024.",
    )

    assert result["scored"] is True
    assert result["exact_match"] is True
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0


def test_numeric_answer_score_penalizes_extra_and_incorrect_numeric_claims() -> None:
    result = score_numeric_answer("Revenue was $90 million, up 12%.", "$100 million")

    assert result["exact_match"] is False
    assert result["true_positive_count"] == 0
    assert result["predicted_numeric_count"] == 2
    assert result["gold_numeric_count"] == 1


def test_numeric_signature_excludes_bare_reporting_years() -> None:
    assert numeric_fact_signatures("For FY2023, revenue was $100 million [Source 1].") == (
        ("amount", "USD", "100000000", "base", "fy2023"),
    )


def test_numeric_exact_match_requires_the_same_period() -> None:
    result = score_numeric_answer(
        "Revenue was $100 million in FY2023.",
        "Revenue was $100 million in FY2022.",
    )

    assert result["exact_match"] is False
    assert result["true_positive_count"] == 0


def test_text_answer_metrics_ignore_punctuation_and_citation_markers() -> None:
    result = score_text_answer("Revenue grew 10% [Source 1].", "Revenue grew 10%!")

    assert result["exact_match"] is True
    assert result["f1"] == 1.0
