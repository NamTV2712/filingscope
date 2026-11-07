"""
Module: retriever.py
Purpose: The only class that external code needs to use to perform retrieval.
(LLM) only needs to import Retriever — regardless of whether Embedder or
VectorStore exists.
"""

import logging
from dataclasses import dataclass

from src.retrieval.embedder import Embedder
from src.retrieval.vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """Result returned from retrieval — only contains what Step 8 (LLM) needs.
    score: cosine similarity (0-1), higher = closer to the question in terms of semantics.
    citation: pre-formatted citation string for LLM to insert into the response.
    """
    chunk_id: str
    ticker: str
    section: str
    filing_date: str
    score: float
    text: str
    citation: str  # Example: "AAPL 10-K (2025-10-31), Section: Risk Factors"
    document_id: str | None = None
    filing_type: str | None = None
    report_date: str | None = None
    chunk_index: int | None = None
    source_url: str | None = None
    score_kind: str = "retrieval"
    company: str | None = None
    doc_name: str | None = None
    page_number: int | None = None
    dataset_id: str | None = None

    @classmethod
    def from_raw(
        cls,
        raw: dict,
        score: float | None = None,
        score_kind: str | None = None,
    ) -> "RetrievedChunk":
        """Create a RetrievedChunk from a raw dict, using provided score or raw['score']."""
        section = str(raw.get("section") or "document")
        section_label = section.replace("_", " ").title()
        doc_name = raw.get("doc_name")
        page_number = raw.get("page_number")
        company = raw.get("company")
        ticker = raw.get("ticker") or company or doc_name or "UNKNOWN"
        filing_date = raw.get("filing_date") or raw.get("report_date") or ""
        if doc_name is not None and isinstance(page_number, int):
            citation = f"{doc_name}, PDF page {page_number + 1}"
        else:
            citation = (
                f"{ticker} 10-K (filed {filing_date}), "
                f"Section: {section_label}"
            )
        accession_number = raw.get("accession_number")
        document_id = raw.get("document_id")
        if document_id is None and ticker and accession_number:
            document_id = f"{ticker}:{accession_number}"
        return cls(
            chunk_id=raw["chunk_id"],
            ticker=ticker,
            section=section,
            filing_date=filing_date,
            score=float(score if score is not None else raw.get("score", 0.0)),
            text=raw["text"],
            citation=citation,
            document_id=document_id,
            filing_type=raw.get("filing_type"),
            report_date=raw.get("report_date"),
            chunk_index=raw.get("chunk_index"),
            source_url=raw.get("source_url") or raw.get("filing_url"),
            score_kind=score_kind or ("cross_encoder" if score is not None else "retrieval"),
            company=company,
            doc_name=doc_name,
            page_number=page_number,
            dataset_id=raw.get("dataset_id"),
        )


class Retriever:
    def __init__(self, embedder: Embedder, store: VectorStore):
        # Receive dependency from outside (dependency injection) instead of
        # initializing internally — makes testing easier (can inject mock),
        # and avoids loading the model multiple times when multiple modules share the Retriever.
        self.embedder = embedder
        self.store = store

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        ticker: str | None = None,
        section: str | None = None,
    ) -> list[RetrievedChunk]:
        """The only entry point for all retrieval requests.
        query: the user's English question (without prefix — Retriever adds it)
        top_k: the number of chunks to return
        ticker/section: optional filters — None means no filter
        """
        if not query.strip():
            logger.warning("Query is empty, returning empty results")
            return []

        query_vector = self.embedder.embed_query(query)
        raw_results = self.store.search(
            query_vector=query_vector,
            top_k=top_k,
            ticker=ticker,
            section=section,
        )

        chunks = [RetrievedChunk.from_raw(r) for r in raw_results]
        logger.info(
            "Query '%s...' → %d chunk (top score: %.4f)",
            query[:50], len(chunks), chunks[0].score if chunks else 0,
        )
        return chunks
