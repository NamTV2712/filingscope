"""Replay parent-page retrieval and audit annual financial table alignment."""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import mean

from configs.hard_negatives import CASES, P1_CORPUS_FINGERPRINT, P1_INDEX_ID
from configs.multi_agent_ablation import CASES as ABLATION_CASES
from scripts.run_financebench_retrieval import _sha256_file
from scripts.run_hard_negative_retrieval import DEFAULT_RUN, SPLITS, _load_corpus, _peak_memory_bytes
from scripts.run_retrieval_diagnostics import _nearest_rank, _write_json_atomic
from src.decision.company_catalog import CompanyCatalog
from src.decision.models import CoverageStatus
from src.decision.policy import EvidenceDecisionLayer
from src.decision.statement_columns import extract_annual_statement_values
from src.evaluation.answer_metrics import numeric_fact_signatures
from src.evaluation.hard_negative_retrieval import resolve_passages
from src.ingestion.chunker import count_tokens
from src.ingestion.pdf_ingestion import normalize_pdf_page_text
from src.retrieval.parent_context import PageParent, expand_contexts, page_key


DEFAULT_PAGES = Path("data/financebench/cache/extracted_pages_d5c2a1369d9997a3055a.jsonl")
DEFAULT_RANKINGS = Path("data/financebench/hard_negative_runs/m12-results.json")
METRICS = {
    "revenue": "revenue", "operating income": "operating_income", "total assets": "total_assets",
    "cash and cash equivalents": "cash_and_equivalents",
}
SCALES = {"unit": 0, "thousand": 3, "million": 6, "billion": 9}


def _annual_audit_cases():
    slots = {}
    for case in ABLATION_CASES:
        for claim in case.claims:
            if len(claim.periods) != 1 or not claim.periods[0].startswith("FY") or len(claim.source_slots) != 1:
                continue
            pdf_sources = [item for item in claim.source_slots[0] if "#p" in item]
            if not pdf_sources:
                continue
            document, page = pdf_sources[0].rsplit("#p", 1)
            if not document.endswith("_10K"):
                continue
            key = document, int(page)
            metric = METRICS[claim.terms[-1]]
            slots.setdefault((key, metric, claim.periods[0]), (case.question, claim.value))
    return slots


def _read_parents(path, keys, children) -> dict:
    pages = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            key = page_key(row)
            if key in keys:
                if key in pages:
                    raise ValueError(f"Duplicate page cache record: {key}")
                text = normalize_pdf_page_text(row["text"])
                pages[key] = PageParent(*key, text, tuple(item["chunk_id"] for item in children[key]), count_tokens(text))
    if pages.keys() != keys:
        raise ValueError("Frozen PDF cache is missing requested pages")
    return pages


def _audit_statement_rows(children, parents, cases):
    rows = []
    layer = EvidenceDecisionLayer(catalog=CompanyCatalog.from_document_rows(
        child for key, _, _ in cases for child in children[key]
    ))
    for (key, metric, period), (question, expected) in cases.items():
        chunks = children[key]
        metadata = chunks[0]
        _, currency, amount, _, _ = numeric_fact_signatures(expected)[0]
        expected_amount = Decimal(amount)
        finding = next((item for item in layer.assess(question, chunks).findings
                        if item.metric_id == metric and item.period == period), None)
        raw_exact = False
        if finding and finding.status == CoverageStatus.FOUND:
            raw_exact = all(
                fact.currency == currency and fact.scale in SCALES
                and Decimal(fact.numeric_value).scaleb(SCALES[fact.scale]) == expected_amount
                for fact in finding.facts
            ) and bool(finding.facts)
        table = extract_annual_statement_values(
            parents[key].text, form=metadata["doc_type"], filing_year=metadata["reporting_periods"][0],
        )
        aligned = next((value for value in table if value.metric_id == metric and value.period == period), None)
        rows.append({
            "document": key[0], "page": key[1], "source_url": metadata["source_url"],
            "metric": metric, "period": period, "expected": expected,
            "raw_status": finding.status.value if finding else "missing", "raw_exact": raw_exact,
            "aligned_exact": bool(aligned and aligned.currency == currency and aligned.base_amount == expected_amount),
            "aligned_observation": {"header": aligned.header, "row": aligned.row, "amount": str(aligned.base_amount),
                                    "currency": aligned.currency} if aligned else None,
        })
    return {"slot_count": len(rows), "raw_exact": sum(item["raw_exact"] for item in rows),
            "aligned_exact": sum(item["aligned_exact"] for item in rows), "slots": rows}


