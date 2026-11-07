# Source Code Audit

## Scope and provenance

- Source: `D:\Project\Enterprise_Document_QA`
- Source revision inspected: `2ac043347f57e257dac4e2947a57dfced8709d97`
- Source branch: `main`
- Target: `D:\Project\filingscope`
- Target starting revision: `2a1fa6d231b9a4be8a9772e8610687f120a8e982`
- Audit date: 2026-11-07

The source worktree had untracked local files before the audit. They were left
untouched. The target began as a clean `main` checkout. Its configured
`origin/main` is `https://github.com/NamTV2712/filingscope.git`; a read-only
`git ls-remote` confirmed that the remote `HEAD` and `main` matched the target's
starting commit.

The source `README.md`, `ARCHITECTURE.md`, `docs/SETUP.md`,
`requirements.txt`, `.env.example` variable names, `AGENTS.md`, and
`PROJECT_STATE.md` were reviewed. The actual source `.env` was not opened. The
names of `.env.example` variables and the model revision identifiers were
checked; no credential values were inspected or copied. Local corpus,
embedding files, Qdrant storage, model caches, virtual environments, browser
artifacts, and SQLite databases were not copied.

The source contains local `data/raw`, `data/processed`, and
`data/embedding_generations` directories. They were treated as private runtime
artifacts and were not inspected or migrated. No source files were edited.

## Existing system and migration decision

| Area | Source implementation | Source tests reviewed for reuse | P0 decision |
|---|---|---|---|
| SEC ingestion | `src/ingestion/sec_client.py`; `scripts/download_filings.py` | `tests/test_sec_client.py` | Reuse client, throttling, retry/error mapping, and idempotent download orchestration. Target downloader reads `SEC_USER_AGENT` from target config instead of copying a personal contact string. |
| Section extraction | `src/ingestion/section_extractor.py` | `tests/test_section_extractor.py` | Reuse SEC HTML parsing and section boundary logic. |
| Text/table chunking | `src/ingestion/chunker.py`; `scripts/chunk_filings.py` | No dedicated source chunker test file was present in the inspected test inventory. | Reuse token-aware chunk construction and preserve filing metadata. Add a focused target unit test for token bounds and filing metadata. |
| Financial tables | `src/ingestion/table_extractor.py`, `table_discovery.py`, `companion_documents.py`; `scripts/add_table_chunks.py` | `tests/test_table_extractor.py`, `tests/test_table_discovery.py` | Reuse table parsing, explicit unit extraction, statement discovery, and companion document handling. Move the locator helper out of a diagnostics script into `src/ingestion/financial_section_locator.py`. |
| Embeddings | `src/retrieval/embedder.py` | `tests/test_embedder_revision.py` | Reuse Sentence Transformers and the `search_document:` / `search_query:` prefixes. Pin the source model revision in target settings and preserve CPU/GPU resolution and float32, unnormalized vectors. |
| Vector store | `src/retrieval/vector_store.py` | `tests/test_vector_store.py` | Reuse Qdrant local/cloud setup, deterministic point IDs, upsert, search filters, payload loading, and lifecycle management. Do not migrate the local collection. |
| Hybrid retrieval | `src/retrieval/hybrid_retriever.py`, `retriever.py`, `lexical_ladder.py`, `query_shaper.py`, `structured_lookup.py` | `tests/test_hybrid_retriever_inspect.py`, `test_hybrid_retriever_concurrency.py`, `test_hybrid_retriever_section_filter.py`, `test_query_shaper.py`, `test_lexical_ladder.py`, `test_structured_lookup.py` | Reuse BM25, Qdrant dense search, candidate shaping, RRF, optional lexical candidates, structured lookup, and cross-encoder reranking. Keep `inspect()` distinct from production `retrieve()`. |
| Embedding/index integrity | `src/retrieval/embedding_generation.py`, `index_manifest.py`, `canonical_json.py`, `chunk_loader.py`; `scripts/embed_chunks.py`, `index_chunks.py` | `tests/test_embedding_generation.py`, `test_index_manifest.py`, `test_index_chunks.py`, `test_chunk_loader.py` | Reuse immutable generation validation, canonical hashing, index manifests, and chunk loading. Never reuse the source index without verifying its manifest. |
| Configuration | `configs/settings.py`, `logging_config.py`, `offline_guard.py`, `tickers.py` | Covered by focused tests and hermetic pytest setup. | Reuse ticker metadata, logging, and socket guard. Replace the source's broad application settings with a smaller P0 settings model limited to ingestion, Qdrant, and model provenance. |
| Dependencies/operations | `requirements.txt`, `pytest.ini`, `Dockerfile`, Compose, CI workflows | CI and setup instructions reviewed | Use a focused P0 dependency set and pytest configuration. Docker, API, frontend, and CI are deferred until later phases. |

