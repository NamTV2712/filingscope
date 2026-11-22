# Offline filing demo reproduction

## Prepare the environment

Use Python 3.12 on Windows x86-64 or Linux x86-64 and uv 0.11.28 or later.
Run from the repository root. Preparation downloads packages and model files.

```powershell
uv sync --locked --python 3.12 --extra ixbrl
$env:TIKTOKEN_CACHE_DIR = Join-Path (Get-Location) '.local/tokenizer'
uv run --locked --extra ixbrl python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
uv run --locked --extra ixbrl python -c "from src.retrieval.embedder import Embedder; Embedder(device='cpu')"
```

Keep the model revision in `configs/financebench.py` and the dependency lock.
For SEC acquisition set `SEC_USER_AGENT` to a descriptive application name and
a contact email in the ignored `.env`. Offline replay needs no provider key.
Model caches, PDF files, vectors and SEC snapshots stay in ignored directories.

## Restore evidence and run

The historical Apple workspace uses the P1 corpus, vectors and page cache plus
M13 SEC snapshots. Follow the acquisition and indexing commands in README and
`docs/ABLATION_STUDY.md`. The default locations are in `configs/financebench.py`
and `configs/sec_snapshots.py`. The public replay uses the pinned FinRank JSONL
and complete Devon/EOG filing PDFs described in `docs/G6_FINRANK_PUBLIC_REVIEW.md`.
The JSONL license is CC BY-NC 4.0. Record its published SHA-256 before replay.

Restore the frozen Devon/EOG bundle under `data/independent-final/finrank-2025`
and the pinned `FinRank.jsonl` under `data/independent-final/public-sources`.
Save the original PDFs and inventory when moving to another checkout. The
EOG PDF can be restored from its [issuer download](https://filecache.investorroom.com/mr5ir_eogresources2/383/download/2024.12.31%2010-K.pdf).
Use the preserved Devon PDF for the exact historical page mapping. The
[SEC Devon filing](https://www.sec.gov/Archives/edgar/data/1090012/000095017025022844/dvn-20241231.htm)
provides the same disclosures in HTML. The two PDF digests are in the
[source inventory](DEMO_FINRANK_INVENTORY.json). To rebuild the index, copy
the inventory to `filing-inventory.json` in a fresh bundle and place the
matching PDFs in its `filings` directory, then run the builder below. Reuse
the archived corpus and index for a byte-matched historical replay.

For Ford/Chevron, follow [the frozen cohort setup](D2_TRANSFER_COHORT.md).
That builder acquires and checks both PDFs, writes the locked questions and
labels, and builds the local index. The scorer can ingest hash-bound source
reviews once predictions have been recorded.

For a new local PDF bundle, place `filing-inventory.json` and the hash-matched
`filings/<document_id>.pdf` files in a fresh directory. Inventory entries extend
the `Filing` schema with `company`, `ticker` and `fiscal_year`. The builder reads
no answer labels and creates the index, pages and corpus manifest atomically
within its staging directory. Preserve the source inventory and source URLs.

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
uv run --offline --locked --extra ixbrl python -m scripts.run_offline_checks
uv run --offline --locked --extra ixbrl python -m scripts.run_local_research
uv run --offline --locked --extra ixbrl python -m scripts.run_local_research --bundle data/independent-final/finrank-2025
# For a fresh bundle with an existing inventory and PDFs
uv run --offline --locked --extra ixbrl python -m scripts.prepare_independent_corpus --bundle data/my-bundle --cutoff 2025-12-31 --threads 6
```

FinRank prediction and scoring commands are in `docs/G6_FINRANK_PUBLIC_REVIEW.md`.
Use fresh output filenames and pass the printed prediction hash to scoring.
The runner's context includes the inventory's company, ticker, form and fiscal
year. Its prediction phase reads questions and source documents. Scoring reads
the public answers. The independent G6 runner keeps its reviewer freeze,
clean-commit and label-release checks.

## Browser check

Open `http://127.0.0.1:8765` with the Devon/EOG bundle. Submit these questions
with Automatic mode at desktop and mobile widths.

| Question | Expected result |
| --- | --- |
| What were Devon Energy's FY2024 oil sales? | USD 9,368,000,000, oil sales row in the oil/gas/NGL group |
| What was Devon Energy's FY2024 marketing and midstream revenue as a percentage of revenue from contracts with customers? | 29.79%, with 4,743 million and 15,919 million USD linked in Calculations |
| What share of sales revenue did Devon Energy's largest customer account for in FY2024? | At most 10%, with the upper bound and its sales basis shown in Sources |
| What were Devon Energy's oil sales in FY2030? | Withheld with an evidence gap for FY2030 |

Open the cited PDF from Sources for each released answer. Chromium should
show physical page 56. Check the actual FY2024 column and customer note on
that page. These flows work with outside network access disabled after the
local model and bundle have been prepared.

## D0 baseline

On Windows with the locked Arelle environment, 594 offline tests passed and
three tests skipped because original AAPL/MSFT/local companion HTML was absent.
Ruff, configured mypy and the offline dependency lock check passed. The replay
retained 130 IDs in each arm, zero released answers, 107 unsupported routes and
23 abstentions. Complete mapped pages were found for 6/31 Adaptive and 5/31
routed cases. The Apple HTTP smoke returned USD 391,035,000,000 for FY2024 with
a citation and withheld FY2030. Raw D0 outputs are under
`data/independent-final/finrank-2025/d0-*`.
