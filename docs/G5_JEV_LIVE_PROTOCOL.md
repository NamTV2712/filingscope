# G5 Jev live comparison protocol

Use the same 18 labeled public filing pages and the same frozen
deterministic features as the Groq observer replay. The plan records
the Groq plan hash, Jev request hashes, expected model, estimated
tokens and price before execution. The tests must reproduce the
documented OpenRouter response shape, fall back on transport and
schema failures, and preserve all hard rejections. Compare provider
support judgments on matched valid predictions. Treat probabilities as
diagnostic estimates of direct support and keep them outside policy.

## Dry-run result

The dry run matched all 18 Groq candidate IDs, source locators,
reference judgments, request hashes and deterministic policy features.
The Jev requests use the same question, source title and page text.
The runner requests `typesafe/jev-1.14` and checks for the documented
served snapshot `typesafe/jev-1.14-20261014` from TypeSafe. It calls
OpenRouter's Decisions endpoint with one typed choice per page.
[OpenRouter request and response example](https://openrouter.ai/blog/insights/what-is-jev/).

The plan estimated 15,485 input tokens using `cl100k_base` as a proxy.
The published rate gives an estimated USD 0.00065037. The local plan
at `.local/g5/jev-observer-dry-run.json` has SHA-256
`9ecf6efda737459b59888b909f4fa3688a21ed6f29eed19d0956977f8bfb0195`.
The referenced Groq receipt hash is
`6fe892f9222a39b579ae14f7c624177870bda678c5beb1d6fc14ba2c4cc9df2f`.
[Jev 1.14 pricing](https://openrouter.ai/typesafe/jev-1.14).

## TypeSafe live comparison

The credential configured for the OpenRouter attempt was issued by
TypeSafe Console. OpenRouter returned HTTP 401 and recorded zero
reported tokens. The direct TypeSafe model endpoint authenticated the
key. The benchmark then sent the same 18 frozen inputs to the TypeSafe
System One endpoint with model `jev-1.14.0`. The runner now supports
explicit provider selection and stops on HTTP 401, 402 or 403.
[TypeSafe API](https://docs.typesafe.ai/api/system-one) · [Model and pricing](https://docs.typesafe.ai/models).

| Measure | Deterministic | Groq GPT-OSS 120B | TypeSafe Jev 1.14 |
| --- | ---: | ---: | ---: |
| Correct support judgments on the 14 shared binary predictions | 8/14 | 9/14 | 10/14 |
| Correct support judgments on own binary predictions | 11/18 | 11/16 | 11/16 |
| False support judgments on own binary predictions | 0/11 | 5/10 | 5/9 |
| Valid provider results / attempts | — | 16/18 | 18/18 |
| Unclear classifications | — | 0 | 2 |
| Policy changes / hard rejections weakened | — | 0/18 / 0/5 | 0/18 / 0/5 |

Jev marked all seven positive pages relevant. Five negatives were
also marked relevant. They include subgroup revenue, membership fees,
a year-over-year change, quarterly operating income for an annual
question and an original filing for a restated request. The
year-over-year distractor received support probability 1.0. The
deterministic policy retained all 13 WEAK and five REJECT decisions.
The release policy and runtime configuration are unchanged. The
sample is development-exposed, and this experiment measures candidate
decisions. Answer-level performance requires a separate benchmark.

Across all 18 Jev results, the direct-support probability had Brier
score 0.1806 and five-bin ECE 0.2278. The bin counts were 5, 1, 2, 0
and 10. These are descriptive diagnostics on a small selected cohort.

TypeSafe reported 23,272 input and 844 output tokens across 18
successful requests. Estimated cost was USD 0.00097742 at the
published input rate. Native usage reports token counts and the
receipt uses those counts to estimate cost. Warm request p50/p95 was
590.40/2,671.42 ms. Peak process working set was 1,914,109,952 bytes
including embedding and index setup. Native dry-run SHA-256 is
`d57d65be680cf04472c68785c29a5ec4f87db9590e0902b441afc29cb02e434e`.
The live receipt SHA-256 is
`7aec4a6170f5bb8d5195b97b1e9a9e8514e8df6d70f726c479dbaa394a2193c7`.

## Validation and decision

The focused suite passed 30 tests. The new tests cover request parity,
gold omission, response usage, wrong snapshots, inconsistent choice
probabilities, timeouts and calibration denominators. The reused
policy replay tests verify fallback, preserve hard rejections and stop
after the first account-level error. The full offline suite passed 512
tests with three fixture skips on Windows and 511 tests with four skips
on WSL. Both reproduced 100%
claim-status and disposition accuracy. Ruff and focused mypy passed.

**KEEP** the matched protocol and deterministic authority. **REJECT**
enabling Jev by default for this path. Its page classification differed
from Groq, while the policy outcomes matched the deterministic arm.
G5's live Jev comparison is measured on the stated cohort. The original
OpenRouter-only baseline was `62fb970`, and the TypeSafe run followed
`1b38a23`.

## Reproduce

Use the G0 pinned CPU environment and the public Q4/Groq receipts.
Use `TYPESAFE_API_KEY` for a key from TypeSafe Console. The first
command is offline. The second sends the prepared questions and public
filing excerpts to TypeSafe when the run is authorized.

```text
python -m scripts.run_g5_jev_observer --provider typesafe --groq-receipt .local/g5/groq-observer-live.json --output .local/g5/jev-typesafe-dry-run.json
python -m scripts.run_g5_jev_observer --provider typesafe --groq-receipt .local/g5/groq-observer-live.json --execute .local/g5/jev-typesafe-dry-run.json --output .local/g5/jev-typesafe-live.json
```

The default `--provider openrouter` expects `OPENROUTER_API_KEY` and
the separate OpenRouter plan. Provider credentials stay local.
