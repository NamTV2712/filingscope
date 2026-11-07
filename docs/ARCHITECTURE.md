# FilingScope Architecture

## Current implementation (P0–P4)

### Offline document and evaluation paths

```text
SEC EDGAR HTML ──→ section extraction ──→ chunks and financial tables
                                              │
FinanceBench PDFs ──→ page extraction ────────┤
                                              ↓
                           pinned embeddings ──→ Qdrant
                                              ↓
                         BM25 + dense + lexical candidates
                                              ↓
                              RRF + optional reranker
```

The ingestion and retrieval code is migrated from the source project. P1 adds
PDF page extraction, a corpus manifest, and an offline retrieval evaluator.
Dataset labels remain inside the evaluation package and are not passed to the
runtime retrieval implementation.

### Evidence decision and adaptive retrieval

```text
Question + retrieved chunks
           ↓
Requirement extractor
  entities · metrics · explicit periods · operations · required slots
           ↓
Evidence coverage analyzer
  provenance · value/period alignment · conflicts · operation compatibility
           ↓
Decision policy + remaining retrieval-attempt budget
  ├── ANSWER       structurally sufficient inputs
  ├── RETRIEVE_MORE
  │       ↓
  │   Bounded controller plans a company/metric/period query
  │       ↓
  │   Existing HybridRetriever.retrieve() → merge unique evidence
  │       └──────────────────────────────────────────→ reassess
  └── ABSTAIN      unsupported requirement or exhausted retrieval budget
```

`src/decision/` does not call a model or inspect retrieval scores. The analyzer
only sees chunks explicitly supplied by its caller. `ANSWER` means the
registered evidence requirements are met; it does not assert that a generated
answer is correct. The decision result retains requirement IDs, operation gap
codes, evidence IDs, page/source provenance, and reason codes.

`src/agent/adaptive_retrieval.py` handles only `RETRIEVE_MORE`. It derives one
target query from a current missing/conflicted slot or operation gap, invokes
the migrated `HybridRetriever.retrieve()`, preserves initial evidence, merges
new chunks, and reassesses. Round, total-query, evidence-token, and cooperative
elapsed-time limits bound the run. Query fingerprints prevent exact duplicate
calls; coverage changes and trace outcomes make no-progress stops inspectable.

The P2 evaluation uses 15 fixed synthetic scenarios. The P3 controller uses
nine fixed synthetic scenarios plus a temporary Qdrant/HybridRetriever
integration test. See [`DECISION_EVALUATION.md`](DECISION_EVALUATION.md) and
[`ADAPTIVE_RETRIEVAL_EVALUATION.md`](ADAPTIVE_RETRIEVAL_EVALUATION.md) for
measured results and limitations.

### Claim, citation, and numerical verification

```text
Question + answer clauses + source-ordered evidence chunks
                         ↓
             Canonical citation audit
     valid · missing · malformed · out-of-range
                         ↓
        Claim entity / metric / period / value
                         ↓
  P2 evidence facts from cited chunks only
     ├── direct financial fact matching
     ├── percentage growth recomputation
     ├── period difference recomputation
     └── topical lexical-anchor comparison
                         ↓
       claim status + response disposition
  VERIFIED · PARTIAL · REJECTED · ABSTAIN
```

`ClaimLevelVerifier` adapts the source project's `[Source N]` citation,
malformed legacy citation, and fallback-answer integrity checks from
`src/evaluation/answer_contract.py`. Claim values are matched using the P2
period/value parser and entity/metric-scoped evidence analyzer; source text
outside the citations attached to a claim is never considered. Growth and
difference calculations use `Decimal`, require compatible currencies and
scales, and fail closed when inputs conflict or are missing. Direct financial
fact mismatches are contradicted; absent metric/period support is unsupported;
invalid citations, ambiguous values, or conflicting sources are unverifiable.

Topical checking is intentionally lexical, so a valid paraphrase can be
classified as partial, unsupported, or unverifiable. The fixed P4 test set
contains 15 synthetic cases and is not a semantic benchmark or a real-response
accuracy estimate. Results and failure categories are in
[`VERIFICATION_EVALUATION.md`](VERIFICATION_EVALUATION.md).

## Planned connections

P5 will evaluate complete A0–A5 answer and retrieval variants, with a
labelled end-to-end report and ablations. P6 will deliver the research UI,
evidence inspector, deployment workflow, and reproducible demo.
