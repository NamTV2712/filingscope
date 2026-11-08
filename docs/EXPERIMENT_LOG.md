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
  (completed below), then continue with M3. R4 and R6 remain later work.

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
- **Decision:** **KEEP** as current safety layer; **EXPERIMENT** with a separate
  labeled policy benchmark in M3.

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
- **Decision:** **KEEP** bounded behavior; **EXPERIMENT** against P5 evidence
  gaps after retrieval diagnostics.

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
  IDs and calibrated policy only with separate labels.

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
  M2 retrieval diagnostics, completed below. M3 candidate policy evaluation
  now follows.

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
  analysis. No fusion or reranker default changes. M3 is next.

## Planned experiments

Each planned experiment must add its exact hypothesis, baseline, changed
variable, dataset, configuration, result, latency/resource use, interpretation,
and decision before the change is promoted. The protocols are tracked in
`RETRIEVAL_RESEARCH.md`, `DECISION_CALIBRATION.md`, and
`RESEARCH_BACKLOG.md`.
