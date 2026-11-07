# FinanceBench Dataset Protocol

## Scope and attribution

P1 uses the **public 150-case FinanceBench open-source sample** from Patronus
AI. It does not use or claim results for the full 10,231-case collection. The
dataset card identifies the sample as CC BY-NC 4.0; retain Patronus AI
attribution and use the benchmark only under that license. The financial
reports are original source documents linked by the dataset; the dataset
license is not assumed to grant rights over those reports.

Pinned references:

- FinanceBench dataset card and revision:
  [PatronusAI/financebench](https://huggingface.co/datasets/PatronusAI/financebench)
  at `e04404e3a97f69f79c14d42f24981a1c9c3bcd18`.
- Public source files and PDFs:
  [patronus-ai/financebench](https://github.com/patronus-ai/financebench)
  at `cc39aeb4afdf33909ee1412188bf89035950c2eb`.
- License text: [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).

The acquisition script downloads the two JSONL source files and only the PDFs
referenced by the 150 cases. It checks each downloaded file against the pinned
Git blob SHA and byte size, and checks PDF magic bytes. It writes a local
`data/financebench/source_manifest.json` with revisions, hashes, coverage and
metadata conflicts. Raw data, PDFs, extracted text, embeddings, indexes and run
outputs stay under the git-ignored `data/` directory.

```powershell
python -m scripts.download_financebench
```

## Source coverage and metadata

The sample refers to 84 distinct source PDFs. The document metadata file has
361 rows and repeated `doc_name` values. Rows are merged by document while all
conflicting values are retained. The pinned snapshot includes one reporting
period conflict for `FOOTLOCKER_2023_annualreport` (periods 2022 and 2023); the
ingestion metadata keeps both periods and marks the conflict instead of
choosing one. The local source manifest is the acquisition record for the
remaining source details.

FinanceBench evidence page numbers are zero-based. PDF extraction uses pypdf
7.0.0 layout mode with fontTools 4.68.0 available for CFF Type1 font encoding,
whitespace-only vertical rows removed, and every page index preserved.
Repeated horizontal whitespace is collapsed before token chunking to prevent
layout padding from creating abnormally long model inputs. Text is chunked
within each page into 450-token chunks with 75-token overlap. Every chunk
retains its `doc_name`, company, document type, reporting periods, source URL,
page number, and stable chunk ID. Citations display a human-readable one-based PDF page,
while evaluation compares zero-based source indices.

pypdf is BSD-3-Clause licensed and supports layout-oriented extraction through
`page.extract_text(extraction_mode="layout")`. It does not perform OCR. A page
with no extracted text remains in the page inventory and is not grounds for
dropping a question. The benchmark records nonempty-page and evidence-text
overlap diagnostics separately from retrieval scores.

## Eligibility and evidence alignment

Eligibility is decided before retrieval results are inspected. A case is
eligible when its case-referenced source PDF is present and every gold evidence
page index is within that PDF's page count. A valid page with empty extracted
text stays eligible and can count as a retrieval miss. Cases are excluded only
for an unavailable source PDF or an out-of-range evidence page; the runner
records the case IDs and reason.

The evaluator separately compares FinanceBench's full-page evidence text with
the extracted text using token overlap. This measures parser alignment only;
it does not change eligibility, seed the retrieval corpus, or promote a
retrieved page. Evidence snippets, gold answers and justifications never enter
the embedded page corpus. The retrieval runner receives only the question and
the frozen corpus; the evaluator reads evidence labels after retrieval to score
the ranked result IDs.

## Company-grouped splits

All cases for one company stay in a single split to prevent company/document
overlap across development and final evaluation. The split seed is
`filingscope-financebench-company-split-v1`. A deterministic SHA-256 ordering
of company names drives exact subset-sum assignment: 60 cases to development,
45 to validation, and 45 to held-out evaluation. If the pinned sample cannot
form those exact company-grouped counts, the loader fails instead of silently
changing the split.

The split algorithm and source revisions are part of the checked-in protocol;
case IDs and labels remain in the ignored local dataset files.
