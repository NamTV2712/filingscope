from decimal import Decimal

import pytest

from src.decision.requirement_extractor import EvidenceRequirementExtractor
from src.ledger import (
    CalculationValidationStatus,
    DerivedCalculation,
    EvidenceLedger,
    EvidenceRecord,
    EvidenceSourceType,
    EvidenceStatus,
    FinancialFact,
    GeneratedClaim,
    LedgerConflictError,
    LedgerReferenceError,
)
from src.research.planner import QuestionOnlyPlanner, ResearchTask
from src.verification.models import (
    ClaimAssessment,
    ClaimStatus,
    CitationStatus,
    ResponseDisposition,
    VerificationResult,
)


def _request(question="What was Apple's revenue in FY2024?"):
    requirements = EvidenceRequirementExtractor().extract(question)
    plan = QuestionOnlyPlanner(max_tasks=6).plan(question)
    assert requirements.supported
    assert plan.tasks
    return requirements, plan


def _evidence(
    request_id,
    requirement_id,
    task_id,
    *,
    document_id="AAPL_2024_10K",
    chunk_id="chunk-17",
    period="FY2024",
    value="100",
    discovered_by=("filing_worker",),
    retrieval_method="dense",
    retrieval_rank=3,
    source_type=EvidenceSourceType.TEXT_EVIDENCE,
):
    return EvidenceRecord.from_source(
        request_id=request_id,
        document_id=document_id,
        chunk_id=chunk_id,
        company="Apple Inc.",
        ticker="AAPL",
        form_type="10k",
        filing_date="2024-11-01",
        fiscal_period=period,
        section="financial_statements",
        page=12,
        metric="revenue",
        metric_id="revenue",
        raw_value=f"${value} million",
        normalized_value=value,
        unit="million",
        currency="USD",
        source_type=source_type,
        source_url="https://www.sec.gov/Archives/edgar/data/aapl/filing.htm",
        retrieval_method=retrieval_method,
        retrieval_rank=retrieval_rank,
        discovered_by=discovered_by,
        source_revision="accession-0001",
        evidence_status=EvidenceStatus.CURRENT,
        task_id=task_id,
        requirement_ids=(requirement_id,),
    )


def test_evidence_id_is_stable_and_duplicate_discoveries_merge_provenance():
    requirements, plan = _request()
    task = plan.tasks[0]
    requirement_id = task.requirement_ids[0]
    ledger = EvidenceLedger("request-1")
    ledger.register_requirements(requirements)
    ledger.register_plan(plan)

    dense = _evidence("request-1", requirement_id, task.task_id)
    bm25 = _evidence(
        "request-1",
        requirement_id,
        task.task_id,
        discovered_by=("table_worker",),
        retrieval_method="bm25",
        retrieval_rank=1,
    )
    assert dense.evidence_id == bm25.evidence_id

    ledger.add_evidence(dense)
    merged = ledger.add_evidence(bm25)
    snapshot = ledger.snapshot()

    assert len(snapshot.evidence_records) == 1
    assert merged.discovered_by == ("filing_worker", "table_worker")
    assert merged.retrieval_method == "bm25"
    assert merged.retrieval_rank == 1
    assert {item.method for item in merged.retrieval_observations} == {"dense", "bm25"}
    assert merged.task_ids == (task.task_id,)
    assert merged.requirement_ids == (requirement_id,)


def test_same_evidence_merged_across_tasks_keeps_all_task_links():
    requirements, plan = _request()
    task_a = plan.tasks[0]
    task_b = ResearchTask.model_validate({
        **task_a.model_dump(mode="python"),
        "task_id": "worker-task-02",
    })
    ledger = EvidenceLedger("request-1")
    ledger.register_requirements(requirements)
    ledger.register_tasks((task_a, task_b))

    ledger.add_evidence(_evidence("request-1", task_a.requirement_ids[0], task_a.task_id))
    merged = ledger.add_evidence(_evidence(
        "request-1",
        task_b.requirement_ids[0],
        task_b.task_id,
        discovered_by=("table_worker",),
        retrieval_method="bm25",
        retrieval_rank=1,
    ))

    assert merged.task_ids == tuple(sorted((task_a.task_id, task_b.task_id)))
    assert len(ledger.snapshot().evidence_records) == 1


