from src.evaluation.retrieval_adapter import FinanceBenchRetrievalAdapter
from src.retrieval.hybrid_retriever import HybridRetriever


class _NoCrossEncoder:
    def __init__(self, *args, **kwargs):
        pass

    def predict(self, *_args, **_kwargs):
        raise AssertionError("hybrid without reranking must not call CrossEncoder")


class _Embedder:
    def embed_query(self, _query):
        return [1.0, 0.0]


class _Store:
    def search(self, query_vector, top_k, ticker=None, section=None):
        return [
            {"chunk_id": "chunk-a", "score": 0.9},
            {"chunk_id": "chunk-b", "score": 0.2},
        ][:top_k]


def test_company_document_corpus_supports_hybrid_rrf_without_reranker(monkeypatch) -> None:
    import src.retrieval.hybrid_retriever as hybrid_module

    monkeypatch.setattr(hybrid_module, "CrossEncoder", _NoCrossEncoder)
    chunks = [
        {
            "chunk_id": "chunk-a",
            "company": "Synthetic Co",
            "doc_name": "SYNTHETIC_2024_10K",
            "page_number": 0,
            "section": "document",
            "text": "Synthetic Co revenue was 100 million dollars.",
        },
        {
            "chunk_id": "chunk-b",
            "company": "Synthetic Co",
            "doc_name": "SYNTHETIC_2024_10K",
            "page_number": 1,
            "section": "document",
            "text": "Operating expenses were 30 million dollars.",
        },
    ]
    retriever = HybridRetriever(
        embedder=_Embedder(),
        store=_Store(),
        all_chunks=chunks,
        device="cpu",
    )
    adapter = FinanceBenchRetrievalAdapter(retriever, top_k=2, candidate_pool=2)

    results = adapter.retrieve(
        "What was revenue?",
        preset="hybrid",
        query_embedding=[1.0, 0.0],
    )

    assert results
    assert results[0]["doc_name"] == "SYNTHETIC_2024_10K"
    assert results[0]["score_kind"] == "rrf"
    assert results[0]["page_number"] in {0, 1}
