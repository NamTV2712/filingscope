# M2 retrieval diagnostics — FinanceBench

## Status and reproducibility

M2 is complete for the metadata available in the frozen P1 corpus. The full
diagnostic run used all 150 FinanceBench cases: 60 development, 45 validation,
and 45 held-out. It replayed the same P1 corpus and index (28,849 chunks,
corpus fingerprint
sha256:9f45dcd8586fe1f52a8b5b48c0dfeeb201498c166f78b01a5a3acd6c00662c48).
The run made zero provider calls and reproduced P1's BM25, dense, hybrid, and
hybrid-rerank top-10 chunk IDs on all 150 cases.

The diagnostic code was committed as c0c887df6128e3720d68fac09b2f91adb5f74948.
Its source fingerprint is
7a560e304ac8f960266b5493754aa37ac8610d92845bf6e4c873f5d87ae27acf; the
working tree was clean. The ignored local output is
data/financebench/diagnostic_runs/m2-full-20261108/results.json and includes
per-case candidate IDs. Raw results remain outside Git under the research
data policy.

Reproduce the full run from the repository root:

    .venv\Scripts\python.exe -m scripts.run_retrieval_diagnostics --retrieval-run-dir data\financebench\runs\3ea92c895826e46ccf03ee52248771cc83e779e90b1660c390d29f2c4abfd18f --output-dir data\financebench\diagnostic_runs\m2-full-20261108

The diagnostic reused one embedding per question across filter profiles. It
compared BM25, dense, and lexical candidate rankings before fusion; equal RRF,
weighted RRF, dense-preserving fusion, and query-routed fusion; independent
candidate and final-k sweeps; and cross-encoder candidate pools of 10, 25, and
50. Metadata-filter metrics compare against unfiltered candidates on the same
queries where the filter value could be derived from the question and runtime
corpus metadata.

Runtime environment: Python 3.12.7, PyTorch 2.15.0 CPU build,
Sentence Transformers 5.6.0, Qdrant client 1.18.0, Windows 11 Home, Intel Core
i7-14650HX (16 cores, 24 logical processors), 16.9 GB visible system memory;
CUDA was unavailable. The run took 790 seconds wall time. An external monitor
sampled the diagnostic Python process once per second and observed a maximum
working set of 2,954,768,384 bytes (2.95 GB / 2.75 GiB); this is a sampled
maximum, not a guaranteed operating-system peak. No provider cost was incurred.

The retrieval model was nomic-ai/nomic-embed-text-v1.5 at revision
e9b6763023c676ca8431644204f50c2b100d9aab; the cross-encoder was
cross-encoder/ms-marco-MiniLM-L-6-v2 at revision
233902d25c440f23af6f7d6e94d2946bac0bee0a.

## Candidate recall before fusion

Gold-page recall is macro-averaged across questions. Full-evidence coverage is
the fraction of questions for which all annotated gold pages were present.
Each source was capped at 50 candidates; source union combines the top 50 from
each source before deduplication.

| Candidate source | Gold-page recall @10 | Gold-page recall @50 | Full-evidence coverage @50 |
|---|---:|---:|---:|
| BM25 | 0.1133 | 0.1800 | 0.1733 |
| Dense | **0.4167** | **0.6989** | **0.6733** |
| Lexical ladder | 0.0000 | 0.0000 | 0.0000 |
| Union of BM25, dense, lexical @50/source | — | 0.7256 | 0.7000 |

Dense is the strongest individual producer. The union recovers a modest number
of additional gold pages at candidate time, so fusion has some complementary
evidence available. The lexical ladder contributes no annotated gold page in
this cohort.

## Fusion and reranking

Recall@10 measures retrieved gold pages; Full evidence@10 requires all gold
pages for the question; MRR@10 measures first relevant page rank. The held-out
column is included to check whether aggregate changes carry to the fixed cohort.

| Variant | Recall@10 | Full evidence@10 | MRR@10 | Held-out Recall@10 | Held-out full evidence@10 |
|---|---:|---:|---:|---:|---:|
| Dense top 10 | **0.4167** | **0.3733** | **0.2496** | **0.4778** | **0.4222** |
| Equal RRF top 10 | 0.3167 | 0.2600 | 0.1315 | 0.3444 | 0.2667 |
| Weighted RRF top 10 (BM25 1, dense 2, lexical 0.5) | 0.3800 | 0.3267 | 0.1805 | 0.4222 | 0.3556 |
| Dense-preserving pool (reserve dense top 25) | 0.3667 | 0.3067 | 0.1837 | 0.3889 | 0.2889 |
| Route-aware RRF | 0.3800 | 0.3267 | 0.1805 | 0.4222 | 0.3556 |
| Cross-encoder, RRF pool 10 | 0.2533 | 0.2000 | 0.1718 | 0.3111 | 0.2444 |
| Cross-encoder, RRF pool 25 | 0.3200 | 0.2733 | 0.2018 | 0.3111 | 0.2667 |
| Cross-encoder, RRF pool 50 | 0.3100 | 0.2600 | 0.2044 | 0.2778 | 0.2222 |

Dense led on Recall@10 and full-evidence coverage in development, validation,
and held-out splits. Weighted RRF improved on equal RRF but remained below
dense in every split. Dense-preserving fusion also remained below dense. The
route-aware variant selected the dense-priority profile on all 150 questions,
so it was identical to weighted RRF; the filing-native phrase profile was not
exercised by this cohort.

The cross-encoder increased MRR versus equal RRF for pools of 25 and 50, but it
did not improve aggregate Recall@10 or full-evidence coverage over dense. A
reranker cannot recover gold pages that did not enter its candidate set.

## Independent pool sweeps