def _aggregate(rows):
    return {
        "cases": len(rows), "labeled_passage_recall": round(mean(row["recall"] for row in rows), 4),
        "complete_cases": sum(row["complete"] for row in rows),
        "known_negative_exposure_cases": sum(bool(row["known_negatives"]) for row in rows),
        "mean_tokens": round(mean(row["tokens"] for row in rows), 2),
        "mean_contexts": round(mean(row["contexts"] for row in rows), 2),
        "mean_expanded_pages": round(mean(row["expanded_pages"] for row in rows), 2),
        "p95_expansion_ms": _nearest_rank([row["expansion_ms"] for row in rows], .95),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p1-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--pages", type=Path, default=DEFAULT_PAGES)
    parser.add_argument("--rankings", type=Path, default=DEFAULT_RANKINGS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    chunks = _load_corpus(args.p1_run)
    replay = json.loads(args.rankings.read_text(encoding="utf-8"))
    manifest = json.loads((args.p1_run / "run_manifest.json").read_text(encoding="utf-8"))
    if replay["p1_index_id"] != P1_INDEX_ID or replay["corpus_fingerprint"] != P1_CORPUS_FINGERPRINT:
        raise ValueError("Ranking replay is not the frozen P1 corpus")
    if _sha256_file(args.pages) != manifest["extracted_page_cache_sha256"]:
        raise ValueError("Page cache hash does not match P1 provenance")
    passage_ids = {ref: chunks[position]["chunk_id"] for ref, position in resolve_passages(CASES, chunks).items()}
    by_id = {row["chunk_id"]: row for row in chunks}
    children = defaultdict(list)
    for row in chunks:
        children[page_key(row)].append(row)
    ranked_by_case = {row["case_id"]: [by_id[item] for item in row["ranking"]]
                      for row in replay["variants"]["dense"]["per_case"]}
    if ranked_by_case.keys() != {case.case_id for case in CASES}:
        raise ValueError("M12 dense ranking replay lacks the frozen cases")
    audit_cases = _annual_audit_cases()
    keys = {page_key(row) for ranking in ranked_by_case.values() for row in ranking}
    keys.update(key for key, _, _ in audit_cases)
    parents = _read_parents(args.pages, keys, children)
    setup_seconds = time.perf_counter() - started

    results = {}
    for mode in ("children", "parents", "selective"):
        rows = []
        for case in CASES:
            started = time.perf_counter()
            contexts = expand_contexts(ranked_by_case[case.case_id], parents, mode=mode)
            elapsed = (time.perf_counter() - started) * 1000
            included = {chunk_id for context in contexts for chunk_id in context.chunk_ids}
            gold = {passage_ids[item] for item in case.evidence}
            negatives = {passage_ids[item.passage] for item in case.negatives}
            rows.append({
                "case_id": case.case_id, "split": case.split, "recall": len(gold.intersection(included)) / len(gold),
                "complete": gold.issubset(included), "known_negatives": sorted(negatives.intersection(included)),
                "tokens": sum(item.token_count for item in contexts), "contexts": len(contexts),
                "expanded_pages": sum(item.expanded for item in contexts), "expansion_ms": round(elapsed, 4),
                "retained": [{"document": item.document, "page": item.page, "chunk_ids": item.chunk_ids,
                              "source_url": item.source_url, "expanded": item.expanded} for item in contexts],
            })
        results[mode] = {"overall": _aggregate(rows), "per_case": rows,
                         "by_split": {split: _aggregate([row for row in rows if row["split"] == split]) for split in SPLITS}}

    report = {
        "benchmark": "filingscope-parent-context-v1", "index_id": P1_INDEX_ID,
        "corpus_fingerprint": P1_CORPUS_FINGERPRINT, "page_cache_sha256": _sha256_file(args.pages),
        "ranking_report_sha256": _sha256_file(args.rankings), "page_count": len(parents),
        "setup_seconds": round(setup_seconds, 3), "variants": results,
        "statement_audit": _audit_statement_rows(children, parents, audit_cases),
        "peak_memory_bytes": _peak_memory_bytes(), "provider_calls": 0,
    }
    _write_json_atomic(args.output, report)
    print(args.output)


if __name__ == "__main__":
    main()
