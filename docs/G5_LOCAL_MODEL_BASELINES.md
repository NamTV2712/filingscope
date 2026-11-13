# G5 local closed-book and long-context baselines

Compare a pinned Qwen2.5-7B-Instruct Q4_K_M snapshot in two conditions
on the same 26 development-exposed SEC questions as the specialist
graph. Both conditions use local inference and greedy decoding. The
closed-book arm sees the question alone. The long-context arm sees
PDF pages for the issuers mentioned in the question, including every
pilot filing for those issuers. It never sees a gold value, gold page
or a graph output. Prefer the full text within budget. For overflowing
inputs put physical financial-statement pages first, then other pages
in document order, and keep the longest prefix that fits. Keep page
IDs fixed across truncation and record what was dropped. Source
selection is issuer-only and uses the same rule for both answerable
and unanswerable questions.

Measure complete numeric answer correctness, citation-locator grounded
exactness where citations are available, abstention, released errors,
latency, tokens and resource use. For closed-book, report correctness
separately from evidence support. Model drafts are raw baseline outputs.
The test does not change FilingScope's release policy. The main
comparison uses the G3 normalized pilot graph. Select model, prompts
and resource limits before collecting predictions. Treat model
pretraining exposure to these filings as unknown.

Run the existing Dense A0 and Adaptive research controls on the same
questions and normalized index. A0 uses PDF retrieval and the direct
renderer, so its raw answers are scored before any release gate.
Adaptive uses the same Company Facts and PDF inventory as the routed
graph and retains deterministic verification.

Use the upstream [Qwen GGUF snapshot](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/tree/bb5d59e06d9551d752d08b292a50eb208b07ab1f)
and [llama.cpp b12345](https://github.com/ggml-org/llama.cpp/releases/tag/b12345).
The predeclared context window is 16,384 tokens, with 256 tokens
reserved for output and room for tokenization overhead. Report observed
truncation and the actual server counts. Hosted Jev stays blocked
under the current API authorization.

## Reproduce

The tested Windows Vulkan archive has SHA-256
`f9bb0fc734a9731d22f7106e3961e8a5ed83d1a905295ca4759c78ba82e6997e`.
The two GGUF shard hashes are pinned by the runner. The server used
the reported build `b12345 / 2a4daf0e0` and an RTX 5060 Laptop GPU.
Use the device number returned by the pinned server's `--list-devices`.
The two model shards must be in the same directory.

```text
llama-server -m .local/g5/local-model/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf --host 127.0.0.1 --port 18055 --alias qwen2.5-7b-instruct-q4_k_m --ctx-size 16384 --parallel 1 --device Vulkan1 --gpu-layers 99 --flash-attn on --no-context-shift --offline
uv run --offline --locked python -m scripts.run_g5_local_baselines --pilot .local/g3/statement-normalization-pilot --model-dir .local/g5/local-model --server .local/g5/local-model/runtime/llama-server.exe --output .local/g5/local-model-baselines-new.json
uv run --offline --locked python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --architecture-controls --output .local/g5/local-architecture-controls-new
```

The model scorer uses complete claim matching with the verified-release
check disabled for raw drafts. A model answer without a correct frozen
locator can be numerically correct. Malformed or truncated output is
counted as an error and retained in the per-case report. Source labels
are assigned before page ordering and truncation. The runner binds the
question and page cache hashes and logs the exact prompt hash, selected
source IDs, server token usage, raw model output and warm HTTP duration
for each case. Warm duration excludes local token-count probes and
server model load. The architecture comparison reuses the G3 normalized
vectors and verifies the paired source hashes.

## Results

| Arm | Exact under shared scorer | Grounded by frozen locator | Answers emitted | Incorrect or unsupported by scorer | Warm p50 / p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Closed-book Qwen 7B | 0/23 | 0/23 | 25/26 | 25/25 | 1.37 / 2.14 s |
| Long-context Qwen 7B | 1/23 | 1/23 | 26/26 | 25/26 | 10.88 / 12.04 s |
| Dense A0 | 0/23 | 0/23 | 17/26 | 17/17 | 33.20 / 47.23 ms |
| Adaptive with PDF and Company Facts | 22/23 | 22/23 | 22/26 | 0/22 | 9.06 / 110.12 ms |
| Routed hybrid graph | 22/23 | 22/23 | 22/26 | 0/22 | 9.07 / 111.79 ms |

The shared scorer expects the labeled metric phrase, fiscal label and
numeric signature. It undercounts correct natural paraphrases from the
local model. A post-run author review counted 17/23 long-context answers
with correct amounts and financial identity, including issuer-specific
fiscal end dates and equivalent terminology. Twelve also cited every
required frozen PDF locator. The closed-book outputs still had 0/23
exact amounts across all required claims. The raw outputs and strict
scores are preserved. The author review is development-exposed and
carries no independent adjudication claim.

| Long-context cases judged correct in author review | Cases with all required frozen locators |
| --- | --- |
| Apple annual revenue, operating income, net income and assets | Revenue, operating income, net income |
| Apple quarter revenue and operating income | Both |
| NVIDIA annual net income and assets | Net income |
| Tesla annual revenue, operating income, assets and energy revenue | Operating income and assets |
| Walmart annual revenue, operating income and assets | Revenue and operating income |
| Apple and NVIDIA two-year revenue questions | Both |

The six answerable misses were Apple YTD revenue, Apple YTD operating
income, Apple Q3 assets, NVIDIA annual revenue, NVIDIA annual operating
income and the Apple/NVIDIA comparison. They included a prior-year YTD
amount, a discrete quarter reported as YTD, annual assets substituted
for quarterly assets, rounded numbers and NVIDIA's revenue attributed
to Apple. The Tesla energy draft recovered the correct amount and cited
the balance sheet. The long-context model also answered all three
unanswerable controls. The closed-book model withheld the future case
and answered the currency and revision controls. Adaptive and routed
withheld the Tesla segment case and all three unanswerable controls.
Dense A0 often emitted numbers from the wrong period or with missing
scale.

Long-context used 410,916 input and 1,634 output tokens. All 26 full
issuer selections exceeded the budget, ranging from 96,271 to 304,032
tokens before truncation. Actual input was 15,427–15,935 tokens per
question and contained 17.69 pages on average. Closed-book used 4,456
input and 1,492 output tokens. All 52 local calls stopped normally.
The Python runner peaked at 162,414,592 B, and the model server peaked
at 9,817,841,664 B working set. The sampled GPU usage near completion
was 5,382 MiB for the entire GPU. Adaptive and routed averaged
1.31 and 1.58 tool calls. All arms incurred USD 0 provider spend.

## Verification and decision

Windows offline verification passed 472 tests with 3 local fixture
skips. Linux WSL passed 471 with 4 skips. The focused runner and scorer
checks passed 6 tests. Ruff, mypy, lock and syntax checks passed. The
paired architecture run matched every non-timing G3 pilot case field
in the three existing source tracks.

**KEEP** the local baselines as development controls. The routed graph
and Adaptive tied on this cohort. **DEFER** live Jev and hosted model
comparisons. The local Qwen measurement depends on one checkpoint and
its context budget. Independent generalization and risk remain open.

Baseline Git commit `af9e614`. The [model report](../.local/g5/local-model-baselines.json)
has SHA-256 `f1c2d031b515af1f303ff236f4effc0752a92c0240fd899430197aa0c54bc429`.
The [matched architecture report](../.local/g5/local-architecture-controls/report.json)
has SHA-256 `315f0ecd65fe2f9fef1c85c0f62c257f4f6744998559b89607ce441283b7c32c`.
