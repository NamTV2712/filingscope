# G6 frozen evaluation readiness

## Predeclared checks

Reuse the existing independent-final protocol. The real run requires
a reviewer-supplied freeze, label-free question and corpus inputs,
and a subsequent release of reviewer-held gold. A development replay
may verify the scoring and resource outputs while these inputs are
pending. Keep its provenance explicit. Compare adaptive and routed
on identical cases with issuer-grouped resampling.

Provisional thresholds for reviewer handoff are at least 50% answer
coverage, at most 5% incorrect release point estimate, zero critical
source-identity violations in adversarial controls, and a reported
95% interval on risk. If the uncertainty is too large for a 5% risk
claim, report that claim as inconclusive. Reviewer independence and
the exposed-membership crosswalk must be confirmed before the freeze.

## Handoff and verification

The workspace contains public benchmark material and provisional G2
data. An independent reviewer bundle with a verified exposure crosswalk,
later issuer-disjoint filings, frozen questions and reviewer-held
labels is unavailable. Independent prediction, prediction-hash commit,
label release and scoring are **NOT_RUN**. This milestone is
**PARTIALLY_COMPLETE / PROVISIONAL_NOT_INDEPENDENT**.

`scripts/prepare_g6_readiness.py` generates a label-free handoff
checklist with the existing protocol schemas and the proposed sampling
and risk targets. It also binds the historical architecture report
by hash. The actual corpus and freeze need the independent reviewer
inputs. The G2 auto-XBRL cohorts are development-exposed and belong in
the crosswalk. No gold file was opened. The pre-existing local changes
to the independent runner and corpus helpers were left as-is.

The [independent execution protocol](POST_M15_EVALUATION_PROTOCOL.md#reviewer-handoff-and-execution)
continues to require an exact clean Git SHA, corpus and index hashes,
fixed model revision and dependencies, offline execution, prediction
receipt before scoring, and issuer-aware membership. For the actual
freeze also record the Nomic external code revision, prompts, policy
versions, tool/token/time budgets and the scorer version. Strict G1
metrics require semantic claim, numeric and retrieval labels. The
runner accepts post-prediction reviewer judgments and retains the
original locator scores. [Primary scoring workflow](G6_PRIMARY_SCORING.md).

## Historical readiness replay

This report scores the G4 Adaptive and routed LangGraph observations
on the 24 exposed M13 cases. It is a paired evaluation of prior
runtime outputs. The scoring path uses eight connected issuer groups,
21 answerable pairs and bootstrap seed 20261112. It retains every
released error and false abstention if present. The first readiness
run used the Q7 issuer map, which lacked M13 case IDs. The final
script derives issuer membership from the existing M13 source slots.

| Measure | Adaptive | Routed LangGraph |
| --- | ---: | ---: |
| Historical grounded exact | 21/21 | 21/21 |
| Historical numeric exact | 21/21 | 21/21 |
| Coverage | 21/24 (87.5%) | 21/24 (87.5%) |
| Incorrect release | 0/21 | 0/21 |
| Descriptive Wilson 95% risk interval | 0–15.46% | 0–15.46% |
| Correct abstention / false abstention | 3/3 / 0/21 | 3/3 / 0/21 |
| Warm p50/p95 | 15.61/147.04 ms | 14.06/134.25 ms |
| Mean tool calls | 1.25 | 1.33 |
| Mean evidence tokens | 208.58 | 249.42 |

The paired grounded-exact difference was 0/21 with no changed cases.
The grouped bootstrap returned [0, 0] on these identical observations.
Both arms have the same 87.5% coverage and 0 observed errors at all
three release-eligible disposition thresholds. Withholding every
answer has an undefined risk denominator. The 5% risk claim is
**INCONCLUSIVE**. Correlated issuer observations and development
exposure limit population inference. The historical citation locator
support measure is 100% in both arms. Context Precision/Recall@10
and atomic-claim faithfulness on independent data are unavailable.
Peak architecture process memory was 2,009,079,808 B. Provider
calls, billed tokens and USD spend were zero.

The existing independent-final tests demonstrate preflight without
access to the fixture labels, prediction with both arms, tamper
detection and scoring of unsupported content. The G6 fixture checks
that zero observed errors with 21 releases remains inconclusive.
Windows offline verification passed 453 tests with 3 fixture skips.

```text
python -m scripts.prepare_g6_readiness --historical-report .local/g4/candidate-architectures.json --output .local/g6/readiness
python -m pytest -q tests/test_independent_final.py tests/test_g6_readiness.py
```

The [historical readiness result](../.local/g6/readiness/provisional-report.json)
and [label-free checklist](../.local/g6/readiness/reviewer-handoff.json)
are local artifacts. Their SHA-256 values are
`e732b4267731d2b9014f7e4372610be5aee5915e3ebd77beb5613c80db5a56af`
and `9d982a02aa0e751b5ce6b5f603ff09865a2c05be23775eb3c16efe111cecb14e`.

**KEEP** the freeze-and-predict handoff. **DEFER** independent
conclusions until a qualifying reviewer bundle arrives. G6 builds
over `85f7d82d1e108544cac5b961008b63b61d5aec59`. G7 can report the
measured results with the documented limitations.
