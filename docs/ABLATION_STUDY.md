# A0–A5 ablation study

All six variants use the same 150 cases, pinned P1 corpus, and frozen answer prompt. Each row adds one component to the preceding variant. A5 reuses A4 answers and applies the claim verifier as an output gate.

Quality and latency columns below use the held-out split. Calls and modeled cost columns count responses used by the completed benchmark run; they exclude any abandoned provider attempts listed in the results header.

| Variant | Enabled component | Coverage | Text token F1 | Numeric exact | Citation validity | p95 ms | Calls | Cost USD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A0 | Dense retrieval + generator | 44.4% | 11.6% | 0.0% | 100.0% | 7751.3 | 150 | $0.12828405 |
| A1 | Hybrid retrieval + generator | 35.6% | 16.4% | 0.0% | 85.2% | 10798.4 | 150 | $0.12559665 |
| A2 | Hybrid retrieval + reranker + generator | 40.0% | 17.9% | 0.0% | 100.0% | 7803.7 | 150 | $0.09421350 |
| A3 | A2 + evidence decision | 0.0% | 7.4% | 0.0% | n/a | 2487.9 | 5 | $0.00344670 |
| A4 | A3 + adaptive retrieval | 0.0% | 7.4% | 0.0% | n/a | 4067.4 | 5 | $0.00344610 |
| A5 | A4 + claim verification gate | 0.0% | 7.4% | 0.0% | n/a | 4067.4 | 0 | $0 |

| Transition | Change in answer token F1 | Change in coverage | Change in numeric exact accuracy |
|---|---:|---:|---:|
| A0 → A1 | +4.8 pp | -8.9 pp | +0.0 pp |
| A1 → A2 | +1.5 pp | +4.4 pp | +0.0 pp |
| A2 → A3 | -10.6 pp | -40.0 pp | +0.0 pp |
| A3 → A4 | +0.0 pp | +0.0 pp | +0.0 pp |
| A4 → A5 | +0.0 pp | +0.0 pp | +0.0 pp |

These differences are descriptive for this pinned public sample. They are not a significance test. Text metrics are lexical agreement measures, and the evidence-page abstention proxy can misclassify cases where alternate evidence pages support the answer.

## M13 research workflow ablation

The M13 experiment uses 24 fixed questions with eight each in development,
validation and held-out. Issuers are grouped by split. Cases include simple
lookup, multiple statements in one filing, numerical differences and growth,
multiple filings and issuers, explicit revision basis, hard negatives, a
contradictory premise, an absent company and an instruction to invent a
forecast. For each expected value, the labels name the issuer, metric, period
and permitted source pages or original SEC accessions. Growth labels require
the two endpoint sources. Questions and provenance labels are in
`configs/multi_agent_ablation.py`.

The experiment uses the full P1 corpus and pinned Nomic vectors. Every
variant uses the deterministic FilingScope report writer. The two ungated
retrieval baselines may render an available value from a conflicted or
incomplete finding. This exposes the risk of releasing retrieved facts
without a sufficiency decision. The M13 A variants below are separate
runs from the hosted-generator P5 results above.

| M13 variant | Active workflow |
|---|---|
| A0 | Dense and the deterministic writer |
| A1 | A0 with the fixed M12 query-metadata mask |
| A2 | A0 with evidence sufficiency |
| A3 | A2 with bounded P3 adaptive retrieval |
| A4 | A3 with candidate policy and M11 release |
| B0 | M5 route selection and a bounded solo adaptive path with candidate policy |
| B1 | Force supported requests through RESEARCH using question-only tasks, the ledger, and candidate policy |
| B2 | B1 with the Corpus Map and adapter-level document scopes |
| B3 | B2 with offline SEC Company Facts |
| B4 | B3 with the M11 release policy |
| B5 | B4 with normal FAST/RESEARCH routing |

All earlier variants run P4 claim checks as diagnostics. A4, B4 and B5 apply
the M11 answer-release decision. The B1–B5 variants execute the actual
specialist graph. The retrieval adapter locks model inference while allowing
the independent worker calls and ranking to use separate threads. Its
document scopes come from planner tasks. The same catalog resolves issuers
through routing, sufficiency and verification. Candidate policy results are
inspectable through the specialist execution contract. It retains weak
observations for the downstream sufficiency gate and preserves comparative
periods when the document year differs from the fact period.

