# G5 Groq GPT-OSS 120B benchmark

Use Groq's `openai/gpt-oss-120b` for the matched closed-book and
long-context comparison on the same 26 SEC pilot questions. The two
conditions share a strict JSON claim schema, low reasoning effort and a
768-token completion cap. Closed-book sees the question. The context
condition uses the frozen filing pages for issuers named in the question,
prioritizes financial statement pages and records page truncation.
The planned input cap is 5,200 estimated tokens per request for the
published Free allowance. Its context is smaller than the historical
local experiment. Compare both Groq conditions on the same model and
report the actual provider token counts and served model identifier.

Groq model metadata returned HTTP 200 and confirmed the configured
credential can see the active model with a 131,072-token context.
The metadata endpoint did not expose the account's billing tier.
Groq publishes Free limits of 8,000 tokens/minute and 200,000
tokens/day for this model and lists Developer pricing of USD 0.15
per million input and USD 0.60 per million output tokens. Check the
organization's active plan before running under USD 0 authorization.
[Model and pricing](https://console.groq.com/docs/model/openai/gpt-oss-120b).
[Free limits](https://console.groq.com/docs/rate-limits).
[Billing](https://console.groq.com/docs/billing-faqs).

The dry run prepared 52 requests with 145,932 estimated input tokens,
39,936 maximum completion tokens and an estimated Developer-tier charge
of USD 0.04585 before cached-input discounts. It uses the
`o200k_harmony` tokenizer and reserves schema and envelope overhead.
The numbers are estimates and usage can differ. The dry run issued zero
generation requests. The live run followed the user's authorization
to proceed with Groq without the earlier USD 0 limit.

## Measured comparison

All 52 planned requests completed. No request hit a provider error or
returned invalid JSON. Every response identified `openai/gpt-oss-120b`.
The report records the varying provider system fingerprints. The
long-context arm supplied 7.46 pages per question on average and
truncated all 26 full issuer selections. All outcomes are
development-exposed and provisional.

| Outcome | Closed-book | Long-context |
| --- | ---: | ---: |
| Answers emitted | 23/26 | 23/26 |
| Correct abstentions | 2/3 | 3/3 |
| Exact by shared automated scorer | 0/23 | 1/23 |
| Grounded exact by shared automated scorer | 0/23 | 1/23 |
| Exact on author review of company, amount, unit, scope and period | 0/23 | 22/23 |
| Correct with every frozen PDF locator on author review | 0/23 | 20/23 |
| Input / completion tokens | 8,936 / 2,246 | 112,244 / 2,394 |
| Request p50 / p95 | 718 / 2,875 ms | 1,516 / 5,297 ms |
| Estimated Developer charge before cache discounts | USD 0.00269 | USD 0.01827 |

The automated score is sensitive to abbreviations like “Inc.” and
“Corporation”, alternative fiscal-date wording and net-sales labels.
The post-run author review preserved the original outputs and labels.
It identified two correct amounts with citations outside the frozen
reference. Apple annual assets cited the income statement. Tesla
energy revenue cited the consolidated income statement's valid
energy generation and storage row, while the frozen label points to
the segment discussion. The main comparison missed the NVIDIA half of
the multi-company question because no NVIDIA page survived truncation.

A subsequent deterministic replay of the raw JSON claims reproduced
the author's 22/23 exact and 20/23 frozen-locator counts. It checks
issuer, amount, period, currency and reporting scope for this numeric
pilot. [Typed scorer replay](G5_GROQ_SCORER_REPLAY.md).

One follow-up request kept an annual statement page for each issuer
before applying the same budget. It returned both exact values and
both frozen income-statement locators on author review. This was a
post-run diagnostic and is excluded from the table. It used 4,290
input and 127 completion tokens with a 3,172 ms HTTP duration.
The main run plus probe cost approximately **USD 0.02168** at
published uncached Developer rates. The invoice was unavailable.

The matched Adaptive and routed hybrid arms each grounded 22/23
under the shared scorer. They withheld the Tesla segment case and
answered the two-company case. The Groq context arm recovered the
segment value and failed the two-company case before the probe.
[Architecture controls](G5_LOCAL_MODEL_BASELINES.md#results).

## Reproduction

```text
uv run --offline --locked python -m scripts.run_g5_groq_baselines --pilot .local/g3/statement-normalization-pilot --output .local/g5/groq-120b-dry-run-new.json
```

Use `--execute` for an authorized run or `--execute-free` to
pace against the published Free allowance. The runner saves each
successful case. It can resume an interrupted run with the same output
and request plan. Use `--comparison-probe` for the separate single-case
truncation test. The completed run initially used Free pacing and
resumed with the remaining cases after removing that local delay.
No provider key,
reasoning text or API error body is stored in the report.

The earlier Qwen model weights were removed from the workspace on
request. Its observed metrics remain an archived experiment.

**KEEP** GPT-OSS 120B as the hosted benchmark control. Use the measured
token budget and reference receipts. The observed results show the
impact of supplying filing pages and the need to score paraphrases
with reviewer adjudication. Live Jev remains a separate provider
experiment.

The [52-request report](../.local/g5/groq-120b-live.json) has SHA-256
`d03565eb3d1e15ce6a757dc5c0a86113358be05b65081c70a18a813c87a7a7d6`.
The [probe report](../.local/g5/groq-120b-comparison-probe.json) has
SHA-256 `aa66f3e8a069418b0c84fe04fc8738280a54d4c9150dafb5914830bd4e3db772`.
The focused Groq request and scorer controls passed. The Windows
offline suite passed 475 tests with three unavailable local fixtures
skipped. Ruff, focused mypy and the lock check passed.
