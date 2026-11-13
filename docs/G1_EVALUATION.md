# G1 evaluation foundation and Jev offline adapter

## Objective and predeclared checks

Add a versioned scoring contract for the eight primary metrics and an
optional semantic observer behind the existing candidate feature interface.
The hypothesis is that explicit label applicability exposes where the
historical proxies are insufficient while preserving historical results
and deterministic authority over evidence and release.

The G0 CPU environment, frozen P1/SEC inputs and seven offline report
types form the baseline. Compare the old and new reports on identical
cases, excluding timing, memory and timestamps. Require matching ranked
outputs, dispositions, cited evidence, grounded scores and fault outcomes.

The new fixture must check exact numeric identity, citation scope,
semantic support, unsupported releases, correct and false abstention,
duplicate ranks, top-ten cutoff, missing and empty annotations, and
undefined denominators. Require exact raw count agreement. Test the
observer with valid, malformed, timed-out and failed transports. A high
semantic score must preserve each deterministic hard rejection. All
checks must run under the offline guard at zero provider spend.

## Changes and architecture

- [Primary scorer](../src/evaluation/primary_metrics.py) and its
  [offline CLI](../scripts/run_primary_metrics.py) validate explicit
  adjudications, return per-case release outcomes and preserve raw counts
  and applicability. The CLI binds the evaluated JSON bytes by SHA-256.
- [Jev observer](../src/policy/jev_observer.py) implements the existing
  `CandidateFeatureObserver` protocol around a deterministic feature
  source. It projects only candidate text and the requirement description
  into the provider-neutral request. The strict response permits the
  relevance categories `relevant`, `unclear` and `irrelevant`.
- The observer can lower `semantic_relevance` using the respective caps
  1.0, 0.5 and 0.0. These are ordinal policy inputs. A capped observation
  cannot improve the deterministic candidate disposition. The adapter
  leaves all entity, metric, period, unit, filing, provenance, revision,
  numeric and table checks with the deterministic feature source.
  `DecisionBackend`, `CandidateEvidenceGate`, sufficiency, the ledger
  and final release use the existing Python implementations.
- The default adapter has no transport. Explicit injection supplies a
  configurable provider, model and positive deadline (default 2 seconds).
  The transport must honor that deadline and normalize its response.
  On invalid input, invalid output, timeout or declared transport error,
  the adapter returns the deterministic features. It makes one attempt.
  G1 ships a mock seam and fixtures. The runtime graph has no Jev wiring.
