# M12 Financial Hard-Negative Retrieval

## Cohort and controls

M12 tests whether ranking favors evidence from the requested company, period,
metric, disclosure, and revision. The benchmark has 24 authored questions
with 30 positive and 35 hard-negative passage judgments from 20 annual,
quarterly, and earnings-release documents. There are eight cases in each of
development, validation, and held-out. Each judged document belongs to one
split. All variants search the same full P1 corpus of 28,849 chunks from
84 documents. The holdout is for the frozen M12 judgments. Some source
documents also appear in earlier FinanceBench evaluations.

Seven non-held-out M2 misses identified failure neighborhoods in Amcor, MGM
Resorts, and Best Buy disclosures. The M12 questions and judgments were
authored from the filing passages and frozen before scoring. The cohort also
includes Boeing, Nike, General Mills, and Corning. Source and candidate keys
use the original document, zero-based physical page, and chunk index.
The loader checks the pinned P1 index identity, content fingerprint, source
URLs and audited text anchors before ranking. The output preserves the
provenance of each judgment.

| Hard-negative type | Passage judgments | Example |
|---|---:|---|
| Wrong company | 6 | A peer's total current assets in the same period |
| Wrong period | 9 | A prior fiscal-year cash flow statement |
| Wrong metric | 7 | Operating cash flow for a question about investing cash flow |
| Wrong disclosure | 8 | The same revenue in a segment note or unaudited earnings release when the question requires the audited statement |
| Wrong revision | 5 | Original Best Buy FY2017 non-GAAP operating income versus the FY2019 recast |

The Best Buy FY2017 original and recast non-GAAP operating income are
$1,759 million and $1,733 million. For General Mills, FY2020 North America
Retail net sales were $10,750.5 million in the original filing and $10,978.1
million under the FY2022 segment presentation. These are company-described
presentation changes. Revision questions may require multiple chunks for the
amount, table header, and stated revision basis.

FinRank motivated measuring global retrieval separately from pairwise
discrimination against curated distractors. The authors release their dataset
under CC BY-NC 4.0. Fin-RATE's MIT-labeled data card and paper describe
within-disclosure, cross-company, and longitudinal questions. M12 uses local
P1 passages and FilingScope's authored labels with no new dataset or runtime
dependency. [FinRank paper](https://arxiv.org/abs/2608.07400) · [FinRank release](https://github.com/datanxt/FinRank) · [Fin-RATE paper](https://arxiv.org/abs/2602.07294) · [Fin-RATE data card](https://huggingface.co/datasets/GGLabYale/Fin-RATE)

## Ranking and scoring

Dense uses the frozen P1 Nomic vectors with exhaustive cosine similarity.
BM25 uses the existing FilingScope tokenizer and rank-bm25 over the same
chunks. The third variant masks dense scores using explicit company, year,
and form cues from the query and values present in corpus metadata. All
variants compute scores from the question and corpus. Judgments apply after
scoring. Equal scores in the global ranking use chunk ID order.

Recall and coverage use exact required passage IDs. Recall@50 measures
candidate recall. Full evidence coverage@10 requires every labeled positive.
The pairwise metric compares each required positive with every labeled
distractor for the same question, awarding half credit for a tie. It reports
excluded positives separately for the metadata variant. A seeded sample of
other-company chunks, equal in size to each curated negative set, provides a
random control. Unjudged passages can include valid alternative evidence.

## Results

| Metric | Dense | BM25 | Dense with query metadata |
|---|---:|---:|---:|
| Recall@5 | 0.4792 | 0.1181 | 0.5833 |
| Recall@10 | 0.5625 | 0.2153 | 0.7083 |
| Candidate Recall@50 | 0.8472 | 0.5069 | 0.9306 |
| Full evidence coverage@10 | 13/24 | 3/24 | 16/24 |
| MRR@10 | 0.3529 | 0.1067 | 0.4945 |
| nDCG@5 | 0.3757 | 0.0774 | 0.4976 |
| Cases with a known negative in top 10 | 9/24 | 0/24 | 5/24 |
| Known negative before all gold in top 50 | 3/24 | 0/24 | 1/24 |
| Curated pairwise accuracy | 35/42 | 37/42 | 35/40 |
| Random-control pairwise accuracy | 42/42 | 41/42 | 40/40 |
| Rank latency p50 / p95 | 39.757 / 50.911 ms | 125.279 / 167.633 ms | 46.461 / 58.387 ms |

Dense timings include query embedding and cosine ranking on CPU. Metadata
timing adds the question-derived mask and filtered ranking to the shared
dense time. Setup took 11.608 s and the combined benchmark process reached
2.42 GB peak Windows working set. No provider calls were made. This ranking
replay does not measure Qdrant service latency or answer generation.

| Split | Dense Recall@10 | BM25 Recall@10 | Dense with query metadata Recall@10 |
|---|---:|---:|---:|
| Development | 0.6875 | 0.1875 | 0.8750 |
| Validation | 0.2500 | 0.3333 | 0.5000 |
| Held-out | 0.7500 | 0.1250 | 0.7500 |

| Curated pair | Dense wins / evaluated | BM25 wins / evaluated | Dense with query metadata wins / evaluated |
|---|---:|---:|---:|
| Wrong company | 5/6 | 5/6 | 6/6 |
| Wrong period | 8/9 | 8/9 | 9/9 |
| Wrong metric | 10/10 | 10/10 | 10/10 |
| Wrong disclosure | 7/8 | 7/8 | 5/6 |
| Wrong revision | 5/9 | 7/9 | 5/9 |

On the Best Buy balance-sheet question, the July 29, 2023 calendar date was
used as a filing fiscal-year filter. The correct FY2024 Q2 chunk was excluded,
along with its two hard-negative comparisons and two random comparisons.
The masked run still ranked Boeing's same-value segment note first for a
question that specified the consolidated statement of operations. BM25's
higher curated pairwise accuracy occurred alongside lower global coverage.
Dense won every random control and lost seven curated comparisons, including
four revision comparisons.

**Decision**. Keep unfiltered dense as the baseline. Retain the metadata mask
as an offline experiment because its overall gain came from development and
validation and it excluded one correct passage. The 24 targeted questions
measure these specific provenance confusions. The judgments do not cover
every relevant passage or estimate full-corpus false-positive rates.

Source `b9d53ed7424d5837386a69c0355543c28a12df33` passed 335 tests with
3 skips. Compilation and Git whitespace checks passed. The report SHA-256
is `db0ee70e6239aa5ce5896b3a3199d3b0666ecac78dd89e41fff7641fa283af74`.

## Reproduce

Use the completed P1 run, the pinned Nomic model cache, and the existing
project environment. The optional Windows `psutil` overlay measures peak
working set for the benchmark process.

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:OPENBLAS_NUM_THREADS = '6'
uv run --offline --with psutil==7.2.2 python -m scripts.run_hard_negative_retrieval --threads 6 --output data/financebench/hard_negative_runs/m12-results.json
```

Pass `--labels-only` to check the corpus fingerprint, anchors, and split
boundaries without loading the embedding vectors or running ranking.
