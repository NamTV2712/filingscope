from types import SimpleNamespace
from unittest.mock import MagicMock, call

from src.retrieval.vector_store import COLLECTION_NAME, VectorStore


def test_load_all_chunks_scrolls_payloads_without_vectors() -> None:
    store = VectorStore.__new__(VectorStore)
    store.client = MagicMock()
    store.client.scroll.side_effect = [
        ([SimpleNamespace(payload={"chunk_id": "first"})], "next-page"),
        ([SimpleNamespace(payload={"chunk_id": "second"})], None),
    ]

    chunks = store.load_all_chunks(page_size=10)

    assert chunks == [{"chunk_id": "first"}, {"chunk_id": "second"}]
    assert store.client.scroll.call_args_list == [
        call(
            collection_name=COLLECTION_NAME,
            limit=10,
            offset=None,
            with_payload=True,
            with_vectors=False,
        ),
        call(
            collection_name=COLLECTION_NAME,
            limit=10,
            offset="next-page",
            with_payload=True,
            with_vectors=False,
        ),
    ]


def test_custom_collection_and_generic_payloads_keep_dataset_page_metadata() -> None:
    store = VectorStore.__new__(VectorStore)
    store.collection_name = "financebench_test"
    store.client = MagicMock()

    store.upsert_chunks(
        [
            {
                "chunk_id": "financebench-doc-page-0",
                "company": "Synthetic Co",
                "doc_name": "SYNTHETIC_10K",
                "page_number": 0,
                "section": "document",
                "text": "Revenue was 100 million dollars.",
                "embedding": [0.25, 0.75],
            }
        ]
    )

    call_args = store.client.upsert.call_args.kwargs
    point = call_args["points"][0]
    assert call_args["collection_name"] == "financebench_test"
    assert point.payload["doc_name"] == "SYNTHETIC_10K"
    assert point.payload["page_number"] == 0
    assert "embedding" not in point.payload
