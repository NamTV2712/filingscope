# Multi-agent research architecture

## Status

No multi-agent graph is implemented. The current adaptive controller is a
bounded single retrieval controller. M1/P5 is an offline end-to-end evaluation
path, not a supervisor/worker system. M2 diagnostics and M3 policy contracts
are complete. M4 adds a standalone corpus-aware planner and typed task
contract. M5 adds a finite LangGraph classifier with FAST, RESEARCH, and
UNSUPPORTED branches, but it does not call workers or connect to P5. M6 adds
the request-scoped in-memory Evidence Ledger and deterministic merge contract;
specialist graph work is next in M7.

## Current M5 route graph

```text
START → classify_request → FAST | RESEARCH | UNSUPPORTED → END
```

The route is deterministic, has no loops or checkpoint store, and only prepares
a bounded M4 plan. It invokes no retriever, provider, LLM, or agent. The
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
is in-memory and is not yet used by the router, P5, or a specialist worker.
See [`EVIDENCE_LEDGER.md`](EVIDENCE_LEDGER.md).

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

## Guardrails required before M7/M8

- finite node graph, explicit terminal states, and a configured recursion cap;
- route profiles with max steps, tool/retrieval/LLM calls, candidates, tokens,
  concurrency, and wall time;
- no unbounded task spawning or self-reflection;
- fan out only across independent company/period/source tasks;
- deterministic ledger merge, stable evidence IDs, and per-node context limits;
- trace safe progress events without exposing private chain-of-thought;
- measured B0–B5 ablation; retain the simplest route if extra workers do not
  improve grounded quality per call, token, second, or dollar.
