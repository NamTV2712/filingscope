from decimal import Decimal
from types import SimpleNamespace

from src.agent.adaptive_retrieval import AdaptiveStopReason
from src.decision.models import (
    DecisionAction,
    DecisionResult,
    EvidenceCoverage,
    QuestionRequirements,
)
from src.evaluation.end_to_end_evaluation import (
    EndToEndBenchmark,
    EndToEndCase,
    ProviderBudgetExceeded,
    _percentile,
    _CallBudget,
)
from src.evaluation.financebench_dataset import FinanceBenchCase
from src.evaluation.retrieval_adapter import RETRIEVAL_PRESETS
from src.generation.answer_generator import AnswerGenerationResult
from src.verification.models import ResponseDisposition, VerificationResult


def _decision() -> DecisionResult:
    return DecisionResult(
        action=DecisionAction.ANSWER,
        reason_code="requirements_satisfied",
        coverage=EvidenceCoverage(
            requirements=QuestionRequirements(question="What was Acme revenue for FY2023?")
        ),
        rationale="synthetic test result",
    )


def _fixture(generator, *, dry_run: bool, **benchmark_kwargs):
    case = FinanceBenchCase(
        case_id="case-1",
        company="Acme Inc.",
        doc_name="ACME_2023_10K",
        question="What was Acme revenue for FY2023?",
        gold_pages=(4,),
        question_type="single_hop",
        split="development",
    )
    evidence = {
        "chunk_id": "chunk-1",
        "company": "Acme Inc.",
        "ticker": "ACME",
        "doc_name": "ACME_2023_10K",
        "document_id": "ACME_2023_10K",
        "page_number": 4,
        "token_count": 10,
        "text": "Acme Inc. revenue for FY2023 was $100 million.",
    }
    predictions = {
        preset: {
            case.case_id: {
                "retrieved": [{"chunk_id": "chunk-1", "score": 1.0}],
                "latency_ms": 2.0,
            }
        }
        for preset in RETRIEVAL_PRESETS
    }

    class FakeController:
        def run(self, _question, initial_chunks):
            return SimpleNamespace(
                initial_decision=_decision(),
                final_decision=_decision(),
                evidence_chunks=tuple(initial_chunks),
                elapsed_ms=5.0,
                queries_used=0,
                rounds_used=0,
                trace=(),
                stop_reason=AdaptiveStopReason.EVIDENCE_SUFFICIENT,
            )

    benchmark = EndToEndBenchmark(
        cases=(EndToEndCase(case=case, gold_answer="Revenue was $100 million."),),
        chunks_by_id={"chunk-1": evidence},
        predictions=predictions,
        adaptive_controller=FakeController(),
        baseline_retrieval_adapter=None,
        generator=generator,
        dry_run=dry_run,
        max_provider_calls=10,
        max_provider_cost_usd=Decimal("1"),
        **benchmark_kwargs,
    )
    benchmark.decision_layer = SimpleNamespace(decide=lambda *_args, **_kwargs: _decision())
    return benchmark


def test_dry_run_plans_generation_without_false_answer_or_abstention_metrics() -> None:
    report = _fixture(None, dry_run=True).run()

    assert report["mode"] == "dry_run"
    assert report["generator"]["provider_calls_planned_or_made"] == 5
    for variant in ("A0", "A1", "A2", "A3", "A4", "A5"):
        assert report["variants"][variant]["metrics_status"] == "not_measured_during_dry_run"
    row = report["cases"][0]["variants"]
    assert row["A0"]["answer"] is None
    assert row["A0"]["abstained"] is None
    assert row["A0"]["numeric_score"] is None
    assert row["A0"]["text_score"] is None
    assert row["A5"]["generation_request_planned"] is False
    assert row["A5"]["generation_reused_from"] == "A4"
    assert report["variants"]["A5"]["generation_requests_planned"] == 0


def test_provider_run_calls_only_a0_through_a4_and_reuses_a4_for_a5(monkeypatch) -> None:
    class FakeGenerator:
        model_id = "fake-model"
        max_output_tokens = 32

        def __init__(self):
            self.calls = []

        def generate(self, question, evidence_chunks):
            self.calls.append((question, tuple(chunk["chunk_id"] for chunk in evidence_chunks)))
            return AnswerGenerationResult(
                answer="Revenue was $100 million [Source 1].",
                model_id=self.model_id,
                prompt_tokens=10,
                completion_tokens=8,
                estimated_cost_usd=Decimal("0.0001"),
                latency_ms=1.5,
            )

    monkeypatch.setattr(
        "src.evaluation.end_to_end_evaluation._verifier_payload",
        lambda *_args, **_kwargs: (
            VerificationResult(
                disposition=ResponseDisposition.VERIFIED,
                valid_citation_count=1,
                invalid_citation_count=0,
                supported_claim_count=1,
                partial_claim_count=0,
                unsupported_claim_count=0,
                contradicted_claim_count=0,
                unverifiable_claim_count=0,
            ),
            0.25,
        ),
    )
    generator = FakeGenerator()
    report = _fixture(generator, dry_run=False).run()

    assert len(generator.calls) == 5
    assert report["generator"]["provider_calls_planned_or_made"] == 5
    assert report["generator"]["reported_cost_estimate_usd"] == "0.0005"
    assert report["cases"][0]["variants"]["A0"]["numeric_score"]["exact_match"] is True
    assert report["cases"][0]["variants"]["A5"]["variant"] == "A5"
    assert report["cases"][0]["variants"]["A5"]["answer"] == "Revenue was $100 million [Source 1]."
    assert report["cases"][0]["variants"]["A5"]["timing_ms"]["end_to_end_measured_components"] == round(
        report["cases"][0]["variants"]["A4"]["timing_ms"]["end_to_end_measured_components"] + 0.25,
        3,
    )


