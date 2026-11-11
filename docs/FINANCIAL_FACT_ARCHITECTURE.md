# Financial fact architecture

## Status

M9 replaces the first Company Facts selector with
`src/ingestion/company_facts.py`. The resolver binds each payload to the
requested CIK and selects facts from a versioned US GAAP and IFRS concept
registry. It returns a reason when a fact remains unknown.
Source commit `aad24377da2075ccb6e1c4d55106dc480c6309e5`.

## Candidate fact record

Structured evidence and its linked ledger fact retain:

- entity: CIK, ticker, canonical company;
- concept: taxonomy, namespace, tag, label, and resolution method;
- value and unit: raw value, normalized Decimal, unit/currency, scale;
- period: instant vs duration, start/end/as-of, fiscal year/period;
- provenance: form, filing date, accession, source URL, source revision;
- revision history for the selected concept, currency and date interval,
  with the original and selected accessions and the resolution policy version.

Concept and tag mappings must be auditable. Never silently merge different
concepts, units, fiscal periods, dimensions, accessions, or restated and
as-reported values. Derived facts must reference all input evidence IDs and
store operation, formula, rounding policy, and validation status.

## Source evaluation

Start from official SEC [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
for submissions and Company Facts. Compare a narrow optional EdgarTools adapter
only if the official JSON path leaves important filing-specific facts or
taxonomy context unavailable. Any client must identify itself and observe SEC
access guidance. Tests should use saved, license-compatible fixtures; live
requests are opt-in.

## Selection policy

- The resolver uses the filing's fiscal focus together with actual dates.
  SEC Submissions report dates take precedence where available. Historical
  rows without those dates use filing form, interval length and bounded
  filing lag. Full years, discrete quarters and instant balances have
  separate rules. Q4 duration facts require an explicit short interval
  ending at the verified annual boundary.
- The original filing anchors the interval. The default `AS_REPORTED`
  policy selects the first eligible original. `LATEST` considers later
  observations for the exact concept, currency and interval and records
  whether the value is unchanged, amended or changed in a comparative
  filing. A changed comparative value can reflect a presentation change or
  a formal restatement. Competing same-day values remain unknown.
- Tag drift is supported for individual lookups through reviewed historical
  tags. Arithmetic requires compatible concept, currency, duration and
  revision provenance. Calculations cannot fill one operand from a filing
  excerpt and the other from an unreconciled structured fact. The evidence
  analyst compares agreeing filing and SEC amounts at their common scale and
  reports disagreements as conflicts.
- Monetary units normalize to the supported ISO currency codes. Explicit
  currency requests require matching evidence. Competing currencies stay
  unknown without a specified currency. Company Facts covers standard
  entity-wide facts. Custom tags, segments, foreign exchange conversion,
  transition periods outside the date rules, and reconstructed quarterly
  cash flow from year-to-date rows require separate evidence.

The graph routes explicit revision requests to RESEARCH. A request for a
changed value needs a changed observation and uses only resolved SEC evidence.
The report cites the filing index and labels the selected revision basis.
The SEC worker reserves Company Facts calls for the remaining issuers before
spending a call on optional report-date metadata.

## Validation

The offline suite uses Company Facts shaped subsets reconstructed from public
filings. It checks six Apple slots and two Microsoft slots against their
published values and original accessions. The replay invokes the earlier
`StructuredFinancialDataWorker._records_for_task` from `6dc25ff` on the
same Apple fixture and eight ineligible rows. The fixture order places the
six-month net sales observation before the three-month row, matching the
tie the previous selector failed to resolve. [Apple FY2024 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm) · [Apple FY2023 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm) · [Apple Q2 FY2024 10-Q](https://www.sec.gov/Archives/edgar/data/320193/000032019324000069/aapl-20240330.htm) · [Apple Q2 FY2023 10-Q](https://www.sec.gov/Archives/edgar/data/320193/000032019323000064/aapl-20230401.htm) · [Microsoft FY2024 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/msft-20240630.htm)

| Outcome | M8 selector | M9 resolver |
|---|---:|---:|
| Apple value and accession exact | 5/6 | 6/6 |
| Ineligible period or period type accepted | 5/5 | 0/5 |
| Ineligible form, amendment without original, or missing accession accepted | 3/3 | 0/3 |

The M9 resolver also matched both Microsoft slots and rejected the
mismatched CIK fixture. Apple Q2 FY2024 changed from the six-month
`210,328,000,000` to the discrete-quarter `90,753,000,000` USD value.
Synthetic cases cover revision conflicts, currencies, taxonomy, tag drift
and optional report dates. These results measure the selected fact slots.
Run `uv run python -m pytest tests/test_company_facts.py tests/test_specialist_graph.py tests/test_sec_client.py -q`.
The full regression suite passed with 303 tests and 3 skips.

The official Company Facts API supplies the runtime payload. EdgarTools
documents a richer lookup and filing API, including restatement inspection.
M9 uses the existing SEC client and keeps fiscal and revision policy explicit
in FilingScope. [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) · [SEC XBRL filing guide](https://www.sec.gov/files/edgar/filer-information/specifications/xbrl-guide.pdf) · [EdgarTools Company Facts](https://edgartools.readthedocs.io/en/latest/guides/company-facts/)
