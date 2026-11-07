from src.evaluation.financebench_dataset import FinanceBenchCase
from src.evaluation.retrieval_metrics import evaluate_retrieval


def _case() -> FinanceBenchCase:
    return FinanceBenchCase(
        case_id="case-1",
        company="Synthetic Co",
        doc_name="SYNTHETIC_2024_10K",
        question="What was revenue?",
        gold_pages=(0, 2),
        question_type="synthetic",
        split="development",
    )


def test_metrics_count_unique_document_pages_not_duplicate_chunks() -> None:
    result = evaluate_retrieval(
        [_case()],
        {
            "case-1": [
                {"doc_name": "SYNTHETIC_2024_10K", "page_number": 0},
                {"doc_name": "SYNTHETIC_2024_10K", "page_number": 0},
                {"doc_name": "SYNTHETIC_2024_10K", "page_number": 2},
            ]
        },
        {"case-1": 25.0},
    )

    metrics = result["overall"]
    assert metrics["Recall@5"] == 1.0
    assert metrics["Recall@10"] == 1.0
    assert metrics["MRR@10"] == 1.0
    assert metrics["AllEvidencePages@5"] == 1.0
    assert metrics["latency_ms_p50"] == 25.0
    assert metrics["latency_ms_p95"] == 25.0
