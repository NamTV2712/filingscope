# FilingScope Post-M15 reproducibility

## Environment and offline CI

Use Python 3.12 and the pinned packages in `requirements.txt`. Install the
PyTorch wheel for the machine before resolving the requirements. GitHub
Actions uses the CPU build `torch==2.15.0+cpu` on Ubuntu 24.04. The local
research replays used Python 3.12.7 on Windows, CPU PyTorch and six threads.
Manifests record exact installed dependency versions. `psutil==7.2.2`
provides peak working set measurements for the real-corpus replays.

```powershell
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0+cpu
python -m pip install -r requirements.txt
python -m pip check
python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
python -m scripts.check_tracked_secrets
python -m compileall -q configs scripts src tests
python -m scripts.run_offline_checks
```

Install dependencies and prime the small, checksum-verified tiktoken
vocabulary before enforcing offline mode. The offline runner denies outbound
Python socket connections for test collection, fixture tests and evaluation.
Loopback is available for local tests. The GitHub workflow requires read-only
repository access and uses tracked fixtures. Its steps cover dependency
compatibility, Python syntax, deterministic regression and the fixed P4
claim/citation evaluation. [Workflow](../.github/workflows/backend.yml).

## Sources, versions and splits

| Input | Revision and use |
| --- | --- |
| FinanceBench public OPEN_SOURCE sample | 150 queries over 84 referenced PDFs. Dataset revision `e04404e3a97f69f79c14d42f24981a1c9c3bcd18`. Source repository revision `cc39aeb4afdf33909ee1412188bf89035950c2eb`. Dataset CC BY-NC 4.0. The company-grouped repository split is 60/45/45. Use the acquisition and attribution rules in the [dataset protocol](DATASET_PROTOCOL.md). |
| Frozen P1 index | `3ea92c895826e46ccf03ee52248771cc83e779e90b1660c390d29f2c4abfd18f` with pinned pypdf page cache, normalized corpus and vectors. File hashes are checked on load. |
| Nomic text embeddings | `nomic-ai/nomic-embed-text-v1.5` revision `e9b6763023c676ca8431644204f50c2b100d9aab`. Cache the model at that revision during setup, then use the cache offline. The model card lists Apache-2.0. [Model card](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5/tree/e9b6763023c676ca8431644204f50c2b100d9aab). |
| SEC Company Facts replay | Nine CIK snapshots with a `2024-12-31` filing cutoff. `m13-sec/manifest.json` records per-file hashes and retrieval metadata. Resolved evidence records carry the filed date, accession, concept, interval, currency and revision. |
| M13 and Q3 direct | M13 is an exposed 24-case real-filing benchmark (8/8/8 historical memberships, 21 answerable). Q3 direct has 15 cases with 14 answerable and overlapping issuer coverage. Historical labels remain exposed. |
| Q2 through Q7 development and validation | Project-authored, source-checked labels. Q2 has 57 labeled PDF cells and 9 SEC checks. Q4 has six answerable and six withholding controls. The Q5/Q6 filing set has 13 development and 20 validation requests including three withholding controls. Q7 has 4 development and 8 validation comparisons across separate issuer groups, plus two disclosure controls. Cohort scripts and manifests bind label content, locators and membership. These small cohorts are provisional. |
| FinRank | Scoring-design reference for M12 and Q5. The release lists CC BY-NC 4.0. FilingScope's experiments use existing FinanceBench passages and local judgments. [FinRank release](https://github.com/datanxt/FinRank). |
| Independent final evaluation | Awaiting a reviewer-held cohort with source-checked labels, distinct issuer groups and a later filing window. Follow the [sequestering and freeze procedure](POST_M15_EVALUATION_PROTOCOL.md#independent-cohort-procedure). Keep benchmark labels and expected source locators outside runtime and the public repository until release is authorized. |

Keep the PDF and SEC corpora, source datasets, models, vectors, results and
traces under ignored local paths. Retain provenance and honor the terms of
the source documents separately from dataset and model licenses. Dataset
versions used by historical runs are in their phase manifests.

## Prepare local artifacts

An existing authorized snapshot is the most direct way to replay a frozen
run. The manifest includes the source and embedding revisions, source and
snapshot hashes, corpus fingerprint and index identity. To acquire missing
sources, first consult [FinanceBench acquisition](../README.md#financebench-retrieval-evaluation)
and [M13 SEC acquisition](ABLATION_STUDY.md#reproduce-m13). The initial
acquisition and model caching use the network. The SEC step uses EDGAR
fair-access identification and request bounds. Compare newly retrieved
snapshot hashes with the original before claiming exact reproduction.

```powershell
python -m scripts.download_financebench
python -m scripts.run_financebench_retrieval
python -m scripts.run_multi_agent_ablation --acquire-sec
```

## Reproduce selected results

Use the commit named in each phase report for historical metrics. Keep the
original benchmark files and use a fresh output directory or new filenames.
For the final backend use the following commands from the repository root
after priming the required caches. Paths in this example are relative to
the repository.

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OPENBLAS_NUM_THREADS = '6'
$runs = 'data/financebench/ablation_runs'
uv run --offline --with psutil==7.2.2 python -m scripts.run_specialist_architectures `
  --faults --output "$runs/replay-architectures.json" --manifest "$runs/replay-architectures-manifest.json"
uv run --offline --with psutil==7.2.2 python -m scripts.run_retrieval_utility `
  --variants dense natural_dense natural_runtime --safety --output "$runs/replay-natural-runtime.json"
python -m scripts.run_grounded_writer_evaluation --candidate "$runs/replay-natural-runtime.json" `
  --output "$runs/replay-writer-summary.json" --manifest "$runs/replay-writer-manifest.json"
```

The writer summarizer uses the preserved Q5 natural control and historical
P5 archive for its comparison. The Q6 phase report names these inputs and
their provenance. For the current routed M13 grounded score, inspect
`cohorts.m13.C_routed.overall` in the architecture output. The `by_class`
and `per_case` fields provide denominators, cited sources and dispositions.
For source isolation, inspect `fault_replay.unavailable_source`. For the
33-case filing score, inspect `real.after`, `real.by_split` and `real.paired`
in the writer output. Check all manifest artifact hashes before comparing
metrics. Elapsed times, timestamps and complete JSON hashes may vary across
replays. Confirm stable outcomes by case ID and claim/citation adjudication.

## Optional hosted experiment and local traces

Run the loopback backend with `python -m scripts.run_local_research`.
`--stage-traces` writes JSON stage metadata to stderr. Match the hashed
request ID to `trace_id(execution.request_id)`. Source and evidence IDs are
fingerprints of the matching ledger identifiers. Stage events include
timestamps, stable failure codes and usage. They omit questions, drafts,
document excerpts, transport exceptions and credentials. The typed trace
is also available as `SpecialistExecution.stage_traces` in Python.

Hosted runs require separate authorization and a local `GROQ_API_KEY`.
The loopback command accepts `--provider-run` with four positive process
limits covering attempts, input tokens, output tokens and modeled USD.
The documented P5 historical evaluation has its own budgeted CLI in
[the end-to-end protocol](END_TO_END_EVALUATION_PROTOCOL.md). CI uses mocked transports.
The v2 prompt and local approved-fact serialization differ from the
historical P5 prompt. Hosted v2 answer quality is unmeasured.

## Known limits

Benchmarks measure exact release for the specified filing snapshots and
labels. Generalization to a later, independently reviewed cohort and a
population unsupported-release target require further evidence. The local
deterministic narrative grammar covers explicit industry disclosures.
Throughput and latency depend on CPU, model cache, worker scheduling and
the shared embedding lock. The fault replay measures one specified source
outage model. A new index build may require rechecking the frozen corpus
and numerical results before comparison.
