# Specification completion audit

The M1–M15 sequence was developed on `main` and validated before each
milestone push. The source and documentation commits are recorded in
[implementation progress](IMPLEMENTATION_PROGRESS.md).

## Milestone evidence

| Milestone | Verified deliverable | Evidence |
| --- | --- | --- |
| M1 | Reproducible P5 path from frozen retrieval through sufficiency, adaptive retrieval, generation and claim verification. The compatibility fix restored all 150 P1 retrieval replays. | [Initial architecture audit](CURRENT_ARCHITECTURE_AUDIT.md), [P5 results](BENCHMARK_RESULTS.md) |
| M2 | Candidate recall, RRF/fusion, pool sizes, available metadata filters, and cross-encoder comparisons on 150 questions. Dense remained the strongest measured default. | [Retrieval stage diagnostics](RETRIEVAL_DIAGNOSTICS_RESULTS.md) |
| M3 | Versioned ACCEPT/WEAK/REJECT policy over explicit observations, deterministic backend, score-only comparator and 60 candidate fixtures. | [Policy contract](EVIDENCE_POLICY_ENGINE.md), [Candidate benchmark](EVIDENCE_POLICY_EVALUATION.md) |
| M4 | Metadata-only Corpus Map and scoped tasks. Question-only and corpus-aware planning compared on 150 questions. | [Planning evaluation](CORPUS_AWARE_PLANNING.md) |
| M5 | Finite FAST, RESEARCH and zero-tool UNSUPPORTED routes. Route classification checked on 56 authored fixtures and profiled on 150 FinanceBench questions. | [Routing evaluation](COMPLEXITY_ROUTING.md) |
| M6 | Request ledger linking requirements, tasks, source records, financial facts, calculations, claims and checks. Replay covers provenance, deterministic merging and atomic conflict handling. | [Ledger contract](EVIDENCE_LEDGER.md) |
| M7 | Bounded specialist workflow with filing, table and SEC workers, sufficiency, Decimal reasoning, report writing and verification. | [Graph validation](SPECIALIST_RESEARCH_GRAPH.md) |
| M8 | Bounded filing fan-out and deterministic merge with worker-specific task packets, budgets and receipts. Six simulated calls per variant. | [Concurrency comparison](PARALLEL_RESEARCH.md) |
| M9 | SEC concepts, fiscal intervals, units, accession lineage and revision selection. Eight published fixture slots matched. | [Fact validation](FINANCIAL_FACT_ARCHITECTURE.md) |
| M10 | pypdf and Docling page and table experiments on five PDFs. pypdf stayed the default. | [Document experiment](DOCUMENT_INTELLIGENCE.md) |
| M11 | Atomic claim graph with source and numeric checks and at most one actionable correction. Expected release matched on all 16 authored replay cases. | [Verification replay](ADVANCED_VERIFICATION.md) |
| M12 | Five categories of provenance hard negatives across 24 questions and a frozen 28,849-chunk corpus. | [Provenance benchmark](HARD_NEGATIVE_RETRIEVAL.md) |
| M13 | A0–A4 and B0–B5 on common questions, splits and sources. Forced research recovered three grounded answers and smart routing recovered one. | [Ablation results](ABLATION_STUDY.md) |
| M14 | Parent-page expansion, annual table alignment, pinned cross-encoder, ColBERT/NumPy/Qdrant and three provenance graph adaptations. | [Advanced retrieval results](ADVANCED_RETRIEVAL.md) |
| M15 | Local streamed research, six evidence views, claim-linked source inspection and actionable abstention. Five API cases and two Chromium viewport checks passed. | [Workspace and reproduction](LOCAL_RESEARCH.md) |

## Cross-cutting requirements

