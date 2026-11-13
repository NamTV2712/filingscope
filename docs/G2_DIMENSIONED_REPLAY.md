# G2 dimensioned iXBRL replay

The SEC pilot withheld Tesla's energy generation and storage revenue
after the reporting-scope guard was added. Test whether the frozen
iXBRL extract supplies the missing observation when the caller supplies
the exact requested financial identity. Compare with Company Facts
and the PDF-transcribed controls. This is a source capability test.
Question interpretation and runtime release need separate validation.

Before scoring, fix the CIK, accession, concept, context interval,
unit, axis, member and filing revision for every request. Use exact
matching, require a unique value and retain the source anchor. Run
same-value wrong-axis, wrong-member, wrong-period, wrong-unit and
amendment controls. Keep the existing release guard and test that
the historical architecture scores reproduce.

## Results

The replay resolved all **10/10** PDF-transcribed cells across four
issuers and withheld every result in **50/50** identity perturbations.
Each source carries its SEC filing accession and the exact iXBRL anchor.
Apple Services has two matching anchors with the same normalized value.
The unit test also verifies that conflicting duplicates, a mismatched
identity hash and a mismatched source URL prevent resolution.

| Filing | PDF controls | iXBRL exact | Company Facts dimension availability |
| --- | ---: | ---: | ---: |
| Tesla FY2024 10-K | 3 | 3 | 0 |
| Walmart FY2025 10-K | 3 | 3 | 0 |
| NVIDIA FY2025 10-K | 2 | 2 | 0 |
| Apple FY2025 10-K | 2 | 2 | 0 |

Tesla's segment revenue was USD 10,086 million. Its product-or-service
axis also reported USD 9,564 million in sales and USD 522 million in
leasing. The replay requires the exact member and axis before looking
at the values. It retains the entity-wide Company Facts counterpart
for context. [Tesla segment fact](https://www.sec.gov/Archives/edgar/data/1318605/000162828025003063/tsla-20241231.htm#f-1636).

The run took 184 ms with a peak process working set of 607,215,616 B,
including loaded evaluation dependencies. It used zero provider calls
and USD 0. This is a provisional lookup result with supplied
identities. The graph still needs to resolve user language to a
dimension identity and verify it through the ledger and writer.
All three iXBRL tests passed. The full Windows offline suite passed
475 tests with three missing local fixtures skipped.

```text
uv run --offline --locked python -m scripts.run_g2_dimensioned_replay --facts .local/g2/verified-replay/facts --pages .local/g3/statement-normalization-pilot/pages.jsonl --cache .local/g2/sec-cache --output .local/g2/dimensioned-replay-new.json
```

**KEEP** exact dimension identity and matching anchor checks.
**DEFER** runtime integration until dimension-aware routing and
verification are measured on a wider cohort. The
[replay report](../.local/g2/dimensioned-replay.json) has SHA-256
`82ddf4674db50c0888efef5f5de87b8f797c5b058f1517c1c0880bbe45f296fa`.
Baseline commit `bf29d96`.
