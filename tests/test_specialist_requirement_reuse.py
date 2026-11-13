from unittest.mock import patch

import pytest

from src.agent.complexity_router import ComplexityRouter, ExecutionPath
from src.agent.specialist_graph import SpecialistResearchGraph
from src.decision.policy import EvidenceDecisionLayer


@pytest.mark.parametrize(("question", "path"), [
    ("What was Apple's FY2024 revenue?", ExecutionPath.FAST),
    ("Compare Apple and Microsoft revenue growth from FY2023 to FY2024.", ExecutionPath.RESEARCH),
    ("Forecast Apple's FY2035 revenue.", ExecutionPath.UNSUPPORTED),
])
def test_specialist_graph_reuses_same_question_requirements(question, path):
    router = ComplexityRouter()
    graph = SpecialistResearchGraph(router=router)
    with patch.object(router.extractor, "extract", wraps=router.extractor.extract) as extract:
        result = graph.run(question)
    assert result.route.selected_path == path
    assert extract.call_count == 2


def test_preparsed_requirements_use_the_same_sufficiency_policy():
    decision = EvidenceDecisionLayer()
    question = "What was Apple's FY2024 revenue?"
    requirements = decision.extractor.extract(question)
    assert decision.decide_requirements(requirements, []) == decision.decide(question, [])