- OpenRouter and AI/ML API both document `typesafe/jev-1.14`.
  The scaffold defaults to OpenRouter and the versioned model ID.
  The real served snapshot, error mapping, deadline enforcement and
  billed token usage remain unverified. [OpenRouter](https://openrouter.ai/typesafe/jev-1.14),
  [AI/ML API](https://aimlapi.com/models/typesafe-jev-1-14).

## Metric contract

The scoring unit is a fixed case and one system response. Supply
`released=true` for a substantive answer, including a partial answer.
An abstention or a non-substantive rejection has `released=false`.
For each adjudicated release, label exactness and list the complete
set of atomic output claims, including extraneous and uncited claims.
Reviewers should label source contributions and whether the citations
jointly support each claim. For numeric answers, independently check
all required values against the requested company, metric, period,
currency, scale and reporting basis. Check the calculation and operands
when required. `calculation=null` means no calculation is required.
An unknown required check leaves `numeric_checks` absent.

| Outcome | Numerator and denominator |
| --- | --- |
| Grounded Exact Accuracy | Answerable cases with an exact release, all applicable numeric checks passing, and every claim supported by context and by its citations. Every supplied citation must contribute valid support. The denominator is judgeable answerable cases. Withholding an answerable case counts as a miss. |
| Numeric Exact Accuracy | Numeric-applicable cases with every numeric check passing. The denominator includes applicable abstentions and releases with complete checks. |
| Answer Coverage | Substantive releases divided by all cases. |
| Incorrect or Unsupported Release Risk | Releases with known grounded-exact failure divided by judged releases. Releasing on an unanswerable case is a known error. A known failure can be counted with other labels missing. The report also gives the number of unjudged releases and full-denominator lower and upper bounds over their possible labels. These are missing-label bounds. |
| Context Precision@10 | Relevant unique retrieved identities divided by all unique returned identities within the first ten original ranks. Relevance must be adjudicated for all those identities. |
| Gold Evidence/Fact Recall@10 | Required targets with at least one acceptable identity within the first ten ranks, divided by the number of required targets. A shared locator can satisfy multiple labeled targets. |
| Citation Support Precision | Valid claim-citation contributions divided by all distinct claim-citation associations on fully labeled releases. A citation may contribute one operand to a claim whose complete proof uses multiple sources. Missing or invalid reference markers can be recorded as unsupported associations. An uncited claim has zero associations and can fail grounded exactness. |
| Claim Faithfulness | Atomic output claims supported by retrieved context divided by all atomic claims on fully labeled releases. The claim can be faithful with a wrong citation. |

The report pools raw counts across judged items. It includes eligible
and applicable case counts. Zero denominators return JSON `null`.
Duplicate candidates occupy their original ranks and count at most once
per identity. Duplicate cases, atomic claim IDs and claim-citation
associations fail input validation. An explicit empty relevance set
judges all returned items irrelevant. Missing relevance leaves
precision unscored. An empty or missing gold target set makes recall
inapplicable. A known empty retrieval still misses any positive targets.
Rank metrics are reported by page, chunk or fact granularity.
Fact IDs need company, period, unit, revision and concept specificity in
the annotation. The same page containing two facts does not establish
two semantically correct retrieved fact records.

Existing Recall@K, MRR, nDCG, AllEvidence and historical ablation
metrics keep their definitions. Historical numeric matching, expected
claim coverage and citation-locator overlap have their original labels.
Complete numeric checks and semantic claim/citation adjudication remain
prerequisites for strict real-cohort scores. The initial semantic
annotations are synthetic controls reviewed against the fixture
specification. A later [author-reviewed SEC pilot](G1_SEC_CLAIM_REVIEW.md)
applies the scorer to frozen real-filing releases. Independent
semantic judgments remain pending.
Other diagnostics, including rank-weighted context precision, reference
claim recall and AURC, remain deferred pending suitable judgments or
continuous scores. G1 reports false/correct abstention and retains the
existing six-decision false accept/reject and resource evaluations.

## Tests and evaluation results

### Scorer fixture and observer controls

The seven-case [CI fixture](../tests/fixtures/g1_adjudications.json)
deliberately includes incorrect and unsupported releases, an unjudged
release, duplicate ranks and both forms of abstention. Its counts are
asserted by the offline suite.

| Metric | Fixture score |
| --- | ---: |
| Grounded Exact Accuracy | 1/4 judged, 5 eligible |
| Numeric Exact Accuracy | 1/3 judged, 4 eligible |
| Answer Coverage | 5/7 |
| Incorrect or Unsupported Release Risk | 3/4 judged, 5 releases. Full-denominator bounds 3/5–4/5. |
| Page Context Precision@10 / Gold Evidence Recall@10 | 1/10 / 1/3 |
| Fact Context Precision@10 / Gold Fact Recall@10 | 1/1 / 1/2 |
| Citation Support Precision | 1/3 associations, 3 of 5 release cases labeled |
| Claim Faithfulness | 2/3 claims, 3 of 5 release cases labeled |
| False abstention / correct abstention | 1/5 / 1/2 |

A mock positive reply reproduced every deterministic disposition and
reason across the existing 60 candidate fixtures and five supplemental
hard-rejection controls. The original fixture has 20 ACCEPT, 20 WEAK
and 20 REJECT. The augmented replay had zero changed decisions.
A negative mock reply downgraded a known ACCEPT to WEAK. The targeted
tests exercise timeout, transport failure, malformed fields and
deterministic fallback. The timeout test simulates a deadline exception.
G1 estimates no provider accuracy or calibration.

### Historical regression comparison

The comparison used the G0 locked CPU dependencies and development-exposed
filing labels. P1 uses the same frozen index and pinned Nomic model.
Company Facts uses the same nine snapshots and 2024-12-31 filing cutoff.
The baseline architecture, retrieval and writer reports were rerun
before G1 edits. The other four baseline reports came from the verified
G0 candidate. The G1 candidate reran all seven. Stable report fields
matched after omitting latency, timestamp and resource fields.

| Result | Baseline | G1 |
| --- | ---: | ---: |
| Windows offline suite | 403 passed, 3 skipped | 437 passed, 3 skipped |
| Linux WSL corpus-free suite | 402 passed, 4 skipped | 436 passed, 4 skipped |
| P4 dispositions / claim statuses | 15/15 / 14/14 | 15/15 / 14/14 |
| Six decision gates | 181/181 | 181/181 |
| Q2 labeled statement cells / SEC facts | 57/57 / 9/9 | 57/57 / 9/9 |
| Q4 validation grounded / incorrect releases | 4/4 / 0/4 | 4/4 / 0/4 |
| M13 routed grounded / incorrect releases | 21/21 / 0/21 | 21/21 / 0/21 |
| Natural statement grounded / incorrect releases | 30/30 / 0/30 | 30/30 / 0/30 |
| M12 Dense Recall@10 / MRR@10 / nDCG@5 | 56.25% / 0.3529 / 0.3757 | 56.25% / 0.3529 / 0.3757 |
| Q7 healthy-source retention, adaptive / routed | 5/10 / 10/10 | 5/10 / 10/10 |
| Q6 writer gates | 9/9 | 9/9 |

As a locator-only check, the G1 retrieval scorer read the 30 existing
Dense page rankings and the document-only source alternatives in
`configs/retrieval_utility.py`. Using listed reference pages as the
relevance set gave **21/291** micro precision and **21/37** micro
required-slot recall on both runs. Unlisted pages can contain useful
evidence. The historical page Recall@10 is 60% with case-level averaging.
These scores use different aggregation units.

No new critical source or release errors appeared in the paired
comparison. The strict fixture catches a wrong reporting basis despite
an otherwise matching number and a grounded narrative cited to an
unrelated page. The first observer test exposed missing unit and
revision controls in the reused fixture. Explicit mismatch rows now
exercise those paths. Three raw-HTML fixture tests were skipped in
both environments. Linux also skipped the local FinanceBench sample.
Ruff, focused mypy, dependency compatibility, compileall and tracked-file
checks passed. The updated offline test suite ran locally on both OSes.

## Latency, usage and cost

| Windows CPU sample | Baseline | G1 |
| --- | ---: | ---: |
| M13 routed p50 / p95 | 16.14 / 221.60 ms | 12.18 / 166.75 ms |
| Natural statement p50 / p95 | 16.93 / 113.34 ms | 14.45 / 113.81 ms |
| Architecture replay peak memory | 2,007,212,032 B | 2,007,244,800 B |
| Retrieval replay peak memory | 2,015,453,184 B | 2,012,602,368 B |
| Natural statement tools / local embeddings | 38 / 14 | 38 / 14 |
| Hosted calls / generated provider tokens / spend | 0 / 0 / USD 0 | 0 / 0 / USD 0 |

The scorer CLI used about 1.03 ms inside the timed scoring section and
39,698,432 B peak process memory on the seven-case fixture. The
per-stage runtime was outside this scorer measurement. The warm
runtime timings are single-run samples. The fixture mock calls incur
zero provider usage. Live Jev latency and tokens remain unmeasured.

## Reproduce

Use the [G0 locked environment and replay commands](G0_BASELINE.md#reproduce).
Run the following from the repository root in PowerShell or Linux.

```text
uv run --offline --locked python -m scripts.run_primary_metrics tests/fixtures/g1_adjudications.json --output .local/g1/primary-fixture.json
uv run --offline --locked python -m pytest -q tests/test_primary_metrics.py tests/test_jev_observer.py
uv run --offline --locked python -m scripts.run_offline_checks
uv run --offline --locked ruff check configs scripts src tests
uv run --offline --locked mypy
```

The [fixture output](../.local/g1/primary-fixture.json) binds the input
hash `905234634a80dcba61d36ddee506db8a8f04199a063b45ad337893d83ae2b172`.
The local [historical comparison receipt](../.local/g1/historical-comparison.json)
records both runs' hashes and counts. The files are ignored local outputs.
For the locator check, key the answerable cases from
`configs.retrieval_utility.CASES` by ID, assign a target ID to each
claim-source slot, retain its PDF locators, and score
`variants.dense.pages_per_case[].ranking` with `score_retrieval`.
Use the union of each case's PDF locators as the judged relevance set
for that check.

## Decision and Git status

**KEEP** the primary scoring contract and offline regression fixtures.
**EXPERIMENT** with the Jev adapter as an offline-only scaffold.
The remaining prerequisites are real semantic and complete numeric
adjudications, plus a separately authorized live provider validation.

The evaluations ran over `91367269638e55a7e7c26e2f7f78b18efd16fb33`
with the G0 changes now in commit `7881b440a4bdd1b7b7a8afa54927d66ad4e7be8c`.
The three pre-existing independent/FinRank script changes are outside
the milestone commits. No final labels were inspected during G1.
