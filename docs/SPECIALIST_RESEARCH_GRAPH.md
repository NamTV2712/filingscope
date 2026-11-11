# M7 Specialist Research Graph

## Status and scope

M7 adds a finite, sequential LangGraph over the M5 router, M4 research plan,
existing retrieval interface, M6 request ledger, P2 evidence sufficiency, and
P4 claim verifier. It does not modify the P5 benchmark path. The graph has no
parallel fan-out, checkpointing, autonomous loop, or persistence.

Source commit: `eb3654113823240d93d043e714647f4b69f22910`.

The source entry point is `SpecialistResearchGraph` in
`src/agent/specialist_graph.py`; worker contracts and invocation-local context
are in `src/agent/specialists.py`.

## Route traces

```text
FAST:        filing_worker → evidence_analyst → report_writer → claim_verifier
RESEARCH:    supervisor → filing_worker → structured_data_worker → table_worker
             → evidence_analyst → financial_reasoner → report_writer → claim_verifier
UNSUPPORTED: unsupported_path
```

FAST numerical requests run the deterministic reasoner inline with the
evidence analyst so the route remains four graph nodes. The unsupported path
does no retrieval, SEC, or model work. The runtime rejects a supported plan
that exceeds the selected route's planned task or retrieval budget and checks
the executed graph trace against its step cap.

## Worker contracts

Each worker returns a strict `SpecialistTaskResult` with status, task IDs,
evidence IDs, missing requirement IDs, structured observations, measured call
counts, candidates, context tokens, and elapsed time. Raw retrieved text stays
inside one `SpecialistRuntime` for the lifetime of a graph invocation. Graph
state carries the question, plan, route, trace, answer, IDs, and structured
worker results.

- **Supervisor:** records the bounded plan and any planner warnings.
- **Filing research:** groups duplicate queries, calls the existing retriever,
  deduplicates candidates by chunk ID, and adds metadata-only evidence records.
- **Structured financial data:** when configured with an SEC client and a
  ticker mapping, reads a narrow standard-tag allowlist from the official SEC
  Company Facts API. It keeps concept, raw/normalized value, unit, reported
  period, form, filing date, accession, CIK, and source URL. It emits facts
  into the ledger only after P2 finds a requirement gap that XBRL can fill.
- **Table evidence:** promotes retrieved table chunks and can spend remaining
  retrieval allowance on table-shaped queries for tasks without matching
  table evidence. It retains table ID and the base source provenance.
- **Evidence analyst:** runs the existing P2 decision layer, uses table/text
  evidence first, and falls back to XBRL for uncovered requirements. P2
  remains the sufficiency authority.
- **Financial reasoner:** calculates supported period growth and absolute
  difference using `Decimal`; it skips CAGR, nonpositive growth baselines,
  unknown/incompatible units, and conflicting or unsupported inputs. Derived
  facts retain calculation and input evidence IDs.
- **Report writer:** renders supported lookups/calculations deterministically.
  An injected existing `AnswerGenerator` may be used when deterministic output
  is unavailable and coverage is sufficient; there is no default provider
  construction.
- **Claim verifier:** calls the existing P4 verifier, remaps chunk references
  to ledger evidence IDs, and records generated claims and verification.

## Budget and safety behavior

The invocation counts graph steps, tools, retrievals, model calls, candidate
chunks, context tokens, and elapsed wall time against the selected M5 route.
Retrieval and SEC/tool starts are cooperatively refused when their configured
limits are exhausted; candidate counts bound retained chunks; the report
writer checks context-token and LLM-call limits before generation. Wall-time
checks occur before a worker starts work and do not interrupt a blocking
adapter call already in progress. The graph is sequential, so M8 concurrency
limits are not yet applicable.

The SEC client requires a contact-bearing User-Agent, centralizes throttling
and HTTP errors, and exposes estimated and actual request counts. Unit tests
mock HTTP responses. The specialist suite uses synthetic SEC JSON and fake
retrieval. No live SEC calls or model-provider requests were made.

## XBRL limits

The M7 adapter handles a short allowlist of standard revenue, net income,
assets, liabilities, operating income, gross profit, and cash tags. The alias
list is a retrieval fallback, not a reviewed concept equivalence map. Rows are
selected for a requested year/quarter using SEC fiscal fields and filing date;
the code does not establish that two concepts, duration intervals, or
amendment revisions are equivalent. Custom taxonomy resolution, dimensions,
fiscal calendars, robust unit conversion, as-reported/restated policy, and
amendment precedence remain M9 work. No fact accuracy is claimed from the
synthetic fixture.

## Validation

`tests/test_specialist_graph.py` and `tests/test_sec_client.py` pass 20 focused
tests, including 4-node FAST execution, FAST growth, zero-call unsupported
execution, 8-node research execution over two companies, table retrieval
within the remaining route budget, SEC CIK URL formatting, invalid CIK
rejection, and mocked HTTP behavior. The full suite passes with 263 passed and
3 skipped. These checks establish software contracts and integration flow;
there is no real-document answer-quality, XBRL accuracy, latency, or cost
benchmark for M7.

Related design: [`MULTI_AGENT_ARCHITECTURE.md`](MULTI_AGENT_ARCHITECTURE.md),
[`FINANCIAL_FACT_ARCHITECTURE.md`](FINANCIAL_FACT_ARCHITECTURE.md), and
[`EVIDENCE_LEDGER.md`](EVIDENCE_LEDGER.md).
