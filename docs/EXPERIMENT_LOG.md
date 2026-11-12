# Experiment log

The log separates software-contract checks from answer-quality evidence.
“Resource use” is recorded only where measured; blanks are not inferred.

## P1 — FinanceBench retrieval baseline

- **Hypothesis:** Dense, BM25, hybrid RRF, and hybrid reranking may have
  different evidence-page retrieval trade-offs.
- **Baseline / changed variable:** Compare BM25, dense, RRF, and reranking on
  identical FinanceBench questions and pinned corpus; retrieval method varies.
- **Dataset/config:** Public FinanceBench sample, 150 cases; pinned corpus and
  source revisions; see `EVALUATION_PROTOCOL.md`.
- **Result:** Dense is strongest, Recall@10 0.4167 and full evidence-page
  coverage@10 0.3733. Current hybrid and reranking do not beat dense.
- **Latency/resources:** Split/stage measurements are in
  `RETRIEVAL_BENCHMARK_RESULTS.md`; benchmark report is the source of exact
  values. Peak RAM was not recorded.
- **Interpretation:** Fusion may dilute dense candidates or pool composition
  may be weak; stage-level cause is unknown.
- **Decision:** **KEEP** dense baseline; run the R1–R3/R5 diagnostics in M2
  (completed below). R4 and R6 remain later work.

## P2 — Evidence sufficiency rules

- **Hypothesis:** Requirement slot coverage can select answer/retrieve/abstain
  without a single similarity threshold.
- **Baseline / changed variable:** Fixed deterministic policies evaluated on
  15 labeled synthetic scenarios.
- **Dataset/config:** `DECISION_EVALUATION.md`.
- **Result:** Action and reason-code accuracy 100% on these fixtures.
- **Latency/resources:** Provider-free; per-run resource usage not measured.
- **Interpretation:** Confirms expected rule behavior only; no calibration or
  real-corpus accuracy claim.
- **Decision:** **KEEP** as current safety layer; M3 adds a separate candidate
  policy benchmark. P2 remains the requirement-slot sufficiency path.

## P3 — Bounded adaptive retrieval

- **Hypothesis:** Targeting an explicit gap and reassessing can resolve eligible
  missing evidence while stopping within declared limits.
- **Baseline / changed variable:** Fixed synthetic cases and a Qdrant-backed
  integration fixture compare initial decision to adaptive rounds.
- **Dataset/config:** Nine synthetic scenarios; see
  `ADAPTIVE_RETRIEVAL_EVALUATION.md`.
- **Result:** Action/stop-reason accuracy 100%; 2/2 eligible multi-hop cases
  resolved on the fixed set.
- **Latency/resources:** No provider calls; synchronous retrieval cannot be
  interrupted mid-call by cooperative elapsed-time limit.
- **Interpretation:** Tests control flow, not FinanceBench success.
- **Decision:** **KEEP** bounded behavior; evaluate against P5 evidence gaps
  after corpus-aware planning and candidate-policy integration mature.

## P4 — Claim and numerical verification

- **Hypothesis:** Citation-scoped evidence matching and Decimal calculations
  can conservatively detect unsupported/contradictory claims.
- **Baseline / changed variable:** Fixed deterministic verifier scenarios.
- **Dataset/config:** 15 synthetic cases, 14 labeled claims; see
  `VERIFICATION_EVALUATION.md`.
- **Result:** 100% disposition agreement and 100% claim-status agreement on
  these fixtures.
- **Latency/resources:** Provider-free; no external resource use measured.
- **Interpretation:** Lexical topical checks may miss paraphrases; not a
  semantic benchmark.
- **Decision:** **KEEP** fail-closed baseline; **EXPERIMENT** with atomic claim
  IDs and separately labeled claim-support decisions in M11.

## P5/M1 — End-to-end A0–A5 benchmark

- **Hypothesis:** Adding evidence sufficiency, adaptive retrieval, and claim
  verification to retrieval plus generation will improve supported answers and
  expose failure modes.
- **Baseline / changed variable:** A0 dense, A1 hybrid, A2 reranked hybrid,
  A3 evidence gate, A4 bounded adaptive retrieval, A5 verification gate.
- **Dataset/config:** FinanceBench 150 cases, 60/45/45 development,
  validation, held-out; pinned P1 corpus; Groq `openai/gpt-oss-120b`, temperature
  0, up to 1,024 output tokens; full protocol in
  `END_TO_END_EVALUATION_PROTOCOL.md`.
