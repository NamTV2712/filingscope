"""Publish reproducible P5 benchmark tables, failure analysis, and SVG charts."""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

VARIANTS = ("A0", "A1", "A2", "A3", "A4", "A5")
VARIANT_COMPONENTS = {
    "A0": "Dense retrieval + generator",
    "A1": "Hybrid retrieval + generator",
    "A2": "Hybrid retrieval + reranker + generator",
    "A3": "A2 + evidence decision",
    "A4": "A3 + adaptive retrieval",
    "A5": "A4 + claim verification gate",
}
COLORS = ("#3978a8", "#4c9a76", "#d89036", "#8b6bb1", "#c45d68", "#3f8f9c")


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.1f}%"


def _number(value: Any, places: int = 3) -> str:
    return "n/a" if value is None else f"{float(value):.{places}f}"


def _metrics_table(variants: dict[str, Any]) -> list[str]:
    return [
        "| Metric | " + " | ".join(VARIANTS) + " |",
        "|---|" + "---:|" * len(VARIANTS),
        "| Answer coverage | " + " | ".join(_percent(variants[name].get("answer_coverage")) for name in VARIANTS) + " |",
        "| Normalized text exact match | " + " | ".join(_percent(variants[name].get("normalized_text_exact_match")) for name in VARIANTS) + " |",
        "| Answer token F1 | " + " | ".join(_percent(variants[name].get("answer_token_f1")) for name in VARIANTS) + " |",
        "| Numeric exact accuracy (scored cases) | " + " | ".join(_percent(variants[name].get("numeric_exact_answer_accuracy")) for name in VARIANTS) + " |",
        "| Citation validity | " + " | ".join(_percent(variants[name].get("citation_validity")) for name in VARIANTS) + " |",
        "| Unsupported or contradicted claim rate | " + " | ".join(_percent(variants[name].get("unsupported_or_contradicted_claim_rate")) for name in VARIANTS) + " |",
        "| p50 component latency (ms) | " + " | ".join(_number(variants[name].get("latency_p50_ms"), 1) for name in VARIANTS) + " |",
        "| p95 component latency (ms) | " + " | ".join(_number(variants[name].get("latency_p95_ms"), 1) for name in VARIANTS) + " |",
        "| Reranking p95 (ms) | " + " | ".join(_number(variants[name].get("reranking_time_p95_ms"), 1) for name in VARIANTS) + " |",
        "| Adaptive gap resolution | " + " | ".join(_percent(variants[name].get("adaptive_gap_resolution_rate")) for name in VARIANTS) + " |",
    ]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _svg_bar_chart(
    *,
    title: str,
    metric_names: Sequence[tuple[str, str]],
    variants: dict[str, Any],
    output: Path,
) -> None:
    width, height = 960, 480
    left, right, top, bottom = 58, 20, 58, 112
    plot_width, plot_height = width - left - right, height - top - bottom
    group_width = plot_width / max(1, len(metric_names))
    bar_width = min(12, group_width / (len(VARIANTS) * 1.7))
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2}" y="30" text-anchor="middle" font-family="Arial,sans-serif" font-size="19" font-weight="700">{html.escape(title)}</text>',
    ]
    for tick in range(6):
        value = tick / 5
        y = top + plot_height * (1 - value)
        chunks.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#d9e0e6"/>')
        chunks.append(f'<text x="{left - 9}" y="{y + 4:.1f}" text-anchor="end" font-family="Arial,sans-serif" font-size="11" fill="#44515c">{value:.0%}</text>')
    for group_index, (label, key) in enumerate(metric_names):
        center = left + group_width * (group_index + 0.5)
        start = center - (len(VARIANTS) * bar_width) / 2
        for variant_index, variant in enumerate(VARIANTS):
            raw = variants[variant].get(key)
            if raw is None:
                continue
            value = max(0.0, min(1.0, float(raw)))
            bar_height = value * plot_height
            x = start + variant_index * bar_width
            y = top + plot_height - bar_height
            chunks.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(5, bar_width - 1):.1f}" height="{bar_height:.1f}" fill="{COLORS[variant_index]}"><title>{variant}: {label} {value:.3f}</title></rect>'
            )
        chunks.append(f'<text x="{center:.1f}" y="{top + plot_height + 23}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11">{html.escape(label)}</text>')
    legend_y = height - 40
    legend_width = width / len(VARIANTS)
    for index, variant in enumerate(VARIANTS):
        x = 26 + index * legend_width
        chunks.append(f'<rect x="{x}" y="{legend_y - 10}" width="11" height="11" fill="{COLORS[index]}"/>')
        chunks.append(f'<text x="{x + 16}" y="{legend_y}" font-family="Arial,sans-serif" font-size="11">{variant}</text>')
    chunks.append('</svg>')
    _write(output, "\n".join(chunks) + "\n")


