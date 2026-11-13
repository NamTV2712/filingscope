# G3 SEC pilot retrieval ablation

The statement ranker prioritizes pages with the requested metric and
period. Compare unscoped Dense, planner-scoped Dense and planner-scoped
Dense with the existing statement ranker on the same 23 answerable
pilot questions. Hold the original question, corpus, embeddings and
top-ten cutoff fixed. Derive scope from the router's planned documents
before reading the gold locators. Check that scoped arms return no
out-of-scope pages. Report context precision against the frozen PDF
locators and required-cell recall, preserving duplicate chunk ranks.
Treat other pages as unjudged for semantic precision. Compare scoped
Dense and scoped statement ranking downstream in the same document-only
graph, with direct statement lookup enabled in both. Preserve the
existing default pending the measured accuracy and release results.

Review all pages returned by either arm on the four cases where
scoped Dense misses at least one frozen target. Apply the same rule
to every page in this selected subset. A page contributes evidence
when it states at least one requested amount with the correct issuer,
metric, period, scale and reporting scope. The question does not
request rounded values. Record valid alternative pages without
editing the original pilot references. This post-run review is a
diagnostic on selected misses and is development-exposed.

## Results

| Ranking arm | Frozen locator precision@10 | Required-cell recall@10 | Warm retrieval p50 / p95 |
| --- | ---: | ---: | ---: |
| Dense | 20/219 | 22/26 | 49.35 / 54.70 ms |
| Planner-scoped Dense | 20/219 | 22/26 | 48.90 / 55.95 ms |
| Planner-scoped with statement ranking | 23/212 | 25/26 | 53.24 / 59.93 ms |

Counts pool unique physical pages within each request's original top
ten chunks. The 26 cells include multiple requirements on some pages.
Scope excluded all out-of-scope results. The ranking arm recovered
the frozen pages for Apple's Q3 and YTD revenue and the Apple operand
in the Apple–NVIDIA comparison. Dense scope alone recovered no extra
gold targets in this five-document corpus.

The author checked all returned pages on the four selected questions
and added source-supported alternatives. Apple Note 2 repeats both
quarterly and YTD net sales, and the MD&A gives the same figures.
NVIDIA's segment, geographic and end-market disclosures include its
consolidated total. Tesla's FY2024 income statement also gives the
segment's USD 10,086 million. All three arms ranked that page second,
so the Tesla miss by original locator was a reference coverage issue.
[Page judgments](G3_SEC_RANKING_REVIEW.json).

| Ranking arm | Reviewed page Context Precision@10 | Reviewed Gold Evidence Recall@10 |
| --- | ---: | ---: |
| Dense | 8/38 | 4/5 |
| Planner-scoped Dense | 8/38 | 4/5 |
| Planner-scoped with statement ranking | 11/36 | 5/5 |

Both document-only graphs grounded 22/23 by the original locators,
released 22/26 and had zero incorrect releases. The graph's direct
statement lookup was available in both arms. One false abstention
remained on the Tesla segment question. The optional Inline XBRL arm
continues to verify it. The four original runtime tracks matched all
104 stable outcomes against the prior frozen replay. Claim-level
faithfulness and citation entailment were outside this ranking study.

Both document-only arms used 33 tools and 10,506 evidence tokens.
Warm graph p50/p95 was 14.32/191.11 ms for Dense and 17.99/185.82 ms
with ranking. Peak process working set was 1,896,398,848 bytes,
including shared setup. Model-provider calls, billed tokens and spend
were zero. Timings describe single runs with the local embedding model.

## Reproduction and decision

**KEEP** the current statement ranker and direct statement lookup.
The reranker improved the isolated rank measure. The paired runtime
outputs matched. **DEFER** a general precision claim until a larger
cohort has complete judgments. Baseline commit `75f65e5`.

The focused tests passed 29/29. Windows passed 508 tests with three
fixture skips and WSL passed 507 with four. Both reported 100% claim
status and disposition accuracy. Ruff and focused mypy passed.

Run with the G0 offline CPU environment and the previously verified
G2 PDFs, Company Facts snapshots and iXBRL extracts. Reusing the prior
pilot vectors checks the model revision, reconstructed chunk order,
matrix dimensions, unit norms and vector byte hash. Omitting
`--reuse-pilot-vectors` regenerates the document embeddings.

```text
python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --inline-facts .local/g2/verified-replay/facts --ranking-controls --reuse-pilot-vectors .local/g3/inline-runtime-full --output .local/g3/sec-ranking
python -m scripts.score_sec_ranking_review --report .local/g3/sec-ranking/report.json --output .local/g3/sec-ranking/review-score.json
```

The pilot report SHA-256 is `2a67c11fa7d69a498e86f95383c56fee6bf9a7dfe5594dc013023e37cd03e744`.
The reviewed score SHA-256 is `60c3cf0f3d70a20378124f381640217a8448343e7770badc20017295c6c1b756`.
