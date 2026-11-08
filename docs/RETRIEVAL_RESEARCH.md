# Retrieval research program

## Preserved evidence

P1's pinned 150-case evaluation measured dense retrieval at Recall@10 0.4167
and full evidence-page coverage@10 0.3733. M2 found dense to be the strongest
individual candidate producer; unioning all three sources at 50 candidates
adds some gold-page recall, but tested fusion and reranking still trail dense.
The P5 and M2 replays matched frozen P1 chunk IDs on all 150 cases. Keep dense
as the baseline and require measured gains before promoting hybrid variants.

## M2 stage diagnostics — complete

The full 150-case diagnostics explain why the current hybrid path trails dense:
dense Recall@10 is 0.4167 and full evidence coverage@10 is 0.3733; equal RRF
falls to 0.3167 / 0.2600. Weighted RRF recovers some quality (0.3800 / 0.3267)
but remains below dense in development, validation, and held-out. Candidate
union at 50 per source raises gold-page recall from dense's 0.6989 to 0.7256,
while lexical candidates alone recover none of the annotated gold pages. The
loss is therefore primarily in fusion/ranking rather than the complete absence
of complementary candidates.

Query-derived company and reporting-period filters improve dense retrieval on
their eligible cohorts, including held-out cases; the same filters hurt RRF.
They remain diagnostic-only pending paired latency and false-filter analysis.
The P1 corpus has no CIK, ticker, or form_type metadata, and its sole section
value is document. The available doc_type field is used as a form proxy. Full
tables, provenance, cohort results, latency, resource measurements, and source
fingerprint are in [M2 diagnostics results](RETRIEVAL_DIAGNOSTICS_RESULTS.md).

| ID | Experiment | Main measurement | Status |
|---|---|---|---|
| R1 | Candidate recall before fusion and reranking | Dense, BM25, lexical, and union gold-page recall at each pool size | Complete; dense dominates individual sources |
| R2 | Fusion ablation | Equal/weighted RRF, dense-preserving, route-aware, rerank | Complete; dense remains ahead on held-out |
| R3 | Independent pool sizes | Dense, BM25, lexical, fusion, rerank candidate counts and final-k sweep | Complete; no hybrid setting beats dense |
| R4 | Hard negatives | Same company/wrong year; same metric/wrong company; wrong metric; similar wording/wrong disclosure; restated vs as-reported | Deferred to M12 |
| R5 | Metadata routing | Company, CIK, period, form, and section filters independently and jointly | Complete for available fields; CIK absent and section not discriminative |
| R6 | Structure-aware retrieval | Section-aware, table-aware, parent-child and small-to-big expansion | Planned with M10 document-structure work |
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
