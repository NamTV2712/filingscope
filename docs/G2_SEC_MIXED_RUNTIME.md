# G2 mixed SEC runtime replay

## Evaluation protocol

Run all 204 frozen mixed-cohort questions through the existing routed
specialist graph. Compare document-only, Company Facts-only and hybrid
arms. Within each cohort, index only that cohort's filings. Use the same
questions and filing metadata for every arm. The document index uses
visible HTML from the frozen SEC archives. The Company Facts snapshots
retain the existing filing-date cutoff. Pass only the question to the
graph. Check the evidence and labels after predictions.

Record release disposition, citations, latency, tools, and evidence
tokens for every case. Count correct abstentions on the eight
missing-unit controls. For numeric releases, count how many can be
confirmed from the verifier-linked ledger on complete matching issuer,
metric, interval, currency, amount, and accession. Report releases with
incomplete matching evidence separately. Inspect the actual output for
representative successes and failures. Narrative and revision cases
get a separate release and source review. Keep the experiment if the
cohort hashes, filing receipts and source inventories validate, all
predictions are recorded, and the prior replay and offline checks pass.

## Implementation and evidence boundaries

The runner validates the three canonical question and reference hashes,
checks cohort disjointness, and verifies the frozen SEC archive receipts
before reading each primary HTML member. Fiscal focus comes from the
filing cover and the reported end date is checked against EDGAR metadata.
The document path indexes visible prose and tables with nearby headings.
It discards the hidden Inline XBRL header and does not load the Arelle
fact extracts. Logical HTML block indices are local citation locators.
They do not correspond to physical PDF pages. The Company Facts client
replays cutoff-filtered snapshots offline.

The graph receives the unchanged question text and the cohort's eligible
source inventory. It uses its existing router, scoped Dense retriever,
statement parser, ledger, verifier and release policy. Predictions are
written before the evaluator checks them against the reference. A numeric
release is confirmed only when each atomic claim matches a distinct
expected value and its cited supporting records establish the expected
financial identity. A document match requires a typed statement row and
the registry's metric-to-concept mapping. Narrative excerpt retrieval is
a literal source diagnostic. Semantic judgments remain author review.

## Matched results

| Measure | Document-only | Company Facts-only | Hybrid |
| --- | ---: | ---: | ---: |
| Confirmed numeric releases, pilot | 3/28 | 6/28 | 6/28 |
| Confirmed numeric releases, development | 7/94 | 20/94 | 20/94 |
| Confirmed numeric releases, validation | 10/65 | 11/65 | 11/65 |
| Confirmed numeric releases, overall | 20/187 | 37/187 | 37/187 |
| Answer coverage | 26/204 | 37/204 | 42/204 |
| Answerable questions withheld | 170/196 | 159/196 | 154/196 |
| Released answers with an extra or wrong numeric claim | 5/26 | 0/37 | 5/42 |
| Released answers with unconfirmed evidence identity | 1/26 | 0/37 | 0/42 |
| Correct missing-unit abstentions | 8/8 | 8/8 | 8/8 |
| Narrative/revision releases | 0/9 | 0/9 | 0/9 |
| Reference excerpts retrieved, narrative/revision | 6/9 | 0/9 | 6/9 |
| Total tools / Company Facts reads | 136 / 0 | 65 / 65 | 151 / 65 |
| Total evidence tokens | 22,405 | 2,373 | 14,883 |

The prebound structured diagnostic confirmed 187/187 numeric cases.
Through the graph, Company Facts-only confirmed 37/187. The input
question now has to resolve the financial metric, dates and filing
scope before an exact observation can be chosen. A separate extractor
check found 109 questions with an unrecognized metric, including six
quarter/YTD questions in development. All 26 quarter/YTD questions
lack a typed cumulative slot from the date-only prompts. Six
multi-company questions produced a four-slot cross product of their
two companies and two years, although each issuer was assigned one
as-of date in the question.

The document and hybrid arms returned two fiscal-year amounts for
five questions that requested a single observation spanning an
explicit date range. For example, the Apple hard-negative question
requests 2024-09-29 through 2025-09-27. Both released FY2024 and FY2025
operating income. The Coca-Cola document-only release had the
correct amount and fiscal end date, but its cited table fact lacked
a typed start date. The strict identity check leaves it unconfirmed.
All three arms withheld all 32 multi-period cases. The six retrieved
narrative excerpts led to zero releases in each text-enabled arm.
Context Precision@10 and full claim/citation faithfulness require
separate relevance and entailment judgments on these HTML blocks.

The first replay indexed 3,944 chunks from 17 filings. It took
918.68 s and peaked at 2,080,759,808 bytes. Warm per-case p50/p95
was 4.23/132.95 ms for document-only, 2.98/12.79 ms for Company
Facts-only and 3.76/147.37 ms for hybrid. Model provider calls,
billed tokens and USD spend were zero. These are descriptive single-host
measurements from a development-exposed corpus.

## Reproduce

```text
python -m scripts.run_sec_mixed_runtime --manifest .local/g2/verified-replay/manifest.json --cache .local/g2/sec-cache --cohorts .local/g2/mixed-cohorts-final --output .local/g2/mixed-runtime-replay --threads 10
```

Use the pinned offline CPU setup. The report binds each cohort's HTML
blocks, chunks, vectors and predictions to their hashes. Subsequent runs
can pass `--reuse-vectors` with an earlier mixed replay directory. The
loader checks the reconstructed chunk hash, model revision, vector file
hash, shape and norms before use.

The second run used the frozen vectors. All 612 predictions reproduced
their answers, routes, dispositions, claims, citation IDs and case
scores. It took 23.49 s and peaked at 1,770,532,864 bytes. The
[first report](../.local/g2/mixed-runtime-full/report.json) has SHA-256
`23aecb4de4209b1dbe875acffbb59d3028f9d6d714d320161982d39f7de7e543`.
The [verified report](../.local/g2/mixed-runtime-verified/report.json)
has SHA-256 `3bfd79d49ff0aa0098d53fa95a1c3e7892207169fea098667d939d05cd3e7d1e`.

The 26-question PDF pilot also reproduced its 104 numeric arm/case
outputs and 18 narrative arm/case outputs. Answers, dispositions,
ranked source sets and citations matched the previous G4 replay. Its
reference, page, chunk and vector hashes matched. Windows offline
passed 538 tests with three skips. WSL passed 537 with four. Both
deterministic claim and citation fixture checks reproduced. Ruff and
focused mypy passed. The focused runtime and pilot suite passed 16 tests.

**KEEP** the mixed runtime benchmark and the separate exact-lookup
control. The results identify date-interval interpretation as the first
release-safety issue to address on these inputs. Baseline Git commit
`7a82a3f`. Independent evaluation still awaits reviewer-held material.
