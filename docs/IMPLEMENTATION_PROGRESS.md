# Implementation progress

Updated: 2026-11-11<br>
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

## Current milestone

M7 source and documentation are pushed and verified on `origin/main` at
`81fe0e013a9270b18829d06a62a4952a0ff9b0d0`. Start M8 next.

## Exact next steps

1. Read M8 and sections P/R/V/W/AA in the pasted specification. Implement
   bounded fan-out/fan-in only for independent company/period/source tasks;
   preserve deterministic evidence-ledger merges and isolate worker failures.
2. Add concurrency, budget, duplicate-work, merge-order, and failure-isolation
   tests. Run focused and full regressions, record limits and results, commit
   source and docs, push to `origin/main`, and verify the remote SHA.
3. Continue with M9 only after M8 is validated and pushed.

## Remaining milestones

M8 parallel research; M9 structured financial intelligence; M10 document
intelligence experiment; M11 advanced verification; M12 hard-negative
financial retrieval benchmark; M13 multi-agent ablation; M14 advanced
retrieval experiments; M15 local research UX. Do not deploy.