def test_a5_abstains_on_partially_supported_answers(monkeypatch) -> None:
    class FakeGenerator:
        model_id = "fake-model"
        max_output_tokens = 32

        def generate(self, _question, _evidence_chunks):
            return AnswerGenerationResult(
                answer="Revenue was $100 million [Source 1]. It doubled [Source 2].",
                model_id=self.model_id,
                prompt_tokens=10,
                completion_tokens=12,
                estimated_cost_usd=Decimal("0.0001"),
                latency_ms=1.0,
            )

    monkeypatch.setattr(
        "src.evaluation.end_to_end_evaluation._verifier_payload",
        lambda *_args, **_kwargs: (
            VerificationResult(
                disposition=ResponseDisposition.PARTIAL,
                valid_citation_count=1,
                invalid_citation_count=1,
                supported_claim_count=1,
                partial_claim_count=0,
                unsupported_claim_count=1,
                contradicted_claim_count=0,
                unverifiable_claim_count=0,
            ),
            0.25,
        ),
    )

    report = _fixture(FakeGenerator(), dry_run=False).run()
    variants = report["cases"][0]["variants"]

    assert variants["A4"]["abstained"] is False
    assert variants["A5"]["abstained"] is True
    assert variants["A5"]["final_disposition"] == "PARTIAL"
    assert "could not find sufficient information" in variants["A5"]["answer"]


def test_provider_checkpoint_reuses_completed_responses_on_resume() -> None:
    class FakeGenerator:
        model_id = "fake-model"
        max_output_tokens = 32

        def __init__(self):
            self.calls = 0

        def generate(self, _question, _evidence_chunks):
            self.calls += 1
            return AnswerGenerationResult(
                answer="Revenue was $100 million [Source 1].",
                model_id=self.model_id,
                prompt_tokens=10,
                completion_tokens=8,
                estimated_cost_usd=Decimal("0.0001"),
                latency_ms=1.0,
            )

    state_updates = []
    metadata = {"source_fingerprint": "test"}
    first_generator = FakeGenerator()
    first = _fixture(
        first_generator,
        dry_run=False,
        checkpoint_metadata=metadata,
        checkpoint_callback=state_updates.append,
    ).run()

    assert first_generator.calls == 5
    checkpoint = state_updates[-1]
    assert len(checkpoint["completed_cases"]) == 1
    assert checkpoint["current_run_provider_attempts"] == 5

    resumed_generator = FakeGenerator()
    resumed = _fixture(
        resumed_generator,
        dry_run=False,
        checkpoint_metadata=metadata,
        checkpoint_state=checkpoint,
    ).run()

    assert resumed_generator.calls == 0
    assert resumed["cases"] == first["cases"]
    assert resumed["generator"]["provider_calls_planned_or_made"] == 5


def test_provider_checkpoint_counts_failed_attempt_and_preserves_budget() -> None:
    class FailingGenerator:
        model_id = "fake-model"
        max_output_tokens = 32

        def generate(self, _question, _evidence_chunks):
            raise ConnectionError("synthetic disconnected request")

    state_updates = []
    metadata = {"source_fingerprint": "test"}
    try:
        _fixture(
            FailingGenerator(),
            dry_run=False,
            checkpoint_metadata=metadata,
            checkpoint_callback=state_updates.append,
        ).run()
    except ConnectionError:
        pass
    else:
        raise AssertionError("the synthetic provider failure should propagate")

    checkpoint = state_updates[-1]
    assert checkpoint["current_run_provider_attempts"] == 1
    assert checkpoint["budget"]["calls_reserved"] == 1
    assert Decimal(checkpoint["budget"]["cost_reserved_usd"]) > 0

    class RecoveryGenerator:
        model_id = "fake-model"
        max_output_tokens = 32

        def generate(self, _question, _evidence_chunks):
            return AnswerGenerationResult(
                answer="Revenue was $100 million [Source 1].",
                model_id=self.model_id,
                prompt_tokens=10,
                completion_tokens=8,
                estimated_cost_usd=Decimal("0.0001"),
                latency_ms=1.0,
            )

    resumed = _fixture(
        RecoveryGenerator(),
        dry_run=False,
        checkpoint_metadata=metadata,
        checkpoint_state=checkpoint,
    ).run()
    assert resumed["generator"]["provider_calls_planned_or_made"] == 6
    assert resumed["generator"]["provider_attempts_current_run"] == 6
    assert resumed["generator"]["successful_generation_responses_used_for_metrics"] == 5


def test_provider_cost_guard_includes_reported_and_prior_cost() -> None:
    budget = _CallBudget(
        max_calls=3,
        max_cost_usd=Decimal("0.10"),
        initial_calls=1,
        prior_cost_upper_bound_usd=Decimal("0.04"),
    )
    budget.reserve(estimate=Decimal("0.03"))
    budget.settle(
        estimate=Decimal("0.03"),
        result=AnswerGenerationResult(
            answer="ok",
            model_id="fake-model",
            prompt_tokens=1,
            completion_tokens=1,
            estimated_cost_usd=Decimal("0.02"),
            latency_ms=1.0,
        ),
    )

    try:
        budget.reserve(estimate=Decimal("0.05"))
    except ProviderBudgetExceeded as error:
        assert str(error) == "provider_cost_budget_exhausted"
    else:
        raise AssertionError("the cumulative cost guard must account for settled usage")


def test_percentile_sorts_unsorted_measurements_before_nearest_rank() -> None:
    assert _percentile([100.0, 1.0, 50.0, 2.0], 0.50) == 2.0
    assert _percentile([100.0, 1.0, 50.0, 2.0], 0.95) == 100.0
    assert _percentile([], 0.95) is None
