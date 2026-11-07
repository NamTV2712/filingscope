# Current architecture audit

Audit refreshed: 2026-11-07<br>
Branch: `main`<br>
Audited repository: `D:\Project\filingscope`<br>
Audited commit: `9b87e6b5b2d93350058e98d8922aea76fb802a5a`<br>
Initial audit baseline: `956cef412d765395b5a7f0b773f821a58686a35a`

This refresh reflects the committed P0–P5 repository plus an M1 runtime
compatibility check. P0–P4 behavior and the completed P5 provider benchmark
remain preserved. Source benchmark data, model caches, and generated run
artifacts remain local and git-ignored.

## Existing capabilities

- SEC filing ingestion: `src/ingestion/sec_client.py`,
  `section_extractor.py`, `chunker.py`, financial table discovery/extraction,
  and companion-document handling.
- PDF page extraction for FinanceBench with page provenance:
  `src/ingestion/pdf_ingestion.py`.
- Retrieval: pinned Nomic embeddings, embedding generation manifests,
  Qdrant vector storage, BM25, dense retrieval, lexical fallback, reciprocal
  rank fusion, optional MS MARCO reranking, query shaping, and structured table
  lookup under `src/retrieval/`.
- Evidence sufficiency: `src/decision/` extracts entity, metric, period, and
  operation requirements, maps evidence to those slots, reports gaps and
  conflicts, and selects `ANSWER`, `RETRIEVE_MORE`, or `ABSTAIN`.
- Bounded adaptive retrieval: `src/agent/adaptive_retrieval.py` targets gaps,
  deduplicates chunks and queries, and enforces round, query, token, and
  cooperative time budgets.
- Claim/citation/numerical verification: `src/verification/` validates
  canonical citations, maps claims to evidence, detects contradictions, and
  recomputes supported financial operations with `Decimal`.
- Generation and evaluation: `src/generation/` contains a provider-agnostic
  answer interface plus a Groq adapter; `src/evaluation/` includes P1
  retrieval metrics and the P5 A0–A5 pipeline, lexical/numeric answer metrics,
  cost estimates, and restartable provider checkpoints.
- P1 measures retrieval on the public 150-case FinanceBench sample. P5 joins
  frozen retrieval artifacts to decision, adaptive retrieval, generation, and
  verification. Per-case predictions and corpus artifacts stay local.

## Current interfaces

| Boundary | Current interface | Important limitation |
|---|---|---|
| Retrieval | `Retriever.retrieve(query, top_k)` and `HybridRetriever.retrieve(...)` | Evidence is a mapping/chunk; no shared policy-owned candidate record yet. |
| Retrieval inspection | `HybridRetriever.inspect(...)` | Diagnostic only; not an answer-quality result. |
| Decision | `EvidenceDecisionLayer.assess/decide(question, chunks, budget)` | Deterministic slot coverage, not calibrated probability or general semantic support. |
| Adaptive retrieval | `AdaptiveRetrievalController.run(question, initial_chunks, budget)` | One bounded flow over the existing retriever; no planner/corpus map. |
| Generation | `AnswerGenerator.generate(question, evidence_chunks)` | Provider call is not itself the evidence authority. |
| Verification | `ClaimLevelVerifier.verify(question, answer, evidence_chunks)` | Lexical topical anchors and deterministic number parsing can miss paraphrases or valid facts. |
| P5 evaluation | `EndToEndBenchmark.run()` | Offline batch harness; no request API, persistent ledger, or UX. |

## Benchmark evidence and weaknesses

- P1 dense retrieval is the strongest measured retrieval configuration on this
  pinned sample: Recall@10 0.4167 and full evidence-page coverage@10 0.3733.
  Current RRF and reranking do not beat it. See
  [`RETRIEVAL_BENCHMARK_RESULTS.md`](RETRIEVAL_BENCHMARK_RESULTS.md).
- P5 covers 150 cases with development, validation, and company-grouped held-out
  splits (60/45/45). Held-out A0/A1/A2 answer coverage is 44.4%/35.6%/40.0%;
  A3/A4/A5 coverage is 0%. Held-out numeric exact is 0% for all six variants.
- P5 text exact and token F1 are lexical metrics, not semantic grading.
  Abstention correctness uses annotated evidence-page coverage as a proxy, and
  alternate evidence pages can be valid. A small held-out sample cannot support
  broad accuracy claims.
