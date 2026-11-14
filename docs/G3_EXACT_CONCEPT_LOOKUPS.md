# G3 exact concept lookups for remaining duration requests

## Evaluation protocol

Baseline `8325823` confirmed 182 of 187 numeric questions with either
structured arm. The other five requests specify operating expenses,
payments to acquire property, plant and equipment, or revenue from
contracts with customers. Verify each against the exact Company Facts
tag and the accession-matched iXBRL reference. Walmart’s 2025 10-K
reports USD 674,538 million as net sales and USD 680,985 million as total
revenues. Test that requesting the contract revenue concept selects the
former and that an unspecified revenue request retains its existing
conflict handling. [Walmart 2025 Form 10-K, consolidated income](https://www.sec.gov/Archives/edgar/data/104169/000010416925000021/R3.htm).

Require improved confirmed releases with unchanged existing correct
answers, no new incorrect or unconfirmed release, and all missing-unit
controls preserved. Replay the matched mixed and historical PDF
cohorts and the specialist architecture and fault controls.

## Implementation

Add the exact `OperatingExpenses` and
`RevenueFromContractWithCustomerExcludingAssessedTax` measures to the
existing structured lookup. The line-item wording for payments to
acquire property, plant and equipment resolves the existing capital
expenditures measure. The extractor and verifier associate the full
contract revenue phrase with its own measure and keep its nested words
out of generic revenue and customer aliases. Unsupported qualifiers
still block release. The scorer checks the requested concept against the
record's metric map, which permits a reviewed tag to serve both a
generic lookup and an explicit concept lookup.

Microsoft’s 2025 10-K gives operating expenses of USD 65,365 million
for the full year ended 2025-06-30. Both Microsoft questions cite that
observation. [Microsoft 2025 Form 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm).

## Matched results

| Measure | Document-only | Company Facts-only | Hybrid |
| --- | ---: | ---: | ---: |
| Confirmed numeric releases, pilot | 4/28 → 4/28 | 28/28 → 28/28 | 28/28 → 28/28 |
| Confirmed numeric releases, development | 11/94 → 11/94 | 90/94 → 94/94 | 90/94 → 94/94 |
| Confirmed numeric releases, validation | 15/65 → 15/65 | 64/65 → 65/65 | 64/65 → 65/65 |
| Confirmed numeric releases, overall | 30/187 → 30/187 | 182/187 → 187/187 | 182/187 → 187/187 |
| Answer coverage | 30/204 → 30/204 | 182/204 → 187/204 | 182/204 → 187/204 |
| Answerable questions withheld | 166/196 → 166/196 | 14/196 → 9/196 | 14/196 → 9/196 |
| Incorrect or unconfirmed releases | 0/30 → 0/30 | 0/182 → 0/187 | 0/182 → 0/187 |
| Correct missing-unit abstentions | 8/8 → 8/8 | 8/8 → 8/8 | 8/8 → 8/8 |
| Total tools / Company Facts reads | 141 / 0 → 145 / 0 | 206 / 206 → 211 / 211 | 230 / 206 → 235 / 211 |
| Evidence tokens | 18,164 → 18,164 | 10,003 → 10,193 | 10,003 → 10,193 |
| Warm p50/p95, ms | 4.79/96.82 → 5.11/98.92 | 10.82/27.87 → 11.38/27.49 | 15.68/63.81 → 14.86/65.22 |

All five new answers in each structured arm matched exact cited facts.
Previous released answers, dispositions, routes, claims and citation
IDs matched. The document-only arm attempted both newly recognized
capital expenditure lookups and found no supporting typed duration.
All nine narrative or revision questions stayed withheld. The numeric
replay shares the underlying public SEC facts with the reference.
The measurements establish runtime identity matching on this exposed
cohort. Independent scoring and mixed HTML semantic adjudication remain
open.

The candidate took 24.35 s at 1,771,630,592 bytes peak. Neither run had
model-provider calls, billed tokens or spend. Latency is descriptive on
this host.

## Regression and reproduction

Windows passed 565 tests with three corpus skips and WSL passed 564
with four. Ruff, focused mypy, the offline lock, and deterministic claim
and citation checks passed. All 122 numeric and narrative PDF pilot
outcomes and the historical architecture and fault results matched.
The new adversarial control exercises a conflicting same-filing tag and
an explicit incompatible tax basis.

**KEEP** the exact concept routes and the verified capital expenditure
wording. The deterministic evidence policy retains release authority.

```text
python -m scripts.run_sec_mixed_runtime --manifest .local/g2/verified-replay/manifest.json --cache .local/g2/sec-cache --cohorts .local/g2/mixed-cohorts-final --output .local/g3/exact-concepts-timed --threads 10 --reuse-vectors .local/g2/mixed-runtime-full
python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --reuse-pilot-vectors .local/g3/inline-runtime-full --narrative-controls --inline-facts .local/g2/verified-replay/facts --output .local/g3/exact-concepts-pilot
python -m scripts.run_specialist_architectures --faults --output .local/g3/exact-concepts-historical.json --manifest .local/g3/exact-concepts-historical-manifest.json
```

| Replay | SHA-256 |
| --- | --- |
| [Mixed candidate](../.local/g3/exact-concepts-timed/report.json) | `fdbd60407935dd15380b3f3479fdd383bde9f83478551c387b72f325fe85da53` |
| [PDF pilot](../.local/g3/exact-concepts-pilot/report.json) | `30c2878446b26a9923a8fa80527f45fa65456a0878b80dcf115d493b3469cd95` |
| [Historical architecture](../.local/g3/exact-concepts-historical.json) | `446bca8c43f97da0efd844492aeeb6444692bdcf885bc0c315b76cc23195c989` |
