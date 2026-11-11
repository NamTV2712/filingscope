# FilingScope — Trustworthy Agentic RAG for Financial Document Intelligence

FilingScope is an AI engineering project for answering financial-document
questions with traceable evidence. It extends a working SEC filing retrieval
system with explicit evidence sufficiency, targeted retrieval, and claim-level
verification, then measures each addition against a reproducible benchmark.

The migrated baseline and P0–P4 evidence components are implemented. P5 now
adds a provider-backed A0–A5 FinanceBench end-to-end evaluation and an honest
failure report. Its results are weak: answer coverage is low, held-out numeric
exact accuracy is zero, and evidence-aware variants often abstain. That result
is preserved as a baseline for the research roadmap rather than presented as a
quality success. See [`docs/BENCHMARK_RESULTS.md`](docs/BENCHMARK_RESULTS.md).
M3 adds a deterministic candidate Evidence Policy Engine and a separate
60-case synthetic decision benchmark. Its results validate fixed policy
behavior only; they are not financial-document accuracy or calibration
results. See
[`docs/EVIDENCE_POLICY_EVALUATION.md`](docs/EVIDENCE_POLICY_EVALUATION.md).

M4 adds a metadata-only runtime Corpus Map and a bounded corpus-aware query
planner. On the fixed 150-case BM25 comparison it improved Recall@10 by 4.34
points overall and 2.22 points held-out, while increasing retrieval p95 to
1,051 ms. This remains a standalone research component: dense retrieval is
still the baseline, and no answer-quality gain was measured. See
[`docs/CORPUS_AWARE_PLANNING.md`](docs/CORPUS_AWARE_PLANNING.md).

The next work follows the research milestones in
[`docs/RESEARCH_AGENDA.md`](docs/RESEARCH_AGENDA.md). M5 now adds a finite
LangGraph router with FAST, RESEARCH, and UNSUPPORTED paths and explicit route
budgets. Its hand-authored 56-case behavior fixture passes, while the unlabeled
150-question FinanceBench pass shows 104 requests remain unsupported under the
current metric/period vocabulary. M7 adds a bounded specialist graph over the
existing retriever, a narrow official SEC Company Facts client, P2 sufficiency,
Decimal calculations, the M6 ledger, and P4 claim verification. Its hermetic
fixtures validate flow and budget contracts, not real-world answer accuracy;
it is not connected to P5. The target design separates a Research Plane from
an Evidence Control Plane that decides evidence acceptance, sufficiency,
verification, and answer release. A local evidence-first interface is a later
milestone. See [`docs/SPECIALIST_RESEARCH_GRAPH.md`](docs/SPECIALIST_RESEARCH_GRAPH.md).
**No cloud deployment is planned.**

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

## Claim and numerical verification (P4)

`ClaimLevelVerifier` maps answer clauses to entity, metric, period, value, and
canonical `[Source N]` references. It checks numeric facts only against the
corresponding cited chunks, recomputes percentage growth and period-to-period
differences with `Decimal`, detects contradictory cited values, and applies a
conservative evidence policy: verified, partial, rejected, or abstain. Topical
claims use lexical anchors and can miss valid paraphrases. The 15-case fixed
synthetic evaluation achieved 100% disposition agreement and 100% claim-status
agreement on 14 labeled claims. These controlled fixtures are not an answer
accuracy estimate for FinanceBench or real generated responses. See
[`docs/VERIFICATION_EVALUATION.md`](docs/VERIFICATION_EVALUATION.md).

## Local setup

Use Python 3.12 or newer. Install a CPU or CUDA PyTorch wheel appropriate for
the machine before installing the project requirements.

`requirements.txt` pins Transformers 4.57.6 because the pinned Nomic embedding
revision uses custom model APIs that are unavailable in Transformers 5. Re-run
the offline end-to-end preflight before changing this pin.

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
published in [`docs/RETRIEVAL_BENCHMARK_RESULTS.md`](docs/RETRIEVAL_BENCHMARK_RESULTS.md) and
[`docs/RETRIEVAL_FAILURE_ANALYSIS.md`](docs/RETRIEVAL_FAILURE_ANALYSIS.md).

P1's completed baseline found dense retrieval strongest on this sample
(Recall@10 0.4167; complete evidence-page coverage at 10 of 0.3733). Hybrid RRF
and hybrid reranking did not beat the dense baseline; the reranker improved
hybrid MRR@10 but increased latency. M2 stage diagnostics then confirmed that
the candidate union adds a small amount of recall while tested fusion and
reranking still trail dense. See the
[`M2 retrieval diagnostics`](docs/RETRIEVAL_DIAGNOSTICS_RESULTS.md) report and
the result/failure reports for full split metrics and limitations.

## End-to-end answer benchmark (P5)

