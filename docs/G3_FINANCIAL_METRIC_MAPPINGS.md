# G3 financial metric mappings

## Evaluation protocol

The 26 quarter/YTD questions produced nine confirmed pairs. The other
17 ask for seven US-GAAP concepts absent from the runtime vocabulary.
Check their issuer, form, units, periods and accessions in the frozen
Inline XBRL and Company Facts snapshots. Map only the verified concepts.
Test negative cash flow, quarter versus YTD, scope qualifiers and cost of
revenue versus revenue. Preserve established metric meanings and reject
unsupported qualifiers rather than substituting a consolidated value.

Replay all 204 questions across the three source configurations using
the pinned vectors and unchanged references. Compare against commit
`959c68d`. Require an increase in confirmed numeric releases, no new
incorrect release or unsupported negative-control answer, and matching
historic PDF-pilot outcomes. Inspect every changed release and retain
failures in the report.

## Implementation

The 34 missing USD observations agreed between the frozen Company
Facts snapshots and accession-matched Inline XBRL. The registry now
maps each supported consolidated measure to an exact US-GAAP concept.
The counts below are the previously withheld quarter/YTD questions
covered by each mapping. [FASB US-GAAP taxonomy](https://fasb.org/page/detail?pageId=%2Fprojects%2FFASB-Taxonomies%2F2025-gaap-financial-reporting-taxonomy.html).

| Measure | US-GAAP concept | Pairs |
| --- | --- | ---: |
| Cost of revenue | `CostOfRevenue` | 4 |
| Income tax expense | `IncomeTaxExpenseBenefit` | 3 |
| Pretax income from continuing operations | `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest` | 6 |
| Research and development expense | `ResearchAndDevelopmentExpense` | 1 |
| Selling, general and administrative expense | `SellingGeneralAndAdministrativeExpense` | 1 |
| Net investing cash flow | `NetCashProvidedByUsedInInvestingActivities` | 1 |
| Net financing cash flow | `NetCashProvidedByUsedInFinancingActivities` | 1 |

Requirement extraction preserves explicit Costco issuer mentions and
ignores the embedded `COST` and revenue aliases in the expense label.
The router skips retrieval for requests limited to these measures when
the requested issuers lack a structured source. Evidence coverage
requires the typed XBRL concept and rejects unsupported component
scopes such as current or deferred tax. The atomic verifier also
checks the scope of each generated assertion. The numeric parser
preserves negative currency amounts written with a sign before the
currency marker or with surrounding accounting parentheses.

The Amazon 10-Q provides a signed control. The quarter and YTD
financing amounts are USD −44 million and −2,630 million, respectively.
Both claims retain their own durations and cite the filing index for the
correct accession. [Amazon Consolidated Statements of Cash Flows](https://www.sec.gov/Archives/edgar/data/1018724/000101872425000123/amzn-20250930.htm).

## Matched results

| Measure | Document-only | Company Facts-only | Hybrid |
| --- | ---: | ---: | ---: |
| Confirmed quarter/YTD, pilot | 0/4 → 0/4 | 1/4 → 4/4 | 1/4 → 4/4 |
| Confirmed quarter/YTD, development | 0/12 → 0/12 | 5/12 → 12/12 | 5/12 → 12/12 |
| Confirmed quarter/YTD, validation | 0/10 → 0/10 | 3/10 → 10/10 | 3/10 → 10/10 |
| Confirmed numeric releases, pilot | 4/28 → 4/28 | 9/28 → 12/28 | 9/28 → 12/28 |
| Confirmed numeric releases, development | 10/94 → 10/94 | 28/94 → 49/94 | 28/94 → 49/94 |
| Confirmed numeric releases, validation | 12/65 → 12/65 | 17/65 → 36/65 | 17/65 → 36/65 |
| Confirmed numeric releases, overall | 26/187 → 26/187 | 54/187 → 97/187 | 54/187 → 97/187 |
| Answer coverage | 26/204 → 26/204 | 54/204 → 97/204 | 54/204 → 97/204 |
| Answerable questions withheld | 170/196 → 170/196 | 142/196 → 99/196 | 142/196 → 99/196 |
| Incorrect or unconfirmed releases | 0/26 → 0/26 | 0/54 → 0/97 | 0/54 → 0/97 |
| Correct missing-unit abstentions | 8/8 → 8/8 | 8/8 → 8/8 | 8/8 → 8/8 |
| Narrative or revision reference excerpts retrieved | 6/9 → 6/9 | 0/9 → 0/9 | 6/9 → 6/9 |
| Total tools / Company Facts reads | 148 / 0 → 140 / 0 | 80 / 80 → 119 / 119 | 149 / 80 → 204 / 119 |
| Evidence tokens | 19,572 → 18,161 | 3,091 → 5,499 | 10,452 → 11,449 |
| Warm p50/p95, ms | 4.21/133.32 → 4.35/81.63 | 2.93/16.02 → 8.04/15.53 | 4.59/133.16 → 10.97/86.11 |

The structured arms added 17 quarter/YTD, 23 single-period lookups and
three answerable hard negatives. All 60 newly released numeric claims
per structured arm matched a distinct reference observation on value,
unit, concept, CIK, duration and accession. Each source linked to the
corresponding EDGAR filing index. All previously released answers
kept their claims, citations and dispositions. The nine narrative and
revision questions remained withheld. Context Precision@10 and
semantic faithfulness await broader evidence judgments on the mixed
HTML corpus.

The first candidate recognized the new measures in the document-only
arm and raised usage from 148 to 250 tools without recovering a case.
The source check reduced that count to 140. The structured-only arm
added 39 Company Facts reads, and hybrid also added 16 text retrieval
calls. Each structured arm routed 24 date-anchored multi-period
questions with the expanded vocabulary. All 32 multi-period questions
remained withheld. Date-bound annual pairs and HTML statement duration
starts remain open. Warm latencies are descriptive single-host values.
The guarded run took 23.35 s and peaked at 1,770,348,544 bytes with zero
model-provider calls, billed tokens or spend.

## Regression and reproduction

The offline checks passed 550 tests on Windows with three fixture skips
and 549 on WSL with four. Deterministic claim and citation fixtures,
Ruff, focused mypy and the offline lock check passed. The 104 PDF numeric
and 18 narrative arm/case outputs matched all stable fields. The M13,
direct, complex, narrative and fault replays matched the previous
architecture outcomes after excluding timings and memory.

**KEEP** the seven scoped concept mappings and source check. Coverage
and release quality are measured on development-exposed data. G6
independent scoring awaits a reviewer-held cohort.

```text
python -m scripts.run_sec_mixed_runtime --manifest .local/g2/verified-replay/manifest.json --cache .local/g2/sec-cache --cohorts .local/g2/mixed-cohorts-final --output .local/g3/metric-mappings-guarded --threads 10 --reuse-vectors .local/g2/mixed-runtime-full
python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --reuse-pilot-vectors .local/g3/inline-runtime-full --narrative-controls --inline-facts .local/g2/verified-replay/facts --output .local/g3/metric-mappings-pilot-final
python -m scripts.run_specialist_architectures --faults --output .local/g3/metric-mappings-historical-final.json --manifest .local/g3/metric-mappings-historical-final-manifest.json
```

The [mixed report](../.local/g3/metric-mappings-guarded/report.json) has
SHA-256 `f57b945c644a5fd87f7f84fc25d66b5f345b9209966f84af45df9d4306d4ae03`.
The [PDF replay](../.local/g3/metric-mappings-pilot-final/report.json) has
SHA-256 `8c68501e0d76fe15c24ff9ece274050df92feb6a76154b5b669ae15d74853faa`.
The [historical replay](../.local/g3/metric-mappings-historical-final.json)
has SHA-256 `8fa0d06db1cc08e8cbc5f0b5d9dae52b259c9926709eb991b4233ba7aeabe1f8`.
