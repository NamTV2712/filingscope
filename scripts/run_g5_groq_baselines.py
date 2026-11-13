"""Plan or run matched Groq GPT-OSS 120B baselines on the frozen SEC pilot."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import deque
from pathlib import Path

import requests
import tiktoken
from dotenv import dotenv_values

from configs.sec_runtime_pilot import PDFS, STATUS
from scripts.run_g5_local_baselines import Draft, Page, _cases, _context, _messages, _pages, _render, _summarize
from src.decision.company_catalog import CompanyCatalog
from src.evaluation.benchmark_io import write_json_atomic
from src.evaluation.multi_agent_ablation import AblationObservation, evaluate_observation
from src.retrieval.canonical_json import canonical_sha256, sha256_file

MODEL = "openai/gpt-oss-120b"
OUTPUT_CAP = 768
INPUT_CAP = 5_200
FREE_TPM = 8_000
FREE_TPD = 200_000
PRICE_INPUT = 0.15
PRICE_OUTPUT = 0.60
TOKENIZER_OVERHEAD = 512


class TokenEstimate:
    def __init__(self):
        self.encoding = tiktoken.get_encoding("o200k_harmony")
        self.schema_tokens = len(self.encoding.encode_ordinary(str(Draft.model_json_schema())))

    def input_tokens(self, messages: list[dict]) -> int:
        return self.schema_tokens + TOKENIZER_OVERHEAD + sum(
            len(self.encoding.encode_ordinary(message["content"])) for message in messages
        )


def _request(messages: list[dict]) -> dict:
    schema = Draft.model_json_schema()
    schema["properties"]["claims"].pop("maxItems", None)
    schema["$defs"]["Claim"]["properties"]["statement"].pop("minLength", None)
    for alternative in schema["$defs"]["Claim"]["properties"]["source"]["anyOf"]:
        alternative.pop("minimum", None)
    return {
        "model": MODEL, "messages": messages, "temperature": 0, "reasoning_effort": "low",
        "include_reasoning": False, "max_completion_tokens": OUTPUT_CAP,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "financial_answer", "strict": True, "schema": schema,
        }},
    }


def _plan(pilot: Path) -> list[dict]:
    cases = _cases(pilot / "reference.json")
    pages = _pages(pilot / "pages.jsonl")
    catalog = CompanyCatalog.from_document_rows({"company": pdf.company, "ticker": pdf.name.split("_", 1)[0]}
                                                for pdf in PDFS)
    tokenizer = TokenEstimate()
    plan = []
    for track in ("closed_book", "long_context"):
        for case in cases:
            source_required = track == "long_context"
            entities = {match.entity_id for match in catalog.identify(case.question)}
            selected = (page for pdf in PDFS if pdf.name.split("_", 1)[0] in entities for page in pages[pdf.name])
            eligible = tuple(Page(page.locator, page.text, page.statement, number)
                             for number, page in enumerate(selected, 1)) if source_required else ()
            shown, full_tokens, prompt_tokens = _context(
                tokenizer, case.question, eligible, source_required=source_required, input_budget=INPUT_CAP,
            )
            messages = _messages(case.question, shown, source_required=source_required)
            plan.append({"track": track, "case": case, "messages": messages, "full_prompt_tokens": full_tokens,
                         "planned_prompt_tokens": prompt_tokens, "eligible_pages": len(eligible),
                         "supplied_pages": {page.source: page.locator for page in shown},
                         "truncated_pages": len(eligible) - len(shown)})
    return plan


def _public_plan(plan: list[dict]) -> list[dict]:
    return [{**{key: value for key, value in row.items() if key not in {"case", "messages"}},
             "case_id": row["case"].case_id, "prompt_sha256": canonical_sha256(row["messages"])} for row in plan]


def _live(plan: list[dict], api_key: str, output: Path, report: dict) -> None:
    session = requests.Session()
    session.trust_env = False
    session.headers["Authorization"] = f"Bearer {api_key}"
    rows = {track: [] for track in ("closed_book", "long_context")}
    report["tracks"] = {}
    next_request = 0.0
    requests_in_window: deque[tuple[float, int]] = deque()
    reserved = 0
    for row, receipt in zip(plan, report["cases"], strict=True):
        budget = row["planned_prompt_tokens"] + OUTPUT_CAP
        while True:
            now = time.monotonic()
            while requests_in_window and now - requests_in_window[0][0] >= 61:
                reserved -= requests_in_window.popleft()[1]
            if reserved + budget <= FREE_TPM and now >= next_request:
                break
            token_reset = requests_in_window[0][0] + 61 if reserved + budget > FREE_TPM else now
            time.sleep(max(token_reset, next_request) - now)
        started = time.monotonic()
        requests_in_window.append((started, budget))
        reserved += budget
        next_request = started + 2.1
        case = row["case"]
        report["provider_attempts"] += 1
        try:
            response = session.post("https://api.groq.com/openai/v1/chat/completions",
                                    json=_request(row["messages"]), timeout=(10, 60), allow_redirects=False)
        except requests.RequestException as error:
            report["halted"] = {"case_id": case.case_id, "error_type": type(error).__name__}
            break
        if response.status_code != 200:
            code = None
            if response.headers.get("content-type", "").startswith("application/json"):
                try:
                    code = response.json().get("error", {}).get("code")
                except requests.exceptions.JSONDecodeError:
                    pass
            report["halted"] = {"case_id": case.case_id, "http_status": response.status_code, "error_code": code}
            break
        try:
            payload = response.json()
            choice, = payload["choices"]
            usage = payload["usage"]
            returned_model = payload["model"]
        except (ValueError, KeyError, TypeError) as error:
            report["halted"] = {"case_id": case.case_id, "error_type": type(error).__name__}
            break
        if returned_model != MODEL:
            report["halted"] = {"case_id": case.case_id, "error_type": "UnexpectedModel"}
            break
        raw = choice["message"].get("content") or ""
        answer, error = _render(raw)
        if choice["finish_reason"] != "stop":
            error = error or f"finish_{choice['finish_reason']}"
        shown = row["supplied_pages"]
        observed = AblationObservation(
            answer=answer, disposition="RAW_MODEL_DRAFT",
            citation_sources=tuple(shown.get(number) for number in range(1, row["eligible_pages"] + 1)),
            retrieved_sources=frozenset(shown.values()), llm_calls=1,
            input_tokens=usage["prompt_tokens"], output_tokens=usage["completion_tokens"],
        )
        score = evaluate_observation(case, observed, latency_ms=(time.monotonic() - started) * 1000,
                                     require_complete_claims=True, require_verified_release=False)
        if error:
            score.update(answered=True, exact=False, grounded_exact=False, supported_citations=0, grounded_claims=0,
                         numeric_exact=False if score["answerable"] else None,
                         unsupported_released_claims=max(1, score["unsupported_released_claims"]))
        rows[row["track"]].append({**receipt, **score, "raw": raw, "response_error": error,
                                   "finish_reason": choice["finish_reason"], "served_model": returned_model,
                                   "system_fingerprint": payload.get("system_fingerprint")})
        report["tracks"] = {track: {"overall": _summarize(results), "per_case": results}
                            for track, results in rows.items() if results}
        report["provider_calls"] = sum(map(len, rows.values()))
        requests_in_window[-1] = (started, usage["prompt_tokens"] + usage["completion_tokens"])
        reserved += requests_in_window[-1][1] - budget
        write_json_atomic(output, report)
        print(row["track"], case.case_id, usage["prompt_tokens"], usage["completion_tokens"], flush=True)
        if usage["prompt_tokens"] > row["planned_prompt_tokens"]:
            report["halted"] = {"case_id": case.case_id, "error_type": "PromptEstimateExceeded"}
            break
    report["status"] = STATUS if report["provider_calls"] == len(plan) else "INCOMPLETE_PROVIDER_RUN"
    write_json_atomic(output, report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-free", action="store_true", help="Run after confirming the Groq organization is on Free")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a fresh path")
    plan = _plan(args.pilot)
    estimated_input = sum(row["planned_prompt_tokens"] for row in plan)
    maximum_output = OUTPUT_CAP * len(plan)
    if args.execute_free and estimated_input + maximum_output > FREE_TPD:
        parser.error("The planned run exceeds the published Free daily token limit")
    report = {
        "status": "API_VALIDATION_BLOCKED", "model": MODEL, "reference_sha256": sha256_file(args.pilot / "reference.json"),
        "pages_sha256": sha256_file(args.pilot / "pages.jsonl"), "cases": _public_plan(plan),
        "estimated_input_tokens": estimated_input, "maximum_output_tokens": maximum_output,
        "developer_price_estimate_usd": (estimated_input * PRICE_INPUT + maximum_output * PRICE_OUTPUT) / 1_000_000,
        "input_cap": INPUT_CAP, "output_cap": OUTPUT_CAP, "provider_attempts": 0, "provider_calls": 0,
        "request_settings": {key: value for key, value in _request([]).items() if key != "messages"},
    }
    if args.execute_free:
        key = os.getenv("GROQ_API_KEY") or dotenv_values(".env").get("GROQ_API_KEY")
        if not key:
            parser.error("GROQ_API_KEY is missing")
        _live(plan, key, args.output, report)
    else:
        write_json_atomic(args.output, report)
        print(json.dumps({"requests": len(plan), "estimated_input": estimated_input, "output_cap": maximum_output,
                          "developer_price_estimate_usd": report["developer_price_estimate_usd"]}))


if __name__ == "__main__":
    main()
