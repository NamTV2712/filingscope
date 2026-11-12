# M10 Document Intelligence

## Cohort and controls

The experiment uses ten development and validation questions whose evidence
pages were absent from the original P1 dense top 10. The five source PDFs
cover annual reports, a quarterly report, an 8-K and an earnings release.
The cohort contains 226 complete pages across Amcor, MGM Resorts, Best Buy
and Nike. The source PDF SHA-256 hashes and question IDs are frozen in
`configs/document_intelligence.py`. Retrieval searches all 226 pages.
The selected pages and expected table cells are used only for offline scoring.
The source run is P1 retrieval run
`3ea92c895826e46ccf03ee52248771cc83e779e90b1660c390d29f2c4abfd18f`.

The dense comparison holds the pinned Nomic embedding model, questions,
source documents, cosine ranking and top-k scoring constant. It varies the
parser and chunk representation. The first two variants use the existing
450-token page chunker with 75 tokens of overlap. The structured variant
keeps section headings and table IDs, attaches native header spans to row
values, and keeps each chunk on its source page. This is a failure-focused
subset. Its within-subset scores use a smaller candidate corpus than P1.

## Parser fidelity and cost

| Full-corpus measurement | pypdf layout | Docling ACCURATE |
|---|---:|---:|
| Physical page indexes preserved | 226/226 | 226/226 |
| Text or table blocks omitted for ambiguous page provenance | unavailable | 0 |
| Evidence records with nonempty page text | 12/12 | 12/12 |
| Mean full-page token overlap | 0.9920 | 0.9738 |
| Median full-page token overlap | 1.0000 | 0.9763 |
| Reading order anchor sequences | 5/5 | 5/5 |
| Complete value sequences in audited text rows | 6/6 | 6/6 |
| Audited rows recovered in a native table grid | unavailable | 6/6 |
| Expected header-to-value associations in native grid | unavailable | 20/20 |
| Parse seconds | 8.205 | 424.444 |
| Peak Windows working set | 97.2 MB | 3,795.8 MB |
| Serialized output | 1.28 MB | 3.84 MB |

Reading order checks use ordered anchors on five visually inspected physical
pages. The table checks cover six rows across four of those pages, including
three- versus six- or twelve-month headers and a parenthesized negative
amount. Native grid scores require the row labels, exact ordered amounts and
physical column spans. pypdf preserved all six text rows in layout mode.
The token overlap metric measures recovery of unique tokens from the
FinanceBench full-page reference. It does not measure extra text or its
placement.

On matched one-page slices of the five audit documents, FAST and ACCURATE
each recovered 6/6 native rows and 20/20 header associations. FAST took
11.658 s and ACCURATE took 13.706 s, including first model initialization.
The peak working sets were 1,194.7 MB and 1,182.3 MB. FAST was measured
on those five pages. All PDFs used embedded text with OCR disabled.