The SEC snapshot contains nine issuers with rows filed through December 31,
2024. The acquisition made nine public HTTP requests. The measured runs use
the hash-verified local snapshots and the actual fiscal and revision
resolver. The output distinguishes local replay calls, filing retrieval,
provider calls, and evidence tokens. Local SEC calls are timed as local
reads. [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

The scorer matches rendered values and units with the independently labeled
company, metric and period. Grounded exactness also requires the correct
source location for each claim. It tracks coverage and risk separately.
Task success counts planned tasks whose requirement slots are present in
final coverage. Handoff links count resolved verification evidence IDs.
Gap resolution compares the initial filing evidence with final coverage.
The comparison measures the frozen local workload and does not measure
hosted generation, network latency, or performance across all filings.

### Results

| Variant | Grounded exact / 21 answerable | Answers / 24 | Unsupported release rate | Source-location coverage | Retrieval / case | Tool calls / case | p50 / p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| A0 | 0 | 15 | 1.0000 | 0.4048 | 1.0000 | 1.0000 | 65.250 / 95.218 |
| A1 | 0 | 17 | 1.0000 | 0.5238 | 1.0000 | 1.0000 | 61.206 / 93.496 |
| A2 | 0 | 0 | — | 0.4048 | 1.0000 | 1.0000 | 62.029 / 82.473 |
| A3 | 0 | 0 | — | 0.4048 | 1.9583 | 1.9583 | 143.811 / 230.953 |
| A4 | 0 | 0 | — | 0.4048 | 1.9583 | 1.9583 | 176.478 / 291.542 |
| B0 | 0 | 0 | — | 0.0000 | 0.4167 | 0.4167 | 1.633 / 179.381 |
| B1 | 0 | 0 | — | 0.0000 | 0.5417 | 0.5417 | 1.901 / 115.935 |
| B2 | 0 | 0 | — | 0.6190 | 1.7917 | 1.7917 | 122.588 / 250.120 |
| B3 | 3 | 3 | 0.0000 | 1.0000 | 1.7917 | 2.7500 | 131.651 / 318.524 |
| B4 | 3 | 3 | 0.0000 | 1.0000 | 1.7917 | 2.7500 | 112.588 / 260.433 |
| B5 | 1 | 1 | 0.0000 | 0.7143 | 0.9167 | 1.0833 | 66.178 / 170.972 |

Numerical exact and grounded exact agreed on all variants. The three
grounded B3/B4 answers were Best Buy FY2019 assets, Apple FY2024 original
revenue, and Microsoft FY2024 revenue. B5 preserved the Apple answer.
Held-out grounded accuracy was 2/7 for B3/B4 and 1/7 for B5. The gated
variants correctly withheld all three unanswerable cases. False abstention
among the 21 answerable questions was 18/21 for B3/B4 and 20/21 for B5.
The unsupported-release rate has no denominator for variants that emitted
zero answers. Empirical risk at coverage was 1.0 for A0/A1 and 0.0 for
B3/B4/B5. The small number of released answers limits interpretation.

B0 and B1 skipped 19 requests because the question-only catalog or route
could not resolve them. B2 used the local inventory and searched on 22 cases.
B4 resolved six of 31 missing or conflicted filing slots and completed six
of 31 linked tasks. B5 resolved four and completed four. Verification links
resolved in the ledger for all reported B3/B4/B5 claims. Independent source
scoring confirms that the three released answers had the required sources.
The smart router chose 19 FAST, three RESEARCH and two UNSUPPORTED routes.
It avoided the 18 unnecessary research invocations counted for forced B4.
It made one retrieval for the contradictory-premise probe and withheld an
answer. Two simple lookups lost with B5 needed the structured worker or
research evidence.

The process reached 2.01 GB peak working set and took 10.835 seconds to
load the corpus, embedding model, and SEC snapshots. Mean retained evidence
was 3,907 tokens for B4 and 3,167 for B5. B3/B4 used 23 SEC replay calls
each and B5 used four. All variants made zero timed HTTP or model calls
and used zero provider tokens with $0 modeled provider cost. Host compute
cost was outside the experiment.

**Decision**. Adopt the explicit candidate gate and consistent company
catalog in the specialist path. Keep both graph modes available. B4
recovered more answers and incurred more retrieval. In a development-only
diagnostic, even the labeled filing pages gave conflicting values because
the P1 text parser attached multiple table columns to one period. More
retrieval alone did not resolve those gaps. The original P5 provider
benchmark remains the comparison for hosted model behavior.

Source `91f3ee5a7cdfb6a4091b4360354bc764cc4b9eb3` passed 338 tests with
3 skips. Compilation and Git whitespace checks passed. The results JSON
SHA-256 is `e414e386c0f1af2722369a80254d3a5bdf08e89484bcd6fa45767d7bb89c80d9`.
The SEC replay manifest SHA-256 is
`7d7496605ca96ed0047de1c485da22156d84fde9576483984a2b66207c19add5`.

### Reproduce M13

```powershell
uv run python -m scripts.run_multi_agent_ablation --acquire-sec
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OPENBLAS_NUM_THREADS = '6'
uv run --offline --with psutil==7.2.2 python -m scripts.run_multi_agent_ablation --threads 6 --output data/financebench/ablation_runs/m13-results.json
```
