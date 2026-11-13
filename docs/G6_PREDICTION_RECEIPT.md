# G6 committed prediction receipts

The independent runner checks the supplied prediction hash against the
file bytes. Add an opt-in freeze setting that also requires a Git
receipt committed before the reviewer releases labels. The receipt
must bind the freeze, the prediction bytes and the runtime commit. A
receipt commit may add only the receipt, so scoring can run at the
frozen revision or at that commit. Test the workflow in a temporary
repository with synthetic inputs and verify that rejected receipts fail
before the label file is opened. Preserve existing freezes.

## Reviewer workflow

Set `require_committed_prediction_receipt` to `true` in the reviewer
freeze before its hash is recorded. Start on the frozen Git commit in
a clean checkout. Run the existing preflight and prediction commands.
Use the SHA-256 printed by `predict` as `$predictionHash`.

```powershell
$receipt = python -m scripts.run_independent_final receipt --bundle $bundle `
  --freeze-sha256 $freezeHash --predictions $predictions --predictions-sha256 $predictionHash
if ($LASTEXITCODE -ne 0) { throw 'Receipt generation failed' }
git add -- $receipt
git commit -m 'Record frozen G6 prediction hash' -- $receipt
$receiptCommit = git rev-parse HEAD
```

The receipt contains the schema version, the runtime Git SHA and
both hashes. The reviewer records `$receiptCommit` before sharing
the sealed labels. After the release, run `score` with
`--prediction-receipt-commit $receiptCommit` and the original hashes.
Use the frozen revision or its receipt-only child for scoring. The
runner verifies the commit tree and the predictions before reading
labels, then records the receipt commit in the score report.
Git binds the receipt contents to the frozen code. The reviewer still
controls release order and independently records the commit SHA.

## Verification and decision

The synthetic end-to-end test withheld labels while generating and
committing the receipt, then rejected missing, incorrect and mixed-file
receipts. It released the fixture labels after the valid receipt and
reproduced 7/7 grounded answers. The historical provisional report
remains byte-identical. The offline suite passed 521 tests with three
fixture skips on Windows and 520 with four on WSL. Ruff, focused mypy
and both claim fixtures passed. The test used synthetic labels and
zero model-provider calls. **KEEP** the receipt protocol for
reviewer-held runs. The live independent run awaits the reviewer bundle.
Baseline commit `0e452fc`.

The [updated reviewer handoff](../.local/g6/prediction-receipt-handoff/reviewer-handoff.json)
has SHA-256 `82a294dc8519a5889da5b8e8c1263d152506778eceff317310435e11ebd1c348`.
