from __future__ import annotations

from configs.multi_agent_ablation import AblationCase, GoldClaim
from src.agent.complexity_router import RESEARCH_BUDGET, ComplexityRouter, ExecutionPath
from src.decision.policy import EvidenceDecisionLayer
from src.evaluation.multi_agent_ablation import AblationObservation, evaluate_observation, summarize_ablation
from src.policy.candidate_gate import CandidateEvidenceGate
from src.policy.evidence_policy import CandidateDisposition, PolicyReason


def test_candidate_policy_keeps_comparatives_and_rejects_wrong_issuer_or_broken_provenance():
    layer = EvidenceDecisionLayer()
    requirements = layer.extractor.extract("What was Apple's revenue in FY2023?")
    comparative = {
        "chunk_id": "comparative", "doc_name": "AAPL_2024_10K", "ticker": "AAPL", "page_number": 0,
        "source_url": "https://example.org/aapl", "reporting_periods": ["2024"],
        "text": "Apple revenue was $100 billion in FY2023.", "score_kind": "dense", "score": 0.9,
    }
    wrong_entity = {**comparative, "chunk_id": "wrong", "ticker": "MSFT", "doc_name": "MSFT_2024_10K"}
    invalid = {**comparative, "chunk_id": "invalid", "source_url": "invalid-scheme:value"}
    retained, decisions = CandidateEvidenceGate().screen(requirements, [comparative, wrong_entity, invalid], layer)
    assert retained == [comparative]
    assert decisions[0].disposition in {CandidateDisposition.WEAK, CandidateDisposition.ACCEPT}
    assert PolicyReason.ENTITY_MISMATCH in decisions[1].reason_codes
    assert PolicyReason.INVALID_PROVENANCE in decisions[2].reason_codes


def test_force_research_exercises_full_plan_and_preserves_unsupported_requests():
    router = ComplexityRouter()
    question = "What was Apple's revenue in FY2024?"
    assert router.route(question).selected_path == ExecutionPath.FAST
    forced = router.route(question, force_research=True)
    assert forced.selected_path == ExecutionPath.RESEARCH
    assert forced.budget == RESEARCH_BUDGET and forced.planned_task_count == 1
    unsupported = router.route("What is Apple's predicted revenue in FY2035?", force_research=True)
    assert unsupported.selected_path == ExecutionPath.UNSUPPORTED


def test_answer_value_and_provenance_are_scored_independently():
    case = AblationCase(
        "example", "development", "numerical", "What was Apple's revenue growth?", ExecutionPath.RESEARCH,
        (GoldClaim("10%", ("apple", "revenue", "growth"), (("annual#p1",), ("annual#p2",)), ("FY2023", "FY2024")),),
    )
    answer = "Apple revenue growth was 10% from FY2023 to FY2024. [Source 1] [Source 2]"
    exact = evaluate_observation(case, AblationObservation(answer=answer, citation_sources=("annual#p1", "annual#p2")), latency_ms=2)
    assert exact["grounded_exact"] and exact["supported_citations"] == 2
    wrong = evaluate_observation(case, AblationObservation(answer=answer, citation_sources=("annual#p1", "segment#p2")), latency_ms=1)
    assert wrong["numeric_exact"] and not wrong["grounded_exact"]
    assert wrong["supported_citations"] == 1
    assert summarize_ablation([exact, wrong])["unsupported_answer_rate"] == 0.5
