# Q4 — Evidence policy and selective answering

## Finding and policy change

All seven M13 false abstentions after Q3 had a usable financial statement or
SEC fact. Six were blocked by prose or table fragments whose numbers were
attached to a metric or a filing year without enough local context. The
seventh was Amcor's FY2023 revenue. The consolidated statement showed
USD 14,694 million on page index 49. Page index 104 showed USD 377 million
under the Deed of Cross Guarantee, which covers a subgroup of entities.
The latter had entered the set as a second consolidated value.

- Parse canonical financial statement rows from the retrieved physical page.
  When a statement heading is scoped to the guarantor group, record the
  scope ambiguity and exclude its cells from registrant-level observations.
- On an inspected filing page outside a recognized statement, require a
  directly asserted metric, one explicit period and one amount with an
  explicit currency or percent unit. Filing publication year and adjacent
  amounts no longer supply missing parts of this observation. This covers
  common fragments such as components, deltas, credit availability,
  unconsolidated investments and quarterly values beside annual figures.
- Keep candidate `ACCEPT`, `WEAK`, `REJECT` independent from the evidence-set
  result. Record entity, metric, period, unit, provenance, authority and
  revision checks with candidate decisions. Findings distinguish
  `FULL_SUPPORT`, `PARTIAL_SUPPORT`, `IRRELEVANT`, `MISSING` and `CONTRADICTORY`.
  Set results expose `COMPLETE`, `INCOMPLETE`, `CONTRADICTORY` or `UNSUPPORTED`,
  including missing slots, conflicting slots and operation gaps.
- Comparable contradictory observations still block release. An explicit
  original or restated claim must cite the corresponding SEC revision.
  Wrong issuer, period and requested currency remain hard eligibility checks.
  Score thresholds were kept at their existing settings.

