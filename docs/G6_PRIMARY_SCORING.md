# G6 reviewer-held primary scoring

The current independent runner scores numeric and citation locators.
G1 semantic scoring needs judgments tied to each arm's actual frozen
answer, citations and retrieval ranking. Add a post-prediction path
that consumes those judgments after the prediction hash is recorded.
Use the G1 scorer for the eight primary outcomes and retain the
historical locator results in the same report.

Preflight and prediction must succeed without access to answer labels or
semantic judgments. Scoring must reject judgments for a different freeze,
prediction, case, arm, release state or ranking. Compare results on a
synthetic reviewer fixture with an exact numeric release, a paraphrased
narrative, wrong citations, incomplete judgments and abstentions.
Report Wilson risk bounds and issuer-grouped paired accuracy with
explicit denominators. Historical tests and scoring must still pass.

## Evidence and adjudication

The independent runner records a page ranking for both arms before
candidate screening. For multi-query cases, the selected ranking is
the lexicographically first normalized query and document scope.
Matching retries prefer a nonempty result. This makes the selection
independent of parallel completion order. Page identities keep their
original chunk ranks, including repeated pages. The score describes
this specific dense retrieval call. Cases that rely on direct
statement or structured facts without a dense call have no ranking.
Fact-rank metrics require separately captured ordered facts.

The JSON schema is in the [label-free handoff](../.local/g6/primary-handoff/reviewer-handoff.json).
The reviewer supplies a row for every question in each arm and
can omit individual judgments when evidence is insufficient. Use
`Source N` as each citation ID. Check the answer, the numbered
sources and the contents of the retrieved pages and facts. Label every
atomic claim, including extraneous claims, and account for all markers
when the claim set is complete. Retrieval relevance applies to the
frozen top-ten ranks. Gold targets retain acceptable alternatives.
The runner checks both receipt hashes, applicability, citation markers
and ranking identity. A semantic review can accept a supported
paraphrase even when the locator scorer expects different wording.

Record the prediction SHA-256 before releasing the pre-prediction
gold labels. After reviewing both frozen outputs, record the
adjudication SHA-256 and run `score` with the existing arguments plus
`--adjudications` and `--adjudications-sha256`. The report adds
`primary_adjudication`, retains the legacy outcomes, and gives a
Wilson interval among judged releases and one with unjudged releases
treated as errors. The paired bootstrap compares jointly judged
answerable cases and reports the eligible count. Reviewer
independence and semantic judgment quality are external inputs.

## Verification and decision

A synthetic end-to-end score fixture distinguishes a paraphrased
narrative from a locator-score miss, rejects changed hashes, ranks and
unresolved citations, and confirms that missing judgments remain
visible in the denominator and risk bounds. A blind prediction
fixture verifies that neither arm reads the held-back labels.
The focused run passed 23 tests. Windows offline verification passed
473 tests with three local fixture skips. Linux WSL passed 472 with
four skips. Ruff and focused mypy passed. The historical architecture
replay matched stable results across the case cohorts and fault
controls. Its routed M13 result stayed at 21/21 grounded.

**KEEP** the optional adjudicated scoring path for the reviewer-held
run. **DEFER** real independent results until the reviewer has supplied
the bundle. No independent labels were opened. The refreshed
[historical provisional report](../.local/g6/primary-handoff/provisional-report.json)
has SHA-256 `5ea3aead172d5785e9329293c83e04f9e19c48e176b549c51547d575b36d371c`.
The label-free handoff has SHA-256
`270b025c817121b6bcfa89c5a28162a2b5df373a05af98aebe6a27b6073bb140`.
Baseline Git commit `b167a38`.
