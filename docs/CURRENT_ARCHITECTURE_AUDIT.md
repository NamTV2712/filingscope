# Current architecture audit

Audit refreshed: 2026-11-12<br>
Branch: `main`<br>
Audited repository: `D:\Project\filingscope`<br>
Audited source commit: `91f3ee5a7cdfb6a4091b4360354bc764cc4b9eb3`<br>
Initial audit baseline: `956cef412d765395b5a7f0b773f821a58686a35a`

This refresh reflects P0–P5, M1 runtime compatibility, M2 retrieval
diagnostics, M3 candidate policy, M4 corpus-aware planning, M5 finite
complexity routing, M6's in-memory Evidence Ledger, M7's specialist graph
and narrow Company Facts path, M8's bounded filing fan-out, M9's
structured fact resolution, M10's PDF parser comparison, M11's atomic
verification and bounded release policy, M12's provenance-sensitive
retrieval benchmark, and M13's graph ablation and candidate-policy integration.
P0–P4 behavior and the
completed P5 provider benchmark remain preserved. Source benchmark data,
model caches, and generated run artifacts remain local and git-ignored.

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
- Candidate policy: `src/policy/` defines a versioned observation schema,
  deterministic `ACCEPT`/`WEAK`/`REJECT` rules, stable reason codes, backend
  protocols, and a separate synthetic benchmark. It is not yet called by the
  P5 A0–A5 evaluation pipeline.
- Evidence Ledger: `src/ledger/` provides a request-scoped in-memory blackboard
  linking requirements, tasks, evidence, facts, calculations, claims, and
  verification. Stable IDs and deterministic merge behavior are tested; there
  is no persistence or P5 integration.
- Corpus-aware planning: `src/research/` builds a metadata-only runtime Corpus
  Map and emits bounded, typed research tasks from question requirements.
  Missing versus unknown source states are kept explicit. The planner is not
  yet wired into the P5 answer path.
- Complexity routing: `src/agent/complexity_router.py` compiles a deterministic
  LangGraph with FAST, RESEARCH, and zero-budget UNSUPPORTED branches. It
  prepares bounded research plans. `src/agent/specialist_graph.py` executes
  those routes through finite FAST/RESEARCH/UNSUPPORTED paths, using typed
  specialist results and invocation-local runtime context. It remains outside
  the P5 path.
- Specialist execution: `src/agent/specialists.py` implements bounded filing,
  table, Company Facts, sufficiency, and Decimal reasoning workers. The graph
  registers evidence and claims in the M6 ledger and calls the P4 verifier.
  M9 binds SEC facts to the CIK, concept, currency, period and accession.
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
| Candidate policy | `DeterministicDecisionBackend.decide(features)` | Typed observations and hard rules; synthetic cases only; not integrated into P5. |
| Research planning | `QuestionOnlyPlanner.plan(question)` / `CorpusAwarePlanner.plan(question)` | Standalone M4 component; map is metadata-only and planner is not yet connected to a retriever or answer flow. |
| Complexity routing | `ComplexityRouter.route(question)` → `SpecialistResearchGraph.run(question)` | Deterministic M5 routing plus M7 finite execution; not integrated into P5. |
| Specialist graph | `SpecialistResearchGraph.run(question, request_id, route, ledger)` | RESEARCH supports concurrent filing searches with a compatible adapter. Answer quality remains unmeasured. |
| Evidence ledger | `EvidenceLedger` registration/add/merge/snapshot API | Request-scoped and in-memory; consumed by M7 workers, not persisted or consumed by P5. |
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
- P2/P3/P4 and M3 decision/verification accuracy is measured with small fixed
  synthetic scenario sets; those results are software behavior checks, not
  calibration or real-world decision accuracy.
- M4's 150-case BM25 planning comparison improved Recall@10 from 0.1133 to
  0.1567 overall and from 0.0889 to 0.1111 held-out. It remains below dense
  P1 Recall@10 of 0.4167; corpus-aware p95 BM25 latency was 1,051 ms. No answer
  generation was evaluated.
- M5's 56-case hand-authored route fixture has 100% rule agreement; it is not
  independently labeled. In the label-free 150-question run, the frozen map
  selected 36 FAST, 10 RESEARCH, and 104 UNSUPPORTED paths. Unknown metrics,
  incomplete periods, and unresolved companies remain common. No answer or
  agent quality was measured; see [`COMPLEXITY_ROUTING.md`](COMPLEXITY_ROUTING.md).
- M6's eight focused ledger tests cover stable IDs, idempotent/commutative
  merge, provenance aggregation, financial-fact deduplication, derived-fact
  input links, claim verification, and atomic conflict handling. This validates
  the data contract, not financial accuracy; see
  [`EVIDENCE_LEDGER.md`](EVIDENCE_LEDGER.md).
