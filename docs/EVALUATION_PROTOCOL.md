# Retrieval Evaluation Protocol

## Corpus and controls

The retrieval corpus contains the page text of every FinanceBench source PDF
referenced by the public 150-case sample. It is built from the 84 distinct
case-referenced reports, with no query-specific document filtering. Chunking
uses the shared FilingScope `chunk_text` implementation, 450 tokens per chunk
and 75 tokens of overlap, without crossing PDF page boundaries.

Inference receives only a question and the shared corpus. It does not receive
gold answers, evidence snippets, evidence page numbers, dataset split labels,
or question-type labels. The `src.evaluation` package is called by offline
benchmark scripts and is not imported by runtime retrieval modules.

Each retrieval run uses a Qdrant collection and artifact directory derived
from the corpus fingerprint, embedding model revision, and chunking settings.
The index manifest records the fingerprint, point count, vector dimension and
distance metric. Existing collections are verified and reused; a mismatched
collection fails closed instead of being deleted or overwritten.

## Baselines

The runner uses a fixed `top_k=10` and hybrid candidate pool of 50:

| Preset | Ranking behavior |
|---|---|
| `bm25` | Existing BM25 index and tokenizer; no dense or reranker scores in ranking. |
| `dense` | Pinned Nomic query embeddings and Qdrant cosine retrieval. |
| `hybrid` | BM25, dense Qdrant retrieval, the existing deterministic lexical ladder, reciprocal rank fusion, no cross-encoder. |
| `hybrid_rerank` | The same hybrid candidate generation followed by the pinned MS MARCO cross-encoder. |

The structured financial-row lookup is disabled for this PDF corpus because
it is designed for extracted SEC table chunks, not raw PDF page text. The
retrieval implementation itself remains the migrated FilingScope retriever;
the evaluation adapter only selects a stage and normalizes its result record.

Models and exact revisions are read from `configs/settings.py` and written to
the run manifest. The runner performs a generic warm-up query before measuring
the dataset. Query embeddings are computed once per question and shared by the
dense, hybrid and reranked presets. Their reported latency includes query
embedding time plus that preset's retrieval work. BM25 latency includes its
own retrieval work and excludes embedding time. The system records p50 and
p95 by the nearest-rank percentile method.

## Metrics

Ground truth is a set of `(doc_name, zero_based_page_number)` pairs per case.
Multiple retrieved chunks from the same page count as one page for recall,
evidence coverage and nDCG. A page from a different document is not relevant.

- **Recall@5 / Recall@10:** fraction of gold evidence pages found in the first
  5 / 10 retrieved chunks, after duplicate page collapse.
- **MRR@10:** reciprocal rank of the first chunk whose document-page pair is
  gold relevant.
- **nDCG@5:** binary-relevance, page-deduplicated discounted gain at five.
- **AllEvidencePages@5 / @10:** fraction of cases for which every gold page was
  retrieved in the first 5 / 10 chunks.
- **Latency p50 / p95:** nearest-rank percentiles over per-case retrieval
  latency in milliseconds, with the inclusion rules described above.

Results are reported overall and separately for development, validation and
held-out cases. Parser diagnostics (evidence page text availability and token
overlap) are reported separately and do not remove difficult cases.

## Reproduction

Install the requirements after installing a suitable CPU or CUDA PyTorch wheel,
then run:

```powershell
python -m scripts.download_financebench
python -m scripts.run_financebench_retrieval
```

The runner writes manifests, per-preset predictions, metrics, and failure
analysis beneath `data/financebench/runs/<index-id>/`. These files include
case IDs and retrieved chunk IDs/scores but not gold answers or evidence text.
All generated artifacts and local source documents are ignored by Git.

The four presets measure retrieval only. They do not measure answer generation,
abstention, claim verification, or agentic retrieval; those are later phases.

## Evidence decision evaluation (P2)

P2 uses a separate 15-case controlled synthetic evaluation for exact action and
reason-code correctness. It covers complete, missing, conflicting, unsupported,
and budget-exhausted evidence bundles. These fixtures do not use FinanceBench
gold answers and do not estimate generalization or calibration. The cases,
metrics, reproducibility command, and measured results are documented in
[`DECISION_EVALUATION.md`](DECISION_EVALUATION.md). Independent labelled
decision cases belong to the end-to-end P5 evaluation.

## Adaptive retrieval evaluation (P3)

P3's nine-case controller evaluation measures final action and stop-reason
accuracy, completion of cases with retrievable evidence gaps, no-progress
detection, and targeted query count. A separate hermetic integration test
invokes the migrated `HybridRetriever` over a synthetic Qdrant corpus. The
cases and limitations are recorded in
[`ADAPTIVE_RETRIEVAL_EVALUATION.md`](ADAPTIVE_RETRIEVAL_EVALUATION.md). The
fixed scenarios do not estimate real-corpus performance.
