# Implementation progress

Updated: 2026-11-12<br>
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

## Current milestone

M1–M15 are implemented, validated and pushed. Completion source
`3c55a2bc1393d327fba26a0b7e666cd791907e44` adds the six-decision replay,
ordinal risk-coverage points from M13, configurable route budgets and
provider token accounting. The final regression suite passed with 349
tests and 3 skips. [Specification audit](SPECIFICATION_AUDIT.md)

## Exact next steps

To reproduce the audit, run the commands in the specification audit.

## Remaining milestones

All implementation milestones are complete. Deployment is outside the
specification.