def test_merge_is_idempotent_commutative_and_atomic_on_conflict():
    requirements, plan = _request()
    task = plan.tasks[0]
    requirement_id = task.requirement_ids[0]
    left = EvidenceLedger("request-1")
    right = EvidenceLedger("request-1")
    for ledger in (left, right):
        ledger.register_requirements(requirements)
        ledger.register_plan(plan)
    left.add_evidence(_evidence(
        "request-1", requirement_id, task.task_id, discovered_by=("filing_worker",)
    ))
    right.add_evidence(_evidence(
        "request-1", requirement_id, task.task_id, discovered_by=("table_worker",),
        retrieval_method="bm25", retrieval_rank=1,
    ))

    left_snapshot, right_snapshot = left.snapshot(), right.snapshot()
    merged_lr = EvidenceLedger("request-1")
    merged_rl = EvidenceLedger("request-1")
    merged_lr.merge(left_snapshot)
    merged_lr.merge(right_snapshot)
    merged_rl.merge(right_snapshot)
    merged_rl.merge(left_snapshot)
    merged_lr.merge(right_snapshot)
    assert merged_lr.snapshot() == merged_rl.snapshot()
    assert len(merged_lr.snapshot().evidence_records) == 1

    original = merged_lr.snapshot()
    conflicting_task = ResearchTask.model_validate({
        **task.model_dump(mode="python"),
        "query": "conflicting task query",
    })
    from src.ledger import LedgerSnapshot

    conflict = LedgerSnapshot(
        request_id="request-1",
        question_requirements=requirements,
        tasks=(conflicting_task,),
    )
    with pytest.raises(LedgerConflictError):
        merged_lr.merge(conflict)
    assert merged_lr.snapshot() == original


def test_financial_facts_deduplicate_across_source_records():
    requirements, plan = _request()
    task = plan.tasks[0]
    requirement_id = task.requirement_ids[0]
    ledger = EvidenceLedger("request-1")
    ledger.register_requirements(requirements)
    ledger.register_plan(plan)
    first = _evidence("request-1", requirement_id, task.task_id)
    second = _evidence(
        "request-1",
        requirement_id,
        task.task_id,
        document_id="AAPL_2024_ANNUAL_REPORT",
        chunk_id="chunk-91",
        discovered_by=("table_worker",),
    )
    ledger.add_evidence(first)
    ledger.add_evidence(second)

    fact_a = FinancialFact.from_evidence(
        first, entity_id="AAPL", requirement_ids=(requirement_id,)
    )
    fact_b = FinancialFact.from_evidence(
        second, entity_id="AAPL", requirement_ids=(requirement_id,)
    )
    assert fact_a.fact_id == fact_b.fact_id
    ledger.add_fact(fact_a)
    merged_fact = ledger.add_fact(fact_b)

    assert len(ledger.snapshot().financial_facts) == 1
    assert merged_fact.evidence_ids == tuple(sorted((first.evidence_id, second.evidence_id)))


def test_derived_calculation_and_fact_retain_every_input_evidence_id():
    requirements, plan = _request(
        "Calculate Apple's revenue growth from FY2022 to FY2023"
    )
    ledger = EvidenceLedger("request-calc")
    ledger.register_requirements(requirements)
    ledger.register_plan(plan)
    input_records = []
    for task, value in zip(plan.tasks, ("100", "120")):
        requirement_id = task.requirement_ids[0]
        record = _evidence(
            "request-calc",
            requirement_id,
            task.task_id,
            document_id=f"AAPL_{task.period}_10K",
            chunk_id=f"{task.period}-revenue",
            period=task.period,
            value=value,
        )
        input_records.append(ledger.add_evidence(record))
    input_ids = tuple(item.evidence_id for item in input_records)
    requirement_ids = tuple(sorted({item for task in plan.tasks for item in task.requirement_ids}))
    calculation = DerivedCalculation.create(
        request_id="request-calc",
        operation="percentage_growth",
        formula="((current - prior) / prior) * 100",
        input_evidence_ids=input_ids,
        normalized_inputs=("100", "120"),
        result=Decimal("20"),
        metric_id="revenue",
        company="Apple Inc.",
        fiscal_period="FY2022-FY2023",
        unit="percent",
        currency=None,
        rounding_policy="half_up:2",
        validation_status=CalculationValidationStatus.VALID,
        task_ids=tuple(task.task_id for task in plan.tasks),
        requirement_ids=requirement_ids,
        discovered_by=("financial_reasoner",),
    )

    derived = ledger.add_calculation(calculation)
    assert derived.source_type == EvidenceSourceType.DERIVED_FACT
    assert derived.derived_from_evidence_ids == input_ids
    assert derived.calculation_id == calculation.calculation_id
    fact = FinancialFact.from_evidence(
        derived, entity_id="AAPL", requirement_ids=requirement_ids
    )
    ledger.add_fact(fact)
    snapshot = ledger.snapshot()
    assert set(snapshot.calculations[0].input_evidence_ids) == set(input_ids)
    derived_record = next(
        item for item in snapshot.evidence_records
        if item.source_type == EvidenceSourceType.DERIVED_FACT
    )
    assert set(derived_record.derived_from_evidence_ids) == set(input_ids)


