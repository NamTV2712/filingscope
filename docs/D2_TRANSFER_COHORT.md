# D2 internal Ford/Chevron transfer cohort

## Frozen inputs and source review

The cohort contains 24 internally authored English questions. Each company
contributes four balance lookups, four same-date percentage questions and four
unanswerable controls. The question and label files were locked before D3
runtime changes. They remain development-exposed internal evidence. The
reviewer-held G6 protocol remains applicable to a future independent cohort.

Ford's frozen source is its FY2024 Form 10-K, filed February 6, 2025,
accession `0000037996-25-000013`. The PDF was acquired from Ford's official
filing host. Its consolidated balance sheet is at physical PDF page 114,
printed page 109, with December 2023 and December 2024 columns in that order.
The December 2024 USD-million cells reviewed were total assets 285,196,
current assets 124,474, liabilities 240,338, current liabilities 106,859 and
cash 22,935. [Ford source](https://www.sec.gov/Archives/edgar/data/37996/000003799625000013/f-20241231.htm)

Chevron's frozen source is its FY2024 Form 10-K, filed February 21, 2025,
accession `0000093410-25-000009`. Direct issuer and SEC PDF downloads returned
HTTP 403 during preparation. The preserved PDF was acquired from the public
AnnualReports mirror and checked against the issuer's FY2024 statement. Its
consolidated balance sheet is physical PDF page 58, printed page 56, with
December 2024 then December 2023 columns. Reviewed USD-million cells were
total assets 256,938, current assets 40,911, liabilities 103,781, current
liabilities 38,558 and cash 6,781. The extraction repeats each line on this
page. Those repetitions have the same source identity. [Chevron source](https://www.sec.gov/Archives/edgar/data/93410/000009341025000009/cvx-20241231.htm)

Percentage questions request cash/assets, current assets/assets,
liabilities/assets and current liabilities/liabilities. Labels retain both
operand roles, raw cells, period, currency, scale, basis, accession and page
locator. Decimal division is rounded half up to two decimal places.

Controls request FY2030 balances, euro amounts without a conversion source,
segment-specific cash, and a correcting 2025 Form 10-K/A absent from the
bundle. Whole-filing review found segment assets in both reports, so segment
cash was chosen before the freeze. Both PDFs contain consolidated cash and
segment disclosures, with no segment-cash statement matching the controls.
`D2_TRANSFER_EXPOSURE.json` records these issuers, accessions and document IDs
for inclusion in future reviewer exposure crosswalks.

| Frozen input | SHA-256 |
| --- | --- |
| Ford PDF | `9b4a74ac0a3395513e239084d9b1d7f5f45e481611d9dbfefe1014f3b77c6cb8` |
| Chevron PDF | `0044b0f397d47c70ca34c572002b0f21a9a575e411ac20a2d612fe642eb56983` |
| Questions | `22b657f715a4138454235b3851e5e525545693ba38d4a3fa52314034bf39e49f` |
| Labels | `d58f7ba84b4c369ddf3c7d11c5d1337b15404717f8ea4ee769ef97823c0966f3` |
| Source inventory | `38ae07b9b8ce2cd9c4451f599142cee4624b545dd89715662c1169c62951bef5` |
| Corpus manifest | `22616e0b24c1c106b8a75c8c0316aeb108199e5b1ecfd91deb08f5994f4022f5` |
| Transfer freeze | `1ad8829b83d7858dde590e0a30e86e17c6560e46945a54f06008ac334a27950d` |

The corpus has 848 chunks and 768-dimensional Nomic vectors. It pins
`nomic-ai/nomic-embed-text-v1.5` revision
`e9b6763023c676ca8431644204f50c2b100d9aab`, uses document prefixes, six CPU
threads and unnormalized document vectors. The cutoff is December 31, 2025.
Company Facts is empty for this document-only cohort.

## Baseline and label-free execution

Prediction used the immutable D0 checkout at
`54ea2b651c8d37ad014cfed6849a614da0f4503c`. The new cohort runner was executed
with its imports rooted in that checkout, retaining D0's graph and readers.
The actual label file was moved out of the bundle for the entire prediction
and restored afterward. No runtime file was modified. The result includes
all 24 case IDs in each architecture.

| Baseline result | Adaptive | Routed |
| --- | ---: | ---: |
| Released | 0/24 | 0/24 |
| Numeric result with complete reference locators | 0/16 | 0/16 |
| Correct abstention on controls | 8/8 | 8/8 |
| Provider requests / spend | 0 / USD 0 | 0 / USD 0 |

The prediction file `data/transfer-fy2024/d2-baseline-predictions.json` has
SHA-256 `30387eb15f02e0c23eb8a4e88d38d23baa93ee5ee9e8b8a159fe38ee9028dbb1`.
The baseline score file `d2-baseline-scores.json` has SHA-256
`3e2a9fd67c923e98ad0191393952c02cbe7e21aef9671ba8c1b859f505a12177`.
The run recorded 1,750.972 ms setup and 1,775,943,680 bytes peak working set.
These are single-host measurements.

## Reproduction and strict source review

The preparation script can acquire the two pinned PDFs into a fresh bundle,
write the internally authored inputs, index them offline after the pinned
model is cached, and emit `transfer-freeze.json`. An earlier
`preindex-freeze.json` prevents changes to question/label inputs while indexing.

```powershell
python -m scripts.prepare_transfer_cohort --bundle data/transfer-replay --acquire --index
python -m scripts.run_transfer_cohort predict --bundle data/transfer-replay --freeze-sha256 <printed-freeze-hash> --output data/transfer-replay/predictions.json
python -m scripts.run_transfer_cohort score --bundle data/transfer-replay --freeze-sha256 <printed-freeze-hash> --predictions data/transfer-replay/predictions.json --predictions-sha256 <printed-prediction-hash> --output data/transfer-replay/scores.json
python -m pytest -q tests/test_transfer_cohort.py
```

The initial scorer reports numeric-result and citation-locator agreement.
The final grounded gate additionally requires post-prediction source review
of every released answer and all its atomic claims. Supply `--reviews` and
`--reviews-sha256` with a JSON object binding `freeze_sha256`,
`predictions_sha256` and `arms`. Each arm maps released case IDs to a reviewer,
`answer_sha256` (canonical JSON hash of the answer string), Boolean
`grounded_correct`, `all_atomic_claims_supported` and `checked_evidence`.
An affirmative review must match every frozen evidence cell exactly,
including each operand role, source, accession, period, unit and basis.
The result counts source-reviewed grounded answers, unreviewed releases and
known release errors separately. Review judgments remain internal human or
agent source adjudications, with the reviewer named explicitly.

Four focused tests passed for balanced operands, loading with no label file,
freeze-hash rejection, complete prediction membership, real citation markers
and answer/operand review binding. Ruff passed. An actual score command with
an all-zero prediction hash failed before opening labels and created no
score output. Every frozen question/label hash was rechecked after baseline.
