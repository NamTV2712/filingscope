"""Score Q2 fiscal labels, units and provenance on frozen filing artifacts."""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from configs.financebench import P1_PAGE_CACHE, P1_RUN
from configs.financial_normalization import AMBIGUOUS_PAGES, COMPANY_FACT_CELLS, STATEMENT_CELLS
from configs.offline_guard import offline_socket_guard
from configs.sec_snapshots import SEC_CUTOFF, SEC_ISSUERS
from src.decision.statement_columns import extract_annual_statement_values, parse_statement_columns
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.company_facts_replay import CompanyFactsReplay
from src.evaluation.m13_failure_replay import expected_slots
from src.evaluation.post_m15_manifest import build_manifest
from src.evaluation.retrieval_metrics import _nearest_rank
from src.ingestion.company_facts import CompanyFactsResolver
from src.retrieval.canonical_json import sha256_file
from src.retrieval.pdf_page_cache import FrozenPdfPages


_DATA = Path("data/financebench")
_EXPONENTS = {"millions": 6, "thousands": 3}
_CODE_FILES = (
    "configs/financial_normalization.py",
    "scripts/run_financial_normalization_evaluation.py",
    "scripts/run_multi_agent_ablation.py",
    "src/agent/specialists.py",
    "src/decision/evidence_coverage.py",
    "src/decision/models.py",
    "src/decision/period_value_parser.py",
    "src/decision/statement_columns.py",
    "src/ingestion/company_facts.py",
    "src/ingestion/period_identity.py",
    "src/ledger/models.py",
    "src/retrieval/pdf_page_cache.py",
    "src/verification/claim_verifier.py",
)


def _score_statement_cells(parsed, baseline, labels):
    rows = []
    for label in labels:
        key = label.document, label.page
        for column, period, raw in label.columns:
            actual = next((cell for cell in parsed[key].values
                           if cell.metric_id == label.metric and cell.column_index == column), None)
            base = Decimal(raw).scaleb(_EXPONENTS[label.scale])
            correct_header = bool(
                actual and actual.period == period and actual.period_identity is not None
                and actual.period_identity.kind == label.kind
            )
            rows.append({
                "split": label.split, "document": label.document, "page": label.page,
                "metric": label.metric, "column": column, "expected_period": period,
                "actual_period": actual.period if actual else None,
                "legacy_exact": any(
                    cell.metric_id == label.metric and cell.period == period
                    and cell.base_amount == base and cell.currency == "USD"
                    for cell in baseline[key]
                ),
                "header_exact": correct_header,
                "unit_exact": bool(actual and actual.scale == label.scale and actual.currency == "USD"),
                "amount_exact": correct_header and actual.base_amount == base,
                "source_locator_complete": bool(actual and actual.row_index is not None and actual.column_index is not None),
            })
    return rows


def _score_retro_pages(parsed, baseline, expected):
    rows = []
    for key, slots in sorted(expected.items()):
        for (metric, period), amount in sorted(slots.items()):
            def exact(cells):
                return any(
                    cell.metric_id == metric and cell.period == period
                    and cell.base_amount == amount and cell.currency == "USD"
                    for cell in cells
                )

            rows.append({
                "document": key[0], "page": key[1], "metric": metric, "period": period,
                "legacy_exact": exact(baseline[key]), "q2_exact": exact(parsed[key].values),
            })
    return rows


def _score_sec(sec_dir):
    sec = CompanyFactsReplay(sec_dir, SEC_ISSUERS, latest_filed=SEC_CUTOFF)
    resolvers = {
        ticker: CompanyFactsResolver(sec.facts[cik], expected_cik=cik) for ticker, cik in SEC_ISSUERS.items()
    }
    rows = []
    for label in COMPANY_FACT_CELLS:
        resolved = resolvers[label.ticker].resolve(label.metric, label.period)
        actual = resolved.fact
        rows.append({
            "ticker": label.ticker, "metric": label.metric, "period": label.period,
            "status": resolved.reason,
            "value_and_currency_exact": bool(actual and actual.value == Decimal(label.amount) and actual.currency == "USD"),
            "provenance_exact": bool(
                actual and actual.provenance.accession == label.accession
                and actual.provenance.period_start == label.start and actual.provenance.period_end == label.end
                and actual.fiscal_period == label.period and actual.period_identity.label == label.period
            ),
        })
    return rows


