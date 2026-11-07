from scripts.summarize_end_to_end_benchmark import VARIANTS, publish_summary


def test_summary_requires_full_measured_provider_benchmark(tmp_path) -> None:
    report = {
        "mode": "provider_backed",
        "case_count": 150,
        "split_counts": {"development": 60, "validation": 45, "held_out": 45},
        "generated_at_utc": "2026-11-07T00:00:00+00:00",
        "dataset": {"revision": "dataset-revision"},
        "retrieval_run": {"corpus_fingerprint": "sha256:corpus"},
        "generator": {
            "provider_calls_planned_or_made": 521,
            "provider_attempts_current_run": 460,
            "prior_provider_attempts": 61,
            "prior_run_cost_upper_bound_usd": "0.08507790",
            "reported_cost_estimate_usd": "0.30",
            "combined_cost_upper_bound_usd": "0.39",
            "preflight_cost_estimate_usd": "0.71904525",
        },
        "frozen_configuration": {
            "generator_model_id": "fake-model",
            "temperature": 0,
            "prompt_version": "test-prompt",
            "prompt_sha256": "f" * 64,
        },
        "variants": {
            name: {
                "metrics_status": "measured",
                "answer_coverage": 0.8,
                "normalized_text_exact_match": 0.4,
                "answer_token_f1": 0.6,
                "numeric_exact_answer_accuracy": 0.5,
                "citation_validity": 0.9,
                "unsupported_or_contradicted_claim_rate": 0.1,
                "latency_p50_ms": 500,
                "latency_p95_ms": 1000,
                "provider_calls": 100 if name != "A5" else 0,
                "provider_cost_estimate_usd": "0.10" if name != "A5" else "0",
            }
            for name in VARIANTS
        },
        "metrics_by_split": {
            split: {
                name: {
                    "metrics_status": "measured",
                    "answer_coverage": coverage,
                    "normalized_text_exact_match": 0.4,
                    "answer_token_f1": token_f1,
                    "numeric_exact_answer_accuracy": numeric_exact,
                    "citation_validity": citation_validity,
                    "unsupported_or_contradicted_claim_rate": 0.1,
                    "latency_p50_ms": latency_p95 / 2,
                    "latency_p95_ms": latency_p95,
                    "reranking_time_p95_ms": 10,
                    "adaptive_gap_resolution_rate": 0.5,
                }
                for name in VARIANTS
            }
            for split, coverage, token_f1, numeric_exact, citation_validity, latency_p95 in (
                ("development", 0.7, 0.5, 0.4, 0.8, 2000),
                ("validation", 0.8, 0.6, 0.5, 0.9, 1500),
                ("held_out", 0.9, 0.7, 0.6, 1.0, 1000),
            )
        },
        "cases": [],
    }
    docs_dir = tmp_path / "docs"

    publish_summary(report, docs_dir)

    assert (docs_dir / "BENCHMARK_RESULTS.md").is_file()
    assert (docs_dir / "ABLATION_STUDY.md").is_file()
    assert (docs_dir / "FAILURE_ANALYSIS.md").is_file()
    benchmark = (docs_dir / "BENCHMARK_RESULTS.md").read_text(encoding="utf-8")
    ablation = (docs_dir / "ABLATION_STUDY.md").read_text(encoding="utf-8")
    assert "## Primary held-out results" in benchmark
    assert "521** total" in benchmark
    assert "Prior-run usage details were not retained" in benchmark
    assert "| A0 | Dense retrieval + generator | 90.0% | 70.0% | 60.0% | 100.0% | 1000.0 |" in ablation
    assert "Calls and modeled cost columns count responses used by the completed benchmark run" in ablation
    failure_analysis = (docs_dir / "FAILURE_ANALYSIS.md").read_text(encoding="utf-8")
    assert "61 attempts" in failure_analysis
    assert (docs_dir / "assets" / "benchmark_quality.svg").read_text(encoding="utf-8").startswith("<svg")
    assert (docs_dir / "assets" / "benchmark_latency.svg").is_file()
    assert (docs_dir / "assets" / "benchmark_cost.svg").is_file()


def test_summary_rejects_dry_run_as_benchmark_results(tmp_path) -> None:
    try:
        publish_summary({"mode": "dry_run"}, tmp_path)
    except ValueError as error:
        assert "provider-backed" in str(error)
    else:
        raise AssertionError("dry-run metrics must not be published as benchmark results")


def test_summary_rejects_missing_split_metrics(tmp_path) -> None:
    report = {
        "mode": "provider_backed",
        "case_count": 150,
        "split_counts": {"development": 60, "validation": 45, "held_out": 45},
        "variants": {name: {"metrics_status": "measured"} for name in VARIANTS},
        "metrics_by_split": {},
    }
    try:
        publish_summary(report, tmp_path)
    except ValueError as error:
        assert "every frozen split" in str(error)
    else:
        raise AssertionError("partial split metrics must not be published")
