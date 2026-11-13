# G3 follow-up on segment reporting scope

The G2 source-track pilot found that all three arms released Tesla's
consolidated FY2024 revenue for the energy generation and storage
business. The pilot is the pre-change baseline. The follow-up tests
whether the existing reporting-basis guard can withhold that answer
when the runtime lacks dimension-qualified evidence.

Keep the 26 original questions, gold cells, filing snapshots and
index fixed. Require zero consolidated releases on the segment case,
exact agreement in release and score on the other 25 questions, and
unchanged outcomes on the historical architecture replay. Include
ordinary consolidated-revenue questions as positive controls. A
segment abstention remains a false abstention in the pilot score.

Walmart's FY2025 revenue miss has a separate cause. The same Company
Facts accession and interval report USD 674,538 million under
`RevenueFromContractWithCustomerExcludingAssessedTax` and USD
680,985 million under `Revenues`. The PDF reports the larger value
as total revenues. The structured resolver conservatively rejects the
concept disagreement. Resolution requires evidence that distinguishes
net sales from total revenue across issuers.

## Change and conformance

The shared requirement predicate now recognizes explicit segment wording
and the observed energy generation and storage label. The existing router
avoids direct entity-wide lookup for these questions, and the deterministic
sufficiency gate withholds a quantitative answer when the reporting basis
cannot be verified. The change applies to the observed scope and explicit
segment wording. A broader vocabulary and dimension-aware resolution still
need labeled examples and source bindings.

## Paired results

All three tracks withheld the consolidated value. The other 25 questions
matched in every recorded case field except latency. The baseline and
candidate have identical reference, extracted page, chunk, vector and
Company Facts snapshot hashes. The candidate replay reused the frozen
normalized vectors and ran the same local Nomic model for query embedding.

| Outcome | PDF only, before → after | Company Facts only, before → after | Hybrid, before → after |
| --- | ---: | ---: | ---: |
| Grounded exact | 3/23 → 3/23 | 21/23 → 21/23 | 21/23 → 21/23 |
| Releases failing grounded exact | 2/5 → 1/4 | 1/22 → 0/21 | 1/22 → 0/21 |
| False abstentions | 18/23 → 19/23 | 1/23 → 2/23 | 1/23 → 2/23 |
| Coverage | 5/26 → 4/26 | 22/26 → 21/26 | 22/26 → 21/26 |
| Total tools | 53 → 53 | 27 → 26 | 47 → 47 |
| Mean evidence tokens | 84.46 → 67.65 | 32.96 → 31.46 | 32.96 → 31.46 |
| Warm p50 / p95 (ms) | 57.02 / 267.30 → 49.01 / 248.45 | 9.20 / 16.48 → 9.11 / 13.39 | 11.70 / 268.51 → 8.57 / 268.34 |

Peak working set was 1,904,029,696 B for the cached-vector candidate.
The baseline included document embedding. Warm latency comes from single
runs. Hosted calls, billed tokens and spend were zero. The remaining
PDF locator miss is the alternate Apple net-income citation documented
in the [G2 runtime pilot](G2_RUNTIME_REPLAY.md#failure-analysis).

The three new graph controls exercised both explicit and named segment
wording with each source inventory, plus ordinary Tesla revenue. The
focused run passed 44 tests. Full offline verification passed 466 tests
on Windows with 3 local fixture skips and 465 on Linux WSL with 4 skips.
Ruff passed. The historical architecture report matched stable outcomes,
including M13 routed grounded exact 21/21 and incorrect releases 0/21.

## Decision and reproduction

**KEEP** the deterministic scope guard. **DEFER** release of the actual
segment value until the runtime can verify the segment identity. The
pilot remains development-exposed. The observed zero errors on 21
released answers leave the 5% independent risk target unresolved.

Baseline Git SHA `4870471cdd5249e95764a404723e90b6cced5c44`.
Rebuild the candidate index and run the replay with the [G2
commands](G2_RUNTIME_REPLAY.md#reproduce). The [local paired candidate
report](../.local/g2/runtime-pilot-scope/report.json) has SHA-256
`d5b974ad88c87763daa2f5f39eefa6f6b154c7e3975fcbbc77765dcb2997669d`.
