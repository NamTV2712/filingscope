# Implementation progress

Updated: 2026-11-14<br>
Branch: `main`<br>
Remote: `origin` (`https://github.com/NamTV2712/filingscope.git`)<br>
Deployment: none; explicitly out of scope

## Completed milestones

- M1 connects the P5 pipeline and pins the working Transformers version.
  Vertical slice `9b87e6b5b2d93350058e98d8922aea76fb802a5a`; compatibility
  and audit `3d11f7aa5a3d740e2a7fde709c5b5b4895488bbe`.
- M2 adds retrieval stage diagnostics. Source
  `c0c887df6128e3720d68fac09b2f91adb5f74948`; docs
  `6953d6483b7813628a0df0eb54997f0983681038`.
- M3 adds versioned candidate screening. Source
  `3ac21fed877627bbe93a61a0978b3b12d1a0856b`; docs
  `f5c1acce6d7acbe34f2dd21b079720008e9b3bf2`.
- M4 adds the Corpus Map and planner. Source
  `1192e63c91759c512535eadfe62b2168908b4313`; fingerprint
  `0be938d31cf3a76b5b0baa31023bd4354ce571a3`; docs
  `a7f9eed69061325886e33ceab2e4c42cfc9d5822`.
- M5 adds finite route planning. Source
  `0fffebc0d5d0a6b88532e3c3b0969a9f3246509f`; docs
  `525f3d350cf01e1dd6b44129e6105fb9e8c5e7b5`.
- M6: shared in-memory Evidence Ledger. Source `706af9a86e8090dd7dca86400f007ce395185a55`;
  docs `b26849488a38d77bd638258fd45b97364f3a8285`.
- M7: finite sequential specialist graph and narrow official SEC Company Facts
  path. Source `eb3654113823240d93d043e714647f4b69f22910`; docs
  `81fe0e013a9270b18829d06a62a4952a0ff9b0d0`. Validation: 20 focused tests passed; full
  suite 263 passed, 3 skipped; `compileall` and `git diff --check` passed.
  No live SEC or model-provider calls. Ruff was unavailable in the project
  environment (`uv run ruff` could not find the executable).
- M8 adds bounded parallel filing research. Source
  `2131e3cda186874b5bd1dc17a516454256437b99`. Docs
  `6dc25ffb962760a1c2274c0c8b41642a51dbfff7`. The full suite passed with
  269 tests and 3 skips. Simulated search p50 fell from 250.85 ms to 87.44 ms
  with six calls in each mode. [M8 validation](PARALLEL_RESEARCH.md)
- M9 resolves SEC financial facts by concept, fiscal interval, unit and
  revision. Source `aad24377da2075ccb6e1c4d55106dc480c6309e5`. Docs
  `7e9a287bb615d23d884768f542c8a31e3cb9e6bb`. Eight of
  eight published fixture slots matched. The full suite passed with 303
  tests and 3 skips. [M9 validation](FINANCIAL_FACT_ARCHITECTURE.md)
- M10 benchmarks pypdf, Docling page text and structure-aware chunks on
  five PDFs. Source `1d08a0079aaee5991c5a13e1db6fd6b4365d03ed`. pypdf
  stays the default. The full suite passed with 306 tests and 3 skips.
  Docs `4424427c3e4d82bdcb4b7bf072c2eb67d4745063`.
  [M10 validation and reproduction](DOCUMENT_INTELLIGENCE.md)
- M11 adds atomic claim support and a one-pass correction policy to the
  specialist graph. Source `16e106bf7761aa0115c0ec01cabeb06312f117a1`.
  Docs `74aaed8ddcb6e138fc6042395cadc419b898f17d`.
  The fixed replay matched 16/16 expected release decisions. The full suite
  passed with 332 tests and 3 skips. [M11 validation](ADVANCED_VERIFICATION.md)
- M12 adds a 24-case hard-negative retrieval benchmark with five categories.
  Source `b9d53ed7424d5837386a69c0355543c28a12df33`. Dense stays the baseline.
  Docs `55d23ae4a5a31066969fdd61d7385e5908647aa0`.
  The full suite passed with 335 tests and 3 skips. [M12 validation](HARD_NEGATIVE_RETRIEVAL.md)
