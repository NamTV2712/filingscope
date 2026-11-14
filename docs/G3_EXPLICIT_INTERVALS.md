# G3 explicit reporting intervals

## Evaluation protocol

The frozen mixed SEC replay found five single-interval questions with
unrequested prior-year figures in the document and hybrid arms. Keep
the questions and sources fixed. Represent an explicit ISO date range
as one exact interval. Verify only against provenance that establishes
both dates and any explicitly requested accession. Reject ambiguous
combinations and contradictory dates. Test mismatched and unavailable
dates, off-scope claims, and historical fiscal-year queries.

Require the five extra-year errors to disappear, no new unexpected
release, and consistent historic PDF pilot outputs. Measure how many
complete answers the exact-interval path can recover on the same mixed
control. Review any differences and report per-arm coverage and risk.

## Implementation

The requirement extractor maps a single `from YYYY-MM-DD to YYYY-MM-DD`
range to one typed duration and preserves an explicit accession. It
requests clarification when a range is malformed, reversed or combined
with another period or operation outside the supported scope. The same
coverage analyzer enforces both dates on typed facts. Company Facts
queries match the exact interval and requested accession and retain fiscal
focus, form, unit and revision checks. For consolidated annual statement
tables, the parser can infer a start from the previous adjacent fiscal
year-end when the heading establishes an annual duration and the current
end matches accession-bound filing metadata. Missing dates do not pass.
The atomic verifier checks each cited fact against the requested interval.
The release policy allows one matching claim for this lookup.

## Matched results

| Measure | Document-only | Company Facts-only | Hybrid |
| --- | ---: | ---: | ---: |
| Confirmed numeric releases | 20/187 → 26/187 | 37/187 → 45/187 | 37/187 → 45/187 |
| Coverage | 26/204 → 26/204 | 37/204 → 45/204 | 42/204 → 45/204 |
| Extra or wrong claims among releases | 5/26 → 0/26 | 0/37 → 0/45 | 5/42 → 0/45 |
| Unconfirmed evidence identity among releases | 1/26 → 0/26 | 0/37 → 0/45 | 0/42 → 0/45 |
| Correct missing-unit abstentions | 8/8 → 8/8 | 8/8 → 8/8 | 8/8 → 8/8 |
| Answerable questions withheld | 170/196 → 170/196 | 159/196 → 151/196 | 154/196 → 151/196 |
| Tools | 136 → 130 | 65 → 71 | 151 → 140 |
| Evidence tokens | 22,405 → 19,572 | 2,373 → 2,439 | 14,883 → 9,800 |
| Warm p50/p95, ms | 3.81/128.49 → 4.15/138.53 | 2.66/10.78 → 2.97/12.09 | 3.12/138.91 → 4.22/140.27 |

The Apple question for 2024-09-29 through 2025-09-27 now releases only
FY2025 operating income of USD 133.05 billion. The Coca-Cola table
now supplies the start date from its previous annual column. Every
changed prediction in the 612-run comparison came from an explicit
range question. All 122 prior PDF-pilot outcomes retained their
answers, dispositions, scores and sources. The candidate reused the
same vectors, took 23.73 s and peaked at 1,769,705,472 bytes. Provider
calls, billed tokens and cost were zero.

Windows passed 544 tests with 3 corpus skips. WSL passed 543 with 4.
Ruff, focused mypy, the offline lock check and the deterministic claim
and citation fixture passed. New controls cover wrong accessions,
missing dates, invalid and ambiguous ranges, and distinct quarter and
YTD intervals. Baseline commit `185e2bc`.

**KEEP** exact-range lookups. The measured gain applies to the frozen
mixed cohort. The existing date-only quarter/YTD comparisons and
issuer-specific multi-period assignment remain open. G6 still requires
reviewer-held data.

```text
python -m scripts.run_sec_mixed_runtime --manifest .local/g2/verified-replay/manifest.json --cache .local/g2/sec-cache --cohorts .local/g2/mixed-cohorts-final --output .local/g3/explicit-interval --threads 10 --reuse-vectors .local/g2/mixed-runtime-full
```

The [mixed replay](../.local/g3/explicit-interval/report.json) has SHA-256
`ac3dda48aeced72a09f11c93b16e6e5253a953e7a18ea9ddc96909f06801d42f`.
The [PDF regression](../.local/g3/explicit-interval-pilot/report.json)
has SHA-256 `79eca459edaa18c147aa65d0f2affa79a5f61629ab8f48841001ef9ef77e5ea2`.
