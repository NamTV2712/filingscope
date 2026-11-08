# M3 evidence policy benchmark — fixed synthetic cases

## Status and reproduction

M3 code is committed at `3ac21fed877627bbe93a61a0978b3b12d1a0856b`.
The test suite passed with 227 passed and 3 skipped. Run the focused benchmark
from the repository root:

```powershell
.venv\Scripts\python.exe -m scripts.run_evidence_policy_evaluation `
  --output data\decision_evaluation\m3-evidence-policy-v1.json
```

The JSON result is local generated data and remains git-ignored. It records
source revision `3ac21fed877627bbe93a61a0978b3b12d1a0856b`, a clean working
tree, and SHA-256 source fingerprint
`72ee26ec770868b2a342666e47cbf7032cf6098952cfdf87c65fd04034c11942`.

## Hypothesis and comparison

- **Hypothesis:** Explicit entity, metric, period, support, provenance,
  revision, table, numeric-consistency, and contradiction rules will make
  candidate acceptance decisions more reliable on hard categorical cases
  than one semantic similarity threshold.
- **Baseline:** A score-only decision accepts candidates at or above one
  semantic relevance threshold.
- **Changed variable:** The M3 deterministic policy adds typed features and
  `ACCEPT`/`WEAK`/`REJECT` reasoned decisions. Scores can demote to `WEAK`, but
  cannot override a hard rejection.
- **Dataset:** 60 synthetic hand-labeled candidates; 20 per disposition, split
  24 development / 18 validation / 18 held-out, balanced by disposition in
  each split. These are not real filings, company-disjoint cases, or external
  annotations.
- **Configuration:** Policy v1.0.0; nine semantic/retrieval threshold pairs
  selected on development under a 5% false-accept ceiling. The score-only
  threshold is also selected on development under a 10% false-accept ceiling.
  Validation and held-out labels do not select thresholds.

## Results

| Split | Policy disposition accuracy | Policy reason-code agreement | Policy FAR / FRR | Score-only accuracy | Score-only FAR / FRR |
|---|---:|---:|---:|---:|---:|
| Development (24) | 100% | 100% | 0% / 0% | 66.7% | 6.25% / 87.5% |
| Validation (18) | 100% | 100% | 0% / 0% | 61.1% | 8.33% / 100% |
| Held-out (18) | 100% | 100% | 0% / 0% | 61.1% | 16.67% / 83.33% |

Selected policy thresholds: semantic relevance 0.50 and retrieval confidence
0.25. Selected score-only semantic threshold: 0.98. On held-out, the
score-only baseline had 2 false accepts among 12 non-ACCEPT cases and 5 false
rejects among 6 ACCEPT cases. The policy had neither error on these fixed
cases.

## Cost and resources

- Provider calls, input/output tokens, and estimated provider cost: zero.
- Decision-only latency: p50 0.0023 ms, p95 0.0030 ms across 60 in-process
  policy calls. This is a small local timing sample, not a production service
  measurement.
- Peak memory: not measured.
- Probability calibration: not applicable because the deterministic backend
  returns no acceptance probability. Brier/ECE helpers are unit-tested, but
  no probabilistic backend was evaluated.

## Interpretation and decision

**ADOPT** the deterministic typed policy as the v1 candidate-decision contract.
Its hard rules reject wrong entity/metric/period/filing, invalid provenance,
superseded sources, explicit contradictions, missing or contradicted support,
observed numeric inconsistency, and broken required table context regardless
of high similarity. Unknown and partial observations stay weak.

This is a software behavior benchmark. Features and expected labels are
hand-authored together, so the result does not establish accuracy on financial
documents or generalization to unseen companies. The score-only comparison
demonstrates a fixture-specific failure mode, not a production-quality gain.
The policy is not yet connected to P5's A0–A5 evaluation pipeline.
**EXPERIMENT** on independently annotated real candidate evidence, add
probability-producing backends only when needed, and measure false accepts
before runtime promotion. Jev remains optional; FilingScope has no Jev
dependency. M4 is next.