Candidate pool limits are varied independently while the other source limits
stay at 50. The source-pool rows report Recall@10 / full-evidence coverage@10
for the fused top 10. Fusion-pool changes do not change the selected top 10 in
this experiment.

| Variable | Setting | Recall at output k | Full evidence coverage at output k |
|---|---:|---:|---:|
| BM25 candidates | 10 | 0.3533 | 0.3067 |
| BM25 candidates | 25 | 0.3433 | 0.2933 |
| BM25 candidates | 50 | 0.3167 | 0.2600 |
| Dense candidates | 10 | 0.3567 | 0.3000 |
| Dense candidates | 25 | 0.3533 | 0.2933 |
| Dense candidates | 50 | 0.3167 | 0.2600 |
| Lexical candidates | 0 or 50 | 0.3167 | 0.2600 |
| Fusion output pool | 10, 25, or 50 | 0.3167 | 0.2600 |
| Cross-encoder candidates | 10 | 0.2533 | 0.2000 |
| Cross-encoder candidates | 25 | 0.3200 | 0.2733 |
| Cross-encoder candidates | 50 | 0.3100 | 0.2600 |
| Final k, equal RRF | 5 | 0.1933 | 0.1667 |
| Final k, equal RRF | 10 | 0.3167 | 0.2600 |
| Final k, cross-encoder pool 50 | 5 | 0.2367 | 0.1933 |
| Final k, cross-encoder pool 50 | 10 | 0.3100 | 0.2600 |

Smaller BM25 and dense candidate contributions improved the top-10 fused
metrics within the tested RRF configuration, but neither beat dense retrieval.
The 50-candidate source rankings remain useful for measuring upstream recall;
these results do not justify lowering production retrieval limits globally.

## Metadata routing

The P1 chunk metadata contains company on all 28,849 chunks (32 unique values),
reporting period on all chunks (10 years, 2015–2024), and doc_type on all
chunks (10-K, 10-Q, 8-K, Earnings). It has no CIK, ticker, or form_type fields.
Its only section value is document, so section filtering cannot narrow this
corpus. doc_type is used as the available form proxy. Qdrant array payloads
match when at least one array value satisfies a filter, and payload indexes
support efficient exact-match filtering; see the official
[Qdrant filtering documentation](https://qdrant.tech/documentation/search/filtering/)
and [payload indexing documentation](https://qdrant.tech/documentation/manage-data/indexing/).

Filter values came only from explicit company names, four-digit years, and form
phrases in the question, intersected with values present in the runtime corpus.
No gold company, period, form, or evidence labels were used as runtime filter
inputs. Baseline and filtered quality below use the same eligible cases.

| Dense filter profile | Eligible cases | Recall@10, baseline → filtered | Full evidence@10, baseline → filtered | Held-out Recall@10, baseline → filtered | Filtered inspect latency p50 / p95 |
|---|---:|---:|---:|---:|---:|
| Company | 128 | 0.4336 → 0.4727 | 0.3828 → 0.4219 | 0.4767 → 0.5000 (43 cases) | 509 / 702 ms |
| Reporting period | 132 | 0.4205 → 0.5303 | 0.3712 → 0.4773 | 0.4643 → 0.5119 (42 cases) | 681 / 953 ms |
| Company + period | 112 | 0.4420 → 0.5625 | 0.3839 → 0.5000 | 0.4756 → 0.5244 (41 cases) | 458 / 678 ms |
| Form (doc_type) | 2 | 0.5000 → 1.0000 | 0.5000 → 1.0000 | No held-out cases | 358 / 1,201 ms |
| Company + period + form | 1 | 0.0000 → 1.0000 | 0.0000 → 1.0000 | No held-out cases | 359 / 359 ms |

The dense period and company-plus-period profiles improved Recall@10 and full
evidence coverage on their eligible cohorts, including held-out cases. The form
profiles are too small for a quality claim. Applying the same metadata filters
to RRF reduced Recall@10 for company (0.3164 → 0.2461) and company-plus-period
(0.3259 → 0.2009); period-only filtering was a smaller gain (0.3220 → 0.3447).
Filtering is therefore a targeted dense-retrieval experiment, not a universal
hybrid-search improvement.

Filtered inspect latency includes the trace's BM25, dense, and lexical stages;
it is not a paired end-to-end answer latency. Stage p50/p95 on the unfiltered
trace was BM25 220/429 ms, dense 75/102 ms, query embedding 36/62 ms, and
lexical ladder 930/981 ms. Cross-encoder p50/p95 was 285/331 ms for 10 pairs,
701/806 ms for 25 pairs, and 1,413/1,616 ms for 50 pairs.

## Decisions and next work

- **KEEP** dense as the permanent retrieval baseline. No fusion or reranking
  variant beat it on held-out Recall@10 and full-evidence coverage.
- **ADAPT** query-derived company/period filters as an opt-in dense-only
  experiment. Their gains warrant a more focused, paired latency and error
  analysis before any production-path change.
- **DEFER** route-aware fusion until the router signal activates for a useful
  number of real questions; it selected the same dense-priority profile on all
  current cases.
- **EXPERIMENT** with RRF weight and candidate-pool choices only as baselines
  for later evidence-policy work. No default changes are justified.
- **DEFER** CIK and section routing until ingestion provides discriminative
  metadata; doc_type is the only available form proxy in P1.
- M3, the versioned Evidence Policy Engine and independent synthetic decision
  benchmark, is complete. M4's runtime Corpus Map and corpus-aware planner are
  now complete as a standalone evaluation component. Continue with M5 finite
  complexity routing. Hard-negative retrieval work remains M12; structural
  retrieval remains a later experiment.
