# Q5 — Retrieval with downstream utility

Q4 control commit `a1856c6052220cbe68f69408b182129a26ef36e3` provided the
unchanged candidate, coverage, and release rules for these comparisons.
The research question was whether a ranking change could recover grounded
answers after Q4. The hypothesis was that a requested metric and fiscal
period visibly aligned in a financial statement would help prioritize
usable evidence when Dense placed it outside the graph's output budget.

## Inputs and controls

- M12 supplies 24 questions with exact positive and hard-negative passage
  judgments. Its three historical splits are exposed and preserved. The
  cases distinguish company, fiscal period, metric, disclosure, and source
  revision, including the same number in an unaudited release or a segment
  note. FinRank motivated distinguishing a curated negative ranking from
  corpus retrieval. This evaluation uses only the existing licensed
  FinanceBench-derived local corpus and FilingScope judgments.
  [FinRank paper](https://arxiv.org/abs/2608.07400) · [FinRank release and license](https://github.com/datanxt/FinRank)
- The Q5 graph cohort contains 30 answerable cases and three cases to
  withhold. Development has five issuer groups and 13 questions. Validation
  has 17 answerable cases and three controls across six issuers. The
  issuer bootstrap uses five connected groups in validation because one
  query compares American Water Works and AES. Filing values and source
  pages were checked in Q2. The Q5 questions use these provisional
  judgments, with new multi-statement combinations. The 3M, JPMorgan, and
  Pfizer pairs distinguish fiscal quarters from year-to-date totals on the
  same page. The controls exercise unavailable restatement, currency
  mismatch, and forecast intent. This cohort awaits independent review.
- Every comparison uses frozen P1 vectors, the pinned Nomic revision, and
  the Q4 PDF page cache. The controlled graph uses the same forced research
  route, output budgets, and no SEC client. The natural-route comparison
  also measures M13 and Q3 direct-fact safety against pinned local SEC
  snapshots. Those replays preserve the structured and direct-table paths.
  M13 and the Q3 direct-fact cohort are regression checks.
- Candidate recall covers each method's full generated candidate pool.
  Top-k scoring is measured separately. M12 measures exact passage ranks,
  while Q5 measures source-page coverage. M12 pairwise discrimination
  includes pairs with both candidates in the generated pool. The artifacts
  preserve per-case ranks and missing pairs. The same page can contain
  several numeric columns. Quarter/YTD correctness is scored on the final
  claim and its evidence, in addition to page retrieval.

## Controlled variables

Dense stays available as the permanent control. Pool size 20, 50, and 100
was swept with fixed top-k and again under the same statement ranker.
Company, document year, form, and section filters were applied independently.
Company and period ranking were also tested as soft priorities over the
unchanged Dense pool. Query shaping added canonical row aliases. Parent
context expansion reused the M14 selective, bounded expansion method.

The fusion comparisons used the same Dense and BM25 channel pools. DBSF
normalizes each returned score distribution using sample standard deviation
and the three-sigma endpoints. Route-aware RRF changes weights based on
filing or statement cues. Dense preservation reserves the top three Dense
passages before filling remaining ranks with equal-weight RRF.
[Qdrant hybrid queries documentation](https://qdrant.tech/documentation/search/hybrid-queries/#distribution-based-score-fusion-dbsf)

The graph variants use the existing M14 local graph, personalized PageRank,
and dual-level methods. The cross-encoder, ColBERT MaxSim, and local Qdrant
multivector compare identical Dense top-20 pools on both the original
benchmark questions and actual graph retrieval queries. The evaluation
checks each common query and scope for identical candidate IDs. Learned
reranking latency combines observed warm ranking and graph replay overhead.
Local Qdrant provides numerical parity evidence for multivectors.

## Runtime implementation

`FinancialStatementRanker` parses already retrieved, hash-checked physical
pages with the Q2 column parser. It ranks on presence of requested metric
and period identities. The bounded cache stores slot identities. It skips
restated cells in this ranking signal and retains Dense order on ties.
`FrozenDenseRetriever` applies it to at most 100 candidates for scoped
financial filing searches in the local application. Search results continue
to honor the existing top-k, tool, context, and release limits. The ranking
signal is ordinal and the original Dense cosine remains available in the
retrieval record. Direct source lookups and unscoped Dense searches use
their existing behavior. The local backend accepts `--retrieval-policy dense`
for reproduction. The runtime uses no benchmark labels or additional model.

## Quality and failure changes

Under forced PDF research, Dense had ten grounded answers among the 17
answerable validation cases. The same statement ranker recovered 12 with a
20-passage pool, 15 with 50, and 17 with 100. Dense alone still had ten at
each pool size. The larger pool exposed the missing statements, and ranking
the observed slots moved them into the top-k result. The seven recoveries
were AES assets, revenue and combined statements, Block operating loss and
combined statements, and PayPal cash and combined statements. The
comparison on 100 candidates had a 41.2 percentage point paired gain
(issuer-group bootstrap interval 14.3–61.1 points).

With normal source routing, the existing direct paths already resolved
four of those seven cases. Statement ranking recovered the three remaining
multi-statement cases for AES, Block, and PayPal. The paired natural-route
gain was 17.6 percentage points (6.3–28.6 points) across five connected
issuer groups. All three controls withheld the response. M13 retained
21/21 grounded answers and 3/3 correct abstentions, and the Q3 direct-fact
cohort retained 14/14 grounded answers and 1/1 correct abstention.

The strongest M12 top-10 evidence coverage came from the graph PageRank
variant. The table ranker improved grounded answers on the separately
graded financial statements. Several M12 topics, including recast and
non-GAAP disclosures, require statement types beyond its parsed slot
catalog. DBSF raised M12 Recall@10 while losing most validated answers.
Its lexical pool often displaced usable financial statement pages. Reserving
three Dense passages improved RRF's answer count while leaving it below
the Dense control. Quarter and YTD retrieval sometimes found the correct
physical page without enabling a release. The four 3M development cases
had complete evidence and an unverifiable draft. The numeric mention
parser reads the `3` in the issuer name as a value, a generation and
verification issue to address in Q6.

## Research decisions

| Method | Decision | Rationale |
| --- | --- | --- |
| Dense | Retain | Permanent retrieval control and fallback for unscoped searches. |
| Scoped statement rank, pool 100 | ADOPT | More grounded answers under both controlled and natural routing, with no observed release or provenance regression. |
| Pool 20 or 50 with statement rank | EXPERIMENT | Smaller pools cost less to inspect and miss some answers recovered at 100. |
| Pool increase alone | REJECT | Higher candidate recall at the same top-k yielded the same answers. |
| Issuer, year, form, and section hard filters | REJECT as additional defaults | Individual filters improved some passage metrics without an answer gain. Filing publication year can also exclude comparative evidence. |
| Company or period rank | REJECT as additional defaults | Neither increased grounded answers over Dense. |
| Canonical query shaping | EXPERIMENT | One net additional grounded answer with lower M12 Recall@10 and higher latency. |
| RRF, DBSF, route-aware RRF and Dense preservation | REJECT | Reduced grounded answer accuracy and raised CPU query time on these channels. |
| Selective parent expansion | REJECT as default | Physical statement normalization already supplies full-page context for recognized tables. Expanded prose yielded no answer gain. |
| M14 graph ranks | EXPERIMENT | Improved M12 passage retrieval and recovered two to four validation answers under controlled research. |
| ColBERT MaxSim | EXPERIMENT | One net additional answer on the same top-20 pools, with added model and passage-vector cost. |
| Qdrant multivector | DEFER for runtime | Local MaxSim scores agreed with NumPy. The local adapter was slower and server latency was outside this run. |
| Cross-encoder | REJECT as default | One net additional answer, with estimated graph p95 close to 3 seconds on this CPU. |

## Measured trade-offs

The full JSON reports per-case and per-class metrics for all 28 variants,
including rank changes for labeled negatives, supported citations and
connected-issuer bootstrap intervals. Selected comparisons follow.

| Variant | M12 candidate recall | M12 R@5 / R@10 | M12 complete@10 | M12 MRR@10 / nDCG@5 | M12 negative in top 10 | M12 rank p50 / p95 ms | Q5 grounded validation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dense 50 | 84.7% | 47.9% / 56.3% | 13/24 | .353 / .376 | 9/24 | 50.5 / 57.9 | 10/17 |
| Dense 100 | 91.0% | 47.9% / 56.3% | 13/24 | .353 / .376 | 9/24 | 50.2 / 62.5 | 10/17 |
| Statement rank 100 | 91.0% | 52.1% / 56.3% | 13/24 | .423 / .443 | 9/24 | 57.4 / 64.6 | 17/17 |
| RRF | 92.4% | 30.6% / 59.7% | 12/24 | .252 / .220 | 4/24 | 193.6 / 219.3 | 0/17 |
| DBSF | 92.4% | 38.9% / 65.3% | 13/24 | .263 / .256 | 5/24 | 193.1 / 242.7 | 1/17 |
| RRF with Dense preservation | 92.4% | 45.1% / 61.8% | 13/24 | .372 / .367 | 6/24 | 179.1 / 237.8 | 8/17 |
| Graph PageRank | 84.7% | 60.4% / 83.3% | 18/24 | .434 / .441 | 10/24 | 51.0 / 59.7 | 14/17 |
| ColBERT MaxSim | 70.1% | 55.6% / 70.1% | 15/24 | .476 / .458 | 8/24 | 79.2 / 89.0 | 11/17 |
| Local Qdrant multivector | 70.1% | 55.6% / 70.1% | 15/24 | .476 / .458 | 8/24 | 303.2 / 349.2 | 11/17 |
| Cross-encoder | 70.1% | 61.8% / 70.1% | 15/24 | .473 / .470 | 8/24 | 1,159.4 / 1,408.6 | 11/17 |

The Q5 validation source-page candidate recall moved from 82.4% to 91.2%
and complete top-10 coverage from 10/17 to 15/17 for Dense 50 versus
statement rank 100. Graph queries can request multiple scoped searches.
The forced graph moved from 10/17 to 17/17 grounded answers at 40 tools
in both runs, with p50/p95 moving from 119.6/152.5 to 135.9/165.0 ms.
Both runs made 40 embedding calls and consumed 1,134 embedding input
tokens on the 20 validation requests.

The adopted runtime moved natural routing from 14/17 to 17/17 grounded
answers with 24 tools and 11 embedding calls in each run. The same requests
retained 100% support for emitted citations. The request texts and scopes
matched the control, which used 319 embedding input tokens. Warm graph p50/p95 moved from
16.9/90.9 to 13.4/101.0 ms. The observed cost was USD 0 with zero LLM calls
and zero generation tokens. These measurements describe a Windows CPU,
single-run timing on a small cohort. Setup and model loading are separate.

The pinned index and vectors occupy 565,574,862 bytes on disk and the
normalized matrix uses 88,624,128 bytes. The core benchmark process
peaked at 2.02 GB. Artifact loading took 8.397 s, Nomic model loading took
1.168 s, and the experimental adapters took 9.914 s to prepare. The
runtime skips the experimental adapters.

The learned rerankers scored 120 distinct query-and-scope requests.
ColBERT used 3,857 query token positions, 117.8 MB of passage vectors,
436.9 MB of local model files, and 2.51 GB peak working set. Initial passage
embedding took 213.807 s and model loading took 0.696 s. Local Qdrant
setup took 1.870 s and its maximum absolute score difference from NumPy
MaxSim was 0.0000037. The cross-encoder loaded in 0.120 s and processed
904,847 input tokens across 2,400 query/passage pairs with 2.02 GB peak
working set. All learned runs used fixed top-20 candidate pools and no
external provider.

## Reproduction and limits

The P1 loader verifies the corpus fingerprint and frozen embedding
manifest. Q5 also checks the original M12 Dense ranking order on every
question and checks the existing M12 and M14 report hashes. Use the cached
ColBERT files specified in [M14](ADVANCED_RETRIEVAL.md#reproduce).

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OPENBLAS_NUM_THREADS = '6'
$runs = 'data/financebench/ablation_runs'
uv run --offline --with psutil==7.2.2 python -m scripts.run_retrieval_utility --output "$runs/q5-utility-core.json"
uv run --offline --with fastembed==0.9.1 --with psutil==7.2.2 python -m scripts.run_retrieval_utility --variants dense dense20 --deep-backend colbert --output "$runs/q5-utility-colbert.json"
uv run --offline --with psutil==7.2.2 python -m scripts.run_retrieval_utility --variants dense dense20 --deep-backend cross-encoder --output "$runs/q5-utility-cross.json"
uv run --offline --with psutil==7.2.2 python -m scripts.run_retrieval_utility --variants dense natural_dense natural_table_rank natural_table_rank100 natural_runtime --safety --output "$runs/q5-utility-natural-runtime.json"
python -m scripts.summarize_retrieval_utility --output "$runs/q5-utility-summary.json" --manifest "$runs/q5-utility-manifest.json"
```

The real-filing validation is small and uses source labels checked in Q2.
The zero unsupported releases are observations on these cohorts. Financial
ranking on newly acquired filings, optional server Qdrant multivector
latency, and generalization beyond canonical statements remain open.

Loopback API replay in `auto` mode verified the three recovered
multi-statement questions under the default policy. The Dense control
withheld all three. Both policies withheld the restatement and currency
controls. All ten requests used zero LLM calls. The real server process
peaked at 2.074 GB with Dense and 2.073 GB with statement ranking on this
single comparison. The API artifact records release and citations.
The full test suite passed 376 tests with 0 failures and three existing
missing-local-HTML skips. All seven comparison checks passed. The summary
SHA-256 is `a26a150371d1f45db617add132d7fa98366849262d8baa749ec39683f0a6654c`.
The Q5 phase commit contains this report and its adopted backend.

The next phase audits generation and verification, including issuer names
that contain digits.
