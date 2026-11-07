# P3 Adaptive Retrieval Evaluation

## Purpose and controls

This provider-free evaluation exercises the P2 decision layer together with a
bounded retrieval controller. It uses nine controlled evidence bundles and a
fixed retriever that returns scenario-specific chunks for each targeted query.
The scenarios cover already-sufficient input, one-gap and two-gap completion,
duplicate/irrelevant results, unsupported scope, and query, time, and evidence
token budget stops.

A separate integration test sends a missing-slot query through the migrated
`HybridRetriever`, BM25, dense Qdrant search, cross-encoder interface, and a
temporary Qdrant collection using deterministic test models. No model download,
provider request, or external document is used.

## Metrics

- **Action accuracy:** final `ANSWER`/`ABSTAIN` matches the frozen case label.
- **Stop-reason accuracy:** controller stop reason matches the frozen label.
- **Multi-hop completion rate:** unresolved cases labelled retrievable that end
  with sufficient evidence and `ANSWER`.
- **No-progress detection rate:** duplicate and irrelevant-result cases that
  terminate with the `no_progress` stop reason.
- **Query count:** total additional search calls and mean calls per case.

The evaluation runner reports these metrics and per-case trace summaries:

```powershell
python -m scripts.run_adaptive_retrieval_evaluation
```

An optional JSON artifact can be written under ignored local data:

```powershell
python -m scripts.run_adaptive_retrieval_evaluation --output data/adaptive-evaluation/p3.json
```

## P3 result

| Measure | Result |
|---|---:|
| Fixed scenarios | 9 |
| Final action accuracy | 9/9 (100%) |
| Stop-reason accuracy | 9/9 (100%) |
| Eligible multi-hop completions | 2/2 (100%) |
| No-progress detections | 2/2 (100%) |
| Additional targeted queries | 8 total; 0.89 mean per scenario |

The synthetic results validate the controller's implementation against known
branches. They do not estimate FinanceBench multi-hop performance or general
retrieval success. Phase P5 must evaluate independently labelled cases.

## Resource bounds and limits

Each run has finite round, query, retrieved-evidence token, and elapsed-time
budgets. Accepted chunks are deduplicated by document/chunk identity; initial
chunks remain in the evidence set. A repeated query is fingerprinted and is
not executed twice. The controller stops when the evidence requirements no
longer improve, even if a search returned new but irrelevant chunks.

The time budget is cooperative because the migrated retriever is synchronous:
the controller checks before and after each search call and starts no further
call after the deadline. It cannot interrupt a single embedding, Qdrant, or
cross-encoder call already in progress. The token budget is for retrieved
evidence text; there is no LLM generation or provider-token spend in P3.
