# Source Reuse Matrix

Source repository: `D:\Project\Enterprise_Document_QA`
Source revision: `2ac043347f57e257dac4e2947a57dfced8709d97`
Target repository: `D:\Project\filingscope`

| Original file | Target file | Reused functions/classes | Adaptation | Dependencies | Target tests |
|---|---|---|---|---|---|
| `src/ingestion/sec_client.py` | `src/ingestion/sec_client.py` | `SECEdgarClient`, `FilingMetadata`, EDGAR exceptions | Replaced copied personal email examples with `contact@example.com`; downloader contact is configured locally. | `requests` | `tests/test_sec_client.py` |
| `scripts/download_filings.py` | `scripts/download_filings.py` | `process_ticker`, idempotent local artifacts, extraction/report flow | Removed source hard-coded personal `USER_AGENT`; now requires `SEC_USER_AGENT`. | `configs.settings`, `configs.tickers`, ingestion client/extractor | Covered by client and extraction tests; live network intentionally not run. |
| `src/ingestion/section_extractor.py` | `src/ingestion/section_extractor.py` | `ExtractionResult`, `extract_sections`, `extract_sections_from_html` | None in P0. | Beautiful Soup, lxml | `tests/test_section_extractor.py` |
| `src/ingestion/chunker.py` | `src/ingestion/chunker.py` | `Chunk`, `chunk_text`, `build_chunks_for_filing`, `build_table_chunks`, `save_chunks` | None in P0. | tiktoken, Beautiful Soup, `table_extractor` | New `tests/test_chunker.py` |
| `scripts/chunk_filings.py` | `scripts/chunk_filings.py` | `process_file`, `_output_path`, batch summary | Uses the smaller target settings module. | target config, chunker | Invoked by the documented offline/local pipeline; no SEC data is bundled. |
| `src/ingestion/table_extractor.py` | `src/ingestion/table_extractor.py` | `TableRow`, `extract_table_rows`, caption/unit helpers, `rows_to_markdown` | None in P0. | Beautiful Soup | `tests/test_table_extractor.py` |
| `src/ingestion/companion_documents.py` | `src/ingestion/companion_documents.py` | Companion candidate, page-range, and table discovery | None in P0. | Beautiful Soup | `tests/test_table_discovery.py` |
| `scripts/diagnostics/diagnose_all_financial_tables.py` (`find_tables_in_financial_section`) | `src/ingestion/financial_section_locator.py` | `_candidate_start_snippets`, `_find_start_node`, `_resolve_toc_link_start`, `find_tables_in_financial_section` | Moved the reusable locator into the ingestion package; replaced stdout warning with module logging. Did not copy the one-off diagnostic runner or its local filing list. | Beautiful Soup, lxml | `tests/test_table_discovery.py` |
| `src/ingestion/table_discovery.py` | `src/ingestion/table_discovery.py` | Statement links, same-document interval, root-anchor and companion discovery | Imports the moved library locator instead of a diagnostic script. | Beautiful Soup, table extractor, companion documents | `tests/test_table_discovery.py` |
| `scripts/add_table_chunks.py` | `scripts/add_table_chunks.py` | `_can_attempt_table_discovery`, idempotent supplemental chunk append | Uses target config. | target config, ingestion modules | `tests/test_table_discovery.py` |
| `src/retrieval/embedder.py` | `src/retrieval/embedder.py` | `Embedder`, `resolve_torch_device`, Nomic document/query prefixes | Source revision is pinned in target settings and supplied by the embedding script. Added optional progress control for streaming evaluation batches; default behavior is preserved. | PyTorch, Sentence Transformers | `tests/test_embedder_revision.py`, `tests/test_synthetic_retrieval_smoke.py`, `tests/test_financebench_runner.py` |
| `src/retrieval/vector_store.py` | `src/retrieval/vector_store.py` | `VectorStore`, deterministic UUIDs, Qdrant collection/search/filter/payload methods | Added per-instance collection names and generic metadata payloads so benchmark collections are isolated from SEC data. Default collection remains unchanged; source data and Qdrant files are excluded. | `qdrant-client` | `tests/test_vector_store.py`, `tests/test_synthetic_retrieval_smoke.py` |
| `src/retrieval/retriever.py` | `src/retrieval/retriever.py` | `RetrievedChunk`, `Retriever` | `RetrievedChunk` supports PDF `doc_name` and zero-based page metadata while formatting human-facing pages one-based; score semantics are explicit. | Embedder, Qdrant store | Smoke test via `HybridRetriever`, `tests/test_financebench_retrieval_adapter.py` |
| `src/retrieval/hybrid_retriever.py` | `src/retrieval/hybrid_retriever.py` | `HybridRetriever.retrieve`, `retrieve_with_embedding`, `inspect`, BM25, RRF, cross-encoder | Preserved production and inspection paths separately. Added optional company grouping and switches for reranking and structured lookup; defaults preserve the prior production path. | rank-bm25, Sentence Transformers, retrieval modules | `tests/test_hybrid_retriever_inspect.py`, `test_hybrid_retriever_concurrency.py`, `test_hybrid_retriever_section_filter.py`, synthetic smoke, `tests/test_financebench_retrieval_adapter.py` |
| `src/retrieval/lexical_ladder.py` | `src/retrieval/lexical_ladder.py` | Lexical candidate generation and fingerprinted rules | None in P0. | Python standard library | `tests/test_lexical_ladder.py` |
| `src/retrieval/query_shaper.py` | `src/retrieval/query_shaper.py` | Deterministic retrieval query shaping and fingerprints | None in P0. | Python standard library | `tests/test_query_shaper.py` |
| `src/retrieval/structured_lookup.py` | `src/retrieval/structured_lookup.py` | Structured financial match parsing and ranking | None in P0. | Python standard library | `tests/test_structured_lookup.py` |
| `src/retrieval/chunk_loader.py` | `src/retrieval/chunk_loader.py` | Local/cloud retrieval payload loading | None in P0. | Qdrant payload types at runtime | `tests/test_chunk_loader.py` |
| `src/retrieval/canonical_json.py` | `src/retrieval/canonical_json.py` | `canonical_json_bytes` | None in P0. | Python standard library | `tests/test_index_manifest.py`, `test_embedding_generation.py` |
| `src/retrieval/index_manifest.py` | `src/retrieval/index_manifest.py` | Corpus/vector fingerprints, manifest build/validate/read/write | None in P0. | Python standard library | `tests/test_index_manifest.py`, `test_index_chunks.py` |
| `src/retrieval/embedding_generation.py` | `src/retrieval/embedding_generation.py` | Immutable generation build, validation, promotion | None in P0. | Python standard library, target retrieval integrity modules | `tests/test_embedding_generation.py` |
| `scripts/embed_chunks.py` | `scripts/embed_chunks.py` | Immutable embedding generation builder CLI | Uses target model and data settings. | Sentence Transformers, PyTorch, target config | Unit coverage through embedding-generation and revision tests. |
| `scripts/index_chunks.py` | `scripts/index_chunks.py` | `rebuild_index_with_manifest` and local indexing CLI | Uses target paths; no source collection is opened. | Qdrant, target retrieval integrity modules | `tests/test_index_chunks.py` |
| `configs/settings.py` | `configs/settings.py` | Retrieval/data setting concepts only | Replaced broad app configuration with a P0-specific Pydantic settings model; uses `SecretStr` for optional Qdrant credentials. | Pydantic Settings, python-dotenv | Exercised during settings-backed script/test imports. |
| `configs/tickers.py` | `configs/tickers.py` | Source ticker set and CIK overrides | None in P0. | Python standard library | SEC client/downloader tests |
| `configs/logging_config.py` | `configs/logging_config.py` | JSON and human-readable formatting | None in P0. | Python standard library | Not independently covered in P0. |
| `configs/offline_guard.py`, `tests/conftest.py`, `pytest.ini` | Same target paths | Hermetic test socket guard and marker policy | Kept default tests offline. | pytest | Entire P0 test suite |
| `requirements.txt` | `requirements.txt` | Compatible ingestion/retrieval dependency pins | Removed unused provider, FastAPI, report-generation and frontend-adjacent requirements. | Python packages listed in file | Test suite and import compilation |
| `LICENSE` | `LICENSE` | MIT license | Carried with reused source modules. | None | N/A |

The target suite is the focused source regression set plus the new synthetic
retrieval smoke. P1 adds `src/ingestion/pdf_ingestion.py`, pinned FinanceBench
acquisition and grouped split handling in `scripts/download_financebench.py`
and `src/evaluation/financebench_dataset.py`, the retrieval adapter and
page-level metrics in `src/evaluation/`, and the reproducible runner in
`scripts/run_financebench_retrieval.py`. The public data, extracted text,
embeddings, Qdrant index, predictions, and case-level failure lists remain
ignored local artifacts. P1's unit and full regression test results are
recorded with the phase report. API, generation, Agent, and frontend are later
roadmap phases.
