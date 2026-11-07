# P2 Evidence Decision Evaluation

## Purpose

This evaluation checks whether the deterministic decision layer selects
`ANSWER`, `RETRIEVE_MORE`, or `ABSTAIN` for a fixed set of auditable evidence
conditions. It is a controlled software evaluation of phase P2, not a
FinanceBench answer-quality benchmark.

## Frozen cases and labels

The runner contains 15 synthetic scenarios with expected actions and reason
codes fixed in source. Cases cover complete quantitative and qualitative
evidence, missing entity/metric/period/value/provenance, contradictory values,
unit mismatch, exhausted retrieval budget, unsupported relative periods, and
unknown metrics. The company catalog is populated from the scenario's source
metadata, matching the runtime pattern for extending aliases from the verified
corpus.

The scenarios deliberately use small retrieved-chunk bundles. They do not call
an embedding model, an LLM provider, or the FinanceBench evaluator. Gold labels
are not passed into requirement extraction, coverage analysis, or policy code.

## Metrics

- **Action accuracy:** fraction of cases where the selected action equals the
  frozen expected action.
- **Reason accuracy:** fraction of cases where the selected reason code equals
  the frozen expected reason code.
- **Action confusion counts:** expected action by selected action.

The runner reports per-case expected and actual actions, reason codes, and
remaining evidence gaps. Accuracy is exact count divided by all 15 cases.

## Reproduction

From the project root:

```powershell
python -m scripts.run_decision_evaluation
```

Optional JSON output can be written to an ignored runtime location:

```powershell
python -m scripts.run_decision_evaluation --output data/decision-evaluation/p2.json
```

## P2 result

The implementation run produced:

| Expected action | Correct | Cases | Accuracy |
|---|---:|---:|---:|
| `ANSWER` | 2 | 2 | 100% |
| `RETRIEVE_MORE` | 9 | 9 | 100% |
| `ABSTAIN` | 4 | 4 | 100% |
| **Overall action** | **15** | **15** | **100%** |
| **Reason code** | **15** | **15** | **100%** |

These results show that the current code follows the labels of its controlled
fixtures. They do not estimate general decision accuracy, calibration, false
abstention rates, or user-facing answer quality. P5 must add independently
annotated decision cases and held-out evaluation before making those claims.

## Limitations

- Requirements are extracted by deterministic aliases and explicit-period
  rules; ambiguous natural-language questions safely abstain.
- `ANSWER` indicates structurally sufficient evidence inputs for a later
  generation stage. P2 does not generate or verify a natural-language answer.
- `RETRIEVE_MORE` is a structured recommendation. The bounded retrieval
  controller is implemented in P3.
- The synthetic set is small and intentionally covers known policy branches;
  it is not statistically representative of financial questions.
