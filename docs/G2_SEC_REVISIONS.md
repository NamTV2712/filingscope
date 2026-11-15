# G2 filed, restated and recast financial observations

## Protocol

The mixed benchmark verifies the scope of a Tesla 10-K/A. Add a separate
development diagnostic with positive numeric restatement and segment
recast cases. Keep the frozen 17-filing benchmark intact. Use the
existing bounded SEC acquisition and offline Inline XBRL extraction.

- Compare Massimo Group FY2024 revenue, gross profit, operating income
  and net income in its March 26 original 10-K and May 20 restating
  10-K/A. Read the expected values from the displayed reconciliation
  and confirm the original and restated statements. Verify the original
  accession link and check that a swapped accession or filing revision
  cannot satisfy an exact lookup. Compare Company Facts by exact
  accession where available.
  [Original 10-K](https://www.sec.gov/Archives/edgar/data/1952853/000164117225000763/form10-k.htm) ·
  [Restating 10-K/A](https://www.sec.gov/Archives/edgar/data/1952853/000164117225011711/form10-ka.htm).
- Compare Redfin's previously reported Other segment revenue and recast
  Title and Monetization segment revenue for the three quarters ended
  March, June and September 2024. Check the displayed comparison and
  whether each cell has an Inline XBRL tag. Verify each available tag
  with its exact interval, segment and source anchor. A missing tag in
  the comparison is a measured limitation. Require a tag anchored to
  the assessed cell.
  [Redfin FY2024 10-K](https://www.sec.gov/Archives/edgar/data/1382821/000138282125000046/rdfn-20241231.htm).

The quarterly comparisons contain no Inline XBRL revenue tags. Also
check the six annual cells in the fiscal 2023 and 2022 comparison in
Redfin's audited segment note, using the same criteria. For Massimo,
verify the four rows in the amendment's bridge against their
previously reported, adjustment and restated contexts. Check that the
two amounts and the signed adjustment reconcile for each row.

Run two offline replays and compare exact manifest and observation
hashes. Keep the filing form and the presentation basis of each row
explicit. Abstain when more than one value matches a requested identity.
Record any unsupported concepts or missing source cells. Report the
measurements as author-reviewed development evidence, mark both issuers
as exposed and retain the previous benchmark outcomes.

## Results

The corpus contains two original 10-Ks and two 10-K/As from two issuers,
with 3,180 numeric observations. Both amendments have an unambiguous
same-period original in SEC Submissions. The acquisition used 10 SEC
HTTP attempts and took 64.235 s. Both offline replays reproduced the
acquired manifest and all four fact files byte for byte. They took
2.942 s and 2.974 s, making zero HTTP requests and using 185,954,304 B
and 187,613,184 B peak process memory, respectively.
[Frozen revision manifest](G2_SEC_REVISION_MANIFEST.json).

### Massimo FY2024 restatement

| Consolidated FY2024 amount | March 26 original, USD | Signed adjustment, USD | May 20 restated, USD |
| --- | ---: | ---: | ---: |
| Revenue | 111,209,142 | −1,883,400 | 109,325,742 |
| Gross profit | 34,343,339 | −1,883,400 | 32,459,939 |
| Income from operations | 6,811,991 | −1,762,402 | 5,049,589 |
| Net income | 3,154,207 | −1,392,298 | 1,761,909 |

The lookup verified 8/8 main-statement amounts and 12/12 amendment bridge
cells at their source anchors. All four signed adjustments reconcile.
Company Facts verified 8/8 main-statement amounts at their respective
accessions. The resolver rejected all 16 wrong-accession and wrong-filing-
revision requests. Within the amendment, the `RestatementAxis` members
separate previously reported amounts from adjustments. The corrected
statement and the restated bridge column share the undimensioned
identity and have separate source anchors.
[Original revenue](https://www.sec.gov/Archives/edgar/data/1952853/000164117225000763/form10-k.htm#Fact000214) ·
[Restated revenue bridge](https://www.sec.gov/Archives/edgar/data/1952853/000164117225011711/form10-ka.htm#Fact000682).

### Redfin segment recast

| Period ended | Previously reported Other, USD thousands | Recast Title, USD thousands | Recast Monetization, USD thousands | Tags in these cells |
| --- | ---: | ---: | ---: | --- |
| FY 2022-12-31 | 23,684 | 17,425 | 6,259 | 3/3 exact |
| FY 2023-12-31 | 39,175 | 25,095 | 14,080 | 3/3 exact |
| Quarter 2024-03-31 | 10,962 | 6,513 | 4,449 | 0/3 · HTML |
| Quarter 2024-06-30 | 16,528 | 11,505 | 5,023 | 0/3 · HTML |
| Quarter 2024-09-30 | 15,598 | 10,394 | 5,204 | 0/3 · HTML |

All 15 displayed amounts and five decompositions agree. The six annual
tags resolve by interval and dimension. The Other cells carry
`ScenarioPreviouslyReportedMember`. The Title and Monetization cells
carry the corresponding segment members. The display headers establish
the recast scope and the filing note attributes the change to segment
reporting. All nine quarterly cells were untagged in their displayed
table. The April 25 Redfin amendment adds Part III disclosures and
certifications. Its explanatory note confirms the scope of the amendment.
[Annual recast](https://www.sec.gov/Archives/edgar/data/1382821/000138282125000046/rdfn-20241231.htm#f-892) ·
[Quarterly recast and notes](https://www.sec.gov/Archives/edgar/data/1382821/000138282125000046/rdfn-20241231.htm) ·
[April amendment](https://www.sec.gov/Archives/edgar/data/1382821/000110465925039439/rdfn-20241231x10ka.htm).

## Reproduce and verify

Restore the pinned SEC cache and use the optional transform files from
the [transform replay](G2_SEC_INLINE_TRANSFORMS.md). The acquisition adds
`--acquire` and uses the configured SEC contact. Reproducing the recorded
hashes requires the recorded Submissions and Company Facts snapshots.

```text
uv run --offline --locked --extra ixbrl python -m scripts.run_sec_ixbrl_corpus --issuer MAMO=1952853 --issuer RDFN=1382821 --form 10-K --form 10-K/A --cutoff 2025-05-20 --cache .local/g2/revision-cache --sec-transforms .local/g2/sec-transform-plugin/transform --output .local/g2/revisions-offline
uv run --offline --locked --extra ixbrl python -m scripts.run_g2_revision_replay --corpus .local/g2/revisions-offline --cache .local/g2/revision-cache --output .local/g2/revisions-evaluation.json
python -m scripts.prepare_g6_exposure --ticker-cache .local/g6/sec-exposure-cache --output .local/g6/revision-exposure
```

The [Windows manifest](../.local/g2/revisions-offline/manifest.json) has
SHA-256 `d14c851fec34ce614b7b1f2138f98b6bc98c7cacd3e438ae613990869a7e0789`.
The [lookup audit](../.local/g2/revisions-evaluation.json) reproduced
SHA-256 `aa0cfd3d9b86b4258d5af613dbf4c14009574892ac2e65a58a9e2d9779117709`.
The audit took 98.424 ms at 89,718,784 B peak in its first run.
Linux WSL reproduced all four parsed payloads and every audit outcome.
The platform newline changes the raw JSON hashes. The WSL manifest SHA-256
is `df42aaf88445746d73756890034fd1a4878494433eaee26e06425cbf76ad3b6f`.
All extraction and evaluation used zero provider calls, billed tokens
and USD spend. Answer coverage, claim faithfulness and release risk are
outside this source lookup experiment.

`scripts/run_g2_revision_replay.py` verifies the cells and references.
`scripts/prepare_g6_exposure.py` reads the frozen manifest and records both
issuer CIKs and four accessions. Two offline drafts reproduced the inventory
and receipt hashes. [Updated exposure inventory](G6_EXPOSURE_INVENTORY.md).

Windows and Linux WSL each passed 594 tests with three unavailable local
fixtures skipped. Both runs reported 1.0 deterministic disposition and
claim status accuracy. Ruff, configured mypy, the dependency lock check
and the local CI syntax and tracked-file checks passed.

**KEEP** the existing accession and dimensional identities and the
source-anchored replay. **DEFER** automatic presentation classification
across filings and document QA on the untagged recast rows. The
filing revision field describes the form, which also accommodates
amendments with unchanged financial results. Reporting the specific
presentation basis requires the issuer's disclosure. The baseline commit
was `a2c29a8`.
