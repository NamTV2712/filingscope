# Q7 — Specialist execution and source isolation

Q7 used Q6 commit `33073129dc71fbac2cb516e26ca1ec07adce822f` as its
runtime baseline. The replay holds the FinanceBench corpus, Q5 scoped
statement ranker, SEC snapshot cutoff, typed financial facts, evidence
policy, deterministic writer and release verifier constant. The baseline
artifact records four architectures before the runtime changes.

## Architectures and routing

| Mode | Execution |
| --- | --- |
| A | Deterministic SEC Company Facts for supported scalar slots with accessions. Returns an abstention outside that capability. |
| B | One serial adaptive workflow. Uses the same plan to define document scope, tries eligible SEC facts, runs bounded evidence-targeted queries, and shares the analyst, Decimal reasoner, writer and verifier with C and D. |
| C | Existing routed LangGraph. Direct SEC/table and simple targeted text use FAST. The supervisor allocates separate scoped filing tasks for complex requests. |
| D | Same graph with RESEARCH forced for supported requests. |

The review covered the conditional FAST and RESEARCH edges, corpus-aware
task assignment, filing fan-out, structured SEC and table workers, ledger
merge, analyst coverage, arithmetic and the shared release stage. The
supervisor and specialist stages are the existing LangGraph nodes. The
planner decomposes questions into fact slots and the graph allocates one
retrieval budget across them. Arithmetic uses aligned fact pairs and the
Decimal verifier. Contradictory and unsupported questions retain their
early stop and evidence release gates.

## Changes

- Query deduplication now keys on normalized query and effective document
  scope. A scope-aware adapter receives the planned document IDs and results
  outside those IDs are excluded. FAST divides its candidate budget across
  outstanding filing scopes. The runtime verifies identical query text can
  independently cover two filing years.
- Assignments retain objectives, task IDs, fact requirements, allowed tools,
  effective source scope, budget and expected outputs. Receipts retain IDs,
  coverage gaps, conflicts, status and usage. Approved facts carry verified
  slot provenance. The ledger merges deterministically and detects conflicting
  content under the same chunk ID. Full filing pages remain in request-local
  source storage.
- One bounded retry repeats failed scoped filing queries after a recoverable
  transport error. It uses remaining route budget and preserves successful
  sibling results. SEC acquisition runs once per request and remains outside
  the retry. Ledger idempotence and deterministic merge are covered by tests.
- An explicit consolidated statement request uses filing evidence. A growth
  request can use two compatible typed filing operands when the available
  SEC operands use incompatible concepts or reporting bases. Source types
  remain homogeneous within a calculation.
- The deterministic writer can render an explicit, issuer-bound industry
  disclosure. The atomic verifier checks the same filing sentence and its
  citation and binds fiscal years through the approved source facts. Scoped
  local retrieval prioritizes explicit disclosures within the bounded
  candidate pool. Conflicting disclosures cause abstention. Broader open-ended
  narrative synthesis remains outside this local deterministic grammar.

## Cohorts and scoring

The exposed M13 cohort has 24 questions including 21 answerable. Its
categories include lookup, numerical arithmetic, multi-period and
multi-company requests, a cross-company multi-hop calculation, original
and recast results, contradiction and unsupported questions. The Q3
direct-fact controls contain 14 answerable questions and one future request.

The provisional Q7 set has 12 source-checked answers across six disconnected
issuer pairs. Four cases are development and eight are validation. The cases
cover cross-company, cross-document, multi-statement and multi-period
comparisons. The case labels include exact values, periods and source
locators. Original FY2021 Boeing and MGM SEC accessions were checked against
the pinned resolver and added as equivalent citation locations. Numeric
answers were frozen. Two industry disclosures are scored separately by
exact statement and source page. Both Coca-Cola pages in the scoring key
contain the same independently inspected disclosure.

The fault replay uses the five two-statement questions with an explicit
consolidated statement constraint. Each question is replayed in both source
failure directions. A one-time transport timeout and a persistent scoped
lookup failure exercise the same injected adapter in B and C. Outcomes are
grounded exact release and retention of every slot from the available
issuer. Issuer-pair bootstrap intervals use 10,000 samples with seed
`20261112`. The fault replay measures this specific failure model on real
source data and makes no production outage rate assumption.

## Acceptance and tradeoffs

