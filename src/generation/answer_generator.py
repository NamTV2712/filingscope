"""Evidence-grounded answer generation adapted from the source Groq generator."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal
from math import ceil, isfinite
from typing import Any, Protocol

import tiktoken
from pydantic import BaseModel, ConfigDict, Field

from configs.end_to_end import (
    GENERATOR_CACHED_INPUT_USD_PER_MILLION,
    GENERATOR_INPUT_USD_PER_MILLION,
    GENERATOR_MAX_INPUT_TOKENS,
    GENERATOR_MAX_OUTPUT_TOKENS,
    GENERATOR_MODEL_ID,
    GENERATOR_OUTPUT_USD_PER_MILLION,
    GENERATOR_PROMPT_TOKEN_ESTIMATE_MARGIN,
    GENERATOR_TEMPERATURE,
    PROMPT_VERSION,
)


SYSTEM_PROMPT = """You are a financial analyst assistant. Answer questions about financial reports accurately and concisely.

Strict rules:
1. Use only information explicitly stated in the supplied evidence. Do not use outside knowledge.
2. Cite every factual claim with the exact canonical marker [Source N] from the supplied context.
3. If the evidence is insufficient, respond exactly: "I could not find sufficient information in the available documents to answer this question with confidence."
4. Do not speculate, calculate unstated facts, or mix reporting periods.
5. For a numeric trend, comparison, or growth question, list each available
   underlying value with its period before any summary. Report values exactly as
   printed; do not round, abbreviate, convert units, or derive a new number.
6. Preserve financial values, currencies, units, and fiscal periods as shown in evidence.
7. Answer in English.
"""

_FALLBACK_RE = re.compile(
    r"could not find sufficient information|insufficient (?:information|evidence)|"
    r"unable to verify|cannot determine from (?:the )?(?:available )?evidence",
    re.I,
)
_SCALE = Decimal("1000000")
_ENCODING = tiktoken.get_encoding("cl100k_base")


class AnswerGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    answer: str
    model_id: str
    prompt_version: str = PROMPT_VERSION
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    cached_prompt_tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    estimated_cost_usd: Decimal | None = None
    provider_request_id: str | None = None


class AnswerGenerator(Protocol):
    """Narrow generation contract used by the P5 evaluator."""

    model_id: str
    max_output_tokens: int

    def generate(self, question: str, evidence_chunks: Sequence[Mapping[str, Any]]) -> AnswerGenerationResult: ...


def is_fallback_answer(answer: str) -> bool:
    """Match the source generator's insufficient-evidence response family."""
    return bool(_FALLBACK_RE.search(answer))