- M7's 20 focused tests cover SEC Company Facts request formatting, FAST and
  RESEARCH traces, zero-call UNSUPPORTED behavior, route budget accounting,
  table retrieval within remaining budget, evidence lineage, deterministic
  Decimal growth, and P4 verification. The SEC facts are authored fixtures;
  this is orchestration and contract coverage, not a quality or fact-accuracy
  benchmark. No live SEC or model call was made; see
  [`SPECIALIST_RESEARCH_GRAPH.md`](SPECIALIST_RESEARCH_GRAPH.md).
- The provider-backed P5 run had interrupted attempts before the completed
  run. Completed case outputs and reported usage are preserved; prior-run token
  usage was unavailable and is represented by a conservative upper bound.

## Technical debt

1. **Evidence identity and provenance.** M6 adds canonical metadata-only
   `EvidenceRecord`s and deterministic request-scoped merges, but snapshots do
   not persist. Source revision validity policy and cross-process storage are
   still missing.
2. **Policy integration.** M3 now centralizes candidate observations and
   decisions in a versioned schema, but callers must still supply features;
   there is no real-candidate feature observer or runtime adapter. P2
   sufficiency, candidate acceptance, and P4 claim verification remain separate
   decisions rather than one evidence-control flow.
3. **Financial facts.** M9 resolves standard Company Facts concepts, units,
   fiscal intervals and filing revisions. Company Facts is entity-wide.
   Custom taxonomy, segment facts and foreign exchange conversion need
   separate evidence. Historical date alignment without Submissions data
   uses conservative interval and filing-lag rules.
4. **Planning and routing.** M4 adds rule-based corpus-conditioned planning
   and M5 adds a deterministic FAST/RESEARCH/UNSUPPORTED router. Both are
   standalone; neither is integrated in P5. The route taxonomy still depends
   on the current company, metric, and period vocabulary, with 104/150
   FinanceBench questions routed unsupported under the map-aware run.
5. **Generation/verification.** The verifier splits answer text into clauses
   and creates local claim IDs. M6 can join request-scoped claims, calculation
   objects, and evidence IDs in memory, but P5 does not consume that ledger and
   no durable claim graph exists. Atomic semantic verification and a bounded
   correction pass do not exist.
6. **Decision calibration.** M3 has a 60-case hand-authored synthetic
   candidate benchmark. It is a policy contract check rather than external
   accuracy evidence. No probabilistic backend, measured Brier/ECE, or
   risk-coverage curve is implemented.
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
  but it does not use M6's in-memory ledger to carry IDs through reasoning
  and output, and no persistent ledger exists.

## Missing vertical integrations

- Evidence Policy Engine integration with a real-candidate observer and the
  end-to-end evaluation path;
- corpus-aware planner integration into the answer and retrieval path;
- evaluate FAST/RESEARCH answer quality and validate budget accounting against
  production adapters;
- persistence and P5 integration for the Evidence Ledger; connect the M3
  candidate policy into the runtime evidence path;
- broaden SEC company-facts/submissions support with concept, fiscal-period,
  unit, amendment, and restatement resolution;
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

## M2 validation update

The 150-case stage diagnostic replayed the frozen P1 corpus and matched BM25,
dense, hybrid, and hybrid-rerank top-10 chunk IDs on all 150 cases. Dense
Recall@10 / full evidence coverage@10 was 0.4167 / 0.3733, versus equal RRF at
0.3167 / 0.2600. Weighted RRF recovered some quality but remained below dense.
Dense candidate gold-page recall at 50 was 0.6989; union recall at 50 per
source was 0.7256. The reranker raised MRR at some pool sizes but not recall or
full-evidence coverage over dense.

Question-derived company and period filters improved dense retrieval on
eligible validation and held-out cases, but the same filters hurt RRF. CIK,
ticker, and form_type are absent from P1 metadata; section contains only the
generic value document. These filters remain opt-in diagnostics. Full split
metrics and latency/resource measurements are in
[`RETRIEVAL_DIAGNOSTICS_RESULTS.md`](RETRIEVAL_DIAGNOSTICS_RESULTS.md).

The full regression suite after M2 implementation passed with 203 passed and
3 skipped tests. The source and P1 result provenance are recorded in the
diagnostics report.

## M3 validation update

Policy v1.0.0 and a fixed 60-case candidate benchmark are implemented. On the
synthetic development/validation/held-out splits (24/18/18), policy disposition
and reason-code agreement were 100%, with 0% false acceptance and rejection.
The score-only baseline had 61.1% held-out accuracy, 16.67% false-accept rate,
and 83.33% false-reject rate. These fixture results do not estimate accuracy
on financial documents. No probability-producing backend was evaluated, so
Brier/ECE are not applicable. The policy is not wired into the P5 answer path.
See [`EVIDENCE_POLICY_EVALUATION.md`](EVIDENCE_POLICY_EVALUATION.md).

The full regression suite after M3 implementation passed with 227 passed and
3 skipped tests.

