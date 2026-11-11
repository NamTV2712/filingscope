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
  `2131e3cda186874b5bd1dc17a516454256437b99`. The full suite passed with
  269 tests and 3 skips. Simulated search p50 fell from 250.85 ms to 87.44 ms
  with six calls in each mode. [M8 validation](PARALLEL_RESEARCH.md)

## Current milestone

M8 is validated. M9 structured financial intelligence is next.

## Exact next steps

1. Read section L and M9 in the specification. Compare the existing
   Company Facts reader with the official SEC documentation and EdgarTools.
2. Replace permissive row selection with explicit company, taxonomy,
   concept, fiscal period, duration, unit and revision handling.
3. Exercise realistic Company Facts fixtures with comparative rows,
   year-to-date data, amendments, competing units and restatements. Verify
   the structured worker's ledger provenance and unknown states.
4. Run the focused and full suites, document the findings, commit to
   `main`, push and verify the remote before starting M10.

## Remaining milestones

M9 structured financial intelligence; M10 document
intelligence experiment; M11 advanced verification; M12 hard-negative
financial retrieval benchmark; M13 multi-agent ablation; M14 advanced
retrieval experiments; M15 local research UX. Do not deploy.
