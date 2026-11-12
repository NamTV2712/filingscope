"""Compare source-aware FAST with frozen M13 and new direct-fact controls."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import mean

from configs.financebench import P1_PAGE_CACHE, P1_RUN
from configs.multi_agent_ablation import CASES as M13_CASES
from configs.source_routing import ADJUDICATED_PDF_LOCATORS, CASES as DIRECT_CASES
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.m13_failure_replay import expected_slots
from src.evaluation.multi_agent_ablation import paired_grounded_exact, summarize_ablation
from src.evaluation.post_m15_manifest import build_manifest
from src.retrieval.canonical_json import sha256_file


_DATA = Path("data/financebench")
_RUNS = _DATA / "ablation_runs"
_SEED = 20261112
_CONTROL_FIELDS = (
    "case_id", "answerable", "answered", "grounded_exact", "numeric_exact", "unsupported_released_claims",
    "citations", "supported_citations", "tool_calls", "retrieval_calls", "llm_calls", "sec_calls", "execution_path",
)
_CODE_FILES = (
    "configs/source_routing.py",
    "scripts/run_multi_agent_ablation.py",
    "scripts/run_source_routing_evaluation.py",
    "src/agent/complexity_router.py",
    "src/agent/specialist_graph.py",
    "src/agent/specialists.py",
    "src/evaluation/multi_agent_ablation.py",
    "src/retrieval/frozen_dense.py",
    "src/retrieval/pdf_page_cache.py",
)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(report: dict, variant: str, split: str | None = None) -> list[dict]:
    return [row for row in report["variants"][variant]["per_case"] if split is None or row["split"] == split]


def _verify_control(frozen: dict, replay: dict, *, accepted_locators: dict[str, str] | None = None) -> list[dict]:
    adjudicated = []
    for variant in ("B4", "B5"):
        for before, after in zip(_rows(frozen, variant), _rows(replay, variant), strict=True):
            differences = {field for field in _CONTROL_FIELDS if before[field] != after[field]}
            if not differences:
                continue
            locator = (accepted_locators or {}).get(before["case_id"])
            citation_numbers = [int(number) for number in re.findall(r"\[Source (\d+)\]", after["answer"])]
            cited = {
                after["citation_sources"][index - 1]
                for index in citation_numbers if 1 <= index <= len(after["citation_sources"])
            }
            if (
                locator is not None and locator in cited and differences.issubset({
                    "grounded_exact", "supported_citations", "unsupported_released_claims",
                })
                and before["answer"] == after["answer"] and before["retrieval_trace"] == after["retrieval_trace"]
                and not before["grounded_exact"] and after["grounded_exact"]
            ):
                adjudicated.append({"variant": variant, "case_id": before["case_id"], "accepted_locator": locator})
            else:
                raise ValueError(f"Control drift for {variant}/{before['case_id']}: {sorted(differences)}")
    return adjudicated


def _summarize(report: dict, issuers: dict[str, set[str]], *, split: str | None = None) -> dict:
    results = {variant: _rows(report, variant, split) for variant in ("B4", "B5", "B6")}
    selected = results["B6"]
    return {
        "scores": {variant: summarize_ablation(rows) for variant, rows in results.items()},
        "answerable_mean_tool_calls": {
            variant: mean(row["tool_calls"] for row in rows if row["answerable"])
            for variant, rows in results.items()
        },
        "pairs": {
            f"B6_minus_{variant}": paired_grounded_exact(selected, results[variant], issuers, seed=_SEED)
            for variant in ("B4", "B5")
        },
        "unsupported_cases": {
            variant: [row["case_id"] for row in rows if row["unsupported_released_claims"] > 0]
            for variant, rows in results.items()
        },
        "candidate_cases": selected,
        "resource_peak_bytes": report["peak_memory_bytes"],
        "setup_seconds": report["setup_seconds"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-baseline", type=Path, default=_RUNS / "q3-direct-baseline.json")
    parser.add_argument("--m13-baseline", type=Path, default=_RUNS / "q2-verified-ablation.json")
    parser.add_argument("--direct", type=Path, default=_RUNS / "q3-direct-adjudicated.json")
    parser.add_argument("--m13", type=Path, default=_RUNS / "q3-m13-verified.json")
    parser.add_argument("--p1-run", type=Path, default=P1_RUN)
    parser.add_argument("--pages", type=Path, default=P1_PAGE_CACHE)
    parser.add_argument("--source-manifest", type=Path, default=_DATA / "source_manifest.json")
    parser.add_argument("--sec-dir", type=Path, default=_RUNS / "m13-sec")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    direct, m13 = _read(args.direct), _read(args.m13)
    adjudications = _verify_control(_read(args.direct_baseline), direct, accepted_locators=ADJUDICATED_PDF_LOCATORS)
    _verify_control(_read(args.m13_baseline), m13)
    direct_groups = {case.case_id: {case.claims[0].terms[0]} for case in DIRECT_CASES if case.claims}
    m13_groups = {case.case_id: {slot.entity for slot in expected_slots(case)} for case in M13_CASES if case.claims}
    development = _summarize(direct, direct_groups, split="development")
    validation = _summarize(direct, direct_groups, split="validation")
    total = _summarize(m13, m13_groups)
    quality = validation["scores"]
    tools = validation["answerable_mean_tool_calls"]
    report = {
        "benchmark": "filingscope-source-routing-v1",
        "configuration": {"random_seed": _SEED, "bootstrap_samples": 10_000, "providers": [],
                          "direct_labels_sha256": sha256_file(Path("configs/source_routing.py"))},
        "direct_development": development,
        "direct_validation": validation,
        "control_label_adjudications": adjudications,
        "m13": total,
        "gates": {
            "direct_grounded_exact_matches_forced": quality["B6"]["grounded_exact_answers"] >= quality["B4"]["grounded_exact_answers"],
            "direct_tool_calls_at_most_half_forced": tools["B6"] <= tools["B4"] / 2,
            "no_candidate_unsupported_releases": not (
                development["unsupported_cases"]["B6"] or validation["unsupported_cases"]["B6"]
                or total["unsupported_cases"]["B6"]
            ),
            "no_m13_grounded_regressions_vs_old_fast": all(
                row["difference"] > 0 for row in total["pairs"]["B6_minus_B5"]["changed_cases"]
            ),
        },
    }
    write_json_atomic(args.output, report)
    write_json_atomic(args.manifest, build_manifest(
        p1_run=args.p1_run, source_manifest=args.source_manifest, sec_manifest=args.sec_dir / "manifest.json",
        pages=args.pages, configuration=report["configuration"], code_files=_CODE_FILES,
        artifacts={
            "routing": args.output, "direct": args.direct, "m13": args.m13,
            "direct_baseline": args.direct_baseline, "m13_baseline": args.m13_baseline,
        },
    ))
    print(args.output, flush=True)


if __name__ == "__main__":
    main()
