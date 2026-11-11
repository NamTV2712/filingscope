from src.evaluation.corpus_aware_planning import evaluate_corpus_aware_planning
from src.evaluation.financebench_dataset import FinanceBenchCase
from src.research.corpus_map import CorpusMap
from src.research.planner import CorpusAwarePlanner, QuestionOnlyPlanner


def test_planner_comparison_keeps_gold_labels_in_the_evaluator(monkeypatch):
    chunks = [
        {
            "chunk_id": "chunk-1",
            "document_id": "ACME_2023_10K",
            "doc_name": "ACME_2023_10K",
            "company": "Acme Corp",
            "doc_type": "10k",
            "reporting_periods": ["2023"],
            "section": "document",
            "page_number": 4,
            "text": "Acme reported total revenue of 10 million dollars in fiscal 2023.",
        },
        {
            "chunk_id": "chunk-2",
            "document_id": "ACME_2023_10K",
            "doc_name": "ACME_2023_10K",
            "company": "Acme Corp",
            "doc_type": "10k",
            "reporting_periods": ["2023"],
            "section": "document",
            "page_number": 5,
            "text": "Acme has a diverse business and operating footprint.",
        },
    ]
    cases = [
        FinanceBenchCase(
            case_id="case-1",
            company="Acme Corp",
            doc_name="ACME_2023_10K",
            question="What was Acme revenue in FY2023?",
            gold_pages=(4,),
            question_type="lookup",
            split="development",
        )
    ]
    corpus_map = CorpusMap.from_chunks(chunks, index_generation_id="index-1")
    calls = {"question_only": [], "corpus_aware": []}
    original_question_only = QuestionOnlyPlanner.plan
    original_corpus_aware = CorpusAwarePlanner.plan

    def track_question_only(self, question):
        calls["question_only"].append(question)
        return original_question_only(self, question)

    def track_corpus_aware(self, question):
        calls["corpus_aware"].append(question)
        return original_corpus_aware(self, question)

    monkeypatch.setattr(QuestionOnlyPlanner, "plan", track_question_only)
    monkeypatch.setattr(CorpusAwarePlanner, "plan", track_corpus_aware)

    result = evaluate_corpus_aware_planning(
        cases,
        chunks,
        corpus_map,
        index_manifest={"index_id": "index-1", "point_count": len(chunks)},
    )

    assert calls["question_only"]
    assert calls["corpus_aware"]
    assert all(isinstance(question, str) for group in calls.values() for question in group)
    assert calls["question_only"][0] == cases[0].question
    assert calls["corpus_aware"][0] == cases[0].question
    assert result["dataset"]["gold_labels_passed_to_planners"] is False
    assert result["case_count"] == 1
    assert result["comparison"]["corpus_aware"]["retrieval_metrics"]["overall"]["Recall@10"] == 1.0
    assert result["comparison"]["corpus_aware"]["gold_source_document_target_rate"] == 1.0
    assert result["comparison"]["question_only"]["gold_source_document_target_rate"] is None
    assert result["comparison"]["corpus_aware"]["candidate_recall_at_50"][
        "gold_page_candidate_recall_at_50_per_query_union"
    ] == 1.0
    assert result["corpus_map"]["serialized_size_bytes"] > 0
    assert result["resource_use"]["python_peak_allocated_bytes"] > 0
    assert result["provider_calls"] == 0
