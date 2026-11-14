# G3 accession-bound balance sheet dates

## Evaluation protocol

Baseline `705db9b` confirmed 2/16 multi-company questions with
Company Facts and hybrid, and 1/16 using document-only. Each question
requests a consolidated balance-sheet measure at a separate date and
filing for each issuer. The generic multi-company plan combines both
issuers with both fiscal years on requests spanning different years.
Fiscal-year labels alone also lose the exact dates for issuers with
different fiscal year ends in the same calendar year.

Map issuer, date and accession into one slot per requested balance.
Use the same runtime for one issuer or two. Check the 32 multi-company
slots and the 62 single-issuer as-of references against the frozen
Company Facts payloads and Inline XBRL receipts. Introduce only the
seven missing balance-sheet concepts represented by those observations.
Require both requested claims when listing two companies. Reject wrong
accessions, dates, currencies, duration rows and unbound issuers.

Compare with the baseline on all 204 mixed questions across the three
source arms. Require increased confirmed numeric coverage and zero
additional incorrect or unconfirmed releases. Recheck the earlier PDF
pilot, historical architecture and fault replays, and the eight
missing-unit controls.

## Implementation

The extractor binds an ISO as-of date and 10-K accession to the
preceding issuer. The planner produces one requirement for each issuer,
including when both filing dates fall in the same fiscal year. One or
two original annual balance-sheet observations can run through the
existing bounded FAST XBRL lookup. The document path can supply a
normalized statement row when its source and instant match precisely.
The writer displays the issuer ticker and exact observation date.
The verifier checks the rendered date and cited accession for each
claim and requires every requested claim before release.

| Balance-sheet measure | US-GAAP concept |
| --- | --- |
| Current net accounts receivable | `AccountsReceivableNetCurrent` |
| Current assets | `AssetsCurrent` |
| Noncurrent assets | `AssetsNoncurrent` |
| Current liabilities | `LiabilitiesCurrent` |
| Net inventory | `InventoryNet` |
| Net property, plant and equipment | `PropertyPlantAndEquipmentNet` |
| Equity attributable to the parent | `StockholdersEquity` |

These seven concepts require typed XBRL. For example, Microsoft's
balance sheet shows USD 69,905 million in current net receivables
as of June 30, 2025. The filing discusses its long-term receivables
separately. Walmart's fiscal 2025 balance sheet is dated January 31,
2025. These different dates are preserved in the ledger and citations.
[Microsoft 2025 Form 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm) · [Walmart 2025 Form 10-K](https://www.sec.gov/Archives/edgar/data/104169/000010416925000021/wmt-20250131.htm).

## Matched results

| Measure | Document-only | Company Facts-only | Hybrid |
| --- | ---: | ---: | ---: |
| Confirmed multi-company, pilot | 0/4 → 0/4 | 0/4 → 4/4 | 0/4 → 4/4 |
| Confirmed multi-company, development | 0/6 → 0/6 | 1/6 → 6/6 | 1/6 → 6/6 |
| Confirmed multi-company, validation | 1/6 → 3/6 | 1/6 → 6/6 | 1/6 → 6/6 |
| Confirmed numeric releases, overall | 28/187 → 30/187 | 133/187 → 182/187 | 133/187 → 182/187 |
| Answer coverage | 28/204 → 30/204 | 133/204 → 182/204 | 133/204 → 182/204 |
| Answerable questions withheld | 168/196 → 166/196 | 63/196 → 14/196 | 63/196 → 14/196 |
| Incorrect or unconfirmed releases | 0/28 → 0/30 | 0/133 → 0/182 | 0/133 → 0/182 |
| Correct missing-unit abstentions | 8/8 → 8/8 | 8/8 → 8/8 | 8/8 → 8/8 |
| Total tools / Company Facts reads | 141 / 0 → 141 / 0 | 155 / 155 → 206 / 206 | 211 / 155 → 230 / 206 |
| Evidence tokens | 19,158 → 18,164 | 8,374 → 10,003 | 14,324 → 10,003 |
| Warm p50/p95, ms | 4.58/93.76 → 4.79/96.82 | 9.71/26.29 → 10.82/27.87 | 15.14/85.81 → 15.68/63.81 |

The structured arms added 14 cross-company answers, 28 single lookups
and seven answerable hard negatives. All 94 released as-of claims per
structured arm matched the reference observation and its SEC filing.
The two previously confirmed structured and one document-only
multi-company answers stayed confirmed. Each structured company pair
used two cached Company Facts reads. The writer uses the ticker for
these claims to disambiguate the corpus-backed GOOG identity from
other Alphabet aliases. All previous confirmed results stayed
confirmed. The other previous numeric answers, their claim checks and
their citations matched exactly.

Each structured arm still withheld five numeric questions about
operating expenses, property and equipment purchases and a specific
contract revenue tag. Nine narrative or revision questions await
source review. Semantic citation precision and faithfulness require
broader judgments on the mixed HTML corpus. Evidence identity counts
are descriptive on the frozen development-exposed cohort.

Sequential runs took 24.38 s and 23.98 s with peak working sets of
1,772,843,008 and 1,772,343,296 bytes. Both had zero hosted calls,
provider tokens and spend. Latency is descriptive on this host.

## Regression and reproduction

Windows passed 564 tests with three corpus skips. WSL passed 563 with
four. Ruff, focused mypy, the offline dependency lock and deterministic
claim and citation checks passed. All 122 stable PDF-pilot outcomes
matched. Historical M13, direct, complex, narrative and fault outcomes
matched. New fixtures exercise a missing or wrong issuer filing, wrong
date or currency, duration masquerading as a balance, and a date in a
rendered claim that disagrees with its cited observation.

**KEEP** exact issuer-specific annual balances and the seven measure
mappings. The release remains governed by deterministic evidence checks.

```text
python -m scripts.run_sec_mixed_runtime --manifest .local/g2/verified-replay/manifest.json --cache .local/g2/sec-cache --cohorts .local/g2/mixed-cohorts-final --output .local/g3/filing-instants-timed --threads 10 --reuse-vectors .local/g2/mixed-runtime-full
python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --reuse-pilot-vectors .local/g3/inline-runtime-full --narrative-controls --inline-facts .local/g2/verified-replay/facts --output .local/g3/filing-instants-pilot
python -m scripts.run_specialist_architectures --faults --output .local/g3/filing-instants-historical.json --manifest .local/g3/filing-instants-historical-manifest.json
```

| Replay | SHA-256 |
| --- | --- |
| [Mixed baseline](../.local/g3/filing-instants-baseline-timed/report.json) | `38fcf44f35e11f4d740add7a02dc6c4a110ddf5e023797847fd72d427de373bd` |
| [Mixed candidate](../.local/g3/filing-instants-timed/report.json) | `98d6abba1edb7ffb318d65720556cb9821c7fcd992f897e4dfb8e7b5d7142b31` |
| [PDF pilot](../.local/g3/filing-instants-pilot/report.json) | `ac55655abfabbdf1b06ac7553b87da7aaba4d5692898cd0f683568c55ba28eef` |
| [Historical architecture](../.local/g3/filing-instants-historical.json) | `755001f2dd2a3ae99f41285bff1123899bb1e84c16832d8b58d83e95768ac564` |