- **Result:** Held-out coverage A0–A5: 44.4%, 35.6%, 40.0%, 0%, 0%, 0%; held-out
  numeric exact: 0% for all. A2 has the best held-out token F1 at 17.9%, which
  remains lexical. Replay parity with P1 is 100%. See `BENCHMARK_RESULTS.md`.
- **Latency/resources:** Held-out p95 components: A0 7,751 ms, A1 10,798 ms,
  A2 7,804 ms, A3 2,488 ms, A4/A5 4,067 ms. Run used 460 successful
  generations in 522 total authorized attempts; current completed-run reported
  usage estimate $0.354987. Combined conservative modeled maximum $0.720492
  under the approved $0.85 budget. These are modeled costs, not provider
  invoices. Peak RAM was not measured.
- **Interpretation:** Evidence gates abstain too frequently for useful coverage;
  no exact numeric answers were recovered. Retrieval-stage causes and missing
  requirement parsing likely need separate diagnosis. Do not describe M1 as an
  end-user quality win.
- **Decision:** **KEEP** all baselines and the negative result; **ADAPT** the
  integrated harness for regressions; the next experiment at that point was
  M2 retrieval diagnostics, completed below. M3 now adds a separate candidate
  policy contract and benchmark.

## M1 — Nomic embedding runtime compatibility

- **Hypothesis:** The pinned Nomic remote model needs a Transformers 4.x
  runtime; an unconstrained resolver can select a newer major version that
  breaks its custom model code.
- **Baseline / changed variable:** Transformers 5.22.2 failed in
  `NomicBertModel` with a missing `get_extended_attention_mask` method. Changed
  only the Transformers version to 4.57.6; kept the embedding model revision,
  corpus, retrieval configuration, and P1 artifacts fixed.
- **Dataset/config:** Full pinned FinanceBench sample (150 cases), local P1
  corpus/index, CPU PyTorch 2.15.0, Sentence Transformers 5.6.0, no provider
  calls. Run artifact: ignored local directory
  `data/financebench/e2e_runs/20261107T155925Z-4c0dcc3b2ef1`.
- **Result:** The 150-case dry run completed. Dense, hybrid, and hybrid-rerank
  replay each matched P1 for 150/150 cases. It planned 460 generation requests;
  zero were sent. Answer-quality metrics remained unmeasured. The forecast cost
  was $0.63396735 and is not a charge.
- **Latency/resources:** Approximately 10 minutes wall time on this CPU
  environment. Working set was observed at about 2.7 GiB mid-run; peak RAM was
  not recorded.
- **Interpretation:** The runtime pin restores the actual retrieval path
  without changing model weights or benchmark inputs. The dry run validates
  integration and replay parity, not answer quality.
- **Decision:** **ADOPT** `transformers==4.57.6`; require an offline preflight
  before changing the pin.

## M2 — Retrieval stage diagnostics

- **Hypothesis:** Dense outperforms hybrid because candidate producers fail to
  retrieve evidence, fusion dilutes useful candidates, pool settings are poor,
  metadata is underused, or reranking changes evidence order.
- **Baseline / changed variable:** Replayed P1 BM25, dense, equal-RRF, and
  hybrid-rerank top-10 results, then varied candidate source/pool sizes, RRF
  weights, dense-preserving fusion, query-derived metadata filters, and
  cross-encoder pool sizes while holding the 150 questions and P1 corpus fixed.
