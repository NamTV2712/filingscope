# G6 FinRank public replay

## Protocol

Use the existing local public runner with the pinned FinRank release
and the two complete PDFs in the frozen filing inventory. Include all
2025 Form 10-K records for those two issuers. Supply the named issuer,
form and fiscal year from the inventory. Both architectures use the
same PDFs, index and six-thread CPU setting. Freeze predictions by
hash before running the public scorer. Store the worktree runner and
source hashes with the result. The study is public and development-exposed.
[FinRank paper](https://arxiv.org/abs/2608.07400) ·
[Pinned dataset and license](https://github.com/datanxt/FinRank/blob/916dc27e77b90e294ea1b3a2cc5b0abcf07392d1/README.md).

The PDFs cover Devon Energy and EOG Resources for FY2024, filed
February 19 and February 27, 2025. Company Facts is empty in this
bundle. FinRank's year selects the filing year. A reference page
mapping requires every supplied excerpt to occur on a unique PDF
page after normalization. Preserve all 130 cases in the coverage
denominator. Report the subset eligible for source checks separately
and compare predictions pairwise.
[Devon 10-K](https://www.sec.gov/Archives/edgar/data/1090012/000095017025022844/dvn-20241231.htm) ·
[EOG 10-K](https://www.sec.gov/Archives/edgar/data/821189/000082118925000011/eog-20241231.htm).

The baseline also exposed lower-case uses of the word “cost” being
resolved as Costco. Test requiring upper-case for this ticker alias
while keeping the company name and explicit ticker available. Require
all seven erroneous Costco selections in this slice to disappear and
preserve explicit cross-issuer and COST lookup cases. Use the frozen
outputs to check whether routing, retrieval or release changes.

## Results

The slice contains 60 Devon and 70 EOG records, with 87 qualitative
and 43 quantitative. Two distinct Devon records use the same
question text. Both arms retained all records. Codex reviewed the
paired outputs, mapped evidence and representative failures.

| Measure | Adaptive | Routed LangGraph |
| --- | ---: | ---: |
| Answer coverage | 0/130 | 0/130 |
| Unsupported before retrieval | 107/130 | 107/130 |
| Abstained after routing | 23/130 | 23/130 |
| Normalized text exact | 0/130 | 0/130 |
| Numeric exact on parseable quantitative references | 0/38 | 0/38 |
| All mapped reference pages retrieved | 6/31 | 5/31 |
| All mapped reference pages cited | 0/31 | 0/31 |
| Numeric exact with all reference pages on parseable, aligned questions | 0/15 | 0/15 |
| Warm p50/p95, ms | 1.39/127.40 | 2.75/69.93 |
| Tool calls | 38 | 43 |
| Evidence tokens | 16,012 | 19,205 |
| Hosted calls, billed tokens and spend | 0 | 0 |

The baseline peaked at 1,779,068,928 bytes. A routing rejection
accounted for 107 records, including 88 with unrecognized metrics,
16 with insufficient operation periods and three flagged as
predictive or advisory. Only 31 records have a complete exact
excerpt-to-page mapping, 27 from Devon and four from EOG. The five
routed page matches were among Adaptive's six matches. Coverage was
identical on each issuer. The pair has two issuer groups, and the
results are descriptive. Incorrect-release risk, citation support
precision and claim faithfulness have zero release denominators.
The public scorer measures answer strings and page alignment. It
has no exhaustive retrieved-page relevance or full semantic labels.

## Source checks and failure analysis

- Both arms retrieved the Devon customer-concentration evidence. Its
  FY2024 disclosure sets a 10% upper threshold for every customer,
  while the workflow asked for consolidated revenue and abstained.
  [Devon 10-K](https://www.sec.gov/Archives/edgar/data/1090012/000095017025022844/dvn-20241231.htm).
- On the Devon commodity sales split, the FinRank answer gives
  USD 9,268 million for oil. The FY2024 source table reports
  USD 9,368 million, USD 398 million for gas and USD 1,410 million
  for NGL. Preserve the published label and record the discrepancy.
  An exact page match alone cannot validate the answer key.
  [Devon 10-K](https://www.sec.gov/Archives/edgar/data/1090012/000095017025022844/dvn-20241231.htm).
- The Devon midstream share question requires a ratio with
  numerator and denominator defined from the same reporting basis.
  Both arms retrieved the referenced pages and abstained on a generic
  revenue slot. The filing reports USD 4,743 million in marketing and
  midstream revenue against USD 15,919 million in total customer-contract
  revenue. This supports the approximate 29.79% ratio in the reference.
  [Devon 10-K](https://www.sec.gov/Archives/edgar/data/1090012/000095017025022844/dvn-20241231.htm).
- An EOG question about drilling cost and availability had two
  spurious COST requirements. The candidate removes those requirements
  while the EOG risk and CapEx tasks still lead to abstention.
  [EOG 10-K](https://www.sec.gov/Archives/edgar/data/821189/000082118925000011/eog-20241231.htm).

## Issuer resolution follow-up

Case-sensitive matching of the COST ticker, including lower-case
aliases produced by catalog normalization, eliminated seven false
issuer resolutions. Six already failed the routing checks. The
remaining question lost two incorrect requirements in both arms and
retained its abstention. The other 129 public outputs matched within
each arm apart from latency. Explicit COST and Costco mentions remain
resolvable. Public release, page alignment and tool counts matched.

All 612 mixed SEC arm/case records matched apart from timing, including
196/204 hybrid releases and all eight missing-unit abstentions in
each arm. Windows passed 583 tests with three fixture skips and Linux
WSL passed 582 with four. Ruff, configured mypy and deterministic
verification passed. All stable historical architecture and fault
outcomes matched. The comparison used the same evidence verifier and
release policy. The candidate peaked at 1,777,926,144 bytes. Its
Adaptive and routed evidence totals were 14,691 and 19,205 tokens.
Candidate warm p50/p95 were 2.11/217.43 ms and 4.28/131.95 ms.
The candidate shared the host with the mixed replay and test suite.

**KEEP** the targeted issuer-resolution fix. **DEFER** any
generalization or independent-release claim from this public slice.
The observed coverage is limited to this two-issuer, document-only
evidence setup and question mix.

## Reproduction

Use checkout `69410a24abddb764aa0aa6f9ebcd9d2a0465e42c` for the
baseline and apply the COST catalog change for the candidate. This
experiment uses the pre-existing local corpus and public runner.
Their SHA-256 hashes are `0f70467729ab3a66ced10d7586bf35ab403076cbf751a8c126c7ac40f60de672`
for `prepare_independent_corpus.py`,
`13eda8faa70f33ef91390d6207b849c1f40414b1b101bdae71c462388551e4d0`
for `run_finrank_external.py` and
`696f3578be3e755573162113e2f32c457e6459c6de87b0b38e2f9d089148a4d7`
for the worktree `run_independent_final.py`. The predictions record the
tracked diff hash and full environment for each run. Archived artifacts
stay under ignored data directories.

```text
python -m scripts.run_finrank_external predict --dataset data/independent-final/public-sources/FinRank.jsonl --bundle data/independent-final/finrank-2025 --filing-year 2025 --cutoff 2025-12-31 --threads 6 --output data/independent-final/finrank-2025/replay-predictions.json
python -m scripts.run_finrank_external score --dataset data/independent-final/public-sources/FinRank.jsonl --bundle data/independent-final/finrank-2025 --filing-year 2025 --cutoff 2025-12-31 --threads 6 --predictions data/independent-final/finrank-2025/replay-predictions.json --predictions-sha256 <sha256 printed by predict> --output data/independent-final/finrank-2025/replay-scores.json
```

| Artifact | SHA-256 |
| --- | --- |
| [Pinned FinRank JSONL](https://github.com/datanxt/FinRank/blob/916dc27e77b90e294ea1b3a2cc5b0abcf07392d1/FinRank.jsonl) | `e9295f680bd6085362486c90c170bce243be7f85ed18074d6ba21cb75141ac78` |
| [Corpus](../data/independent-final/finrank-2025/corpus.json) | `0d6c53cb12bbab30d1cf11d7e4c0d6226c5cb783f8fb926834623ca8dab49ab9` |
| [Baseline predictions](../data/independent-final/finrank-2025/local-review-69410a2-predictions.json) | `26221b8ad143b6020591675816d064b53a528df1adac58268b478723e32cadc6` |
| [Baseline scores](../data/independent-final/finrank-2025/local-review-69410a2-scores.json) | `85fe84632068cef9b53ae02ba7adf35cdd14f93647acca76d103d372f063edee` |
| [Candidate predictions](../data/independent-final/finrank-2025/local-review-cost-ticker-final-predictions.json) | `a1e9da294d921b2f7f5fe2ad4686d1e91b4d0ab4295db1761a8f9367a323baec` |
| [Candidate scores](../data/independent-final/finrank-2025/local-review-cost-ticker-final-scores.json) | `e104c755bbca930b28a4782645e3eee59ef803d19218ab94f124e4169c7a1026` |
| [Candidate mixed SEC replay](../.local/g3/cost-ticker-final/report.json) | `3b562f78c2422346662fc9b527694f8656410ff86645c0425eccd341c1352285` |
| [Candidate historical replay](../.local/g3/cost-ticker-historical.json) | `5a1c400dadfd71ab92efab3d1b6429b0f294edbf2f35a22bcaaf57643a952153` |
