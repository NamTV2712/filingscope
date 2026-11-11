# FilingScope Architecture

## Current implementation (P0–P5 and M1–M8)

### Offline document and evaluation paths

```text
SEC EDGAR HTML ──→ section extraction ──→ chunks and financial tables
                                              │
FinanceBench PDFs ──→ page extraction ────────┤
                                              ↓
                           pinned embeddings ──→ Qdrant
                                              ↓
                         BM25 + dense + lexical candidates
                                              ↓
                              RRF + optional reranker
```

The ingestion and retrieval code is migrated from the source project. P1 adds
PDF page extraction, a corpus manifest, and an offline retrieval evaluator.
Dataset labels remain inside the evaluation package and are not passed to the
runtime retrieval implementation.

### Evidence decision and adaptive retrieval

```text
Question + retrieved chunks
           ↓
Requirement extractor
  entities · metrics · explicit periods · operations · required slots
           ↓
Evidence coverage analyzer
  provenance · value/period alignment · conflicts · operation compatibility
           ↓
Decision policy + remaining retrieval-attempt budget
  ├── ANSWER       structurally sufficient inputs
  ├── RETRIEVE_MORE
  │       ↓
  │   Bounded controller plans a company/metric/period query
  │       ↓
  │   Existing HybridRetriever.retrieve() → merge unique evidence
  │       └──────────────────────────────────────────→ reassess
  └── ABSTAIN      unsupported requirement or exhausted retrieval budget
```

`src/decision/` does not call a model or inspect retrieval scores. The analyzer
only sees chunks explicitly supplied by its caller. `ANSWER` means the
registered evidence requirements are met; it does not assert that a generated
answer is correct. The decision result retains requirement IDs, operation gap
codes, evidence IDs, page/source provenance, and reason codes.

`src/agent/adaptive_retrieval.py` handles only `RETRIEVE_MORE`. It derives one
target query from a current missing/conflicted slot or operation gap, invokes
the migrated `HybridRetriever.retrieve()`, preserves initial evidence, merges
new chunks, and reassesses. Round, total-query, evidence-token, and cooperative
elapsed-time limits bound the run. Query fingerprints prevent exact duplicate
calls; coverage changes and trace outcomes make no-progress stops inspectable.

The P2 evaluation uses 15 fixed synthetic scenarios. The P3 controller uses
nine fixed synthetic scenarios plus a temporary Qdrant/HybridRetriever
integration test. See [`DECISION_EVALUATION.md`](DECISION_EVALUATION.md) and
[`ADAPTIVE_RETRIEVAL_EVALUATION.md`](ADAPTIVE_RETRIEVAL_EVALUATION.md) for
measured results and limitations.

### Claim, citation, and numerical verification

```text
Question + answer clauses + source-ordered evidence chunks
                         ↓
             Canonical citation audit
     valid · missing · malformed · out-of-range
                         ↓
        Claim entity / metric / period / value
                         ↓
  P2 evidence facts from cited chunks only
     ├── direct financial fact matching
     ├── percentage growth recomputation
     ├── period difference recomputation
     └── topical lexical-anchor comparison
                         ↓
       claim status + response disposition
  VERIFIED · PARTIAL · REJECTED · ABSTAIN
```

`ClaimLevelVerifier` adapts the source project's `[Source N]` citation,
malformed legacy citation, and fallback-answer integrity checks from
`src/evaluation/answer_contract.py`. Claim values are matched using the P2
period/value parser and entity/metric-scoped evidence analyzer; source text
outside the citations attached to a claim is never considered. Growth and
difference calculations use `Decimal`, require compatible currencies and
scales, and fail closed when inputs conflict or are missing. Direct financial
fact mismatches are contradicted; absent metric/period support is unsupported;
invalid citations, ambiguous values, or conflicting sources are unverifiable.

Topical checking is intentionally lexical, so a valid paraphrase can be
classified as partial, unsupported, or unverifiable. The fixed P4 test set
contains 15 synthetic cases and is not a semantic benchmark or a real-response
accuracy estimate. Results and failure categories are in
[`VERIFICATION_EVALUATION.md`](VERIFICATION_EVALUATION.md).

