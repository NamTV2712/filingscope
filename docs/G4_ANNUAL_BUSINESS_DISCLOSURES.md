# G4 accession-bound annual business disclosures

## Evaluation protocol

Baseline `508dbbe` withheld all eight business disclosure questions
in the frozen mixed replay. Measure a bounded extension of the existing
segment-list verifier against those same questions and source snapshots.
Require the named issuer, annual form and exact accession, or the
existing fiscal year for legacy questions. Verify complete lists and
the requested reporting scope, including the named business within
a parent issuer's filing. Treat lines of business as their own disclosure.

Before comparing, inspect the frozen excerpts and cite the actual
released source blocks. Compare names and scope against the frozen
author references and record outcomes with unreviewed or missing support.
Keep an improvement only with no incorrect releases, wrong-filing
support or scope reversals. Recheck malformed lists, conflicting sources,
issuer collisions and sentence-local prompt injection. Replay all 204
questions, the PDF pilot, and historical architecture and fault controls.
Report releases, abstentions, reference excerpt retrieval, timing and
resource use. The mixed excerpts are development-exposed.

## Implementation

The existing segment verifier now accepts complete, explicit lists from
annual filings with an exact accession. The evidence check matches the
issuer, form and metadata accession to the SEC locator. The prior fiscal
year path remains available. Source-specific statements include an
exhaustive list with no stated count, a counted list of lines of business,
and a list for a named business within an issuer's filing. The writer
preserves the requested scope, and the atomic verifier checks the entire
list and every cited source before release. Dense ranking gives complete
disclosures priority within its existing bounded candidate pool.

## Source review and matched results

Codex reviewed each answer and its numbered citation against the frozen
SEC HTML after both runs. The review checked the complete entity-scoped
list, CIK, form, accession and the text of the cited block. Source files,
references and per-arm predictions retain their hashes. The review uses
the G1 scoring contract and is `PROVISIONAL_NOT_INDEPENDENT`.

| Measure on nine narrative and revision questions | Document-only | Company Facts-only | Hybrid |
| --- | ---: | ---: | ---: |
| Reviewed grounded exact and answer coverage | 0/9 → 8/9 | 0/9 → 0/9 | 0/9 → 8/9 |
| Reviewed false abstentions | 9/9 → 1/9 | 9/9 → 9/9 | 9/9 → 1/9 |
| Reviewed gold HTML-block recall at 10 | 6/9 → 8/9 | — | 6/9 → 8/9 |
| Reviewed citation support and claim faithfulness | — → 8/8 each | — | — → 8/8 each |
| Reviewed incorrect releases | — → 0/8 | — | — → 0/8 |
| Tool calls | 8 → 8 | 0 → 0 | 8 → 8 |
| Evidence tokens | 0 → 6,208 | 0 → 0 | 0 → 6,208 |
| Warm latency p50/p95, ms | 63.22/102.05 → 75.06/84.12 | 8.17/10.95 → 5.65/8.77 | 61.75/99.03 → 73.26/83.26 |

Seven numbered citations contain the frozen reference excerpt. Walmart
cites another block of the same 10-K with the same three reportable
segments. Alphabet cites the two Google businesses and preserves the
scope of the question. Coca-Cola lists concentrate and finished product
operations as lines of business. [Walmart 10-K](https://www.sec.gov/Archives/edgar/data/104169/000010416925000021/wmt-20250131.htm) · [Alphabet 10-K](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm) · [Coca-Cola 10-K](https://www.sec.gov/Archives/edgar/data/21344/000002134425000011/ko-20241231.htm).

All 585 numeric and missing-unit arm/case outcomes matched the baseline,
including 187/187 confirmed numeric releases in each structured arm,
30/187 in document-only and 8/8 missing-unit abstentions in every arm.
The hybrid arm released 195/204 cases across the mixed cohort. The
reported narrative risk has a descriptive Wilson 95% upper bound of
32.44% on eight releases. Full Context Precision@10 awaits judgments
on every returned block. Numeric exactness is inapplicable to the nine
reviewed disclosure questions. Tesla's amendment question remains
withheld in all arms.

The replay took 22.09 s and peaked at 1,770,635,264 bytes. Hosted model
calls, billed tokens and spend were zero. Latency is descriptive on
this host.

## Regression and reproduction

Windows passed 571 tests with three missing-corpus skips. WSL passed
570 with four. Ruff, focused mypy, the offline lock and deterministic
claim and citation checks passed. All 122 stable PDF-pilot outcomes
and the historical architecture and fault outcomes matched.

**KEEP** accession-bound lists and the existing evidence-control
authority. The labeled evaluation remains internal. Amendment scope is
the remaining case on this mixed narrative set.

```text
python -m scripts.run_sec_mixed_runtime --manifest .local/g2/verified-replay/manifest.json --cache .local/g2/sec-cache --cohorts .local/g2/mixed-cohorts-final --output .local/g4/annual-disclosures --threads 10 --reuse-vectors .local/g2/mixed-runtime-full
python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --reuse-pilot-vectors .local/g3/inline-runtime-full --narrative-controls --inline-facts .local/g2/verified-replay/facts --output .local/g4/annual-disclosures-pilot
python -m scripts.run_specialist_architectures --faults --output .local/g4/annual-disclosures-historical.json --manifest .local/g4/annual-disclosures-historical-manifest.json
```

| Artifact | SHA-256 |
| --- | --- |
| [Mixed replay](../.local/g4/annual-disclosures/report.json) | `3188da3ceca92d89efb2580eb76e23b5d5dd188d240907ee504e988b7b6c4720` |
| [Per-case source review](../.local/g4/annual-disclosures-source-review.json) | `b2051f29592869323e54173aa0a987ec581b0447445db79c3db7dd288ef4a83d` |
| [PDF pilot](../.local/g4/annual-disclosures-pilot/report.json) | `8a90c45f2ac9aa6fb256a93c23063ac67b32304292e2e0e041c638709f328493` |
| [Historical architecture](../.local/g4/annual-disclosures-historical.json) | `c9a56857f0c6f845947d71723cb9a46830a13c3272517a076f9373f5ebd4e78c` |