| Specification | Verification |
| --- | --- |
| A, AA, AC | Initial repository audit, preserved baseline history, milestone commits, and one local branch pushed to `origin/main`. |
| B, C, E–H, K | The research plane shares bounded task receipts and source IDs. The independent candidate gate, sufficiency analyst and final verifier govern evidence release. Filing retrieval, table inspection and Company Facts feed the same request ledger. |
| D | The optional backend protocol and calibration metrics are implemented. The deterministic policy and score-only comparator are measured. The external probabilistic backend was deferred. |
| I, J | R1–R7 runs cover the frozen corpus and selected parser cases. CIK and section filtering have recorded applicability limits on P1. |
| L–O | SEC provenance and Decimal derivations reach the final verification gate. The historical P5 slice and M13 A3/A4/B0 exercise gap-targeted adaptive retrieval. The local specialist path checks filing, structured and table evidence within its route, then may withhold an answer. |
| P–R, AB | Independent filing work has per-assignment limits and the supervisor uses metadata receipts. The report writer is the model-context consumer and has a route-specific input cap. The specialist result records provider input/output, retained evidence tokens and tool calls. FAST and RESEARCH profiles accept validated caller configuration. |
| S | Local answer, sources, coverage, calculations, verification and trace, with public lifecycle events and evidence links. |
| T, V | FinanceBench remains pinned. Separate hard-negative labels and grouped ablations include lookup, numeric, comparative, multi-document, multi-company, multi-hop, unanswerable, contradiction and prompt-injection cases. Runtime inputs exclude evaluation labels. |
| U, W | Independent decision replay and risk-coverage thresholds below. The milestone reports record retrieval, provenance, decision, answer, routing, abstention and resource metrics. |
| X, Y, Z | Research source decisions, experiment reports and reproducible commands are linked from the [research agenda](RESEARCH_AGENDA.md) and [source review](OPEN_SOURCE_RESEARCH.md). |

## Decision benchmark

The runner replays the existing M5, M3, P2 and M11 fixtures through their
current deterministic components. Expected labels come from the authored
fixtures. The replay keeps these decisions independent of generated answer
accuracy. The two P2 rows below reuse the same 15 evidence bundles.

| Gate | Positive label | Cases | True positive | True negative | Accuracy / precision / recall | False accept / false reject |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ShouldRetrieve | Supported initial route | 56 | 48 | 8 | 100% / 100% / 100% | 0% / 0% |
| CandidateAccept | Full ACCEPT | 60 | 20 | 40 | 100% / 100% / 100% | 0% / 0% |
| EvidenceSufficient | Complete consistent slots | 15 | 2 | 13 | 100% / 100% / 100% | 0% / 0% |
| ShouldRetrieveMore | Evidence gap with budget | 15 | 9 | 6 | 100% / 100% / 100% | 0% / 0% |
| ClaimSupported | Supported atomic claim before correction | 19 | 10 | 9 | 100% / 100% / 100% | 0% / 0% |
| ShouldAbstain | Final answer withheld | 16 | 7 | 9 | 100% / 100% / 100% | 0% / 0% |

The in-process replay took 169 ms and used zero retrieval and LLM calls.
The labels were written for behavior checks. Real-filing generalization
and probabilistic calibration remain unmeasured by this replay.

## Risk and coverage

The runner applies four nested release thresholds to each frozen M13
variant, overall and by split. Coverage is released responses divided by
cases. Risk is responses that fail the independent grounded-exact check
divided by released responses. An empty release set has undefined risk.
The release thresholds use the recorded verifier disposition, and the
grounded answer labels are used for scoring.

| Variant, overall | All rendered coverage / risk | Partial or verified | Verified only | Withhold all |
| --- | ---: | ---: | ---: | ---: |
| A0 dense writer | 15/24 · 100% | 0/24 · — | 0/24 · — | 0/24 · — |
| A1 filtered dense writer | 17/24 · 100% | 5/24 · 100% | 3/24 · 100% | 0/24 · — |
| B4 forced research | 3/24 · 0% | 3/24 · 0% | 3/24 · 0% | 0/24 · — |
| B5 smart route | 1/24 · 0% | 1/24 · 0% | 1/24 · 0% | 0/24 · — |

A1's stricter verification threshold cut coverage while the released
answers still failed independent provenance and value checks. B4 and B5
released fewer responses and had no grounded-exact errors among those
releases. The M13 comparison documents 18 and 20 false abstentions among
21 answerable questions, respectively. These are discrete operating points
on a small cohort.

## Final validation

Completion source `3c55a2bc1393d327fba26a0b7e666cd791907e44` passed 349
tests, with 3 skipped tests for unavailable local raw-filing fixtures.
Python compilation, JavaScript syntax, and Git whitespace checks passed.
The local completion report had SHA-256
`d0abedbe91962fe5b1f063676b073bb068c8cba33d84f5e250df72798520497c`.
The input hash matches the published [M13 artifact](ABLATION_STUDY.md#reproduce-m13).

```powershell
uv run --offline python -m scripts.run_completion_evaluation --output .local/completion-evaluation.json
uv run --offline python -m pytest -q -rs
```

The project was never deployed during this work.
