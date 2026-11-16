# D1 public FinRank failure attribution

## Inputs and replay

The diagnostic ran on D0 commit `54ea2b651c8d37ad014cfed6849a614da0f4503c`
with six CPU threads and offline sockets guarded. The public slice retains
all 130 Devon/EOG question IDs, including the two records sharing question
text. Both architectures use the frozen PDFs and the inventory's issuer,
form and fiscal-year context. Each replayed answer, disposition, retrieved
source set, citation order, tool count and model-call count matched the
pinned baseline. The data remains development-exposed.

| Input | SHA-256 |
| --- | --- |
| Baseline predictions | `a1e9da294d921b2f7f5fe2ad4686d1e91b4d0ab4295db1761a8f9367a323baec` |
| Corpus manifest | `0d6c53cb12bbab30d1cf11d7e4c0d6226c5cb783f8fb926834623ca8dab49ab9` |
| Pinned FinRank release | `e9295f680bd6085362486c90c170bce243be7f85ed18074d6ba21cb75141ac78` |
| Diagnostic result | `847d10e4c274af52bac0594223092db1dfacae8a7a76240412eb95e6b6fbe9f6` |

## Findings

Each arm has 107 routing rejections and 23 abstentions. Native router
rejection reasons divide into 88 unrecognized metrics, 16 insufficient
operation-period scopes and three predictive/advisory requests. The
extractor can expose several gaps simultaneously. The existing first-loss
accounting orders those observed gaps by evidence flow, so its counts
differ from the mutually exclusive native routing decisions.

| First observed loss | Adaptive | Routed |
| --- | ---: | ---: |
| Metric resolution | 101 | 101 |
| Period resolution | 5 | 5 |
| Complexity routing | 1 | 1 |
| Missing mapped reference page | 4 | 5 |
| Unresolved evidence slots after retrieval | 12 | 10 |
| Undetermined from available observations | 7 | 8 |
| Total | 130 | 130 |

For example, case `58f208c8-1a06-43b0-a62e-d4f9702f4fb1`
retrieved its mapped source pages in both arms. Routed coverage still
reported `DVN:revenue:FY2024` missing, with
`numerical_value_or_period_alignment_missing`. The verifier returned
`ABSTAIN` with `fallback_answer` and zero claims. This establishes an
unresolved slot after retrieval. A finer table-cell or numeric-parsing
cause requires an additional diagnostic observation.

The report records requirement gaps, native route reasons, retrieved and
cited sources, disposition and operation-level details for 260 arm/case
records. Routed records include actual coverage and verification
payloads. The Adaptive observer has no claim-adjudication payload, which
is explicitly recorded as unavailable. It retains its observed
disposition, missing slots and verified-claim count.

## Raw-page location intervention

All supplied reference excerpts uniquely mapped to physical PDF pages
for 31 cases. For each of those cases and both arms, an evaluation-only
retriever substituted the full unmodified mapped page text, with its
physical page metadata and recalculated token count. Document scoping,
requirements, route, evidence reader, reasoner, writer and verifier were
retained. The intervention uses the existing `Oracle.LOCATION` diagnostic
contract. It supplies no numeric labels, normalized facts or reference
answer text to the runtime.

Each arm still returned 21 `UNSUPPORTED` outcomes and ten `ABSTAIN`
outcomes on these 31 cases. The reader was invoked in ten cases per arm.
There were zero releases. Location alone therefore did not recover an
answer in this diagnostic. The other 21 cases stopped at the original
route, before a reader could consume the supplied pages. Cases outside
the 31-case mapping subset have no location-intervention result.

## Reproduction and checks

Restore the D0 source revision and prepared corpus, then run the
diagnostic script from this milestone with a fresh output path. The script
checks baseline membership and hashes and rejects source files changing
during the replay. The result stores source hashes for the tracked
runtime, scripts and configuration, plus the diagnostic itself.

```powershell
python -m scripts.run_finrank_diagnostics --bundle data/independent-final/finrank-2025 --dataset data/independent-final/public-sources/FinRank.jsonl --baseline data/independent-final/finrank-2025/local-review-cost-ticker-final-predictions.json --baseline-sha256 sha256:a1e9da294d921b2f7f5fe2ad4686d1e91b4d0ab4295db1761a8f9367a323baec --output data/independent-final/finrank-2025/d1-diagnostics-replay.json
python -m pytest -q tests/test_finrank_diagnostics.py
```

Four focused tests passed. They cover routing-versus-retrieval
attribution, mapped-page versus unresolved-slot failures, an undetermined
cause, and exact raw-text/document-scope preservation by the location
intervention. Ruff passed for both new Python files. Provider calls and
API spend were zero. Raw records stay in the ignored data directory.
