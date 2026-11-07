# FilingScope — Trustworthy Agentic RAG for Financial Document Intelligence

FilingScope is an AI engineering project for answering financial-document
questions with traceable evidence. It extends a working SEC filing retrieval
system with explicit evidence sufficiency, targeted retrieval, and claim-level
verification, then measures each addition against a reproducible benchmark.

The work is being delivered in phases. **P0–P3 are implemented:** the project
has an independent SEC ingestion and hybrid retrieval baseline, a reproducible
FinanceBench retrieval benchmark, a deterministic evidence sufficiency
decision layer, and bounded adaptive retrieval. Claim verification, the
research UI, and deployment are later phases.

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

## Evidence sufficiency decision (P2)

The decision layer maps a question into entity, metric, period, and operation
requirements, aligns retrieved evidence to those slots, checks provenance and
numeric consistency, then returns `ANSWER`, `RETRIEVE_MORE`, or `ABSTAIN` with
reason codes and evidence gaps. It does not use a single retrieval-score
threshold and does not generate an answer. On 15 fixed synthetic scenarios,
action and reason-code accuracy were both 100%; this controlled result is not a
general accuracy estimate. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and
[`docs/DECISION_EVALUATION.md`](docs/DECISION_EVALUATION.md).

## Adaptive retrieval (P3)

When P2 returns `RETRIEVE_MORE`, the bounded controller builds a targeted query
from the missing company, metric, and reporting period, calls the migrated
`HybridRetriever`, merges unique evidence with the initial chunks, and
reassesses. Query fingerprints, round/query limits, an evidence-token budget,
an elapsed-time budget, and coverage-progress checks stop repeated or
unproductive searches. On nine fixed synthetic scenarios, action and stop
reason accuracy were both 100%; both eligible multi-hop completion cases
resolved (2/2). These results are controlled checks, not a real-corpus success
estimate. The synchronous retriever's in-progress call cannot be interrupted
by the elapsed-time budget. See
[`docs/ADAPTIVE_RETRIEVAL_EVALUATION.md`](docs/ADAPTIVE_RETRIEVAL_EVALUATION.md).

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

## FinanceBench retrieval evaluation

P1 uses the public 150-case FinanceBench sample and the 84 reports referenced
by its cases. Documents and benchmark files are downloaded locally with pinned
source revisions and SHA verification. The raw dataset, PDFs, extracted text,
vectors, and run outputs are git-ignored. Dataset licensing, company-grouped
splits, evidence alignment, and metric definitions are documented in
[`docs/DATASET_PROTOCOL.md`](docs/DATASET_PROTOCOL.md) and
[`docs/EVALUATION_PROTOCOL.md`](docs/EVALUATION_PROTOCOL.md).

After installing requirements, acquire the benchmark and run all four
retrieval presets:

```powershell
python -m scripts.download_financebench
python -m scripts.run_financebench_retrieval
```

The presets are BM25, dense Qdrant, hybrid reciprocal-rank fusion, and hybrid
with cross-encoder reranking. They score retrieved document-page evidence; they
do not evaluate generated answers. Measured results and failure analysis are
published in [`docs/BENCHMARK_RESULTS.md`](docs/BENCHMARK_RESULTS.md) and
[`docs/FAILURE_ANALYSIS.md`](docs/FAILURE_ANALYSIS.md) after the full run.

P1's completed baseline found dense retrieval strongest on this sample
(Recall@10 0.4167; complete evidence-page coverage at 10 of 0.3733). Hybrid RRF
and hybrid reranking did not beat the dense baseline; the reranker improved
hybrid MRR@10 but increased latency. See the result and failure reports for
the full split metrics and limitations.

## Evaluation roadmap

| Phase | Scope | Status |
|---|---|---|
| P0 | Source audit, migration, independent retrieval smoke | Complete |
| P1 | FinanceBench acquisition, corpus coverage, retrieval baselines | Complete |
| P2 | Evidence requirements, coverage analysis, answer/retrieve/abstain | Complete |
| P3 | Bounded adaptive retrieval for explicit evidence gaps | Complete |
| P4 | Claim, citation, contradiction, and numerical verification | Planned |
| P5 | Controlled A0–A5 benchmark and failure analysis | Planned |
| P6 | Research UI, evidence inspector, deployment, and demo | Planned |

No answer quality or end-to-end agent performance claims are made by the
retrieval-only FinanceBench benchmark.

## Limitations

- FinanceBench retrieval evaluates the public 150-case sample, not the full
  10,231-case dataset.
- pypdf text extraction does not perform OCR; empty pages remain eligible and
  can reduce retrieval recall.
- Local SEC documents and Qdrant data are deliberately not included.
- The synthetic test validates code integration, not real-model quality.
- P2's synthetic decision evaluation validates fixed policy cases, not general
  decision accuracy or calibration. Independent labelled evaluation is planned
  for P5.
- P3's synthetic retrieval evaluation does not estimate FinanceBench multi-hop
  performance. Its elapsed-time budget is cooperative around synchronous
  retrieval calls.
- Claim verification, API, and frontend are still planned.

## License

MIT. See [LICENSE](LICENSE).
