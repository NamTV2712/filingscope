# G3 financial understanding and scoped retrieval

## Objective and predeclared gates

The G2 baseline computes a dense dot product against the entire frozen
matrix before discarding rows outside a request's document scope.
Compute only within that same eligible set and preserve stable corpus
order for ties. Test identical ranked IDs, ineligible source exclusion,
score agreement within floating-point tolerance and downstream
grounding. Measure paired warm latency on cached query embeddings, with
timing that includes scope selection and retrieval ranking.

Use the pinned P1 index, the historical M12 and Q5 replays, and G2 lookup
controls. Keep existing financial requirements, retrieval choices and
source-policy gates unless a paired test shows an improvement. A
critical provenance or release regression rejects the change.

The baseline also drops the YTD or calendar-year qualifier when
expanding a single explicit period for a year-over-year question.
Test paired prior/current periods for discrete quarters, YTD and
calendar years before accepting the fix. Keep the established period
comparators and deterministic arithmetic.

## Changes

- `FrozenDenseRetriever` intersects the caller's eligibility mask
  with the document scope before scoring. For scopes below half of
  the corpus, it scores only eligible rows and maps results back to
  their original corpus positions. Wide and unscoped queries use the
  existing full-matrix path. Both preserve stable ordering and the
  same statement reranker. The cutoff is an implementation choice.
  The measured scopes are substantially smaller.
- `EvidenceRequirementExtractor` preserves the entire period prefix
  when expanding YoY. A prior-year YTD slot remains YTD and a prior
  calendar-year slot remains calendar-year. The existing router,
  ledger, verifier and release policy retain their authority.

## Paired evaluation

The scoped test ran 15 alternating baseline/candidate repetitions
on each of 30 answerable Q5 questions. Its document scope came from
known source locators to isolate the scoring cost. Query embeddings
were cached once from the pinned Nomic model. The timing includes
masking, selection and ranking. Top-10 chunk IDs matched for all
30 questions and no returned chunk escaped the scope. The largest
absolute cosine difference was `1.19e-7`. The five focused tests
cover scope intersections, empty scope, ties, and four YoY period
variants. On the G2-era code the YTD and calendar-year variants
created a different prior-period scope. Both now pass.

| Measure | G2 baseline | G3 candidate |
| --- | ---: | ---: |
| Scoped rank p50 / p95 across case medians | 4.25 / 5.18 ms | 1.16 / 1.87 ms |
| Validation scoped rank p50 across case medians | 4.38 ms | 1.48 ms |
| M12 Dense Recall@10 | 56.25% | 56.25% |
| Q5 Dense page-locator precision / gold slot recall @10 | 21/291 / 21/37 | 21/291 / 21/37 |
| M13 routed grounded exact / incorrect releases / false abstentions | 21/21 / 0/21 / 0/21 | 21/21 / 0/21 / 0/21 |
| Natural statement grounded exact / incorrect releases / false abstentions | 30/30 / 0/30 / 0/30 | 30/30 / 0/30 / 0/30 |
| Q7 persistent outage healthy-source retention, adaptive / routed | 5/10 / 10/10 | 5/10 / 10/10 |
| Q6 writer gates | 9/9 | 9/9 |

The architecture, retrieval and writer reports match on stable
fields. That includes historical citation outcomes and released
claims. G1 semantic faithfulness and citation precision still need
reviewed claim labels for new cohorts. On the G2 templates only
44/204 questions met the current default extractor's syntactic
support checks. Many templates ask for exact ISO dates, an explicit
accession or concepts outside the runtime vocabulary. Those labels
measure structured lookup. Turning this cohort into an answer-level
benchmark requires explicit accession and interval enforcement.
Alias expansion, query rewriting and learned reranking are deferred
until they can be tested against those full requirements.

Windows with the iXBRL extra passed 447 tests with 3 missing
HTML fixture skips. Ruff and focused mypy passed.

## Latency, usage and decision

M13 warm p50/p95 was 18.46/213.40 ms before and 20.64/205.65 ms
after. The natural statement graph was 16.66/127.81 ms before and
17.00/110.20 ms after. Single-pass graph measurements do not isolate
the scoring change. Peak architecture process memory stayed near
2.01 GB. The paired kernel process peaked at about 1.91 GB. Natural
statement usage held at 38 tools and 14 embedding calls. Both runtime
replays used zero provider calls, zero billed tokens and USD 0.

**KEEP** the scoped Dense optimization and YoY period fix. The
paired rank benchmark measures a lower CPU cost with matching
ranked IDs. No new critical provenance or release failures were
observed. No new generalization claim is made for the provisional
G2 QA templates.

Baseline local commit `4368903d3c2f05b15102ce217024457818e47952`.
Reproduce the graph comparisons with the
[G0 replay commands](G0_BASELINE.md#reproduce). The local
[kernel receipt](../.local/g3/scoped-kernel.json) contains each
query's score delta and median. The G4 work starts with request
stage duplication and source verification.
