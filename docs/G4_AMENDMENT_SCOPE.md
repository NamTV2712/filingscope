# G4 annual filing amendment scope

## Evaluation protocol

Baseline `9bdf22c` withholds the Tesla amendment-scope question in the
204-case mixed replay. Test whether the document path can answer from
the explanatory note of the exact SEC amendment. Verify the named
issuer, CIK, form, accession and locator before accepting the note.
Require the full amended part and numbered item list. Items that the
original filing omitted or that appear elsewhere in the amendment
need explicit support from the note before they can enter the answer.

Compare paired document-only, Company Facts-only and hybrid outcomes
on the same frozen source snapshots and questions. Review the released
claims and numbered citations against the SEC HTML. Require the eight
earlier narrative results, 585 numeric and missing-unit outcomes and
PDF-pilot and historical results to match. Check wrong issuers, forms,
accessions and locators, conflicting scope, incomplete assertions and
irrelevant citations. Record timing, retrieval work and provider use.
The exposed amendment question measures an internal regression.

## Implementation and source review

The corpus-aware planner selects 10-K/A documents for the accession-bound
question. Evidence coverage requires the exact SEC accession and a CIK
consistent with the locator. The deterministic writer states the items,
and the atomic verifier checks the complete part and list against every
numbered citation. The existing evidence-control plane handles release.

The cited block is HTML block 13, zero-based, in Tesla's April 2025
amendment. The explanatory note says the amendment addresses Part III,
Items 10 through 14 of the original Form 10-K. The note discusses new
certifications under Part IV, Item 15 separately. The released claim
contains the requested Part III items. [Tesla Form 10-K/A](https://www.sec.gov/Archives/edgar/data/1318605/000110465925042659/tm252787d2_10ka.htm).

Codex reviewed the nine narrative and amendment cases against frozen
SEC text and the actual numbered citations. The review carries forward
eight byte-matched outputs and their reviewed citations in each
document-enabled arm. It adds the Tesla note and judges every unique
HTML block among the first ten original ranks. A block counts as relevant
when it identifies a requested name in its reporting scope or gives an
explicit statement of the amended items. An exact claim requires the
complete list. This evaluation is **PROVISIONAL_NOT_INDEPENDENT**.

| Measure on nine cases | Document-only | Company Facts-only | Hybrid |
| --- | ---: | ---: | ---: |
| Grounded exact and answer coverage | 8/9 → 9/9 | 0/9 → 0/9 | 8/9 → 9/9 |
| False abstentions | 1/9 → 0/9 | 9/9 → 9/9 | 1/9 → 0/9 |
| Gold HTML-block recall at 10 | 8/9 → 9/9 | — | 8/9 → 9/9 |
| Context Precision@10 | 21/78 → 22/88 | — | 21/78 → 22/88 |
| Citation support and claim faithfulness | 8/8 → 9/9 each | — | 8/8 → 9/9 each |
| Incorrect or unsupported releases | 0/8 → 0/9 | — | 0/8 → 0/9 |
| Tool calls | 8 → 9 | 0 → 0 | 8 → 9 |
| Evidence tokens | 6,208 → 6,250 | 0 → 0 | 6,208 → 6,250 |
| Warm p50/p95, ms | 75.06/84.12 → 74.52/107.83 | 5.64/8.77 → 6.02/6.94 | 73.26/83.26 → 83.30/92.13 |

The amendment contributes one relevant block at rank five across ten
returned blocks. The other eight rankings match. Numeric exactness
is inapplicable to this source review. The descriptive Wilson 95%
upper risk bound is 29.91% on nine releases, with two questions about
the same issuer. The 5% risk target remains inconclusive.

On all 204 questions, coverage rose to 39/204 for document-only
and 196/204 for hybrid. Company Facts-only retained 187/204. Numeric
confirmations remained 30/187 for document-only and 187/187 for both
structured arms. Each arm withheld all eight missing-unit controls.
All 609 other arm/case records matched after excluding timing.
The candidate run took 23.87 s and peaked at 1,771,499,520 bytes.
Hosted calls, billed tokens and USD spend were zero.

## Verification and reproduction

Windows passed 582 tests with three fixture skips. Linux WSL passed
581 tests with four fixture skips. Deterministic claim and citation
checks, Ruff, configured mypy and the offline lock check passed.
The broader type check on the touched runtime modules reproduced
the same 15 findings on baseline and candidate.
All 122 PDF-pilot outcomes and the historical architecture and fault
outcomes matched apart from resource measurements. The new controls
exercise wrong filing identity, a misleading omission, an incomplete
list, a conflicting scope and an extraneous reference.

**KEEP** the accession-bound amendment check. Its measured scope is one
amendment question. Questions asking for a broader explanation, an
accession-free lookup or a note outside the supported format still
require additional evaluation.

```text
python -m scripts.run_sec_mixed_runtime --manifest .local/g2/verified-replay/manifest.json --cache .local/g2/sec-cache --cohorts .local/g2/mixed-cohorts-final --output .local/g4/amendment-scope-final --threads 10 --reuse-vectors .local/g2/mixed-runtime-full
python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --reuse-pilot-vectors .local/g3/inline-runtime-full --narrative-controls --inline-facts .local/g2/verified-replay/facts --output .local/g4/amendment-scope-pilot
python -m scripts.run_specialist_architectures --faults --output .local/g4/amendment-scope-historical.json --manifest .local/g4/amendment-scope-historical-manifest.json
```

| Local artifact | SHA-256 |
| --- | --- |
| [Mixed replay](../.local/g4/amendment-scope-final/report.json) | `3b11dbffe3c562980ab94ca1feb2c92116dda7da8464f84080ed3812d5a7cd47` |
| [Per-case source and retrieval review](../.local/g4/amendment-scope-source-review.json) | `5130964e801b1bf82c341a97b23bc78f8713cd34c243b137f1f4e9a1c391b0c8` |
| [PDF pilot](../.local/g4/amendment-scope-pilot/report.json) | `ef7f64a3e417cccf17c085407d5413d3a649a95ff9299b6c3ddc20e6dc8b568a` |
| [Historical architecture](../.local/g4/amendment-scope-historical.json) | `7ea5626f4b9f3e3aea01fe34d7e46709a45e803a02007207d9f8377f1eff08b0` |
