# M8 Parallel Research

Source commit `2131e3cda186874b5bd1dc17a516454256437b99`.

The RESEARCH route uses LangGraph Send to run independent filing searches by
company, metric and fiscal period. The supervisor groups identical queries
before dispatch. Each assignment carries its objective, allowed retrieval
tool, requirement IDs and a share of the route budget. Workers record
candidate provenance in private ledgers. The next specialist stage merges
their receipts in stable order and passes the merged sources to the existing
evidence analyst and report writer. [LangGraph Send reference](https://reference.langchain.com/python/langgraph/types/Send)

## Adapter and budget

Adapters can declare `supports_concurrent_retrieval = True`, or callers can
pass `retriever_concurrency_safe=True` to `SpecialistResearchGraph` for a
backend they know can accept simultaneous calls. The existing serial path
serves unmarked adapters, including the default local retrieval backend.
The route caps concurrent filing workers at three by default. Each worker
can make one retrieval call and receives a candidate allowance allocated
before dispatch. Queued workers check the shared wall time budget before
starting retrieval. Synchronous calls already in progress finish under
their adapter's timeout policy. The structured SEC, table, reasoning and
verification stages run in sequence.

The result reports actual calls, retained candidates, peak concurrent tasks,
duplicate candidates and queries grouped before dispatch. Fan-in preserves
all task links for identical evidence, isolates failed workers and excludes
workers that return inconsistent versions of the same chunk. Table searches
reuse identical queries within the request.

## Validation

Run `uv run python -m scripts.benchmark_parallel_research` to reproduce the
comparison. Each mode ran 20 measured requests after one warmup. The
retriever simulated 40 ms of blocking I/O for each of six filing calls and
returned empty results. The experiment measures scheduling and latency for
that workload. Live retrieval speed and answer quality remain unmeasured.

| Concurrency limit | Peak tasks | Retrieval calls per request | p50 | p95 |
|---:|---:|---:|---:|---:|
| 1 | 1 | 6 | 250.85 ms | 251.65 ms |
| 3 | 3 | 6 | 87.44 ms | 87.89 ms |

The median fell by 65%. Both modes used zero SEC requests and zero model
calls. Six new integration tests cover bounded overlap, candidate quotas,
stable results under reversed completion order, failure isolation,
deduplication, serial fallback and conflicting chunk versions. The full
suite passed with 269 tests and 3 skips.