## P5 offline end-to-end evaluation

`src/evaluation/end_to_end_evaluation.py` joins the frozen P1 retrieval
artifacts to the runtime decision layer, bounded adaptive controller, grounded
answer generator, and claim verifier. A0–A2 compare retrieval variants; A3
gates generation on evidence sufficiency; A4 adds bounded targeted retrieval;
A5 applies claim verification as the final answer gate. The harness also checks
replay parity and records per-stage timing, usage, and per-case checkpoints.
This is a reproducible batch evaluation path, not a public request API or
interactive research application.

The provider-backed run completed for 150 FinanceBench cases. Held-out answer
coverage was 44.4%, 35.6%, and 40.0% for A0–A2 and 0% for A3–A5; numeric exact
accuracy was 0% for every variant on held-out cases. The strict decision and
verification components therefore work as controls but currently reject or
abstain on too many cases. These are failure findings, not a demonstrated
end-user quality gain. See [`BENCHMARK_RESULTS.md`](BENCHMARK_RESULTS.md) and
[`FAILURE_ANALYSIS.md`](FAILURE_ANALYSIS.md).

## M4 corpus-aware planning

`src/research/corpus_map.py` aggregates a versioned metadata-only inventory of
the indexed corpus. `src/research/planner.py` exposes question-only and
Corpus-Map-conditioned planning modes, with explicit `AVAILABLE`, `MISSING`,
and `UNKNOWN` states and document IDs sourced only from the map. A fixed
150-case comparison showed a BM25 Recall@10 increase from 0.1133 to 0.1567
overall and from 0.0889 to 0.1111 on held-out cases. The experiment also
recorded the latency increase and missing metadata limits; it did not measure
answer generation. The planner remains standalone and does not alter the P5
path or dense retrieval default. See
[`CORPUS_AWARE_PLANNING.md`](CORPUS_AWARE_PLANNING.md).

## M5 finite complexity routing

`src/agent/complexity_router.py` compiles a deterministic LangGraph with
`classify_request` followed by one terminal branch: `fast_path`,
`research_path`, or `unsupported_path`. The first two prepare bounded M4 plans;
the unsupported branch assigns zero downstream call budget. Route profiles
carry graph-step, tool, retrieval, LLM, candidate, context-token, concurrency,
wall-time, and task caps. M5 enforces graph steps, planned task count, and
planned retrieval count. The other caps require retrieval/generation
executors, which are not part of this milestone. No branch invokes a model,
provider, retriever, or worker, and the router does not change P5 behavior.

The authored 56-case policy fixture has 100% class agreement, but it is not
independent semantic validation. In the label-free 150-case FinanceBench route
distribution, the M4 Corpus Map selected 36 FAST, 10 RESEARCH, and 104
UNSUPPORTED routes. Unknown metrics, period-scope gaps, and unresolved company
names explain the high unsupported share. Answer quality and actual agent
invocations were not measured. See
[`COMPLEXITY_ROUTING.md`](COMPLEXITY_ROUTING.md).

## M6 shared Evidence Ledger

`src/ledger/` provides immutable evidence/fact/calculation/claim/verification
records and a mutable request-scoped `EvidenceLedger` that emits validated,
deterministically sorted snapshots. Evidence IDs derive from request/source
identity. Merges stage and validate the full reference graph before commit,
coalesce duplicate discoveries, and reject incompatible stable task/claim or
verification records. `DERIVED_FACT` rows point to a calculation and retain
all ordered input evidence IDs. The ledger is in memory only; it does not
replace or connect the P2, M3, or P4 decision authority, and P5 does not yet
use it. See [`EVIDENCE_LEDGER.md`](EVIDENCE_LEDGER.md).

## M7 specialist research graph

