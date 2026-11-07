"""Offline smoke test for the migrated dense + BM25 + reranking path."""

import src.retrieval.hybrid_retriever as hybrid_module
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.vector_store import VectorStore


class DeterministicEmbedder:
    """Small deterministic vectors keep this smoke test model-download free."""

    model_name = "filingscope-test-embedding"

    @staticmethod
    def _vector(text: str) -> list[float]:
        return [1.0, 0.0, 0.0] if "apple" in text.casefold() else [0.0, 1.0, 0.0]

    def embed_documents(self, texts: list[str], batch_size: int | None = None):
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class DeterministicCrossEncoder:
    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def predict(pairs, batch_size: int = 4):
        return [1.0 if "apple" in text.casefold() else 0.0 for _, text in pairs]


def test_synthetic_hybrid_retrieval_uses_qdrant_bm25_and_reranker(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(hybrid_module, "CrossEncoder", DeterministicCrossEncoder)
    chunks = [
        {
            "chunk_id": "aapl-fy2024-revenue",
            "ticker": "AAPL",
            "section": "financial_table",
            "accession_number": "0000320193-24-000123",
            "filing_date": "2024-11-01",
            "report_date": "2024-09-28",
            "chunk_index": 0,
            "token_count": 8,
            "text": "Apple reported FY2024 revenue of 391 billion dollars.",
        },
        {
            "chunk_id": "msft-fy2024-revenue",
            "ticker": "MSFT",
            "section": "financial_table",
            "accession_number": "0000789019-24-000456",
            "filing_date": "2024-07-30",
            "report_date": "2024-06-30",
            "chunk_index": 0,
            "token_count": 8,
            "text": "Microsoft reported FY2024 revenue of 245 billion dollars.",
        },
    ]
    embedder = DeterministicEmbedder()

    with VectorStore(path=tmp_path / "qdrant") as store:
        store.create_collection(embedding_dim=3)
        embedded = [
            {**chunk, "embedding": vector}
            for chunk, vector in zip(
                chunks, embedder.embed_documents([chunk["text"] for chunk in chunks])
            )
        ]
        store.upsert_chunks(embedded)

        retriever = HybridRetriever(
            embedder=embedder,
            store=store,
            all_chunks=chunks,
            cross_encoder_model="test-only",
            cross_encoder_revision="test-only",
        )
        result = retriever.retrieve("Apple FY2024 revenue", top_k=1)

    assert len(result) == 1
    assert result[0].chunk_id == "aapl-fy2024-revenue"
    assert result[0].ticker == "AAPL"