The evaluation separates local claim support from evidence-set sufficiency,
as in the published framing of [Sufficient Context](https://research.google/pubs/sufficient-context-a-new-lens-on-retrieval-augmented-generation-systems/)
and [SURE-RAG](https://arxiv.org/abs/2605.03534).

## Fixed real-filing evaluation

Development uses three issuer groups. Validation uses four other issuer
groups and ten cases. Seven development and validation lookup bundles each
contain a consolidated statement and a distractor. The six validation
controls cover wrong issuer, annual versus quarter, USD versus EUR,
unavailable restatement, missing calculation operand and forecast intent.
The source pages and their support judgments are pinned in
`configs/evidence_policy_validation.py`. The development bundle for Amcor is
also in M13. The fixed-candidate labels were checked against the filings
with AI assistance before changing the policy. They await a second reviewer
and are separate from the final independent cohort.

The benchmark replays the same chunk IDs through the normal specialist
graph with a fixed retriever and no SEC or model network access. It probes
the claim verifier with a labeled draft and source independently of the
candidate gate. `CandidateAccept` counts a candidate usable for at least
one labeled slot after screening, including usable `WEAK` candidates.
The artifact keeps the ordinal candidate dispositions. `ShouldRetrieveMore`
tests the decision with one remaining attempt over the observed evidence.
The threshold declared before the code change allows zero new unsupported
releases in the observed samples.

| Validation metric | Q3 policy | Q4 policy |
| --- | ---: | ---: |
| Answer coverage | 0/10 | 4/10 (95% Wilson interval 16.8–68.7%) |
| Grounded exact among answerable cases | 0/4 | 4/4 (51.0–100%) |
| False abstention | 4/4 | 0/4 (0–49.0%) |
| False acceptance among cases to withhold | 0/6 | 0/6 (0–39.0%) |
| Unsupported release risk | undefined, 0 releases | 0/4 (0–49.0%) |
| Precision of releases | undefined, 0 releases | 4/4 (51.0–100%) |
| Tools / model calls / provider cost | 10 / 0 / USD 0 | 10 / 0 / USD 0 |
| Single-run p95 | 10.538 ms | 15.578 ms |

The four contested lookups were all recovered. All six other query classes
withheld the response, one case in each class. In development, three of
three false abstentions were recovered. The Q4 validation risk–coverage
points for all rendered, partial-or-verified and verified-only coincide at
4/10 coverage and 0/4 grounded exact errors. Withhold-all has 0/10 coverage
and undefined risk. The Q3 baseline has 0/10 coverage and undefined risk
at all four settings. The JSON publishes Wilson intervals and per-class
denominators. There is only one positive coverage point, so an AURC would
depend on interpolation and is omitted. The paired gain is 4/4 on four
issuer groups. A bootstrap that only resamples four improving groups yields
a degenerate interval and provides little information about future issuers.

| Decision | Q3 correct / judgments | Q4 correct / judgments |
| --- | ---: | ---: |
| ShouldRetrieve | 10/10 | 10/10 |
| CandidateAccept | 13/13 | 13/13 |
| EvidenceSufficient | 6/10 | 10/10 |
| ShouldRetrieveMore | 6/10 | 10/10 |
| ClaimSupported | 12/12 | 12/12 |
| ShouldRelease | 6/10 | 10/10 |
| ShouldAbstain | 6/10 | 10/10 |

The original/restated revision suite also includes synthetic controls for
an actual value change. Synthetic test outcomes are excluded from this
benchmark. The production backend remains deterministic. No probabilities,
external judge or provider were used.

## Retrospective replay and limits

Using the same dense index, SEC snapshots, extraction cache and route as Q3,
M13 moved from 14/21 to 21/21 grounded exact and retained 3/3 correct
abstentions. The seven changed cases were Amcor, MGM, Boeing, General Mills,
Nike, Apple plus Microsoft, and Corning. The paired gain was 33.3 percentage
points, with an issuer-group bootstrap interval of 19.2–53.3 points across
eight groups. Unsupported release risk was 0/14 before and 0/21 after
(95% Wilson upper bound 15.5% after). Coverage moved from 14/24 to 21/24.
Tools moved from 29 to 28, retrievals from 11 to 10, and single-run p95 from
175.102 to 171.008 ms. The Q3 direct cohort retained 9/9 grounded validation
answers and its correct abstention. M13 peaked at 2,003,963,904 bytes with
10.912 s setup. All runs used USD 0 in provider cost.

The M13 improvement measures the exposed diagnostic cohort. The validation
sample is too small for a population risk claim at 2–5%. Strict prose
binding covers explicit single-value assertions, with narrower coverage for
unstructured filing discussion. The policy benchmark uses fixed candidates
and the revision validation control tests an unavailable restatement. The
source-basis and retrieval coverage of newly acquired filings require
independent follow-up.

## Reproduction

Prepare the same frozen inputs used in Q3. In a detached worktree at
`e4674a4d02ca155ed601f6cc789c5db74d8a45e7`, copy the two evaluation files
`configs/evidence_policy_validation.py` and
`scripts/run_evidence_policy_validation.py` from the Q4 checkout. Run the
script with `--p1-run` and `--statement-pages` pointing at the pinned files
and write `q4-policy-baseline-isolated.json` in the main run directory.
Then use the Q4 checkout for the paired replays.

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OPENBLAS_NUM_THREADS = '6'
$runs = 'data/financebench/ablation_runs'
$pages = 'data/financebench/cache/extracted_pages_d5c2a1369d9997a3055a.jsonl'
uv run --offline --with psutil==7.2.2 python -m scripts.run_multi_agent_ablation --variants B6 --statement-pages $pages --output "$runs/q4-m13-verified.json"
uv run --offline --with psutil==7.2.2 python -m scripts.run_multi_agent_ablation --cohort direct_facts --variants B6 --statement-pages $pages --output "$runs/q4-direct-regression.json"
python -m scripts.run_evidence_policy_validation --statement-pages $pages --baseline "$runs/q4-policy-baseline-isolated.json" --m13-before "$runs/q3-m13-verified.json" --m13-after "$runs/q4-m13-verified.json" --output "$runs/q4-policy-verified.json" --manifest "$runs/q4-manifest.json"
```

The Q4 report SHA-256 is
`3840fd9c52d18b7f805a6b3945fa646f85e56b0091f5b541a298a3d5e0cc5d5c`.
The manifest records replay files, hashes, environment, and the pinned
corpus. Regression passed 375 tests with three existing missing-local-HTML
skips. The documented acceptance gates passed. Promote the evidence policy
and carry it into Q5 retrieval experiments.
