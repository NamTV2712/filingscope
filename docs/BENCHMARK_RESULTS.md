# FinanceBench Retrieval Results

## Run identity

This report records the P1 retrieval-only baseline. The full machine-readable
run manifest, predictions, and per-case analysis are produced locally beneath
`data/financebench/runs/` and are excluded from Git. The checked-in values below
were copied from the completed run's `metrics.json` and `run_manifest.json`.

| Setting | Value |
|---|---|
| Benchmark snapshot | FinanceBench public sample, Git revision `cc39aeb4afdf33909ee1412188bf89035950c2eb` |
| Cases | 150 eligible, 0 excluded |
| Company-grouped split | 60 development / 45 validation / 45 held out |
| Source PDFs | 84 |
| Extracted pages | 12,013 total; 11,934 nonempty |
| Page-local chunks | 28,849; 450 tokens with 75-token overlap |
| Evidence-page text | 188 of 189 evidence records had extracted text (99.47%) |
| Full-page token overlap | Median 0.9945; mean 0.9677 |
| Embedding model | `nomic-ai/nomic-embed-text-v1.5` at `e9b6763023c676ca8431644204f50c2b100d9aab` |
| Cross-encoder | `cross-encoder/ms-marco-MiniLM-L-6-v2` at `233902d25c440f23af6f7d6e94d2946bac0bee0a` |
| Runtime | Python 3.12.7, PyTorch 2.11.0+cu128, CUDA 12.8 |

## Overall results

Recall and ranking metrics compare retrieved document-page pairs to the
FinanceBench evidence pages. Latency is per query; see
[`EVALUATION_PROTOCOL.md`](EVALUATION_PROTOCOL.md) for exact definitions.

| Preset | Recall@5 | Recall@10 | AllEvidence@5 | AllEvidence@10 | MRR@10 | nDCG@5 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.1000 | 0.1133 | 0.1000 | 0.1133 | 0.0750 | 0.0802 | 196.833 | 497.904 |
| Dense | 0.3267 | **0.4167** | 0.2733 | **0.3733** | **0.2496** | **0.2442** | **94.926** | **121.713** |
| Hybrid RRF | 0.1933 | 0.3167 | 0.1667 | 0.2600 | 0.1315 | 0.1287 | 1374.296 | 1728.462 |
| Hybrid + reranker | 0.2367 | 0.3100 | 0.1933 | 0.2600 | 0.2044 | 0.1897 | 1741.154 | 2052.725 |

Dense retrieval leads this baseline on Recall@10, complete evidence-page
coverage at 10, MRR@10, and nDCG@5, while also having the lowest measured
median and p95 latency. Hybrid RRF is below dense retrieval on these measures.
Adding the cross-encoder improves MRR@10 from 0.1315 to 0.2044 and nDCG@5
from 0.1287 to 0.1897 versus hybrid RRF, while slightly lowering Recall@10
from 0.3167 to 0.3100 and increasing p50 latency by about 367 ms. The reranker
does not outperform the dense baseline on this sample.

## Results by company split

| Preset | Split | Cases | Recall@10 | AllEvidence@10 | MRR@10 | nDCG@5 | p50 ms | p95 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | Development | 60 | 0.1167 | 0.1167 | 0.0906 | 0.0917 | 175.611 | 371.810 |
| BM25 | Validation | 45 | 0.1333 | 0.1333 | 0.0624 | 0.0725 | 238.039 | 509.722 |
| BM25 | Held out | 45 | 0.0889 | 0.0889 | 0.0667 | 0.0725 | 232.240 | 539.705 |
| Dense | Development | 60 | 0.4250 | 0.3833 | 0.2370 | 0.2395 | 91.465 | 128.919 |
| Dense | Validation | 45 | 0.3444 | 0.3111 | 0.2171 | 0.2002 | 96.582 | 119.425 |
| Dense | Held out | 45 | 0.4778 | 0.4222 | 0.2989 | 0.2946 | 93.174 | 105.545 |
| Hybrid RRF | Development | 60 | 0.3417 | 0.3000 | 0.1514 | 0.1543 | 1303.021 | 1750.552 |
| Hybrid RRF | Validation | 45 | 0.2556 | 0.2000 | 0.1146 | 0.1160 | 1434.860 | 1728.462 |
| Hybrid RRF | Held out | 45 | 0.3444 | 0.2667 | 0.1220 | 0.1072 | 1281.072 | 1702.694 |
| Hybrid + reranker | Development | 60 | 0.3083 | 0.2500 | 0.2094 | 0.1928 | 1684.142 | 2004.693 |
| Hybrid + reranker | Validation | 45 | 0.3444 | 0.3111 | 0.2400 | 0.2323 | 1815.674 | 2082.999 |
| Hybrid + reranker | Held out | 45 | 0.2778 | 0.2222 | 0.1622 | 0.1430 | 1643.603 | 2063.100 |

## Limits

These measurements cover the public 150-case sample and this fixed 84-PDF
corpus. Company grouping reduces document leakage between splits, but the
held-out set is only 45 cases. The task scored here is evidence-page retrieval;
it does not assess generated answers, abstention, claim support, or full agent
behavior. pypdf does not run OCR, and retrieval errors have not yet been
manually attributed to extraction, chunking, query formulation, or ranking.
The local CUDA run and measured latency should not be treated as a production
service benchmark.
