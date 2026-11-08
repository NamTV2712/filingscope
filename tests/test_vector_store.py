from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

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


def test_metadata_filters_build_exact_and_any_payload_conditions() -> None:
    query_filter = VectorStore._build_filter(
        ticker=None,
        section=None,
        metadata_filters={
            "company": ("Acme Inc.", "Beta Inc."),
            "reporting_periods": ("2021",),
        },
    )

    assert query_filter is not None
    conditions = {condition.key: condition.match for condition in query_filter.must}
    assert conditions["company"].any == ["Acme Inc.", "Beta Inc."]
    assert conditions["reporting_periods"].value == "2021"


def test_metadata_filter_rejects_unknown_fields_and_empty_values() -> None:
    with pytest.raises(ValueError, match="unsupported metadata filter field"):
        VectorStore._build_filter(None, None, {"cik": ("0000001",)})
    with pytest.raises(ValueError, match="non-empty strings"):
        VectorStore._build_filter(None, None, {"company": ("")})


def test_search_applies_company_period_and_document_type_filters(tmp_path) -> None:
    store = VectorStore(path=tmp_path, collection_name="metadata_filter_test")
    try:
        store.create_collection(embedding_dim=2)
        store.upsert_chunks(
            [
                {
                    "chunk_id": "apple-2022-10k",
                    "company": "Apple Inc.",
                    "reporting_periods": ["2022"],
                    "doc_type": "10k",
                    "embedding": [1.0, 0.0],
                },
                {
                    "chunk_id": "apple-2021-10k",
                    "company": "Apple Inc.",
                    "reporting_periods": ["2021"],
                    "doc_type": "10k",
                    "embedding": [0.99, 0.01],
                },
                {
                    "chunk_id": "beta-2022-10k",
                    "company": "Beta Inc.",
                    "reporting_periods": ["2022"],
                    "doc_type": "10k",
                    "embedding": [0.98, 0.02],
                },
                {
                    "chunk_id": "apple-2022-10q",
                    "company": "Apple Inc.",
                    "reporting_periods": ["2022"],
                    "doc_type": "10q",
                    "embedding": [0.97, 0.03],
                },
            ]
        )

        results = store.search(
            query_vector=[1.0, 0.0],
            top_k=10,
            metadata_filters={
                "company": ("Apple Inc.",),
                "reporting_periods": ("2022",),
                "doc_type": ("10k",),
            },
        )

        assert [row["chunk_id"] for row in results] == ["apple-2022-10k"]
    finally:
        store.close()
