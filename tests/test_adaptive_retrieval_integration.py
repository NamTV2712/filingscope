"""Offline integration from evidence gaps through the migrated retriever."""

import src.retrieval.hybrid_retriever as hybrid_module
from src.agent.adaptive_retrieval import AdaptiveRetrievalBudget, AdaptiveRetrievalController
from src.decision.models import DecisionAction
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.vector_store import VectorStore


class DeterministicEmbedder:
    model_name = "filingscope-adaptive-test-embedding"

    @staticmethod
    def _vector(text: str) -> list[float]:
        folded = text.casefold()
        if "microsoft" in folded or "msft" in folded:
            return [0.0, 1.0, 0.0]
        return [1.0, 0.0, 0.0]

    def embed_documents(self, texts: list[str], batch_size: int | None = None):
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class DeterministicCrossEncoder:
    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def predict(pairs, batch_size: int = 4):
        return [1.0 if "microsoft" in query.casefold() and "microsoft" in text.casefold() else 0.0
                for query, text in pairs]


def _chunk(chunk_id: str, ticker: str, company: str, year: str, value: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "ticker": ticker,
        "company": company,
        "doc_name": f"{ticker}_annual_report.pdf",
        "document_id": f"{ticker}_annual_report.pdf",
        "section": "financial_table",
        "page_number": 4,
        "source_url": "https://example.com/report.pdf",
        "filing_date": "2025-01-01",
        "report_date": "2024-12-31",
        "chunk_index": 0,
        "token_count": 8,
        "text": f"{year}\nTotal revenue\n{value}",
    }


def test_adaptive_controller_retrieves_missing_slot_with_hybrid_retriever(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(hybrid_module, "CrossEncoder", DeterministicCrossEncoder)
    chunks = [
        _chunk("aapl-fy2024", "AAPL", "Apple Inc.", "2024", "$391 billion"),
        _chunk("aapl-fy2022", "AAPL", "Apple Inc.", "2022", "$394 billion"),
        _chunk("msft-fy2024", "MSFT", "Microsoft Corporation", "2024", "$245 billion"),
        _chunk("msft-fy2022", "MSFT", "Microsoft Corporation", "2022", "$198 billion"),
    ]
    embedder = DeterministicEmbedder()

    with VectorStore(path=tmp_path / "qdrant") as store:
        store.create_collection(embedding_dim=3)
        embedded = [
            {**chunk, "embedding": vector}
            for chunk, vector in zip(
                chunks,
                embedder.embed_documents([chunk["text"] for chunk in chunks]),
                strict=True,
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
        initial = [chunks[0], chunks[1], chunks[2]]

        result = AdaptiveRetrievalController(retriever).run(
            "Compare Apple and Microsoft revenue growth between 2022 and 2024",
            initial,
            budget=AdaptiveRetrievalBudget(max_rounds=2, max_queries=2, top_k=4),
        )

    assert result.final_decision.action == DecisionAction.ANSWER
    assert result.queries_used == 1
    assert "msft-fy2022" in result.trace[0].added_chunk_ids
