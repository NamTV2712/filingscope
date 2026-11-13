# G6 development exposure inventory

The reviewer handoff currently asks for an exposure crosswalk. Generate
a draft from the frozen FinanceBench, G2 SEC, FinAgent and local FinRank
inputs. Resolve identities against the SEC ticker snapshot and explicit
historical issuer mappings. Preserve known document IDs and source
hashes. Check that reruns reproduce the same output and unresolved
identities stop generation. Record filing-date ceilings that still need
review. The draft is input to reviewer verification.

## Results

| Development input | Excluded CIKs | Local document IDs |
| --- | ---: | ---: |
| FinanceBench P1/P5, M13 and Q2–Q7 inputs | 33 | 84 |
| G2 SEC and G3/G5 pilot | 8 | 5 |
| FinAgent v1.1.1 issuer metadata | 31 | 0 |
| Public FinRank and local filing inventory | 23 | 2 |
| Union | 68 | 91 |

The FinanceBench row covers its 32 companies and the pinned M13 SEC
snapshot issuer list. The G2 receipt also lists all 17 extracted
accessions. The FinRank row conservatively excludes every ticker in
the locally available public release. Its two local filings contribute
document IDs, actual filing dates and accessions. The SEC ticker map
was acquired once through the bounded, content-addressed SEC client.
The draft explicitly excludes historical Activision Blizzard, Foot
Locker and Coterra CIKs and both ExxonMobil CIKs. [SEC ticker map](https://www.sec.gov/files/company_tickers.json) · [Activision Blizzard filing](https://www.sec.gov/Archives/edgar/data/718877/000162828023004842/0001628280-23-004842-index.html) · [Foot Locker filing](https://www.sec.gov/Archives/edgar/data/850209/000085020922000006/0000850209-22-000006-index.htm) · [Coterra filing](https://www.sec.gov/Archives/edgar/data/858470/000110465925026118/tm253060d2_ars.pdf).

Issuer matching uses the declared source metadata. The draft dates for
FinAgent and FinRank need reviewer confirmation against actual filing
dates, and the reviewer must check historical aliases, corporate
successors and exposures outside these inputs. FinRank's local filing
ceiling covers two identified filings. Before creating `freeze.json`,
review the inventory and add missing issuer or document exclusions.
The generated file is named `draft-exposed.jsonl`. The final protocol
uses the reviewer-verified `exposed.jsonl` and its SHA-256.

## Verification and reproduction

Two offline runs produced identical hashes for both files. The focused
G6 tests passed 14/14. The full offline suite passed 520 tests with
three skips on Windows and 519 with four on WSL. Ruff, focused mypy,
and both claim fixture checks passed. The inventory used no model
providers, and it generated no independent predictions or scores.
Baseline commit `fee6ff2`.

```text
python -m scripts.prepare_g6_exposure --ticker-cache .local/g6/sec-exposure-cache --output .local/g6/exposure-final-draft
```

The [draft inventory](../.local/g6/exposure-final-draft/draft-exposed.jsonl)
has SHA-256 `877aa5698f11876c285a83b2c6925eeb69dec2302c419ea1647793382f9eed18`.
The [source receipt](../.local/g6/exposure-final-draft/report.json)
has SHA-256 `79d5e02886b95c5ba0f8bc4c9a48e40ed8e69e39651c31f1c4a92f1da476fc91`.
**KEEP** the draft and source receipts for reviewer handoff. The G6
independent run awaits the verified crosswalk, eligible corpus, frozen
questions and reviewer-held labels.
