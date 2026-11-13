# G4 deterministic segment disclosures

## Evaluation protocol

The G2 narrative replay retrieved complete segment lists for NVIDIA and
Walmart but withheld both answers. It also missed Tesla's disclosure page.
Test whether extracting complete, explicitly counted segment lists from
approved filing text recovers answers on the same six narrative questions.
Keep the frozen G2 labels and report its strict wording and page score.
Review any released lists against the frozen disclosures and the specific
pages actually cited. Report this author review separately.

Keep the change if it recovers at least two of the three list answers with
valid issuer, period, form and source identity, preserves abstention on
the other three questions and introduces no unsupported release. Test
incomplete lists, altered names, wrong issuer, period and form, conflicting
lists and instruction-like text. Reproduce the same 104 numeric pilot
outcomes and run the existing offline regression checks. Use cached
public filings and pinned vectors. Record latency, tool calls, evidence
tokens and provider spend.

## Implementation

The document-scoped Dense retriever prioritizes matching explicit segment
lists within its existing bounded 100-candidate pool. The coverage
analyzer requires an issuer-bound, dated annual filing, page locator,
matching fiscal year, requested form and a complete counted list. Lists
that disagree for the same segment kind block release. The deterministic
writer preserves the disclosed names and segment kind. The atomic verifier
checks the full list against the cited approved page before release. This
path uses no provider calls and reuses the existing evidence ledger.

## Matched replay

| Measure | Document-only baseline → candidate | Hybrid baseline → candidate | Company Facts-only baseline → candidate |
| --- | ---: | ---: | ---: |
| Releases / questions | 0/6 → 3/6 | 0/6 → 3/6 | 0/6 → 0/6 |
| False abstentions | 6/6 → 3/6 | 6/6 → 3/6 | 6/6 → 6/6 |
| Frozen page retrieved | 2/6 → 4/6 | 2/6 → 4/6 | 0/6 → 0/6 |
| Strict frozen wording and page score | 0/6 → 0/6 | 0/6 → 0/6 | 0/6 → 0/6 |
| Author-checked incorrect releases | — → 0/3 | — → 0/3 | — → — |
| Author-checked citation support and claim faithfulness | — → 3/3 each | — → 3/3 each | — → — |
| Total tool calls | 6 → 6 | 6 → 6 | 0 → 0 |
| Mean evidence tokens | 1,313.5 → 1,242.3 | 1,313.5 → 1,242.3 | 0 → 0 |
| Warm p50/p95, ms | 39.65/46.38 → 39.79/47.88 | 39.20/42.99 → 42.42/46.45 | 4.22/5.43 → 3.98/4.50 |

Both PDF arms cited Tesla `#p4`, NVIDIA `#p127` and Walmart `#p7`.
The three released statements match the disclosed segment counts and
names. NVIDIA's cited page differs from the frozen locator `#p96`.
The canonical wording differs from all three reference strings. The
historical scorer consequently counts each release as a miss. The author
review is limited to the three released claims and their cited pages.
Context Precision@10 requires broader candidate judgments. The Apple
product and disruption cases and Tesla currency-risk case still abstain.

All 104 numeric arm/case outcomes matched the G2 replay, including
answers, dispositions, cited and retrieved sources, and accuracy.
The historical architecture and injected-fault replay matched its G3
predecessor after excluding timing and process memory. Windows offline
passed 534 tests with 3 skips. WSL passed 533 with 4 skips. The fixture
skips reflect missing local corpora. Ruff, focused mypy, the offline
lockfile check and deterministic claim and citation checks passed.
The final SEC process used 1,881,821,184 bytes peak and 36.83 s setup.
Provider calls, billed tokens and spend were zero.

**KEEP** the deterministic path for complete two- or three-segment
lists from a single fiscal year's annual filing. **DEFER** broader
disclosure templates and independent narrative accuracy claims. This
run used one warm replay per arm and author-checked references.
Baseline Git commit `4c4ca83`.

```text
python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --reuse-pilot-vectors .local/g3/inline-runtime-full --narrative-controls --inline-facts .local/g2/verified-replay/facts --output .local/g4/segment-final
python -m scripts.run_specialist_architectures --faults --output .local/g4/segment-historical.json --manifest .local/g4/segment-historical-manifest.json
```

Use the G0 offline CPU environment. The [SEC replay](../.local/g4/segment-final/report.json)
has SHA-256 `3f08cc63d518cdfb65741c86f44bb058cce05a99ce9f1faa81948e7450f2269b`.
The [historical replay](../.local/g4/segment-historical.json) has SHA-256
`7fd8671bfd04d2edc904c270d5af2e479f9cf7b0e13d56488dc3ab8abdff04fd`.