def test_generated_claim_and_verification_are_linked_to_evidence():
    requirements, plan = _request()
    task = plan.tasks[0]
    requirement_id = task.requirement_ids[0]
    ledger = EvidenceLedger("request-claim")
    ledger.register_requirements(requirements)
    ledger.register_plan(plan)
    evidence = ledger.add_evidence(
        _evidence("request-claim", requirement_id, task.task_id)
    )
    claim = GeneratedClaim.create(
        claim_id="claim_1",
        request_id="request-claim",
        claim_text="Apple reported revenue of $100 million in FY2024.",
        claim_type="financial_fact",
        supporting_evidence_ids=(evidence.evidence_id,),
        requirement_ids=(requirement_id,),
    )
    ledger.add_claim(claim)
    assessment = ClaimAssessment(
        claim_id="claim_1",
        statement=claim.claim_text,
        status=ClaimStatus.SUPPORTED,
        citation_status=CitationStatus.VALID,
        citations=(1,),
        evidence_ids=(evidence.evidence_id,),
    )
    result = VerificationResult(
        disposition=ResponseDisposition.VERIFIED,
        claims=(assessment,),
        valid_citation_count=1,
        invalid_citation_count=0,
        supported_claim_count=1,
        partial_claim_count=0,
        unsupported_claim_count=0,
        contradicted_claim_count=0,
        unverifiable_claim_count=0,
    )

    verification = ledger.add_verification(
        result,
        verifier_id="claim-level-verifier",
        verifier_version="1.0.0",
    )
    snapshot = ledger.snapshot()

    assert snapshot.claims[0].verification_status == ClaimStatus.SUPPORTED
    assert snapshot.verifications[0] == verification
    assert snapshot.verifications[0].result.claims[0].evidence_ids == (evidence.evidence_id,)


def test_ledger_rejects_unknown_sources_and_cross_request_references():
    with pytest.raises(ValueError):
        EvidenceRecord.from_source(
            request_id="request-1",
            source_type="LLM_GENERATED",
        )

    ledger = EvidenceLedger("request-1")
    other_request_record = EvidenceRecord.from_source(
        request_id="request-2",
        document_id="AAPL_2024_10K",
        chunk_id="chunk-17",
        source_type=EvidenceSourceType.TEXT_EVIDENCE,
    )
    with pytest.raises(LedgerReferenceError):
        ledger.add_evidence(other_request_record)


def test_snapshot_rejects_derived_facts_without_all_inputs():
    requirements, plan = _request(
        "Calculate Apple's revenue growth from FY2022 to FY2023"
    )
    ledger = EvidenceLedger("request-derived")
    ledger.register_requirements(requirements)
    ledger.register_plan(plan)
    for task, value in zip(plan.tasks, ("100", "120")):
        ledger.add_evidence(_evidence(
            "request-derived",
            task.requirement_ids[0],
            task.task_id,
            document_id=f"AAPL_{task.period}_10K",
            chunk_id=f"{task.period}-revenue",
            period=task.period,
            value=value,
        ))
    snapshot = ledger.snapshot()
    with pytest.raises(LedgerReferenceError):
        ledger.add_calculation(DerivedCalculation.create(
            request_id="request-derived",
            operation="percentage_growth",
            formula="growth",
            input_evidence_ids=("ev_00000000000000000000000000000000", "ev_00000000000000000000000000000001"),
            normalized_inputs=("100", "120"),
            result=Decimal("20"),
            metric_id="revenue",
            rounding_policy="half_up:2",
        ))
    assert ledger.snapshot() == snapshot