`src/agent/specialist_graph.py` compiles the M5 route into a bounded execution
path. FAST runs filing retrieval, evidence analysis, report writing, and claim
verification in four graph nodes. RESEARCH runs the supervisor, filing worker,
official SEC Company Facts worker, table worker, evidence analyst, financial
reasoner, report writer, and claim verifier in eight nodes. UNSUPPORTED ends
in one node with no downstream calls. The workers pass evidence IDs through a
request-scoped M6 ledger; filing text stays in invocation-local runtime
context. Retrieval, tool, candidate, token, LLM, and graph-step use is counted
against the selected route budget.

The graph reuses P2 sufficiency and P4 verification. M3's candidate policy is
not integrated. M7's XBRL support is deliberately narrow: standard concept
aliases, a resolved ticker, and a requested period from official Company Facts
fixtures or an explicitly supplied client. It does not resolve tag drift,
amendment precedence, duration/instant equivalence, or restatements; M9 owns
those cases. The graphs are tested with fake retrieval and SEC clients. No
live SEC request, provider call, P5 integration, answer-quality benchmark,
parallel fan-out, persistence, or deployment is part of M7. Details and
limitations are in [`SPECIALIST_RESEARCH_GRAPH.md`](SPECIALIST_RESEARCH_GRAPH.md).

## M8 parallel filing research

The RESEARCH supervisor dispatches independent filing tasks with LangGraph
Send. Each worker receives a bounded assignment and keeps source text in
private runtime storage. The next stage merges the worker ledgers and
records failures before running the SEC worker. The existing evidence
analyst consumes the merged sources. [M8 validation](PARALLEL_RESEARCH.md)

## Target: separate logical planes

```text
RESEARCH PLANE
question → intent/risk → bounded route → corpus-aware tasks → retrieval paths
        → specialist observations linked to evidence IDs
                                  │
                                  ▼
                       shared Evidence Ledger
                                  │
                                  ▼
EVIDENCE CONTROL PLANE
provenance + entity/metric/period + source authority + numeric consistency
        → candidate policy → sufficiency/gaps → calculations → claim support
        → deterministic ANSWER / PARTIAL / ABSTAIN / REJECTED release policy
```

This is still a target architecture. M3 adds `src/policy/` as an independent,
typed candidate-decision component with a deterministic policy, but it is not
connected to the M7 execution graph or P5 answer path. M4 adds `src/research/`
with a standalone runtime Corpus Map and corpus-aware task planner. M5 adds a
finite complexity router; M7 executes its route through a finite sequential
specialist graph and an in-memory M6 ledger. These components remain outside
P5. The XBRL worker only supports a narrow standard-tag path; M9 owns advanced
fact reconciliation. M8 adds filing fan-out for adapters that support
concurrent retrieval. `src/decision/`,
`src/verification/`, and `src/agent/adaptive_retrieval.py` remain the starting
points; extend them instead of replacing them with broad framework
abstractions. See [`CURRENT_ARCHITECTURE_AUDIT.md`](CURRENT_ARCHITECTURE_AUDIT.md)
and [`RESEARCH_AGENDA.md`](RESEARCH_AGENDA.md).

## Research milestone sequence

M1 is complete as the offline end-to-end evaluation path. M2 retrieval stage
diagnostics are complete; dense remains the permanent baseline because no
fusion or reranking variant beat it on the held-out cohort. M3's deterministic
candidate policy and separate 60-case synthetic benchmark are complete, with
the limitation that the policy is not yet part of the P5 answer path and its
fixtures do not measure financial-document accuracy. M4's standalone
Corpus-Map-conditioned planner is complete and measured; dense remains the
retrieval baseline, and P5 integration is deferred pending downstream
evaluation. M5's deterministic router and route-budget contract are complete
but are not connected to retrieval, generation, or P5. M6's in-memory shared
ledger and deterministic merge contract are complete, but snapshots do not
persist. M7 adds a bounded sequential specialist graph and a narrow SEC Company
Facts path. M8 adds bounded parallel filing searches. M9 advances XBRL
reconciliation, followed by parser comparisons, verification, hard negatives
and agent ablations.
M15 may add a local evidence-first interface. Cloud deployment is out of scope
unless explicitly requested.
