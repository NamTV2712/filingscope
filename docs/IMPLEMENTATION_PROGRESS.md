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
  The full suite passed with 335 tests and 3 skips. [M12 validation](HARD_NEGATIVE_RETRIEVAL.md)

## Current milestone

M13 multi-agent ablation is next. The M12 ranking report is complete at
`data/financebench/hard_negative_runs/m12-results.json`.

## Exact next steps

1. Read specification sections V and W and inspect `docs/ABLATION_STUDY.md`,
   the P5 evaluation artifacts and the current specialist graph contracts.
2. Freeze a comparable cohort and specify the active components for B0–B5.
   Run the ablation through the actual retrieval and specialist paths.
3. Record quality, provenance, resource use and routing errors. Validate,
   commit and push M13 before starting M14.

## Remaining milestones

M13 multi-agent ablation, M14 advanced retrieval experiments and M15 local
research UX. Do not deploy.
