# G5 observer experiment and architecture baselines

## Objective and predeclared checks

Compare deterministic policy and the G1 observer adapter on the same
60 frozen policy fixtures. Test positive, negative and timeout mock
responses and report their behavioral effect, decision errors and local
timing. A mock transport gives no evidence about live Jev accuracy.
Every hard rejection must remain a rejection. Zero paid or hosted
model calls are permitted under the current authorization.

Use the fixed M13 cases and P1/SEC sources for the architecture
comparison. Compare Dense, Adaptive, forced LangGraph and full routed
LangGraph on the same case IDs. Record hosted closed-book and
long-context availability separately. The later Groq observer
comparison reuses the semantic observation contract on labeled SEC
pages. [Structured observer comparison](G5_GROQ_OBSERVER.md).
The [matched Jev protocol](G5_JEV_LIVE_PROTOCOL.md) freezes the same
candidates and includes the live TypeSafe results.

## Observer and dry run

`scripts/run_g5_offline_observers.py` replays the existing fixed
candidate features through the G1 adapter and the deterministic policy.
The provider-neutral request can be shaped as a Decisions API choice
request. OpenRouter documents `typesafe/jev-1.14`, the alpha decisions
endpoint and USD 0.042 per million input tokens. The script builds the
request locally. The 134-token example estimates USD 0.000005628 with
a local tokenizer proxy. Actual provider usage depends on its request
serialization. [Model and price](https://openrouter.ai/typesafe/jev-1.14),
[Decisions API example](https://openrouter.ai/blog/insights/what-is-jev/).

| Synthetic observer arm | Correct / 60 | Hard false accepts | ACCEPT → WEAK | Local p50 / p95 |
| --- | ---: | ---: | ---: | ---: |
| Deterministic only | 60 | 0 | 0 | 0.0029 / 0.0076 ms |
| Positive mock | 60 | 0 | 0 | 0.0052 / 0.0064 ms |
| Negative mock | 40 | 0 | 20 | 0.0078 / 0.0094 ms |
| Timeout mock | 60 | 0 | 0 | 0.0045 / 0.0050 ms |

No arm turned a gold ACCEPT into REJECT. The negative mock shows the
possible false downgrades from noisy observations. The timeout arm
injected 60 failures and returned deterministic decisions on all of them.
The timings measure local Python and mock execution. Peak working set was
78,970,880 B. Provider calls, billed tokens and spend were zero. Brier and
ECE are inapplicable to these scripted replies. The offline stage used
USD 0 authorization. A later matched TypeSafe run measured the live
snapshot, errors, latency and probabilities. [Live comparison](G5_JEV_LIVE_PROTOCOL.md).

## Architecture comparison

All arms use the same 24 historical M13 requests, including 21 answerable.
The Dense control uses the P1 index and deterministic writer. The adaptive
and specialist arms use the matching offline Company Facts snapshots
where configured. The ablation is descriptive because the enabled source
paths and release policy differ across arms. The adaptive, routed and
forced rows are from the G4 replay. Dense A0 and B6 were re-run in G5.

| Arm | Grounded exact | Coverage | Incorrect or unsupported risk | False abstention | Warm p50 / p95 | Mean tools |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Dense A0 | 0/21 | 14/24 | 14/14 | 7/21 | 63.59 / 92.86 ms | 1.00 |
| Adaptive with evidence and SEC | 21/21 | 21/24 | 0/21 | 0/21 | 15.61 / 147.04 ms | 1.25 |
| Forced LangGraph | 21/21 | 21/24 | 0/21 | 0/21 | 100.01 / 301.00 ms | 2.79 |
| Full routed LangGraph | 21/21 | 21/24 | 0/21 | 0/21 | 14.06 / 134.25 ms | 1.33 |

Historical citation-locator support was 0% for Dense A0 and 100% for
the three evidence-controlled arms. The result depends on M13's existing
labels and verifier contracts. Human claim faithfulness and strict
citation entailment remain unmeasured. M13 contains exposed examples.
The G4 forced and routed graph share policy and differ in how work is
scheduled. Under the G4 persistent fault test the routed specialist
retained healthy sources on 10/10 versus 5/10 for the adaptive arm.
Natural statement runtime retained 30/30 grounded answers in G4.
G5 B6 revalidated 21/21 grounded answers with zero incorrect releases.

The original hosted dry run sized all 24 question-only
prompts at 6,788 total input tokens. Eighteen requests had document
locators that allowed a full-text prompt estimate. Six fit a
100,000-token input budget. Twelve exceeded it, with a maximum
714,190 tokens. Those estimates use oracle document identities for
sizing. A live comparison will need predeclared source selection,
truncation, model revision and a common case set. No quality result
or provider cost is inferred from the dry run. Follow-ups measured
both conditions on the SEC 2025 pilot.
[Groq benchmark](G5_GROQ_BASELINES.md) ·
[Archived local comparison](G5_LOCAL_MODEL_BASELINES.md).

## Verification and decision

Windows offline suite passed 452 tests with 3 missing fixture skips.
The focused observer checks passed 21 tests. Ruff and focused mypy passed.
The full two-plane policy is still authoritative. **KEEP** deterministic
release. **EXPERIMENT** with observers offline. The subsequent live
comparison supported keeping the default deterministic.

```text
python -m scripts.run_g5_offline_observers --output .local/g5/observer-replay.json
python -m scripts.run_multi_agent_ablation --variants A0 B0 B6 --statement-pages data/financebench/cache/extracted_pages_d5c2a1369d9997a3055a.jsonl --output .local/g5/m13-architecture-controls.json
python -m scripts.plan_g5_hosted_baselines --output .local/g5/hosted-dry-run.json
```

Use the pinned G0 CPU and offline model cache settings. Baseline local
commit `3b03633219f1464964fd097b9e7f40ac86e3d36a`. The G6 readiness
work can proceed without paid APIs.
