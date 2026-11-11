# Multi-agent research architecture

## Status

M7 adds a finite sequential specialist graph over the M5 router, M4 plan,
existing retriever, M6 request-scoped ledger, P2 evidence sufficiency, and P4
claim verifier. FAST uses four graph nodes, RESEARCH uses eight, and
UNSUPPORTED uses one terminal node. M8 adds parallel filing tasks to the
RESEARCH stage for adapters that support concurrent calls. The graph remains
separate from the offline P5 evaluation path. See [parallel research](PARALLEL_RESEARCH.md).

## Current M5 route graph

```text
START → classify_request → FAST | RESEARCH | UNSUPPORTED → END
```

The route graph is deterministic, has no loops or checkpoint store, and only
prepares a bounded M4 plan. It invokes no retriever, provider, LLM, or agent. The
56-case authored fixture has 100% behavior agreement but is not independent
quality evidence. On 150 unlabeled FinanceBench questions, the Corpus Map
selected 36 FAST, 10 RESEARCH, and 104 UNSUPPORTED routes. Details and the
high unsupported rate are in [`COMPLEXITY_ROUTING.md`](COMPLEXITY_ROUTING.md).

## Current M6 ledger

The blackboard in `src/ledger/` links question requirements, M4 task IDs,
metadata-only evidence records, normalized facts, calculations, generated
claims, and P4 verification results. Evidence and calculation IDs are stable;
duplicate discovery merges provenance observations, while malformed or
cross-request references fail before snapshots are committed. A `DERIVED_FACT`
must carry its calculation ID and all ordered input evidence IDs. The ledger
is in-memory and is not used by P5. M7 specialist workers add evidence and
derived facts through this API. See [`EVIDENCE_LEDGER.md`](EVIDENCE_LEDGER.md).

## M7 execution graph

```text
FAST:        filing → evidence analyst → report writer → verifier
RESEARCH:    supervisor → filing → SEC facts → table → analyst → reasoner → writer → verifier
UNSUPPORTED: terminal
```

This graph is acyclic. Each run owns its `SpecialistRuntime`, which keeps raw
chunk text out of graph state and carries budget counters, P2 coverage, and
ledger IDs. Workers return typed status, requirement/task/evidence IDs,
structured observations, and measured calls, candidates, and elapsed time. The
table worker spends only remaining route retrieval budget. The structured
worker uses the official SEC Company Facts endpoint through
`SECEdgarClient` when a client and company-to-ticker mapping are supplied. A
deterministic writer formats supported lookups and calculations; the verifier
controls the final status.

The M7 Company Facts adapter is a narrow starter path. It does not guarantee
concept equivalence, duration/instant matching, latest-as-reported selection,
amendment handling, or restatement reconciliation. The SEC fixture checks
provenance links and Decimal arithmetic, not real-world accuracy. See
[`SPECIALIST_RESEARCH_GRAPH.md`](SPECIALIST_RESEARCH_GRAPH.md).

## Target planes

**Research Plane:** intent/risk analysis, bounded complexity routing,
corpus-aware planning, specialist retrieval, structured fact lookup, parallel
independent research, and synthesis preparation.

**Evidence Control Plane:** candidate acceptance, provenance and
entity/metric/period validation, numerical consistency, sufficiency, gap
decisions, claim support, abstention, and final answer release. It is logically
independent of generative workers and reuses `src/decision/`,
`src/verification/`, and bounded adaptive retrieval.

## Finite workflow (target)

```text
question → risk/complexity router ── simple ──→ targeted retrieval
                    │                              │
                    └── research → planner → bounded independent tasks
                                                  ├─ filing worker
                                                  ├─ table worker
                                                  └─ structured-fact worker
                                                           ↓
                                                  evidence IDs / ledger
                                                           ↓
                                     deterministic evidence control plane
                                                           ↓
                               calculate → write → verify → release/abstain
```

M5 uses LangGraph for typed state, conditional routing, and an inspectable finite
trace. It has not been benchmarked against equivalent plain Python control
flow. No worker may write the final answer. Workers should
receive task IDs, allowed tools, required evidence, and explicit budgets, and
return evidence IDs, structured observations, missing requirements, status,
and measured usage. Do not copy raw filing context into a supervisor prompt.

## M8 parallelism guardrails

- finite node graph, explicit terminal states, and a configured recursion cap;
- route profiles with max steps, tool/retrieval/LLM calls, candidates, tokens,
  concurrency, and wall time;
- no unbounded task spawning or self-reflection;
- fan out only across independent company/period/source tasks;
- deterministic ledger merge, stable evidence IDs, and per-node context limits;
- trace safe progress events without exposing private chain-of-thought;
- measured B0–B5 ablation; retain the simplest route if extra workers do not
  improve grounded quality per call, token, second, or dollar.
