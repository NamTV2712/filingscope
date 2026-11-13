"""Estimate closed-book and long-context prompt budgets without calling a model."""

from __future__ import annotations

import argparse
from pathlib import Path

from configs.financebench import P1_PAGE_CACHE, P1_RUN
from configs.multi_agent_ablation import CASES
from configs.offline_guard import offline_socket_guard
from src.evaluation.benchmark_io import write_json_atomic
from src.generation.answer_generator import build_generation_messages, estimate_prompt_tokens
from src.retrieval.frozen_artifacts import load_frozen_corpus
from src.retrieval.pdf_page_cache import FrozenPdfPages


def plan(context_budget: int) -> dict:
    chunks = load_frozen_corpus(P1_RUN)
    pages = FrozenPdfPages.from_run(P1_PAGE_CACHE, P1_RUN)
    document_pages: dict[str, set[int]] = {}
    for chunk in chunks:
        document_pages.setdefault(chunk["doc_name"], set()).add(chunk["page_number"])
    rows = []
    for case in CASES:
        # Use source locators only to size an oracle-document dry run.
        # These document selections are unsuitable for open corpus comparisons.
        documents = sorted({source.rsplit("#p", 1)[0] for claim in case.claims
                            for slot in claim.source_slots for source in slot if "#p" in source})
        evidence = [
            {"doc_name": document, "page_number": number, "text": text}
            for document in documents for number in sorted(document_pages.get(document, ()))
            if (text := pages.get(document, number)) is not None
        ]
        closed_tokens = estimate_prompt_tokens(build_generation_messages(case.question, ()))
        full_tokens = estimate_prompt_tokens(build_generation_messages(case.question, evidence)) if evidence else None
        rows.append({
            "case_id": case.case_id, "closed_book_estimated_input_tokens": closed_tokens,
            "oracle_documents": documents, "document_page_count": len(evidence),
            "long_context_estimated_input_tokens": full_tokens,
            "long_context_fits_input_budget": full_tokens <= context_budget if full_tokens is not None else None,
        })
    return {
        "status": "API_VALIDATION_BLOCKED",
        "model_id": None,
        "budget_tokens_input": context_budget,
        "estimation": "cl100k_base proxy with existing provider prompt envelope",
        "long_context_source_selection": "oracle_document_budgeting_only",
        "provider_calls": 0, "billed_tokens": 0, "provider_cost_usd": 0,
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-budget", type=int, default=100_000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.context_budget < 1:
        parser.error("Input context budget must be positive")
    with offline_socket_guard():
        result = plan(args.context_budget)
        write_json_atomic(args.output, result)
    print(f"Prepared prompt budgets for {len(result['cases'])} cases")


if __name__ == "__main__":
    main()