def evaluate(args):
    from configs.multi_agent_ablation import CASES

    source = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    p1_manifest = json.loads((args.p1_run / "run_manifest.json").read_text(encoding="utf-8"))
    if p1_manifest["dataset_source_manifest_sha256"] != sha256_file(args.source_manifest):
        raise ValueError("Source manifest does not match the frozen P1 run")
    metadata = {row["doc_name"]: row for row in source["files"]["source_pdfs"]}
    started = perf_counter()
    pages = FrozenPdfPages.from_run(args.pages, args.p1_run)
    setup_seconds = perf_counter() - started
    retrospective = {}
    for case in CASES:
        for slot in expected_slots(case):
            for source_id in slot.sources:
                if "#p" in source_id:
                    doc, page = source_id.rsplit("#p", 1)
                    retrospective.setdefault((doc, int(page)), {})[(slot.metric, slot.period)] = slot.amount
    keys = (
        {(case.document, case.page) for case in STATEMENT_CELLS}
        | {(doc, page) for doc, page, _ in AMBIGUOUS_PAGES}
        | retrospective.keys()
    )
    parsed, baseline, times = {}, {}, {"legacy": [], "q2": []}
    for doc, page in sorted(keys):
        text = pages.get(doc, page)
        if text is None:
            raise ValueError(f"Missing labeled source page: {doc} page {page}")
        meta = metadata[doc]
        fiscal_year, = meta["reporting_periods"]
        quarter = re.search(r"(?:19|20)\d{2}Q([1-4])(?:_|$)", doc, re.I)
        started = perf_counter()
        baseline[doc, page] = extract_annual_statement_values(text, form=meta["doc_type"], filing_year=fiscal_year)
        times["legacy"].append((perf_counter() - started) * 1000)
        started = perf_counter()
        parsed[doc, page] = parse_statement_columns(
            text, form=meta["doc_type"], fiscal_year=int(fiscal_year), quarter=int(quarter[1]) if quarter else None,
        )
        times["q2"].append((perf_counter() - started) * 1000)

    statement_rows = _score_statement_cells(parsed, baseline, STATEMENT_CELLS)
    retro_rows = _score_retro_pages(parsed, baseline, retrospective)
    negative_rows = [
        {"document": doc, "page": page, "metric": metric,
         "withheld": not any(cell.metric_id == metric for cell in parsed[doc, page].values)}
        for doc, page, metric in AMBIGUOUS_PAGES
    ]
    sec_rows = _score_sec(args.sec_dir)
    counts = {}
    for split in ("development", "validation"):
        rows = [row for row in statement_rows if row["split"] == split]
        counts[split] = {"cells": len(rows), **{
            field: sum(row[field] for row in rows)
            for field in ("legacy_exact", "header_exact", "unit_exact", "amount_exact", "source_locator_complete")
        }}
    return {
        "benchmark": "filingscope-financial-normalization-v1",
        "labels": "provisional_source_checked_ai_assisted",
        "configuration": {
            "statement_labels_sha256": sha256_file(Path("configs/financial_normalization.py")),
            "source": "pinned pypdf page cache and SEC Company Facts snapshots",
            "random_seed": None,
        },
        "statement_cells": {"counts": counts, "rows": statement_rows},
        "retrospective_m13_pages": {
            "cells": len(retro_rows), "legacy_exact": sum(row["legacy_exact"] for row in retro_rows),
            "q2_exact": sum(row["q2_exact"] for row in retro_rows), "rows": retro_rows,
        },
        "ambiguity_controls": negative_rows,
        "company_facts": {"cells": len(sec_rows), "exact": sum(
            row["value_and_currency_exact"] and row["provenance_exact"] for row in sec_rows
        ), "rows": sec_rows},
        "resources": {"pages": len(keys), "setup_seconds": round(setup_seconds, 3),
                      "peak_memory_bytes": peak_memory_bytes(), "page_parser_latency_ms": {
                          key: {f"p{p}": round(_nearest_rank(values, p / 100), 3) for p in (50, 95)}
                          for key, values in times.items()
                      }},
        "provider_calls": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p1-run", type=Path, default=P1_RUN)
    parser.add_argument("--pages", type=Path, default=P1_PAGE_CACHE)
    parser.add_argument("--source-manifest", type=Path, default=_DATA / "source_manifest.json")
    parser.add_argument("--sec-dir", type=Path, default=_DATA / "ablation_runs/m13-sec")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ablation", type=Path, help="Bind a paired Q2 M13 replay to the manifest")
    parser.add_argument("--baseline", type=Path, default=_DATA / "ablation_runs/post-m15-baseline.json")
    args = parser.parse_args()
    with offline_socket_guard():
        report = evaluate(args)
    artifacts = {"normalization": args.output}
    if args.ablation:
        from scripts.run_failure_attribution import _BOOTSTRAP_SAMPLES, _paired_comparison
        from scripts.run_hard_negative_retrieval import RANDOM_SEED

        candidate = json.loads(args.ablation.read_text(encoding="utf-8"))
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        report["paired_m13"] = {}
        for variant in ("B4", "B5"):
            changed = candidate["variants"][variant]["per_case"]
            frozen = baseline["variants"][variant]["per_case"]
            if [row["case_id"] for row in changed] != [row["case_id"] for row in frozen]:
                raise ValueError(f"Paired M13 case IDs differ for {variant}")
            comparison = _paired_comparison({"B4": changed, "B5": frozen})
            comparison["direction"] = "Q2 minus frozen Post-M15 baseline"
            report["paired_m13"][variant] = comparison
        report["configuration"].update(random_seed=RANDOM_SEED, bootstrap_samples=_BOOTSTRAP_SAMPLES)
        artifacts["ablation"] = args.ablation
        artifacts["baseline"] = args.baseline
    write_json_atomic(args.output, report)
    write_json_atomic(args.manifest, build_manifest(
        p1_run=args.p1_run, source_manifest=args.source_manifest, sec_manifest=args.sec_dir / "manifest.json",
        pages=args.pages, artifacts=artifacts, configuration=report["configuration"], code_files=_CODE_FILES,
    ))
    print(args.output, flush=True)


if __name__ == "__main__":
    main()
