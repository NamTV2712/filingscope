# D3 filing-bound revenue cells

The disclosure reader retains the annual header, physical row and column,
table title, row label, subtotal group, accession and unit declaration locator.
Repeated oil/gas/NGL labels are assigned to a subtotal only when their sum
matches every reported year column. Conflicting or missing units, non-annual
forms and source identity mismatches withhold those cells.

Devon's FY2024 table on PDF index 55 has two commodity groups. The first
belongs to oil, gas and NGL sales. The second belongs to marketing and
midstream revenues. The original public question 'DVN current sales split by
commodity?' produced verified oil USD 9,368,000,000, gas USD 398,000,000 and
NGL USD 1,410,000,000 in both Adaptive and routed paths. Every claim cited the
same table page. The PDF's explicit global USD-million declaration is at
index 2 and is retained as the unit source. [Devon filing](https://www.sec.gov/Archives/edgar/data/1090012/000095017025022844/dvn-20241231.htm)

The publisher's oil reference remains USD 9,268 million. Source-reviewed
correctness uses the filed USD 9,368 million. Raw outputs are under
`data/independent-final/finrank-2025/d3-smoke.json`; this is a development
smoke and the final public score retains the full 130-question denominator.

The implementation extends the existing scoped ranker and evidence analyst.
Metadata contributes to evidence/fact identity only when populated, retaining
legacy identities. The ordinary annual statement reader remains available.
Tests cover the normal graph entry point, repeated rows, changed subtotals,
column ordering, wrong accession/CIK, units, and legacy identity preservation.

```powershell
python -m pytest -q tests/test_filing_tables.py tests/test_evidence_ledger.py
```
