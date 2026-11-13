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
generation requests. Live generation awaits confirmation of the Free
organization plan or an explicit paid budget.

```text
uv run --offline --locked python -m scripts.run_g5_groq_baselines --pilot .local/g3/statement-normalization-pilot --output .local/g5/groq-120b-dry-run-new.json
```

For a confirmed Free organization, use a fresh output and add
`--execute-free`. The runner saves each successful case, spaces requests
within the published allowance and records a partial run on provider
errors. Use the measured output for the benchmark. No provider key,
reasoning text or API error body is stored in the report.

The earlier Qwen model weights were removed from the workspace on
request. Its observed metrics remain an archived experiment.
