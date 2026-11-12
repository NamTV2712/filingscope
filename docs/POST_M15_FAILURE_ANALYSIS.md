# Q1 Measurement integrity and failure attribution

**Status** Validated offline. Baseline Git SHA
`1218f9002fca5c0c11774a97be5e7b1e21428719`. The Q1 replay code and phase
report are in the commit referenced by the
[implementation checkpoint](IMPLEMENTATION_PROGRESS.md#post-m15-checkpoint).

## Research question and intervention

We tested whether answerable requests lost evidence before retrieval, while
assigning values to financial periods, or at a release gate. The starting
hypothesis was that correct source locations were often present and the
parser produced incompatible financial observations from them. FAST could
also omit a usable structured-fact path.

The evaluation adds an ordered failure taxonomy, request and slot traces,
an offline A–G replay, and manifests. It consumes the existing M13 scorer,
P1 dense index, M14 statement parser, SEC replay, specialist receipts and
ledger, P2 evidence analyzer, candidate policy and M11 verifier. The replay
changes only the selected diagnostic boundary. Runtime thresholds and
production paths use the baseline code.

## Baseline and paired results

The frozen Post-M15 baseline replays A0–A4 and B0–B5 against all 24 M13
questions. All 264 runs match historical M13 on the reported independent
quality measures. Some answer surface text changed in A0/A1 and B3/B4,
and latency varied. A0/A1 released 15 and 17 answers respectively, all with
an unsupported claim according to the independent scorer. The detailed
diagnostic run covers B4 and B5 on the same 24 questions. Historical P5 used
the separate FinanceBench hosted benchmark. [M13](ABLATION_STUDY.md#m13-research-workflow-ablation), [P5](BENCHMARK_RESULTS.md).

| Metric | B4 forced RESEARCH | B5 routed FAST/RESEARCH |
|---|---:|---:|
| Grounded exact / answerable, baseline and instrumented | 3/21 | 1/21 |
| Numeric exact / answerable | 3/21 | 1/21 |
| Released / all cases | 3/24 | 1/24 |
| False abstentions / answerable | 18/21 | 20/21 |
| Correct abstentions / unanswerable | 3/3 | 3/3 |
| Releases with unsupported claims / releases | 0/3 | 0/1 |
| Valid claim citations / emitted citations | 3/3 | 1/1 |

B4 recovered Best Buy FY2019 assets and Microsoft FY2024 revenue relative
to B5. Both answered Apple FY2024 original revenue. No paired case favored
B5 on grounded exactness. The B4 advantage was 2/21, or 9.52 percentage
points. A 10,000-replicate issuer-group bootstrap over eight groups gave a
descriptive 95% interval of 0.0 to 16.67 points. The cohort is small and
exposed, and the release counts give limited evidence about risk.

| Failed query class | B4 | B5 |
|---|---:|---:|
| Simple lookup | 7 | 9 |
| Hard negative | 5 | 5 |
| Numerical | 3 | 3 |
| Single document | 1 | 1 |
| Multi-document | 1 | 1 |
| Multi-company and multi-hop | 1 | 1 |

## First stage that lost evidence

| Stage | B4 / 18 failures | B5 / 20 failures |
|---|---:|---:|
| Table header and period alignment | 15 | 12 |
| Table cell extraction | 1 | 1 |
| XBRL fact normalization at coverage handoff | 2 | 0 |
| Source capability routing | 0 | 3 |
| Candidate retrieval | 0 | 2 |
| Ranking cutoff | 0 | 2 |
| Undetermined | 0 | 0 |
| Total | 18 | 20 |

These counts describe 38 failed runs across two paired modes, with shared
questions. Per-slot secondary signals and worker receipts remain in the
local JSON. Three bottlenecks account for most of the run failures.

1. **Financial table interpretation.** Header or period alignment was
   first in 27 runs. The Boeing FY2022 statement on PDF page index 54
   contains values for FY2022, FY2021 and FY2020. Baseline coverage put
   incompatible amounts under the FY2022 slot. For MGM FY2022, the requested
   statement at page index 59 had an unlabeled total between the revenue
   components and the expense heading. The raw parser returned no fact
   from that page for the target slot. Independent column annotations
   and M14 parsing distinguish these two failure mechanisms.
2. **Bounded PDF retrieval.** B5 missed four labeled pages at its runtime
   cutoff. A same-query, same-scope probe found Best Buy quarterly cash
   at rank 12 and Microsoft's FY2023 operating income at rank 27. The
   labeled Best Buy annual statement was absent from the top-50 probe
   for its revenue and operating income queries.
3. **FAST source capability.** The forced branch recovered the two
   successful paired differences through SEC facts. Apple quarterly
   revenue had an SEC-only accepted locator and FAST omitted that worker.
   B4 reached the correct accession for Apple quarterly revenue and Best
   Buy quarterly cash, then coverage reparsed each fact's text as annual.
   A structured encoding restored the quarterly slot in isolation. This
   identifies a second loss after routing and justifies a typed handoff in Q2.

## Oracle experiments

Counts below show grounded recoveries over executed interventions on
baseline failures. A recovery can appear in more than one intervention.

| Intervention | B4 | B5 | Result or execution limit |
|---|---:|---:|---|
| A Requirements | — | — | Issuers, metrics, periods, slots and operations matched the reference requirements. |
| B Route | — | 2/18 | Both recoveries use the paired B4 SEC path. |
| C Raw labeled PDF page | 0/17 | 0/18 | The unchanged extractor still lost or contradicted facts. SEC-only requests use the route and normalized-fact probes. |
| D Located, normalized observations | 2/14 | 3/13 | B4 recovered Amcor cash and Boeing assets. B5 also recovered Best Buy assets. SEC quarter probes restored the slot in isolation and did not recover a verified full answer. |
| E Set-sufficiency bypass | 6/18 | 1/20 | Independent scorer and production verifier agreed on these responses in the diagnostic runs. Other runs still failed. |
| F Reference construction | — | — | All baseline failures with coverage were insufficient, so the formatter had no complete approved input. |
| G Final verifier bypass | — | — | Failed runs had no non-fallback draft to score. |

At least one executed intervention recovered 8/18 B4 and 5/20 B5 failures.
The remaining 10 and 15 resisted the individual probes that ran. These
results do not estimate recovery from combined interventions. Oracle E can
ask a writer to proceed with a conflicted evidence set. It remains an
offline diagnostic and provides no justification for weakening the
production sufficiency rule.

## Efficiency, validation and provenance

| Warm request measure | B4 | B5 |
|---|---:|---:|
| p50 / p95 latency | 120.951 / 273.886 ms | 66.756 / 175.748 ms |
| Mean tool calls | 2.7500 | 1.0833 |
| Mean retrieval calls | 1.7917 | 0.9167 |
| Mean retained evidence tokens | 3,907.2083 | 3,167 |

The primary diagnostic run took 10.413 seconds to prepare its artifacts
and reached 2,013,118,464 bytes peak working set. Timing in the table
covers each unchanged graph request, including routing. Oracle processing,
deeper ranks and aggregate scoring are outside those request timings.
All runs used local snapshots, zero provider calls and tokens, and zero
SEC HTTP calls. Provider cost was $0. Host compute cost was outside the
benchmark. No deployment was performed.

The run used a six-thread Windows CPU replay with the pinned Nomic query
embedder, 28,849 P1 chunks, 84 PDF hashes, and nine SEC Company Facts
snapshots through 2024-12-31. The configuration hash is
`a1810203e7b8dcb417d113300fe972d4df6310d94f748efb4fd379b82a3ebec4`.
The Post-M15 baseline artifact SHA-256 is
`a483ea98f6a3d98dc0104abaf3583decfc6b9015a3daa2ab356e8694e8ffd12a`.
The primary Q1 JSON SHA-256 is
`992ed494a61b17c01806c21b23cbfc9682c82ec2aba4793c452c1193f92a646e`.
The artifact and manifest stay in the ignored local evaluation directory.
The manifest records the original splits, data and model hashes, dependency
versions, runtime configuration, seed and code hashes. [Reproduction](POST_M15_EVALUATION_PROTOCOL.md#reproduction).

The focused suite checks deterministic attribution and reconciliation,
source-derived oracle payloads, quarterly unit and period preservation,
artifact hashing, and rejection of oracle options on the live research
HTTP route. The full regression suite passed 354 tests with three
pre-existing missing-local-filing skips. Syntax and Git whitespace checks
passed. A second benchmark reproduced every trace, classification and
oracle outcome after excluding timings and peak memory. The M13 labels,
page annotations and oracle code are used by
the offline evaluator. The website UI files are unchanged.

**Decision** Adopt the diagnostic harness. Proceed to Q2 with a typed
quarterly SEC handoff and strict table-column ownership. The phase gate
requires new labeled evidence and a separate normalization comparison.
