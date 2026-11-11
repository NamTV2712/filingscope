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
  revision. Source `aad24377da2075ccb6e1c4d55106dc480c6309e5`. Eight of
  eight published fixture slots matched. The full suite passed with 303
  tests and 3 skips. [M9 validation](FINANCIAL_FACT_ARCHITECTURE.md)

## Current milestone

M9 is validated. M10 document intelligence is next.

## Exact next steps

1. Read the document intelligence requirements and M10 in the specification.
   Locate the pypdf ingestion path and known FinanceBench failure pages.
2. Freeze a comparable subset and run the baseline and optional Docling
   parser under the same retrieval protocol. Track evidence coverage,
   structure, provenance, latency, memory and model/disk requirements.
3. Retain only a demonstrated improvement and keep optional dependencies
   isolated. Run focused and full tests, record results and commit to
   `main`. Push and verify the remote before starting M11.

## Remaining milestones

M10 document intelligence experiment; M11 advanced verification; M12 hard-negative
financial retrieval benchmark; M13 multi-agent ablation; M14 advanced
retrieval experiments; M15 local research UX. Do not deploy.
