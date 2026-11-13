# G4 specialist orchestration and verification

## Objective and predeclared checks

Reduce repeated parsing of the same question inside the deterministic
router and specialist evidence analyst. Preserve public route/response
schemas and require same-question binding before reusing requirements.
Compare calls to the same extractor for fixed FAST, RESEARCH and
UNSUPPORTED requests. Require identical stable release, citation,
retrieval and recovery results on the G3 historical replay. Reuse the
existing injected filing failure and prompt-injection tests. Adoption
requires measured work reduction and zero critical safety regressions.

## Implementation

The classification node retains immutable `QuestionRequirements`
in internal LangGraph router state for source selection. The specialist
analyst uses the requirements already bound to its request, checks
that they belong to the same question, and calls the existing
deterministic sufficiency decision with freshly analyzed evidence.
This keeps candidate screening and sufficiency aligned. Planning,
tool budgets, source isolation, numerical checks and final release
use the existing code. No new provider or output fields are required.

| Fixed request and measured extractor | G3 calls | G4 calls |
| --- | ---: | ---: |
| FAST single issuer annual lookup | 4 | 2 |
| RESEARCH two-issuer growth | 3 | 2 |
| UNSUPPORTED forecast | 2 | 2 |

Counts instrument the router's extractor instance. Independent
planner extraction and claim verification remain outside the count.
The baseline was run from an archive of `45eeac4`, and the candidate
was run with the same dependency environment.

## Safety and regression

The focused suite passed 68 tests, including nine existing filing
prompt-injection and unsafe-draft regressions. The Windows offline
suite passed 451 tests with 3 missing HTML fixture skips.
Ruff and focused mypy passed.

The same pinned historical P1 and SEC inputs were replayed against
G3 and G4. M13 routed stayed 21/21 grounded, with 21/24 coverage,
0/21 incorrect releases and 0/21 false abstentions. The natural
statement cohort stayed 30/30 grounded and 0/30 incorrect releases.
M12 Recall@10 remained 56.25%. Persistent outage healthy-source
retention stayed at 5/10 adaptive and 10/10 LangGraph. Both recovered
10/10 transient failures. All nine writer gates passed. Existing
citation outcomes reproduced. General narrative entailment and strict
claim faithfulness still require adjudicated cases.

M13 warm p50/p95 was 20.64/205.65 ms on G3 and 14.06/134.25 ms
on G4. These single-pass timings include runtime noise. Peak working
set stayed near 2.01 GB. The natural statement replay retained 38
tool calls and 14 embeddings. Hosted calls, billed tokens and cost
were zero. The verified gain is fewer deterministic extractions.

**KEEP** reuse of same-request requirements. **DEFER** broader
qualitative inference until reviewed narrative evidence can measure
false acceptance. The architecture, evidence budgets and release
contract remain consistent with the G0 matrix.

Reproduce the local checks with the
[G0 replay commands](G0_BASELINE.md#reproduce) and
`python -m pytest -q tests/test_specialist_requirement_reuse.py tests/test_research_security.py`.
G4 builds over local G3 commit
`45eeac47f36669f4442fbd669d93a0ca31865312`.
G5 next compares observer behavior and baseline availability under the
USD 0 API budget.
