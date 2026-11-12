# Implementation progress

Updated: 2026-11-12<br>
Branch: `main`<br>
Remote: `origin` (`https://github.com/NamTV2712/filingscope.git`)<br>
Deployment: none; explicitly out of scope

## Completed milestones

- M1–M5: complete and pushed; preserve their individual reports and benchmark
  baselines in `docs/`.
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
  `4121d0b8c2f34a7ddb409de4939d5df5b3c101da`. The full suite passed with
  346 tests and 3 skips. [M15 validation](LOCAL_RESEARCH.md)

## Current milestone

The M1–M15 sequence is implemented and validated. The specification audit
found two reporting gaps. Section U requires one independent report
covering all six decision points. Section W requires risk at multiple
coverage operating points.

## Exact next steps

1. Replay the labeled router, candidate, evidence-decision, and verification
   fixtures through the actual control plane and report Section U binary metrics.
2. Build the Section W risk-coverage comparison from the frozen M13 rows
   and distinguish operating points from a calibrated confidence sweep.
3. Finish the specification audit, run regressions and verify the final push.

## Remaining milestones

Final specification audit and the two reporting gaps above. Do not deploy.
