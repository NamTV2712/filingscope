# M5 finite complexity routing

## Status

M5 implements a deterministic, finite LangGraph router in
`src/agent/complexity_router.py`. It selects `FAST`, `RESEARCH`, or
`UNSUPPORTED`, records stable reason codes, and prepares a bounded M4 research
plan. It does not execute retrieval, generation, tools, or agents, and it is
not wired into the P5 answer path.

## Graph and classification

```text
START → classify_request ── FAST ─────────→ fast_path ───────→ END
                         ├─ RESEARCH ─────→ research_path ───→ END
                         └─ UNSUPPORTED ──→ unsupported_path → END
```

The graph has no loops, checkpoint store, fan-out, or model-based classifier.
It uses the existing deterministic `EvidenceRequirementExtractor`, optionally
extended with company aliases in a runtime `CorpusMap`. Broad/repeated filing
work, multi-company questions, and causal reasoning select `RESEARCH`;
single-period lookups, one-document requests, and bounded single-company
calculations select `FAST`. Unresolved companies or metrics, missing periods
for calculations, future-period requests, and predictive/advisory questions
select `UNSUPPORTED` and receive no retrieval or model budget.

`FAST`, `RESEARCH`, and `UNSUPPORTED` carry immutable caps:

| Limit | FAST | RESEARCH | UNSUPPORTED |
|---|---:|---:|---:|
| Graph steps | 4 | 8 | 2 |
| Total tool calls | 3 | 10 | 0 |
| Retrieval calls | 2 | 6 | 0 |
| LLM calls | 1 | 3 | 0 |
| Candidate chunks | 10 | 50 | 0 |
| Context tokens | 8,000 | 24,000 | 0 |
| Concurrency | 1 | 3 | 0 |
| Wall time | 15 s | 60 s | 0 s |
| Planned tasks | 2 | 6 | 0 |

M5 enforces graph-step, planned-task, and planned-retrieval-call caps. It
records zero actual calls, tokens, and cost because the graph is a router and
planner only. Candidate, context, concurrency, and execution wall-time limits
remain contracts for later execution milestones; they cannot be meaningfully
measured before retrieval and generation run inside the graph.

LangGraph is pinned to `1.2.20` (MIT). The implementation uses its typed
`StateGraph` and conditional edges, then compiles the finite graph before
invocation. See the [StateGraph reference](https://reference.langchain.com/python/langgraph/graph/StateGraph),
the [Graph API guide](https://docs.langchain.com/oss/python/langgraph/graph-api),
and [PyPI release metadata](https://pypi.org/project/langgraph/). No source
code was copied. This milestone measures routing latency but does not compare
LangGraph with an equivalent plain-Python implementation.

## Evaluation

- **Behavior fixture:** 56 hand-authored questions, eight per complexity
  class. Labels exercise the deterministic policy itself. They are not
  independently annotated or representative of request prevalence.
- **Unlabeled request sample:** the fixed 150 public FinanceBench questions,
  split by company into 60 development, 45 validation, and 45 held-out cases.
  Only question strings reach either router. Gold answers and evidence labels
  are not used for routing or scoring.
- **Corpus treatment:** question-only alias catalog versus the same rules
  initialized with the frozen M4 Corpus Map from index
  `3ea92c895826e46ccf03ee52248771cc83e779e90b1660c390d29f2c4abfd18f`
  (84 documents, 28,849 chunks). The map is loaded before the timed routing
  run.
- **Inputs:** synthetic fixture SHA-256
  `f30f9c3554753c962bb98e870f859aa7acabfb40957918c21be1304fb5b8457d`;
  FinanceBench question-set SHA-256
  `9fc32b9e6d789b7bb4b4ebcfd843c102dab5cc87ee6644e783ca9128674d6c96`.
- **Reproduction:**

  ```powershell
  .venv\Scripts\python.exe -m scripts.run_complexity_router_evaluation `
    --run-dir data\financebench\runs\3ea92c895826e46ccf03ee52248771cc83e779e90b1660c390d29f2c4abfd18f `
    --output data\financebench\router_runs\m5-complexity-routing-v1.json
  ```

  The generated report is ignored local data. It captures input and source
  fingerprints, reason counts, routing distribution, latency, budgets, and
  actual resource use.

## Results

| Measure | Hand-authored fixture | FinanceBench, question only | FinanceBench, Corpus Map |
|---|---:|---:|---:|
| Cases | 56 | 150 | 150 |
| Class accuracy / macro F1 | 1.000 / 1.000 | not labeled | not labeled |
| `FAST` selections | 24 | 4 | 36 |
| `RESEARCH` selections | 24 | 0 | 10 |
| `UNSUPPORTED` selections | 8 | 146 | 104 |
| Routing p50 / p95 | — | 3.438 / 5.316 ms | 4.320 / 11.891 ms |
| Research-path selection errors | 0 / 32 expected non-research | not measured | not measured |
| Incorrect fast-path selections | 0 / 24 expected research | not measured | not measured |

The fixture had zero class mistakes, zero unsupported-path mistakes, and zero
budget violations. These are rule-behavior checks against labels authored with
the rules; they do not estimate real routing accuracy. FinanceBench has no
routing labels, so its FAST/RESEARCH/UNSUPPORTED counts are a distribution,
not a quality score. The map moved 42 questions out of `UNSUPPORTED`: 32 to
`FAST` and 10 to `RESEARCH`. It also raised router p95 by about 6.6 ms.

With the map, the split distributions were development 14/5/41, validation
8/4/33, and held-out 14/1/30 (`FAST`/`RESEARCH`/`UNSUPPORTED`). Across the
sample, `metric_not_recognized` occurred 77 times,
`operation_missing_required_period_scope` 21 times, and `company_not_resolved`
16 times; some questions had more than one missing requirement. The high
unsupported count shows that the current metric and period vocabulary is too
narrow for broad natural-language support. The router fails closed and exposes
clarification reasons instead of widening the taxonomy from evaluation labels.

Across the 150 questions in each treatment, the map-aware planner formed 68
bounded tasks with 68 planned retrieval queries. The question-only planner
formed 6. Neither executed retrieval. Both treatments made zero model,
provider, retrieval, tool, or multi-agent calls; actual model tokens and cost
were zero. Answer quality, evidence quality, and the correctness of any
selected FAST route were not measured.

Router construction took 14.404 ms for the two configurations. The full
evaluation took 1,811.6 ms and used 1,968,146 bytes of peak incremental Python
allocations; process RSS was not measured. These timings exclude loading the
local corpus-map input. The artifact records source commit
`0fffebc0d5d0a6b88532e3c3b0969a9f3246509f`, source fingerprint
`db6a2cadc922512bae188d6ced044c35c803c9a8f6febd33715d2f713f6c1f57`, and a
clean source working tree.

## Decision and next work

**ADOPT** the finite deterministic route contract and typed budgets as the
entry point for M6. **KEEP** unsupported requests at zero retrieval/model
budget and preserve the dense P1 baseline. Do not claim an answer-quality or
multi-agent invocation improvement: this graph does not run workers. M6 has
added the shared in-memory Evidence Ledger; later execution milestones must
enforce the remaining candidate, context, concurrency, wall-time, and cost
limits before the research route can perform work.
