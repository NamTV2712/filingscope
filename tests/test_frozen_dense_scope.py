import numpy as np

from src.retrieval.frozen_dense import FrozenDenseRetriever


def test_scoped_dense_intersects_filters_and_keeps_tie_order():
    class QueryEmbedder:
        def embed_query(self, query):
            return [1.0, 0.0]

    chunks = [
        {"document_id": document, "chunk_id": str(index)}
        for index, document in enumerate(("wrong", "right", "right", "right", "wrong", "wrong", "wrong", "wrong"))
    ]
    vectors = np.array([[1, 0], [0.5, 0.5], [0.5, -0.5], [1, 0], [1, 0], [1, 0], [1, 0], [1, 0]],
                       dtype=np.float32)
    retriever = FrozenDenseRetriever(chunks, vectors, QueryEmbedder())
    eligible = np.ones(len(chunks), dtype=bool)
    eligible[3] = False
    rows = retriever.retrieve("test", document_ids=("right",), eligible=eligible)
    assert [(row["chunk_id"], row["score"]) for row in rows] == [("1", 0.5), ("2", 0.5)]
    assert retriever.retrieve("test", document_ids=("missing",)) == []
    assert [row["chunk_id"] for row in retriever.retrieve("test", top_k=2)] == ["0", "3"]