- **Dataset/config:** FinanceBench 150 cases (60/45/45 development,
  validation, held-out), 28,849 P1 chunks, candidate ceiling 50, final k 5/10,
  Nomic embedding revision `e9b6763023c676ca8431644204f50c2b100d9aab`,
  MiniLM cross-encoder revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`.
  Full metrics and command are in `RETRIEVAL_DIAGNOSTICS_RESULTS.md`; raw
  per-case artifact remains ignored local data.
- **Result:** Replay parity was 150/150 for BM25, dense, hybrid, and reranked
  hybrid. Dense Recall@10 / full evidence coverage@10 was 0.4167 / 0.3733;
  equal RRF was 0.3167 / 0.2600; weighted RRF was 0.3800 / 0.3267. Dense
  candidate recall at 50 was 0.6989; union recall at 50/source was 0.7256.
  Query-derived company-plus-period filtering improved dense Recall@10 from
  0.4420 to 0.5625 and full evidence coverage from 0.3839 to 0.5000 on 112
  eligible cases; held-out Recall@10 rose from 0.4756 to 0.5244. It reduced RRF
  Recall@10 from 0.3259 to 0.2009 on the same cases.
- **Latency/resources:** Zero provider calls. Full run wall time 790 seconds on
  Windows 11, Intel i7-14650HX, CPU-only PyTorch 2.15.0. Stage p50/p95: query
  embedding 36/62 ms, BM25 220/429 ms, dense 75/102 ms, lexical ladder
  930/981 ms. Cross-encoder p50/p95: 285/331 ms for 10 pairs, 701/806 ms for
  25 pairs, 1,413/1,616 ms for 50 pairs. One-second process sampling observed
  2,954,768,384 bytes maximum working set (2.95 GB decimal); this is a sampled
  maximum rather than an exact OS peak. Filter-profile latency is listed in
  the detailed report.
- **Interpretation:** Dense generates better candidates and preserves better
  top-10 evidence than the tested fusion paths. Weighted RRF improves over
  equal RRF but still loses to dense on every split. Metadata routing is
  promising for dense when exact company/period values occur in the question;
  available form cohorts are too small, CIK/ticker/form_type are absent, and
  section has one value. The route-aware profile did not activate on any case.
- **Decision:** **KEEP** dense as the permanent baseline; **ADAPT** the
  query-derived company/period filters as dense-only opt-in diagnostics;
  **DEFER** production filter promotion until paired latency and false-filter
  analysis. No fusion or reranker default changes. M4 was the next planned
  milestone and is now complete; see the M4 experiment below.

## M3 — Candidate Evidence Policy Engine

- **Hypothesis:** Typed alignment, support, provenance, revision, table,
  numeric-consistency, and contradiction observations with deterministic hard
  rules will avoid candidate false accepts that a semantic-score threshold
  cannot distinguish.
- **Baseline / changed variable:** Compared a semantic-relevance-only
  threshold against policy v1.0.0 with `ACCEPT`/`WEAK`/`REJECT` dispositions
  and reason codes. Score thresholds only demote candidates; categorical hard
  constraints cannot be overridden by high scores.
- **Dataset/config:** 60 hand-authored synthetic candidates (20 per
  disposition), development/validation/held-out 24/18/18, balanced per split.
  Both threshold choices use development only. This is not an independently
  annotated financial corpus. Full report:
  `EVIDENCE_POLICY_EVALUATION.md`.
- **Result:** Policy disposition and reason-code agreement were 100% on every
  split, with 0% candidate false-accept and false-reject rates on the fixtures.
  The score-only baseline's held-out accuracy was 61.1%, false-accept rate
  16.67%, and false-reject rate 83.33%. These values verify fixed rules, not
  real-document accuracy.
- **Latency/resources:** Policy-only p50/p95 0.0023/0.0030 ms across 60
  in-process calls; zero provider calls, tokens, or provider cost. Peak memory
  not measured. No probabilistic backend was evaluated, so Brier/ECE are not
  applicable.
- **Interpretation:** Typed hard constraints represent the synthetic
  wrong-entity/period/metric/provenance and support cases that a scalar score
  cannot represent. Labels and feature scenarios are hand-authored together;
  external financial-data validation is required before runtime promotion.
- **Decision:** **ADOPT** the deterministic schema and policy v1.0.0 as the
  candidate-decision contract; **EXPERIMENT** on independently annotated
  financial evidence before wiring into the P5 answer path. No Jev or other
  probabilistic backend is adopted. Code commit:
  `3ac21fed877627bbe93a61a0978b3b12d1a0856b`.

## M4 — Runtime Corpus Map and corpus-aware planning

- **Hypothesis:** A compact map of indexed companies, forms, periods, sections,
  and source coverage can improve query targeting and prevent searches for
  sources known to be absent, without passing evaluation labels to the planner.
- **Baseline / changed variable:** Deterministic question-only requirement
  extraction and query planning versus the same bounded planner conditioned
  on a frozen runtime Corpus Map. Both used the same BM25 scorer, corpus,
  top-50-per-task candidate rule, and top-10 final output.
- **Dataset/config:** 150 public FinanceBench questions with development,
  validation, and held-out splits of 60/45/45; frozen P1 generation
  `3ea92c895826e46ccf03ee52248771cc83e779e90b1660c390d29f2c4abfd18f`; 84
  documents and 28,849 chunks; `rank-bm25==0.2.2`. Only question strings reach
  either planner; gold document/page labels are read by the separate scorer.
  The evaluator uses the union of each task query's top-50 pages, so the
  candidate measure is not a single global 50-item cap. Full protocol and
  reproduction command are in `CORPUS_AWARE_PLANNING.md`.
- **Result:** Corpus-aware planning improved Recall@10 from 0.1133 to 0.1567
  overall and 0.0889 to 0.1111 on held-out cases. Candidate page recall over
  task top-50 unions increased from 0.1800 to 0.2389; full candidate evidence
  coverage increased from 0.1733 to 0.2267. For 128 cases with known source
  states, gold source-document target alignment was 128/128. Ten synthetic
  absent-company probes were marked missing, avoiding 10/10 baseline retrieval
  calls.
- **Latency/resources:** Planner p50/p95 was 1.047/1.422 ms for question-only
  and 1.939/2.669 ms for Corpus Map planning. BM25 p50/p95 was 223/490 ms and
  225/1,051 ms, respectively. Corpus Map load/build took 629 ms; evaluation
  took 95.0 seconds. Tracemalloc measured 473,284,499 bytes of peak incremental
  Python allocations; process RSS was not measured. Map serialized size was
  28,421 bytes. Zero provider calls, tokens, or estimated cost.
- **Interpretation:** Corpus conditioning improved this isolated BM25 planning
  comparison but increased mean retrieval calls from 1.01 to 1.21 and roughly
  doubled p95 BM25 latency. Its absolute Recall@10 of 0.1567 remains below
  dense P1 at 0.4167. No answer-generation quality was measured. Missing
  CIK/ticker and structured-table metadata remain explicit coverage gaps; XBRL
  remains unknown.
- **Decision:** **ADAPT** the Corpus Map and finite task contract as a standalone
  research component; **KEEP** dense retrieval as the baseline. Do not route
  P5 or claim an end-to-end quality gain yet. M5 should measure quality and
  budgets using this interface before integration. Source commit:
  `0be938d31cf3a76b5b0baa31023bd4354ce571a3`. Evaluation case-set SHA-256:
  `e73869cb631d51670f23afa38bfb2a47bd955b7c6e3e727663bea1fd856fc6cd`.

## M5 — Finite complexity routing

- **Hypothesis:** Deterministic complexity classes with separate finite route
  budgets can keep bounded lookups on FAST, send cross-entity/causal/broad
  requests to RESEARCH, and stop unsupported or predictive requests before
  downstream tools run.
- **Baseline / changed variable:** No finite route graph existed. The
  question-only alias catalog was compared with the same router initialized
  from the frozen M4 Corpus Map. A separate balanced synthetic fixture checks
  each decision rule. No worker, retrieval, generation, or answer path runs in
  this milestone.
- **Dataset/config:** 56 hand-authored questions, eight per each of seven
  classes; plus 150 unlabeled FinanceBench questions on the frozen P1 index
  `3ea92c895826e46ccf03ee52248771cc83e779e90b1660c390d29f2c4abfd18f` (84
  documents, 28,849 chunks), split 60/45/45. Only question strings reach the
  router. Synthetic fixture SHA-256:
  `f30f9c3554753c962bb98e870f859aa7acabfb40957918c21be1304fb5b8457d`;
  FinanceBench question-set SHA-256:
  `9fc32b9e6d789b7bb4b4ebcfd843c102dab5cc87ee6644e783ca9128674d6c96`.
  Full protocol and route tables are in `COMPLEXITY_ROUTING.md`.
- **Result:** The synthetic fixture had 100% class agreement and macro F1,
  zero unnecessary RESEARCH selections among its 32 expected non-research
  cases, zero incorrect FAST selections among 24 expected research cases, and
  zero unsupported-path errors. These are authored rule fixtures, not
  independent intent labels. On FinanceBench, question-only routing selected
  4 FAST / 0 RESEARCH / 146 UNSUPPORTED. Corpus Map-aware routing selected 36
  FAST / 10 RESEARCH / 104 UNSUPPORTED. The map moved 42 requests out of
  UNSUPPORTED, but 104 remain unclassified for execution; unknown metrics,
  insufficient period scope, and unresolved companies are the main reasons.
- **Latency/resources:** Question-only p50/p95 was 3.438/5.316 ms; map-aware
  p50/p95 was 4.320/11.891 ms. Router initialization took 14.404 ms for both
  configurations. The 1,811.6 ms evaluation measured 1,968,146 bytes of peak
  incremental Python allocation; process RSS was not measured. Loading the
  runtime map is excluded. Zero actual retrieval/tool/agent/provider calls,
  model tokens, and cost. Corpus-aware planning produced 68 planned queries;
  these were not executed.
- **Interpretation:** Corpus metadata makes more known companies routable,
  but class counts on unlabeled questions do not establish route correctness.
  The narrow metric/period vocabulary is a material limitation. Budget checks
  cover graph steps, planned tasks, and planned retrieval counts; the
  candidate, context, concurrency, and execution-time caps need enforcement
  inside later execution nodes. LangGraph is used for explicit typed state and
  finite conditional edges; no performance comparison against plain Python
  control flow was run.
- **Decision:** **ADOPT** the finite deterministic route contract as the M6
  entry point; **KEEP** unsupported requests at zero downstream budget and
  preserve dense retrieval. Do not claim answer-quality or multi-agent gains.
  Source commit `0fffebc0d5d0a6b88532e3c3b0969a9f3246509f`; source fingerprint
  `db6a2cadc922512bae188d6ced044c35c803c9a8f6febd33715d2f713f6c1f57`; the
  fingerprinted source tree was clean. No deployment performed.

## M6 — Shared Evidence Ledger

- **Hypothesis:** A request-scoped blackboard with stable source IDs and
  deterministic merge semantics lets later specialists share evidence and
  derived artifacts by reference while preserving provenance and refusing
  dangling or cross-request links.
- **Baseline / changed variable:** No shared request ledger existed. M6 adds
  immutable Pydantic records and an in-memory `EvidenceLedger`; it does not
  replace the P2 evidence analyzer, M3 candidate policy, P4 verifier, or call
  P5.
- **Dataset/config:** Eight focused tests cover stable evidence IDs, duplicate
  discoveries across retrieval methods/tasks, merge order and idempotency,
  atomic conflict rejection, fact deduplication, derived calculation/input
  links, generated claim/verification links, and invalid source/request
  rejection. This is a software contract suite, not a labeled quality set.
- **Result:** All eight focused tests passed. Duplicate source evidence
  coalesces while preserving worker, task, requirement, and retrieval
  observations. `DERIVED_FACT` records require a calculation and all ordered
  input evidence IDs. Facts, claims, and verification results retain their
  ledger links. Conflicting task IDs fail without partially changing the
  ledger. The full repository suite passed with 255 passed and 3 skipped.
- **Latency/resources:** No timing or memory benchmark was run; the ledger is
  currently an in-memory software contract. No external service, retrieval,
  model, provider, token, or cost usage.
- **Interpretation:** M6 establishes a referential boundary for later workers
  and preserves deterministic merge behavior. It does not establish the
  correctness of financial facts, arithmetic, source revision validity, or
  generated claims. Persistence, retention rules, and connection to P5 remain
  out of scope for this milestone.
- **Decision:** **ADOPT** the typed in-memory ledger API for M7 specialist
  contracts. **DEFER** persistence and answer-path integration until later
  execution and privacy requirements are defined. See the M6 validation in
  `CURRENT_ARCHITECTURE_AUDIT.md` for its source revision.

## M7 — Specialist Research Graph

- **Hypothesis:** A finite specialist sequence can connect current routing,
  retrieval, the request ledger, evidence sufficiency, supported arithmetic,
  report writing, and claim verification while enforcing route budgets.
- **Baseline / changed variable:** M5 only planned work and M6 only stored
  records. M7 adds sequential execution, invocation-local text storage,
  metadata-only ledger provenance, an optional official SEC Company Facts
  client path, and typed specialist receipts. P5 and the retrieval baseline
  are unchanged.
- **Dataset/config:** Authored fake-retrieval and fake-SEC fixtures. Twenty
  focused tests cover SEC request contracts, 4-node FAST, FAST growth,
  zero-call UNSUPPORTED, 8-node two-company RESEARCH, table retrieval under
  remaining route budget, evidence lineage, Decimal growth, and P4
  verification. Full suite: 263 passed, 3 skipped.
- **Result:** All focused and full-suite checks passed. The RESEARCH fixture
  retrieves 2023/2024 Company Facts for two companies, produces supported
  10% and 15% growth calculations, links each derived fact to its source
  evidence, and verifies the generated claims. This is deterministic fixture
  behavior, not real financial-answer accuracy.
- **Latency/resources:** No separate latency, memory, or cost benchmark was
  run. Runtime reports cooperative wall time and resource counters. Tests made
  no live SEC requests and no provider/model calls.
- **Interpretation:** M7 provides vertical orchestration and explicit
  specialist contracts over existing P2/P4 behavior. XBRL tag aliases,
  fiscal-period matching, and amendment selection remain narrow and must not
  be treated as general fact normalization. The graph is not wired into P5,
  M3 candidate policy is not applied, and there is no parallel execution.
- **Decision:** **ADOPT** the sequential graph as the base for M8. Keep
  unsupported requests at zero downstream budget. Continue to withhold any
  answer-quality claim until a labeled, real-document evaluation exists. See
  [`SPECIALIST_RESEARCH_GRAPH.md`](SPECIALIST_RESEARCH_GRAPH.md). Source
  commit: `eb3654113823240d93d043e714647f4b69f22910`.

## M8 — Parallel Research

- **Hypothesis** Independent blocking filing searches complete faster with
  bounded parallel execution.
- **Experiment** Six scoped queries, 40 ms simulated I/O per call and 20
  measured runs per concurrency setting after warmup. The settings varied
  only the concurrency cap.
- **Result** Peak concurrency rose from one to three. p50 fell from 250.85 ms
  to 87.44 ms and p95 fell from 251.65 ms to 87.89 ms. Both settings made
  six retrieval calls and zero model calls per request.
- **Decision** Adopt fan-out for adapters that support simultaneous retrieval.
  The fixture measures scheduling under simulated I/O. M13 will measure
  quality and end-to-end efficiency across research configurations.
  [Reproduction and limitations](PARALLEL_RESEARCH.md)

## M9 — Structured Financial Intelligence

- **Hypothesis** Original filing focus plus dates, period type and provenance
  can distinguish fiscal facts that share the same Company Facts FY and FP.
- **Experiment** Replay the M8 selector from `6dc25ff` and the M9 resolver on
  six Apple slots and eight ineligible rows. Check two additional Microsoft
  slots, a wrong CIK and revision/currency decisions with hermetic tests.
- **Result** Apple exact value and accession coverage rose from 5/6 to 6/6.
  The new resolver accepted zero of eight ineligible rows versus eight for
  M8. Both additional Microsoft facts matched. The wrong CIK was rejected.
- **Decision** Adopt the versioned selector and its explicit revision basis.
  The fixture results describe the sampled financial facts. [M9 report](FINANCIAL_FACT_ARCHITECTURE.md)

## M10 — Document Intelligence

- **Hypothesis** Native document structure can recover table semantics and
  improve retrieval on known PDF evidence misses.
- **Experiment** Compare pypdf layout, Docling ACCURATE page text and Docling
  section/table chunks over 226 pages and ten non-held-out dense misses.
  Hold the embedding model, questions, source corpus and ranking constant.
  Compare FAST and ACCURATE on five visually audited pages.
- **Result** Both parsers recovered 6/6 text rows and 5/5 reading-order
  sequences. Docling recovered 20/20 native header associations. Recall@10
  was 0.50 for pypdf, 0.60 for Docling page text and 0.55 for structured
  chunks. All three scored 0.20 on validation and 0.90 at 50 overall.
- **Decision** Keep pypdf as the default. Docling ACCURATE took 424.444 s
  and 3.80 GB peak working set, compared with 8.205 s and 97.2 MB for pypdf.
  [M10 reproduction, resource use and split metrics](DOCUMENT_INTELLIGENCE.md)

## M11 — Advanced Verification

- **Hypothesis** Atomic, source-local verification and one actionable
  correction improve the release decisions for compound or misleading drafts.
- **Experiment** Replay P4 and M11 over 16 fixed, hand-labeled drafts with
  identical evidence. Time 20 passes per case on CPU. Run the specialist
  path with a fake generator to check actual release and ledger lineage.
- **Result** Exact draft claim sequences and expected dispositions rose
  from 8/16 to 16/16. Four drafts were corrected in one pass each. p95
  rose from 2.211 ms to 6.376 ms, with zero model calls in the replay.
- **Decision** Adopt in the specialist graph and retain P4 for baseline
  comparisons. [M11 reproduction and limitations](ADVANCED_VERIFICATION.md)

## M12 — Financial Hard Negatives

- **Hypothesis** Relevant-looking filing passages create provenance errors
  that a random-negative test misses. Explicit query metadata may reduce
  company and period confusion.
- **Experiment** Compare dense, BM25 and dense with query-derived metadata
  on 24 questions, 35 audited negatives and 28,849 frozen P1 chunks.
- **Result** Dense pairwise accuracy was 42/42 on random controls and 35/42
  on curated comparisons. The mask increased Recall@10 from 0.5625 to 0.7083
  overall and left held-out Recall@10 at 0.75. It excluded a valid quarterly
  balance-sheet chunk. Dense p95 was 50.911 ms and masked p95 was 58.387 ms.
- **Decision** Retain unfiltered dense as the baseline. Preserve the mask as
  a research variant. [M12 resources, splits and categories](HARD_NEGATIVE_RETRIEVAL.md)

## M13 — Multi-Agent Ablation

- **Hypothesis** Corpus-aware tasks, specialist handoffs and structured
  facts can improve grounded answers. Smart routing may trade coverage for
  fewer calls.
- **Experiment** Run A0–A4 and B0–B5 on 24 fixed questions, a shared P1
  index, the deterministic report writer and nine SEC snapshots.
- **Result** B4 returned three exact grounded answers and B5 returned one.
  B5 reduced retrieval calls per case from 1.792 to 0.917 and p95 from
  260.433 ms to 170.972 ms. Both released zero unsupported answers.
- **Decision** Adopt candidate screening and catalog consistency. Preserve
  both graph modes and use the observed table and fiscal failures in later
  experiments. [M13 provenance and resources](ABLATION_STUDY.md)

## M14 — Advanced Retrieval

- **Hypothesis** Parent context can restore missing table headers. Late
  interaction and provenance graph cues can improve ranking within a fixed
  dense candidate pool.
- **Experiment** Replay the 24 M12 queries and P1 source pages. Compare
  three context sizes under a fixed cap, audit 14 annual slots, and rerank
  50 dense candidates per question with neural and graph variants.
- **Result** Full parent expansion lowered held-out recall from 0.7500 to
  0.6250. Annual column pairing recovered 11/14 audited values versus 0/14.
  PageRank led overall Recall@10 at 0.8333. The dual-level graph led
  nDCG@5 at 0.5647. ColBERT improved Recall@10 to 0.8056 and local Qdrant
  returned the same rankings with higher added latency.
- **Decision** Keep dense as the default. Retain the improved rankers and
  source-column audit as opt-in research. [M14 scope and resources](ADVANCED_RETRIEVAL.md)

## M15 — Local Research Workspace

- **Hypothesis** The specialist contracts can expose the basis of an answer
  or abstention through an allowlisted event stream and evidence links.
- **Experiment** Connect the graph to the browser using frozen P1 and SEC
  artifacts. Exercise two SEC-supported Apple answers, a Best Buy lookup
  with filing retrieval, a missing period and an unsupported request.
- **Result** Three verified answers and two withheld cases matched the
  expected outcomes. The five warm graph runs took approximately 1–118 ms
  with zero LLM calls. Chromium verified the evidence views, keyboard
  navigation and retry on desktop and phone widths.
- **Decision** Adopt the local workspace using the existing runtime
  dependencies. [Reproduction and limitations](LOCAL_RESEARCH.md)

## Completion evaluation

- **Experiment** Replay all six control-plane decisions on their authored
  labels. Apply four release thresholds to fixed M13 results and score
  independent grounded exactness among released responses.
- **Result** All six fixture gates matched expected labels. A1's risk
  remained 100% as the release threshold reduced coverage from 17/24 to
  3/24. B4 released 3/24 with zero grounded-exact errors and B5 released 1/24.
- **Decision** Retain the decision replay as a regression check and the
  risk-coverage points as a small-cohort comparison. [Audit and reproduction](SPECIFICATION_AUDIT.md)

## Planned experiments

Each planned experiment must add its exact hypothesis, baseline, changed
variable, dataset, configuration, result, latency/resource use, interpretation,
and decision before the change is promoted. The protocols are tracked in
`RETRIEVAL_RESEARCH.md`, `DECISION_CALIBRATION.md`, and
`RESEARCH_BACKLOG.md`.
