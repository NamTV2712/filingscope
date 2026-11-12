# M11 Advanced Verification

## Specialist graph

The default FAST and RESEARCH paths now assess individual assertions before
releasing the report. The verifier retains explicit citations and splits
coordinated values and common coordinated predicates. Each ledger claim has a
request-stable ID, a claim type, the cited and supporting evidence IDs, covered
requirements, a linked calculation when the reasoner supplied one, and a
verification status. Refuting and irrelevant citations can be inspected in the
audit. They do not enter the supporting evidence list.

Financial claims use the existing entity, metric, period, unit and Decimal
checks. Unresolved compound scope and conflicting inputs prevent full support.
The verifier excludes recognized forecasts and disclaimed values from actuals.
Qualitative claims use evidence within one cited sentence, with explicit
industry/sector paraphrases and polarity, or a sentence match for other
recognized topics. A keyword elsewhere in the same chunk supplies no proof of
the relationship.

A report earns `VERIFIED` when every released claim has source support and
the report covers the requested facts and arithmetic for each entity and
metric. `PARTIAL` releases a supported subset. `ABSTAIN` and `REJECTED`
return the insufficient-evidence response. A supported claim about another
metric contributes no coverage to the requested answer.

When verification finds an actionable defect and time remains, the verifier
can remove unsafe claims or replace a mismatched arithmetic value with the
deterministic calculation. It rechecks the edited report once and records both
passes in the ledger. Missing source evidence stays with the existing evidence
analysis and retrieval stages. Correction uses the supplied evidence, adds no
retrieval, model or tool calls, and keeps the four- and eight-stage graph
budgets. The previous P4 verifier remains available for comparison.

## Research and implementation decision

Chain-of-Verification separates drafting, independent checks and revision.
Reflexion uses feedback across attempts. FilingScope applies independent
source checks and a single correction based on a concrete verification result.
FEVER's evidence-linked labels inform the distinction between support,
refutation and missing evidence. [Chain-of-Verification](https://aclanthology.org/2024.findings-acl.212/) · [Reflexion](https://arxiv.org/abs/2303.11366) · [FEVER](https://aclanthology.org/N18-1074/)

## Controlled replay

The replay holds 16 authored draft answers and their supplied evidence fixed.
It compares P4's original verification disposition with the complete M11
release policy. Claim labels apply to the initial draft, before corrections.
Timings use 20 runs per case and include the second check when triggered.

| Metric | P4 | M11 |
|---|---:|---:|
| Exact atomic draft status sequence | 8/16 | 16/16 |
| Expected final disposition | 8/16 | 16/16 |
| Drafts with non-supported claims classified as VERIFIED | 1 | 0 |
| Corrected drafts | 0 | 4 |
| Wall time p50 | 1.375 ms | 2.060 ms |
| Wall time p95 | 2.211 ms | 6.376 ms |

Two drafts were repaired by removing a claim and two by recomputing growth,
including correcting the reported direction. The replay used zero model and
retrieval calls. A separate FAST graph test verified that a correction used
one original generator call, stayed within four graph stages, and preserved
the rejected claim in the draft audit. The tests also cover conflicting
growth inputs, ambiguous company scope, and cited forecasts or disclaimers.

The cohort is a deterministic behavior test. It provides no estimate of
real-filing answer accuracy or general semantic entailment. The qualitative
checks and the coordination patterns cover bounded forms. Ambiguous or
unrecognized wording can be held for lack of support. The default P5
offline evaluation continues to use the P4 baseline.

Source `16e106bf7761aa0115c0ec01cabeb06312f117a1` passed the full suite
with 332 tests and 3 skips. Compilation and Git whitespace checks passed.
The local replay JSON has SHA-256
`aaede22f4fd5de6020653206f7550c11ebf70f053b271fabb27a0247918d1f81`.

```powershell
uv run python -m scripts.run_advanced_verification_evaluation --repeats 20 --output data/financebench/verification_runs/m11-replay.json
uv run python -m pytest -q
```
