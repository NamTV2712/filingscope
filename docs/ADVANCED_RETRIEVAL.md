# M14 Advanced Retrieval

## Parent-page context and statement alignment

The remaining R6 experiment replays the 24 M12 dense rankings against the
original P1 page cache. It compares ten ranked children, ranked parent-page
selection, and selective page expansion when two of the top ten children
come from the same page. All variants have a 4,500-token cap and use the
same physical page and chunk identities. A page too large for the remaining
budget falls back to its ranked child. The replay confirms the source-page
cache hash and keeps the source URL on every retained context.

This adapts hierarchical parent selection from retrieval systems that group
child hits into larger contexts. In FilingScope the physical PDF page is a
source-boundary with independently checkable provenance. [Auto-merging retriever](https://developers.llamaindex.ai/python/framework/integrations/retrievers/auto_merging_retriever/)

| Context | Labeled passage recall | Complete cases / 24 | Cases exposed to a labeled negative | Mean tokens | Held-out recall |
|---|---:|---:|---:|---:|---:|
| Dense children | 0.5625 | 13 | 9 | 4,047 | 0.7500 |
| Parent pages | 0.5000 | 12 | 10 | 4,398 | 0.6250 |
| Selective expansion | 0.5625 | 13 | 9 | 4,089 | 0.7500 |

Parent expansion consumed more of the token budget and displaced relevant
children. Selective expansion kept coverage and exposed the same number of
cases to labeled negatives. The 569 loaded pages took 2.273 s to prepare.
The process reached 892 MB peak working set. In-memory selection p95 was
0.055, 0.045, and 0.025 ms, respectively, excluding initial retrieval.

A separate extraction audit starts from known source pages for 14 annual
financial slots from M13. P2 recovered 0/14 exact values with complete units
and periods from the raw child chunks. Explicit header and row pairing
recovered 11/14. It resolves annual tables with recognized statement titles,
ordered fiscal columns, a stated scale and exact metric rows. An unlabeled
MGM revenue subtotal and two incompatible table headers remained unresolved.
This is an extraction audit with known evidence locations. Keep the
statement parser available for source inspection and further controlled
integration. Keep dense child context as the default.

## Fixed-pool reranking

All reranking variants receive the same 50 dense candidates per M12 question.
They can change the top five and top ten. The fixed pool controls candidate
recall and prevents access to answer labels. The comparison includes the P1
cross-encoder and scores hard-negative pairs only when both passages entered
the pool.

ColBERTv2 uses the pinned `colbert-ir/colbertv2.0` ONNX weights with FastEmbed
0.9.1. NumPy computes token-wise MaxSim and a local Qdrant collection runs
the same multivector scoring on the same candidate IDs. Qdrant is in memory
with HNSW disabled for the reranking vectors. [ColBERT model](https://huggingface.co/colbert-ir/colbertv2.0) · [Qdrant FastEmbed](https://qdrant.tech/documentation/fastembed/fastembed-colbert/) · [Qdrant multivectors](https://qdrant.tech/documentation/tutorials-search-engineering/using-multivector-representations/)

Three graph experiments use observed company, filing, physical page, form,
reporting year and text cues. The GraphRAG adaptation follows issuer-to-filing
and filing-to-text links. The HippoRAG adaptation runs personalized PageRank
with query and dense seeds. The LightRAG adaptation fuses issuer-local and
issuer-topic relationship rankings. These evaluate retrieval mechanisms
using the same evidence graph. Graph construction and scoring use no LLM,
OpenIE, generated entity profiles or community summaries.
[GraphRAG local search](https://microsoft.github.io/graphrag/query/local_search/) · [HippoRAG paper](https://arxiv.org/abs/2405.14831) · [LightRAG paper](https://arxiv.org/abs/2410.05779)

### Results

| Variant | Recall@5 | Recall@10 | Full evidence@10 | MRR@10 | nDCG@5 | Held-out Recall@10 | Curated pairs | Added p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Dense | 0.4792 | 0.5625 | 13/24 | 0.3529 | 0.3757 | 0.7500 | 12/14 | — |
| P1 cross-encoder | 0.7222 | 0.7639 | 16/24 | 0.5552 | 0.5516 | 0.8750 | 10/14 | 2,180.200 |
| ColBERT MaxSim | 0.6597 | 0.8056 | 17/24 | 0.5376 | 0.5294 | 0.8750 | 11/14 | 36.571 |
| Qdrant multivector | 0.6597 | 0.8056 | 17/24 | 0.5376 | 0.5294 | 0.8750 | 11/14 | 277.744 |
| GraphRAG local | 0.6667 | 0.7708 | 17/24 | 0.4431 | 0.4817 | 0.8125 | 13/14 | 0.457 |
| HippoRAG-style PageRank | 0.6042 | 0.8333 | 18/24 | 0.4341 | 0.4412 | 0.8750 | 13/14 | 0.831 |
| LightRAG-style dual level | 0.6667 | 0.7708 | 17/24 | 0.5712 | 0.5647 | 0.8125 | 13/14 | 0.442 |

Every variant had Recall@50 of 0.8472. Held-out full coverage remained 6/8.
All three graph adaptations won 9/9 held-out curated pairs, compared with
8/9 for dense. The graph variants placed a known negative above the best
labeled evidence in 2/24 cases versus 3/24 for dense and 4/24 for ColBERT.
They can still increase negative exposure within the top ten. The PageRank
variant did so in ten cases versus nine for dense. These results use sparse
judgments and do not establish behavior for other companies or queries.

Added latency excludes the initial dense query, which had a p95 of
50.911 ms in M12. The ColBERT run encoded 662 distinct passages in
129.651 s and stored 171,070 token vectors using 87.6 MB, with 436.9 MB of
model files. Its process reached 1.73 GB peak working set. Qdrant loaded the
vectors in 1.178 s and matched all 24 NumPy rankings with a maximum absolute
score error of 0.00000316. This compares local Python Qdrant with NumPy;
the local result does not measure the Qdrant server. The cross-encoder
process reached 1.04 GB peak working set. The deterministic graph built
28,849 passage nodes, 84 filing nodes and 196 issuer-topic links in 8.533 s
and reached 889 MB peak working set. No provider calls were made.

**Decision**. Keep dense as the default. Retain the measured graph ranking
improvements and direct ColBERT MaxSim as opt-in research methods. Keep
the Qdrant implementation for parity measurements and the P1 cross-encoder
for comparison. The held-out full-coverage and provenance results justify
another cohort before replacing the working default. Keep annual column
pairing for source inspection where the title, units and ordered fiscal
columns are explicit.

## Reproduce

Source commit `c3d93459a63c290589cae95715844e743bf7692c` passed 343 tests
with 3 skips, compilation and Git whitespace checks. The cached ColBERT
replay reproduced all 24 rankings for each tested backend.

| Local report | SHA-256 |
| --- | --- |
| `m14-r6.json` | `7850fb86bf4104d65e5e746301624bd1d6c196eff8939d044854e7a7925b4081` |
| `m14-colbert.json` | `a6a9d29a9c03da04e0d5c58969bdb033e9dbe5359f7699484e3e02da837277db` |
| `m14-cross-encoder.json` | `47f63695fcbbc097920868d3eb80fdc743d85ae48d5b022587134133e2307923` |
| `m14-graphs.json` | `60ce597bf0ad9d70c29ee253aa5c6900f8a35648d1ee5f6304eef5ac3013b97f` |

The reranking runners use the verified M12 rankings. The ColBERT model
directory contains the six files from the pinned model revision. The runner
checks their SHA-256 digests. The first ColBERT run stores a local vector
checkpoint for subsequent MaxSim or Qdrant replays.

```powershell
$env:HF_HUB_DISABLE_XET = '1'
@'
from huggingface_hub import snapshot_download
from scripts.run_late_interaction_retrieval import COLBERT_FILES, COLBERT_MODEL, COLBERT_REVISION, DEFAULT_MODEL

snapshot_download(COLBERT_MODEL, revision=COLBERT_REVISION, local_dir=DEFAULT_MODEL, allow_patterns=list(COLBERT_FILES))
'@ | uv run --with fastembed==0.9.1 --with psutil==7.2.2 python -
```

```powershell
uv run --offline --with psutil==7.2.2 python -m scripts.run_context_expansion --output data/financebench/advanced_runs/m14-r6.json
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OPENBLAS_NUM_THREADS = '6'
uv run --offline --with fastembed==0.9.1 --with psutil==7.2.2 python -m scripts.run_late_interaction_retrieval --backend colbert --threads 6 --output data/financebench/advanced_runs/m14-colbert.json
uv run --offline --with psutil==7.2.2 python -m scripts.run_late_interaction_retrieval --backend cross-encoder --threads 6 --output data/financebench/advanced_runs/m14-cross-encoder.json
uv run --offline --with psutil==7.2.2 python -m scripts.run_late_interaction_retrieval --backend graphs --output data/financebench/advanced_runs/m14-graphs.json
```
