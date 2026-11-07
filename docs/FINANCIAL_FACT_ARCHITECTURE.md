# Financial fact architecture

## Status

The repository has financial table extraction and deterministic arithmetic,
but no SEC XBRL fact client, resolver, or shared financial fact model. Missing
facts must remain `UNKNOWN`; absence from an API response is not a false value.

## Candidate fact record

The M7/M9 design should preserve at least:

- entity: CIK, ticker, canonical company;
- concept: taxonomy, namespace, tag, label, and resolution method;
- value and unit: raw value, normalized Decimal, unit/currency, scale;
- period: instant vs duration, start/end/as-of, fiscal year/period;
- provenance: form, filing date, accession, source URL, source revision;
- context: dimensions/segment, statement/table, filing amendment, reported vs
  restated status, parser/source version.

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

## M7/M9 acceptance

Test company/CIK resolution, standard and custom tags, tag drift, taxonomy,
instant vs duration, fiscal calendar, unit/currency conversion, accession
selection, amendments, missing facts, and restatement conflicts. Report fact
coverage and wrong-period/wrong-entity false acceptance separately from answer
accuracy. Use `Decimal` for financial operations.
