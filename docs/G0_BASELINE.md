# G0 architecture and engineering baseline

## Objective and acceptance criteria

Freeze the current CPU research baseline and test whether a locked
environment and targeted dependency fixes preserve its behavior.

The comparison uses the existing socket-guarded backend suite, fixed
decision and verification fixtures, and the same frozen P1 index, M13 SEC
snapshots and exposed Q3/Q5/Q7 cases on Windows before and after dependency
changes. Preserve the routed and alternative architecture results, per-case
grounded correctness, release and citation outcomes, retrieval scores,
writer safety gates and fault recovery. Compare stable case outputs
independently of timing and resource measurements. Require a clean checkout
to pass the offline CI steps and document all unresolved dependency
findings. Measure warm per-case latency, tool and model usage, and process
peak memory where available. These single-host timings describe the run.
The evaluation budget is zero paid calls.

## Architecture conformance and implementation inventory

| Stage | Current implementation | G0 finding |
| --- | --- | --- |
| Intent, risk and routing | `ComplexityRouter`, `RequirementExtractor` and `SourceInventory` in `src/agent/complexity_router.py` and `src/decision/` | Implemented. Typed financial requirements and source capability route FAST, RESEARCH or UNSUPPORTED. FAST can use Company Facts, statement pages or filing retrieval. |
| Planning and bounded specialists | `CorpusMap` and `CorpusAwarePlanner` in `src/research/`. Compiled `SpecialistResearchGraph` in `src/agent/specialist_graph.py`. | Implemented. The planner caps tasks, and the graph executes Filing, Structured Data, Table, Evidence Analyst and Financial Reasoner stages with tool budgets, scoped source assignments and bounded recovery. Adaptive retrieval also has an existing controller and evaluation path. |
| Frozen retrieval | `src/retrieval/frozen_dense.py`, `frozen_artifacts.py`, `financial_statement_ranker.py` and `scripts/run_local_research.py` | The loopback research backend loads the verified local corpus and vectors, scores exact cosine, scopes by document and can promote matching statement cells. A real pinned Nomic model embeds queries. |
| Qdrant and hybrid retrieval | `src/retrieval/vector_store.py`, `hybrid_retriever.py`, `index_manifest.py` and `scripts/index_chunks.py` | Separate runtime/index path with Qdrant filters, BM25, reciprocal rank fusion and optional cross-encoder. It has local fixture coverage. This G0 real-corpus comparison exercises the frozen backend. Live Qdrant parity remains unmeasured. |
| SEC and filing ingestion | `src/ingestion/sec_client.py`, `company_facts.py`, `section_extractor.py`, `table_discovery.py` and `pdf_ingestion.py` | SEC submissions and EDGAR filing HTML use a contact-bearing session and request throttling. Company Facts resolves mapped concepts and records CIK, accession, form, filing date, period, units, URL and revision provenance. Beautiful Soup/lxml handles HTML. pypdf is the PDF default. Docling is optional. Native iXBRL contexts, dimensions and extension-taxonomy facts remain gaps. [SEC data APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces). |
| Shared Evidence Ledger | `src/ledger/models.py` and `evidence_ledger.py` | Implemented per request. Links source records, derived facts and calculations to claims and verification. Stage traces carry hashed IDs and usage. |
| Candidate observation and screening | `src/policy/evidence_features.py`, `candidate_gate.py`, `decision_backend.py` and `evidence_policy.py` | Runtime `EvidenceAnalyst` screens normalized candidates before final sufficiency. The default backend is deterministic policy 1.1.0. ACCEPT and WEAK stay eligible for further evidence checks. REJECT removes the candidate when every slot rejects it. `CandidateFeatureObserver` exists as a protocol. The runtime gate builds its own typed features. Jev has no runtime adapter or calls. |
| Sufficiency and release | `src/decision/policy.py`, `src/generation/grounded_writer.py`, `src/verification/atomic_claim_verifier.py`, `numerical_verifier.py` and `response_policy.py` | Deterministic sufficiency exposes ANSWER, RETRIEVE_MORE and ABSTAIN. The final graph analyst evaluates with the remaining retrieval budget set to zero after the source stages. The grounded writer uses approved facts and Decimal calculations. Atomic claims and citations are checked before release with at most one correction. VERIFIED, PARTIAL and ABSTAIN remain supported. REJECTED and UNSUPPORTED are existing execution outcomes that withhold substantive answers. Optional Groq drafting remains budgeted and subject to the same release checks. |
| Evaluation and CI | `src/evaluation/`, `scripts/run_*evaluation.py`, `scripts/run_independent_final.py`, `tests/` and `.github/workflows/backend.yml` | Existing retrieval, paired source/risk, verification and provider-fixture evaluations reproduced below. The independent protocol exists and was outside this replay. The prior workflow succeeded on the baseline SHA. The G0 workflow commands passed locally in Linux WSL. [Baseline GitHub Actions run](https://github.com/NamTV2712/filingscope/actions/runs/43342638173). |

## Dependency and security audit

Audited the installed Windows environments on 2026-11-13 with pip-audit
2.10.1 against PyPI and OSV. The baseline had 92 installed distributions.
The candidate dev environment had 91. PyPI returned **24 → 9** raw
records, and OSV returned **26 → 11**. Both services identify **14 → 6**
distinct package/advisory pairs after deduplicating CVE aliases and using
the GHSA ID for the record without a CVE. A scan reports affected
versions. Reachability depends on the paths and inputs below.

| Package | Baseline → locked CPU candidate | Verification and scope |
| --- | --- | --- |
| Requests | 2.31.0 → 2.33.0 | Three verified affected ranges. Fixes cover TLS state reuse, crafted-URL netrc credential disclosure and insecure temp extraction. SEC and acquisition use Requests, with TLS verification enabled in the SEC client. [Requests advisories](https://github.com/psf/requests/security/advisories). |
| lxml | 5.3.0 → 6.1.1 | One verified Python package advisory for XML entity resolution, fixed from 6.1.0. FilingScope currently uses the HTML parser through Beautiful Soup. The Windows wheel changed from libxml2 2.11.7 and libxslt 1.1.39 to 2.11.9 and 1.1.45. A Python package scan has limited coverage of bundled native libraries. [XML entity advisory](https://github.com/advisories/GHSA-vfmq-68hx-4jfw), [lxml 6.1.1](https://github.com/lxml/lxml/releases/tag/lxml-6.1.1). |
| python-dotenv | 1.0.1 → 1.2.2 | One verified advisory for a write helper's symlink handling. Runtime settings read dotenv through pydantic-settings. [Advisory](https://github.com/advisories/GHSA-mf9w-mj56-hr94). |
| setuptools | 78.1.0 → 84.2.1 | PyTorch pulls setuptools into the runtime graph. Verified affected ranges cover legacy package download, a macOS source-distribution exclusion bypass and Windows legacy wheel installation. The resolver floor is 84.1.0. [Download](https://github.com/advisories/GHSA-5rjg-fvgr-3xxf), [macOS](https://github.com/advisories/GHSA-h35f-9h28-mq5c), [Windows](https://github.com/advisories/GHSA-xmj3-9gf7-h52w). |
| NumPy | 2.5.4 → 2.5.4 | Both services returned zero NumPy records for the installed version. The lock replaces the open-ended NumPy range for CPU reproduction. |
| Transformers | 4.57.6 → 4.57.6 | Six verified affected ranges remain. The Nomic weights revision is pinned. Its configuration references a separate remote-code repository and the loader leaves that code revision implicit. The manifest records the exact cached code revision and file hashes observed in G0. `Embedder` enables `trust_remote_code` and accepts a model identifier and revision. Arbitrary model configuration and cache contents remain outside the measured path. |
| Other transitives | Resolved in `uv.lock` | Both scans returned zero records for the other installed packages, including urllib3, certifi, pydantic-core, huggingface-hub, tokenizers and Torch. `uv pip check` passed on Windows and Linux. The fresh resolution also changed filelock, langchain-core, MarkupSafe, regex and Soup Sieve and selected Linux-only hub transport dependencies. Exact versions are recorded in the lock and run manifests. |

The remaining Transformers entries include X-CLIP checkpoint loading
(`CVE-2025-14929`), Trainer RNG restoration (`CVE-2026-1839`),
model-selected attention kernels (`CVE-2026-4372`), LightGlue
initialization (`CVE-2026-5241`), chat-template writes in
`save_pretrained` (`CVE-2026-9856`) and custom generation code
download before consent (`CVE-2026-80047`). G0 ran pinned text
embedding inference. It did not test these vulnerable paths. [X-CLIP](https://www.zerodayinitiative.com/advisories/ZDI-25-1144/),
[Trainer](https://github.com/advisories/GHSA-69w3-r845-3855),
[attention kernels](https://github.com/advisories/GHSA-29pf-2h5f-8g72),
[LightGlue](https://github.com/advisories/GHSA-fgcw-684q-jj6r),
[chat templates](https://github.com/advisories/GHSA-xrqw-3rrv-vx5w),
[custom generation](https://github.com/advisories/GHSA-x9r9-c232-4q39).

## Results on identical inputs

The [frozen manifest](G0_BASELINE_MANIFEST.json) binds Git, package
versions, model and corpus identities, case inputs and local artifacts.
Historical FinanceBench and Q cohorts contain development-exposed
material. The three raw-HTML tests could not run on this machine.
The corpus-free runs also skip the local FinanceBench sample test.
The writer's API smoke gate reads the archived loopback result and
replays the fixed drafts with a mock transport.

| Check | Baseline | G0 candidate |
| --- | ---: | ---: |
| Windows offline suite with the local corpus | 403 passed, 3 skipped | 403 passed, 3 skipped |
| Corpus-free suite | 402 passed, 4 skipped (Windows) | 402 passed, 4 skipped (Linux WSL) |
| P4 disposition / labeled claim status | 15/15 / 14/14 | 15/15 / 14/14 |
| Six fixed decision gates | 181/181 correct across gates | 181/181 |
| Q2 statement cells / Company Facts / retrospective PDF cells | 57/57 / 9/9 / 19/22 | 57/57 / 9/9 / 19/22 |
| Q4 validation grounded exact / releases / incorrect releases | 4/4 / 4/10 / 0/4 | 4/4 / 4/10 / 0/4 |
| M12 Dense Recall@10 / MRR@10 / nDCG@5, 24 cases | 56.25% / 0.3529 / 0.3757 | 56.25% / 0.3529 / 0.3757 |
| M13 routed grounded exact / releases / incorrect releases | 21/21 / 21/24 / 0/21 | 21/21 / 21/24 / 0/21 |
| Natural statement retrieval grounded exact / releases / incorrect releases | 30/30 / 30/33 / 0/30 | 30/30 / 30/33 / 0/30 |
| Q3 direct cohort routed / Q7 complex routed / Q7 narrative routed | 14/14 / 12/12 / 2/2 | 14/14 / 12/12 / 2/2 |
| Persistent outage healthy-source retention, adaptive / routed | 5/10 / 10/10 | 5/10 / 10/10 |
| Single-timeout recovery, adaptive / routed | 10/10 / 10/10 | 10/10 / 10/10 |
| Q6 writer safety gates | 9/9 | 9/9 |

Grounded exact in the real-case rows uses the existing answerable-case
denominator. Release coverage uses all cases. Zero errors in the four
Q4 validation releases has a two-sided Wilson 95% upper bound of
48.99%. The baseline and candidate produced identical stable fields
across all seven paired reports after excluding timing, timestamps and
resource fields. The 3/22 retrospective PDF misses and 2/6 mock unified
writer misses persist. The mock writer released four supported answers.
Ruff checks syntax and undefined-name-class errors across backend Python.
Mypy checks three policy and verification contract modules. A broader
exploratory check found nine errors in ledger constructor kwargs, which
remain outside the enforced scope.

| Resource on Windows i7-14650HX CPU, six threads | Baseline | Candidate |
| --- | ---: | ---: |
| M13 routed warm p50 / p95 | 14.12 / 172.45 ms | 17.92 / 196.37 ms |
| 33-case natural statement warm p50 / p95 | 18.77 / 143.63 ms | 25.12 / 173.04 ms |
| Architecture replay peak working set | 2,010,804,224 B | 2,020,175,872 B |
| Retrieval replay peak working set | 2,018,418,688 B | 2,013,372,416 B |
| Natural statement tool / embedding calls | 38 / 14 | 38 / 14 |
| Natural statement mean evidence tokens | 474.06 | 474.06 |
| Default real-replay generation calls / tokens / provider cost | 0 / 0 / USD 0 | 0 / 0 / USD 0 |
| Unified mock calls / prompt tokens / fixture completion tokens | 6 / 2,016 / 240 | 6 / 2,016 / 240 |

The candidate was slower in the observed warm samples. These were
single passes with background activity. They do not isolate the source
of the difference or establish a latency regression threshold. Natural
statement embedding token totals were unavailable. The fixed M12 Dense
run recorded 689 embedding input tokens on both sides. No hosted calls
were made. The measured costs cover provider spend.

## Reproduce

Run from the Git checkout root. Install uv 0.11.28 and use Python 3.12
on x86-64 Windows or Linux. `uv sync --locked` installs the exact CPU
dependency set. To keep an existing environment, set
`UV_PROJECT_ENVIRONMENT` to a separate path before syncing. The package
and tokenizer priming steps use the network. The offline runner blocks
outbound Python sockets while allowing loopback fixtures.

**Windows PowerShell**

```powershell
uv sync --locked --python 3.12
uv pip check
$env:TIKTOKEN_CACHE_DIR = Join-Path (Get-Location) '.local/tokenizer'
uv run --offline --locked python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OPENBLAS_NUM_THREADS = '6'
$env:PYTHONUTF8 = '1'
uv run --offline --locked python -m scripts.check_tracked_secrets
uv run --offline --locked python -m compileall -q configs scripts src tests
uv run --offline --locked ruff check configs scripts src tests
uv run --offline --locked mypy
uv run --offline --locked python -m scripts.run_offline_checks
```

**Linux**

```bash
uv sync --locked --python 3.12
uv pip check
export TIKTOKEN_CACHE_DIR="$PWD/.local/tokenizer"
uv run --offline --locked python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OPENBLAS_NUM_THREADS=6 PYTHONUTF8=1
uv run --offline --locked python -m scripts.check_tracked_secrets
uv run --offline --locked python -m compileall -q configs scripts src tests
uv run --offline --locked ruff check configs scripts src tests
uv run --offline --locked mypy
uv run --offline --locked python -m scripts.run_offline_checks
```

The uv `--offline` flag governs dependency resolution. The explicit
tokenizer command primes the checksum-verified vocabulary before the
application socket guard is installed. The manual CPU/CUDA path uses
a separate venv, the desired PyTorch wheel followed by
`python -m pip install -r requirements.txt`, and direct invocation via
that environment's `python`. G0 validated the locked CPU profile.

**Filing and fixture replays on either shell**

Obtain the authorized frozen P1 corpus, page cache, Nomic cache,
SEC snapshots and the historical scoring inputs listed in the manifest.
Use the acquisition guidance if artifacts are missing and verify their
hashes. Match both the Nomic weights and the external Nomic BERT code
cache. A newly acquired snapshot can differ from the frozen one.
The offline writer replay also needs the archived P5 receipt. [Artifact
setup](POST_M15_REPRODUCIBILITY.md#prepare-local-artifacts).

```text
uv run --offline --locked python -m scripts.run_specialist_architectures --faults --output .local/g0/replay-architectures.json --manifest .local/g0/replay-architectures-manifest.json
uv run --offline --locked python -m scripts.run_retrieval_utility --variants dense natural_dense natural_runtime --safety --output .local/g0/replay-retrieval.json
uv run --offline --locked python -m scripts.run_grounded_writer_evaluation --candidate .local/g0/replay-retrieval.json --output .local/g0/replay-writer.json --manifest .local/g0/replay-writer-manifest.json
uv run --offline --locked python -m scripts.run_financial_normalization_evaluation --output .local/g0/replay-normalization.json --manifest .local/g0/replay-normalization-manifest.json
uv run --offline --locked python -m scripts.run_evidence_policy_validation --statement-pages data/financebench/cache/extracted_pages_d5c2a1369d9997a3055a.jsonl --output .local/g0/replay-policy.json
uv run --offline --locked python -m scripts.run_verification_evaluation --output .local/g0/replay-verification.json
uv run --offline --locked python -m scripts.run_completion_evaluation --output .local/g0/replay-decisions.json
```

For the pre-G0 side, use the pinned Git SHA and Windows distributions
listed in the manifest to recreate a separate Python 3.12.7 environment.
Install `torch==2.15.0+cpu` from the official CPU index and
`psutil==7.2.2` for memory measurement. Run the same module commands
with that environment's Python and separate output filenames. Match
case IDs, release decisions, grounded exactness and cited sources and
compare ranking metrics and fault outcomes. Timing, resource fields,
timestamps and full JSON hashes vary on reruns.

**Recheck advisory feeds**

Use the matching site-packages directory for your OS. Retain JSON
receipts with aliases to deduplicate findings. An exit code of 1 is
expected when the service reports findings. Create the `.local/g0`
output directory if the replays have yet to create it.

```powershell
uvx --from pip-audit==2.10.1 pip-audit --path .venv/Lib/site-packages --aliases --desc off --format json --output .local/g0/recheck-pypi.json
uvx --from pip-audit==2.10.1 pip-audit --path .venv/Lib/site-packages --vulnerability-service osv --aliases --desc off --format json --output .local/g0/recheck-osv.json
```

```bash
uvx --from pip-audit==2.10.1 pip-audit --path .venv/lib/python3.12/site-packages --aliases --desc off --format json --output .local/g0/recheck-pypi.json
uvx --from pip-audit==2.10.1 pip-audit --path .venv/lib/python3.12/site-packages --vulnerability-service osv --aliases --desc off --format json --output .local/g0/recheck-osv.json
```

## Decision and prioritized gaps

- **KEEP** the CPU lock, dependency fixes and offline CI checks.
  G0 passed the defined behavior gates. The CI change was exercised
  locally against the locked Linux environment.
- **DEFER** replacing Transformers until an alternative can load a vetted
  embedding revision and reproduce retrieval, grounding and source
  decisions. The six advisories and implicit Nomic BERT code revision
  remain recorded compatibility debt.
- **G1** needs a metric applicability contract for page/fact versus
  claim-level labels and an offline observer adapter that preserves
  deterministic hard checks.
- **G2** needs native iXBRL dimensions, custom taxonomies and a later
  corpus with source and label independence checks. The archived P5
  provider results and Q cohorts remain historical.
- **Later validation** needs live Qdrant parity, hosted quality and an
  independently adjudicated evaluation cohort. The untouched reviewer
  protocol is documented separately.

The baseline was measured on `main` at the audited remote SHA, before
the G0 commit. The three pre-existing script changes are outside the
G0 commit. No final labels were inspected.
