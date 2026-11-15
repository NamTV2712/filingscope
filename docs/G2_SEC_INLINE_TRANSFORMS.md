# G2 SEC Inline XBRL transformations

## Protocol

The 17-filing baseline has 20,723 numeric observations and skips 81
numeric `ixt-sec:numwordsen` entries. The locked Arelle wheel includes
the standard XBRL transform registries. The SEC extension is separately
distributed. Evaluate the official SEC plugin at a pinned Git revision
against the same cached filings. Run the parser with network access
disabled after staging the verified plugin files.

Require recovery of all 81 named observations with exact sign, scale,
unit, context and source anchor. Require every existing observation to
match byte for byte and preserve the original replay when the optional
plugin is absent. Report taxonomy-loading diagnostics separately.
Run the Company Facts and PDF comparisons and measure changes in
applicability, runtime, memory and cost. Test malformed inputs and
fail closed on mismatched plugin files. [SEC transformation rules](https://www.sec.gov/files/edgar/filermanual/efmvol2.pdf) ·
[Arelle 2.47.4 transforms documentation](https://arelle.readthedocs.io/en/2.47.4/plugins/popular/transforms_sec.html).

## Implementation

`scripts/run_sec_ixbrl_corpus.py --sec-transforms PATH` loads the SEC
extension through Arelle's custom transformation registry.
`src/ingestion/inline_xbrl.py` stages two verified files in a temporary
directory, disables network access and persistent Arelle configuration
for the run, checks that `numwordsen` registered and records the plugin
revision and file hashes in the manifest. `tests/test_inline_xbrl.py`
covers scaling a signed word amount, rejecting malformed input and
rejecting changed plugin bytes before load.
[Pinned EDGAR release 26.3 source](https://github.com/Arelle/EDGAR/commit/4891c4c9889c77af247428ceff4fa7cc52d534ea).

## Paired results

The replay used the same 17 primary Inline XBRL documents, Company Facts
snapshots and Apple PDF as the G2 baseline. The baseline manifest
reproduced byte for byte. Both plugin runs produced identical manifests
and fact payloads across all 17 filings. Every one of the 20,723 existing
observation payloads matched. Codex checked all 81 additions against the
archived XML by accession, source ID, context, unit, scale, sign and
literal English value. The additions spanned 14 filings and included
seven zeros spelled `No`, `no` or `none` and five USD observations.

| Measure | Baseline | SEC transforms |
| --- | ---: | ---: |
| Numeric observations | 20,723 | 20,804 |
| Invalid or unsupported numeric transforms | 81 | 0 |
| Nonnumeric transformation diagnostics | 514 | 0 |
| Consolidated US-GAAP USD comparison groups | 7,162 | 7,166 |
| Exact unique-value Company Facts pairs | 7,087/7,087 | 7,088/7,088 |
| Multiple-value groups | 67 | 67 |
| Groups missing a Company Facts counterpart | 8 | 11 |
| Apple FY2025 PDF cells with exact agreement | 6/6 | 6/6 |
| Auto-XBRL lookup matches | 204/204 | 204/204 |
| Total extraction time across filings | 11.052 s | 12.765 s |
| Corpus command wall time | 11.840 s | 13.463 s |
| Peak process memory | 258,400,256 B | 267,669,504 B |
| Extraction HTTP requests, provider calls, billed tokens and cost | 0 | 0 |

Four new comparison groups are Microsoft goodwill impairment disclosures
of USD 0. The annual observation agrees with Company Facts. The dated
2023, 2024 and 2025 test observations have no matched counterparts.
A recovered commercial paper zero adds a source anchor to an existing
group. The cases and membership of the 32/100/72 auto-XBRL splits match
the baseline. Their corpus manifest hash changes.
[Microsoft FY2025 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm).

Arelle still reports 110 `IOerror` diagnostics and 21,644
`ix11.12.1.2:missingReferences` diagnostics. Full taxonomy validation
remains unmeasured. The second plugin run took 16.761 s wall time and
15.962 s for extraction, with 266,366,976 B peak under concurrent local
checks. These are single-run
resource samples. This extraction experiment does not generate answers,
so claim faithfulness, incorrect release and false abstention are outside
its measured outcomes.

## Reproduction and decision

Use the locked G2 environment and the original verified SEC cache from
the [G2 replay](G2_SEC_DATA.md#reproduction-and-decision). Obtain the two
files in `.local/g2/sec-transform-plugin/transform` from the pinned
revision. The CLI verifies their SHA-256 hashes on load.

| File | SHA-256 |
| --- | --- |
| `__init__.py` | `2296586f945ffd95ab37d3d4147c4e45f42ce4e5f397f61143e053208adefbf1` |
| `text2num.py` | `6c9b26354320a2fb34fe380cdc71ff7f8d1cc712811e6b10c661e512f0383409` |

```powershell
$transformDir = '.local/g2/sec-transform-plugin/transform'
$transformSource = 'https://raw.githubusercontent.com/Arelle/EDGAR/4891c4c9889c77af247428ceff4fa7cc52d534ea/transform'
New-Item -ItemType Directory -Force -Path $transformDir | Out-Null
foreach ($transformFile in '__init__.py', 'text2num.py') {
    Invoke-WebRequest "$transformSource/$transformFile" -OutFile (Join-Path $transformDir $transformFile)
}
uv run --offline --locked --extra ixbrl python -m scripts.run_sec_ixbrl_corpus --issuer AAPL=320193 --issuer AMZN=1018724 --issuer GOOG=1652044 --issuer KO=21344 --issuer MSFT=789019 --issuer NVDA=1045810 --issuer TSLA=1318605 --issuer WMT=104169 --form 10-K --form 10-Q --form 10-K/A --form 10-Q/A --cutoff 2025-12-31 --cache .local/g2/sec-cache --sec-transforms $transformDir --output .local/g2/sec-transforms-candidate
uv run --offline --locked --extra ixbrl python -m scripts.run_sec_ixbrl_evaluation --corpus .local/g2/sec-transforms-candidate --cache .local/g2/sec-cache --output .local/g2/sec-transforms-evaluation
uv run --offline --locked --extra ixbrl python -m scripts.compare_sec_statement_pdf --pdf .local/g2/apple-fy25-statements.pdf --comparison .local/g2/sec-transforms-evaluation/comparison.json --output .local/g2/sec-transforms-evaluation/pdf-comparison.json
```

| Artifact | SHA-256 |
| --- | --- |
| [Original manifest](G2_SEC_CORPUS_MANIFEST.json) | `e83b3df4910e5572e81535a5c72e8a5c6011e83e4e11e56ba1bb0b6e61ea3e9f` |
| [Plugin replay manifest](../.local/g2/sec-transforms-candidate/manifest.json) | `20847adeaa35957b8ff856de5804d4015662ef86c2919e4c81ba13fb5a97b727` |
| [Company Facts comparison](../.local/g2/sec-transforms-evaluation/comparison.json) | `fefbd0f66fd7ab86d76835c421c672a0a19c030806abf7cb83690b0bda6f2840` |
| [PDF comparison](../.local/g2/sec-transforms-evaluation/pdf-comparison.json) | `dfeafefa534b80afee73975f7bd399a65de8de9c3c6be13ac23fd72c5e851135` |
| [Source-level recovery audit](../.local/g2/sec-transforms-evaluation/transform-audit.json) | `a636fa8bddaa515224e7fc34cdd8d40213eed9735378c7563ae1758a2ba7b895` |

**KEEP** the verified plugin as an opt-in extraction profile. **DEFER**
schema-complete validation. The baseline omits `--sec-transforms` and
remains reproducible. Windows passed 594 tests with three skips and WSL
passed 593 with four skips. The dedicated parser and corpus tests passed
9/9. Ruff, configured mypy, the lock check and the deterministic claim
and citation fixtures passed. The baseline commit was `699ac87`.
