"""Run the frozen A0–A5 FinanceBench benchmark, dry-run by default."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from configs.end_to_end import (
    ADAPTIVE_RETRIEVAL_BUDGET,
    BENCHMARK_ID,
    GENERATOR_CACHED_INPUT_USD_PER_MILLION,
    GENERATOR_INPUT_USD_PER_MILLION,
    GENERATOR_MAX_OUTPUT_TOKENS,
    GENERATOR_MAX_INPUT_TOKENS,
    GENERATOR_MODEL_ID,
    GENERATOR_OUTPUT_USD_PER_MILLION,
    GENERATOR_PROMPT_TOKEN_ESTIMATE_MARGIN,
    GENERATOR_PRICE_CHECKED_AT,
    RETRIEVAL_CANDIDATE_POOL,
    RETRIEVAL_TOP_K,
    GENERATOR_TEMPERATURE,
    PROMPT_VERSION,
)
from src.evaluation.end_to_end_evaluation import build_end_to_end_report
from src.generation.answer_generator import (
    GroqAnswerGenerator,
    SYSTEM_PROMPT,
    build_generation_messages,
)

_PROVENANCE_FILES = (
    "configs/end_to_end.py",
    "configs/financebench.py",
    "configs/settings.py",
    "src/agent/adaptive_retrieval.py",
    "src/ingestion/chunker.py",
    "src/decision/company_catalog.py",
    "src/decision/evidence_coverage.py",
    "src/decision/models.py",
    "src/decision/policy.py",
    "src/decision/period_value_parser.py",
    "src/decision/requirement_extractor.py",
    "src/evaluation/answer_metrics.py",
    "src/evaluation/end_to_end_evaluation.py",
    "src/evaluation/financebench_dataset.py",
    "src/evaluation/retrieval_adapter.py",
    "src/generation/answer_generator.py",
    "src/retrieval/embedder.py",
    "src/retrieval/hybrid_retriever.py",
    "src/retrieval/lexical_ladder.py",
    "src/retrieval/query_shaper.py",
    "src/retrieval/vector_store.py",
    "src/verification/claim_verifier.py",
    "src/verification/numerical_verifier.py",
    "scripts/run_end_to_end_benchmark.py",
)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__} to JSON")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _source_provenance(root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    for relative_path in _PROVENANCE_FILES:
        path = root / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Cannot fingerprint benchmark source file: {relative_path}")
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {
        "git_revision": revision,
        "working_tree_dirty": bool(status.strip()),
        "source_fingerprint_sha256": digest.hexdigest(),
        "fingerprinted_files": list(_PROVENANCE_FILES),
    }


def _run_directory(base: Path, report: dict[str, Any]) -> Path:
    now = datetime.now(UTC)
    identity = {
        "benchmark": BENCHMARK_ID,
        "mode": report["mode"],
        "dataset_revision": report["dataset"]["revision"],
        "corpus_fingerprint": report["retrieval_run"]["corpus_fingerprint"],
        "case_count": report["case_count"],
        "generated_at_utc": now.isoformat(),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return base / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{digest}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retrieval-run-dir",
        type=Path,
        help="P1 retrieval run to evaluate (auto-detected only when exactly one valid run exists).",
    )
    parser.add_argument("--split", choices=("development", "validation", "held_out"))
    parser.add_argument("--max-cases", type=int)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/financebench/e2e_runs"),
        help="Ignored runtime artifact directory; defaults under data/.",
    )
    parser.add_argument(
        "--provider-run",
        action="store_true",
        help="Explicitly enable paid Groq answer generation; requires both budget limits.",
    )
    parser.add_argument(
        "--max-provider-calls",
        type=int,
        help="Global request-attempt cap, including any --prior-provider-attempts.",
    )
    parser.add_argument(
        "--max-cost-usd",
        type=Decimal,
        help="Global modeled cost cap, including prior usage and current reservations.",
    )
    parser.add_argument("--prior-provider-attempts", type=int, default=0)
    parser.add_argument("--prior-modeled-cost-usd", type=Decimal, default=Decimal("0"))
    parser.add_argument(
        "--resume-from",
        type=Path,
        help="Resume a provider-backed run from its ignored local checkpoint JSON file.",
    )
    args = parser.parse_args(argv)

    checkpoint_state = None
    checkpoint_path = None
    checkpoint_metadata: dict[str, Any] = {}
    if args.provider_run:
        if args.max_provider_calls is None or args.max_provider_calls < 1:
            parser.error("--provider-run requires --max-provider-calls greater than zero")
        if args.max_cost_usd is None or args.max_cost_usd <= 0:
            parser.error("--provider-run requires --max-cost-usd greater than zero")
        if args.prior_provider_attempts < 0 or args.prior_modeled_cost_usd < 0:
            parser.error("prior usage flags must be non-negative")
        if args.prior_provider_attempts > args.max_provider_calls:
            parser.error("--prior-provider-attempts cannot exceed --max-provider-calls")
        if args.prior_modeled_cost_usd > args.max_cost_usd:
            parser.error("--prior-modeled-cost-usd cannot exceed --max-cost-usd")
        from configs.settings import settings

        api_key = settings.groq_api_key.get_secret_value()
        if not api_key:
            parser.error("--provider-run requires GROQ_API_KEY in the target project's environment")
        generator = GroqAnswerGenerator(api_key=api_key)
        dry_run = False
        source_provenance = _source_provenance(Path.cwd())
        prompt_sha256 = hashlib.sha256(
            (SYSTEM_PROMPT + inspect.getsource(build_generation_messages)).encode("utf-8")
        ).hexdigest()
        checkpoint_metadata = {
            "benchmark_id": BENCHMARK_ID,
            "mode": "provider_backed",
            "source_fingerprint_sha256": source_provenance["source_fingerprint_sha256"],
            "model_id": GENERATOR_MODEL_ID,
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": prompt_sha256,
            "temperature": GENERATOR_TEMPERATURE,
            "max_output_tokens": GENERATOR_MAX_OUTPUT_TOKENS,
            "prior_provider_attempts": args.prior_provider_attempts,
            "prior_modeled_cost_usd": str(args.prior_modeled_cost_usd),
            "max_provider_calls": args.max_provider_calls,
            "max_cost_usd": str(args.max_cost_usd),
            "retrieval_run_dir": str(args.retrieval_run_dir.resolve()) if args.retrieval_run_dir else None,
            "split": args.split,
            "max_cases": args.max_cases,
        }
        if args.resume_from:
            checkpoint_path = args.resume_from.resolve()
            if not checkpoint_path.is_file():
                parser.error("--resume-from checkpoint file does not exist")
            checkpoint_state = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if checkpoint_state.get("metadata") != checkpoint_metadata:
                parser.error("checkpoint metadata differs from this provider run's frozen configuration")
        else:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_path = args.output_dir / f".checkpoint-{uuid4().hex}.json"
        print(f"P5 provider checkpoint: {checkpoint_path}", file=sys.stderr, flush=True)
    else:
        if args.max_provider_calls is not None or args.max_cost_usd is not None:
            parser.error("budget flags require --provider-run; default execution is a no-call dry run")
        if args.resume_from or args.prior_provider_attempts or args.prior_modeled_cost_usd:
            parser.error("checkpoint and prior-usage flags require --provider-run")
        generator = None
        dry_run = True

    def save_checkpoint(state: dict[str, Any]) -> None:
        if checkpoint_path is None:
            return
        state["metadata"] = checkpoint_metadata
        state["updated_at_utc"] = datetime.now(UTC).isoformat()
        _atomic_write(
            checkpoint_path,
            json.dumps(state, indent=2, sort_keys=True, default=_json_default) + "\n",
        )

    def show_progress(completed: int, total: int) -> None:
        if completed % 10 == 0 or completed == total:
            print(f"P5 benchmark progress: {completed}/{total} cases", file=sys.stderr, flush=True)

    report = build_end_to_end_report(
        data_dir=Path("data/financebench"),
        retrieval_run_dir=args.retrieval_run_dir,
        generator=generator,
        dry_run=dry_run,
        max_provider_calls=args.max_provider_calls or 0,
        max_provider_cost_usd=args.max_cost_usd or Decimal(0),
        prior_provider_attempts=args.prior_provider_attempts,
        prior_modeled_cost_upper_bound_usd=args.prior_modeled_cost_usd,
        split=args.split,
        max_cases=args.max_cases,
        progress_callback=show_progress,
        checkpoint_state=checkpoint_state,
        checkpoint_callback=save_checkpoint if not dry_run else None,
        checkpoint_metadata=checkpoint_metadata,
    )
    report["frozen_configuration"] = {
        "benchmark_id": BENCHMARK_ID,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(
            (SYSTEM_PROMPT + inspect.getsource(build_generation_messages)).encode("utf-8")
        ).hexdigest(),
        "generator_model_id": GENERATOR_MODEL_ID,
        "temperature": GENERATOR_TEMPERATURE,
        "max_output_tokens": GENERATOR_MAX_OUTPUT_TOKENS,
        "max_input_tokens_estimated": GENERATOR_MAX_INPUT_TOKENS,
        "prompt_tokenizer": "tiktoken cl100k_base",
        "prompt_token_estimate_margin": str(GENERATOR_PROMPT_TOKEN_ESTIMATE_MARGIN),
        "retrieval_top_k": RETRIEVAL_TOP_K,
        "retrieval_candidate_pool": RETRIEVAL_CANDIDATE_POOL,
        "adaptive_retrieval_budget": ADAPTIVE_RETRIEVAL_BUDGET.model_dump(mode="json"),
        "provider_price_checked_at": GENERATOR_PRICE_CHECKED_AT,
        "provider_input_usd_per_million_tokens": str(GENERATOR_INPUT_USD_PER_MILLION),
        "provider_cached_input_usd_per_million_tokens": str(GENERATOR_CACHED_INPUT_USD_PER_MILLION),
        "provider_output_usd_per_million_tokens": str(GENERATOR_OUTPUT_USD_PER_MILLION),
        "provider_run_explicit_opt_in": bool(args.provider_run),
    }
    source_provenance = _source_provenance(Path.cwd())
    report["source_provenance"] = source_provenance
    run_dir = _run_directory(args.output_dir, report)
    _atomic_write(run_dir / "results.json", json.dumps(report, indent=2, sort_keys=True, default=_json_default) + "\n")
    prediction_lines = "".join(
        json.dumps(item, sort_keys=True, default=_json_default) + "\n"
        for item in report["cases"]
    )
    _atomic_write(run_dir / "predictions.jsonl", prediction_lines)
    manifest = {
        "benchmark": BENCHMARK_ID,
        "mode": report["mode"],
        "case_count": report["case_count"],
        "split_counts": report["split_counts"],
        "dataset": report["dataset"],
        "retrieval_run": report["retrieval_run"],
        "frozen_configuration": report["frozen_configuration"],
        "source_provenance": source_provenance,
        "generator_budget_and_usage": report["generator"],
        "results_file": "results.json",
        "predictions_file": "predictions.jsonl",
    }
    _atomic_write(run_dir / "run_manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    if checkpoint_path is not None:
        checkpoint_path.unlink(missing_ok=True)
    print(json.dumps({
        "run_dir": str(run_dir),
        "mode": report["mode"],
        "case_count": report["case_count"],
        "variants": report["variants"],
        "generator": report["generator"],
    }, indent=2, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
