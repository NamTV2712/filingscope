# SEC 2025 runtime track replay

## Predeclared method

Run the existing specialist graph on identical, source-checked questions
with PDF only, SEC Company Facts only, and both sources. Freeze the
questions, PDF page locators, source accessions and expected values
before observing any runtime answers. Use the original PDF and SEC
snapshots in every eligible arm. The test evaluates development-exposed
provisional questions. An acceptable result records the failures and
preserves the historical runtime and release policy.

Measure grounded exactness, numeric matching, coverage, incorrect
releases, correct and false abstentions, and historical citation
locator support. Record p50/p95, tool calls and memory. Report the
reference provenance separately from the runtime input. Treat Company
Facts and iXBRL as related SEC data, with no independent claim.

## Inputs and scoring

The [pilot configuration](../configs/sec_runtime_pilot.py) fixes 26
questions and the expected values from five issuer-published PDF
renditions of SEC filings. All five filings were submitted in 2025.
Tesla's fiscal year ended in 2024. Each reference cell records the
zero-based physical PDF page, row, column, fiscal period and expected
amount in millions of USD. The runner checks the extracted cell before
indexing and binds the reference artifact before collecting predictions.
SEC alternatives require the expected accession, concept, USD unit,
start and end dates, and exact value. The two prior-year revenue
questions can also cite their original 2024 accessions if those rows
agree with the transcribed comparative values.

The frozen reference SHA-256 on Windows is
`44f0c295511c23bff75a3b65ab76f8a9f467a9da2d07249b92bae6714b2b8f53`.
The cohort has 14 lookups, five quarter/YTD cases, two multi-period
cases, two hard negatives, one multi-company case, one future-period
case and one revision case. Of 22 unique PDF cells, 21 have an eligible
Company Facts locator. The segment revenue cell is PDF-only under the
predeclared Company Facts mapping.

| Issuer filing | Accession | Reference PDF pages |
| --- | --- | ---: |
| Apple FY2025 10-K | 0000320193-25-000079 | 31, 33 |
| Apple Q3 FY2025 10-Q | 0000320193-25-000073 | 3, 5 |
| NVIDIA FY2025 10-K | 0001045810-25-000023 | 143, 145 |
| Tesla FY2024 10-K | 0001628280-25-003063 | 39, 50, 51 |
| Walmart FY2025 10-K | 0000104169-25-000021 | 54, 56 |

The Company Facts snapshots come from the [G2 corpus
manifest](G2_SEC_CORPUS_MANIFEST.json). The replay drops observations
with missing filing dates or dates after 2025-12-31. All three arms
share issuer and filing metadata. The structured-only graph receives
that metadata for planning and has no PDF retriever. The document-only
graph has no SEC client. The hybrid graph receives both. Each arm uses
the existing source-aware router and deterministic release policy. The
Company Facts counters count local client reads.

