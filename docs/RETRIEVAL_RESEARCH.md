# Retrieval research program

## Preserved evidence

P1's pinned 150-case evaluation measured dense retrieval at Recall@10 0.4167
and full evidence-page coverage@10 0.3733. Dense outperformed current RRF and
hybrid reranking on the aggregate sample. The P5 replay matched P1 chunk IDs on
100% of cases for A0/A1/A2. The reason dense wins is still a hypothesis; do not
assume that hybrid search or reranking is better.

## M2 stage diagnostics

Use the same cases, corpus, split, and query embedding where possible. Record
per-question candidate IDs, retrieval method, score/rank, metadata filters,
latency, token/candidate budget, and gold-page coverage. Gold labels stay in the
evaluation layer.

| ID | Experiment | Main measurement | Status |
|---|---|---|---|
| R1 | Candidate recall before fusion and reranking | Dense/BM25/lexical candidate recall and union recall at each pool size | Planned |
| R2 | Fusion ablation | BM25, dense, current RRF, weighted RRF, dense-preserving fusion, route-aware fusion | Planned |
| R3 | Independent pool sizes | Dense, lexical, rerank candidate counts and final-k sweep | Planned |
| R4 | Hard negatives | Same company/wrong year; same metric/wrong company; wrong metric; similar wording/wrong disclosure; restated vs as-reported | Planned; benchmark work M12 |
| R5 | Metadata routing | Company, CIK, period, form, and section filters independently and jointly | Planned |
| R6 | Structure-aware retrieval | Section-aware, table-aware, parent-child and small-to-big expansion | Planned |
| R7 | Late interaction | ColBERT/Qdrant multivectors after R1–R6 | Deferred to M14 |

## Experiment controls

- Dense is a permanent baseline; report it next to every change.
- Keep answer generation off for pure retrieval tests.
- Report Recall@5/10, MRR, nDCG, full evidence coverage, candidate recall,
  p50/p95 latency, candidate counts, and RAM where relevant.
- Freeze the held-out cohort. Use development for iteration and validation for
  selection; do not tune and claim the same cohort is unseen.
- Inspect false positives and misses by entity, year, metric, section/table,
  and source revision. A relevant-looking passage from the wrong year/company
  is an evidence error even when semantic similarity is high.
- Do not change the production retrieval default unless the measured result is
  reproducible and improves the target evidence metric without an unacceptable
  cost/latency regression.

## Qdrant feature note

Qdrant documents staged prefetch and rescoring, dense/sparse/full-text hybrid
search, and multivectors for late interaction. Current FilingScope diagnostics
must establish where candidates are lost before using these features. The local
Qdrant test warning that payload indexes have no effect in local mode should be
considered when evaluating metadata filters. See
[Qdrant hybrid queries](https://qdrant.tech/documentation/search/hybrid-queries/)
and [Qdrant multivectors](https://qdrant.tech/documentation/tutorials-search-engineering/using-multivector-representations/).
