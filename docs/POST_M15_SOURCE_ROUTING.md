# Q3 Source-aware FAST routing

**Status** Validated offline. Source before Q3
`bb90e3c7a89713558bd267b5bd5e2f97473b50a7`. The validated revision is
recorded in the [implementation checkpoint](IMPLEMENTATION_PROGRESS.md#post-m15-checkpoint).

## Hypothesis and implementation

Q2 recovered discrete-quarter values in RESEARCH. FAST could still omit
the SEC worker and retrieve filing fragments for a single known fact.
Q3 tests whether a typed source decision can recover those answers at a
lower request cost than forced RESEARCH.

The existing LangGraph router carries the source capability selected for
the task. It uses the resolved company, metric, fiscal period, operation,
filing form and runtime inventories. A one-slot standard financial
lookup can select `DIRECT_XBRL`. Explicit statement requests with an
indexed physical page can select `DIRECT_TABLE`. Narrative and
nonstandard requests stay on `TEXT_RAG`. The existing complexity route
and task budget govern `COMPOSITE` questions. Out-of-scope questions
retain `UNSUPPORTED`.

FAST reuses the SEC worker, table worker and filing worker within a
four-step graph. A valid direct SEC fact skips PDF retrieval. On a miss,
the table worker can locate up to six financial statement pages in the
scoped documents. The page index uses headings and document IDs from the
hash-verified cache. It never reads evaluation page labels. If the
available typed table values cannot fill the slot, one targeted filing
search runs within the same request budget. A qualifier that requires an
unmodeled financial reporting basis withholds the numerical answer.

The same evidence analyst, deterministic writer, ledger and claim
verifier remain on the release path. Source-aware FAST uses zero LLM
calls for an eligible lookup. The public API exposes its selected source
capability and existing tool and latency receipts.

## Paired evaluation

The M13 replay uses all 24 original questions and Q2 source artifacts.
The new direct-fact cohort has 15 questions and 14 answerable cases,
with five development and ten validation questions in disjoint issuer
groups. Labels are provisional and source-checked against pinned Company
Facts accessions and physical statement pages. They await independent
human review. B4 is forced RESEARCH, B5 is the Q2 FAST/RESEARCH control,
and B6 enables the source capability decision. The evaluator checks both
controls against their pre-change artifacts before comparing B6.

Two controls cited original financial statement pages omitted from the
initial label set. Source adjudication added Best Buy FY2023 PDF page 38
and Nike FY2021 PDF page 60, both zero-based. The evaluator checks that
the answers and retrieval traces match the frozen controls before
crediting the citations. The original provisional artifact is retained.

| Cohort and metric | B4 | B5 | B6 |
|---|---:|---:|---:|
| New development grounded exact / answerable | 3/5 | 1/5 | 5/5 |
| New validation grounded exact / answerable | 8/9 | 2/9 | 9/9 |
| New validation tools / answerable request | 20/9 | 6/9 | 9/9 |
| New validation unsupported releases / released | 0/8 | 0/2 | 0/9 |
| New validation correct citations / citations | 8/8 | 2/2 | 9/9 |
| New validation warm p50 / p95 ms | 90.667 / 154.358 | 58.409 / 84.331 | 10.199 / 11.524 |
| M13 grounded exact / answerable | 7/21 | 3/21 | 14/21 |
| M13 false abstentions / answerable | 14/21 | 18/21 | 7/21 |
| M13 unsupported releases / released | 0/7 | 0/3 | 0/14 |
| M13 correct abstentions / unanswerable | 3/3 | 3/3 | 3/3 |
| M13 mean tool calls | 2.7500 | 1.0833 | 1.2083 |
| M13 mean vector retrieval calls | 1.7917 | 0.9167 | 0.4583 |
| M13 warm p50 / p95 ms | 115.979 / 234.283 | 62.775 / 180.242 | 16.044 / 175.102 |

FAST recovered Microsoft FY2024 revenue, Best Buy quarterly cash and
FY2019 assets, and Apple discrete-quarter revenue using SEC sources.
Among the remaining M13 recoveries were two statement-scoped lookups
for MGM Resorts and Boeing. General Mills FY2022 revenue in the new
cohort exercised a missing SEC fact followed by a successful table
lookup. Costco FY2021 operating income used the statement locator
directly. Unit tests exercise a second fallback from an unavailable
table to bounded text retrieval, the narrative route, and the
nonstandard-basis guard.

The validation gain over forced RESEARCH was 1/9, or 11.11 percentage
points, with a descriptive 95% issuer-group bootstrap interval of 0.0
to 33.33 points over five groups. It used 45% of the forced variant's
tools on the same answerable requests. M13 B6 gained 11/21 over B5
with an interval of 27.78 to 72.73 percentage points over eight groups.
Each interval used 10,000 grouped draws. M13 citations and numeric
exactness matched grounded exactness. The new cohort has a small release
denominator and does not establish population risk.

The M13 comparative and calculation cases remain difficult. Seven
answerable requests were withheld in B6, including the Amcor
statement-scoped revenue question and several multi-period cases.
The routing comparison measures the pinned source coverage and the
included issuer groups.

## Reproduce

Run the B4/B5 direct cohort on the Q2 runtime to generate the frozen
control before enabling the source-aware variant. Keep the resulting
`q3-direct-baseline.json` and the Q2 `q2-verified-ablation.json` in the
ignored run directory. The cohort labels and ablation runner are
evaluation-only. The post-change B4/B5 variants also reproduce the
quality and usage counts of those controls.

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OPENBLAS_NUM_THREADS = '6'
$runs = 'data/financebench/ablation_runs'
$pages = 'data/financebench/cache/extracted_pages_d5c2a1369d9997a3055a.jsonl'
uv run --offline --with psutil==7.2.2 python -m scripts.run_multi_agent_ablation --variants B4 B5 B6 --cohort direct_facts --statement-pages $pages --output "$runs/q3-direct-adjudicated.json"
uv run --offline --with psutil==7.2.2 python -m scripts.run_multi_agent_ablation --variants B4 B5 B6 --statement-pages $pages --output "$runs/q3-m13-verified.json"
python -m scripts.run_source_routing_evaluation --output "$runs/q3-summary.json" --manifest "$runs/q3-manifest.json"
```

The runs use pinned pypdf pages and local SEC snapshots through
2024-12-31. The benchmarks make zero SEC HTTP calls and use zero
provider calls, input tokens, output tokens and provider cost.
The new-cohort process peaked at 2,002,763,776 bytes with 10.655 s
setup. The M13 process peaked at 2,004,746,240 bytes with 10.586 s setup.
The Q3 summary SHA-256 is
`f9b56c5e76de63fbc71244c181c38d386c0d5f3d58576d46fc11e39c3d14e638`.
The manifest binds it to both frozen controls and the scored replays.

Full regression passed 371 tests with three existing missing-local-HTML
skips. The normal loopback API verified three real requests exercising
SEC direct, SEC-to-table fallback, and direct table lookup, with one,
two and one tools respectively. All three kept source-linked claims and
made zero vector or model calls. Website assets were untouched.

**Decision** Adopt source-aware FAST. Use the Q3 residual cases and a
new policy cohort to evaluate evidence sufficiency in Q4.
