# M6 shared Evidence Ledger

## Status and boundary

M6 adds an in-memory, request-scoped blackboard in `src/ledger/`. Its
immutable snapshot links P2 question requirements, M4 research plans/tasks,
source evidence, normalized financial facts, derived calculations, generated
claims, and P4 verification results. It has no database or cross-process
storage and is not wired into the P5 evaluation or the M5 route graph.

## Record relationships

```text
QuestionRequirements → ResearchPlan → ResearchTask
                                  ↘         ↓
                                     EvidenceRecord
                                      ↓       ↓
                               FinancialFact  DerivedCalculation
                                                   ↓
                                            DERIVED_FACT EvidenceRecord
                                                   ↓
GeneratedClaim → VerificationRecord → ClaimAssessment
```

`EvidenceRecord` is metadata-only: workers pass evidence IDs and structured
observations rather than copying filing text. It carries the M6 provenance
fields for request/document/chunk, company/ticker/CIK, filing/form/period,
section/page/table, metric/concept/value/unit/currency, source URL/revision,
retrieval method/rank, discovery workers, and current/superseded/conflicted/
unknown status. Retrieval observations are retained individually when the
same source record is found by more than one path.

The only allowed source types are `TEXT_EVIDENCE`, `TABLE_EVIDENCE`,
`XBRL_FACT`, and `DERIVED_FACT`; there is no `LLM_GENERATED` evidence type.
A derived record requires a calculation ID and an ordered list of every input
evidence ID. The ledger creates that record when it stores a
`DerivedCalculation`. A calculation or fact cannot be added until its source
evidence exists.

## Stable IDs and deterministic merge

Evidence IDs use SHA-256 over canonical request, source locator, source
revision, metric/period/value/unit, and derived-input identity. Retrieval
method/rank and worker discovery are observations, so those fields do not
change an evidence ID. Financial fact IDs and calculation IDs are also
content-derived. Claims can use an existing P4 claim ID or receive a stable
generated ID.

`EvidenceLedger.merge()` accepts another ledger or an immutable snapshot. It
stages the merge and commits only after all references validate. Identical
source evidence deduplicates by ID; discovery workers, task/requirement links,
and retrieval observations merge as sorted sets. The best retrieval rank is
reported in the summary fields while all observations remain available.
Facts with the same normalized identity merge their source evidence IDs.
Calculation inputs remain ordered because operations such as growth and
subtraction depend on operand order. Conflicting payloads under one task,
claim, calculation, or verification ID raise an error; merge order does not
choose a winner. Re-merging an identical snapshot is idempotent.

Verification records link assessments to registered generated claims and may
cite only evidence IDs already attached to those claims. A claim's visible
verification status is derived conservatively from all linked results, with
contradicted or unsupported outcomes taking precedence over supported ones.

## Example

```python
ledger = EvidenceLedger(request_id="request-123")
ledger.register_requirements(requirements)
ledger.register_plan(research_plan)

evidence = EvidenceRecord.from_source(
    request_id="request-123",
    document_id="AAPL_2024_10K",
    chunk_id="page-12-chunk-2",
    page=12,
    company="Apple Inc.",
    ticker="AAPL",
    fiscal_period="FY2024",
    metric_id="revenue",
    source_type=EvidenceSourceType.TEXT_EVIDENCE,
    task_id=research_plan.tasks[0].task_id,
    requirement_ids=research_plan.tasks[0].requirement_ids,
)
ledger.add_evidence(evidence)
snapshot = ledger.snapshot()
```

The example stores a source pointer and its requirement/task links; filing text
stays in the retrieval store.

## Validation and limits

- Stable ID and source-type validation, including rejection of derived facts
  without calculation/input references.
- Idempotent duplicate evidence merges across retrieval methods and workers.
- Atomic merge rejection for conflicting task data; merge-order equality.
- Request, requirement, task, evidence, calculation, claim, and verification
  reference checks.
- Financial fact deduplication across separate source records.
- Generated claim and P4 verification linking, including conservative status
  aggregation.
- Full regression suite: 255 passed, 3 skipped. No new dependency was required.

These are data-contract and software-behavior checks, not retrieval or answer
quality measurements. The ledger does not yet persist snapshots, enforce
retention/privacy policies, or decide whether source revisions are valid; the
M3 Evidence Policy and P2/P4 control logic remain separate. M7 specialist
results will use the ledger IDs and contracts; M8 will add bounded fan-out.
