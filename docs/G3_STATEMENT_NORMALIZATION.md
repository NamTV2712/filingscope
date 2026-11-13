# G3 filing statement normalization

The frozen G2 pilot found retrieved reference pages with no usable
financial observations. Walmart's fiscal-year date requires an anchor,
NVIDIA prints abbreviated month names, and Apple's statements declare
monetary amounts in millions with a separate share-count scale. The
hypothesis is that bounded header parsing and the source's filing
report date can recover those observations without guessing a period
or accepting conflicting Company Facts tags.

Compare all three tracks against the scope-guard replay on the same
26 questions, labels, page content and embeddings. Bind each new
report-date field to its original SEC accession. Require a grounded
Walmart total revenue answer in a PDF-enabled arm, improved document
grounded exactness, no new incorrect releases, and no regression in
the historical architecture and retrieval evaluations. Keep the SEC
concept conflict visible in the structured-only arm. Include controls
for conflicting or missing date anchors, incompatible currency,
malformed headers and share-count units.

## Changes

The statement parser now recognizes abbreviated month names and
distinguishes an explicitly labeled share-count scale from the
monetary scale. The statement ranker and specialist use the filing
report date from accession-bearing metadata. The pilot supplies that
date from the pinned SEC corpus manifest for each PDF. The parser
rejects an explicit first-column date that conflicts with the anchor,
and the specialist withholds normalization when annual PDF metadata
and the available structured anchor disagree. The existing scope
guard, Company Facts conflict rule and release verifier still apply.

## Paired runtime results

The baseline is the [G3 scope-guard replay](G3_REPORTING_SCOPE.md).
The candidate uses identical questions, source pages, chunk text,
embeddings and Company Facts snapshots. The chunk hash changes when
the accession-bound report dates are added. All three arms run the
same source-aware graph and deterministic policy.

| Metric | PDF only, before → after | Company Facts only, before → after | Hybrid, before → after |
| --- | ---: | ---: | ---: |
| Grounded exact | 3/23 → 22/23 | 21/23 → 21/23 | 21/23 → 22/23 |
| Exact numeric answer and VERIFIED | 4/23 → 22/23 | 21/23 → 21/23 | 21/23 → 22/23 |
| Coverage | 4/26 → 22/26 | 21/26 → 21/26 | 21/26 → 22/26 |
| Releases failing grounded exact | 1/4 → 0/22 | 0/21 → 0/21 | 0/21 → 0/22 |
| False abstentions | 19/23 → 1/23 | 2/23 → 2/23 | 2/23 → 1/23 |
| Correct abstentions | 3/3 → 3/3 | 3/3 → 3/3 | 3/3 → 3/3 |
| Supported citation locators | 3/4 → 25/25 | 24/24 → 24/24 | 24/24 → 25/25 |
| Total tools | 53 → 33 | 26 → 26 | 47 → 41 |
| Mean evidence tokens | 67.65 → 404.08 | 31.46 → 31.46 | 31.46 → 109.04 |
| Warm p50 / p95 (ms) | 49.01 / 248.45 → 9.82 / 107.02 | 9.11 / 13.39 → 10.61 / 15.92 | 8.57 / 268.34 → 9.37 / 131.06 |

The PDF arms returned Walmart's total revenues of USD 680,985 million
with physical page 54. Company Facts only still withheld that answer.
PDF only recovered all five Apple quarter/YTD cases and cited the
expected income statement for Apple net income. The two PDF arms
withheld the Tesla segment value, and all three arms withheld the EUR,
future-period and restatement controls. The pilot used 1,359 cached
document vectors and local query embedding. Candidate peak working set
was 1,897,406,464 B, with zero hosted calls, billed tokens and spend.
The warm timings are single runs.

## Verification and decision

The focused suite passed 56 tests. Offline verification passed 469
tests on Windows with three local fixture skips and 468 on Linux WSL
with four skips. Ruff, focused mypy, lock and syntax checks passed.
The historical architecture and retrieval replays
matched their prior stable report fields. M13 routed stayed at 21/21
grounded exact, with 0/21 incorrect releases. The historical natural
statement replay stayed at 30/30 grounded exact, and Dense M12 Recall@10
stayed at 56.25%.

**KEEP** accession-bound date alignment and the validated header formats.
**DEFER** selecting between conflicting structured revenue concepts
until the evidence can establish the requested financial basis. The
results are from the same development-exposed 26 questions used for
diagnosis. Semantic citation support, narrative claim faithfulness and
independent release risk remain unmeasured.

Baseline Git commit `6b60bd0`. Run the [G2 pilot
command](G2_RUNTIME_REPLAY.md#reproduce) to rebuild and score the corpus.
The [candidate replay](../.local/g3/statement-normalization-pilot/report.json)
has SHA-256
`f295f19d24ea185a9c81ddbfb5d7167f2b13820cca3437e346d965bd28cb5f87`.
