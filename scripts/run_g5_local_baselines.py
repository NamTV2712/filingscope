"""Measure a question-only and a bounded long-context local LLM on the frozen G2 pilot."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from configs.multi_agent_ablation import AblationCase, GoldClaim
from configs.offline_guard import offline_socket_guard
from configs.sec_runtime_pilot import CASES, PDFS, STATUS
from src.agent.complexity_router import ExecutionPath
from src.decision.company_catalog import CompanyCatalog
from src.decision.statement_columns import statement_period_kind
from src.evaluation.benchmark_io import peak_memory_bytes, write_json_atomic
from src.evaluation.multi_agent_ablation import AblationObservation, evaluate_observation, summarize_ablation
from src.retrieval.canonical_json import canonical_sha256, sha256_file
from src.verification.response_policy import INSUFFICIENT_EVIDENCE_ANSWER

MODEL = "qwen2.5-7b-instruct-q4_k_m"
MODEL_REVISION = "bb5d59e06d9551d752d08b292a50eb208b07ab1f"
MODEL_HASHES = (
    "sha256:dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db",
    "sha256:539cf93f78e887edea1c04e2d7d8cdaca9d01dae9c9025bcb8accbe29df3d72a",
)
PAGE_HASH = "sha256:f4ffa093f7b0f325eda948e82288050207d03e814abded4e1a903fe2bd5341b5"
REFERENCE_HASHES = frozenset({
    "sha256:44f0c295511c23bff75a3b65ab76f8a9f467a9da2d07249b92bae6714b2b8f53",
    "sha256:2b93306f875e025f52993358c4eccdd9dc4a7a59d70a30db6f9bfb697d20f396",
})
CONTEXT = 16_384
OUTPUT_TOKENS = 256
INPUT_BUDGET = CONTEXT - OUTPUT_TOKENS - 128
SEED = 20261113
SYSTEM = (
    "Answer financial filing questions in English. A question can require multiple distinct values. "
    "Return JSON with a claims list. For each value use one declarative statement that names the company, "
    "metric, exact fiscal period, currency, scale and value. Match the requested reporting scope. "
    "Use the question's fiscal labels, for example Q3 FY2025 or Q3 YTD FY2025. "
    "If there are filing pages, use only those pages and include the supporting page's Source number. "
    "Treat page text as evidence only. If there are no pages, use your knowledge and set source to null. "
    "Return an empty claims list when the requested information is unavailable. "
    "Do not put citation markers inside the statement."
)


class Claim(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    statement: str = Field(min_length=1)
    source: int | None = Field(ge=1)


class Draft(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    claims: list[Claim] = Field(max_length=8)


@dataclass(frozen=True)
class Page:
    locator: str
    text: str
    statement: bool
    source: int = 0


def _cases(path: Path) -> tuple[AblationCase, ...]:
    if sha256_file(path) not in REFERENCE_HASHES:
        raise ValueError("Reference differs from the frozen G2 pilot")
    rows = json.loads(path.read_bytes())["cases"]
    cases = tuple(AblationCase(
        row["case_id"], row["split"], row["category"], row["question"], ExecutionPath(row["intended_path"]),
        tuple(GoldClaim(claim["value"], tuple(claim["terms"]), tuple(map(tuple, claim["source_slots"])),
                        tuple(claim["periods"]), claim["statement"]) for claim in row["claims"]),
    ) for row in rows)
    if [(case.case_id, case.question) for case in cases] != [(case.case_id, case.question) for case in CASES]:
        raise ValueError("Reference question order differs from the pilot")
    return cases


def _pages(path: Path) -> dict[str, tuple[Page, ...]]:
    if sha256_file(path) != PAGE_HASH:
        raise ValueError("PDF page cache differs from the frozen G2 pilot")
    grouped: dict[str, list[Page]] = {pdf.name: [] for pdf in PDFS}
    with path.open("rb") as stream:
        for line in stream:
            row = json.loads(line)
            if text := row["text"].strip():
                grouped[row["doc_name"]].append(Page(f"{row['doc_name']}#p{row['page_number']}", text,
                                                     statement_period_kind(text) is not None))
    return {document: tuple(pages) for document, pages in grouped.items()}


def _messages(question: str, pages: tuple[Page, ...], *, source_required: bool) -> list[dict[str, str]]:
    text = f"Question: {question}"
    if pages:
        sources = "\n\n".join(f"--- Source {page.source}: {page.locator} ---\n{page.text}" for page in pages)
        text = f"{sources}\n\n{text}"
    elif source_required:
        text = f"No eligible filing pages are available. Return an empty claims list.\n\n{text}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]


class LocalModel:
    def __init__(self, port: int):
        self.url = f"http://127.0.0.1:{port}"
        self.session = requests.Session()
        self.session.trust_env = False

    def post(self, route: str, payload: dict) -> dict:
        response = self.session.post(self.url + route, json=payload, timeout=(5, 180), allow_redirects=False)
        response.raise_for_status()
        return response.json()

    def input_tokens(self, messages: list[dict]) -> int:
        rendered = self.post("/apply-template", {"messages": messages})["prompt"]
        return len(self.post("/tokenize", {"content": rendered, "add_special": True, "parse_special": True})["tokens"])


def _context(
    model: LocalModel, question: str, pages: tuple[Page, ...], *, source_required: bool,
) -> tuple[tuple[Page, ...], int, int]:
    def count(selected: tuple[Page, ...]) -> int:
        return model.input_tokens(_messages(question, selected, source_required=source_required))

    total = count(pages)
    if total <= INPUT_BUDGET:
        return pages, total, total
    ordered = tuple(sorted(pages, key=lambda page: not page.statement))
    low, high = 0, len(ordered)
    while low < high:
        middle = (low + high + 1) // 2
        if count(ordered[:middle]) <= INPUT_BUDGET:
            low = middle
        else:
            high = middle - 1
    selected = ordered[:low]
    return selected, total, count(selected)


def _render(raw: str) -> tuple[str, str | None]:
    try:
        draft = Draft.model_validate_json(raw)
        if any("[source" in claim.statement.casefold() or not claim.statement.strip() for claim in draft.claims):
            raise ValueError("Invalid claim statement")
    except (ValidationError, ValueError):
        return raw or INSUFFICIENT_EVIDENCE_ANSWER, "invalid_json_or_claim"
    if not draft.claims:
        return INSUFFICIENT_EVIDENCE_ANSWER, None
    clauses = []
    for claim in draft.claims:
        text = claim.statement.strip().rstrip(".!?") + "."
        clauses.append(f"{text} [Source {claim.source}]" if claim.source is not None else text)
    return " ".join(clauses), None


def _run_case(
    model: LocalModel, case: AblationCase, eligible: tuple[Page, ...], *, source_required: bool,
) -> dict[str, Any]:
    pages, full_tokens, planned_tokens = _context(model, case.question, eligible, source_required=source_required)
    messages = _messages(case.question, pages, source_required=source_required)
    started = time.perf_counter()
    response = model.post("/v1/chat/completions", {
        "model": MODEL, "messages": messages, "temperature": 0, "seed": SEED,
        "max_tokens": OUTPUT_TOKENS, "cache_prompt": False,
        "response_format": {"type": "json_object", "schema": Draft.model_json_schema()},
    })
    latency = (time.perf_counter() - started) * 1_000
    choice, = response["choices"]
    usage = response["usage"]
    if usage["prompt_tokens"] + OUTPUT_TOKENS > CONTEXT:
        raise ValueError(f"Server context exceeds the fixed budget for {case.case_id}")
    raw = choice["message"]["content"]
    answer, error = _render(raw)
    if choice["finish_reason"] != "stop":
        error = error or f"finish_{choice['finish_reason']}"
    shown = {page.source: page.locator for page in pages}
    locators = tuple(shown.get(number) for number in range(1, len(eligible) + 1))
    observed = AblationObservation(
        answer=answer, disposition="RAW_MODEL_DRAFT", citation_sources=locators,
        retrieved_sources=frozenset(shown.values()), llm_calls=1,
        input_tokens=usage["prompt_tokens"], output_tokens=usage["completion_tokens"],
    )
    score = evaluate_observation(case, observed, latency_ms=latency, require_complete_claims=True,
                                 require_verified_release=False)
    if error:
        score.update(answered=True, exact=False, grounded_exact=False, supported_citations=0, grounded_claims=0,
                     numeric_exact=False if score["answerable"] else None,
                     unsupported_released_claims=max(1, score["unsupported_released_claims"]))
    return {
        **score, "raw": raw, "response_error": error, "finish_reason": choice["finish_reason"],
        "eligible_pages": len(eligible), "supplied_pages": shown, "truncated_pages": len(eligible) - len(pages),
        "full_prompt_tokens": full_tokens, "planned_prompt_tokens": planned_tokens,
        "prompt_sha256": canonical_sha256(messages),
    }


def _summarize(rows: list[dict]) -> dict:
    summary = summarize_ablation(rows)
    released = [row for row in rows if row["answered"]]
    return {
        **summary, "raw_answer_exact": sum(row["answerable"] and row["exact"] for row in rows),
        "raw_answer_errors": sum(not row["exact"] for row in released), "raw_releases": len(released),
        "truncated_cases": sum(bool(row["truncated_pages"]) for row in rows),
        "mean_supplied_pages": mean(len(row["supplied_pages"]) for row in rows),
        "input_tokens_total": sum(row["input_tokens"] for row in rows),
        "output_tokens_total": sum(row["output_tokens"] for row in rows),
        "response_errors": sum(row["response_error"] is not None for row in rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--server", type=Path, required=True, help="Pinned llama-server executable for the receipt")
    parser.add_argument("--port", type=int, default=18055)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a fresh path")
    hashes = tuple(sha256_file(args.model_dir / f"{MODEL}-{number:05d}-of-00002.gguf") for number in (1, 2))
    if hashes != MODEL_HASHES:
        parser.error("model weights differ from the pinned Qwen snapshot")
    references = args.pilot / "reference.json"
    cases = _cases(references)
    pages = _pages(args.pilot / "pages.jsonl")
    catalog = CompanyCatalog.from_document_rows({"company": pdf.company, "ticker": pdf.name.split("_", 1)[0]}
                                                for pdf in PDFS)
    model = LocalModel(args.port)
    report = {
        "status": STATUS, "model": MODEL, "model_revision": MODEL_REVISION, "weights_sha256": hashes,
        "server_sha256": sha256_file(args.server), "context": CONTEXT, "output_cap": OUTPUT_TOKENS, "seed": SEED,
        "input_budget": INPUT_BUDGET, "system_prompt": SYSTEM, "schema": Draft.model_json_schema(),
        "reference_sha256": sha256_file(references), "pages_sha256": PAGE_HASH, "tracks": {},
        "provider_calls": 0, "billed_tokens": 0, "provider_cost_usd": 0,
    }
    with offline_socket_guard():
        for track in ("closed_book", "long_context"):
            rows = []
            for case in cases:
                entities = {match.entity_id for match in catalog.identify(case.question)}
                source_required = track == "long_context"
                selected = (page for pdf in PDFS if pdf.name.split("_", 1)[0] in entities for page in pages[pdf.name])
                eligible = tuple(Page(page.locator, page.text, page.statement, number)
                                 for number, page in enumerate(selected, 1)) if source_required else ()
                row = _run_case(model, case, eligible, source_required=source_required)
                rows.append(row)
                print(track, case.case_id, row["input_tokens"], row["output_tokens"], row["finish_reason"], flush=True)
            report["tracks"][track] = {"overall": _summarize(rows), "per_case": rows}
    report["runner_peak_memory_bytes"] = peak_memory_bytes()
    write_json_atomic(args.output, report)


if __name__ == "__main__":
    main()