- P5 reuses a small public benchmark and an existing P1 corpus. It does not yet
  include hard-negative annotations, prompt-injection cases, multi-company
  comparative cohorts, or cross-document provenance labels.
- P2/P3/P4 decision and verification accuracy is measured with small fixed
  synthetic scenario sets; those results are software behavior checks, not
  calibration or real-world decision accuracy.
- The provider-backed P5 run had interrupted attempts before the completed
  run. Completed case outputs and reported usage are preserved; prior-run token
  usage was unavailable and is represented by a conservative upper bound.

## Technical debt

1. **Evidence identity and provenance.** Chunks carry document/page fields, but
   there is no canonical `EvidenceRecord`, request-scoped ledger, source
   revision policy, or deterministic cross-path merge contract.
2. **Policy boundary.** P2 sufficiency and P4 claim verification each use
   related extractors/parsers, but candidate acceptance features (source
   authority, filing/form alignment, table integrity, revision validity) are
   not centralized or versioned as a policy schema.
3. **Financial facts.** Table extraction exists; SEC XBRL facts do not. There
   is no tag drift, duration/instant, unit, accession, amendment, or
   restatement-aware fact model.
4. **Planning and routing.** Requirements are recognized by rule-based aliases
   and period parsing. There is no corpus map, complexity/cost router,
   corpus-conditioned decomposition, or specialist task interface.
5. **Generation/verification.** The verifier splits answer text into clauses
   and creates local claim IDs, but no durable claim graph joins claims,
   calculation objects, and evidence IDs. Atomic semantic verification and a
   bounded correction pass do not exist.
6. **Decision calibration.** No labelled decision-point benchmark, probabilistic
   backend, Brier score, expected calibration error, or risk-coverage curve is
   implemented.
7. **Application surface.** There is no user request API or local research UI.
   Trace events, evidence coverage, calculations, and an inspectable “why this
   answer” view remain planned. No cloud deployment is in scope.

## Duplicated or adjacent concepts

- `src/decision/requirement_extractor.py` and the P4 claim draft logic both
  identify entities, metrics, periods, and financial values. They share some
  parsing utilities but do not emit one canonical requirement/claim graph.
- P1 `structured_lookup.py` and P2 `period_value_parser.py` both interpret
  financial rows and periods for different purposes; neither is an XBRL fact
  resolver.
- P5 maps chunk IDs from frozen retrieval results back to chunk text and calls
  decision and verification independently. The result is auditable per case,
  but there is no persistent ledger to carry IDs through reasoning and output.

## Missing vertical integrations

- versioned Evidence Policy Engine and independent decision benchmark;
- runtime Corpus Map and corpus-aware planner;
- explicit FAST/STANDARD/DEEP complexity routing and budget profiles;
- shared Evidence Ledger and specialist task/result contracts;
- SEC company-facts/submissions path with provenance and fiscal normalization;
- deterministic calculation objects consumed by the report writer;
- document parser comparison (Docling vs current pypdf) on known failures;
- multi-agent and route ablations; local evidence-first research UI.

## M1 validation update

The A0–A5 path connects frozen retrieval evidence to deterministic sufficiency,
bounded adaptive retrieval, generation, and claim verification. Regression
validation in the isolated project environment completed with 196 passed and
3 skipped tests.

The 150-case no-provider preflight initially failed when dependency resolution
selected Transformers 5.22.2: the pinned Nomic remote model raised an
`AttributeError` for `get_extended_attention_mask`. `requirements.txt` now pins
Transformers 4.57.6. With that pin, the full preflight completed; A0, A1, and
A2 retrieval replay each matched all 150 frozen P1 results. The dry run planned
460 generation requests, made zero provider calls, and correctly marked answer
quality as unmeasured. Its conservative modeled cost forecast was $0.63396735;
this is not a provider charge. The generated run remains in ignored local data.

The completed provider-backed P5 results remain the answer-quality baseline:
held-out answer coverage is 44.4%/35.6%/40.0% for A0–A2 and 0% for A3–A5;
numeric exact accuracy is 0% for all variants. The compatibility check does
not replace or retune those results.

## Next milestone recommendation

M1 is validated. Continue with M2 by measuring candidate recall before fusion,
fusion-stage survival, pool-size sensitivity, metadata filter effects, and
reranker changes against the preserved dense baseline. The experiment sequence
is in [`RETRIEVAL_RESEARCH.md`](RETRIEVAL_RESEARCH.md).