Docling 2.150.0 used Docling Core 2.106.0, Docling Parse 7.25.0,
Docling IBM Models 4.0.4 and PyTorch 2.15.0 CPU with six threads on an
Intel Core i7-14650HX running Windows. The isolated
environment occupies 1.206 GB and the downloaded model directory 701.2 MB,
including the alternate ONNX layout weights. Heron plus the active
TableFormer weights occupy 384.4 MB for ACCURATE and 317.1 MB for FAST.
Parse timings cover extraction and materialization, while memory reports
the maximum working set of each parser process. Model download time is
outside parse time. [Docling options](https://docling-project.github.io/docling/usage/advanced_options/) · [Docling document format](https://docling-project.github.io/docling/concepts/docling_document/)

## Dense retrieval results

| Metric | pypdf layout | Docling ACCURATE page text | Docling ACCURATE structured chunks |
|---|---:|---:|---:|
| Chunks | 565 | 605 | 1,254 |
| Chunk embedding seconds | 140.493 | 252.096 | 230.139 |
| Recall@5 | 0.50 | 0.50 | 0.50 |
| Recall@10 | 0.50 | 0.60 | 0.55 |
| Recall@50 | 0.90 | 0.90 | 0.90 |
| All evidence pages retrieved at 10 | 5/10 | 6/10 | 5/10 |
| MRR@10 | 0.1567 | 0.4444 | 0.3726 |
| nDCG@5 | 0.2405 | 0.4500 | 0.3931 |
| Development Recall@10, 5 cases | 0.80 | 1.00 | 0.90 |
| Validation Recall@10, 5 cases | 0.20 | 0.20 | 0.20 |
| Validation MRR@10, 5 cases | 0.0667 | 0.2000 | 0.2000 |

The index cutoff counts chunks and recall counts distinct gold pages. In
both Docling variants, the validation evidence that surfaced moved up in
rank. The gain in Recall@10 came from development. All three variants
reached the same Recall@50. Embedding times are single CPU runs and exclude
query encoding. The structured variant uses more, shorter chunks and the
reported wall time includes batching and CPU scheduling effects.

Keep pypdf as the default. Docling ACCURATE page text recovered one
additional complete evidence set, with a 52× parse time and a 39× peak
working set on these files. Structure-aware chunking more than doubled the
baseline chunk count and matched its complete evidence count. The optional
adapter and native header provenance are available for further experiments.
The measured changes describe ten selected cases. Held-out evidence recall,
answer accuracy, and full-corpus performance remain unmeasured.

Source commit `1d08a0079aaee5991c5a13e1db6fd6b4365d03ed` passed the full
suite with 306 tests and 3 skips. Python compilation and the staged Git
whitespace check also passed. The local result JSON has SHA-256
`e31c36b5a1170b82a839caf03f3969a04c78a655a0471abc5040e10c1c5cf6f7`.

## Reproduce

Use Python 3.12 with a separate virtual environment for Docling so the
project's pinned Transformers version stays available for Nomic.

```powershell
$runs = 'data/financebench/parser_runs'
uv venv --python 3.12 "$runs/m10-venv"
$parserPython = "$runs/m10-venv/Scripts/python.exe"
uv pip install --python $parserPython --torch-backend cpu docling==2.150.0 docling-core==2.106.0 docling-parse==7.25.0 docling-ibm-models==4.0.4 torch==2.15.0 pypdf==7.0.0 fonttools==4.68.0 tiktoken==0.13.0 psutil==7.2.2
& "$runs/m10-venv/Scripts/docling-tools.exe" models download --output-dir "$runs/m10-models" layout tableformer
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
& $parserPython -m scripts.parse_document_intelligence --parser pypdf --output-dir "$runs/m10-pypdf"
& $parserPython -m scripts.parse_document_intelligence --parser accurate --threads 6 --artifacts "$runs/m10-models" --output-dir "$runs/m10-accurate"
& $parserPython -m scripts.parse_document_intelligence --parser accurate --threads 6 --artifacts "$runs/m10-models" --output-dir "$runs/m10-accurate-audit" --audit-only
& $parserPython -m scripts.parse_document_intelligence --parser fast --threads 6 --artifacts "$runs/m10-models" --output-dir "$runs/m10-fast-audit" --audit-only
uv run python -m scripts.evaluate_document_intelligence --pypdf "$runs/m10-pypdf" --accurate "$runs/m10-accurate" --accurate-audit "$runs/m10-accurate-audit" --fast-audit "$runs/m10-fast-audit" --threads 6 --output "$runs/m10-results.json"
```

The run used Heron snapshot
`8f39ad3c0b4c58e9c2d2c84a38465abf757272d8` and TableFormer snapshot
`fc0f2d45e2218ea24bce5045f58a389aed16dc23`. Parser checkpoints store
the package versions, model SHA-256 hashes and input document hash.
Select individual source PDFs with the parser command's `--document`
option. The full evaluation expects all five documents. Raw parser and
benchmark outputs stay under the ignored local run directory.
