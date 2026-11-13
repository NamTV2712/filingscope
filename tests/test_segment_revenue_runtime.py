from dataclasses import asdict, replace

import pytest

from src.agent.complexity_router import FAST_BUDGET, ComplexityRouter, SourceCapability
from src.agent.specialist_graph import SpecialistResearchGraph
from src.evaluation.benchmark_io import write_json_atomic
from src.ingestion.segment_revenue import ENERGY_FILING, ENERGY_IDENTITY, load_energy_revenue
from src.ledger.models import EvidenceRecord, FinancialFact
from src.local_research import public_result
from src.retrieval.canonical_json import sha256_file
from src.verification.atomic_claim_verifier import AtomicClaimVerifier


QUESTION = "What was Tesla's FY2024 energy generation and storage revenue?"


@pytest.fixture
def extraction(tmp_path):
    path = tmp_path / "facts.json"
    row = {
        "fact_id": ENERGY_IDENTITY.fact_id, "identity": asdict(ENERGY_IDENTITY), "value": "10086000000",
        "filed": ENERGY_FILING.filing_date, "filing_form": ENERGY_FILING.form_type,
        "report_date": ENERGY_FILING.report_date, "source_anchor": "f-1636",
        "source_url": ENERGY_FILING.filing_url + "#f-1636",
    }
    write_json_atomic(path, {"facts": [row]})
    return path, row


def test_inline_extract_requires_pinned_content_and_anchored_identity(extraction):
    path, row = extraction
    digest = sha256_file(path)
    write_json_atomic(path, {"facts": [{**row, "source_anchor": None, "source_url": ENERGY_FILING.filing_url}]})
    with pytest.raises(ValueError, match="differs from the pinned filing"):
        load_energy_revenue(path, digest)
    with pytest.raises(ValueError, match="with an anchor"):
        load_energy_revenue(path, sha256_file(path))


def test_inline_segment_graph_keeps_provenance_and_verifies_claim_scope(extraction):
    class RecordingVerifier(AtomicClaimVerifier):
        def verify(self, question, answer, evidence_chunks):
            self.chunks = list(evidence_chunks)
            return super().verify(question, answer, self.chunks)

    path, row = extraction
    fact = load_energy_revenue(path, sha256_file(path))
    verifier = RecordingVerifier()
    graph = SpecialistResearchGraph(inline_energy_fact=fact, verifier=verifier)
    result = graph.run(QUESTION)
    assert result.status == "VERIFIED" and result.verification.supported_claim_count == 1
    assert result.route.source_capability == SourceCapability.DIRECT_XBRL
    assert result.usage.tool_calls == 1 and result.usage.retrieval_calls == result.usage.llm_calls == 0
    record, = result.ledger_snapshot.evidence_records
    ledger_fact, = result.ledger_snapshot.financial_facts
    assert result.citation_evidence_ids == (record.evidence_id,)
    assert EvidenceRecord.model_validate_json(record.model_dump_json()) == record
    assert FinancialFact.model_validate_json(ledger_fact.model_dump_json()) == ledger_fact
    assert record.xbrl_provenance == ledger_fact.xbrl_provenance == fact.provenance
    source, = public_result(result)["sources"]
    assert (source["url"], source["value"], source["inline_identity_sha256"]) == (
        row["source_url"], row["value"], ENERGY_IDENTITY.fact_id,
    )
    dimension, = ENERGY_IDENTITY.dimensions
    assert source["dimensions"] == [{"axis": dimension.axis, "member": dimension.member}]
    assert "USD 10,086,000,000" in result.answer

    chunks = verifier.chunks
    bare = result.answer.replace("energy generation and storage segment ", "")
    for answer in (bare, result.answer.replace("energy generation", "U.S. energy generation")):
        check = verifier.verify(QUESTION, answer, chunks)
        assert check.disposition == "REJECTED"
        assert any(claim.reason_codes == ("dimensioned_claim_scope_mismatch",) for claim in check.claims)
    wrong_url = {**chunks[0], "source_url": ENERGY_FILING.filing_url}
    assert verifier.verify(QUESTION, result.answer, [wrong_url]).disposition == "REJECTED"


def test_inline_segment_graph_withholds_other_scopes(extraction):
    path, _ = extraction
    fact = load_energy_revenue(path, sha256_file(path))
    graph = SpecialistResearchGraph(inline_energy_fact=fact)
    for question in (
        QUESTION.replace("Tesla", "Apple"), QUESTION.replace("FY2024", "FY2023"),
        QUESTION.replace("FY2024", "Q4 FY2024"), QUESTION.replace("energy", "U.S. energy"),
        QUESTION.replace("energy", "adjusted energy"), QUESTION[:-1] + " excluding leasing?",
        QUESTION[:-1] + " in EUR?", QUESTION[:-1] + " in Form 10-Q?",
        QUESTION[:-1] + " in SEC accession 0001628280-25-003064?",
        QUESTION[:-1] + " from the income statement?", QUESTION[:-1] + " as restated?",
        "What was Tesla's FY2024 revenue?",
    ):
        result = graph.run(question)
        assert result.status == "ABSTAIN", question
        assert not result.citation_evidence_ids
    wrong_dimension = fact.provenance.model_copy(update={"dimensions": (("axis", "member"),)})
    rejected = SpecialistResearchGraph(inline_energy_fact=replace(fact, provenance=wrong_dimension)).run(QUESTION)
    assert rejected.status == "ABSTAIN"
    router = ComplexityRouter(fast_budget=FAST_BUDGET.model_copy(update={"max_tool_calls": 0}))
    limited = SpecialistResearchGraph(router=router, inline_energy_fact=fact).run(QUESTION)
    assert limited.status == "ABSTAIN" and limited.usage.tool_calls == 0