| Cohort | Metric | A SEC | B adaptive | C routed | D forced |
| --- | --- | ---: | ---: | ---: | ---: |
| M13 | Grounded exact, baseline → Q7 | 11 → 11 / 21 | 17 → 21 / 21 | 21 → 21 / 21 | 19 → 21 / 21 |
| Q3 direct | Grounded exact | 12/14 | 14/14 | 14/14 | 14/14 |
| Q3 direct | Mean tools, including abstention | 0.87 | 1.00 | 1.00 | 1.93 |
| Q3 direct | p50 / p95 ms | 14.58 / 16.06 | 15.76 / 92.46 | 14.29 / 17.43 | 89.49 / 115.40 |
| Q7 complex | Grounded exact | 0/12 | 12/12 | 12/12 | 12/12 |
| Q7 complex | Mean tools | 0 | 1.58 | 5.50 | 5.50 |
| Q7 complex | Mean evidence tokens | 0 | 1,041 | 1,212 | 1,212 |
| Q7 complex | p50 / p95 ms | 3.74 / 4.30 | 118.27 / 196.02 | 333.57 / 450.75 | 286.20 / 446.89 |
| Q7 narrative | Grounded exact | 0/2 | 2/2 | 2/2 | 2/2 |

B, C and D each correctly withheld 3/3 M13 and 1/1 direct controls.
All clean releases passed source and value scoring. On the 12 numeric
Q7 comparisons, B, C and D completed every planned slot and linked all
released claim supports. No identical query-and-scope retrieval repeated.
B returned 4 duplicate candidate instances. C and D each returned 213,
with 24 table follow-up calls that yielded no worker evidence IDs. The
paired grounded-exact delta of C and D against B was 0 points (issuer-group
bootstrap interval [0, 0]) on this cohort. C avoided all 14 unnecessary
supervisor invocations that D made on answerable direct controls.

The four-way replay keeps the routed baseline's M13 and direct-fact
quality. After enforcing statement provenance in all modes, the adaptive
baseline recovered Amcor, Boeing and MGM revenue. Compatible filing operands
recovered Nike growth in B and D. The forced graph also recovered MGM.
The routed graph had no new false abstentions on the clean numeric cohorts.

The scoped graph retained every required slot from the healthy issuer in
10/10 persistent-outage replays. B retained them in 5/10. The difference
was +50 percentage points, with one gain in each of five issuer pairs and
a grouped bootstrap interval of [+50, +50] points for this fixed design.
Each pair contains exactly one blocked issuer ordering that interrupts the
adaptive controller early, which explains the degenerate interval. The
demonstrated benefit is preservation of usable evidence from an available
issuer during a scoped outage. Both workflows withheld all complete answers
during persistent outages. Both recovered 10/10 exact answers after a
single timeout. Neither released unsupported claims in these replays.
Five independent pair directions give a two-sided exact sign-test p-value
of 0.0625. This experiment does not establish a population-level advantage.

The result supports preserving bounded, independent filing tasks for
multi-company research. A serial controller that continues across independent
scopes after a targeted read failure is a separate design and could narrow
the observed preservation gap. The clean accuracy result gives no evidence
for broad specialist superiority or adding nodes. The direct route avoids
supervisor work and retains table fallback for facts missing from SEC.

In the separate blocking I/O fixture, six 40 ms retrieval calls per run
and three concurrent workers reduced p50 from 252.28 to 88.65 ms and p95
from 256.90 to 93.72 ms across 20 runs per mode. The frozen dense index uses
a shared embedding lock. The corresponding clean real-corpus serial and
parallel runs both yielded 12/12 with 66 tools each. Serial p50/p95 was
240.72/382.51 ms and parallel p50/p95 was 333.57/450.75 ms. The fixture speedup
is evidence about blocking I/O, and the real run measures the local index.

The full regression suite passed with 386 passed, 0 failed and 3 skips for
local HTML fixtures. Syntax compilation also passed. The replay used about
2.01 GB peak working set and zero LLM calls, provider tokens or provider cost.

## Reproduction

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OPENBLAS_NUM_THREADS = '6'
uv run --offline --with psutil==7.2.2 python -m scripts.run_specialist_architectures `
  --faults --output data/financebench/ablation_runs/q7-specialist-evaluation.json `
  --manifest data/financebench/ablation_runs/q7-specialist-manifest.json
```

The runner denies outbound connections and uses local model, vector, filing
and SEC snapshots. The JSON retains per-case outputs and scores, categories,
retrieval and token usage, latency, assignment and handoff metrics, and the
paired comparisons. The manifest records hashes of evaluation code, labels,
index, pages, SEC snapshots and the resulting JSON. Absolute latency varies
with local model warm-up and scheduler load. Peak working set is measured
for the process that runs all four architectures.

| Local artifact under `data/financebench/ablation_runs` | SHA-256 |
| --- | --- |
| `q7-four-way-baseline.json` | `ee600425207b118164080b021c3489eca91a2101651ba672656aa18a9578b317` |
| `q7-specialist-evaluation.json` | `6a631451d1a4b2e5c0c80ad7077969166a13a390c196d1b1a4ed9f93776c24cb` |
| `q7-specialist-manifest.json` | `df3b0ba01bd270a9c21a20292a22a6f4b73b1f6c229ce36a07a3749638482878` |
| `q7-parallel-io-fixture.json` | `dcb0f3497df63da7d9fa5b335f14dafeea787b59baee4680bebe373c5eb0c21e` |