def build_generation_messages(
    question: str,
    evidence_chunks: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Build stable source labels from evidence order for the prompt contract."""
    context_parts: list[str] = []
    for index, chunk in enumerate(evidence_chunks, start=1):
        doc_name = chunk.get("doc_name") or chunk.get("document_id") or "Unknown document"
        page = chunk.get("page_number")
        locator = f"{doc_name}, PDF page {page + 1}" if isinstance(page, int) else str(doc_name)
        context_parts.append(
            f"--- Context Section {index} ---\n"
            f"[Source {index}] {locator}\n"
            f"Content:\n{chunk.get('text', '')}"
        )
    user_message = (
        "Use the following evidence sections to answer the question. Cite each claim "
        "with the matching [Source N] marker.\n\n"
        + "\n\n".join(context_parts)
        + f"\n\nQuestion: {question}\n"
        + "If a required fact is absent, use the exact insufficient-evidence response from the system instructions."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def render_messages(messages: Sequence[Mapping[str, str]]) -> str:
    """Return deterministic text for token estimates and prompt fingerprints."""
    return "\n".join(f"{item['role']}: {item['content']}" for item in messages)


def estimate_prompt_tokens(messages: Sequence[Mapping[str, str]]) -> int:
    """Estimate prompt size using the repository's pinned cl100k tokenizer."""
    return len(_ENCODING.encode(render_messages(messages)))


def estimate_max_cost_usd(
    *,
    prompt_tokens: int,
    max_output_tokens: int,
    cached_prompt_tokens: int = 0,
) -> Decimal:
    """Estimate a conservative cost for the pinned GPT-OSS 120B tariff."""
    input_tokens = max(0, prompt_tokens)
    cached_tokens = min(input_tokens, max(0, cached_prompt_tokens))
    uncached_tokens = input_tokens - cached_tokens
    uncached_upper_bound = ceil(
        uncached_tokens * (1 + GENERATOR_PROMPT_TOKEN_ESTIMATE_MARGIN)
    )
    input_cost = (
        Decimal(uncached_upper_bound) * GENERATOR_INPUT_USD_PER_MILLION
        + Decimal(cached_tokens) * GENERATOR_CACHED_INPUT_USD_PER_MILLION
    ) / _SCALE
    output_cost = Decimal(max(0, max_output_tokens)) * GENERATOR_OUTPUT_USD_PER_MILLION / _SCALE
    return input_cost + output_cost


def estimate_prompt_tokens_with_margin(prompt_tokens: int) -> int:
    """Return the frozen conservative token estimate used by the cost guard."""
    if prompt_tokens < 0:
        raise ValueError("prompt_tokens must be non-negative")
    return ceil(prompt_tokens * (1 + GENERATOR_PROMPT_TOKEN_ESTIMATE_MARGIN))


def _usage_cost(
    model_id: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cached_prompt_tokens: int,
) -> Decimal | None:
    if model_id != GENERATOR_MODEL_ID or prompt_tokens is None or completion_tokens is None:
        return None
    input_tokens = max(0, prompt_tokens)
    cached = min(input_tokens, max(0, cached_prompt_tokens))
    uncached = input_tokens - cached
    return (
        Decimal(uncached) * GENERATOR_INPUT_USD_PER_MILLION
        + Decimal(cached) * GENERATOR_CACHED_INPUT_USD_PER_MILLION
        + Decimal(completion_tokens) * GENERATOR_OUTPUT_USD_PER_MILLION
    ) / _SCALE


class GroqAnswerGenerator:
    """Synchronous Groq adapter with one visible request and usage accounting.

    The caller must provide the API key. The P5 CLI adds an explicit provider
    opt-in and budget gate; this class never reads ``.env`` or retries calls.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model_id: str = GENERATOR_MODEL_ID,
        max_output_tokens: int = GENERATOR_MAX_OUTPUT_TOKENS,
        client: Any | None = None,
        timeout_seconds: float | None = None,
    ):
        if not api_key:
            raise ValueError("A Groq API key must be supplied explicitly")
        if not 1 <= max_output_tokens <= GENERATOR_MAX_OUTPUT_TOKENS:
            raise ValueError(f"max_output_tokens must be between 1 and {GENERATOR_MAX_OUTPUT_TOKENS}")
        if timeout_seconds is not None and (not isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("Provider timeout must be positive and finite")
        self.model_id = model_id
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        if client is None:
            from groq import Groq

            options = {} if timeout_seconds is None else {"timeout": timeout_seconds}
            client = Groq(api_key=api_key, max_retries=0, **options)
        self.client = client

    def estimate(self, question: str, evidence_chunks: Sequence[Mapping[str, Any]]) -> tuple[int, Decimal]:
        messages = build_generation_messages(question, evidence_chunks)
        prompt_tokens = estimate_prompt_tokens(messages)
        if prompt_tokens > GENERATOR_MAX_INPUT_TOKENS:
            raise ValueError(
                f"Prompt exceeds the frozen input bound ({prompt_tokens} > {GENERATOR_MAX_INPUT_TOKENS})"
            )
        return prompt_tokens, estimate_max_cost_usd(
            prompt_tokens=prompt_tokens,
            max_output_tokens=self.max_output_tokens,
        )

    def generate(
        self,
        question: str,
        evidence_chunks: Sequence[Mapping[str, Any]],
    ) -> AnswerGenerationResult:
        if not evidence_chunks:
            return AnswerGenerationResult(
                answer="I could not find sufficient information in the available documents to answer this question with confidence.",
                model_id=self.model_id,
                latency_ms=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                estimated_cost_usd=Decimal(0),
            )
        messages = build_generation_messages(question, evidence_chunks)
        prompt_tokens_estimate = estimate_prompt_tokens(messages)
        if prompt_tokens_estimate > GENERATOR_MAX_INPUT_TOKENS:
            raise ValueError(
                f"Prompt exceeds the frozen input bound ({prompt_tokens_estimate} > {GENERATOR_MAX_INPUT_TOKENS})"
            )
        started = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            max_tokens=self.max_output_tokens,
            temperature=GENERATOR_TEMPERATURE,
        )
        latency_ms = max(0.0, (time.perf_counter() - started) * 1000)
        choice = response.choices[0]
        answer = getattr(choice.message, "content", None) or ""
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage is not None else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage is not None else None
        details = getattr(usage, "prompt_tokens_details", None) if usage is not None else None
        cached_prompt_tokens = getattr(details, "cached_tokens", 0) if details is not None else 0
        if not isinstance(prompt_tokens, int) or isinstance(prompt_tokens, bool):
            prompt_tokens = None
        if not isinstance(completion_tokens, int) or isinstance(completion_tokens, bool):
            completion_tokens = None
        if not isinstance(cached_prompt_tokens, int) or isinstance(cached_prompt_tokens, bool):
            cached_prompt_tokens = 0
        return AnswerGenerationResult(
            answer=answer,
            model_id=self.model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_prompt_tokens=cached_prompt_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=_usage_cost(
                self.model_id,
                prompt_tokens,
                completion_tokens,
                cached_prompt_tokens,
            ),
            provider_request_id=getattr(response, "id", None),
        )
