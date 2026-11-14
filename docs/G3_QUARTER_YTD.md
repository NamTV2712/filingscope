# G3 quarter and YTD lookups by reporting end

## Evaluation protocol

The mixed SEC baseline withheld all 26 quarter/YTD questions. Recognize
the explicit standalone quarter and cumulative YTD request as two
duration slots sharing one report date and accession. Check that a
prior-year comparative or a standalone quarter cannot fill the
cumulative slot. Use the existing source and release policies.

Replay the same 204 questions across all three source arms. Require an
increase in fully confirmed quarter/YTD answers, no additional incorrect
release, and matching outcomes for the old PDF pilot and unrelated
questions. Report missing metrics and incomplete provenance separately.

## Implementation

A standalone-quarter and YTD question with a shared ISO end date and
explicit 10-Q accession creates separate duration requirements. The
Company Facts worker reads the issuer once and resolves each requirement
against that accession, date, form, currency and fiscal focus. The
coverage analyzer requires both starts, the same fiscal quarter and year,
compatible concepts and currencies, and an earlier start for the YTD
observation. The writer and atomic verifier associate each claim with
its own period. Release requires both claims and rechecks their cited
pair. The supported form covers Q2 and Q3, where the durations differ.
It uses the existing bounded FAST profile and evidence ledger.

## Matched results

| Measure | Document-only | Company Facts-only | Hybrid |
| --- | ---: | ---: | ---: |
| Confirmed quarter/YTD, pilot | 0/4 → 0/4 | 0/4 → 1/4 | 0/4 → 1/4 |
| Confirmed quarter/YTD, development | 0/12 → 0/12 | 0/12 → 5/12 | 0/12 → 5/12 |
| Confirmed quarter/YTD, validation | 0/10 → 0/10 | 0/10 → 3/10 | 0/10 → 3/10 |
| Confirmed numeric releases, all cases | 26/187 → 26/187 | 45/187 → 54/187 | 45/187 → 54/187 |
| Incorrect releases | 0/26 → 0/26 | 0/45 → 0/54 | 0/45 → 0/54 |
| Correct missing-unit abstentions | 8/8 → 8/8 | 8/8 → 8/8 | 8/8 → 8/8 |
| Total tools | 130 → 148 | 71 → 80 | 140 → 149 |
| Evidence tokens | 19,572 → 19,572 | 2,439 → 3,091 | 9,800 → 10,452 |
| Warm p50/p95, ms | 4.15/138.53 → 4.21/133.32 | 2.97/12.09 → 2.93/16.02 | 4.22/140.27 → 4.59/133.16 |

The other 17 quarter/YTD questions ask for concepts outside the current
metric registry. They remain unsupported. The document-only path tried
table and text retrieval on the nine recognized questions. It withheld
all nine because the HTML statement path did not establish both start
dates. The remaining 534 arm/case results matched on answers, claims,
citations, routes and dispositions. The 122 historic PDF-pilot outcomes
also matched on answers, dispositions, scores and sources.

Windows passed 546 tests with three corpus skips. WSL passed 545 with
four. Ruff, focused mypy, offline lock and deterministic claim fixture
checks passed. The new end-to-end fixture resolves both values with one
Company Facts read and abstains if the cumulative observation is from a
different accession. The matched run took 24.58 s at 1,769,512,960 bytes
peak with zero hosted calls, billed tokens or spend. Baseline `ba72b65`.

**KEEP** the date-bound quarter/YTD lookup. HTML start-date resolution
and additional metric mappings remain open. Independent evaluation
still awaits the reviewer bundle.

```text
python -m scripts.run_sec_mixed_runtime --manifest .local/g2/verified-replay/manifest.json --cache .local/g2/sec-cache --cohorts .local/g2/mixed-cohorts-final --output .local/g3/quarter-ytd --threads 10 --reuse-vectors .local/g2/mixed-runtime-full
```

The [mixed report](../.local/g3/quarter-ytd/report.json) has SHA-256
`03c65862a583bd938a087e4ff842099216c6cd0600d27589b8a30146bdc194b2`.
The [PDF replay](../.local/g3/quarter-ytd-pilot/report.json) has SHA-256
`8a54c36a4c8599450c5e67db0f078441cde67a6743e525f316b25ad2d5f46b92`.
