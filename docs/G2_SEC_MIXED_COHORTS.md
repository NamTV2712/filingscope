# G2 mixed SEC cohorts

## Evaluation protocol

The 32/100/72 case SEC cohorts currently contain only lookup questions.
Build a separate mixed benchmark on the same issuer-disjoint membership
and pinned 2025 filings. Keep the legacy lookup-only artifacts available.
Use 32 pilot, 100 development and 72 validation cases. Require all
eight roadmap categories across the three cohorts. Require every cohort
to include lookup, quarter/YTD, multi-period, multi-company, hard
negative, narrative and unanswerable cases. Measure revision coverage
only where the frozen sources establish an amendment relationship.

Generate numeric references from unique Inline XBRL values before
checking Company Facts. Pin every required observation and any distractor
by issuer, accession, interval and source locator. Keep distinct fiscal
periods visible in multi-company questions. For negative controls, limit
the requested scope to the named filing and its reported units or the
known amendment. Check narrative excerpts against the actual archive
member and record their author review separately from automated labels.
Exclude reviewer-held material.

Keep the new cohorts if two offline builds produce identical case files,
cross-cohort issuer, accession, revision-family and observation overlap
is zero, and every category has an explicit source and scoring contract.
Compare the same matched Company Facts lookups for each numeric slot.
Report structured diagnostic outcomes separately from the previous PDF
and hybrid QA arms. Report resource use and category-specific failures.

## Cases and source checks

`--mixed-cohorts` builds 204 provisional cases from the original 17
filings and eight issuer groups. The default mode still produces the
lookup-only benchmark. Each case binds the filing date, accession,
CIK, archive and extraction hashes, and applicable revision family.
Each numeric reference preserves its exact interval, consolidated USD
basis, fact IDs and SEC anchor URLs. Every multi-company question
specifies each issuer's own as-of date and accession.

| Category | Pilot | Development | Validation | Total |
| --- | ---: | ---: | ---: | ---: |
| Lookup | 12 | 46 | 29 | 87 |
| Quarter/YTD | 4 | 12 | 10 | 26 |
| Multi-period | 4 | 18 | 10 | 32 |
| Multi-company | 4 | 6 | 6 | 16 |
| Hard negative | 4 | 12 | 10 | 26 |
| Narrative | 2 | 3 | 3 | 8 |
| Revision | 0 | 0 | 1 | 1 |
| Unanswerable | 2 | 3 | 3 | 8 |
| Total | 32 | 100 | 72 | 204 |

Quarter/YTD cases require different starts and the same fiscal end.
Annual comparisons require adjacent fiscal years. Hard negatives include
an anchored dimensioned fact with a different amount for the same
issuer, concept, interval and unit. Examples include segment operating
income and asset values scoped to a subgroup. Unanswerable cases ask
for EUR operating income in the frozen extract and record the available
USD observation as a distractor. Their labels describe the extract's
contents. The validation revision case checks the items Tesla's 10-K/A
explicitly amended. It measures filing scope. Positive numeric
restatement coverage is pending.

The eight narrative answers and Tesla revision answer are author-checked
against the cited HTML excerpts. The remaining 195 labels use the
extracted iXBRL facts. Both issuers in a multi-company case belong to
the same cohort. Across cohorts, CIKs, accessions, filing URLs, archive
and extraction hashes, revision families, and required and distractor
fact IDs and URLs were disjoint. These are development-exposed cases.
[Frozen SEC filings](G2_SEC_CORPUS_MANIFEST.json) ·
[Tesla amendment](https://www.sec.gov/Archives/edgar/data/1318605/000110465925042659/tm252787d2_10ka.htm).

## Results

| Measure | Pilot | Development | Validation |
| --- | ---: | ---: | ---: |
| Legacy lookup exact | 32/32 | 100/100 | 72/72 |
| Mixed lookup exact on shared cases | 12/12 | 46/46 | 29/29 |
| Mixed exact numeric structured lookup | 28/28 | 94/94 | 65/65 |
| Correct missing-unit abstentions | 2/2 | 3/3 | 3/3 |
| Incorrect structured releases | 0/28 | 0/94 | 0/65 |
| Narrative and revision cases excluded from numeric lookup | 2 | 3 | 4 |

Exactness requires all numeric slots in a case to match. Company Facts
was queried by accession, concept, currency and full interval. Selection
and labels reproduced with every Company Facts observation removed.
The structured diagnostic supplies the requested identities directly.
Its agreement measures consistency across SEC representations. The
document-only and hybrid QA arms have been run on the separate PDF
pilot. On the mixed cohorts, those arms, narrative predictions, context
precision, citation support and claim faithfulness remain unmeasured.
[PDF pilot](G2_RUNTIME_REPLAY.md) · [Narrative pilot](G2_SEC_NARRATIVE.md).

## Reproduction and decision

```text
python -m scripts.run_sec_ixbrl_evaluation --corpus .local/g2/verified-replay --cache .local/g2/sec-cache --mixed-cohorts --output .local/g2/mixed-cohorts-final
```

Both offline builds produced byte-identical case files. The canonical
case hashes exclude platform newline differences. The output also binds
the frozen input manifest. The default evaluation reproduced the three
legacy cohort files, all 7,162 comparison rows and their structured
results. One mixed replay used 1.32 s wall time and peaked at 290,349,056
bytes. Provider calls, billed tokens and spend were zero. Windows passed
536 tests with three skips. WSL passed 535 with four. Ruff, focused mypy
and deterministic claim and citation checks passed. Baseline commit `c8495e7`.

| Local artifact | Canonical case SHA-256 |
| --- | --- |
| [Pilot](../.local/g2/mixed-cohorts-final/pilot.json) | `9b15c9c564dd500da8029fcea95d6ec9b12a944b205d476ceda797526c97285b` |
| [Development](../.local/g2/mixed-cohorts-final/development.json) | `400a885d20761a189eb81c00e875d791f2fd650b38f42b6d82374ee2035c1bf6` |
| [Validation](../.local/g2/mixed-cohorts-final/validation.json) | `82db2c40dcdff67f67775a5d5c2ec63bb78f82d517966682f68f814f30744840` |

**KEEP** the mixed development benchmark and deterministic provenance
checks. **DEFER** mixed document and hybrid QA claims pending broader
source indexing and answer adjudication. Independent final evaluation
still requires the G6 reviewer bundle.
