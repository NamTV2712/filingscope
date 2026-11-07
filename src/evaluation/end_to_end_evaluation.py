"""A0–A5 end-to-end FinanceBench evaluation orchestration."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from math import ceil
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from configs.end_to_end import (
    BENCHMARK_ID,
    GENERATOR_MAX_INPUT_TOKENS,
    GENERATOR_MAX_OUTPUT_TOKENS,
    GENERATOR_MODEL_ID,
    GENERATOR_PRICE_CHECKED_AT,
    PROMPT_VERSION,
    RETRIEVAL_CANDIDATE_POOL,
    RETRIEVAL_TOP_K,
)
from configs.financebench import FINANCEBENCH_GITHUB_REVISION
from src.agent.adaptive_retrieval import AdaptiveRetrievalController, AdaptiveStopReason
from src.decision.company_catalog import CompanyCatalog
from src.decision.models import DecisionAction, DecisionBudget
from src.decision.policy import EvidenceDecisionLayer
from src.evaluation.answer_metrics import score_numeric_answer, score_text_answer
from src.evaluation.financebench_dataset import FinanceBenchCase, load_financebench_cases
from src.evaluation.retrieval_adapter import (
    RETRIEVAL_PRESETS,
    FinanceBenchRetrievalAdapter,
)
from src.generation.answer_generator import (
    AnswerGenerationResult,
    AnswerGenerator,
    build_generation_messages,
    estimate_max_cost_usd,
    estimate_prompt_tokens,
    estimate_prompt_tokens_with_margin,
    is_fallback_answer,
)
from src.verification import ClaimLevelVerifier
from src.verification.models import ResponseDisposition, VerificationResult


E2E_VARIANTS = ("A0", "A1", "A2", "A3", "A4", "A5")
BASELINE_PRESETS = {"A0": "dense", "A1": "hybrid", "A2": "hybrid_rerank"}
P1_REQUIRED_FILES = (
    "run_manifest.json",
    "metrics.json",
    "index_manifest.json",
    "corpus_chunks.jsonl",
    "predictions_bm25.jsonl",
    "predictions_dense.jsonl",
    "predictions_hybrid.jsonl",
    "predictions_hybrid_rerank.jsonl",
)
_SPLIT_ORDER = {"development": 0, "validation": 1, "held_out": 2}


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    """Return the nearest-rank percentile independent of input ordering."""
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    rank = max(1, ceil(len(ordered) * quantile))
    return ordered[rank - 1]


@dataclass(frozen=True)
class EndToEndCase:
    case: FinanceBenchCase
    gold_answer: str


class ProviderBudgetExceeded(RuntimeError):
    """Raised before a provider request when a frozen P5 budget would be exceeded."""


class _CallBudget:
    def __init__(
        self,
        *,
        max_calls: int,
        max_cost_usd: Decimal,
        initial_calls: int = 0,
        prior_cost_upper_bound_usd: Decimal = Decimal("0"),
    ):
        if max_calls < 0 or max_cost_usd < 0:
            raise ValueError("Provider call and cost budgets must be non-negative")
        if initial_calls < 0 or prior_cost_upper_bound_usd < 0:
            raise ValueError("Prior provider usage must be non-negative")
        if initial_calls > max_calls or prior_cost_upper_bound_usd > max_cost_usd:
            raise ValueError("Prior provider usage already exceeds the configured budget")
        self.max_calls = max_calls
        self.max_cost_usd = max_cost_usd
        self.calls_reserved = initial_calls
        self.prior_cost_upper_bound_usd = prior_cost_upper_bound_usd
        self.cost_reserved = Decimal(0)
        self.cost_reported = Decimal(0)

    def reserve(self, *, estimate: Decimal) -> None:
        if self.calls_reserved >= self.max_calls:
            raise ProviderBudgetExceeded("provider_call_budget_exhausted")
        total_cost_upper_bound = (
            self.prior_cost_upper_bound_usd + self.cost_reported + self.cost_reserved + estimate
        )
        if total_cost_upper_bound > self.max_cost_usd:
            raise ProviderBudgetExceeded("provider_cost_budget_exhausted")
        self.calls_reserved += 1
        self.cost_reserved += estimate

    def settle(self, *, estimate: Decimal, result: AnswerGenerationResult) -> None:
        self.cost_reserved -= estimate
        actual_estimate = result.estimated_cost_usd
        self.cost_reported += actual_estimate if actual_estimate is not None else estimate
        if self.prior_cost_upper_bound_usd + self.cost_reported + self.cost_reserved > self.max_cost_usd:
            raise ProviderBudgetExceeded("reported_provider_cost_exceeded_budget")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            records.append(value)
    return records


def find_complete_retrieval_run(data_dir: Path) -> Path:
    """Find the single complete P1 artifact set matching the pinned dataset."""
    runs_dir = data_dir / "runs"
    candidates = [
        child
        for child in runs_dir.iterdir()
        if child.is_dir() and all((child / name).is_file() for name in P1_REQUIRED_FILES)
    ] if runs_dir.is_dir() else []
    valid: list[Path] = []
    for candidate in candidates:
        manifest = json.loads((candidate / "run_manifest.json").read_text(encoding="utf-8"))
        if (
            manifest.get("dataset_revision") == FINANCEBENCH_GITHUB_REVISION
            and manifest.get("prediction_artifacts_exclude_gold_answers") is True
            and set(manifest.get("retrieval", {}).get("presets", ())) >= set(RETRIEVAL_PRESETS)
        ):
            valid.append(candidate)
    fingerprints = {
        json.loads((path / "run_manifest.json").read_text(encoding="utf-8")).get("corpus_fingerprint")
        for path in valid
    }
    if not valid:
        raise FileNotFoundError(
            "No complete pinned FinanceBench retrieval run exists; run "
            "python -m scripts.run_financebench_retrieval first"
        )
    if len(valid) != 1 or len(fingerprints) != 1:
        raise ValueError("Multiple complete FinanceBench runs exist; pass --retrieval-run-dir explicitly")
    return valid[0]


def load_end_to_end_cases(data_dir: Path) -> tuple[EndToEndCase, ...]:
    """Join split metadata to gold answers at the evaluation boundary only."""
    cases_path = data_dir / "source" / "financebench_open_source.jsonl"
    if not cases_path.is_file():
        raise FileNotFoundError(f"FinanceBench cases are missing: {cases_path}")
    cases = load_financebench_cases(cases_path)
    raw_by_id = {
        row.get("financebench_id"): row
        for row in _read_jsonl(cases_path)
    }
    output: list[EndToEndCase] = []
    for case in cases:
        record = raw_by_id.get(case.case_id)
        answer = record.get("answer") if isinstance(record, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError(f"FinanceBench case {case.case_id!r} has no gold answer")
        output.append(EndToEndCase(case=case, gold_answer=answer))
    return tuple(output)


def load_retrieval_artifacts(
    run_dir: Path,
    cases: Sequence[EndToEndCase],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, dict[str, Any]]], dict[str, Any]]:
    """Validate P1 metadata and load source text by retrieved chunk identity."""
    missing = [name for name in P1_REQUIRED_FILES if not (run_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"P1 run is missing required artifact(s): {', '.join(missing)}")
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    index_manifest = json.loads((run_dir / "index_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset_revision") != FINANCEBENCH_GITHUB_REVISION:
        raise ValueError("P1 run uses a different FinanceBench dataset revision")
    if not manifest.get("prediction_artifacts_exclude_gold_answers"):
        raise ValueError("P1 retrieval predictions must exclude gold answers")
    expected_corpus = manifest.get("corpus_fingerprint")
    if index_manifest.get("corpus_fingerprint") != expected_corpus:
        raise ValueError("P1 index and run corpus fingerprints do not match")

    chunks = _read_jsonl(run_dir / "corpus_chunks.jsonl")
    chunks_by_id = {
        str(chunk["chunk_id"]): chunk
        for chunk in chunks
        if isinstance(chunk.get("chunk_id"), str) and chunk.get("chunk_id")
    }
    if len(chunks_by_id) != len(chunks):
        raise ValueError("P1 corpus contains duplicate or missing chunk identities")
    expected_case_ids = {item.case.case_id for item in cases}
    predictions: dict[str, dict[str, dict[str, Any]]] = {}
    for preset in RETRIEVAL_PRESETS:
        records = _read_jsonl(run_dir / f"predictions_{preset}.jsonl")
        by_case = {str(record.get("case_id")): record for record in records}
        if len(by_case) != len(records) or not expected_case_ids.issubset(by_case):
            raise ValueError(f"P1 {preset} predictions do not cover the selected FinanceBench cases")
        predictions[preset] = by_case
        for record in records:
            for retrieved in record.get("retrieved", ()):
                chunk_id = retrieved.get("chunk_id") if isinstance(retrieved, dict) else None
                if not isinstance(chunk_id, str) or chunk_id not in chunks_by_id:
                    raise ValueError(f"P1 {preset} prediction references an unknown corpus chunk")
    return chunks_by_id, predictions, {"run": manifest, "index": index_manifest}


def _selected_cases(
    cases: Sequence[EndToEndCase],
    *,
    split: str | None,
    max_cases: int | None,
) -> tuple[EndToEndCase, ...]:
    selected = sorted(
        (item for item in cases if split is None or item.case.split == split),
        key=lambda item: (_SPLIT_ORDER.get(item.case.split, 99), item.case.case_id),
    )
    if max_cases is not None:
        if max_cases < 1:
            raise ValueError("max_cases must be positive")
        selected = selected[:max_cases]
    return tuple(selected)


def _materialize_evidence(
    prediction: Mapping[str, Any],
    chunks_by_id: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in prediction.get("retrieved", ()):
        chunk_id = str(item["chunk_id"])
        output.append({
            **chunks_by_id[chunk_id],
            "score": item.get("score"),
            "score_kind": item.get("score_kind"),
        })
    return output


def _gold_page_coverage(case: FinanceBenchCase, evidence: Sequence[Mapping[str, Any]]) -> float:
    observed = {
        chunk.get("page_number")
        for chunk in evidence
        if chunk.get("doc_name") == case.doc_name and isinstance(chunk.get("page_number"), int)
    }
    return len(observed.intersection(case.gold_pages)) / max(1, len(case.gold_pages))


def _verifier_payload(answer: str, question: str, evidence: Sequence[Mapping[str, Any]]) -> tuple[VerificationResult, float]:
    started = perf_counter()
    result = ClaimLevelVerifier().verify(question, answer, evidence)
    return result, max(0.0, (perf_counter() - started) * 1000)


class EndToEndBenchmark:
    """Run frozen A0–A5 variants over retrieval artifacts and optional generation."""

    def __init__(
        self,
        *,
        cases: Sequence[EndToEndCase],
        chunks_by_id: Mapping[str, dict[str, Any]],
        predictions: Mapping[str, Mapping[str, dict[str, Any]]],
        adaptive_controller: AdaptiveRetrievalController,
        baseline_retrieval_adapter: FinanceBenchRetrievalAdapter | None,
        generator: AnswerGenerator | None,
        dry_run: bool,
        max_provider_calls: int = 0,
        max_provider_cost_usd: Decimal = Decimal("0"),
        prior_provider_attempts: int = 0,
        prior_modeled_cost_upper_bound_usd: Decimal = Decimal("0"),
        split: str | None = None,
        max_cases: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        checkpoint_state: Mapping[str, Any] | None = None,
        checkpoint_callback: Callable[[dict[str, Any]], None] | None = None,
        checkpoint_metadata: Mapping[str, Any] | None = None,
    ):
        if dry_run and generator is not None:
            raise ValueError("dry_run and a live answer generator are mutually exclusive")
        if not dry_run and generator is None:
            raise ValueError("provider-backed evaluation requires an answer generator")
        self.cases = _selected_cases(cases, split=split, max_cases=max_cases)
        self.chunks_by_id = chunks_by_id
        self.predictions = predictions
        self.adaptive_controller = adaptive_controller
        self.baseline_retrieval_adapter = baseline_retrieval_adapter
        self.generator = generator
        self.dry_run = dry_run
        self.prior_provider_attempts = prior_provider_attempts
        self.prior_modeled_cost_upper_bound_usd = prior_modeled_cost_upper_bound_usd
        self.budget = _CallBudget(
            max_calls=max_provider_calls,
            max_cost_usd=max_provider_cost_usd,
            initial_calls=prior_provider_attempts,
            prior_cost_upper_bound_usd=prior_modeled_cost_upper_bound_usd,
        )
        rows = [
            {key: chunk.get(key) for key in ("company", "ticker", "doc_name")}
            for chunk in chunks_by_id.values()
        ]
        self.decision_layer = EvidenceDecisionLayer(
            catalog=CompanyCatalog.from_document_rows(rows)
        )
        self.checkpoint_metadata = dict(checkpoint_metadata or {})
        self.checkpoint_callback = checkpoint_callback
        state = dict(checkpoint_state or {})
        if state:
            if state.get("checkpoint_version") != 1:
                raise ValueError("Unsupported P5 provider checkpoint version")
            if state.get("metadata") != self.checkpoint_metadata:
                raise ValueError("P5 checkpoint metadata does not match the current frozen run")
            expected_case_ids = [item.case.case_id for item in self.cases]
            if state.get("selected_case_ids") != expected_case_ids:
                raise ValueError("P5 checkpoint case selection does not match the current run")
            budget_state = state.get("budget", {})
            self.budget.calls_reserved = int(budget_state.get("calls_reserved", self.budget.calls_reserved))
            self.budget.cost_reserved = Decimal(str(budget_state.get("cost_reserved_usd", "0")))
            self.budget.cost_reported = Decimal(str(budget_state.get("cost_reported_usd", "0")))
            current_attempts = int(state.get("current_run_provider_attempts", 0))
            if self.budget.calls_reserved > self.budget.max_calls:
                raise ValueError("P5 checkpoint provider attempts exceed the configured call budget")
            if self.budget.calls_reserved < self.prior_provider_attempts + current_attempts:
                raise ValueError("P5 checkpoint attempt counters are inconsistent")
            if (
                self.prior_modeled_cost_upper_bound_usd
                + self.budget.cost_reserved
                + self.budget.cost_reported
                > self.budget.max_cost_usd
            ):
                raise ValueError("P5 checkpoint usage exceeds the configured modeled cost budget")
        self.call_count = int(state.get("current_run_provider_attempts", 0))
        self.generation_cache: dict[str, dict[str, Any]] = dict(state.get("generation_cache", {}))
        self.generation_estimates: dict[str, dict[str, Any]] = dict(state.get("generation_estimates", {}))
        self.completed_cases: dict[str, dict[str, Any]] = {
            str(case["case_id"]): dict(case) for case in state.get("completed_cases", [])
        }
        self.reported_prompt_tokens = int(state.get("reported_prompt_tokens", 0))
        self.reported_completion_tokens = int(state.get("reported_completion_tokens", 0))
        self.progress_callback = progress_callback

    def _checkpoint(self) -> None:
        if self.checkpoint_callback is None or self.dry_run:
            return
        self.checkpoint_callback({
            "checkpoint_version": 1,
            "metadata": self.checkpoint_metadata,
            "selected_case_ids": [item.case.case_id for item in self.cases],
            "current_run_provider_attempts": self.call_count,
            "budget": {
                "calls_reserved": self.budget.calls_reserved,
                "cost_reserved_usd": str(self.budget.cost_reserved),
                "cost_reported_usd": str(self.budget.cost_reported),
            },
            "reported_prompt_tokens": self.reported_prompt_tokens,
            "reported_completion_tokens": self.reported_completion_tokens,
            "generation_estimates": self.generation_estimates,
            "generation_cache": self.generation_cache,
            "completed_cases": list(self.completed_cases.values()),
        })

    def run(self) -> dict[str, Any]:
        per_case: list[dict[str, Any]] = []
        for item in self.cases:
            saved_case = self.completed_cases.get(item.case.case_id)
            if saved_case is not None:
                per_case.append(saved_case)
                if self.progress_callback is not None:
                    self.progress_callback(len(per_case), len(self.cases))
                continue
            case_results: dict[str, dict[str, Any]] = {}
            query_embedding = None
            query_embedding_ms = 0.0
            if self.baseline_retrieval_adapter is not None:
                embedding_started = perf_counter()
                query_embedding = self.baseline_retrieval_adapter.retriever.embed_query(
                    item.case.question
                )
                query_embedding_ms = max(0.0, (perf_counter() - embedding_started) * 1000)
            replay_by_preset: dict[str, dict[str, Any]] = {}
            for variant, preset in BASELINE_PRESETS.items():
                prediction = self.predictions[preset][item.case.case_id]
                evidence = _materialize_evidence(prediction, self.chunks_by_id)
                retrieval_stages: dict[str, float] = {}
                replay_matches_p1: bool | None = None
                if self.baseline_retrieval_adapter is not None:
                    replayed = self.baseline_retrieval_adapter.retrieve(
                        item.case.question,
                        preset=preset,
                        query_embedding=query_embedding,
                        timing_sink=retrieval_stages,
                    )
                    replay_stages = dict(retrieval_stages)
                    replay_stages["query_embedding_ms"] = query_embedding_ms
                    replay_matches_p1 = [record["chunk_id"] for record in replayed] == [
                        str(chunk["chunk_id"]) for chunk in evidence
                    ]
                    retrieval_ms = query_embedding_ms + retrieval_stages.get("total_ms", 0.0)
                else:
                    replay_stages = {}
                    retrieval_ms = float(prediction.get("latency_ms", 0.0))
                replay_by_preset[preset] = {
                    "retrieval_ms": retrieval_ms,
                    "stages": replay_stages,
                    "matches_p1": replay_matches_p1,
                    "p1_reference_ms": float(prediction.get("latency_ms", 0.0)),
                }
                answer_result, estimate = self._generate(
                    item.case.case_id, variant, item.case.question, evidence
                )
                answer = answer_result.answer if answer_result else ""
                abstained = self.dry_run or not evidence or is_fallback_answer(answer)
                verification, verification_ms = _verifier_payload(answer, item.case.question, evidence) if answer else (None, 0.0)
                case_results[variant] = self._variant_record(
                    item,
                    variant=variant,
                    enabled_component={"A0": "dense_retrieval", "A1": "hybrid_retrieval", "A2": "hybrid_reranking"}[variant],
                    answer=answer,
                    evidence=evidence,
                    answer_result=answer_result,
                    verification=verification,
                    abstained=abstained,
                    decision_action=None,
                    decision_reason=None,
                    retrieval_ms=retrieval_ms,
                    decision_ms=0.0,
                    retrieval_stage_ms=replay_stages,
                    retrieval_replay_matches_p1=replay_matches_p1,
                    p1_retrieval_reference_ms=float(prediction.get("latency_ms", 0.0)),
                    verification_ms=verification_ms,
                    adaptive_queries=0,
                    adaptive_rounds=0,
                    generation_estimate=estimate,
                    generation_request_planned=estimate is not None,
                )

            reranked_prediction = self.predictions["hybrid_rerank"][item.case.case_id]
            initial_evidence = _materialize_evidence(reranked_prediction, self.chunks_by_id)
            rerank_replay = replay_by_preset.get("hybrid_rerank", {})
            decision_started = perf_counter()
            decision = self.decision_layer.decide(
                item.case.question,
                initial_evidence,
                budget=DecisionBudget(remaining_retrieval_attempts=0),
            )
            decision_ms = max(0.0, (perf_counter() - decision_started) * 1000)
            if decision.action == DecisionAction.ANSWER:
                answer_result, estimate = self._generate(
                    item.case.case_id, "A3", item.case.question, initial_evidence
                )
                answer = answer_result.answer if answer_result else ""
                abstained = self.dry_run or not answer or is_fallback_answer(answer)
            else:
                answer_result, estimate, answer, abstained = None, None, "", True
            verification, verification_ms = _verifier_payload(answer, item.case.question, initial_evidence) if answer else (None, 0.0)
            case_results["A3"] = self._variant_record(
                item,
                variant="A3",
                enabled_component="evidence_decision",
                answer=answer,
                evidence=initial_evidence,
                answer_result=answer_result,
                verification=verification,
                abstained=abstained,
                decision_action=decision.action.value,
                decision_reason=decision.reason_code,
                retrieval_ms=float(rerank_replay.get("retrieval_ms", reranked_prediction.get("latency_ms", 0.0))),
                decision_ms=decision_ms,
                retrieval_stage_ms=rerank_replay.get("stages", {}),
                retrieval_replay_matches_p1=rerank_replay.get("matches_p1"),
                p1_retrieval_reference_ms=float(reranked_prediction.get("latency_ms", 0.0)),
                verification_ms=verification_ms,
                adaptive_queries=0,
                adaptive_rounds=0,
                generation_estimate=estimate,
                generation_request_planned=estimate is not None,
            )

            adaptive_started = perf_counter()
            adaptive = self.adaptive_controller.run(
                item.case.question,
                initial_evidence,
            )
            adaptive_wall_ms = max(0.0, (perf_counter() - adaptive_started) * 1000)
            adaptive_evidence = [dict(chunk) for chunk in adaptive.evidence_chunks]
            if adaptive.final_decision.action == DecisionAction.ANSWER:
                answer_result, estimate = self._generate(
                    item.case.case_id, "A4", item.case.question, adaptive_evidence
                )
                answer = answer_result.answer if answer_result else ""
                abstained = self.dry_run or not answer or is_fallback_answer(answer)
            else:
                answer_result, estimate, answer, abstained = None, None, "", True
            verification, verification_ms = _verifier_payload(answer, item.case.question, adaptive_evidence) if answer else (None, 0.0)
            a4 = self._variant_record(
                item,
                variant="A4",
                enabled_component="adaptive_retrieval",
                answer=answer,
                evidence=adaptive_evidence,
                answer_result=answer_result,
                verification=verification,
                abstained=abstained,
                decision_action=adaptive.final_decision.action.value,
                decision_reason=adaptive.final_decision.reason_code,
                retrieval_ms=float(rerank_replay.get("retrieval_ms", reranked_prediction.get("latency_ms", 0.0))),
                decision_ms=0.0,
                adaptive_ms=adaptive_wall_ms,
                retrieval_stage_ms=rerank_replay.get("stages", {}),
                retrieval_replay_matches_p1=rerank_replay.get("matches_p1"),
                p1_retrieval_reference_ms=float(reranked_prediction.get("latency_ms", 0.0)),
                verification_ms=verification_ms,
                adaptive_queries=adaptive.queries_used,
                adaptive_rounds=adaptive.rounds_used,
                adaptive_initial_action=adaptive.initial_decision.action.value,
                generation_estimate=estimate,
                generation_request_planned=estimate is not None,
                adaptive_trace=[trace.model_dump(mode="json") for trace in adaptive.trace],
                adaptive_stop_reason=adaptive.stop_reason.value,
            )
            case_results["A4"] = a4

            a5 = dict(a4)
            a5["variant"] = "A5"
            a5["enabled_component"] = "claim_verification"
            a5["timing_ms"] = dict(a4["timing_ms"])
            a5["timing_ms"]["claim_verification_gate"] = a5["timing_ms"]["verifier_evaluation"]
            a5["timing_ms"]["end_to_end_measured_components"] = round(
                a5["timing_ms"]["end_to_end_measured_components"]
                + a5["timing_ms"]["claim_verification_gate"],
                3,
            )
            a5["generation_request_planned"] = False
            a5["generation_reused_from"] = "A4"
            if answer and verification is not None and not self.dry_run:
                if verification.disposition in {
                    ResponseDisposition.REJECTED,
                    ResponseDisposition.ABSTAIN,
                    ResponseDisposition.PARTIAL,
                }:
                    a5["answer"] = "I could not find sufficient information in the available documents to answer this question with confidence."
                    a5["abstained"] = True
                    a5["final_disposition"] = verification.disposition.value
                else:
                    a5["final_disposition"] = verification.disposition.value
            else:
                a5["final_disposition"] = "ABSTAIN" if a5["abstained"] else None
            a5["numeric_score"] = (
                score_numeric_answer(a5["answer"], item.gold_answer)
                if a5["answer"] and not self.dry_run
                else None
            )
            a5["text_score"] = (
                score_text_answer(a5["answer"], item.gold_answer)
                if a5["answer"] and not self.dry_run
                else None
            )
            a5["abstention_evidence_page_coverage"] = _gold_page_coverage(item.case, adaptive_evidence)
            case_results["A5"] = a5

            case_record = {
                "case_id": item.case.case_id,
                "split": item.case.split,
                "question_type": item.case.question_type,
                "gold_evidence_page_count": len(item.case.gold_pages),
                "variants": case_results,
            }
            per_case.append(case_record)
            self.completed_cases[item.case.case_id] = case_record
            self._checkpoint()
            if self.progress_callback is not None:
                self.progress_callback(len(per_case), len(self.cases))

        aggregates = {
            variant: self._aggregate(variant, per_case, dry_run=self.dry_run)
            for variant in E2E_VARIANTS
        }
        metrics_by_split = {
            split_name: {
                variant: self._aggregate(
                    variant,
                    [case for case in per_case if case["split"] == split_name],
                    dry_run=self.dry_run,
                )
                for variant in E2E_VARIANTS
            }
            for split_name in ("development", "validation", "held_out")
            if any(case["split"] == split_name for case in per_case)
        }
        retrieval_replay_summary = {}
        if self.baseline_retrieval_adapter is not None:
            for variant in BASELINE_PRESETS:
                flags = [
                    case["variants"][variant]["retrieval_replay_matches_p1"]
                    for case in per_case
                    if case["variants"][variant]["retrieval_replay_matches_p1"] is not None
                ]
                retrieval_replay_summary[variant] = {
                    "matched_case_count": sum(bool(flag) for flag in flags),
                    "compared_case_count": len(flags),
                    "match_rate": sum(bool(flag) for flag in flags) / len(flags) if flags else None,
                }
        prompt_token_estimate = sum(
            int(item["prompt_tokens_estimated"]) for item in self.generation_estimates.values()
        )
        prompt_cost_estimate = sum(
            (Decimal(str(item["cost_usd_estimated"])) for item in self.generation_estimates.values()),
            Decimal(0),
        )
        provider_calls_total = self.budget.calls_reserved if not self.dry_run else self.call_count
        combined_cost_upper_bound = (
            self.budget.prior_cost_upper_bound_usd
            + self.budget.cost_reported
            + self.budget.cost_reserved
        )
        return {
            "schema_version": 1,
            "benchmark": BENCHMARK_ID,
            "mode": "dry_run" if self.dry_run else "provider_backed",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "case_count": len(self.cases),
            "split_counts": dict(Counter(item.case.split for item in self.cases)),
            "generator": {
                "model_id": self.generator.model_id if self.generator else GENERATOR_MODEL_ID,
                "prompt_version": PROMPT_VERSION,
                "temperature": 0,
                "max_output_tokens": self.generator.max_output_tokens if self.generator else GENERATOR_MAX_OUTPUT_TOKENS,
                "price_checked_at": GENERATOR_PRICE_CHECKED_AT,
                "max_provider_calls": self.budget.max_calls,
                "max_provider_cost_usd": str(self.budget.max_cost_usd),
                "provider_calls_planned_or_made": provider_calls_total,
                "provider_attempts_current_run": self.call_count,
                "prior_provider_attempts": self.prior_provider_attempts,
                "successful_generation_responses_used_for_metrics": len(self.generation_cache),
                "reported_prompt_tokens": self.reported_prompt_tokens,
                "reported_completion_tokens": self.reported_completion_tokens,
                "preflight_prompt_tokens_estimated": prompt_token_estimate,
                "preflight_cost_estimate_usd": str(
                    prompt_cost_estimate
                    + self.prior_modeled_cost_upper_bound_usd
                    + self.budget.cost_reserved
                ),
                "preflight_cost_current_run_usd": str(prompt_cost_estimate),
                "prior_run_cost_upper_bound_usd": str(self.prior_modeled_cost_upper_bound_usd),
                "reported_cost_estimate_usd": str(self.budget.cost_reported),
                "combined_cost_upper_bound_usd": str(combined_cost_upper_bound),
                "prior_run_usage_available": self.prior_provider_attempts == 0,
            },
            "variants": aggregates,
            "metrics_by_split": metrics_by_split,
            "retrieval_replay_vs_p1": retrieval_replay_summary,
            "cases": per_case,
        }

    def _generate(
        self,
        case_id: str,
        variant: str,
        question: str,
        evidence: Sequence[Mapping[str, Any]],
    ) -> tuple[AnswerGenerationResult | None, dict[str, Any] | None]:
        if not evidence:
            return None, None
        cache_key = f"{case_id}:{variant}"
        quote = self.generation_estimates.get(cache_key)
        if quote is None:
            messages = build_generation_messages(question, evidence)
            prompt_tokens = estimate_prompt_tokens(messages)
            if prompt_tokens > GENERATOR_MAX_INPUT_TOKENS:
                raise ValueError(
                    f"Prompt exceeds the frozen input bound ({prompt_tokens} > {GENERATOR_MAX_INPUT_TOKENS})"
                )
            max_output_tokens = self.generator.max_output_tokens if self.generator else GENERATOR_MAX_OUTPUT_TOKENS
            estimate = estimate_max_cost_usd(
                prompt_tokens=prompt_tokens,
                max_output_tokens=max_output_tokens,
            )
            quote = {
                "prompt_tokens_estimated": prompt_tokens,
                "prompt_tokens_upper_bound_estimated": estimate_prompt_tokens_with_margin(prompt_tokens),
                "max_output_tokens": max_output_tokens,
                "cost_usd_estimated": str(estimate),
            }
            self.generation_estimates[cache_key] = quote
        if self.dry_run:
            self.call_count += 1
            return None, quote
        cached = self.generation_cache.get(cache_key)
        if cached is not None:
            return AnswerGenerationResult.model_validate(cached["result"]), quote
        assert self.generator is not None
        estimate = Decimal(str(quote["cost_usd_estimated"]))
        self.budget.reserve(estimate=estimate)
        self.call_count += 1
        self._checkpoint()
        result = self.generator.generate(question, evidence)
        self.generation_cache[cache_key] = {
            "result": result.model_dump(mode="json"),
            "estimate": quote,
        }
        self.reported_prompt_tokens += result.prompt_tokens or 0
        self.reported_completion_tokens += result.completion_tokens or 0
        try:
            self.budget.settle(estimate=estimate, result=result)
        finally:
            self._checkpoint()
        return result, quote

    def _variant_record(
        self,
        item: EndToEndCase,
        *,
        variant: str,
        enabled_component: str,
        answer: str,
        evidence: Sequence[Mapping[str, Any]],
        answer_result: AnswerGenerationResult | None,
        verification: VerificationResult | None,
        abstained: bool,
        decision_action: str | None,
        decision_reason: str | None,
        retrieval_ms: float,
        decision_ms: float,
        retrieval_stage_ms: Mapping[str, float] | None = None,
        retrieval_replay_matches_p1: bool | None = None,
        p1_retrieval_reference_ms: float | None = None,
        adaptive_ms: float = 0.0,
        verification_ms: float,
        adaptive_queries: int,
        adaptive_rounds: int,
        adaptive_initial_action: str | None = None,
        generation_estimate: dict[str, Any] | None,
        generation_request_planned: bool,
        adaptive_trace: list[dict[str, Any]] | None = None,
        adaptive_stop_reason: str | None = None,
    ) -> dict[str, Any]:
        final_answer = None if self.dry_run else (answer if not abstained else (
            "I could not find sufficient information in the available documents to answer this question with confidence."
        ))
        numeric_score = score_numeric_answer(final_answer, item.gold_answer) if final_answer is not None else None
        text_score = score_text_answer(final_answer, item.gold_answer) if final_answer is not None else None
        page_coverage = _gold_page_coverage(item.case, evidence)
        return {
            "variant": variant,
            "enabled_component": enabled_component,
            "answer": final_answer,
            "raw_answer": answer if answer and not self.dry_run else None,
            "abstained": None if self.dry_run else abstained,
            "decision_action": decision_action,
            "decision_reason": decision_reason,
            "evidence_chunk_ids": [str(chunk.get("chunk_id")) for chunk in evidence],
            "gold_evidence_page_coverage": page_coverage,
            "numeric_score": numeric_score,
            "text_score": text_score,
            "verification": verification.model_dump(mode="json") if verification else None,
            "retrieval_replay_matches_p1": retrieval_replay_matches_p1,
            "retrieval_stages_ms": dict(retrieval_stage_ms or {}),
            "generation": answer_result.model_dump(mode="json") if answer_result else None,
            "generation_estimate": generation_estimate,
            "generation_request_planned": generation_request_planned,
            "timing_ms": {
                "initial_retrieval": round(retrieval_ms, 3),
                "p1_retrieval_reference": round(p1_retrieval_reference_ms, 3)
                if p1_retrieval_reference_ms is not None else None,
                "decision_or_adaptive": round(decision_ms, 3),
                "adaptive_retrieval_controller": round(adaptive_ms, 3),
                "generation": round(answer_result.latency_ms, 3) if answer_result else 0.0,
                "verifier_evaluation": round(verification_ms, 3),
                "claim_verification_gate": 0.0,
                "end_to_end_measured_components": round(
                    retrieval_ms + decision_ms + adaptive_ms + (answer_result.latency_ms if answer_result else 0.0),
                    3,
                ),
            },
            "adaptive_queries": adaptive_queries,
            "adaptive_rounds": adaptive_rounds,
            "adaptive_initial_action": adaptive_initial_action,
            "adaptive_stop_reason": adaptive_stop_reason,
            "adaptive_trace": adaptive_trace or [],
        }

    @staticmethod
    def _aggregate(
        variant: str,
        per_case: Sequence[Mapping[str, Any]],
        *,
        dry_run: bool,
    ) -> dict[str, Any]:
        rows = [case["variants"][variant] for case in per_case]
        total = len(rows)
        if dry_run:
            estimates = [
                row["generation_estimate"]
                for row in rows
                if row["generation_request_planned"] and row["generation_estimate"]
            ]
            return {
                "metrics_status": "not_measured_during_dry_run",
                "case_count": total,
                "generation_requests_planned": sum(bool(row["generation_request_planned"]) for row in rows),
                "preflight_prompt_tokens_estimated": sum(int(item["prompt_tokens_estimated"]) for item in estimates),
                "preflight_max_cost_estimate_usd": str(sum(
                    (Decimal(item["cost_usd_estimated"]) for item in estimates), Decimal(0)
                )),
                "mean_gold_evidence_page_coverage": round(
                    statistics.mean(float(row["gold_evidence_page_coverage"]) for row in rows), 6
                ) if rows else None,
            }
        answered = [row for row in rows if not row["abstained"]]
        numeric_rows = [row["numeric_score"] for row in rows if row["numeric_score"]["scored"]]
        text_rows = [row["text_score"] for row in rows if row["text_score"]["scored"]]
        numeric_exact = sum(bool(row["exact_match"]) for row in numeric_rows)
        true_positive = sum(row["true_positive_count"] for row in numeric_rows)
        predicted = sum(row["predicted_numeric_count"] for row in numeric_rows)
        gold = sum(row["gold_numeric_count"] for row in numeric_rows)
        precision = true_positive / predicted if predicted else 0.0
        recall = true_positive / gold if gold else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        text_exact = sum(bool(row["exact_match"]) for row in text_rows)
        text_true_positive = sum(row["true_positive_token_count"] for row in text_rows)
        text_predicted = sum(row["predicted_token_count"] for row in text_rows)
        text_gold = sum(row["gold_token_count"] for row in text_rows)
        text_precision = text_true_positive / text_predicted if text_predicted else 0.0
        text_recall = text_true_positive / text_gold if text_gold else 0.0
        text_f1 = (
            2 * text_precision * text_recall / (text_precision + text_recall)
            if text_precision + text_recall else 0.0
        )
        answered_text_rows = [
            row["text_score"] for row in answered
            if row["text_score"] and row["text_score"]["scored"]
        ]
        answered_text_tp = sum(row["true_positive_token_count"] for row in answered_text_rows)
        answered_text_predicted = sum(row["predicted_token_count"] for row in answered_text_rows)
        answered_text_gold = sum(row["gold_token_count"] for row in answered_text_rows)
        answered_text_precision = answered_text_tp / answered_text_predicted if answered_text_predicted else 0.0
        answered_text_recall = answered_text_tp / answered_text_gold if answered_text_gold else 0.0
        answered_text_f1 = (
            2 * answered_text_precision * answered_text_recall
            / (answered_text_precision + answered_text_recall)
            if answered_text_precision + answered_text_recall else 0.0
        )
        verifier_rows = [row["verification"] for row in rows if row["verification"]]
        claim_status_counts: Counter[str] = Counter()
        citation_valid = citation_invalid = 0
        unverified_answer_count = 0
        for result in verifier_rows:
            for claim in result.get("claims", []):
                claim_status_counts[claim["status"]] += 1
            citation_valid += int(result.get("valid_citation_count", 0))
            citation_invalid += int(result.get("invalid_citation_count", 0))
            if result.get("disposition") in {"REJECTED", "ABSTAIN", "PARTIAL"}:
                unverified_answer_count += 1
        abstained = total - len(answered)
        all_claim_count = sum(claim_status_counts.values())
        unsupported_claim_count = sum(
            count for status, count in claim_status_counts.items()
            if status in {"UNSUPPORTED", "CONTRADICTED"}
        )
        correct_abstention_proxy = sum(
            bool(row["abstained"]) and row["gold_evidence_page_coverage"] < 1.0
            for row in rows
        )
        false_abstention_proxy = sum(
            bool(row["abstained"]) and row["gold_evidence_page_coverage"] >= 1.0
            for row in rows
        )
        exact_answered = sum(
            bool(row["numeric_score"]["exact_match"])
            for row in answered
            if row["numeric_score"]["scored"]
        )
        answered_numeric = sum(
            bool(row["numeric_score"]["scored"])
            for row in answered
        )
        latencies = sorted(float(row["timing_ms"]["end_to_end_measured_components"]) for row in rows)
        generation_rows = [
            row for row in rows
            if row["generation_request_planned"] and row["generation"]
        ]
        generation_cost = Decimal(0)
        for row in generation_rows:
            generation = row["generation"]
            cost = generation.get("estimated_cost_usd")
            if cost is None and row.get("generation_estimate"):
                cost = row["generation_estimate"].get("cost_usd_estimated")
            if cost is not None:
                generation_cost += Decimal(str(cost))
        adaptive_required_cases = [
            row for row in rows if row.get("adaptive_initial_action") == DecisionAction.RETRIEVE_MORE.value
        ]
        adaptive_resolved_cases = sum(
            row.get("decision_action") == DecisionAction.ANSWER.value
            for row in adaptive_required_cases
        )
        budget_stop_reasons = {
            AdaptiveStopReason.RETRIEVAL_BUDGET_EXHAUSTED.value,
            AdaptiveStopReason.QUERY_BUDGET_EXHAUSTED.value,
            AdaptiveStopReason.TIME_BUDGET_EXHAUSTED.value,
            AdaptiveStopReason.EVIDENCE_TOKEN_BUDGET_EXHAUSTED.value,
        }
        budget_exhaustions = sum(row.get("adaptive_stop_reason") in budget_stop_reasons for row in rows)
        def stage_values(stage: str, *, timing_field: str = "initial_retrieval") -> list[float]:
            if stage == "__timing__":
                return [float(row["timing_ms"][timing_field]) for row in rows]
            return [
                float(row["retrieval_stages_ms"][stage])
                for row in rows
                if stage in row["retrieval_stages_ms"]
            ]
        return {
            "metrics_status": "measured",
            "case_count": total,
            "answered_count": len(answered),
            "answer_coverage": len(answered) / total if total else 0.0,
            "abstention_count": abstained,
            "abstention_rate": abstained / total if total else 0.0,
            "correct_abstention_proxy_count": correct_abstention_proxy,
            "false_abstention_proxy_count": false_abstention_proxy,
            "abstention_precision_proxy": correct_abstention_proxy / abstained if abstained else None,
            "numeric_scored_case_count": len(numeric_rows),
            "numeric_exact_answer_accuracy": numeric_exact / len(numeric_rows) if numeric_rows else None,
            "numeric_exact_answer_accuracy_on_answered": exact_answered / answered_numeric if answered_numeric else None,
            "numeric_fact_precision": round(precision, 6) if predicted else None,
            "numeric_fact_recall": round(recall, 6) if gold else None,
            "numeric_fact_f1": round(f1, 6) if precision + recall else None,
            "text_scored_case_count": len(text_rows),
            "normalized_text_exact_match": text_exact / len(text_rows) if text_rows else None,
            "exact_text_task_success_rate": text_exact / len(text_rows) if text_rows else None,
            "answer_token_precision": round(text_precision, 6) if text_predicted else None,
            "answer_token_recall": round(text_recall, 6) if text_gold else None,
            "answer_token_f1": round(text_f1, 6) if text_precision + text_recall else None,
            "answer_token_risk": round(1 - answered_text_f1, 6) if answered_text_rows else None,
            "risk_coverage": {
                "coverage": len(answered) / total if total else 0.0,
                "answered_text_token_f1": round(answered_text_f1, 6) if answered_text_rows else None,
            },
            "claim_status_counts": dict(sorted(claim_status_counts.items())),
            "citation_validity": citation_valid / (citation_valid + citation_invalid) if citation_valid + citation_invalid else None,
            "unverified_answer_rate": unverified_answer_count / len(verifier_rows) if verifier_rows else None,
            "unsupported_or_contradicted_claim_rate": unsupported_claim_count / all_claim_count if all_claim_count else None,
            "provider_calls": len(generation_rows),
            "provider_prompt_tokens": sum(
                row["generation"].get("prompt_tokens") or 0 for row in generation_rows
            ),
            "provider_completion_tokens": sum(
                row["generation"].get("completion_tokens") or 0 for row in generation_rows
            ),
            "provider_cost_estimate_usd": str(generation_cost),
            "latency_p50_ms": _percentile(latencies, 0.50),
            "latency_p95_ms": _percentile(latencies, 0.95),
            "retrieval_time_p50_ms": _percentile(stage_values("__timing__"), 0.50),
            "retrieval_time_p95_ms": _percentile(stage_values("__timing__"), 0.95),
            "reranking_time_p50_ms": _percentile(stage_values("reranking_ms"), 0.50),
            "reranking_time_p95_ms": _percentile(stage_values("reranking_ms"), 0.95),
            "query_embedding_time_p50_ms": _percentile(stage_values("query_embedding_ms"), 0.50),
            "query_embedding_time_p95_ms": _percentile(stage_values("query_embedding_ms"), 0.95),
            "generation_time_p50_ms": _percentile(
                [float(row["timing_ms"]["generation"]) for row in generation_rows], 0.50
            ),
            "generation_time_p95_ms": _percentile(
                [float(row["timing_ms"]["generation"]) for row in generation_rows], 0.95
            ),
            "verification_gate_time_p50_ms": _percentile(
                [float(row["timing_ms"]["claim_verification_gate"]) for row in rows], 0.50
            ),
            "verification_gate_time_p95_ms": _percentile(
                [float(row["timing_ms"]["claim_verification_gate"]) for row in rows], 0.95
            ),
            "mean_adaptive_queries": round(statistics.mean(row["adaptive_queries"] for row in rows), 4) if rows else 0.0,
            "adaptive_query_tool_calls": sum(row["adaptive_queries"] for row in rows),
            "mean_adaptive_rounds": round(statistics.mean(row["adaptive_rounds"] for row in rows), 4) if rows else 0.0,
            "adaptive_budget_exhaustion_count": budget_exhaustions,
            "adaptive_budget_exhaustion_rate": budget_exhaustions / total if total else None,
            "retrieval_replay_match_rate": (
                sum(bool(row["retrieval_replay_matches_p1"]) for row in rows)
                / sum(row["retrieval_replay_matches_p1"] is not None for row in rows)
                if any(row["retrieval_replay_matches_p1"] is not None for row in rows)
                else None
            ),
            "adaptive_gap_resolution_rate": (
                adaptive_resolved_cases / len(adaptive_required_cases)
                if adaptive_required_cases else None
            ),
        }


def build_end_to_end_report(
    *,
    data_dir: Path,
    retrieval_run_dir: Path | None,
    generator: AnswerGenerator | None,
    dry_run: bool,
    max_provider_calls: int = 0,
    max_provider_cost_usd: Decimal = Decimal("0"),
    prior_provider_attempts: int = 0,
    prior_modeled_cost_upper_bound_usd: Decimal = Decimal("0"),
    split: str | None = None,
    max_cases: int | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    checkpoint_state: Mapping[str, Any] | None = None,
    checkpoint_callback: Callable[[dict[str, Any]], None] | None = None,
    checkpoint_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load benchmark artifacts, construct the local adaptive retriever, and run A0–A5."""
    all_cases = load_end_to_end_cases(data_dir)
    selected = _selected_cases(all_cases, split=split, max_cases=max_cases)
    run_dir = retrieval_run_dir or find_complete_retrieval_run(data_dir)
    chunks_by_id, predictions, p1_manifests = load_retrieval_artifacts(run_dir, selected)

    from configs.settings import settings
    from src.retrieval.embedder import Embedder
    from src.retrieval.hybrid_retriever import HybridRetriever
    from src.retrieval.vector_store import VectorStore

    index_manifest = p1_manifests["index"]
    embedder = Embedder(
        model_name=settings.embedding_model_id,
        revision=settings.embedding_model_revision,
    )
    store = VectorStore(
        path=run_dir / "qdrant",
        collection_name=index_manifest["collection_name"],
    )
    try:
        all_chunks = list(chunks_by_id.values())
        if store.get_collection_info().get("points_count") != len(all_chunks):
            raise ValueError("P1 Qdrant point count does not match the corpus chunks")
        adaptive_retriever = HybridRetriever(
            embedder=embedder,
            store=store,
            all_chunks=all_chunks,
            device=embedder.device,
            cross_encoder_model=settings.reranker_model_id,
            cross_encoder_revision=settings.reranker_model_revision,
        )
        catalog = CompanyCatalog.from_document_rows([
            {key: chunk.get(key) for key in ("company", "ticker", "doc_name")}
            for chunk in all_chunks
        ])
        decision_layer = EvidenceDecisionLayer(catalog=catalog)
        controller = AdaptiveRetrievalController(adaptive_retriever, decision_layer=decision_layer)
        retrieval_settings = p1_manifests["run"].get("retrieval", {})
        retrieval_top_k = int(retrieval_settings.get("top_k", 0))
        candidate_pool = int(retrieval_settings.get("candidate_pool", 0))
        if retrieval_top_k != RETRIEVAL_TOP_K or candidate_pool != RETRIEVAL_CANDIDATE_POOL:
            raise ValueError("P1 retrieval settings do not match the frozen P5 retrieval replay settings")
        baseline_retrieval_adapter = FinanceBenchRetrievalAdapter(
            adaptive_retriever,
            top_k=retrieval_top_k,
            candidate_pool=candidate_pool,
        )
        report = EndToEndBenchmark(
            cases=selected,
            chunks_by_id=chunks_by_id,
            predictions=predictions,
            adaptive_controller=controller,
            baseline_retrieval_adapter=baseline_retrieval_adapter,
            generator=generator,
            dry_run=dry_run,
            max_provider_calls=max_provider_calls,
            max_provider_cost_usd=max_provider_cost_usd,
            prior_provider_attempts=prior_provider_attempts,
            prior_modeled_cost_upper_bound_usd=prior_modeled_cost_upper_bound_usd,
            progress_callback=progress_callback,
            checkpoint_state=checkpoint_state,
            checkpoint_callback=checkpoint_callback,
            checkpoint_metadata=checkpoint_metadata,
        ).run()
        report["dataset"] = {
            "id": "FinanceBench public open-source sample",
            "revision": FINANCEBENCH_GITHUB_REVISION,
            "case_count": len(selected),
            "split_counts": dict(Counter(item.case.split for item in selected)),
        }
        report["retrieval_run"] = {
            "path": str(run_dir),
            "source_commit": p1_manifests["run"].get("source_commit"),
            "corpus_fingerprint": p1_manifests["run"].get("corpus_fingerprint"),
            "index_id": p1_manifests["index"].get("index_id"),
            "index_fingerprint": p1_manifests["index"].get("embedding_manifest_sha256"),
            "retrieval_presets": list(RETRIEVAL_PRESETS),
        }
        return report
    finally:
        store.close()
