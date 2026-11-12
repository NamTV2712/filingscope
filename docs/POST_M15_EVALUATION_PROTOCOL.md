# Post-M15 evaluation protocol

## Cohorts and uses

| Cohort | Source and split | Use |
|---|---|---|
| Historical M13 | 24 authored questions over real SEC filings. Eight development, eight validation and eight held-out. 21 answerable, three unanswerable. | Retrospective, paired workflow diagnosis. Both historical and Post-M15 replays use the same original split labels. |
| Historical P1/P5 | Patronus AI FinanceBench public OPEN_SOURCE sample, 150 cases, CC BY-NC 4.0. Repository split 60/45/45, grouped by company. | Historical retrieval and hosted-generation reference. The original held-out scores are development-exposed. |
| New development and validation | New groups of filing questions, table cells and XBRL observations from pinned sources. Each item carries a label provenance and review status. | Develop and tune on development. Choose configurations on validation with prespecified quality and resource limits. |
| New independent final | Fresh questions and source references sequestered by a reviewer, with distinct issuer groups and a later, predeclared filing window. | Evaluate once after locking code, model and index revisions, policy, budgets, scoring rules and success criteria. |

The M13 questions and scoring labels are project-authored fixtures. Q1
supplements them with source-checked operands and table-column annotations
for retrospective diagnostics. The additional labels are AI-assisted and
await independent human review. The FinanceBench PDFs, dataset and local
artifacts remain under ignored paths. [FinanceBench dataset card](https://huggingface.co/datasets/PatronusAI/financebench), [repository dataset protocol](DATASET_PROTOCOL.md), [M13](ABLATION_STUDY.md).

## Independent cohort procedure

1. Before inspecting any candidate result, declare the eligible filing forms,
   filing cutoff, minimum category counts, extraction and adjudication rules,
   and sampling seed. Include answerable and unanswerable cases, original
   and restated values, quarter and YTD distinctions, hard negatives, multiple
   entities or periods, and narrative disclosures.
2. Use issuer CIKs as group keys. Form connected groups across all issuers
   mentioned in each multi-company case. Link any questions sharing a filing,
   revision chain or source observation. Put a whole connected group into
   one split. Exclude groups from the final set if they intersect development,
   validation or previously inspected cohorts. Keep a predeclared later filing
   window for the final cohort and record any gaps in source availability.
3. Assign eligible groups using a deterministic seeded ordering with fixed
   category quotas and record the achieved counts. Keep the final question and
   label files with a reviewer until the configuration freezes. Hash the
   question and label files independently before release to the evaluator.
   Freeze source documents separately so their contents can be indexed without
   exposing benchmark questions, expected answers or gold page IDs to runtime.
4. Store question, canonical company and CIK, metric and basis, date interval
   and period kind, amount and unit, source and revision identifiers, accepted
   alternatives, calculation inputs, answerability, and reviewer provenance.
   Have two reviewers check high-risk cases and resolve disagreements against
   the pinned filings. Record explicitly when labels remain provisional.
5. Hash the development, validation and final membership manifests and freeze
   the code/configuration selected on validation before running the final
   cohort. If final results are used to guide any change, retire that cohort
   from independent evaluation and draw a fresh one for the next final test.

For each evaluation, report the number of queries and eligible claims, answer
coverage, exact numerical and grounded outcomes, false abstention,
unsupported releases per released answer, and citation validity. Use paired
case comparisons on the same source and query set. Use a grouped bootstrap
with the recorded seed for uncertainty when the cohort has enough independent
groups. Report undefined risk if the release count is zero. For small exposed
cohorts, report counts as diagnostic evidence and retain per-case outcomes.

## Q1 attribution and interventions

For each run, score the final result using the frozen M13 independent labels.
Build evidence-stage observations from the existing route, worker receipts,
retrieved IDs, candidate decisions, coverage findings, ledger, draft and
verification results. Compare resolved requirements with independently
specified entity, metric, period and operation. Compare source-location
presence with exact, scaled values at each critical slot. Treat all failures
that lack a demonstrated stage loss as `UNDETERMINED`.

The declaration order of `FailureStage` selects the primary stage. Keep
additional measured signals by slot and stage. The bounded ranking probe
reuses an unchanged query, scope, corpus and embedder, and checks whether
an omitted labeled PDF page occurs between the original cutoff and rank 50.
Absent hits outside that probe remain retrieval misses at the observed
budget. A source-location match alone establishes a locator hit. Exactness
requires the expected fact and provenance.

The offline harness reuses existing graph nodes and changes one boundary at
a time. Oracle A can override requirements in routing, planning and coverage.
B compares the same question with the forced RESEARCH path. C supplies raw
physical PDF pages from the hash-checked cache. D uses header-aligned values
from located pages or re-encodes a verified quarterly SEC observation at the
coverage boundary. E changes the set decision and passes any draft to the
original verifier. F formats available facts or validated calculations. G
scores a withheld draft independently and labels the outcome
`DIAGNOSTIC_BYPASS`. The JSON records execution or a reason for skipping each
probe, with no raw page text, prompts, drafts or credentials in the trace.

The mechanism borrows RAGChecker's separation of retrieval and downstream
failure diagnostics, and Sufficient Context's distinction between available
context and the response made from it. This controlled experiment uses
existing deterministic components, frozen financial labels and no additional
models, APIs or dependencies. RAGChecker's Apache-2.0 implementation and
model-based entailment workflow remain deferred for Q1. [RAGChecker](https://github.com/amazon-science/RAGChecker), [Sufficient Context](https://research.google/pubs/sufficient-context-a-new-lens-on-retrieval-augmented-generation-systems/).

## Reproduction

Use the pinned P1 corpus, vectors and page cache in the original workspace,
and the nine hash-verified M13 SEC snapshots through 2024-12-31. The published
historical artifact is an additional provenance input. If reconstructing it,
use a separate output directory and the historical code and command in
[M13](ABLATION_STUDY.md#reproduce-m13).

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OPENBLAS_NUM_THREADS = '6'
$runs = 'data/financebench/ablation_runs'
.\.venv\Scripts\python.exe -m scripts.run_multi_agent_ablation --threads 6 --output "$runs/post-m15-baseline.json"
uv run --offline --with psutil==7.2.2 python -m scripts.run_failure_attribution --threads 6 --output "$runs/q1-results.json" --manifest "$runs/q1-manifest.json"
```

The runner checks the corpus fingerprint and vectors, page cache hash and PDF
inventory, and SEC snapshot hashes. It requires substantive B4/B5 results
to match the frozen baseline, excluding latency and answer surface text.
The manifest binds the source revisions, dependencies, seed, configuration
and artifact hashes. Runtime timings and artifact hashes can differ on replay.
Compare case-level metrics and stable trace identities for reproducibility.
