# FilingScope — Trustworthy Agentic RAG for Financial Document Intelligence

FilingScope is an AI engineering project for answering financial-document
questions with traceable evidence. It extends a working SEC filing retrieval
system with explicit evidence sufficiency, targeted retrieval, and claim-level
verification, then measures each addition against a reproducible benchmark.

The work is being delivered in phases. **P0 is implemented:** the project has an
independent SEC ingestion and hybrid retrieval baseline migrated from
`Enterprise_Document_QA`, with a synthetic Qdrant smoke test. FinanceBench,
answer generation, the evidence decision layer, adaptive retrieval, claim
verification, the frontend, and deployment are later phases and are not yet
implemented.

## P0 retrieval baseline

The migrated baseline includes:

- SEC EDGAR 10-K downloading and section extraction.
- Token-aware section chunking and financial statement table parsing.
- Nomic `nomic-embed-text-v1.5` document/query prefixes and a pinned revision.
- Qdrant dense search, BM25, query shaping, lexical candidates, reciprocal rank
  fusion, structured financial lookup, and the MS MARCO cross-encoder.
- Immutable embedding generation and index provenance manifests.
- Hermetic regression tests and a synthetic dense + lexical + reranking test.

The retrieval implementation is reused from the source project. P0 does not
include the source project's provider, generation, agent, API, or frontend
systems. See the [source audit](docs/SOURCE_CODE_AUDIT.md) and
[reuse matrix](docs/SOURCE_REUSE_MATRIX.md) for exact file-level provenance.

## Architecture

```text
SEC EDGAR 10-K HTML
        ↓
section extraction → token-aware chunks → supplemental financial tables
        ↓
pinned Nomic embeddings → immutable embedding generation → Qdrant index
        ↓
BM25 + dense Qdrant + lexical candidates → RRF → cross-encoder reranking
```

The `HybridRetriever.inspect()` method exposes a provider-free diagnostic
trace. It is not the production retrieval method and is not used to claim
retrieval accuracy. P0 has no benchmark dataset or measured retrieval scores.

## Local setup

Use Python 3.12 or newer. Install a CPU or CUDA PyTorch wheel appropriate for
the machine before installing the project requirements.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
# Install the PyTorch wheel for this machine (CPU or CUDA) before continuing.
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

For SEC downloads, set `SEC_USER_AGENT` in `.env` to the project name and a
contact email you control. Do not commit `.env`. Qdrant local mode is the
default and uses a single-process file lock. The application downloads model
weights when the real embedding and reranking models are first loaded; model
caches are not included in this repository.

Run the offline tests from the repository root:

```powershell
python -m pytest tests/ -q
```

The synthetic retrieval test uses deterministic test vectors and a temporary
Qdrant collection. It does not download models or contact external services.
To run the SEC ingestion scripts against the live SEC service, configure the
contact value first and run:

```powershell
python -m scripts.download_filings
python -m scripts.chunk_filings
python -m scripts.add_table_chunks
```

Embedding and indexing require the pinned model revision and additional local
compute:

```powershell
python -m scripts.embed_chunks --generation-id <new-generation-id>
# Set EMBEDDING_GENERATION_PATH to the completed generation in .env.
python -m scripts.index_chunks
```

## Evaluation roadmap

| Phase | Scope | Status |
|---|---|---|
| P0 | Source audit, migration, independent retrieval smoke | Complete |
| P1 | FinanceBench acquisition, corpus coverage, retrieval baselines | Next |
| P2 | Evidence requirements, coverage analysis, answer/retrieve/abstain | Planned |
| P3 | Bounded adaptive retrieval for explicit evidence gaps | Planned |
| P4 | Claim, citation, contradiction, and numerical verification | Planned |
| P5 | Controlled A0–A5 benchmark and failure analysis | Planned |
| P6 | Research UI, evidence inspector, deployment, and demo | Planned |

No FinanceBench scores or end-to-end answer quality claims are reported until
those experiments have been run on a verified corpus.

## Limitations

- Only SEC HTML ingestion is migrated. FinanceBench PDF ingestion is a P1 task.
- Local SEC documents and Qdrant data are deliberately not included.
- The synthetic test validates code integration, not real-model quality.
- Evidence decision, adaptive retrieval, claim verification, API, and frontend
  are not part of the current P0 baseline.

## License

MIT. See [LICENSE](LICENSE).
