# G3 accession-bound document balance sheets

## Protocol

Baseline `1c3b28f` confirmed 22 of 78 exact balance-sheet questions
in the document-only arm. The gaps include ascending year columns,
financial rows named only in the structured catalog and multi-issuer
requests that did not use the available statement lookup.

Read the consolidated balance sheet for each requested issuer and
exact SEC accession. Accept an ascending annual header only when
the current column aligns with the confirmed report end. Preserve
physical row and column numbers, currency and as-of date. Require
receivables and inventory to appear in current assets. Use explicitly
reported totals for current and noncurrent assets and current
liabilities. Accept equity only when the row clearly identifies the
parent total. Keep combined receivables and other assets, mixed
units, comparative drift and wrong filing locators as abstentions.

Replay all 204 frozen questions across the three source arms. Require
improved document-only numeric exactness with no new incorrect or
unconfirmed releases, all eight missing-unit controls withheld and
no lost prior confirmations. Review each added balance against the
cited filing block. Recheck the 122 PDF-pilot outcomes and historical
architecture and fault results. The document arm uses filing text
and table headers. Frozen Inline XBRL provides the separate numeric
reference.

## Implementation

The corpus map now retains SEC accessions. The planner scopes each
date-bound requirement to the issuer's named filing when the index
has that accession. The FAST route can make one bounded table lookup
per issuer. The existing statement reader handles both column orders
and keeps the physical row and column. It recognizes seven additional
balance-sheet measures only for exact annual filings. The evidence
analyzer then checks the report date, CIK, form, accession, SEC URL,
unit and statement location. The writer and verifier use the same
approved evidence through the existing ledger and release policy.

## Paired results and source review

| Measure on the frozen SEC mixed cohort | Baseline | Candidate |
| --- | ---: | ---: |
| Document-only confirmed balance-sheet questions | 22/78 | 75/78 |
| Document-only multi-issuer balances | 3/16 | 15/16 |
| Document-only single balance lookups | 14/47 | 46/47 |
| Document-only answerable balance controls | 5/15 | 14/15 |
| Document-only numeric confirmations across categories | 30/187 | 83/187 |
| Document-only releases across all cases | 39/204 | 92/204 |
| Company Facts-only and hybrid frozen numeric tag agreement | 187/187 each | 187/187 each |
| Missing-unit questions withheld | 8/8 per arm | 8/8 per arm |
| Document-only citation support and claim faithfulness on the reviewed balances | 25/25 each | 90/90 each |
| Incorrect or unsupported document-only releases on the reviewed balances | 0/22 | 0/75 |

Codex transcribed 48 distinct cited cells from eight archived 10-Ks
and checked all 90 candidate claims against their numbered citations.
The [review receipt](../.local/g3/document-balances-source-review.json)
records each issuer, archived filing hash, accession, balance date,
HTML block, row, column and value. Amazon and Alphabet use their later
column for the named report date. Microsoft's current net receivables
row reports USD 69,905 million after the allowance. All 53 added
answers passed source review. The descriptive Wilson upper risk bound
is 4.87% on 75 releases. Questions share issuers and cited cells, and
the set was used in development. The independent 5% risk target
remains inconclusive.
[Alphabet 10-K](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm) ·
[Microsoft 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm).

The three withheld balances include Amazon's current net receivables.
Its USD 55,451 million row is labeled “Accounts receivable, net and
other.” The filing notes that this includes prepayments and other
current assets. The issuer tags that cell as `AccountsReceivableNetCurrent`,
which both structured arms match. The current numeric tag benchmark
therefore counts those three matches. Their semantic reporting basis
remains unconfirmed and is flagged in the source receipt.
[Amazon balance-sheet row](https://www.sec.gov/Archives/edgar/data/1018724/000101872425000004/amzn-20241231.htm#f-256).

| Document-only resource measure across 204 questions | Baseline | Candidate |
| --- | ---: | ---: |
| Total tools | 146 | 176 |
| Statement lookups / Dense calls | 66 / 80 | 133 / 43 |
| Evidence tokens | 24,414 | 54,688 |
| Warm p50/p95, ms | 5.49/104.66 | 14.09/83.27 |

Both structured arms retained their previous non-timing results and
usage. The timed candidate finished in 21.17 s and peaked at
1,771,855,872 bytes. The recorded baseline took 26.03 s and peaked
at 1,771,290,624 bytes. Latency is descriptive on this host. Neither
run spent money or called a hosted model. Context Precision and Gold
Evidence Recall at 10 lack a common ranked candidate list here. The
statement reads are logged separately from the first Dense retrieval.

## Verification and reproduction

Windows passed 593 tests with three local-fixture skips. WSL passed
592 with four. Ruff, configured mypy, the dependency lock and
deterministic claim/citation checks passed. All 122 PDF-pilot results
and historical architecture and fault outcomes matched after excluding
timing and memory. Of 612 mixed runtime predictions, 553 matched on
all non-timing fields. The other 59 are document-only balance questions.
The new controls cover column order, wrong accession and CIK, mixed
units, duplicate rows, another reporting period, combined receivables
and equity containing noncontrolling interests.

**KEEP** the accession-scoped table path. Further work requires visible
line-item scope checks for structured tags and report-bound documents
for other financial metrics and periods.

```text
python -m scripts.run_sec_mixed_runtime --manifest .local/g2/verified-replay/manifest.json --cache .local/g2/sec-cache --cohorts .local/g2/mixed-cohorts-final --output .local/g3/document-balances-timed --threads 10 --reuse-vectors .local/g2/mixed-runtime-full
python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --reuse-pilot-vectors .local/g3/inline-runtime-full --narrative-controls --inline-facts .local/g2/verified-replay/facts --output .local/g3/document-balances-pilot
python -m scripts.run_specialist_architectures --faults --output .local/g3/document-balances-historical.json --manifest .local/g3/document-balances-historical-manifest.json
```

| Local artifact | SHA-256 |
| --- | --- |
| [Baseline replay](../.local/g3/cost-ticker-final/report.json) | `3b562f78c2422346662fc9b527694f8656410ff86645c0425eccd341c1352285` |
| [Mixed replay](../.local/g3/document-balances-timed/report.json) | `0a572f8bbfe2ebee1142f7a03d8317bac46be32b6e1662241156542e1385d240` |
| [Per-case source review](../.local/g3/document-balances-source-review.json) | `4448ae5ecee08dabf3298512de2685b5c9070e09381d419e7f331a535d152986` |
| [PDF pilot](../.local/g3/document-balances-pilot/report.json) | `e1330f62e6ab326e45d95c0b92d9c5d89c59499dc2bf98b6c6d31861097168bc` |
| [Historical architecture](../.local/g3/document-balances-historical.json) | `2630adbc4cf0eecf54cf9aad77f061471a340a1f5785127046775969cbd4f140` |