- M13 adds candidate screening and compares solo, forced research and smart
  routing. Source `91f3ee5a7cdfb6a4091b4360354bc764cc4b9eb3`. Docs
  `2fb48a4ff140273b7c28de6036034cba7bc1eeca`. The full suite
  passed with 338 tests and 3 skips. [M13 validation](ABLATION_STUDY.md)
- M14 compares parent-page and selective expansion, annual statement
  alignment, and five reranking methods with dense retrieval. Source
  `c3d93459a63c290589cae95715844e743bf7692c`. Docs
  `d1aceadf38b9a18b40c9938a8d61116569af4e0f`. The full suite passed with
  343 tests and 3 skips. [M14 validation](ADVANCED_RETRIEVAL.md)
- M15 adds a loopback-only evidence-first workspace. Source
  `4121d0b8c2f34a7ddb409de4939d5df5b3c101da`. Docs
  `552b297268a33140ef41a6daf5156bbbfb772b9d`. The full suite passed with
  346 tests and 3 skips. [M15 validation](LOCAL_RESEARCH.md)

## M1–M15 closeout

M1–M15 are implemented, validated and pushed. Completion source
`3c55a2bc1393d327fba26a0b7e666cd791907e44` adds the six-decision replay,
ordinal risk-coverage points from M13, configurable route budgets and
provider token accounting. The final regression suite passed with 349
tests and 3 skips. [Specification audit](SPECIFICATION_AUDIT.md)

## Post-M15 checkpoint

Resume from the first phase whose acceptance gate is open. Before new work,
check `git status --short`, `git log -5 --oneline`, the corresponding phase
report and the manifest under the ignored evaluation directory.

