# G2 selected SEC current reports

## Evaluation protocol

The G2 corpus verified periodic filings and a 10-K/A. Use the existing
EDGAR and Inline XBRL pipeline to measure 8-K current reports separately.
Select the most recent 2025 Item 2.02 filing for Apple, NVIDIA and
Tesla from the frozen Submissions snapshots, with at most one archive
per issuer. Record each accession, primary document, archive hash,
observation count and anchored fact identity. Item 2.02 identifies
results-of-operations disclosures. Inspect whether the primary report
tags the financial figures or carries them in a separate exhibit.

Keep the existing corpus defaults if selection and offline replay pass.
Replay the same three accessions with networking disabled and require
identical manifests and fact hashes. Record any missing archive, empty
numeric result or reported filing identity mismatch. Keep current
reports outside the periodic QA cohorts and compare any usable numeric
observations only with equivalent Company Facts observations. Run the
offline suite and preserve the existing periodic corpus manifest.

## Results

| Issuer | Item 2.02 accession | Filed | Primary numeric iXBRL observations | Exhibit 99.1 |
| --- | --- | --- | ---: | --- |
| Apple | `0000320193-25-000077` | 2025-10-30 | 0 | HTML financial tables |
| NVIDIA | `0001045810-25-000228` | 2025-11-19 | 0 | HTML financial tables |
| Tesla | `0001628280-25-045861` | 2025-10-22 | 0 | Image references in HTML |

All three primary documents parsed. Arelle counted 43, 22 and 22
non-numeric cover-page observations, respectively. The archive HTML
members contained zero `ix:nonFraction` tags. The Apple and NVIDIA
results appear in HTML exhibits linked from the respective primary
documents. Tesla's exhibit references images whose bytes are absent
from this XBRL archive. An image-based extraction for that exhibit
would require separate acquisition and validation.
[SEC EDGAR API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) ·
[Form 8-K instructions](https://www.sec.gov/about/forms/form8-k.pdf).

No same-accession numeric comparison was possible. A separate check
read the following six cells from Exhibit 99.1 and matched each USD
amount against the original 10-K or 10-Q accession in the pinned
Company Facts snapshot. Table and data-column numbers are zero-based.
The data column counts populated numeric cells and skips currency
symbols. This measures cross-filing agreement on the same period and
consolidated metric.

| Exhibit | Table and data column | Exact interval | Periodic accession | Revenue, operating income, net income (USD millions) |
| --- | --- | --- | --- | --- |
| Apple `a8-kex991q4202509272025.htm` | 0, 2 | 2024-09-29 to 2025-09-27 | `0000320193-25-000079` | 416,161 · 133,050 · 112,010 |
| NVIDIA `q3fy26pr.htm` | 3, 0 | 2025-07-28 to 2025-10-26 | `0001045810-25-000230` | 57,006 · 36,010 · 31,910 |

Apple net sales maps to `RevenueFromContractWithCustomerExcludingAssessedTax`.
NVIDIA revenue maps to `Revenues`. Both use `OperatingIncomeLoss` and
`NetIncomeLoss` for the income measures. [Apple exhibit](https://www.sec.gov/Archives/edgar/data/320193/000032019325000077/a8-kex991q4202509272025.htm) ·
[NVIDIA exhibit](https://www.sec.gov/Archives/edgar/data/1045810/000104581025000228/q3fy26pr.htm) ·
[Tesla exhibit](https://www.sec.gov/Archives/edgar/data/1318605/000162828025045861/exhibit991.htm).

## Reproduction and decision

```text
python -m scripts.run_sec_ixbrl_corpus --issuer AAPL=320193 --issuer NVDA=1045810 --issuer TSLA=1318605 --form 8-K --current-report-item 2.02 --cutoff 2025-12-31 --cache .local/g2/sec-cache --output .local/g2/current-reports-replay
```

The selection uses frozen Submissions snapshots. The first run used
`--acquire` and made three SEC requests for the archives. It took
11.46 s and peaked at 100,249,600 bytes. The offline run took 0.70 s,
peaked at 93,806,592 bytes, and reproduced the manifest and all three
fact artifacts byte for byte. The [current-report manifest](G2_SEC_CURRENT_REPORTS_MANIFEST.json)
has SHA-256 `9cfe3676c353e93766d63933f2aad6461bd96edf03736d88a2c0a7a420c6bbaa`.
The original 17-filing periodic manifest also reproduced byte for byte,
with all 20,723 observations. Provider calls, billed tokens and cost
were zero. Windows offline passed 535 tests with 3 skips. WSL passed
534 with 4 skips. Ruff, focused mypy and the deterministic claim
and citation check passed.

**KEEP** optional EDGAR item selection and source receipts for current
reports. **DEFER** 8-K exhibit answer release and OCR until exhibit
provenance and extraction are separately verified. The result leaves
the periodic QA cohorts and evidence release policy as before.
Baseline commit `23ba6f2`.