## M4 validation update

The standalone Corpus Map records 84 documents, 28,849 chunks, and 32 company
entities from the pinned P1 index. Company, filing-form, period, and section
metadata are complete. Ticker and CIK metadata are not indexed; table IDs are
not indexed and structured-table evidence is marked missing for this index;
XBRL coverage remains unknown. The planner receives questions and this map,
never benchmark labels. On 150 FinanceBench questions, corpus-aware planning
improved BM25 Recall@10 by 4.34 percentage points overall and 2.22 points
held-out. It marked all 10 synthetic absent-company probes missing and avoided
10 retrieval calls. Query count and p95 BM25 latency increased, so dense stays
the retrieval baseline and P5 integration is deferred. Peak incremental Python
allocation was 473,289,904 bytes; process RSS was not measured. See
[`CORPUS_AWARE_PLANNING.md`](CORPUS_AWARE_PLANNING.md).

The full regression suite after M4 implementation passed with 242 passed and
3 skipped tests.

## M5 validation update

M5 adds a finite LangGraph with a classifier and exactly one terminal path.
FAST uses a maximum of four graph steps, two retrieval calls, one LLM call,
10 candidate chunks, and 8,000 context tokens. RESEARCH allows eight steps,
six retrieval calls, three LLM calls, 50 candidates, and 24,000 context
tokens. UNSUPPORTED permits no downstream calls. Planned graph steps, tasks,
and retrieval calls are checked in this milestone; candidate, context,
concurrency, and execution-time enforcement belongs to the future execution
nodes.

The 56-case balanced synthetic fixture passed with 100% class agreement and no
path mistakes; hand-authored labels make this a behavior check only. On 150
unlabeled FinanceBench questions, map-aware routing selected 36 FAST, 10
RESEARCH, and 104 UNSUPPORTED paths versus 4/0/146 with the question-only
alias catalog. Actual retrieval, LLM, tool, and agent calls, token usage, and
cost were all zero. The map-aware route p50/p95 was 4.320/11.891 ms. Full
metrics and limitations are in [`COMPLEXITY_ROUTING.md`](COMPLEXITY_ROUTING.md).
The full regression suite passed with 247 passed and 3 skipped tests; `uv pip
check` reported no incompatible installed packages.

## M6 validation update

`src/ledger/` adds deterministic evidence/fact/calculation IDs and a mutable
request-scoped ledger that returns immutable, sorted snapshots. It enforces
requirement/task/evidence/calculation/claim/verification references, merges
duplicate retrieval discoveries without losing worker or retrieval provenance,
and stages merges so a conflict leaves the target ledger unchanged. Derived
calculations automatically create a `DERIVED_FACT` record linked to the
calculation and every ordered input evidence ID. LLM-generated text cannot be
registered as primary evidence. The ledger is not persistent and is not wired
to P5 or M5.

Eight focused ledger tests passed. The full regression suite passed with 255
passed and 3 skipped tests, and `uv pip check` reported no incompatible
packages. These are ledger/data-contract checks; no retrieval, answer-quality,
or financial-calculation accuracy benchmark was run.

## M10 validation update

M10 adds optional Docling ingestion and a structure-aware chunker for the
offline experiment. On ten known misses, Docling page-text Recall@10 was
0.60, structured Recall@10 was 0.55, and pypdf Recall@10 was 0.50. The
validation split scored 0.20 across all variants. The standard PDF path
uses pypdf. The full regression suite passed with 306 tests and 3 skips.
[M10 report](DOCUMENT_INTELLIGENCE.md)

## M11 validation update

The specialist graph now links atomic claim assessments to source evidence,
requested requirements and the reasoner's calculation records. It can revise
once and retains both assessments in the ledger. The controlled replay matched
16/16 claim-status sequences and 16/16 release decisions. The full suite passed
with 332 tests and 3 skips. [M11 report](ADVANCED_VERIFICATION.md)

## M12 validation update

M12 runs 24 hard-negative cases over the 28,849 frozen P1 chunks. Dense
beat BM25 in global Recall@10, while BM25 won more curated revision pairs.
Query-derived company, period and form filters improved overall recall but
excluded a valid quarterly filing and did not improve held-out recall. The
full suite passed with 335 tests and 3 skips. [M12 report](HARD_NEGATIVE_RETRIEVAL.md)

## M13 validation update

The specialist graph screens candidates with the M3 policy and shares the
planner's catalog through sufficiency and verification. The 24-case ablation
recovered three independently grounded answers in forced research with SEC
replay and one with smart routing. The routing variant used fewer calls and
missed two of the recovered answers. The full suite passed with 338 tests and
3 skips. [M13 ablation](ABLATION_STUDY.md)

## Next milestone

M14 completes the parent-child and context expansion comparisons and tests
advanced retrieval on fixed evidence. [Research agenda](RESEARCH_AGENDA.md)
