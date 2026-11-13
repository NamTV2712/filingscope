# G6 frozen release-risk criterion

The existing freeze records success criteria in prose. Bind numeric
coverage and risk thresholds to the reviewer freeze and evaluate them
against the strict post-prediction adjudications. Preserve legacy
freezes and locator scores. The risk result must distinguish a known
breach from insufficient evidence. Require the upper 95% Wilson bound
under worst-case missing labels to meet the frozen maximum before
reporting that the release criterion is met. Use fixtures for a small
zero-error sample, a known breach, low coverage, missing judgments,
and a sufficiently large zero-error sample. Leave reviewer-held inputs
unopened during development.

## Result and interpretation

`freeze.json` accepts optional `release_risk_criteria` with
`minimum_coverage` and `maximum_incorrect_release`. The proposed
handoff values are 0.50 and 0.05. The reviewer freezes the values
before prediction. Scoring attaches the criterion result to each
adjudicated arm. The legacy locator and semantic scores are retained.
The result is `DOES_NOT_MEET` if measured coverage falls below the
threshold or known errors already exceed the risk limit over all
releases. It is `MEETS_DESCRIPTIVE_BOUND` when coverage and the
worst-case Wilson upper bound meet their thresholds. Remaining
cases are `INCONCLUSIVE`. Separate source-identity controls and
issuer-grouped accuracy results still apply.

| Test condition | Result |
| --- | --- |
| 21/24 released, zero observed errors | `INCONCLUSIVE` |
| 80/100 released, zero errors | `MEETS_DESCRIPTIVE_BOUND` |
| 80/100 released, zero known errors, one unjudged release | `INCONCLUSIVE` |
| 80/100 released, five known errors | `DOES_NOT_MEET` |
| 80/161 released, zero errors | `DOES_NOT_MEET` |
| No releases | `DOES_NOT_MEET` at the proposed 50% coverage |

The historical report reproduced the previous bytes and both M13
arms retained 0/21 incorrect releases with a 15.46% Wilson upper
bound. Its status remains `PROVISIONAL_NOT_INDEPENDENT`. The strict
runner used synthetic labels for validation. Independent predictions,
labels, accuracy and latency are still pending. Provider calls,
billed tokens and API cost were zero.

## Verification and handoff

Focused tests passed 26/26. Windows passed 518 offline tests with
three corpus skips. WSL passed 517 with four. Ruff, focused mypy,
syntax and both claim fixtures passed. Baseline commit `c810b75`.
**KEEP** the frozen criterion and **DEFER** its application to real
independent predictions until an eligible reviewer bundle arrives.

```text
python -m scripts.prepare_g6_readiness --historical-report .local/g3/dimensioned-historical.json --output .local/g6/release-risk-handoff
python -m pytest -q tests/test_independent_final.py tests/test_g6_readiness.py tests/test_primary_metrics.py
```

The new [label-free reviewer handoff](../.local/g6/release-risk-handoff/reviewer-handoff.json)
has SHA-256 `85cdf578ef58a65eac1b1418cab524d518c552a660f995d6aaa267bf92afa43f`.
The [historical report](../.local/g6/release-risk-handoff/provisional-report.json)
has SHA-256 `32f1145b95891a8dacf4c5aa55c24f58b944e77ba89bf76e9832f43f579f0868`.
