# G2 SEC narrative track

Run disclosure questions against the five frozen G2 pilot PDFs. Include
reportable segments, products and risk disclosures with source-reviewed
statements. Compare the document-only and hybrid arms against the
structured-only control using the same questions. Check the reference
excerpt on its pinned physical page before inference. Report grounded
exactness, withheld answers, unsupported releases and source usage. This
is a development-exposed diagnostic with author-checked references.

## Results

The six questions cover four issuers and four annual filings from the
five-document pilot corpus. The labels use one source-checked statement
and one pinned physical page per case. The runner verifies the literal
source excerpts before prediction. Exactness requires the full normalized
reference statement, a verified disposition and the frozen citation
locator. No author-independent labels were available for this track.

| Measure | Document-only | Company Facts-only | Hybrid |
| --- | ---: | ---: | ---: |
| Grounded exact | 0/6 | 0/6 | 0/6 |
| Releases / questions | 0/6 | 0/6 | 0/6 |
| False abstentions | 6/6 | 6/6 | 6/6 |
| Retrieved frozen reference page | 2/6 | 0/6 | 2/6 |
| Total tool calls | 6 | 0 | 6 |
| Local Company Facts reads | 0 | 0 | 0 |
| Mean evidence tokens | 1,313.5 | 0 | 1,313.5 |
| Warm p50/p95 | 39.65/46.38 ms | 4.22/5.43 ms | 39.20/42.99 ms |

Release risk and citation support have zero denominators. The two
PDF arms retrieved both frozen Apple pages, then abstained on the
product and disruption-risk disclosures. They also retrieved suitable
alternatives on the NVIDIA segment (`#p127`), Walmart segment (`#p59`)
and Tesla currency-risk (`#p46`) questions. Tesla's segment case retrieved
neither the reference page (`#p4`) nor an equivalent explicit disclosure
identified during the review. The alternative-page observations explain
the misses while keeping the original locator labels fixed. The current
deterministic writer has a dedicated industry template. These six
questions exercise other disclosure types.

## Reproduction and decision

The original four numeric pilot arms retained the same 104 case outcomes,
including answers, dispositions and citations. The numeric reference,
pages, chunks, Company Facts and vectors matched the previous hashes.
The six narrative references and three narrative arms have separate
receipts. No providers were called. Billed tokens and spend were zero.
The whole process peaked at 1,883,471,872 bytes with a 38.63 s setup
using prior hash-checked vectors. This was one warm run per arm.

**KEEP** the narrative diagnostic and deterministic release policy.
**DEFER** a general narrative accuracy claim. Real reviewer-held
semantic judgments remain a G6 dependency. The focused suite passed
28/28. Windows offline passed 522 tests with three corpus skips. WSL
passed 521 with four. Ruff, focused mypy and the deterministic claim
fixture passed. Baseline Git commit `9857487`.

```text
python -m scripts.run_sec_runtime_pilot --pdfs .local/g2/runtime-pdfs --cache .local/g2/sec-cache --reuse-pilot-vectors .local/g3/inline-runtime-full --narrative-controls --inline-facts .local/g2/verified-replay/facts --output .local/g2/sec-narrative
```

Use the G0 offline CPU environment and a fresh output directory. The
[report](../.local/g2/sec-narrative/report.json) has SHA-256
`4cc1e8fe8576607265571dee831a36a2b0893d1da4691556644a9e5fe1c91613`.
The [narrative reference](../.local/g2/sec-narrative/narrative-reference.json)
has SHA-256 `d9503d2ffa7a8ff81955db94771f3b7ce2110095c3204625f7db547df30562b7`.
