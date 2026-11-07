# FilingScope Architecture

## Current implementation (P0–P2)

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

### Evidence decision boundary

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
  ├── RETRIEVE_MORE missing/conflicting slots or operation gaps
  └── ABSTAIN      unsupported requirement or exhausted retrieval budget
```

`src/decision/` does not call a model or inspect retrieval scores. The analyzer
only sees chunks explicitly supplied by its caller. `ANSWER` means the
registered evidence requirements are met; it does not assert that a generated
answer is correct. The decision result retains requirement IDs, operation gap
codes, evidence IDs, page/source provenance, and reason codes.

The P2 evaluation uses 15 fixed synthetic scenarios. See
[`DECISION_EVALUATION.md`](DECISION_EVALUATION.md) for its measured result and
scope.

## Planned connections

P3 will connect `RETRIEVE_MORE` to bounded targeted searches through existing
retrieval tools, merge and deduplicate evidence, and reassess until evidence is
sufficient or a budget/no-progress stop applies. P4 will verify generated
claims, citations, and declared numerical operations. Those components are not
part of the current P2 decision result.
