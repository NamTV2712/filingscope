# Evidence Policy Engine

## Status

The policy engine described here is a target for M3, not an implemented
component. `src/decision/` currently evaluates whether known question slots are
covered, while `src/verification/` evaluates cited answer claims. Neither yet
provides a versioned, candidate-level ACCEPT/WEAK/REJECT decision with a
calibrated false-accept benchmark.

## Design boundary

Retrieval and model-assisted classifiers may return observations. They may not
release the final answer. Deterministic Python policy combines versioned
features and hard constraints and returns a reasoned action.

Candidate observations should use enums/booleans where possible:

- entity: `EXACT | ALIAS | MISMATCH | UNKNOWN`
- metric: `EXACT | COMPATIBLE | MISMATCH | UNKNOWN`
- period: `EXACT | COMPATIBLE | MISMATCH | UNKNOWN`
- support: `FULL | PARTIAL | NONE | CONTRADICTED`
- source quality: `PRIMARY | DERIVED | SECONDARY | UNKNOWN`
- table context: `INTACT | PARTIAL | BROKEN | UNKNOWN`
- source revision: `VALID | SUPERSEDED | UNKNOWN`
- contradiction: `true | false | unknown`
- semantic relevance and retrieval confidence: typed score plus model/version

Wrong-company, incompatible-period, invalid provenance, or contradicted facts
must not be rescued by a high semantic score. The policy output is
`ACCEPT | WEAK | REJECT` with schema version, policy version, feature values,
and reason codes.

## Planned modules

- `src/policy/evidence_features.py`: typed candidate observations.
- `src/policy/evidence_policy.py`: deterministic, versioned decision rules.
- `src/policy/decision_backend.py`: provider-agnostic observation/decision
  interface and deterministic implementation.
- `src/policy/calibration.py`: metrics and calibration diagnostics for
  probabilistic backends; the deterministic baseline remains available.

These modules will be added only if M3's code audit confirms there is no
equivalent existing boundary. No LLM judge or Jev dependency is assumed.

## M3 acceptance evaluation

Create an independent labeled decision benchmark for `CandidateAccept?` and
`EvidenceSufficient?`, separate from answer correctness. Report accuracy,
precision/recall, false accept/reject, confusion matrices, latency, and token
cost. For probabilistic backends also report Brier score, expected calibration
error, and reliability curves. Select thresholds on development only and
freeze validation/held-out before comparison. Require deterministic replay and
reason-code tests.
