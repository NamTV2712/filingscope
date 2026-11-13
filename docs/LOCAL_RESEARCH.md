# M15 local research workspace

FilingScope serves the existing specialist graph at `127.0.0.1` using a
validated FinanceBench index and the M13 SEC Company Facts snapshots. The
browser displays released answers, claim-linked source records, requirement
coverage, calculation inputs and results, verification decisions and an
execution timeline.

## Run locally

Install the repository requirements and prepare the pinned P1 corpus,
embedding manifest, embedded chunks and cached Nomic model using the
[FinanceBench setup](../README.md#financebench-retrieval-evaluation).
Prepare the nine SEC snapshots with the acquisition command in the
[M13 reproduction instructions](ABLATION_STUDY.md#reproduce-m13).
The launch command uses those artifact locations by default. Supply
`--p1-run` or `--sec-dir` when they are stored elsewhere.

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
uv run --offline python -m scripts.run_local_research
```

Open [the local workspace](http://127.0.0.1:8765). Automatic uses the
existing complexity router. Full research selects the existing RESEARCH
route for supported questions, which can inspect structured facts and
tables. The server accepts one research request at a time and returns a
retryable conflict while that slot is in use.

With the pinned PDF page cache, scoped filing searches prioritize statement
pages that contain the requested metric and fiscal period. Use
`--retrieval-policy dense` to replay the Dense control.
[Retrieval evaluation](POST_M15_RETRIEVAL_UTILITY.md)

## Writer configuration

The default writer formats approved filing facts and verified calculations
locally. For an authorized hosted experiment, enable `--provider-run`
with `--max-provider-calls`, `--max-provider-input-tokens`,
`--max-provider-output-tokens`, and `--max-provider-cost-usd`. Each limit
applies to the server process. The writer uses the configured Groq
credential in the local environment and logs model and usage totals.
The same atomic verifier checks both writers. Use
`--max-correction-passes 0` to disable the default single revision pass.
[Grounded writer evaluation](POST_M15_GROUNDED_WRITER.md)

Use `--stage-traces` for typed JSON spans on stderr. The spans carry
hashed request, source and evidence IDs, timestamps, stage status, stable
failure codes and usage. See the [reproduction guide](POST_M15_REPRODUCIBILITY.md#optional-hosted-experiment-and-local-traces).

## Evidence boundaries

- Progress is an allowlisted lifecycle enum. The response stream carries
  public event codes and a terminal result or error. Prompts, hidden graph
  state, unpublished claim text, source chunks and exception details are
  excluded.
- Source links carry the available filing locator. SEC facts include
  accession, taxonomy tag, fiscal interval and revision basis. A calculation
  links each normalized input to its evidence record and shows the check
  status, formula and rounding policy.
- The answer panel opens the source behind each citation. **Why this
  answer?** links supported claims to their evidence and calculation. A
  withheld answer displays requirement gaps, the reported reasons, and a
  shortcut to actual search receipts.
- Source coverage is restricted to the frozen corpus and SEC snapshots with
  a December 31, 2024 filing cutoff. A workbench smoke test validates the
  wiring, while [M13](ABLATION_STUDY.md) measures answer coverage across a
  larger cohort. The local writer may withhold an answer even when it
  has calculated a candidate value. One observed example was the absolute
  Apple FY2023–FY2024 revenue difference.

## Validation

| Offline smoke case | Released result | Retrieval / local tool calls |
| --- | --- | ---: |
| Apple FY2024 original revenue | Verified, USD 391,035,000,000 | 0 / 1 |
| Apple FY2023–FY2024 original revenue growth | Verified, 2.02% with two original filing inputs | 0 / 1 |
| Apple FY2030 revenue | Abstain, missing fiscal-year fact | 0 / 1 |
| Best Buy FY2019 total assets | Verified, filing retrieval and structured fact lookup | 2 / 3 |
| Investment recommendation request | Unsupported | 0 / 0 |

All five requests used zero LLM calls. The warm graph took approximately
1–118 ms across these examples. This small smoke run excludes startup,
browser rendering and live network latency.

Chromium was checked at 1366×900 and 390×844. The checks exercised example
input, keyboard submission, arrow and End tab navigation, a source jump with
focus, SEC accession display, verified calculation inputs, a simulated busy
response followed by a real successful retry, and an abstention without
horizontal overflow. No browser script errors were reported. The HTTP test
checks request and origin validation, stream framing and the zero-tool
unsupported path.

Source `4121d0b8c2f34a7ddb409de4939d5df5b3c101da` passed 346 tests with
3 skips, Python compilation, JavaScript syntax and Git whitespace checks.
All 32 development rows in the A0, A1, B4 and B5 ablation subset matched the
frozen M13 results across every field other than latency. The API smoke JSON
in `.local/m15-browser/api-results.json` has SHA-256
`21420929178eb74c2cebf2532e78bf93b37a63bae0716ed02b5d95a050bd3304`.
