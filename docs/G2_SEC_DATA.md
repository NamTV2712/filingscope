# G2 SEC data, Inline XBRL and benchmark cohorts

## Objective and predeclared checks

Test whether primary Inline XBRL filings preserve source identities and
segment facts beyond the entity-wide Company Facts API. Keep the existing
Company Facts and PDF paths as controls. Compare only like-for-like
company, concept, period, unit and accession records. Disagreements stay
visible. Record unknown revision relationships explicitly.

The acquisition must use official SEC URLs, bound each transfer and
verify cached content on replay. Parser fixtures must cover standard and
extension concepts, instant and duration, explicit and typed dimensions,
scaled and signed amounts, compound units, and source identity
mismatches. Require successful extraction from a real 10-K and 10-Q.
Compare matched values with Company Facts and a filing PDF where
available. Run the G1 offline suite and historical regression checks.

New pilot, development and validation cases must be auditable by case
ID, source and label origin. Check issuer, accession, source observation
and revision-family overlap between cohorts before interpreting results.
Reviewer-held final material stays outside development.

## Implementation and evidence

The existing SEC client now supports bounded, streamed transfers from
official hosts with one transient retry. The corpus command caches
Submissions, Company Facts and accession-specific XBRL archives by SHA-256.
It pins the selected date window, filing metadata and extracted facts in
one manifest. The optional `ixbrl` dependency locks Arelle 2.47.4. The
parser opens archives offline, preserves the namespace-qualified concept,
context CIK and interval, compound units, segment/scenario dimensions,
accession and revision status, and records the exact source anchor,
raw displayed amount, decimals and scale. Typed dimension XML is preserved
in canonical form. The adapter retains duplicate observations and treats
conflicting values separately. The existing ledger, candidate policy,
Company Facts runtime and PDF retriever remain the baseline.
[SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
[SEC fair access](https://www.sec.gov/about/webmaster-frequently-asked-questions),
[Arelle Python API](https://arelle.readthedocs.io/en/latest/apidocs/arelle/arelle.api.Session.html).

The 2025-01-01 through 2025-12-31 filing window yielded 17 filings from
eight issuers. Eight are 10-K, eight are 10-Q and one is a Tesla 10-K/A.
The corpus includes fiscal periods that ended before 2025 and were filed
during 2025. The Tesla amendment was linked to the unique original
10-K for the same CIK and report date. Its two numeric observations
do not establish a financial restatement. Comparative or recast
observations keep their separate accession. Confirmed restatement
classification requires explicit filing evidence. The CLI can request
10-Q/A and 8-K archives. The measured selection had no 10-Q/A, and
8-K was outside the frozen run.

### Parser comparison

| Measurement | Result |
| --- | ---: |
| Numeric observations and distinct identity keys | 20,723 / 18,800 |
| Observations with dimensions, including typed dimensions | 10,285, including 24 typed |
| Observations with exact source anchors | 20,723/20,723 |
| Company Facts comparison groups, consolidated US-GAAP USD | 7,162 |
| Exact agreement on unique-value pairs | 7,087/7,087 |
| Multiple-value groups kept out of exact agreement | 67 |
| Inline groups without a Company Facts match | 8 |
| Apple FY2025 PDF cells agreeing with both structured sources | 6/6 |

The exact denominator matches CIK, US-GAAP tag, accession, full interval
and USD. The inputs share EDGAR provenance. On Apple's unrecognized
tax benefits, rounded narrative values and precise table values produce
multiple observations under the same identity. G2 exposes these groups
for reconciliation. It does not choose the most favorable match.

Arelle logs missing references when the archive omits standard taxonomy
schemas from the offline cache. The command extracts numeric observations
and records diagnostics. It does not certify DTS validation. It skipped
2,829 nonnumeric or nil facts and 81 unsupported/invalid numeric
transforms. The remaining limitations include extra target instances,
other SEC entity schemes and full XBRL validation. Source URLs and
archives remain available to inspect omitted cases.

The PDF check uses pypdf page 0 from the publisher's consolidated
statements PDF and the twelve-month column ending 2025-09-27. It
compares net sales, gross margin, R&D, operating income, pretax income
and net income with the Apple 10-K iXBRL accession and Company Facts.
This is a six-cell document parsing control. OCR and Docling were
unnecessary for the measured page.
[Apple 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm),
[Apple FY2025 statements PDF](https://www.apple.com/newsroom/pdfs/fy2025-q4/FY25_Q4_Consolidated_Financial_Statements.pdf).

## Benchmark compatibility

| Dataset and pinned release | License and evidence | G2 use |
| --- | --- | --- |
| FinanceBench open sample, existing P1 pin `e04404e3a97f69f79c14d42f24981a1c9c3bcd18` | CC BY-NC 4.0. Public 150 questions, source PDFs and page labels. | Existing adapter and historical regression. Earlier filing vintages can share issuers with G2. [Dataset](https://huggingface.co/datasets/PatronusAI/financebench). |
| FinAgent Benchmark v1.1.1, `b048668cdd21bf8e7f9a6fec4b770ec44bdb8440` | MIT. 133 cases with filing issuer/form metadata, gold answer, excerpt and tool annotations. Upstream corrected 50 rows across v1.1 and v1.1.1. | Second adapter. 35/133 had a matching issuer/form in the frozen SEC corpus. 10/133 had one exact normalized excerpt match. Full public answer evaluation is deferred until accession and evidence coverage are resolved. [Pinned release](https://huggingface.co/datasets/finagent-benchmark/finagent-benchmark/tree/b048668cdd21bf8e7f9a6fec4b770ec44bdb8440). |
| DocFinQA, `64ebaff62f692495bcc182f45cf9a9606251b19b` | MIT dataset card. Full SEC report text and FinQA question/program/answer ancestry. The public row schema lacks filing page locators. | Long-context reasoning candidate. Cases can overlap FinQA by construction. [Dataset](https://huggingface.co/datasets/kensho/DocFinQA). |
| FinQA, `0f16e2867befa6840783e58be38c9efb9229d742` | MIT repo. Report text/table excerpts, supporting entries and executable programs. | Targeted numeric reasoning candidate. Shared ancestry with DocFinQA. [Release](https://github.com/czyssrs/FinQA/tree/0f16e2867befa6840783e58be38c9efb9229d742). |
| TAT-QA, `870accc41953dcde885aabeb963d94aabdc0fbc3` | MIT repo. Financial-report tables and passages, scale and derivation labels. | Targeted table/text arithmetic candidate. Exact issuer/document overlap with G2 remains unmeasured. [Release](https://github.com/NExTplusplus/TAT-QA/tree/870accc41953dcde885aabeb963d94aabdc0fbc3). |

The FinAgent result is a source-alignment audit. Exact normalized
excerpt overlap neither proves citation entailment nor supports a
question-answer accuracy claim. All public sets remain outside the
provisional G2 cohorts.

## Cohorts and leakage

The generated cases use fixed US-GAAP metrics, explicit accession,
full period and USD. The label comes from unique inline values selected
independently of Company Facts availability. The Company Facts result
is an identity-matched lookup diagnostic. Cases remain `AUTO_XBRL`
and `PROVISIONAL_NOT_INDEPENDENT`. The final G6 reviewer protocol will
require `REVIEWER_HELD` labels. This milestone has no external
`HUMAN_VERIFIED` or `REVIEWER_HELD` cohort.

| Cohort | Issuer group | Cases | Structured-only exact / released |
| --- | --- | ---: | ---: |
| Pilot | AAPL, AMZN | 32 | 32/32 / 32 |
| Development | GOOG, KO, MSFT | 100 | 100/100 / 100 |
| Validation | NVDA, TSLA, WMT | 72 | 72/72 / 72 |
| Independent final | Reviewer-held group pending | 0 | NOT_RUN |

The validator checks disjoint case IDs, CIKs, accessions, revision
families, fact IDs and evidence URLs across these three cohorts.
The auto-XBRL cohorts contain single-issuer lookups. A subsequent
26-case pilot compares document-only, Company Facts-only and hybrid
QA with PDF-transcribed labels. It covers quarterly/YTD, multi-period,
multi-issuer, revision and unanswerable controls. All three configurations
released consolidated Tesla revenue in response to a segment question.
Independently reviewed narrative evaluation, page relevance and strict
atomic claim/citation adjudication remain open. [Runtime pilot](G2_RUNTIME_REPLAY.md).
An [author-checked narrative track](G2_SEC_NARRATIVE.md) measures six
non-XBRL questions separately on the same filing corpus.

## Regression and resources

The G1 baseline and G2 candidate match stable fields in the
architecture, retrieval and writer reports. M13 routed remains
21/21 grounded, with 21/24 coverage, 0/21 false abstentions and
0/21 incorrect releases. The 33-case natural statement replay remains
30/30 grounded and 0/30 incorrect releases. M12 Dense Recall@10 stays
56.25%, and the nine writer gates passed.

Windows with the optional parser passed 442 tests with 3 fixture skips.
Linux WSL passed 439 tests with 6 skips before installing the extra,
then passed both dedicated parser tests. Ruff, focused mypy, lock
checks and the tracked-file scan passed. The updated workflow was
exercised locally.

| Measurement | G1 baseline | G2 candidate |
| --- | ---: | ---: |
| Routed M13 warm p50 / p95 | 12.18 / 166.75 ms | 18.46 / 213.40 ms |
| Natural statement warm p50 / p95 | 14.45 / 113.81 ms | 16.66 / 127.81 ms |
| Architecture replay peak process memory | 2,007,244,800 B | 2,009,751,552 B |
| Natural statement tool calls / embedding calls | 38 / 14 | 38 / 14 |

The first successful acquisition took 33.07 s, with 30 HTTP attempts
after an exploratory cache fill. Offline extraction repeated in
12.69 s at 259,809,280 B peak. It reproduced the entire manifest
byte for byte and made zero HTTP requests. The Company Facts
comparison ran in 0.45 s with about 217 MB peak. The PDF comparison
took 421 ms. Timing samples were single runs. The runtime does not
load Arelle by default. Provider calls, billed tokens and cost were zero.

## Reproduction and decision

Use the G0 locked CPU environment. The `--acquire` flag explicitly
enables bounded SEC traffic and uses the configured SEC contact.
Keep the frozen cache and use fresh output paths on replay.

```text
uv sync --locked --extra ixbrl
uv run --offline --locked --extra ixbrl python -m scripts.run_sec_ixbrl_corpus --issuer AAPL=320193 --issuer AMZN=1018724 --issuer GOOG=1652044 --issuer KO=21344 --issuer MSFT=789019 --issuer NVDA=1045810 --issuer TSLA=1318605 --issuer WMT=104169 --form 10-K --form 10-Q --form 10-K/A --form 10-Q/A --cutoff 2025-12-31 --cache .local/g2/sec-cache --output .local/g2/new-replay
uv run --offline --locked --extra ixbrl python -m scripts.run_sec_ixbrl_evaluation --corpus .local/g2/new-replay --cache .local/g2/sec-cache --output .local/g2/new-evaluation
uv run --offline --locked --extra ixbrl python -m scripts.compare_sec_statement_pdf --pdf .local/g2/apple-fy25-statements.pdf --comparison .local/g2/new-evaluation/comparison.json --output .local/g2/new-evaluation/pdf-comparison.json
uv run --offline --locked --extra ixbrl python -m scripts.audit_finagent_overlap --dataset .local/g2/finagent-v1.1.1.json --manifest .local/g2/new-replay/manifest.json --cache .local/g2/sec-cache --output .local/g2/new-evaluation/finagent-overlap.json
```

Frozen corpus SHA-256 is
`e83b3df4910e5572e81535a5c72e8a5c6011e83e4e11e56ba1bb0b6e61ea3e9f`.
The [frozen manifest](G2_SEC_CORPUS_MANIFEST.json) lists SEC URLs and
receipt hashes. Reacquiring the mutable submissions and Company Facts
endpoints may produce a new snapshot. The exact replay requires
the original content-addressed cache.

**KEEP** the offline numeric extraction and accession-matched comparison.
**EXPERIMENT** with the new provisional cohorts. **DEFER** full taxonomy
validation, adjudicated mixed cohorts and replacing production Company
Facts. G2 is **PARTIALLY_COMPLETE** on the benchmark breadth and
independent review requirements. The engineering regression gate passed.
G3 can use the existing historical replay and these provisional data
controls without reviewer-held labels.

The G2 baseline was local `main` at `560cbbc`. The three pre-existing
independent/FinRank script changes remain outside this milestone.
