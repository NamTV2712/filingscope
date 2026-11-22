# D8 offline demo release results

The measured runtime is `1fa407418e5c60fcc5bd7f682592eea682ba84df`.
The two evaluation arms used frozen filing bundles, six CPU threads and the
pinned Nomic model. Predictions were generated offline and hashed before
scoring. Provider requests and spend were zero. The Ford/Chevron freeze and
the FinRank corpus and questions retained their original hashes.

| Cohort and arm | Coverage | Grounded positives | Correctly withheld controls | Source-reviewed release errors |
| --- | ---: | ---: | ---: | ---: |
| Ford/Chevron D0, both arms | 0/24 | 0/16 | 8/8 | 0/0 |
| Ford/Chevron Adaptive | 15/24 | 15/16 | 8/8 | 0/15 |
| Ford/Chevron routed | 16/24 | 16/16 | 8/8 | 0/16 |
| Devon/EOG FinRank D0, both arms | 0/130 | 0 newly grounded | — | 0/0 |
| Devon/EOG FinRank Adaptive | 2/130 | 2 newly grounded | — | 0/2 |
| Devon/EOG FinRank routed | 2/130 | 2 newly grounded | — | 0/2 |

The transfer review checked all 31 released answers against the two PDF
balance sheets and recomputed their percentages from the original cells.
Each routed percentage also matched the numeric inputs and ordered operand
identities in the evidence ledger. Both companies contributed eight routed
grounded answers, four lookups and four calculations. Adaptive withheld the
Ford current-assets percentage. All eight controls were withheld in both
arms. The transfer result is an internal evaluation.
[Transfer freeze and review method](D2_TRANSFER_COHORT.md).

The two newly grounded FinRank IDs in both arms were
`64cd491b-da4e-4dbf-b6f3-939d5fc83eb8` and
`7e41b20c-418c-4e2a-bf70-295d2dfb9662`. Physical PDF page 56 supports the
10% customer concentration upper limit and the FY2024 oil, gas and NGL
sales of USD 9,368 million, 398 million and 1,410 million. FinRank's oil
label quotes USD 9,268 million. Publisher scoring reports 0/38 on the
quantitative exact-match denominator and 0/130 for text exact match in
both arms. Each arm has 110 unsupported outcomes and 18 abstentions. Of 31
cases with mapped reference pages, 4/31 retrieved every reference page and
1/31 cited every reference page. For comparison, D0 retrieved every mapped
page in 6/31 Adaptive and 5/31 routed cases.
[Devon filing](https://www.sec.gov/Archives/edgar/data/1090012/000095017025022844/dvn-20241231.htm)
· [FinRank v1 source](https://github.com/datanxt/FinRank/blob/916dc27e77b90e294ea1b3a2cc5b0abcf07392d1/README.md).

A release candidate returned the total amount when asked about sources of
midstream sales. The intent guard now withholds that question. The row-label
fix retains the physical table caption and row name on the evidence card.
The transfer scorer uses the existing numeric exact matcher so a reference
without a lexical fiscal-year tag can match a value displayed with one.
The source review checks the actual period, currency, basis and cell.

## Runtime cost on the Windows development machine

P50 is the median per-question latency. P95 uses the nearest rank. Model setup
and process peak working set are measured separately. These single-host
observations include all released and withheld cases.

| Cohort | Setup ms | Peak bytes | Adaptive p50 / p95 ms | Routed p50 / p95 ms | Tool calls Adaptive / routed |
| --- | ---: | ---: | ---: | ---: | ---: |
| FinRank D0 | 1,286 | 1,782,779,904 | 1.58 / 168.21 | 3.19 / 104.43 | 38 / 43 |
| FinRank D8 | 1,326 | 1,784,598,528 | 1.71 / 153.39 | 3.29 / 100.78 | 30 / 35 |
| Transfer D2 | 1,751 | 1,775,943,680 | 80.69 / 110.18 | 37.46 / 232.71 | 36 / 34 |
| Transfer D8 | 1,564 | 1,778,110,464 | 61.00 / 102.38 | 11.92 / 258.57 | 29 / 36 |

## Reproduction and regression checks

The detached runtime checkout reproduced the public and transfer predictions
and the default Apple HTTP smoke after restoration of the prepared model and
corpora. The Devon/EOG and transfer bundles both load through the common
verified runtime. Chromium ran four flows at each of 1440×900 and 390×844.
The local PDF viewer opened page 56 and showed the exact oil row and source
note. The browser used loopback with outside DNS disabled and the Python
offline guard. [Demo setup and browser flows](DEMO_REPRODUCTION.md).

All 612 mixed SEC case scores matched the D0 replay. Per-case predictions
changed only latency, optional empty cell-metadata fields, and the plural
contract-revenue alias appearing in two requirement records. The four-arm
SEC runtime pilot and historical M13/direct/complex, narrative and injected
fault replays matched their saved controls apart from timing and resources.
The historical routed M13 arm retained 21 correct releases with zero
unsupported releases. The offline suite passed 639 tests. Three tests that
require the original AAPL, MSFT or companion HTML corpus skipped. Ruff,
configured mypy, compileall, JS syntax and the frozen dependency lock passed.

| Local artifact | SHA-256 |
| --- | --- |
| `data/d8/final-finrank-predictions.json` | `c75ec020e7384577099ae2b250da0d6879dfcd0bb09b72d9b9dbf75b5108713d` |
| `data/d8/final-finrank-scores.json` | `a207f2bd68d9f808e1af5579707710ad025fd1891a4182c7e977b90ab652e27a` |
| `data/d8/final-finrank-reviews.json` | `ae2dd2a9fc27ecb87014bbced7388cfad67687c937965e0c8e24d3861cdf76da` |
| `data/d8/final-transfer-predictions.json` | `8d573b185df0a462e78d3d4355c7e2a5a14087494b1236bb082b83a4972569ea` |
| `data/d8/final-transfer-reviews.json` | `479d3f29811942610886187f3a5cfcb0511df26e7c8d155395e8ce705f56b0b0` |
| `data/d8/final-transfer-scores.json` | `9665d274a60f2f5c7be4af52d7f44ca5d4164d1a815f66d3fa03208d2c4d613c` |
| `data/d8/mixed/report.json` | `35d416f1ae17201ac8c20ea468f3b19ab391221108b6a9f701b966c869a6abf5` |
| `data/d8/pilot/report.json` | `e86f077a85180637d220e74452dfc545739f83ae05f49f7b8f7999a3437fcc03` |
| `data/d8/historical.json` | `9e59ea9a9ab6f495faa4483e0dffe43df002d1709abadb9f8c7f59db4102a328` |
| `.local/d7-browser/results.json` | `7b21a2f112713a9eda603874ea186cdba2d0ec490e9591d7dae2c111c71b56c8` |

FinRank covers two issuers and the transfer set covers two consolidated
balance sheets. This evidence supports the specified demo. G6 independent
evaluation still requires a reviewer-held set. Exact FinRank replay depends
on the archived Devon PDF rendition and its original page mapping.