## Baseline architecture

The migrated data path is:

```text
SEC EDGAR → raw 10-K HTML → section JSON → token-aware text chunks
          → supplemental financial table chunks → pinned embeddings
          → immutable embedding generation → Qdrant index + manifest
```

The query path uses the existing `HybridRetriever`: BM25 and dense Qdrant
retrieval are fused with reciprocal rank fusion and refined by the existing
cross-encoder. Query shaping, lexical candidates, and structured financial
lookup remain part of the same retrieval implementation. `RetrievedChunk`
retains the citation and document fields exposed by the source baseline.

`inspect()` produces diagnostic stage information; it does not run the same
full production path as `retrieve()`. Its output must not be used as a
production accuracy result. Qdrant local storage has a file lock and should
only be owned by one process at a time.

## Verification

P0 target tests are hermetic by default. The synthetic integration smoke test
uses the migrated `HybridRetriever`, an actual temporary local Qdrant
collection, BM25, deterministic vectors, and a deterministic cross-encoder
double. It verifies the wiring without downloading models or making network
requests.

The final P0 gate ran `python -m pytest tests/ -q -rs`: **110 passed, 3
skipped**. The skips require local AAPL/MSFT filing fixtures or a local
same-document corpus. `python -m compileall -q src scripts configs tests`
passed. Tests ran from the target checkout using the existing Python 3.12
environment in the source repository's virtual environment; imports resolved
to the target's `src/` tree. The environment emitted a requests/urllib3
version warning, Beautiful Soup deprecation warnings, and Qdrant's expected
local-payload-index warning; none caused a test failure.

No FinanceBench retrieval or answer benchmark was run in P0. The source's
historical benchmark results are not FilingScope results and were not copied
or presented as new measurements.

## Migration risks and open gaps

- The source baseline is SEC HTML-specific. FinanceBench PDFs need a separate
  parser and provenance path in P1.
- P0 chunks retain the source fields but do not yet provide a complete unified
  document schema for PDF page spans, currency, or cross-dataset identity.
- The source vector store uses one collection name. P1 must add an explicit
  dataset collection strategy before indexing FinanceBench.
- Real model weights are downloaded at runtime and are not included. Model
  revision and vector dimension must remain bound to the index manifest.
- SEC downloading requires a user-supplied contact email in `SEC_USER_AGENT`.
- A subset of the source suite depends on API, generation, or agent packages
  intentionally excluded from P0. Those tests were not copied unless their
  subject is present in the migrated target.
- `tests/test_retrieval_inspect_metadata.py` was excluded because it imports
  the source API application, which is not part of the P0 migration.
- Source environment version mismatches can emit dependency warnings; P0
  target tests ran against the already available Python 3.12 environment.

## Excluded from P0

Generation and provider policy, Agent orchestration and persistence, FastAPI,
frontend, historical evaluation artifacts, FinanceBench, local SEC data,
`.env`, local Qdrant files, model caches, and generated runtime artifacts are
not part of this migration. Their inclusion will be decided from actual P1–P6
requirements rather than copied wholesale.
