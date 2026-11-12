# Q6 — Grounded generation and verification

Q5 control commit `72c8451b003dbb9b24cb48e77812e0f1cfb3ab0d` used an
embedded deterministic writer and passed retained retrieval chunks to a
separate optional P5 generation path. The verifier received the entire
retained set. Q6 asked whether one approved-evidence boundary could support
both writers while preserving numeric and citation checks.

## Writer and release contract

`GroundedReportInput` carries question requirements, the evidence coverage
decision and its gaps, ordered approved source records, and validated
calculations. Each source links a ledger record with the observations that
filled a required slot. The deterministic writer, optional provider prompt,
and atomic verifier share one citation order. Verification of numeric facts
reads the approved observations from each source. A separate financial fact
on the same physical page is outside that approval.

- `DeterministicWriter` is the default and formats the accepted facts or
  the Decimal calculation results. Structured lookups, revision-sensitive
  answers and calculations always take this path. A calculation must pass
  the existing numerical verifier before entering the writer and is
  independently checked again at release.
- `OptionalProviderWriter` adapts the existing P5 Groq adapter for
  sufficient, non-calculation requests. Its prompt carries the approved
  numerical facts and citations. A qualitative request can supply an
  excerpt from an approved source. Missing context, transport errors,
  exhausted limits and an empty provider draft leave deterministic
  answering available. The atomic verifier still decides what can release.
- The local backend activates provider mode only with an explicit flag,
  credentials from the local environment and four positive limits covering
  attempted calls, input tokens, output tokens and modeled USD cost. The
  process reserves estimated input with a margin, output and cost before
  each attempt. A failed attempt retains its reservation. The pinned
  adapter makes one request without retries and uses a ten-second timeout
  for local hosted mode. Usage logs show the configured model, attempts,
  responses, reported token totals, missing usage and modeled cost. The
  cost calculation uses the existing pinned tariff.
- Atomic records retain claim and requirement IDs, source evidence links,
  calculation IDs where applicable, status and reason codes. The verifier
  distinguishes facts, calculations, directional comparisons, qualitative
  statements, uncertainty and speculation. The default permits one
  deterministic revision. `--max-correction-passes 0` disables it.
  Additional filing retrieval remains bounded by the existing route.

The original 3M draft failures occurred after evidence selection. The
numeric scanner read the `3` in the issuer's name as a second amount. The
scanner now treats the identifier as a word while continuing to recognize
an explicitly denominated amount such as `USD 3M` as three million.

RAGChecker and Ragas were studied as secondary diagnostics. Their
claim/context assessments can help localize failures. FilingScope's period,
revision, provenance and Decimal checks continue to authorize releases.
The external metrics were deferred for this offline run.
[RAGChecker](https://arxiv.org/abs/2408.08067) · [Ragas faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/)

## Paired real-filing replay

The Q5 source-checked cohort supplies 30 answerable requests and three
withhold controls. Both versions use the same P1 embeddings, page cache,
statement ranking, graph budgets and local SEC snapshots. The approval
step reduced the mean evidence passed onward from 670 to approximately 474
tokens across 33 requests. There were 14 embedding calls, 38 tools, zero
LLM calls, zero generation tokens and USD 0 provider cost in each run.

| Measure | Q5 deterministic | Q6 unified deterministic |
| --- | ---: | ---: |
| Grounded exact among answerable | 26/30 | 30/30 |
| Numeric exact among answerable | 26/30 | 30/30 |
| Development grounded exact | 9/13 | 13/13 |
| Validation grounded exact | 17/17 | 17/17 |
| False abstention | 4/30 | 0/30 |
| Correct abstention | 3/3 | 3/3 |
| Unsupported release | 0/26 | 0/30 |
| Citation support | 100% | 100% |
| Grounded required claims | 33/37 | 37/37 |
| Warm graph p50 / p95 | 13.3 / 122.7 ms | 15.2 / 109.0 ms |

All four improvements were 3M lookups for quarterly and year-to-date
revenue, quarterly operating loss, and quarterly total assets. The paired
grounded exact improvement was 13.3 percentage points with an issuer-group
bootstrap interval of 0–40 points across ten connected groups. The gain
was concentrated in one development issuer. The M13 replay preserved
21/21 grounded answers and 3/3 correct abstentions. The direct-fact replay
preserved 14/14 grounded answers and 1/1 correct abstention.
Peak working set was 2.016 GB in the control and 2.017 GB in the candidate
process. Timing and memory are single-process Windows CPU observations.

## P5 reference and provider simulation

The frozen historical 150-question P5 archive recorded 461 provider attempts
and 460 successful responses across A0–A4. The run logged 1,895,740 prompt
tokens and 136,654 completion tokens with USD 0.354987 modeled from reported
usage. A4 released three answers. A5 withheld all 150. Its p95 was
3,922.189 ms. This historical benchmark used a broader cohort and an
earlier evidence pipeline.

The fixed-draft comparison used the original P5 adapter with a mocked
transport on seven real filing cases. The same filing pages and drafted
claims drive P5-style verification and the new specialist writer. The
mocked provider's quality is determined by the fixture. Hosted Q6
answer-quality evaluation was **NOT RUN**.

| Path | Grounded exact among six answerable | Unsupported content | Correct withhold |
| --- | ---: | ---: | ---: |
| P5 adapter mock draft | 3/6 | 4/7 drafts | 0/1 |
| P5 adapter with P4/A5 gate | 0/6 | undefined, 0 releases | 1/1 |
| Unified deterministic | 6/6 | 0/6 releases | 1/1 |
| Unified optional provider mock | 4/6 | 0/4 releases | 1/1 |

The unified provider path verified three paraphrases. It retained PayPal's
requested revenue and removed the added operating income from the same
filing page in one correction. It rejected a sign error, withheld a draft
with a missing citation and skipped the provider for the currency mismatch.
The mocked provider made six attempts. Budget, outage and zero-correction
cases are exercised separately by regression tests.
The mock logged 1,936 estimated input tokens and 240 fixture output tokens.
The seven P5 mock calls logged 4,761 estimated input tokens and 280 fixture
output tokens. Both transports ran locally at USD 0 actual provider cost.

## Reproduction and limits

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OPENBLAS_NUM_THREADS = '6'
$runs = 'data/financebench/ablation_runs'
uv run --offline --with psutil==7.2.2 python -m scripts.run_retrieval_utility --variants dense natural_dense natural_runtime --safety --output "$runs/q6-grounded-writer-verified.json"
python -m scripts.run_grounded_writer_evaluation --candidate "$runs/q6-grounded-writer-verified.json" --output "$runs/q6-writer-summary.json" --manifest "$runs/q6-writer-manifest.json"
```

The loopback API verified four 3M requests and the Apple/Microsoft
growth comparison, then withheld the PayPal restatement. The script checks
numeric values and citation locators against the frozen labels. All six
requests used zero provider calls. The fixed-draft simulation measures
release and failure behavior. Hosted quality, actual provider tokenization,
provider response latency and invoice cost remain unmeasured for Q6. The
3M improvement uses one issuer and the real-filing labels still await
independent review.

The full suite passed 383 tests with no failures and three existing
missing-local-HTML skips. All nine recorded gates passed. The Q6 summary
SHA-256 is `667756a250abfbc6ac112c8cb75f28a23018c1ceb84bf38b07bc679a567c2e76`.
The Q6 phase commit contains this report. Q7 compares the direct, single
agent and specialist workflows using the unified writer and release policy.
