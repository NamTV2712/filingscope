# Corpus-aware planning

## Status

M4 is implemented and measured. `src/research/` builds a compact runtime
Corpus Map and turns question requirements into bounded retrieval tasks. The
planner is a standalone component and benchmark; it is not yet wired into the
P5 answer path or a request-facing application. The dense P1 baseline remains
unchanged.

## Corpus Map contract

`CorpusMap.from_chunks()` aggregates document IDs, company names and entity
IDs, tickers, CIKs, filing forms, reporting periods, sections, table IDs,
metadata conflicts, source states, chunk counts, and index-generation
metadata. It discards chunk text, answers, evidence-page labels, and other
evaluation fields. The map does not include company facts or generated
descriptions.

Availability has three meanings:

- `AVAILABLE`: indexed metadata or a source explicitly establishes local
  availability.
- `MISSING`: a complete relevant inventory proves the requested source is not
  present.
- `UNKNOWN`: inventory is absent, incomplete, conflicted, or too coarse to
  establish presence or absence. `NOT_INDEXED` metadata is therefore not
  treated as proof that a company or filing is missing.

The planner may use existing document IDs from the map. If an exact period is
missing, it can target a bounded set of other local filings while marking the
requested period `MISSING`. If company coverage is unknown, it can issue a
broad query without fabricating document IDs. A company proven absent from a
complete inventory produces no retrieval call.

## M4 comparison

- **Baseline:** deterministic question-only requirement extraction and query
  planning.
- **Treatment:** the same bounded requirement extraction conditioned on the
  runtime Corpus Map.
- **Dataset:** 150 public FinanceBench questions; development/validation/
  held-out splits of 60/45/45; frozen P1 index generation
  `3ea92c895826e46ccf03ee52248771cc83e779e90b1660c390d29f2c4abfd18f`.
  The exact question/label/split set fingerprint is
  `e73869cb631d51670f23afa38bfb2a47bd955b7c6e3e727663bea1fd856fc6cd`.
- **Label boundary:** each planner receives only the question string. The
  evaluation layer separately reads gold document/page labels to score ranked
  results. There are no answer-generation or external model calls.
- **Retrieval comparison:** BM25 on the same frozen 28,849 chunks. Each task
  query has a top-50 candidate pool and results are merged to top 10. Candidate
  recall is computed over the union of each task's top-50 chunk pages, so it is
  not a single global 50-item cap.
- **Reproduction:**

  ```powershell
  .venv\Scripts\python.exe -m scripts.run_corpus_aware_planning_evaluation `
    --output data\financebench\planning_runs\m4-corpus-aware-v1.json
  ```

The local report is ignored by Git. It records the source-code and case-set
fingerprints; committed tests and their validation run are recorded below.
The experiment used `rank-bm25==0.2.2`, already present in
`requirements.txt`; M4 adds no package dependency.

## Runtime inventory observed

The 84-document, 28,849-chunk index covers 32 companies. Company, form,
filing-period, and section metadata are complete for this index. Ticker, CIK,
and table-ID metadata are not indexed. No structured-table IDs are indexed,
so structured table evidence is marked `MISSING` for this index; this does not
claim that the original PDFs contain no tables. XBRL fact coverage is
`UNKNOWN`. Filing text is available. The serialized Corpus Map is 28,421
bytes.

## Results

| Measure | Question only | Corpus aware |
|---|---:|---:|
| Recall@10, all 150 cases | 0.1133 | 0.1567 |
| Recall@10, held-out (45) | 0.0889 | 0.1111 |
| Candidate page recall, top-50-per-task union | 0.1800 | 0.2389 |
| Full evidence-page coverage, candidate union | 0.1733 | 0.2267 |
| Retrieval calls | 152 | 182 |
| Calls per question, mean | 1.0133 | 1.2133 |
| Planner latency p50 / p95 | 1.047 / 1.422 ms | 1.939 / 2.669 ms |
| BM25 latency p50 / p95 | 223 / 490 ms | 225 / 1,051 ms |

Among 128 evaluation cases where the map reported a known source state, the
gold source document appeared in at least one eligible task target for all 128
cases. This is a map-target alignment measure, not evidence relevance or answer
accuracy. Ten synthetic probes for catalog companies absent from the index
were all marked `MISSING`; the corpus-aware planner made zero retrieval calls
for those probes and avoided the baseline's 10 calls.

The Corpus Map load/build step took 629 ms. Evaluation took about 95 seconds,
made zero provider calls, and generated zero provider tokens. Tracemalloc
measured 473,284,499 bytes of peak incremental Python allocations during the
evaluation. Process RSS was not measured. Mean generated query length was
36.17 tokens for the baseline and 56.52 for the map-conditioned planner. The
serialized Corpus Map is 28,421 bytes.

## Interpretation and decision

Corpus conditioning improved BM25 Recall@10 by 4.34 percentage points overall
and 2.22 points on held-out cases; candidate recall increased by 5.89 points.
The larger query set raised p95 BM25 latency from 490 ms to 1,051 ms. The
absolute retrieval quality remains weak, and this BM25 experiment is far below
the unchanged dense baseline's P1 Recall@10 of 0.4167. The planner therefore
remains a measured research component. Keep the explicit availability states
and bounded local targets; do not replace dense retrieval or claim an answer
quality gain. M5 can build on the typed task contract and measure downstream
quality and budget effects before any integration.

The benchmark artifact was generated from source commit
`0be938d31cf3a76b5b0baa31023bd4354ce571a3`. The full regression suite passed
with 242 passed and 3 skipped tests.

The report records source fingerprint
`2ae143eaf29fe9383bf70841b00f1b5bdd6e8d299e24ca0628d809b28d9e808d`, marks
the fingerprinted source tree clean, and includes the index manifest's corpus
and embedding-manifest fingerprints.
