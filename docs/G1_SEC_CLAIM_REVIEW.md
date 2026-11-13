# G1 claim and citation review on the SEC pilot

Apply the G1 primary scorer to the original and current document-only
arms on the same frozen 26 questions. Review every substantive release
against the source pages. Verify the value, company, metric, period,
currency, scale and reporting basis of each numeric answer. Check
whether each cited page supports the associated claim and whether the
retrieved context supports it. Treat an alternative page as supporting
when the filing explicitly repeats the same fact. Keep the historical
locator scores and source artifacts intact. Bind the two reviewed
outputs to their report and PDF-page hashes. This is an author review
on a development-exposed cohort.

## Results

| G1 outcome | Original PDF-only | Current PDF-only |
| --- | ---: | ---: |
| Grounded exact accuracy | 4/23 | 22/23 |
| Numeric exact accuracy | 4/23 | 22/23 |
| Answer coverage | 5/26 | 22/26 |
| Incorrect or unsupported release risk | 1/5 | 0/22 |
| Citation support precision | 5/5 | 25/25 |
| Claim faithfulness | 5/5 | 25/25 |
| False abstention | 18/23 | 1/23 |
| Correct abstention | 3/3 | 3/3 |

The 95% Wilson release-risk intervals are 3.62–62.45% and
0–14.87%, respectively. These are descriptive bounds on a small
development cohort. The citation denominator counts claim-citation
associations, including multiple claims on the same page. Ranking
metrics require relevance judgments on ordered results. Those were
measured in a separate [four-case ranking review](G3_SEC_RANKING.md).

The original locator score was 3/23. Apple's FY2025 cash-flow
statement on physical page 35 begins with the same USD 112,010
million net income stated on income-statement page 31. The review
credits the original citation and raises the original grounded score
to 4/23. Tesla's income statement supports the stated USD 97,690
million consolidated revenue. The original answer used that figure
for a question about the energy generation and storage segment,
whose revenue was USD 10,086 million. Its statement is supported
in isolation and the answer still fails numeric exactness and release
risk. The current PDF-only arm abstains on that question.

The two arms are the frozen G2 and G3 PDF-only runtime receipts.
Historical warm p50/p95 was 57.02/267.30 ms and 10.75/104.25 ms,
respectively. Mean tools fell from 2.04 to 1.27. Mean evidence tokens
were 84.46 and 404.08. These were separate single runs and describe
the original runtime snapshots. Offline review scoring took 10.77 ms
with a 118,362,112 byte peak working set. Provider calls, billed tokens
and cost were zero.

## Reproduction and decision

The [adjudication file](G1_SEC_CLAIM_REVIEW.json) binds the two
reports and the identical page and reference hashes. The CLI
validates case membership, release applicability and citation
markers, then uses the existing G1 scorer. Labels are author-reviewed
and cover these numeric pilot releases. Independent claim and citation
metrics still require the G6 reviewer bundle. **KEEP** the reviewed
pilot as a diagnostic. Baseline commit `c10d359`.

```text
python -m scripts.score_sec_claim_review --original .local/g2/runtime-pilot-final --current .local/g3/inline-runtime-full --output .local/g1/sec-claim-review-final.json
```

The local score report has SHA-256
`002b75c7881f298a0a7fb1184feda1c448c45b4c1bfa0989960f13ba93a6aaa4`.
