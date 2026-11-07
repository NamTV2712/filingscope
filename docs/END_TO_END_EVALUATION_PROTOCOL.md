# End-to-End Evaluation Protocol (P5)

P5 measures answer quality and evidence controls on the pinned 150-case
FinanceBench open-source sample. It uses the same company-grouped development,
validation, and held-out split (60/45/45) and the immutable P1 corpus/index.
P5 results do not tune the held-out split.

## A0–A5 variants

| Variant | Pipeline |
|---|---|
| A0 | Dense retrieval + answer generation |
| A1 | Hybrid retrieval + answer generation |
| A2 | Hybrid retrieval + cross-encoder reranking + answer generation |
| A3 | A2 + evidence sufficiency decision; generation only on `ANSWER` |
| A4 | A3 + bounded targeted retrieval and final evidence decision |
| A5 | A4 + P4 claim and citation verification; abstains on `PARTIAL`, `REJECTED`, or `ABSTAIN` |

A0–A2 use the frozen P1 per-case retrieval artifacts. A3 and A4 use the
reranked P1 evidence, then A4 may call the migrated hybrid retriever for up to
3 rounds, 6 queries, 16,000 evidence tokens, and 30 seconds. A5 reuses A4's
answer, so its incremental generation call count and cost are zero.

## Leakage boundary and frozen generation settings

The gold answer is attached only to an evaluation record. The generator
receives the question and retrieved evidence chunks; it never receives the
gold answer, justification, or gold evidence annotation. Generated run files
include case identifiers and answers but exclude gold answer text and source
chunk text.

The generator is Groq `openai/gpt-oss-120b`, temperature 0, with a 1,024-token
output cap and a 20,000-token estimated prompt cap. Prompt labels are assigned
in evidence order as `[Source N]`. Each answer uses one API request with SDK
retries disabled. The source project's separate post-answer correction request
is intentionally omitted so each generation call has a visible fixed budget.
The run manifest records the target Git revision, a source-file fingerprint,
model, prompt version and hash, dataset revision, corpus/index fingerprints,
retrieval run, adaptive limits, request count, usage, and cost model.

The dry run loads the P1 index and performs retrieval/decision stages but makes
no provider calls and requires no key. It estimates prompt tokens with the
pinned `tiktoken cl100k_base` encoding, applies a 25% margin to prompt-token
cost, and assumes the full output cap for each planned request. The estimator
is conservative but remains an estimate because provider tokenization and
billing can differ. The cost input snapshot is linked to the published
[Groq GPT-OSS 120B rates](https://console.groq.com/docs/model/openai/gpt-oss-120b).
The caller must explicitly opt in with `--provider-run` and supply both a call
limit and approved USD cap. A budget is checked before each API request.
Every attempted request counts against the call limit, including a request that
fails before returning a response. Settled usage and outstanding request
reservations both count toward the cumulative modeled spend cap. Provider runs
write ignored local checkpoints after each attempt and successful response;
resume only with the same source fingerprint, prompt, model, case selection,
call cap, and cost cap. A checkpoint avoids repeating completed response calls.

## Metrics

All answer-quality results are reported separately for the frozen development
(60 cases), validation (45), and held-out (45) company groups. The held-out
table is the primary reported score; development and validation are shown for
analysis and threshold/model selection. The combined all-split aggregate is
descriptive only. Quality and latency charts and the ablation comparison use
held-out metrics; provider calls and modeled spend remain whole-run totals.

- **Normalized text exact match:** ordered word tokens agree after case,
  punctuation, and `[Source N]` markers are removed.
- **Answer token precision, recall, and F1:** lexical overlap with the gold
  answer. This is an answer-quality proxy, not semantic grading.
- **Numeric exact answer accuracy and fact precision/recall/F1:** extracted
  numeric facts compare value, currency, scale, kind, and fiscal period after
  normalizing scales. Bare years and citation markers are excluded. Cases whose
  gold answer has no numeric fact are not in the numeric denominator.
- **Answer coverage and abstention:** fraction answered and fraction abstained.
  Correct/false abstention counts use retrieval coverage of annotated evidence
  pages as a proxy, not a human answerability label.
- **Risk/coverage:** answer coverage paired with token F1 on answered cases.
- **Citation and claim support:** the P4 verifier's citation validity, claim
  status counts, and unsupported/contradicted claim rate.
- **Adaptive retrieval:** query and round counts, plus the share of cases that
  began with a retrieval gap and ended with sufficient evidence.
- **Latency and provider use:** p50/p95 component-sum latency, retrieval-stage
  timings (including query embedding, dense search, hybrid fusion, and
  reranking), prompt and completion tokens, generation call count, and
  token-priced modeled cost. P5 replays the frozen P1 A0–A2 retrieval settings
  to measure retrieval latency and records chunk-ID parity with the immutable
  P1 evidence used for answers. P5 measures decision, adaptive retrieval,
  generation, and verification stages during the answer run. Modeled cost is
  not a provider invoice.

Dry-run artifacts explicitly mark answer-quality metrics as not measured. The
summary publisher rejects dry runs and partial case sets, so estimated results
cannot be presented as completed benchmark scores.

## Reproduction

From the project root, acquire the pinned data and retrieval artifacts if they
are not already present, then produce a no-call preflight:

```powershell
python -m scripts.download_financebench
python -m scripts.run_financebench_retrieval
python -m scripts.run_end_to_end_benchmark
```

After approval of the displayed call count and spend cap, configure the local
`GROQ_API_KEY` and run the full benchmark. If a provider interruption occurs,
the ignored checkpoint path is preserved; resume with `--resume-from <path>`
and the same frozen arguments. Pass the resulting full-run `results.json` to
`scripts.summarize_end_to_end_benchmark` to create the
benchmark, ablation, failure, and SVG chart documents. All source data, index
files, per-case predictions, and generated answers are git-ignored.
