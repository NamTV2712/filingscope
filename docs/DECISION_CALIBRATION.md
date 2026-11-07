# Decision benchmark and calibration

## Status

P2 and P4 have deterministic synthetic contract evaluations. FilingScope has
no independently labeled candidate/evidence decision benchmark and no
probabilistic decision backend. Existing 100% synthetic results are not
calibration results.

## Separate decision tasks

Label and score these decisions independently from final answer accuracy:

- `ShouldRetrieve?`
- `CandidateAccept?`
- `EvidenceSufficient?`
- `ShouldRetrieveMore?`
- `ClaimSupported?`
- `ShouldAbstain?`

Report accuracy, precision, recall, false-accept rate, false-reject rate,
confusion matrices, and reason-code agreement. Group errors by wrong company,
period, metric, source authority, table/provenance loss, and contradictions.

## Calibration protocol

The deterministic backend is the reference. If a backend emits probabilities,
also report Brier score, expected calibration error and a reliability curve,
with binning policy and sample counts. Split by company/document to limit
leakage. Select any thresholds on development; freeze validation/held-out.
Include latency, model/provider, token use, calls, and modeled cost. Reject a
backend that reduces false rejects only by increasing critical false accepts.

Optional experiments may include cross-encoder features, a structured LLM
observation, or Jev/TypeSafe after license and API review. None may be the final
answer authority or a required FilingScope dependency without a measured win.