The Tesla revision control requests a restated revenue value. The frozen
Company Facts data has the original amount, and the bounded G2 inline
XBRL extraction from the related 10-K/A has two numeric observations and
no restated revenue observation. The amendment's explanatory note
identifies Part III disclosures as its purpose. The currency and
future-period controls also have empty reference answers. The other 23
questions are answerable from the PDFs, including the Tesla segment
control. [Tesla 10-K/A](https://www.sec.gov/Archives/edgar/data/1318605/000110465925042659/tm252787d2_10ka.htm).

The existing ablation scorer matches the company, metric and fiscal
period in each output clause, the normalized numeric signature and the
predeclared citation locators. Complete answers require one clause per
expected claim and a VERIFIED disposition. Any alternative valid
locator outside the frozen labels can fail this score. The results are
provisional and use locator checks. Strict G1 atomic faithfulness and
citation support require separate semantic adjudication.

## Results

| Outcome | PDF only | Company Facts only | Hybrid |
| --- | ---: | ---: | ---: |
| Grounded exact by frozen locator | 3/23 | 21/23 | 21/23 |
| Exact numeric answer and VERIFIED | 4/23 | 21/23 | 21/23 |
| Answer coverage | 5/26 | 22/26 | 22/26 |
| Releases failing grounded exact | 2/5 | 1/22 | 1/22 |
| Correct abstentions | 3/3 | 3/3 | 3/3 |
| False abstentions | 18/23 | 1/23 | 1/23 |
| Supported citation locators | 3/5 | 24/25 | 24/25 |
| Warm graph p50/p95 (ms) | 57.02 / 267.30 | 9.20 / 16.48 | 11.70 / 268.51 |
| Total tools | 53 | 27 | 47 |
| Dense retrieval / direct statement calls | 31 / 22 | 0 / 0 | 17 / 3 |
| Local Company Facts reads | 0 | 27 | 27 |
| Mean evidence tokens per question | 84.46 | 32.96 | 32.96 |
| Hosted calls / tokens / cost | 0 / 0 / USD 0 | 0 / 0 / USD 0 | 0 / 0 / USD 0 |

Hybrid and Company Facts only released the same 22 answers and made
the same two mistakes. Both grounded all five quarter/YTD cases, both
multi-period cases and the multi-company case. Hybrid ran additional
document searches on this sample with zero gains in grounded exactness.
The full 531-page PDF extraction and 1,359-chunk CPU index setup took
571.82 seconds. Peak process working set was 2,425,499,648 bytes.
Setup is excluded from the single-run warm timings.

### Failure analysis

- All three arms released **USD 97,690 million** of consolidated Tesla
  FY2024 revenue when asked for the energy generation and storage
  business's **USD 10,086 million**. The router treated the question as
  a generic revenue lookup. This is a critical reporting-scope error.
- The PDF-only Apple net-income answer cited page 35, which repeats the
  FY2025 amount in the cash flow statement. The frozen reference lists
  page 31, the income statement. The scorer counts the locator miss in
  its 2/5 release-failure total. The frozen reference is preserved.
- All arms withheld Walmart revenue. The structured replay contains
  the exact value under `us-gaap:Revenues`. Both PDF-enabled arms
  retrieved the reference page, so the miss occurs after retrieval.
- PDF-only withheld every Apple quarter/YTD answer. For the Apple
  FY2025 revenue and Walmart FY2025 revenue misses, the retrieved
  evidence includes the correct page. These results motivate
  inspecting normalization and evidence selection before tuning Dense.

## Reproduce

Save the five PDFs under the names in the pilot configuration and verify
their SHA-256 hashes. Use the original content-addressed SEC cache and
the locked [G0 environment, tokenizer and Nomic caches](G0_BASELINE.md#reproduce).
The script performs no acquisition. Run it with a fresh output directory.

```text
uv run --offline --locked python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --output .local/g2/runtime-pilot-new
```

The output includes the per-case answers, citation locators, source use,
traces, timing and hashes of the PDFs, extracted pages, Company Facts
snapshots, labels and normalized vectors. PDFs and model artifacts are
local inputs.

The [local report](../.local/g2/runtime-pilot-final/report.json)
has SHA-256
`242424adda9ee0f0c8b261a5f9eab42eac0987eff7eb79e5a3d2b8a179d19f43`.
Its normalized vector SHA-256 is
`ec08df3acbebed39f12e2b5567de5cc7222d0f0c45d13063c5608882a8a29aab`.
The execution used local baseline `c740f0afcd61c7575baf0df2daea61a036c2e481`
with the pilot runner and labels in the working tree.

## Regression checks

The follow-up adds 10 offline controls for the PDF column and row,
Company Facts cutoffs and hashes, frozen manifest and source isolation.
The original Windows manifest and the LF-normalized Git file have
separately pinned hashes. The full offline suite passed on Windows
(463 passed, 3 skipped) and Linux WSL with the optional parser
(462 passed, 4 skipped). The skips concern unavailable local corpora
and raw filings. Ruff, focused mypy, syntax, lock and tracked-secret
checks passed.

The existing architecture replay matched the G4 result in stable
fields across M13, direct, complex, narrative, fault and serial controls.
Routed M13 stayed at 21/21 grounded answers and 0/21 incorrect
releases. The comparison excludes timing and memory.

## Decision

**KEEP** the offline matched-source replay and predeclared labels as
development regressions. **EXPERIMENT** with fixes for reporting-scope
release and the documented normalization failures, measured on the same
cases. **DEFER** comparative superiority and release-risk claims.
The pilot reuses issuers from earlier development and validation
controls. Independently reviewed narrative cases, broader mixed cohorts
and strict semantic annotations remain open.
