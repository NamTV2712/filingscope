# FilingScope research agenda

## Objective

Build an evidence-controlled financial research system. Research components
may discover and summarize information; deterministic policy remains the final
authority for provenance, company/metric/period alignment, numerical
consistency, sufficiency, verification, abstention, and release.

## Current position

- P0–P4 are complete and preserved.
- P5's provider-backed A0–A5 evaluation is complete. It is a negative/weak
  quality result: held-out numeric exact is 0% for all variants and evidence
  gates produce 0% answer coverage on held-out cases.
- M1 is complete as an offline vertical evaluation path connecting retrieval,
  evidence decision, adaptive retrieval, generation, and verification. A
  request-facing API and persistent ledger are not part of that path.
- M2 retrieval stage diagnostics are complete. Dense remains the measured
  retrieval baseline: no fusion or reranking variant beat it on the held-out
  cohort. Query-derived company and period filters improved dense retrieval on
  eligible queries and remain opt-in research.
- M3 candidate Evidence Policy Engine and its separate 60-case synthetic
  decision benchmark are complete. Policy v1.0.0 is a typed, deterministic
  contract; its perfect fixture agreement is not real-corpus accuracy or
  calibration. It is not yet connected to the P5 answer path.
- M4 runtime Corpus Map and corpus-aware planning are complete as a standalone
  component and 150-case BM25 comparison. Corpus-aware planning improved
  Recall@10 by 4.34 points overall and 2.22 points held-out, but p95 BM25
  latency rose to 1,051 ms and the absolute BM25 result remains below dense.
  Keep dense as the baseline; M5 finite complexity routing is next. See
  [`CORPUS_AWARE_PLANNING.md`](CORPUS_AWARE_PLANNING.md).
- Deployment is explicitly out of scope. M15 may deliver a local research UI.

## Milestones

| Milestone | Deliverable | Status |
|---|---|---|
| M1 | Connected, reproducible retrieval → decision → adaptive retrieval → generation → verification baseline | Complete as offline P5 evaluation |
| M2 | Candidate recall, fusion, pool-size, metadata, and reranker diagnostics | Complete; dense baseline retained |
| M3 | Versioned Evidence Policy Engine and separate decision benchmark | Complete; synthetic contract only |
| M4 | Runtime Corpus Map and corpus-aware task planner | Complete; measured, not integrated into P5 |
| M5 | Finite complexity router with FAST/STANDARD/DEEP budgets | Planned |
| M6 | Deterministically merged shared Evidence Ledger | Planned |
| M7 | Filing, XBRL, table, evidence, and financial reasoning capabilities | Planned |
| M8 | Bounded parallel fan-out/fan-in for independent work | Planned |
| M9 | SEC XBRL concepts, periods, units, accessions, amendments, and restatements | Planned |
| M10 | pypdf vs Docling and structure-aware document experiment | Planned |
| M11 | Atomic claim graph, semantic support checks, contradictions, bounded correction | Planned |
| M12 | Company/year/context hard-negative retrieval benchmark | Planned |
| M13 | Multi-agent and smart-router ablation against retrieval/evidence baselines | Planned |
| M14 | ColBERT/multivectors/GraphRAG/HippoRAG/LightRAG only after earlier evidence | Planned |
| M15 | Local evidence-first research interface and safe progress trace | Planned; do not deploy |

## Research rules

1. Preserve the dense baseline, P0–P4 behavior, and benchmark cohorts.
2. Add one material variable at a time and record the exact dataset, config,
   cost, latency, resource use, and commit.
3. Keep benchmark labels out of runtime inputs.
4. Treat model outputs as observations. Deterministic, versioned Python policy
   decides whether evidence and claims can be used.
5. Do not add an agent or framework unless a bounded capability and measured
   evaluation justify it.
6. Never mix reported/restated periods, incompatible concepts, units, or
   currencies silently. Missing facts remain unknown.
7. Keep raw benchmark data, model caches, runtime indexes, secrets, and
   per-case generated answers out of Git.
8. No cloud deployment without a new explicit request.

See [`RESEARCH_BACKLOG.md`](RESEARCH_BACKLOG.md) for open work and
[`EXPERIMENT_LOG.md`](EXPERIMENT_LOG.md) for completed and planned experiments.
