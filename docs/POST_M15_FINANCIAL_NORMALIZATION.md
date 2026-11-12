# Q2 Financial period, table and SEC normalization

**Status** Validated offline. Source before Q2
`556beff7e772c58f85c6834cf1b8c12d42789bcd`. The validated revision is
recorded in the [implementation checkpoint](IMPLEMENTATION_PROGRESS.md#post-m15-checkpoint).

## Research question and changes

Q1 identified financial table alignment as the first loss in 27 B4/B5
runs. For two other B4 failures, the SEC worker had the right quarterly
fact and coverage interpreted its rendered text as annual. The hypothesis
was that retaining financial period identity across the analyst and
verifier, and recovering physical column ownership before parsing values,
would restore answers under the existing evidence thresholds.

- `company_facts.py`, `period_identity.py`, `decision/models.py` and the
  ledger carry the resolver's fiscal period, duration or instant, start,
  end and filing fiscal focus. The ledger links the typed fact to the
  original SEC accession, tag, form, raw unit and revision history.
  Discrete and year-to-date intervals resolve separately. Competing
  original or revised accessions at the same selection point remain
  ambiguous.
- `statement_columns.py` aligns PDF rows to full-page period headers and
  preserves table units, row and column locators, raw cell values and
  typed periods. It recognizes explicit three-, six- and nine-month
  groups, negative and placeholder cells, and an unlabeled consolidated
  revenue subtotal when its column sums verify. The parser records
  ambiguous rows. An annual January or February date needs a fiscal-year
  anchor, and a restated or amended table stays out of ordinary facts.
- `table_extractor.py` uses physical cell positions for simple HTML
  grids with blanks. It declines legacy mappings whose date labels
  repeat without an explicit period distinction.
- `specialists.py` uses the already retrieved document/page IDs to read
  a bounded, hash-checked pypdf cache. The graph keeps candidate policy,
  set sufficiency and independent claim verification. A typed period
  mismatch blocks support even when values agree.
- `period_value_parser.py`, the requirement extractor, planner and claim
  verifier preserve fiscal, calendar, quarterly and cumulative labels
  across the answer boundary. Existing `FinancialFact` and `EvidenceRecord`
  carry the normalized observation and link to its source.

## Offline corpus results

The new extraction cohort contains 57 provisionally labeled cells from
21 financial rows. The 27 development cells and 30 validation cells
have disjoint issuer groups. They use pinned FinanceBench PDFs with new
cell-level labels. The labels are AI-assisted and source-checked. Independent
human review is pending. The six validation issuers limit any population
inference. These metrics describe a known-page extraction task.

| Cohort | M14 legacy exact | Q2 header to period | Q2 unit and scale | Q2 amount and provenance |
|---|---:|---:|---:|---:|
| Development | 7/27 | 27/27 | 27/27 | 27/27 |
| Validation | 12/30 | 30/30 | 30/30 | 30/30 |

The 22 M13 PDF slot/page pairs used for retrospective diagnosis recovered
13/22 exact observations with the legacy annual parser and 19/22 with Q2.
The Q2 table parser alone withholds three Best Buy annual cells because
the page's January or February end date does not establish the issuer's
fiscal label. The specialist can supply that date anchor when it obtains
a matching typed SEC observation in the same request.

Three ambiguity controls withheld the target value. They cover mixed
monetary and percentage columns, a January fiscal-label ambiguity, and
bank revenue with a different reporting basis. The SEC evaluation
matched 9/9 labeled values, currencies, intervals and accessions,
including Apple's 90,753 million discrete-quarter revenue and 210,328
million cumulative revenue from the same 10-Q. The two values remain
separate through release. Existing synthetic original/revision, CIK,
currency, and concept-drift tests remain part of the regression suite.

## M13 end-to-end comparison

All variants used the same 24 M13 requests, frozen P1 ranks and cutoff SEC
snapshots. The pypdf intervention reads physical pages only after retrieval.
The question labels do not influence source selection.

| Metric | B4 baseline → Q2 | B5 baseline → Q2 |
|---|---:|---:|
| Grounded exact / answerable | 3/21 → 7/21 | 1/21 → 3/21 |
| Numerically exact / answerable | 3/21 → 7/21 | 1/21 → 3/21 |
| False abstention / answerable | 18/21 → 14/21 | 20/21 → 18/21 |
| Correct abstention / unanswerable | 3/3 → 3/3 | 3/3 → 3/3 |
| Unsupported releases / released | 0/3 → 0/7 | 0/1 → 0/3 |
| Correct citations / citations | 3/3 → 7/7 | 1/1 → 3/3 |
| Mean tool calls per request | 2.75 → 2.75 | 1.0833 → 1.0833 |
| Mean retrieval calls per request | 1.7917 → 1.7917 | 0.9167 → 0.9167 |
| Warm p50 / p95 ms | 116.851 / 268.887 → 130.768 / 244.446 | 82.550 / 219.884 → 80.495 / 202.655 |

B4 recovered Apple FY2024 discrete Q2 revenue and Best Buy Q2 FY2024
cash using the typed SEC path. Both modes recovered Amcor FY2020 cash and
Boeing FY2018 assets with full-page statement columns. Every previously
grounded case remained grounded. All emitted citations matched the expected
sources. M13 remains exposed and the small release counts limit the
unsupported-release estimate.

The paired improvement was +19.05 percentage points for B4 and +9.52
for B5. The descriptive 95% issuer-group bootstrap intervals were
6.67 to 28.57 and 0.0 to 23.81 points, respectively, with 10,000 draws
over eight groups. Setup took 10.351 seconds and the paired replay reached
2,003,746,816 bytes peak working set. The standalone 40-page extraction
audit reached 290,066,432 bytes peak working set, including the SEC
snapshots. The hash-verified page cache indexed in 0.346 s and parser
p95 per page was 0.543 ms versus 0.143 ms for the legacy annual parser.
The page cache reads only retrieved physical pages at request time.
These single-run timings do not establish a system latency improvement.

## Parser decisions

| Mechanism | Evidence | Decision |
|---|---|---|
| Pinned pypdf layout text and explicit column alignment | The known-page Q2 labels, 22 M13 page slots, and paired end-to-end changes above. BSD-3-Clause pypdf. | Adopt on retrieved physical pages, with ambiguity handling. |
| Docling native grids | The historical M10 five-PDF run recovered 20/20 annotated header associations. ACCURATE used 424.444 s and 3,795.8 MB peak versus 8.205 s and 97.2 MB for pypdf. The structured representation produced 1,254 chunks versus 565. Its validation Recall@10 remained 0.20. These are M10 measurements on five selected documents. MIT Docling and separately pinned model artifacts. | Retain the existing optional diagnostic path for pages whose layout is unresolved. The Q2 runtime uses pypdf. |
| EdgarTools | MIT library with filing-level taxonomy access. The existing SEC JSON client resolved all nine labeled Q2 observations with the required provenance. | Defer an additional adapter until a measured fact needs filing-level data. |

[M10 comparison](DOCUMENT_INTELLIGENCE.md), [Docling](https://github.com/docling-project/docling), [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [EdgarTools](https://github.com/dgunning/edgartools).

## Reproduce

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OPENBLAS_NUM_THREADS = '6'
$runs = 'data/financebench/ablation_runs'
$pages = 'data/financebench/cache/extracted_pages_d5c2a1369d9997a3055a.jsonl'
uv run --offline --with psutil==7.2.2 python -m scripts.run_multi_agent_ablation --variants B4 B5 --statement-pages $pages --output "$runs/q2-verified-ablation.json"
uv run --offline --with psutil==7.2.2 python -m scripts.run_financial_normalization_evaluation --output "$runs/q2-normalization.json" --manifest "$runs/q2-manifest.json" --ablation "$runs/q2-verified-ablation.json"
```

The manifest binds the code and case-label hashes, data and model
revisions, benchmark configuration and outputs. The normalization and
paired ablation SHA-256 digests are
`0ac5ba27610fad80165c79b96529fe2137c6a691ad7d5c04912759538da74a08` and
`f68bd819c94a529fb80e99cf272bee43ac35817b1ccf584d6416f3e9c2c023f0`.
The full regression suite passed 368 tests with zero failures and three
pre-existing skips due to missing local HTML filings. Syntax and Git
whitespace checks passed. The replay is offline and
uses zero provider calls, zero provider tokens and zero SEC HTTP calls.
The website files are unchanged. The next phase evaluates access to
structured facts through FAST on a separate direct-lookup validation set.
