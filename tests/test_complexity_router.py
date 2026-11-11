from src.agent.complexity_router import (
    FAST_BUDGET,
    RESEARCH_BUDGET,
    UNSUPPORTED_BUDGET,
    ComplexityClass,
    ComplexityRouter,
    ExecutionPath,
)
from src.evaluation.complexity_router_evaluation import (
    SYNTHETIC_ROUTING_CASES,
    evaluate_complexity_routing,
)
from src.research.corpus_map import CorpusMap, SourceAvailability


def test_router_selects_bounded_paths_for_spec_examples():
    router = ComplexityRouter()

    lookup = router.route("What was Apple's revenue in FY2024?")
    comparison = router.route(
        "Compare Apple, Microsoft, and Amazon revenue growth and operating margin from FY2022 to FY2024."
    )
    unsupported = router.route("Forecast Apple's revenue next year.")
    unresolved = router.route("What was Acme's revenue in FY2024?")

    assert lookup.decision.complexity == ComplexityClass.SIMPLE_LOOKUP
    assert lookup.selected_path == ExecutionPath.FAST
    assert lookup.budget == FAST_BUDGET
    assert comparison.decision.complexity == ComplexityClass.COMPARATIVE
    assert comparison.selected_path == ExecutionPath.RESEARCH
    assert comparison.budget == RESEARCH_BUDGET
    assert unsupported.decision.complexity == ComplexityClass.UNSUPPORTED
    assert unsupported.selected_path == ExecutionPath.UNSUPPORTED
    assert unsupported.budget == UNSUPPORTED_BUDGET
    assert unsupported.planned_retrieval_calls == 0
    assert unresolved.decision.requires_clarification is True


def test_all_route_classes_have_finite_trace_and_usage_is_zero():
    router = ComplexityRouter()
    examples = {
        ComplexityClass.SIMPLE_LOOKUP: "What was Apple's revenue in FY2024?",
        ComplexityClass.SINGLE_DOCUMENT: "What was Apple's operating margin in the FY2024 10-K?",
        ComplexityClass.NUMERICAL: "Calculate Apple's revenue growth from FY2023 to FY2024.",
        ComplexityClass.COMPARATIVE: "Compare Apple and Microsoft revenue in FY2024.",
        ComplexityClass.MULTI_HOP: "Why did Apple's operating income change between FY2023 and FY2024?",
        ComplexityClass.DEEP_RESEARCH: "Provide a comprehensive analysis of Apple's revenue, operating income, and net income from FY2021 to FY2023.",
        ComplexityClass.UNSUPPORTED: "What was Acme's revenue in FY2024?",
    }

    for expected, question in examples.items():
        run = router.route(question)
        assert run.decision.complexity == expected
        assert run.graph_steps_used <= run.budget.max_graph_steps
        assert run.planned_task_count <= run.budget.max_planned_tasks
        assert run.planned_retrieval_calls <= run.budget.max_retrieval_calls
        assert run.actual_retrieval_calls == 0
        assert run.actual_llm_calls == 0
        assert run.actual_tool_calls == 0
        assert run.actual_tokens == 0
        assert run.estimated_cost_usd == 0.0
        assert run.route_trace[0] == "classify_request"


def test_router_can_use_verified_corpus_company_aliases_for_fast_lookup():
    corpus_map = CorpusMap.from_chunks(
        [
            {
                "document_id": "GLOBEX_2024_10K",
                "company": "Globex Holdings",
                "ticker": "GLBX",
                "doc_type": "10-K",
                "reporting_periods": ["FY2024"],
                "section": "document",
            }
        ],
        index_generation_id="router-index",
    )

    run = ComplexityRouter(corpus_map).route(
        "What was Globex Holdings revenue in FY2024?"
    )

    assert run.decision.complexity == ComplexityClass.SIMPLE_LOOKUP
    assert run.selected_path == ExecutionPath.FAST
    assert run.research_plan is not None
    assert run.research_plan.index_generation_id == "router-index"
    assert run.research_plan.tasks[0].source_availability == SourceAvailability.AVAILABLE


def test_unsupported_questions_never_receive_research_or_tool_budget():
    router = ComplexityRouter()
    for question in (
        "Forecast Apple's revenue next year.",
        "What was Acme's revenue in FY2024?",
        "What was Apple's revenue growth in FY2024?",
    ):
        run = router.route(question)
        assert run.selected_path == ExecutionPath.UNSUPPORTED
        assert run.budget.max_tool_calls == 0
        assert run.budget.max_retrieval_calls == 0
        assert run.budget.max_llm_calls == 0
        assert run.planned_retrieval_calls == 0
        assert run.research_plan is None


def test_authored_fixture_audit_records_route_errors_without_model_calls():
    result = evaluate_complexity_routing()
    fixture = result["benchmark"]["synthetic_policy_fixture"]

    assert len(SYNTHETIC_ROUTING_CASES) == 56
    assert fixture["class_accuracy"] == 1.0
    assert fixture["unnecessary_research_path_selection_rate"] == 0.0
    assert fixture["incorrect_fast_path_rate"] == 0.0
    assert fixture["unsupported_routing_errors"] == 0
    assert result["usage"]["synthetic_policy_fixture"]["actual_tool_calls"] == 0
    assert result["usage"]["synthetic_policy_fixture"]["actual_multi_agent_invocations"] == 0
    assert result["usage"]["synthetic_policy_fixture"]["actual_tokens"] == 0
    assert result["route_budgets"]["enforced_budget_violations"] == 0
