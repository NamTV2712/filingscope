# G5 structured observation on SEC filing excerpts

## Objective and protocol

Compare the existing deterministic policy with the same policy using
Groq GPT-OSS 120B relevance observations. Reuse the labeled Q4
fixed-candidate cohort. Both arms receive the same SEC physical page,
source title and question, with a 16,000-character prefix for oversized
pages. Deterministic similarity uses the frozen labeled chunk vector.
One page is truncated. The 18 candidates cover 11 annotated single-slot
questions. A multi-slot calculation and a forecast without a labeled
page are outside this protocol. All source and label artifacts are
development-exposed. Freeze the request plan before execution.

The provider returns a schema-validated `relevant`, `irrelevant` or
`unclear` classification. It receives the question and filing page.
Gold judgments are used only for scoring. The shared G1 observation
contract can only reduce the semantic score. The deterministic policy
still owns all identity, numeric, provenance and revision decisions.
The acceptance check requires every baseline hard rejection to stay
rejected. [Groq structured outputs](https://console.groq.com/docs/structured-outputs).

## Results

| Measure | Deterministic | Groq observation |
| --- | ---: | ---: |
| Correct support judgments on the 16 matched provider successes | 10/16 | 11/16 |
| Correct support judgments on all 18 planned candidates | 11/18 | 11/18 with two missing predictions counted as failures |
| Positive judgments on unsupported candidates, matched cases | 0/10 | 5/10 |
| Positive judgments on supported candidates, matched cases | 0/6 | 6/6 |
| Policy decisions on all 18 planned candidates | 13 WEAK, 5 REJECT | 13 WEAK, 5 REJECT |
| Weakened hard rejections | 0/5 | 0/5 |

The deterministic support check requires the runtime's full evidence
finding. Its gray cases remain WEAK. The observer treated subgroup
revenue, membership fees, a year-over-year change, investee assets and
an original filing requested as restated as sufficient support. The
policy blocked the restated-filing case on revision. All policy
dispositions matched, so this replay showed no decision advantage.
Answer release accuracy, calibration and confidence intervals were
outside this candidate-level comparison.

The original 18 calls returned 16 valid observations and two HTTP 400
responses. The receipt remains `INCOMPLETE_PROVIDER_RUN`. Both failures
used the deterministic result. Two diagnostic calls raised the completion
cap from 256 to 768. The Activision case then returned `relevant` and
remained WEAK. The water utility case returned `json_validate_failed`.
The diagnostics preserve the original receipt and stay outside the
paired counts.

The 18-call run used 15,603 reported input tokens and 1,081 output tokens,
estimated at USD 0.002989. End-to-end provider p50 and p95 were 624.83 ms
and 1,458.93 ms across 18 attempts. Peak working set was 1,914,519,552 B
including index and embedding setup. The successful diagnostic added
934 input and 76 output tokens, estimated at USD 0.000186. Usage for
failed requests is unknown. [Groq GPT-OSS 120B rates](https://console.groq.com/docs/model/openai/gpt-oss-120b).

## Decision and reproduction

**KEEP** the deterministic policy. **REJECT** enabling Groq observation
by default for this path. The later TypeSafe run uses the same
observation contract and the frozen candidate plan.
[Live Jev comparison](G5_JEV_LIVE_PROTOCOL.md).

The focused benchmark and observer tests passed 21/21. The offline
suite passed 500 tests with three local fixture skips on Windows and
499 with four skips on WSL. Both returned 100% fixture disposition
and claim-status accuracy. Ruff and focused mypy passed.

```text
python -m scripts.run_g5_groq_observer --output .local/g5/groq-observer-dry-run.json
python -m scripts.run_g5_groq_observer --execute .local/g5/groq-observer-dry-run.json --output .local/g5/groq-observer-live.json
```

Use the G0 offline setup for preparation and the project Groq credential
for execution. Baseline Git commit `c600288`. The frozen plan's SHA-256
is `6105836ae05e2dfd3df9a06c08154a206edc8a40e20f1c8f7d389a66183d6808`.
The initial live receipt's SHA-256 is
`6fe892f9222a39b579ae14f7c624177870bda678c5beb1d6fc14ba2c4cc9df2f`.
The diagnostic receipt's SHA-256 is
`9e6a825517a773f172c3eec41e434d12ef59d37eebbf59ea419ad7207a9ca00d`.
