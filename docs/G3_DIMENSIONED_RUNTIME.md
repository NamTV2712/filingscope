# G3 dimensioned revenue runtime

## Objective and protocol

The frozen SEC pilot had one answerable case withheld by all arms.
Add an optional Inline XBRL source for Tesla FY2024 energy generation
and storage segment revenue. The acceptance checks require agreement
with the PDF-transcribed amount, zero unsupported releases and matching
answers, dispositions and citation locators on the other 25 questions.
The three existing inventories retain their original labels.

The pilot contains 26 questions across four issuers and five filings.
Tesla's PDF reference is `TSLA_2024_10K#p39` and records USD 10,086
million. The optional arm accepts the separately verified Inline XBRL
locator `ixbrl:sha256:c9adbdf3a1adac1ba0c5a6040bbb8af2f9807150fa13e8b4b44d710434c8e88c`
for the same claim. The parser resolves `us-gaap:Revenues` with the
business-segment axis and Tesla's energy generation and storage member.
The fact spans 2024-01-01 through 2024-12-31 in USD and links to the
original accession `0001628280-25-003063`. [SEC filing fact](https://www.sec.gov/Archives/edgar/data/1318605/000162828025003063/tsla-20241231.htm#f-1636).

The pilot status remains `PROVISIONAL_NOT_INDEPENDENT`. The target
case was known during implementation. The paired run reused the
statement-normalization run's hash-checked document vectors and matched
its gold, page, chunk, embedding and Company Facts receipts. The frozen
gold SHA-256 remained `44f0c295511c23bff75a3b65ab76f8a9f467a9da2d07249b92bae6714b2b8f53`.
The Inline XBRL extraction was checked against the existing G2 manifest.

## Implementation and verification

`src/ingestion/segment_revenue.py` loads the hash-pinned extract with the
existing exact iXBRL resolver. The FAST router and structured specialist
admit a single supported Tesla lookup. The ledger retains the fact hash,
taxonomy, accession, dimension, dates, unit and SEC anchor. The coverage
analyzer and atomic verifier check source provenance and require the claim
to state the segment, issuer and year. The graph uses its existing
deterministic release policy. The pilot enables the source via
`--inline-facts`. The normal default source inventory remains unchanged.

Regression checks cover extract hash and anchor validation, ledger
serialization, public citations, wrong issuer, period, unit, form,
accession and revision, qualified or consolidated claims, and tool budget
exhaustion. Focused tests passed 40/40. The offline suite passed 499 with
3 local fixture skips on Windows and 498 with 4 on Linux WSL. The claim
fixture achieved 100% disposition and claim-status accuracy on both.
Ruff, focused mypy, compileall and the tracked-secret scan passed.
The historical architecture replay matched stable results across M13,
direct facts, complex tasks, narrative, serial and fault controls.

## Paired results

| Source inventory | Grounded and numeric exact | Coverage | Incorrect or unsupported releases | False abstentions | Warm p50 / p95 | Total tools |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| PDF only | 22/23 | 22/26 | 0/22 | 1/23 | 14.55 / 206.45 ms | 33 |
| Company Facts only | 21/23 | 21/26 | 0/21 | 2/23 | 14.06 / 22.24 ms | 26 |
| Hybrid | 22/23 | 22/26 | 0/22 | 1/23 | 14.18 / 202.39 ms | 41 |
| Hybrid with Inline XBRL | 23/23 | 23/26 | 0/23 | 0/23 | 12.82 / 198.90 ms | 41 |

The Tesla case changed from abstention with one PDF retrieval to a
verified answer with one local fact lookup. Its measured request latency
was 89.84 → 12.10 ms. The three unanswerable cases still abstained.
Citation-locator support was 25/25 for hybrid and 26/26 for hybrid with
iXBRL. Mean unranked required-source coverage rose from 95.65% to 100%.
Ranked context precision and recall at ten, and human-adjudicated
faithfulness and citation support, were not measured in this replay.
The Wilson 95% upper bound for 0 errors in 23 releases is 14.31%.

Total evidence tokens were 2,835 for hybrid and 2,868 with iXBRL.
Model calls, billed tokens and API spend were zero. Peak working set
was 1,890,930,688 bytes for the whole paired process. Timing and RAM
are single-run measurements on the Windows CPU environment.

## Decision and reproduction

**KEEP** the optional source for the validated accession and segment.
**DEFER** broad segment support pending coverage of additional issuers,
dimensions, and query forms. Company Facts alone still withholds the
conflicting Walmart revenue observations. Live Jev and independent
reviewer scoring retain their separate blockers.

Run with the G0 offline CPU environment, G2 pinned downloads and the
fact exports from `scripts.run_sec_ixbrl_corpus`. The CLI regenerates the
document embeddings. The paired receipt reused the prior normalized
vectors to hold their bytes fixed.

```text
python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --inline-facts .local/g2/verified-replay/facts --output .local/g3/inline-runtime
python -m scripts.run_specialist_architectures --faults --output .local/g3/dimensioned-historical.json --manifest .local/g3/dimensioned-historical-manifest.json
python -m scripts.run_offline_checks
```

Baseline Git commit `4e93619`. The paired report is under
`.local/g3/inline-runtime-paired/report.json` with SHA-256
`bd27073ec653102ad1da8e25c352e8042a7f230364ad74f92d6142101e3fd70d`.
