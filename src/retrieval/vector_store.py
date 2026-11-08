"""
Module: vector_store.py
Purpose: A wrapper for Qdrant — creating collections, upsert chunks, semantic search.
Designed to be easily ported from a local persistent server to the Qdrant server
simply by changing initialization parameters, without modifying business logic.
"""

import logging
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

logger = logging.getLogger(__name__)

COLLECTION_NAME = "sec_filings"
BATCH_SIZE = 100
SCROLL_PAGE_SIZE = 256
METADATA_FILTER_FIELDS = frozenset({"company", "doc_type", "reporting_periods"})
PAYLOAD_INDEX_FIELDS = ("ticker", "section", "company", "doc_type", "reporting_periods")


class VectorStore:
    def __init__(
        self,
        path: str | Path = "data/qdrant",
        mode: str = "local",
        url: str | None = None,
        api_key: str | None = None,
        collection_name: str = COLLECTION_NAME,
    ):
        """Initialize Qdrant in local persistent mode or cloud mode."""
        if not collection_name or not isinstance(collection_name, str):
            raise ValueError("collection_name must be a non-empty string")
        self.collection_name = collection_name
        self.mode = mode
        if mode == "local":
            Path(path).mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(path))
            logger.info("Qdrant local client initialized at: %s", path)
            return

        if mode == "cloud":
            if not url or not api_key:
                raise ValueError("Qdrant cloud mode requires url and api_key")
            self.client = QdrantClient(url=url, api_key=api_key)
            logger.info("Qdrant cloud client initialized at: %s", url)
            return

        raise ValueError("qdrant mode must be 'local' or 'cloud'")

    @property
    def collection_name(self) -> str:
        """Return the configured collection while preserving legacy __new__ tests."""
        return getattr(self, "_collection_name", COLLECTION_NAME)

    @collection_name.setter
    def collection_name(self, value: str) -> None:
        self._collection_name = value

    def create_collection(self, embedding_dim: int = 768) -> None:
        """Create collection if it doesn't exist.
        If it already exists, skip — idempotent, safe to call multiple times.
        """
        existing = [c.name for c in self.client.get_collections().collections]
        if self.collection_name in existing:
            logger.info("Collection '%s' already exists, skipping.", self.collection_name)
            self._ensure_payload_indexes()
            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=embedding_dim, distance=Distance.COSINE),
        )
        logger.info(
            "Created collection '%s' (dim=%d, Cosine)",
            self.collection_name,
            embedding_dim,
        )
        self._ensure_payload_indexes()

    def upsert_chunks(self, chunks: list[dict]) -> None:
        """Upsert list of chunks from embedded JSONL.

        Uses a deterministic UUID derived from chunk_id, so rerunning indexing
        updates existing points instead of creating duplicates across processes.
        """
        points = []
        for chunk in chunks:
            if not isinstance(chunk.get("chunk_id"), str) or not chunk["chunk_id"]:
                raise ValueError("Every chunk must have a non-empty chunk_id")
            if "embedding" not in chunk:
                raise ValueError(f"Chunk {chunk['chunk_id']!r} has no embedding")
            payload = {key: value for key, value in chunk.items() if key != "embedding"}
            points.append(
                PointStruct(
                    id=self._chunk_id_to_uuid(chunk["chunk_id"]),
                    vector=chunk["embedding"],
                    payload=payload,
                )
            )
        for start in range(0, len(points), BATCH_SIZE):
            self.client.upsert(
                collection_name=self.collection_name,
                points=points[start:start + BATCH_SIZE],
            )
        logger.info(
            "Upserted %d points into collection '%s'",
            len(points),
            self.collection_name,
        )

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        ticker: str | None = None,
        section: str | None = None,
        metadata_filters: Mapping[str, str | Sequence[str]] | None = None,
    ) -> list[dict]:
        """Semantic search supports filtering by ticker and/or section.
            Returns a list dict with the fields 'score' (0-1), 'text', and all metadata.
        """
        query_filter = self._build_filter(
            ticker=ticker,
            section=section,
            metadata_filters=metadata_filters,
        )
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )
        results = response.points
        return [{"score": r.score, **r.payload} for r in results]

    def get_collection_info(self) -> dict:
        info = self.client.get_collection(self.collection_name)
        return {
            "vectors_count": getattr(info, "vectors_count", info.points_count),
            "indexed_vectors_count": getattr(info, "indexed_vectors_count", None),
            "points_count": info.points_count,
            "status": str(info.status),
        }

    def load_all_chunks(self, page_size: int = SCROLL_PAGE_SIZE) -> list[dict]:
        """Load chunk payloads without vectors for stateless cloud startup."""
        chunks = []
        offset = None
        while True:
            points, next_offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=page_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            chunks.extend(dict(point.payload) for point in points if point.payload)
            if next_offset is None:
                break
            offset = next_offset

        logger.info("Loaded %d chunk payloads from Qdrant", len(chunks))
        return chunks

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "VectorStore":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @staticmethod
    def _chunk_id_to_uuid(chunk_id: str) -> str:
        """Qdrant accepts UUID strings; uuid5 is stable across Python processes."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))

    def _ensure_payload_indexes(self) -> None:
        """Create keyword payload indexes needed for filtered search in Qdrant Cloud."""
        info = self.client.get_collection(self.collection_name)
        existing_schema = getattr(info, "payload_schema", None) or {}
        for field_name in PAYLOAD_INDEX_FIELDS:
            if field_name in existing_schema:
                continue
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name=field_name,
                field_schema=PayloadSchemaType.KEYWORD,
            )
            logger.info("Created payload index for '%s'", field_name)

    @staticmethod
    def _build_filter(
        ticker: str | None,
        section: str | None,
        metadata_filters: Mapping[str, str | Sequence[str]] | None = None,
    ) -> Filter | None:
        conditions = []
        if ticker:
            conditions.append(FieldCondition(key="ticker", match=MatchValue(value=ticker)))
        if section:
            conditions.append(FieldCondition(key="section", match=MatchValue(value=section)))
        filters = metadata_filters or {}
        unknown_fields = set(filters) - METADATA_FILTER_FIELDS
        if unknown_fields:
            raise ValueError(
                f"unsupported metadata filter field(s): {', '.join(sorted(unknown_fields))}"
            )
        for field, raw_values in filters.items():
            if isinstance(raw_values, str):
                values = (raw_values,)
            elif isinstance(raw_values, Sequence) and not isinstance(raw_values, (bytes, bytearray)):
                values = tuple(raw_values)
            else:
                raise ValueError(f"metadata filter {field!r} must be a string or sequence of strings")
            if not values or any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"metadata filter {field!r} must contain non-empty strings")
            match = (
                MatchValue(value=values[0])
                if len(values) == 1
                else MatchAny(any=list(values))
            )
            conditions.append(FieldCondition(key=field, match=match))
        return Filter(must=conditions) if conditions else None
