# Decision benchmark and calibration

## Status

M3 adds a separate candidate-decision benchmark. P2 and P4 remain deterministic
synthetic contract evaluations. The M3 100% synthetic policy result is not
calibration or real-corpus accuracy. The active M3 backend emits categorical
dispositions and no probabilities.

## Separate decision tasks

The broader decision benchmark should label and score these independently
from final answer accuracy:

- `ShouldRetrieve?`
- `CandidateAccept?`
- `EvidenceSufficient?`
- `ShouldRetrieveMore?`
- `ClaimSupported?`
- `ShouldAbstain?`

M3 implements `CandidateAccept?` with a 60-case fixed synthetic corpus. P2
continues to cover requirement-slot sufficiency on its existing 15 synthetic
scenarios. The remaining decision tasks are not represented by the M3 score.
Report accuracy, precision, recall, false-accept rate, false-reject rate,
confusion matrices, and reason-code agreement; group errors by wrong company,
period, metric, source authority, table/provenance loss, and contradictions.

## M3 candidate benchmark

Cases are hand-authored, evenly balanced among ACCEPT/WEAK/REJECT, and split
24/18/18 into development, validation, and held-out. Both policy and
semantic-score-only thresholds are selected using development only. The
held-out split contains 18 fixtures, not held-out companies or filings.

| Split | Policy disposition accuracy | Reason-code agreement | Policy false accept | Policy false reject | Score-only accuracy | Score-only false accept | Score-only false reject |
|---|---:|---:|---:|---:|---:|---:|---:|
| Development (24) | 100% | 100% | 0% | 0% | 66.7% | 6.25% | 87.5% |
| Validation (18) | 100% | 100% | 0% | 0% | 61.1% | 8.33% | 100% |
| Held-out (18) | 100% | 100% | 0% | 0% | 61.1% | 16.67% | 83.33% |

The score-only semantic relevance threshold was 0.98, selected on development
with a 10% false-accept limit. The policy searched nine development-only
threshold pairs, required false-accept rate no greater than 5%, and selected
semantic relevance 0.50 and retrieval confidence 0.25. The policy benchmark's
labels and categorical observations were authored together to cover the rules;
perfect agreement therefore verifies expected behavior on those fixtures and
does not estimate generalization. The comparison does show that the fixed
score-only threshold cannot represent the categorical hard constraints in
this fixture set.

Decision latency for this local 60-case run was p50 0.0023 ms and p95 0.0030
ms. It is a small in-process rule timing, not a service latency measurement.
The run used zero provider calls, tokens, and provider cost. Peak memory was
not measured. Calibration status is `not_applicable_no_probabilistic_backend`;
there is no Brier score, ECE, or reliability curve result.

See [`EVIDENCE_POLICY_EVALUATION.md`](EVIDENCE_POLICY_EVALUATION.md) for
configuration, source fingerprint, limitations, and replay command.

## Calibration protocol

If a backend emits probabilities, report Brier score, expected calibration
error, and reliability bins/curve with binning policy and sample counts. Split
by company/document to limit leakage. Select thresholds on development and
freeze validation/held-out. Include latency, model/provider, token use, calls,
and modeled cost. Reject a backend that reduces false rejects only by
increasing critical false accepts.

Optional experiments may include cross-encoder features, a structured LLM
observation, or Jev/TypeSafe after license, API, privacy, and cost review. None
may be the final answer authority or a required FilingScope dependency without
a measured win. No probabilistic backend is currently implemented.
