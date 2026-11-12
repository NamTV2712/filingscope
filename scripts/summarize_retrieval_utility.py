"""Check Q5 paired controls and bind the ranking and graph replays to their inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from configs.financebench import P1_PAGE_CACHE, P1_RUN
from configs.hard_negatives import CASES as M12_CASES
from configs.retrieval_utility import ISSUERS
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.multi_agent_ablation import paired_grounded_exact
from src.evaluation.post_m15_manifest import build_manifest
from src.retrieval.canonical_json import sha256_file


SEED = 20261112
RUNS = Path("data/financebench/ablation_runs")
FIXED_COMPARISONS = {
    "company_rank": "dense", "period_rank": "dense", "table_rank": "dense",
    "table_rank20": "dense20", "table_rank100": "dense100", "parent_selective": "dense",
    "graphrag_local": "dense", "hipporag_pagerank": "dense", "lightrag_dual_level": "dense",
    "dbsf": "rrf", "route_rrf": "rrf", "rrf_preserve_dense": "rrf",
    "colbert_maxsim": "dense20", "qdrant_multivector": "dense20", "cross_encoder": "dense20",
}
FROZEN_HISTORICAL = {
    "hard_negative_runs/m12-results.json": "sha256:db0ee70e6239aa5ce5896b3a3199d3b0666ecac78dd89e41fff7641fa283af74",
    "advanced_runs/m14-r6.json": "sha256:7850fb86bf4104d65e5e746301624bd1d6c196eff8939d044854e7a7925b4081",
    "advanced_runs/m14-colbert.json": "sha256:a6a9d29a9c03da04e0d5c58969bdb033e9dbe5359f7699484e3e02da837277db",
    "advanced_runs/m14-cross-encoder.json": "sha256:47f63695fcbbc097920868d3eb80fdc743d85ae48d5b022587134133e2307923",
    "advanced_runs/m14-graphs.json": "sha256:60ce597bf0ad9d70c29ee253aa5c6900f8a35648d1ee5f6304eef5ac3013b97f",
}


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _signature(rows):
    return [(row["case_id"], row["grounded_exact"], row["disposition"], row["answer"], row["citation_sources"])
            for row in rows]


def _request_signature(rows):
    return [(row["case_id"], [(" ".join(call["query"].casefold().split()), call["scope"]) for call in row["queries"]])
            for row in rows if row["split"] == "validation"]


def _fixed_pool(before, after):
    changed = []
    for section in ("m12_per_case", "pages_per_case"):
        for left, right in zip(before[section], after[section], strict=True):
            if left["case_id"] != right["case_id"] or left["candidate_ids"] != right["candidate_ids"]:
                changed.append((section, left["case_id"]))
    compared_requests = 0
    for left, right in zip(before["e2e_per_case"], after["e2e_per_case"], strict=True):
        if left["case_id"] != right["case_id"]:
            raise ValueError("Graph case identities changed across the comparison")
        key = lambda row: (row["query"], tuple(row["scope"]))
        baseline = {key(row): row["candidate_ids"] for row in left["queries"]}
        for call in right["queries"]:
            compared_requests += 1
            if baseline.get(key(call)) != call["candidate_ids"]:
                changed.append(("graph_requests", left["case_id"]))
    return {"changed_cases": changed, "graph_requests_compared": compared_requests}


def _complete_pair(after, before, groups):
    rows = lambda records: [{"case_id": row["case_id"], "answerable": True, "grounded_exact": row["full_at_10"]}
                            for row in records]
    return paired_grounded_exact(rows(after), rows(before), groups, seed=SEED)


def _safety(variant, baseline):
    comparisons = {}
    for key in ("m13_safety", "direct_safety"):
        left, right = baseline[key]["per_case"], variant[key]["per_case"]
        if [row["case_id"] for row in left] != [row["case_id"] for row in right]:
            raise ValueError("Safety cohorts differ")
        comparisons[key] = {
            "grounded_regressions": [old["case_id"] for old, new in zip(left, right, strict=True)
                                     if old["grounded_exact"] and not new["grounded_exact"]],
            "unsupported_release_cases": [row["case_id"] for row in right if row["unsupported_released_claims"] > 0],
            "summary": variant[key]["summary"],
        }
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=RUNS / "q5-utility-core.json")
    parser.add_argument("--colbert", type=Path, default=RUNS / "q5-utility-colbert.json")
    parser.add_argument("--cross", type=Path, default=RUNS / "q5-utility-cross.json")
    parser.add_argument("--natural", type=Path, default=RUNS / "q5-utility-natural-runtime.json")
    parser.add_argument("--api", type=Path, default=RUNS / "q5-utility-api.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in ("core", "colbert", "cross", "natural")}
    runs = {name: _read(path) for name, path in paths.items()}
    core = runs["core"]
    variants = dict(core["variants"])
    for name in ("colbert", "cross", "natural"):
        if runs[name]["configuration"] != core["configuration"]:
            raise ValueError(f"{name} benchmark inputs differ from the frozen core inputs")
        for key, variant in runs[name]["variants"].items():
            if key in variants and _signature(variant["e2e_per_case"]) != _signature(variants[key]["e2e_per_case"]):
                raise ValueError(f"{name} did not reproduce {key} on the same requests")
            if key not in variants or "m13_safety" in variant:
                variants[key] = variant

    m12_groups = {case.case_id: {case.evidence[0].document.split("_", 1)[0]} for case in M12_CASES}
    comparisons = {}
    for name, variant in variants.items():
        if "m12" not in variant:
            continue
        baseline = variants[FIXED_COMPARISONS.get(name, "dense")]
        comparisons[name] = {
            "baseline": FIXED_COMPARISONS.get(name, "dense"),
            "m12_complete_evidence_pair": _complete_pair(variant["m12_per_case"], baseline["m12_per_case"], m12_groups),
            "validation_complete_evidence_pair": _complete_pair(
                [row for row in variant["pages_per_case"] if row["split"] == "validation"],
                [row for row in baseline["pages_per_case"] if row["split"] == "validation"], ISSUERS,
            ),
            "m12_failure_changes": [{"case_id": after["case_id"], "gold_ranks_before": before["gold_ranks"],
                                     "gold_ranks_after": after["gold_ranks"], "negative_ranks_before": before["known_negative_ranks"],
                                     "negative_ranks_after": after["known_negative_ranks"]}
                                    for before, after in zip(baseline["m12_per_case"], variant["m12_per_case"], strict=True)
                                    if (before["gold_ranks"], before["known_negative_ranks"])
                                    != (after["gold_ranks"], after["known_negative_ranks"])],
        }
        if name in FIXED_COMPARISONS:
            comparisons[name]["fixed_pool"] = _fixed_pool(baseline, variant)

    data = Path("data/financebench")
    historical = {key: sha256_file(data / key) for key in FROZEN_HISTORICAL}
    m12_reference = _read(data / "hard_negative_runs/m12-results.json")["variants"]["dense"]["per_case"]
    dense_m12_matches = all(left["case_id"] == right["case_id"] and left["ranking"] == right["ranking"]
                            for left, right in zip(m12_reference, variants["dense"]["m12_per_case"], strict=True))
    safety = {name: _safety(variant, variants["natural_dense"])
              for name, variant in variants.items() if name != "natural_dense" and "m13_safety" in variant}
    runtime = variants["natural_runtime"]
    runtime_safe = all(not result["unsupported_release_cases"] and not result["grounded_regressions"]
                       for result in safety["natural_runtime"].values())
    smoke = _read(args.api) if args.api.is_file() else None
    report = {
        "configuration": core["configuration"], "resources": {name: run["resources"] for name, run in runs.items()},
        "historical_artifacts": historical,
        "variants": {name: {key: value for key, value in variant.items() if not key.endswith("_per_case")
                           and not key.endswith("_safety")} for name, variant in variants.items()},
        "paired_ranking": comparisons, "natural_route_safety": safety,
        "loopback_smoke": smoke,
        "gates": {
            "historical_runs_unchanged": historical == FROZEN_HISTORICAL,
            "dense_reproduces_m12_order": dense_m12_matches,
            "fixed_ranking_pools_match": all(not result["fixed_pool"]["changed_cases"]
                                             for result in comparisons.values() if "fixed_pool" in result),
            "candidate_improves_validation_without_unsupported_release": any(
                variant.get("paired_validation", {}).get("grounded_exact_delta", 0) > 0
                and variant["e2e"]["unsupported_releases"] == 0 for variant in variants.values()),
            "adopted_runtime_improves_without_safety_regression": (
                runtime_safe and runtime["paired_validation"]["grounded_exact_delta"] > 0
                and runtime["e2e"]["unsupported_releases"] == 0),
            "adopted_runtime_matches_control_query_scopes": _request_signature(runtime["e2e_per_case"])
            == _request_signature(variants["natural_dense"]["e2e_per_case"]),
        },
    }
    if smoke is not None:
        report["gates"]["loopback_smoke_verified"] = (
            len(smoke["statement"]["cases"]) == len(smoke["dense"]["cases"]) == 5
            and all(row["grounded_exact"] and row["unsupported_released_claims"] == 0
                    for row in smoke["statement"]["cases"]))
        paths["loopback_smoke"] = args.api
    write_json_atomic(args.output, report)
    write_json_atomic(args.manifest, build_manifest(
        p1_run=P1_RUN, source_manifest=data / "source_manifest.json", sec_manifest=RUNS / "m13-sec/manifest.json",
        pages=P1_PAGE_CACHE, artifacts={**paths, "summary": args.output, **{key: data / key for key in historical}},
        configuration=report["configuration"], code_files=(
            "configs/retrieval_utility.py", "src/evaluation/retrieval_utility.py", "scripts/run_retrieval_utility.py",
            "scripts/summarize_retrieval_utility.py", "scripts/run_late_interaction_retrieval.py",
            "src/retrieval/financial_statement_ranker.py", "src/retrieval/frozen_dense.py", "scripts/run_local_research.py",
        ),
    ))
    print(report["gates"])
    if not all(report["gates"].values()):
        raise SystemExit("A Q5 comparison gate failed")


if __name__ == "__main__":
    main()
