# G3 accession-bound fiscal year pairs

## Evaluation protocol

Baseline `9d9906f` withheld all 32 multi-period questions. Each asks
for two consecutive full fiscal years from a named 10-K. Both values
are present in the frozen Company Facts payload and its corresponding
Inline XBRL reference. Verify the exact end dates, form, accession,
concept, currency and complete annual duration for each slot. The
prior-year comparison must carry its own fiscal year and the revision
relationship to the earlier original filing.

Use the existing bounded lookup, ledger and verification flow. Reject
mixed accessions, ambiguous values or units, incomplete pairs and
nonconsecutive durations. Replay all 204 mixed questions across all
three source arms. Require additional confirmed multi-period releases,
zero new incorrect or unconfirmed releases, and matching previous
releases, missing-unit controls, PDF pilot and architecture outcomes.

## Implementation

An explicit pair of fiscal year-end dates with one 10-K accession creates
two typed requirements. The structured specialist retrieves the issuer's
Company Facts once. It verifies that the newer observation is the
filing's full fiscal year and that the earlier observation uses the
same concept, currency, accession and adjacent annual interval. It
uses the earlier year's original observation to establish its fiscal
label and classify the selected comparative as refiled or revised.
The answer uses the comparative amount from the requested accession.
The filing metadata retains the later filing's own fiscal focus. [SEC EDGAR XBRL guide](https://www.sec.gov/files/edgar/filer-information/specifications/xbrl-guide-2026-08-14.pdf).

The verifier checks each claim against its specific period and cited
evidence, then checks the cited pair before release. The lookup stays
on the existing FAST path, ledger and deterministic writer. Apple
provides a 52-week-year control. The 2025 10-K gives gross profit of
USD 180,683 million for the year ended 2024-09-28 and USD 195,201 million
for the year ended 2025-09-27. [Apple 2025 Form 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm).

## Matched results

| Measure | Document-only | Company Facts-only | Hybrid |
| --- | ---: | ---: | ---: |
| Confirmed fiscal-year pairs, pilot | 0/4 → 0/4 | 0/4 → 4/4 | 0/4 → 4/4 |
| Confirmed fiscal-year pairs, development | 0/18 → 0/18 | 0/18 → 18/18 | 0/18 → 18/18 |
| Confirmed fiscal-year pairs, validation | 0/10 → 0/10 | 0/10 → 10/10 | 0/10 → 10/10 |
| Confirmed numeric releases, overall | 26/187 → 28/187 | 97/187 → 133/187 | 97/187 → 133/187 |
| Answer coverage | 26/204 → 28/204 | 97/204 → 133/204 | 97/204 → 133/204 |
| Answerable questions withheld | 170/196 → 168/196 | 99/196 → 63/196 | 99/196 → 63/196 |
| Incorrect or unconfirmed releases | 0/26 → 0/28 | 0/97 → 0/133 | 0/97 → 0/133 |
| Correct missing-unit abstentions | 8/8 → 8/8 | 8/8 → 8/8 | 8/8 → 8/8 |
| Total tools / Company Facts reads | 140 / 0 → 141 / 0 | 119 / 119 → 155 / 155 | 204 / 119 → 211 / 155 |
| Evidence tokens | 18,161 → 19,158 | 5,499 → 8,374 | 11,449 → 14,324 |
| Warm latency p50/p95, ms | 4.50/100.69 → 4.41/90.95 | 8.51/18.04 → 10.31/26.43 | 16.03/111.93 → 11.35/90.28 |

All 64 new pair claims in each structured arm matched the frozen
references on signed value, unit, concept, CIK, full duration and
accession. The ledger recorded 32 current original observations and 32
unchanged comparative observations. Every pair used one cached Company
Facts read. The operating cash flow alias also recovered four single-period
lookups in both structured arms and two in document-only. All previous
releases kept their answers, citations and dispositions. Both structured
arms confirmed two of 16 multi-company questions. The nine narrative or
revision questions stayed withheld in every arm.
Semantic citation precision and faithfulness still require adjudication
on the mixed HTML cohort.

The document-only arm withheld the annual pairs because this path
requires matched original and comparative Company Facts observations.
The new path covers two consecutive years with a known earlier original
under the same concept. Missing, ambiguous or differently tagged prior
observations remain open. The case counts are development-exposed.

The latency table uses sequential runs with no other evaluation running.
The baseline and candidate took 26.86 s and 24.21 s with peak working sets
of 1,771,925,504 and 1,771,499,520 bytes. Both runs recorded zero hosted
calls, provider tokens and spend. All 612 non-timing predictions
reproduced for each version. Latency is descriptive on this host.

## Regression and reproduction

Windows passed 557 tests with three corpus skips. WSL passed 556 with
four. Ruff, focused mypy, the offline lock and deterministic claim and
citation fixtures passed. The historical architecture and fault replays
and all 122 stable numeric and narrative PDF-pilot outcomes matched.
New cases cover a revised comparative, a gap between durations, a wrong
accession, invalid dates and an incomplete draft with one supported year.

**KEEP** the accession-bound annual pair lookup and the exact
operating cash flow alias. Multi-company date binding remains open.

```text
python -m scripts.run_sec_mixed_runtime --manifest .local/g2/verified-replay/manifest.json --cache .local/g2/sec-cache --cohorts .local/g2/mixed-cohorts-final --output .local/g3/fiscal-year-pairs --threads 10 --reuse-vectors .local/g2/mixed-runtime-full
python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --reuse-pilot-vectors .local/g3/inline-runtime-full --narrative-controls --inline-facts .local/g2/verified-replay/facts --output .local/g3/fiscal-year-pairs-pilot
python -m scripts.run_specialist_architectures --faults --output .local/g3/fiscal-year-pairs-historical.json --manifest .local/g3/fiscal-year-pairs-historical-manifest.json
```

The [mixed replay](../.local/g3/fiscal-year-pairs/report.json) has SHA-256
`86901926b4d473110972fef9a64e16498e5aa714f21065c716f6f34d541dbc51`.
The [PDF replay](../.local/g3/fiscal-year-pairs-pilot/report.json) has
SHA-256 `2f95f7d20231698153af4e7142ec9b468ec9bfe92a4cc67f75d8fd44640b2cca`.
The [historical replay](../.local/g3/fiscal-year-pairs-historical.json)
has SHA-256 `3ebc2c4601e3aa7869f44c8fae8fa169abf7bc8e97973ecc39fcff6894e7895c`.
The sequential [baseline](../.local/g3/fiscal-year-pairs-baseline-timed/report.json)
and [candidate](../.local/g3/fiscal-year-pairs-timed/report.json) have SHA-256
`7c1d469db4fee2663b96776ce61cdd831044805f8944ec419d70dfdaf31f90db` and
`fda0a70e9738ba1f6724e9c3973ad2b4c3db9c46fe03da52f70cbb7d81be32a0`, respectively.
