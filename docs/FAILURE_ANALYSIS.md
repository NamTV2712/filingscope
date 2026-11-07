# FinanceBench Retrieval Failure Analysis

This is an aggregate analysis of cases for which a preset returned no
FinanceBench evidence page in its top 10. Per-case identifiers and retrieved
chunk details remain in the ignored local `failure_analysis.json` and
prediction files. No gold answers or evidence text are included in this report.

## No-evidence-page cases by question type

Each question-type group has 50 cases. A case counts as a miss here only when
none of its labeled evidence pages appears in the top 10; this is distinct from
page-level `Recall@10` and from `AllEvidencePages@10`.

| Preset | Domain-relevant | Metrics-generated | Novel-generated | Total misses |
|---|---:|---:|---:|---:|
| BM25 | 46/50 (92%) | 50/50 (100%) | 37/50 (74%) | 133/150 (88.7%) |
| Dense | 39/50 (78%) | 13/50 (26%) | 29/50 (58%) | 81/150 (54.0%) |
| Hybrid RRF | 42/50 (84%) | 22/50 (44%) | 30/50 (60%) | 94/150 (62.7%) |
| Hybrid + reranker | 42/50 (84%) | 18/50 (36%) | 36/50 (72%) | 96/150 (64.0%) |

Dense retrieval has the fewest no-hit cases overall. The reranker reduces
no-hit cases for metrics-generated questions relative to hybrid RRF (22 to
18), but increases them for novel-generated questions (30 to 36). This
describes the measured top-10 outcomes; it does not establish why those cases
failed.

## No-evidence-page cases by split

| Preset | Development | Validation | Held out |
|---|---:|---:|---:|
| BM25 | 53/60 (88.3%) | 39/45 (86.7%) | 41/45 (91.1%) |
| Dense | 32/60 (53.3%) | 28/45 (62.2%) | 21/45 (46.7%) |
| Hybrid RRF | 37/60 (61.7%) | 31/45 (68.9%) | 26/45 (57.8%) |
| Hybrid + reranker | 38/60 (63.3%) | 28/45 (62.2%) | 30/45 (66.7%) |

## Interpretation and follow-up

- BM25 alone is weak on this corpus, with no evidence page retrieved for all
  50 metrics-generated questions.
- Dense retrieval is the strongest P1 reference, but it still returns no
  evidence page for 81 of 150 cases and retrieves all evidence pages at 10 for
  only 37.33% of cases.
- Hybrid RRF does not improve on dense retrieval in the overall P1 metrics.
  The hybrid path also has higher measured latency; its lexical ladder and
  candidate fusion should be measured stage by stage before tuning.
- Reranking changes the ordering of the hybrid candidate set, improving MRR
  and nDCG against hybrid RRF while not increasing Recall@10 or complete
  evidence coverage. Candidate recall and ranking quality should remain
  separate objectives in later phases.
- Parser alignment is high for most evidence pages (median full-page token
  overlap 0.9945), but the lower mean (0.9677) indicates a tail worth auditing.
  Text availability and token overlap are diagnostics, not proof that every
  relevant passage was extracted faithfully.

The next phases will use these measured gaps to add evidence sufficiency,
adaptive retrieval, and claim verification. Those improvements must be measured
against the same frozen splits and retrieval protocol before any quality claim
is made. Failure counts are benchmark-specific and should not be generalized
to other filings or user questions.
