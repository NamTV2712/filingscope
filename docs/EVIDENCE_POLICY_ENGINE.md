# Evidence Policy Engine

## Status

M3 implements a versioned candidate policy in `src/policy/`. It is an offline
decision component. The P5 A0–A5 run still uses the established
`src/decision/` sufficiency path and does not call this candidate policy yet;
the M3 benchmark measures the policy separately from answer quality.

## Decision boundary

Retrieval and feature observers provide typed observations. The deterministic
Python policy is the final authority for candidate disposition. The provider-
neutral `CandidateFeatureObserver` protocol can later host a local model,
cross-encoder, or remote structured judge, but an observer returns only
`EvidenceCandidateFeatures`; it cannot make the policy decision. The current
`DeterministicDecisionBackend` has no provider dependency and emits no
probability.

`EvidenceCandidateFeatures` schema `1.0.0` records candidate and requirement
IDs; entity, metric, period, and filing-type alignment; support; source
quality; table and numeric consistency; contradiction status; provenance;
source revision; and versioned semantic/retrieval score observations. Unknown
values remain explicit. Metric and period alignment cannot be marked not
applicable.

Policy `1.0.0` returns `ACCEPT`, `WEAK`, or `REJECT` with stable reason codes.
Wrong entity/metric/period/filing type, invalid provenance, superseded source,
missing or contradicted support, explicit contradiction, observed numeric
inconsistency, and broken required table context are hard rejections. Unknown,
compatible, partial, or secondary observations and low scores make a candidate
`WEAK`. A high score cannot override a hard rejection. Score thresholds only
demote candidates; they never promote a weak or rejected candidate.

## Modules

- `src/policy/evidence_features.py`: strict typed observation schema.
- `src/policy/evidence_policy.py`: deterministic versioned rules and reason
  codes.
- `src/policy/decision_backend.py`: observer and decision protocols plus the
  deterministic backend.
- `src/policy/calibration.py`: acceptance metrics and Brier/ECE utilities for
  future probability-producing backends.
- `src/evaluation/evidence_policy_benchmark.py` and
  `src/evaluation/evidence_policy_evaluation.py`: fixed decision cases,
  development-only threshold selection, frozen later splits, and provenance.
- `scripts/run_evidence_policy_evaluation.py`: reproducible JSON report CLI.

## M3 evaluation

The benchmark has 60 hand-authored synthetic candidate cases, balanced across
`ACCEPT`, `WEAK`, and `REJECT`, with development/validation/held-out splits of
24/18/18. It measures `CandidateAccept?` separately from answer accuracy and
reports disposition and reason-code agreement, false acceptance/rejection,
latency, provider calls, and calibration applicability. It is a deterministic
behavior check, not a representative financial corpus or a claim about real
candidate accuracy. See [`EVIDENCE_POLICY_EVALUATION.md`](EVIDENCE_POLICY_EVALUATION.md)
and [`DECISION_CALIBRATION.md`](DECISION_CALIBRATION.md).

The score-only semantic baseline is selected on development under a false-
accept constraint and frozen on validation/held-out. Policy thresholds are
also selected only on development. The deterministic backend has no
acceptance probabilities, so Brier score and ECE are not applicable; the
metric functions are tested but have no measured probability output to score.

## Limits and next steps

No real-corpus observer, cross-encoder decision backend, structured LLM judge,
or Jev/TypeSafe integration is included. M3 does not replace P2 sufficiency,
claim verification, or final response release policy. Evaluate the typed
contract against externally annotated financial evidence and connect it to a
request path only after false-accept behavior is measured on real candidates.
M13 integrates candidate policy into the specialist evidence analyst. The
gate records typed decisions per candidate and requirement, removes
candidates rejected for every slot, and passes eligible observations to P2
for final sufficiency checks. The candidate gate treats a filing's report
year as publication metadata, since comparative facts can have a different
period. [M13 controlled replay](ABLATION_STUDY.md)

M4 subsequently added a standalone runtime Corpus Map and corpus-aware
planner. M5 finite complexity routing is complete as a standalone component;
see [`COMPLEXITY_ROUTING.md`](COMPLEXITY_ROUTING.md).
