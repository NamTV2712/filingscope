# P4 Claim Verification Evaluation

## Scope

The P4 verifier is a deterministic control layer over answer text and the
source-ordered evidence chunks supplied by its caller. It validates canonical
`[Source N]` citations, maps each answer clause to supported entity and metric
contracts, compares numeric values and periods against cited chunks, and
recomputes declared growth percentages and period differences with `Decimal`.
Topical claims receive a lexical-anchor check against cited text. The verifier
does not call a model or inspect uncited evidence.

Run the fixed evaluation with:

```powershell
python -m scripts.run_verification_evaluation
```

## Results

| Measure | Result |
|---|---:|
| Hand-labeled synthetic cases | 15 |
| Disposition agreement | 15 / 15 (100%) |
| Claim-status agreement | 14 / 14 labeled claims (100%) |
| Evaluation errors | 0 |

The disposition confusion matrix was diagonal: 4 `VERIFIED`, 1 `PARTIAL`, 5
`REJECTED`, and 5 `ABSTAIN` cases were all assigned their expected outcome.
The fallback-answer case has no claim status by design; the other 14 cases
cover `SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED`, and
`UNVERIFIABLE` outcomes.

Among the 14 labeled claims, the report contains 4 supported, 1 partially
supported, 2 unsupported, 3 contradicted, and 4 unverifiable claims. The
unsupported cases cited evidence with the wrong metric or period; malformed,
missing, out-of-range, or conflicting evidence citations resulted in
unverifiable claims and abstention.

The fixtures cover:

- A cited value with matching company, metric, period, currency, and scale.
- A contradictory value and evidence that cites the wrong metric or period.
- Missing, malformed legacy, and out-of-range source citations.
- Correct and incorrect percentage-growth calculations from two cited periods.
- Correct and incorrect period-to-period differences.
- Lexically supported and partially supported topical claims.
- Conflicting cited values and a fallback answer that abstains.

## Interpretation and limits

These cases confirm fixed behavior for controlled evidence bundles. They are
not a FinanceBench answer benchmark, do not estimate real-world accuracy, and
do not measure the answer generation system. P5 adds the end-to-end benchmark
and ablations.

The caller must provide evidence in the same deduplicated order used to render
`[Source 1]`, `[Source 2]`, and subsequent source labels. Claim extraction
supports the registered entity and metric vocabulary plus explicit periods and
numeric values. Unsupported or ambiguous mapping fails closed. Topical checks
compare lexical anchors, so valid paraphrases can be marked partial or
unsupported. Conflicting values among the cited sources are reported as
unverifiable rather than choosing one source. These properties favor traceable
evidence and conservative behavior over broad language understanding.

Generic numerical operations accept addition, signed subtraction, absolute
difference, and percentage growth, with unit normalization for unit,
thousand, million, and billion scales. The claim layer currently recognizes
period growth percentages and period differences from answer phrasing; other
operations remain available through `NumericalOperationVerifier` when a
caller supplies an explicit operation request.