| Phase ID | Status | Last validated commit | Completed tasks | Unfinished tasks | Test status | Benchmark status | Acceptance gate | Blocking issues | Exact next action |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | COMPLETE | `556beff7e772c58f85c6834cf1b8c12d42789bcd` on `origin/main` | Freeze baseline, trace M13, execute or document A–G, reproduce stable outcomes and isolate runtime imports | None | 355 passed, 3 skipped after isolation follow-up | Both specialist modes replayed twice on all 24 M13 cases | 38/38 failures attributed | None | Proceed to Q2. [Phase report](POST_M15_FAILURE_ANALYSIS.md) |
| Q2 | COMPLETE | `bb90e3c7a89713558bd267b5bd5e2f97473b50a7` on `origin/main` | Typed period and SEC handoff, column-aware PDF/HTML extraction and paired evaluation | None | 368 passed, 3 skipped | 57/57 newly labeled cells, 9/9 SEC slots, 19/22 retrospective PDF slots | Passed on provisional cohorts | None | Proceed to Q3. [Phase report](POST_M15_FINANCIAL_NORMALIZATION.md) |
| Q3 | COMPLETE | `e4674a4d02ca155ed601f6cc789c5db74d8a45e7` on `origin/main` | Source-aware FAST, bounded fallbacks, direct-fact and M13 paired evaluation, live API smoke | None | 371 passed, 3 skipped | Validation 9/9 exact with 45% of forced tools, M13 14/21 grounded | All four Q3 benchmark gates passed | None | Proceed to Q4. [Phase report](POST_M15_SOURCE_ROUTING.md) |
| Q4 | COMPLETE | `a1856c6052220cbe68f69408b182129a26ef36e3` on `origin/main` | Evidence support and sufficiency, bounded filing assertion parsing, revision verification and paired benchmarks | None | 375 passed, 3 skipped | Validation recovered 4/4 with 6/6 controls, M13 21/21 grounded and 3/3 correct abstentions | Zero unsupported releases on the paired validation and retrospective runs | None | Proceed to Q5. [Phase report](POST_M15_EVIDENCE_POLICY.md) |
| Q5 | COMPLETE | `72c8451b003dbb9b24cb48e77812e0f1cfb3ab0d` on `origin/main` | M12 reproduction, 28 retrieval variants, scoped statement ranking, grounded graph and loopback comparisons | None | 376 passed, 3 skipped | Natural validation 14/17 to 17/17, M13 and direct-fact safety retained | All seven recorded comparison checks passed | None | Proceed to Q6. [Phase report](POST_M15_RETRIEVAL_UTILITY.md) |
| Q6 | COMPLETE | `33073129dc71fbac2cb516e26ca1ec07adce822f` on `origin/main` | Shared approved writer and verifier inputs, prechecked Decimal calculations, provider caps, 3M numeric tokenization and mock verification | Hosted quality not run | 383 passed, 3 skipped | 30/30 grounded, M13 and direct-fact safety retained, six API controls | All nine recorded gates passed | None | Proceed to Q7. [Phase report](POST_M15_GROUNDED_WRITER.md) |
| Q7 | COMPLETE | `9ea4fd3ddd48c5c88ec09a8a9d1c488d53bdc759` on `origin/main` | Four-way replay, scope-aware assignments, verified narrative disclosures and bounded filing retry | General narrative synthesis and population-level effect unverified | 386 passed, 3 skipped | B/C/D tied 12/12 clean comparisons, 2/2 narratives and 21/21 M13. C retained healthy-source slots 10/10 vs B 5/10 under persistent injected outage. | Passed for measured source isolation. Clean grounded accuracy tied. | None | Proceed to Q8. [Phase report](POST_M15_SPECIALIST_ARCHITECTURES.md) |
| Q8 | COMPLETE | `7817975ce6b1b64112747050eefba05a25193598` on `origin/main` | Typed stage traces, nine adversarial fixtures, tracked-secret check, offline GitHub Actions, dataset hygiene and reproducibility | Independent final evaluation and hosted quality remain unmeasured | 399 passed, 3 skipped locally. 398 passed, 4 skipped and 100% fixture verification in [GitHub Actions](https://github.com/NamTV2712/filingscope/actions/runs/43339910663). | 21/21 M13, 14/14 direct, 30/30 source-checked filing questions, 12/12 complex and 2/2 narratives | Q8 engineering gates passed | Reviewer-held independent labels are unavailable | [Final report](POST_M15_FINAL_REPORT.md) and [reproduction guide](POST_M15_REPRODUCIBILITY.md). Run the independent protocol when eligible labels are available. |

## G0 engineering baseline

G0 passed on the worktree over `91367269638e55a7e7c26e2f7f78b18efd16fb33`.
The locked CPU profile and targeted dependency fixes preserve the
two-plane runtime. Windows passed 403 tests with 3 skips. Linux WSL
passed 402 with 4 corpus-related skips. Seven paired offline reports
had identical stable outcomes. The PyPI and OSV audits agreed on a
reduction from 14 distinct advisory findings to 6. The remaining
findings concern the Nomic-compatible Transformers pin.
[G0 report and replay commands](G0_BASELINE.md) ·
[Frozen manifest](G0_BASELINE_MANIFEST.json).

## G1 evaluation foundation

G1 builds on G0 commit `7881b440a4bdd1b7b7a8afa54927d66ad4e7be8c`.
The versioned scorer covers all eight primary metrics with explicit
applicability and seven offline fixture cases. The mock Jev observer
preserved deterministic decisions in 65 policy scenarios. Windows passed
437 tests with 3 skips and Linux WSL passed 436 with 4 skips. All seven
historical regression reports matched on stable outputs.
[G1 report, metric definitions and commands](G1_EVALUATION.md).
The [real-filing claim review](G1_SEC_CLAIM_REVIEW.md) applies the G1
scorer to both frozen document-only pilot runs and reports the scope
error separately from support for the original statement.

## G2 SEC data and benchmark cohorts

G2 passed the data, provenance, reproducibility, leakage and regression
checks. The benchmark labels remain development-exposed and provisional.
The original verified extraction covers 17 SEC filings and 20,723 numeric
observations. The offline manifest
reproduced byte for byte. There were 7,087 exact unique-value Company
Facts pairs and 6/6 exact PDF controls. Pilot/development/validation
contain 32/100/72 provisional lookups with disjoint issuer groups.
Historical architecture, retrieval and writer results reproduced.
A 26-question runtime pilot measured 3/23 grounded exact with PDF
only and 21/23 with either Company Facts only or hybrid. All three
arms confused Tesla segment revenue with consolidated revenue.
The separate mixed benchmark covers all eight planned categories in
32/100/72 cases. Structured lookup matched 187/187 numeric cases and
withheld 8/8 missing-unit controls. Its narrative and revision labels
are author-checked. The matched question-to-answer runtime replay
confirmed 20/187, 37/187 and 37/187 numeric answers with document-only,
Company Facts-only and hybrid. Five document and hybrid answers added
an unrequested prior fiscal year. Independent review remains open.
[Mixed cohorts](G2_SEC_MIXED_COHORTS.md) · [Mixed replay](G2_SEC_MIXED_RUNTIME.md).
[Runtime pilot](G2_RUNTIME_REPLAY.md) · [G2 report](G2_SEC_DATA.md) ·
[Frozen SEC manifest](G2_SEC_CORPUS_MANIFEST.json).
The dimensioned replay resolved 10/10 PDF-transcribed facts and
withheld 50/50 perturbed identities. It keeps the exact filing anchors.
[Dimensioned replay](G2_DIMENSIONED_REPLAY.md).
The selected 8-K replay pinned three earnings-report accessions.
All had zero numeric iXBRL observations. Six financial cells from two
linked HTML exhibits agreed with the corresponding periodic Company
Facts entries. [Current reports](G2_SEC_CURRENT_REPORTS.md).
The optional pinned SEC transform profile recovered 81 numeric
observations and preserved all 20,723 original observation payloads.
Unique exact Company Facts pairs rose to 7,088/7,088. The 204 lookup cases
and six PDF cells matched the baseline. Windows passed 594 tests with
three skips and WSL passed 593 with four.
[SEC transformation replay](G2_SEC_INLINE_TRANSFORMS.md).
The separate revision diagnostic verified 8/8 original and restated
Massimo statement cells and 12/12 bridge cells with exact anchors.
Four signed adjustments reconciled and all 16 mismatched identities
were withheld. Redfin's six tagged annual recast cells matched. Its
nine quarterly cells were verified in HTML and had no tags in the table.
[Revision and recast replay](G2_SEC_REVISIONS.md).
The [SEC narrative track](G2_SEC_NARRATIVE.md) measured six
author-checked questions. All three inventories abstained. The PDF arms
retrieved evidence for five cases including valid alternative pages.

## G3 financial understanding and scoped retrieval

Exact ISO reporting intervals eliminated five prior-year overreleases
in each text-enabled mixed arm. Confirmed numeric outcomes rose from
20 to 26 for document-only and from 37 to 45 for Company Facts-only and
hybrid. [Interval replay](G3_EXPLICIT_INTERVALS.md).
Date-bound quarter/YTD requests now recover 9/26 exact pairs in
Company Facts-only and hybrid. Confirmed numeric cases reached 54/187
in both arms with zero incorrect releases on this cohort.
[Quarter/YTD replay](G3_QUARTER_YTD.md).
Seven exact consolidated metric mappings raised Company Facts-only and
hybrid to 26/26 quarter/YTD pairs and 97/187 confirmed numeric cases.
Both structured arms confirmed all new releases and preserved 8/8
missing-unit abstentions. Document-only stayed at 26/187. The 122 PDF-pilot
outputs and historical architecture outcomes matched. Windows passed 550
tests with three skips and WSL passed 549 with four.
[Financial metric mappings](G3_FINANCIAL_METRIC_MAPPINGS.md).
Accession-bound fiscal year pairs confirmed 32/32 previously withheld
pairs with Company Facts-only and hybrid. Each arm reached 133/187
confirmed numeric outcomes. Document-only reached 28/187 with two
additional operating cash flow lookups. Windows passed 557 tests with
three fixture skips and WSL passed 556 with four.
[Fiscal year pairs](G3_FISCAL_YEAR_PAIRS.md).
Issuer-specific balance-sheet dates raised both structured arms to
16/16 multi-company and 182/187 numeric confirmations. Document-only
confirmed 3/16 multi-company and 30/187 numeric. All arms kept their
prior correct releases and withheld the eight missing-unit controls.
Windows passed 564 tests with three skips and WSL passed 563 with four.
[Balance sheet dates](G3_FILING_INSTANTS.md).
Exact concept and line-item wording resolved the remaining five
numeric questions in Company Facts-only and hybrid. Both confirmed
187/187 with zero incorrect releases and all eight missing-unit
controls withheld. Document-only stayed at 30/187. Windows passed
565 tests with three skips and WSL passed 564 with four.
[Exact concept lookups](G3_EXACT_CONCEPT_LOOKUPS.md).

The accession-scoped balance-sheet reader increased document-only
confirmations from 22/78 to 75/78 balance questions and from 30/187
to 83/187 across numeric categories. Codex checked all 90 released
balance claims and their citations. All three withheld cases involved
an issuer tag whose display row also includes other assets. The two
structured arms still match the frozen tags on 187/187 cases.
[Document balance sheets](G3_DOCUMENT_BALANCE_SHEETS.md).

G3 retains Dense and the current statement ranker. Scoped scoring
matched all 30 top-ten rankings while reducing paired rank p50
from 4.25 ms to 1.16 ms. YoY expansion now preserves YTD and
calendar-year scope. Historical graph, retrieval and writer outcomes
matched, and Windows passed 447 tests with 3 skips.
[G3 report](G3_FINANCIAL_RETRIEVAL.md).

The G3 follow-up caught the Tesla segment scope failure on the same
26 pilot questions. All three tracks now withhold the consolidated
number. The other 25 outcomes and the historical architecture replay
matched. [Reporting scope replay](G3_REPORTING_SCOPE.md).
Accession-bound report dates and statement header parsing subsequently
raised PDF-only grounded exactness from 3/23 to 22/23 and hybrid from
21/23 to 22/23 on the same pilot. The structured-only arm still
withheld Walmart's conflicting revenue tags.
[Statement normalization replay](G3_STATEMENT_NORMALIZATION.md).
The optional accession-bound Inline XBRL path recovered the remaining
Tesla segment case. Hybrid with iXBRL grounded 23/23, compared with
22/23 for hybrid. The other 25 answers and dispositions matched.
Windows passed 499 tests with 3 skips and WSL passed 498 with 4 skips.
[Dimensioned runtime replay](G3_DIMENSIONED_RUNTIME.md).
The SEC pilot ranking ablation improved frozen-locator recall from
22/26 to 25/26. A four-case author review found alternative valid
evidence on several pages. Reviewed recall was 4/5 for Dense and
5/5 for statement ranking. [Ranking report](G3_SEC_RANKING.md).

## G4 orchestration and verification

Same-request requirement reuse reduced measured extractor calls
from 4 to 2 on FAST and 3 to 2 on RESEARCH. The historical graph,
retrieval and writer replays kept their grounded, release and fault
outcomes. Windows passed 451 tests with 3 fixture skips.
[G4 report](G4_AGENT_VERIFICATION.md).
The scoped segment-list path recovered 3/6 narrative answers in both PDF
arms. All three lists and citations matched the disclosed names and pages
in author review. The frozen literal score stayed 0/6. All 104 numeric
outcomes matched the previous replay. [Segment report](G4_SEGMENT_DISCLOSURES.md).
The accession-bound HTML replay recovered all eight business disclosure
questions in both document-enabled arms. Codex source review confirmed
eight of eight claims and their numbered citations in each arm. The
remaining revision question was withheld. All 585 numeric and
missing-unit arm/case outcomes and 122 PDF-pilot outcomes matched.
[Annual business disclosures](G4_ANNUAL_BUSINESS_DISCLOSURES.md).
The amendment follow-up cites Tesla's explanatory note and recovers the
ninth mixed disclosure. Codex reviewed 9/9 claims and citations in
each document-enabled arm. Context Precision@10 was 22/88 and Gold
Evidence Recall@10 was 9/9. The remaining 609 arm/case records match,
apart from timing. [Amendment scope and review](G4_AMENDMENT_SCOPE.md).

## G5 observer and architecture comparison

G5's matched offline and live comparisons are recorded. Offline policy comparisons found zero
critical false accepts. Negative mock observations downgraded 20/60
decisions. The 26-case SEC pilot now has local Qwen 7B closed-book and
long-context comparisons alongside Dense, Adaptive and routed LangGraph.
Adaptive and routed each grounded 22/23. The local experiment is archived.
[G5 report](G5_BASELINE_EXPERIMENT.md) ·
[Matched local baseline report](G5_LOCAL_MODEL_BASELINES.md).
The Groq GPT-OSS 120B closed-book and long-context runs completed all
52 requests. Author review found 0/23 exact closed-book and 22/23
exact with context, including 20/23 with every frozen PDF locator.
[Groq benchmark](G5_GROQ_BASELINES.md).
The offline typed numeric replay reproduced the review counts on
the original model outputs. [Scorer replay](G5_GROQ_SCORER_REPLAY.md).
The Groq relevance comparison attempted 18 SEC candidate pages and
returned 16 valid judgments. It changed zero policy dispositions
and weakened zero of five hard rejections. Groq remains an evaluation
control. [Structured observer comparison](G5_GROQ_OBSERVER.md).
TypeSafe Jev 1.14 returned 18/18 valid observations on the same pages.
On the 14 shared binary predictions, Jev was correct on 10 and Groq
on nine. Neither changed a deterministic policy disposition. G5's
live comparison is measured. [Jev protocol and results](G5_JEV_LIVE_PROTOCOL.md).

## G6 independent evaluation readiness

G6 is **PARTIALLY_COMPLETE / PROVISIONAL_NOT_INDEPENDENT**. The label-free
reviewer handoff and historical risk report were generated. The routed
M13 replay had 0/21 incorrect releases and a Wilson 95% upper bound of
15.46%. The 5% risk claim is inconclusive. Independent prediction and
scoring await an eligible reviewer bundle. [G6 report](G6_EVALUATION_READINESS.md).
The G1 reviewer scoring path now binds semantic judgments to both
frozen arms and exports page rankings for adjudication.
[Primary scoring workflow](G6_PRIMARY_SCORING.md).
The reviewer freeze now accepts machine-readable coverage and
release-risk criteria. Offline fixtures exercise insufficient sample
size, missing judgments and known threshold violations. The historical
report reproduced byte for byte. [Release risk gate](G6_RELEASE_RISK_GATE.md).
The [draft G6 exposure inventory](G6_EXPOSURE_INVENTORY.md) consolidates
70 CIKs and 91 local document IDs for the reviewer to verify. Both
offline runs produced identical inventory and source receipt hashes.
The [G6 prediction receipt](G6_PREDICTION_RECEIPT.md) binds prediction
and freeze hashes to a Git commit the reviewer records before label release.
The public FinRank replay measured 0/130 coverage for both workflows
and reviewed evidence and routing failures. A targeted COST alias fix
removed seven false issuer resolutions. All 612 mixed runtime records
and the historical architecture and fault outputs matched apart from
resource fields. [FinRank review](G6_FINRANK_PUBLIC_REVIEW.md).

## G7 research report

The report binds the G0–G6 evidence, architecture, baseline comparisons,
risk–coverage points and reproducibility instructions. The README and
portfolio statements reflect the verified scope. Independent scoring
retains its documented blocker.
[Research report](G7_RESEARCH_REPORT.md).

G0–G5 and G7 met their development gates, seven of the eight roadmap
milestones. G6 completed the internal review, public replay and
reviewer handoff under the v4 fallback. Its independent run stays
`PARTIALLY_COMPLETE / PROVISIONAL_NOT_INDEPENDENT`. The review records
the denominator and evidence provenance for each result.
[Reviewer protocol](G6_EVALUATION_READINESS.md).

## Offline research demo D0–D8

This work targets the user-authorized local English CPU demo and zero paid API
calls. Each completed milestone is committed and pushed to main, followed by
the backend workflow for that exact SHA. The final gate is 12/16 grounded
Ford/Chevron positives, 8/8 withheld controls and at least two newly supported
original routed FinRank IDs. The transfer cohort is an internal evaluation.

### D0 baseline packaging

Reviewed and published the three corpus/public-runner helpers against their
G6 hashes. Corrected the optional observer environment variable names. Added
`DEMO_REPRODUCTION.md` with setup, artifact preparation and offline commands.
Ran the locked Arelle offline suite (594 passed, three missing-corpus skips),
Ruff, configured mypy and `uv lock --check --offline`. Raw prediction and score
outputs are `data/independent-final/finrank-2025/d0-predictions.json` and
`d0-scores.json`. Their SHA-256 values are respectively
`91502da96bed448ef11a4c941ff167e131b88688caa8986754b3c9153d5d378a` and
`b2d02359cd348866e488707874e3782a3811ae0530c845e37abb15ff113a6d4b`.
Both arms reproduced zero releases, 107 unsupported and 23 abstentions on 130
IDs, with mapped-page recall counts of 6/31 and 5/31. The loopback Apple HTTP
smoke checks FY2024 revenue and FY2030 abstention. Clean-checkout verification
and exact-SHA workflow are recorded at the following milestone.
