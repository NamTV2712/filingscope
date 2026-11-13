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

## Validation and decision

The focused suite passed 26 tests. The new tests cover request parity,
gold omission, response usage, wrong snapshots, inconsistent choice
probabilities, timeouts and calibration denominators. The reused
policy replay tests verify fallback and preserve hard rejections.
The full offline suite passed 505 tests with three fixture skips on
Windows and 504 tests with four skips on WSL. Both reproduced 100%
claim-status and disposition accuracy. Ruff and focused mypy passed.

The live command stopped at the missing `OPENROUTER_API_KEY` check.
No requests, provider tokens or charges occurred. Live accuracy,
latency, RAM and calibration results are unavailable. **KEEP** the
matched protocol and deterministic authority. Live Jev stays
`API_VALIDATION_BLOCKED`. Baseline Git commit `62fb970`.

## Reproduce

Use the G0 pinned CPU environment and the public Q4/Groq receipts.
The first command is offline. The second sends the prepared questions
and public filing excerpts to OpenRouter when the key is configured
and the Jev run is authorized.

```text
python -m scripts.run_g5_jev_observer --groq-receipt .local/g5/groq-observer-live.json --output .local/g5/jev-observer-dry-run.json
python -m scripts.run_g5_jev_observer --groq-receipt .local/g5/groq-observer-live.json --execute .local/g5/jev-observer-dry-run.json --output .local/g5/jev-observer-live.json
```
