"""Load hash-bound filing artifacts for the benchmark and local workspace."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from configs.financebench import P1_EMBEDDING_REVISION
from src.agent.complexity_router import ComplexityRouter
from src.agent.specialist_graph import SpecialistResearchGraph
from src.evaluation.company_facts_replay import CompanyFactsReplay
from src.research.corpus_map import CorpusMap
from src.retrieval.canonical_json import sha256_file
from src.retrieval.financial_statement_ranker import FinancialStatementRanker
from src.retrieval.frozen_artifacts import load_frozen_corpus, load_frozen_vectors
from src.retrieval.frozen_dense import FrozenDenseRetriever
from src.retrieval.pdf_page_cache import FrozenPdfPages
from src.runtime.filing_models import Corpus, Filing, FilingInventoryEntry


def _read_pinned(path: Path, checksum: str) -> str:
    if sha256_file(path) != checksum:
        raise ValueError(f"Filing bundle hash mismatch for {path.name}")
    return path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class FilingRuntime:
    corpus: Corpus
    cutoff: str
    graph: SpecialistResearchGraph
    router: ComplexityRouter
    retriever: Any
    sec: CompanyFactsReplay
    pages: FrozenPdfPages
    documents: dict[str, Path]
    document_hashes: dict[str, str]


def load_filing_runtime(
    bundle: Path, *, corpus: Corpus | None = None, cutoff: str | None = None,
    retriever_wrapper: Callable[[FrozenDenseRetriever], Any] | None = None,
    retrieval_policy: str = "statement", generator=None, provider_limits=None,
    max_correction_passes: int = 1,
) -> FilingRuntime:
    """Validate label-free inputs before constructing a local research graph."""
    from src.retrieval.embedder import MODEL_NAME, Embedder

    bundle = bundle.resolve()
    corpus = corpus or Corpus.model_validate_json((bundle / "corpus.json").read_bytes())
    filings = {filing.document_id: filing for filing in corpus.filings}
    if len(filings) != len(corpus.filings) or len({row.accession for row in corpus.filings}) != len(filings):
        raise ValueError("Filing inventory contains duplicate document or accession identities")
    inventory = {}
    inventory_path = bundle / "filing-inventory.json"
    if inventory_path.is_file():
        rows = TypeAdapter(list[FilingInventoryEntry]).validate_json(inventory_path.read_bytes())
        inventory = {row.document_id: row for row in rows}
        if len(inventory) != len(rows) or inventory.keys() != filings.keys() or any(
            Filing.model_validate(row.model_dump(exclude={"company", "ticker", "fiscal_year"})) != filings[row.document_id]
            for row in rows
        ):
            raise ValueError("Source inventory disagrees with the filing corpus")
    index = bundle / "index"
    _read_pinned(index / "index_manifest.json", corpus.index_manifest_sha256)
    embedding = json.loads(_read_pinned(index / "embedding_manifest.json", corpus.embedding_manifest_sha256))
    if embedding["embedding_model_id"] != MODEL_NAME or embedding["embedding_model_revision"] != P1_EMBEDDING_REVISION:
        raise ValueError("Filing bundle must use the pinned Nomic model and revision")
    if embedding.get("document_prefix", "search_document: ") != "search_document: " or embedding.get("normalize_embeddings", False):
        raise ValueError("Filing bundle must use the pinned document embedding protocol")
    _read_pinned(index / "corpus_chunks.jsonl", corpus.chunks_sha256)
    chunks = load_frozen_corpus(index, index_id=corpus.index_id, fingerprint=corpus.fingerprint)
    if {row["document_id"] for row in chunks} != filings.keys():
        raise ValueError("Indexed documents must match the filing corpus")
    for chunk in chunks:
        filing = filings[chunk["document_id"]]
        if (chunk["doc_name"] != filing.document_id or int(chunk["cik"]) != filing.cik
                or chunk["source_url"] != filing.source_url
                or chunk.get("accession_number", filing.accession) != filing.accession
                or chunk.get("filing_date", filing.filed.isoformat()) != filing.filed.isoformat()
                or chunk.get("doc_type", filing.form) != filing.form):
            raise ValueError("Indexed chunk provenance disagrees with the filing corpus")
        declared = inventory.get(filing.document_id)
        if declared is not None and (
            chunk["company"] != declared.company
            or chunk.get("ticker", declared.ticker) != declared.ticker
            or str(declared.fiscal_year) not in {str(year) for year in chunk.get("reporting_periods", ())}
        ):
            raise ValueError("Indexed company or fiscal year disagrees with the source inventory")
    documents = {}
    for filing in corpus.filings:
        path = (bundle / "filings" / f"{filing.document_id}.pdf").resolve()
        if not path.is_relative_to(bundle) or sha256_file(path) != filing.document_sha256:
            raise ValueError("A source PDF differs from the filing corpus")
        documents[filing.document_id] = path
    pages = FrozenPdfPages(bundle / "pages.jsonl", expected_sha256=corpus.pages_sha256)
    for chunk in chunks:
        if pages.get(chunk["document_id"], chunk["page_number"]) is None:
            raise ValueError("An indexed chunk has no physical source page")
    vectors = load_frozen_vectors(index, chunks, fingerprint=corpus.fingerprint)
    sec_manifest = json.loads(_read_pinned(bundle / "sec/manifest.json", corpus.sec_manifest_sha256))
    snapshot_cutoff = date.fromisoformat(sec_manifest["latest_filed"])
    if cutoff is not None and date.fromisoformat(cutoff) != snapshot_cutoff:
        raise ValueError("Requested cutoff differs from the pinned SEC snapshot")
    if any(filing.filed > snapshot_cutoff for filing in corpus.filings):
        raise ValueError("A filing date exceeds the pinned snapshot cutoff")
    cutoff = snapshot_cutoff.isoformat()
    issuers = {ticker: item["cik"] for ticker, item in sec_manifest["issuers"].items()}
    if not set(issuers.values()) <= {filing.cik for filing in corpus.filings}:
        raise ValueError("SEC snapshots include issuers outside the filing corpus")
    sec = CompanyFactsReplay(bundle / "sec", issuers, latest_filed=cutoff)
    ticker_by_cik = {cik: ticker for ticker, cik in issuers.items()}
    tickers = {row["company"]: row.get("ticker") or ticker_by_cik.get(int(row["cik"])) for row in chunks}
    tickers.update({row.company: row.ticker for row in inventory.values() if row.ticker})
    router = ComplexityRouter(CorpusMap.from_chunks(chunks, index_generation_id=corpus.index_id))
    ranker = FinancialStatementRanker(pages, router.extractor) if retrieval_policy == "statement" else None
    dense = FrozenDenseRetriever(chunks, vectors, Embedder(device="cpu", revision=P1_EMBEDDING_REVISION),
                                 pdf_pages=pages, statement_ranker=ranker)
    retriever = retriever_wrapper(dense) if retriever_wrapper else dense
    graph = SpecialistResearchGraph(router=router, retriever=retriever, sec_client=sec,
                                   ticker_by_company={company: ticker for company, ticker in tickers.items() if ticker},
                                   generator=generator, provider_limits=provider_limits,
                                   max_correction_passes=max_correction_passes)
    return FilingRuntime(corpus, cutoff, graph, router, retriever, sec, pages, documents,
                         {row.document_id: row.document_sha256 for row in corpus.filings})