def _single_series_svg(
    *,
    title: str,
    values: dict[str, float | None],
    output: Path,
    unit: str,
) -> None:
    width, height = 860, 360
    left, right, top, bottom = 70, 24, 56, 70
    plot_width, plot_height = width - left - right, height - top - bottom
    observed = [value for value in values.values() if value is not None]
    maximum = max(observed, default=1.0)
    maximum = maximum if maximum > 0 else 1.0
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2}" y="30" text-anchor="middle" font-family="Arial,sans-serif" font-size="19" font-weight="700">{html.escape(title)}</text>',
    ]
    for tick in range(6):
        value = maximum * tick / 5
        y = top + plot_height * (1 - tick / 5)
        chunks.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#d9e0e6"/>')
        chunks.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-family="Arial,sans-serif" font-size="11" fill="#44515c">{value:.2f}{unit}</text>')
    group_width = plot_width / len(VARIANTS)
    bar_width = min(58, group_width * 0.56)
    for index, variant in enumerate(VARIANTS):
        value = values.get(variant)
        center = left + group_width * (index + 0.5)
        if value is not None:
            bar_height = max(0.0, float(value)) / maximum * plot_height
            y = top + plot_height - bar_height
            chunks.append(f'<rect x="{center - bar_width / 2:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" fill="{COLORS[index]}"><title>{variant}: {float(value):.3f}{unit}</title></rect>')
            label = f"{float(value):.3f}{unit}"
            chunks.append(f'<text x="{center:.1f}" y="{max(top + 13, y - 6):.1f}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11">{html.escape(label)}</text>')
        else:
            chunks.append(f'<text x="{center:.1f}" y="{top + plot_height - 8:.1f}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" fill="#77838d">n/a</text>')
        chunks.append(f'<text x="{center:.1f}" y="{top + plot_height + 24}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12">{variant}</text>')
    chunks.append('</svg>')
    _write(output, "\n".join(chunks) + "\n")


