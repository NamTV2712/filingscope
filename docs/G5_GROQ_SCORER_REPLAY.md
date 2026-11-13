# G5 Groq numeric scorer replay

The shared scorer splits free-form answers on periods and can parse
days in fiscal dates as extra numeric claims. Test whether the frozen
JSON claim boundaries and issuer-specific period anchors recover
correct paraphrases. The acceptance checks require exact amounts and
currency, correct issuer and reporting scope, one distinct claim per
reference cell, and complete citation-locator matching. Keep the shared
historical scorer as the baseline. Use saved outputs for all 52 requests
and the single diagnostic probe. No new model calls are needed.

Regression controls cover correct dates, abbreviations, conflicting
year labels, wrong dates, quarter versus YTD, mixed issuers, amount
rounding, currency, segment and extraneous claim errors. The new scorer
is a deterministic comparison for the numeric pilot. It cannot
establish general semantic entailment.

## What changed

The replay reads each saved structured claim before sentence rendering.
It resolves the issuer through the existing company catalog and
normalizes the supported metric labels. It uses exact base-unit USD
values from the existing numeric parser. It removes validated fiscal
dates and duration phrases before parsing amounts. Fiscal year,
quarter, YTD and date phrases must agree with the reference cell.
The pilot's segment and reporting-basis checks reject consolidated,
adjusted, restated and component values where they conflict with the
question. Claim matching is one-to-one. A citation must match the
predeclared PDF page for its claim. These checks are specific to the
numeric pilot and its supported scopes.

## Paired results

| Outcome | Closed-book before → after | Filing-context before → after |
| --- | ---: | ---: |
| Exact financial identity | 0/23 → 0/23 | 1/23 → 22/23 |
| Exact with all frozen PDF locators | 0/23 → 0/23 | 1/23 → 20/23 |
| Answer coverage | 23/26 → 23/26 | 23/26 → 23/26 |
| Incorrect numeric answers among releases | 23/23 → 23/23 | 22/23 → 1/23 |
| Releases failing exactness or locator checks | 23/23 → 23/23 | 22/23 → 3/23 |
| Correct abstentions | 2/3 → 2/3 | 3/3 → 3/3 |
| Matching citation locators | 0/0 → 0/0 | 1/25 → 23/25 |

The updated counts reproduce the prior author's review. Apple annual
assets still cites the income statement. The Tesla segment value
cites a valid alternate statement page that was outside the frozen
reference. The main two-company case still lacks NVIDIA's claim.
The separately recorded page-selection probe scores 1/1 with both
frozen locators. It stays outside the primary cohort score.

The scorer processed 52 saved responses in 14.9 ms with peak process
working set of 117,436,416 bytes. API calls and additional charges
were zero. The earlier response latency and token counts are recorded
in the [Groq report](G5_GROQ_BASELINES.md).

## Verification and decision

The focused suite passed 28 tests, including 21 new claim controls.
The offline suite passed 496 tests on Windows with 3 fixture skips
and 495 on Linux WSL with 4 skips. Ruff, focused mypy and the offline
lock check passed. The shared
historical scorer and the production verification path are unchanged.

**KEEP** the typed replay as a reproducible metric for the provisional
Groq pilot. **DEFER** semantic accuracy claims outside this numeric
cohort. The independent G6 scorer still requires reviewer judgments.
Baseline commit `4e3a004`.

```text
uv run --offline --locked python -m scripts.rescore_g5_groq_baselines .local/g5/groq-120b-live.json --output .local/g5/groq-120b-live-typed-new.json
uv run --offline --locked python -m scripts.rescore_g5_groq_baselines .local/g5/groq-120b-comparison-probe.json --output .local/g5/groq-120b-comparison-probe-typed-new.json
```

The main [local rescore](../.local/g5/groq-120b-live-typed.json) has
SHA-256 `8533e86626acf9969d4ab622179600006d7d180d9921bc63d434f745d49d24db`.
The [probe rescore](../.local/g5/groq-120b-comparison-probe-typed.json) has
SHA-256 `68508fbcb3a201531dfaea43eb7f971df8ace20977f07836feebc3969af54722`.