P5 compares A0 dense retrieval, A1 hybrid retrieval, A2 reranked hybrid
retrieval, A3 evidence sufficiency decisions, A4 adaptive retrieval, and A5
claim verification. The full run uses the same 150 cases and pinned P1 corpus.
Gold answers stay in the evaluation layer and are never passed into the
generator. The raw per-case answers and metrics are written under the ignored
`data/financebench/e2e_runs/` directory.

First run the full local preflight. It loads the pinned P1 index, estimates the
provider request count and conservative token cost, makes no API calls, and
does not require an API key:

```powershell
python -m scripts.run_end_to_end_benchmark
```

After approving a maximum call count and spend cap, set `GROQ_API_KEY` only in
the local FilingScope environment and run with both limits:

```powershell
python -m scripts.run_end_to_end_benchmark `
  --provider-run `
  --max-provider-calls <preflight-count> `
  --max-cost-usd <approved-usd-cap>
python -m scripts.summarize_end_to_end_benchmark `
  data/financebench/e2e_runs/<run-id>/results.json
```

The answer generator uses Groq's `openai/gpt-oss-120b` model with one request
per generated variant, temperature zero, and a 1,024-token output cap. Frozen
price inputs and the 25% prompt-token estimation margin are recorded in the
run manifest. Modeled costs use reported tokens and the published [Groq model
rates](https://console.groq.com/docs/model/openai/gpt-oss-120b); they are not
provider invoices. Dry-run estimates are forecasts only and are never reported
as answer quality. The deterministic text metrics measure lexical agreement,
not semantic equivalence; numeric exactness, citation validity, and claim
support are reported separately.

The completed provider run generates
[`docs/BENCHMARK_RESULTS.md`](docs/BENCHMARK_RESULTS.md),
[`docs/ABLATION_STUDY.md`](docs/ABLATION_STUDY.md),
[`docs/FAILURE_ANALYSIS.md`](docs/FAILURE_ANALYSIS.md), and three SVG charts in
`docs/assets/`. See the
[`P5 evaluation protocol`](docs/END_TO_END_EVALUATION_PROTOCOL.md) for variant,
metric, leakage, and reproduction details.

## Evaluation roadmap

| Phase | Scope | Status |
|---|---|---|
| P0 | Source audit, migration, independent retrieval smoke | Complete |
| P1 | FinanceBench acquisition, corpus coverage, retrieval baselines | Complete |
| P2 | Evidence requirements, coverage analysis, answer/retrieve/abstain | Complete |
| P3 | Bounded adaptive retrieval for explicit evidence gaps | Complete |
| P4 | Claim, citation, contradiction, and numerical verification | Complete |
| P5 | Controlled A0–A5 benchmark and failure analysis | Complete |
| M1 | End-to-end retrieval, decision, adaptive retrieval, generation, and verification baseline | Complete as an offline evaluation path |
| M2 | Retrieval stage diagnostics | Complete; dense baseline retained |
| M3 | Candidate Evidence Policy Engine and independent decision benchmark | Complete; synthetic behavior benchmark only |
| M4 | Runtime Corpus Map and corpus-aware planner | Complete; standalone evaluation component |
| M5 | Finite complexity router and bounded FAST/RESEARCH/UNSUPPORTED routes | Complete; deterministic behavior fixture and unlabeled FinanceBench route distribution |
| M6 | Shared Evidence Ledger | Complete; in-memory typed records and deterministic merge |
| M7 | Bounded specialist research graph | Complete; sequential fixture path, no quality benchmark |
| M8 | Bounded parallel filing research | Complete. Simulated search p50 fell from 251 ms to 87 ms |
| M9 | SEC financial facts and filing revisions | Complete. 8/8 published fixture slots matched |
| M10–M14 | Document intelligence, verification, and retrieval research | Planned |
| M15 | Local evidence-first research UX | Planned; no deployment |

No answer quality or end-to-end agent performance claims are made by the
retrieval-only FinanceBench benchmark.

## Limitations

- FinanceBench retrieval evaluates the public 150-case sample, not the full
  10,231-case dataset.
- pypdf text extraction does not perform OCR; empty pages remain eligible and
  can reduce retrieval recall.
- Local SEC documents and Qdrant data are deliberately not included.
- The synthetic test validates code integration, not real-model quality.
- P2 and M3 use synthetic decision cases. M3's 60-case candidate benchmark
  verifies hand-authored rules and does not estimate general accuracy. There is
  no probability-producing backend or measured calibration result.
- P3's synthetic retrieval evaluation does not estimate FinanceBench multi-hop
  performance. Its elapsed-time budget is cooperative around synchronous
  retrieval calls.
- A persistent evidence ledger, SEC XBRL path, router/ledger integration into
  the answer path, retrieval/generation execution inside the research graph,
  production request API, and local research UI are not implemented yet.
- The current A0–A5 path is an offline evaluation pipeline, not a deployed
  application. Its strict evidence checks expose useful failure modes but do
  not yet produce useful coverage on much of the held-out sample.

## License

MIT. See [LICENSE](LICENSE).