def publish_summary(report: dict[str, Any], docs_dir: Path) -> None:
    if report.get("mode") != "provider_backed":
        raise ValueError("Only a completed provider-backed benchmark can be published as results")
    if report.get("case_count") != 150:
        raise ValueError("A publishable P5 benchmark must include all 150 FinanceBench cases")
    if report.get("split_counts") != {"development": 60, "validation": 45, "held_out": 45}:
        raise ValueError("P5 results must include the frozen 60/45/45 company-held-out splits")
    variants = report.get("variants", {})
    if set(variants) != set(VARIANTS) or any(
        variants[name].get("metrics_status") != "measured" for name in VARIANTS
    ):
        raise ValueError("The report does not contain measured A0–A5 results")
    metrics_by_split = report.get("metrics_by_split", {})
    required_splits = ("development", "validation", "held_out")
    if any(
        split not in metrics_by_split
        or set(metrics_by_split[split]) != set(VARIANTS)
        or any(metrics_by_split[split][name].get("metrics_status") != "measured" for name in VARIANTS)
        for split in required_splits
    ):
        raise ValueError("The report must include measured A0–A5 metrics for every frozen split")
    heldout = metrics_by_split["held_out"]

    dataset = report["dataset"]
    retrieval = report["retrieval_run"]
    generator = report["generator"]
    frozen = report["frozen_configuration"]
    provenance = report.get("source_provenance", {})
    generated_at = report.get("generated_at_utc", "unknown")
    prior_attempts = int(generator.get("prior_provider_attempts", 0))
    prior_cost_bound = str(generator.get("prior_run_cost_upper_bound_usd", "0"))
    current_cost = str(generator.get("reported_cost_estimate_usd", "0"))
    combined_cost_bound = str(generator.get("combined_cost_upper_bound_usd", current_cost))
    combined_preflight_max = str(generator.get("preflight_cost_estimate_usd", combined_cost_bound))
    attempt_note = (
        f"Provider attempts: **{generator['provider_calls_planned_or_made']}** total "
        f"(**{generator.get('provider_attempts_current_run', generator['provider_calls_planned_or_made'])}** in the completed run; "
        f"**{prior_attempts}** prior abandoned attempts); current-run usage-based estimate: **${current_cost}**; "
        f"combined reported cost upper bound: **${combined_cost_bound}**; combined conservative preflight maximum: "
        f"**${combined_preflight_max}** (not a provider invoice)."
    )
    if prior_attempts:
        attempt_note += (
            f" Prior-run usage details were not retained; its conservative cost bound of ${prior_cost_bound} "
            "is carried into the combined estimate."
        )
    header = [
        "# FinanceBench end-to-end benchmark results",
        "",
        f"Run date (UTC): `{generated_at}`<br>",
        f"Cases: **{report['case_count']}** ({', '.join(f'{key}: {value}' for key, value in sorted(report['split_counts'].items()))})<br>",
        f"Dataset revision: `{dataset['revision']}`<br>",
        f"P1 corpus fingerprint: `{retrieval['corpus_fingerprint']}`<br>",
        f"FilingScope source fingerprint: `{provenance.get('source_fingerprint_sha256', 'not-recorded')}`<br>",
        f"Generator: `{frozen['generator_model_id']}`, temperature `{frozen['temperature']}`, prompt `{frozen['prompt_version']}` (`{frozen['prompt_sha256'][:16]}`)<br>",
        attempt_note,
        "",
        "The answer quality metrics are deterministic text and number comparisons against the FinanceBench gold answers. Text exact match and token F1 measure lexical agreement; they are not semantic grading. Numeric metrics compare extracted value, currency, scale, value kind, and fiscal period. Claim and citation outcomes come from FilingScope’s deterministic verifier. Abstention correctness uses annotated evidence-page coverage as a proxy.",
        "",
        "## All-split aggregate",
        "",
        *_metrics_table(variants),
        "",
        "## Primary held-out results",
        "",
        *_metrics_table(heldout),
        "",
        "The split-specific held-out table is the final result. Development and validation tables below are kept separate for debugging and model/threshold selection; the all-split aggregate is descriptive.",
        "",
        "| Split | Variant | Answer coverage | Text token F1 | Numeric exact | Citation validity | p95 ms |",
        "|---|---|---:|---:|---:|---:|---:|",
        *[
            f"| {split.replace('_', ' ')} | {name} | {_percent(metrics_by_split[split][name].get('answer_coverage'))} | "
            f"{_percent(metrics_by_split[split][name].get('answer_token_f1'))} | "
            f"{_percent(metrics_by_split[split][name].get('numeric_exact_answer_accuracy'))} | "
            f"{_percent(metrics_by_split[split][name].get('citation_validity'))} | "
            f"{_number(metrics_by_split[split][name].get('latency_p95_ms'), 1)} |"
            for split in ("development", "validation")
            for name in VARIANTS
        ],
        "",
        "| Metric | " + " | ".join(VARIANTS) + " |",
        "|---|" + "---:|" * len(VARIANTS),
        "| Incremental provider calls | " + " | ".join(str(variants[name].get("provider_calls", 0)) for name in VARIANTS) + " |",
        "| Incremental modeled provider cost (USD) | " + " | ".join(f"${variants[name].get('provider_cost_estimate_usd', '0')}" for name in VARIANTS) + " |",
        "| P1 retrieval replay parity | " + " | ".join(_percent(variants[name].get("retrieval_replay_match_rate")) for name in VARIANTS) + " |",
        "",
        "A5 reuses A4’s generated answer, so it adds verifier latency but no additional provider generation call. P5 replays each frozen P1 A0–A2 retrieval configuration to measure retrieval and reranker stages; the answer evidence itself remains the frozen P1 artifact. The replay match rate shows whether the current replay selected identical chunk IDs. Component totals include query embedding, retrieval, decision/adaptive retrieval, generation, and the active verifier gate.",
        "",
        "![A0–A5 held-out quality metrics](assets/benchmark_quality.svg)",
        "",
        "![A0–A5 held-out p95 component latency](assets/benchmark_latency.svg)",
        "",
        "![A0–A5 incremental modeled provider cost](assets/benchmark_cost.svg)",
        "",
        "The raw per-case predictions, aggregate metrics, manifests, prompt fingerprint, and model usage are stored in the ignored local run directory created by `scripts.run_end_to_end_benchmark`; the corpus and generated run artifacts are intentionally not committed.",
        "",
    ]
    _write(docs_dir / "BENCHMARK_RESULTS.md", "\n".join(header))

    ablation_lines = [
        "# A0–A5 ablation study",
        "",
        "All six variants use the same 150 cases, pinned P1 corpus, and frozen answer prompt. Each row adds one component to the preceding variant. A5 reuses A4 answers and applies the claim verifier as an output gate.",
        "",
        "Quality and latency columns below use the held-out split. Calls and modeled cost columns count responses used by the completed benchmark run; they exclude any abandoned provider attempts listed in the results header.",
        "",
        "| Variant | Enabled component | Coverage | Text token F1 | Numeric exact | Citation validity | p95 ms | Calls | Cost USD |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in VARIANTS:
        row = heldout[name]
        spend = variants[name]
        ablation_lines.append(
            f"| {name} | {VARIANT_COMPONENTS[name]} | {_percent(row.get('answer_coverage'))} | "
            f"{_percent(row.get('answer_token_f1'))} | {_percent(row.get('numeric_exact_answer_accuracy'))} | "
            f"{_percent(row.get('citation_validity'))} | {_number(row.get('latency_p95_ms'), 1)} | "
            f"{spend.get('provider_calls', 0)} | ${spend.get('provider_cost_estimate_usd', '0')} |"
        )
    ablation_lines.extend([
        "",
        "| Transition | Change in answer token F1 | Change in coverage | Change in numeric exact accuracy |",
        "|---|---:|---:|---:|",
    ])
    for previous, current in zip(VARIANTS, VARIANTS[1:]):
        before, after = heldout[previous], heldout[current]
        def delta(key: str) -> str:
            left, right = before.get(key), after.get(key)
            return "n/a" if left is None or right is None else f"{(float(right) - float(left)) * 100:+.1f} pp"
        ablation_lines.append(
            f"| {previous} → {current} | {delta('answer_token_f1')} | {delta('answer_coverage')} | {delta('numeric_exact_answer_accuracy')} |"
        )
    ablation_lines.extend([
        "",
        "These differences are descriptive for this pinned public sample. They are not a significance test. Text metrics are lexical agreement measures, and the evidence-page abstention proxy can misclassify cases where alternate evidence pages support the answer.",
        "",
    ])
    _write(docs_dir / "ABLATION_STUDY.md", "\n".join(ablation_lines))

    disposition_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    claim_counts: Counter[str] = Counter()
    numeric_failures: list[tuple[str, dict[str, Any]]] = []
    verifier_abstentions: list[tuple[str, dict[str, Any]]] = []
    evidence_gaps: list[tuple[str, dict[str, Any]]] = []
    for case in report.get("cases", []):
        a4 = case["variants"]["A4"]
        a5 = case["variants"]["A5"]
        verification = a4.get("verification") or {}
        if verification:
            disposition_counts[str(verification.get("disposition", "unknown"))] += 1
            reason_counts.update(map(str, verification.get("reason_codes", [])))
            for claim in verification.get("claims", []):
                claim_counts[str(claim.get("status", "unknown"))] += 1
                reason_counts.update(map(str, claim.get("reason_codes", [])))
        numeric_score = a4.get("numeric_score") or {}
        if (
            a4.get("answer")
            and not a4.get("abstained")
            and numeric_score.get("scored")
            and not numeric_score.get("exact_match")
        ):
            numeric_failures.append((str(case["case_id"]), a4))
        if a5.get("abstained") and a5.get("final_disposition") in {"REJECTED", "ABSTAIN", "PARTIAL"}:
            verifier_abstentions.append((str(case["case_id"]), a5))
        if float(a4.get("gold_evidence_page_coverage", 1.0)) < 1.0:
            evidence_gaps.append((str(case["case_id"]), a4))

    failure_lines = [
        "# Failure analysis",
        "",
        "This report groups the observed retrieval, generation, claim, and citation outcomes from the held run. It uses case identifiers and verifier reason codes; it does not publish FinanceBench gold answers.",
        "",
        "## Observed A4 verifier dispositions",
        "",
    ]
    if prior_attempts:
        failure_lines[4:4] = [
            f"The completed results followed an interrupted prior provider run with {prior_attempts} attempts. Its case responses and token-usage details were not retained. The combined cost estimate carries its conservative upper bound of ${prior_cost_bound}; per-case quality metrics use only responses from the completed run.",
            "",
        ]
    failure_lines.extend(
        [f"- `{key}`: {value}" for key, value in sorted(disposition_counts.items())]
        or ["- No A4 generated answers reached claim verification."]
    )
    failure_lines.extend(["", "## Claim status counts", ""])
    failure_lines.extend([f"- `{key}`: {value}" for key, value in sorted(claim_counts.items())] or ["- No claims were assessed."])
    failure_lines.extend(["", "## Frequent verifier reasons", ""])
    failure_lines.extend(
        [f"- `{key}`: {value}" for key, value in reason_counts.most_common(15)]
        or ["- No verifier reason codes were recorded."]
    )
    failure_lines.extend([
        "",
        f"## A5 verifier abstentions ({len(verifier_abstentions)} cases)",
        "",
    ])
    for case_id, row in verifier_abstentions[:30]:
        verification = row.get("verification") or {}
        failure_lines.append(
            f"- `{case_id}`: disposition `{row.get('final_disposition')}`, "
            f"reasons `{', '.join(map(str, verification.get('reason_codes', []))) or 'none'}`, "
            f"text exact `{(row.get('text_score') or {}).get('exact_match')}`."
        )
    failure_lines.extend(["", f"## A4 numeric exact-match misses ({len(numeric_failures)} answered cases)", ""])
    for case_id, row in numeric_failures[:30]:
        score = row.get("numeric_score") or {}
        failure_lines.append(
            f"- `{case_id}`: numeric precision `{score.get('precision')}`, recall `{score.get('recall')}`, "
            f"evidence-page coverage `{_percent(row.get('gold_evidence_page_coverage'))}`."
        )
    failure_lines.extend(["", f"## Incomplete annotated-page coverage ({len(evidence_gaps)} cases)", ""])
    for case_id, row in evidence_gaps[:30]:
        failure_lines.append(
            f"- `{case_id}`: `{row.get('adaptive_stop_reason')}`, "
            f"decision `{row.get('decision_reason')}`, "
            f"coverage `{_percent(row.get('gold_evidence_page_coverage'))}`."
        )
    failure_lines.extend([
        "",
        "Per-case generated answers and the full evidence audit trail remain in local ignored artifacts. Failure categories should be interpreted with the metric limitations in `BENCHMARK_RESULTS.md`.",
        "",
    ])
    _write(docs_dir / "FAILURE_ANALYSIS.md", "\n".join(failure_lines))

    assets = docs_dir / "assets"
    _svg_bar_chart(
        title="FinanceBench held-out answer quality and coverage by ablation",
        metric_names=(
            ("Token F1", "answer_token_f1"),
            ("Text exact", "normalized_text_exact_match"),
            ("Numeric exact", "numeric_exact_answer_accuracy"),
            ("Coverage", "answer_coverage"),
            ("Citation valid", "citation_validity"),
        ),
        variants=heldout,
        output=assets / "benchmark_quality.svg",
    )
    _single_series_svg(
        title="FinanceBench held-out p95 component latency",
        values={name: heldout[name].get("latency_p95_ms") for name in VARIANTS},
        output=assets / "benchmark_latency.svg",
        unit=" ms",
    )
    _single_series_svg(
        title="Incremental modeled provider cost by variant",
        values={name: float(variants[name].get("provider_cost_estimate_usd", 0)) for name in VARIANTS},
        output=assets / "benchmark_cost.svg",
        unit=" USD",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_json", type=Path)
    parser.add_argument("--docs-dir", type=Path, default=Path("docs"))
    args = parser.parse_args(argv)
    report = json.loads(args.results_json.read_text(encoding="utf-8"))
    publish_summary(report, args.docs_dir)
    print(f"Published P5 summary files under {args.docs_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
