from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.generation.answer_generator import (
    GroqAnswerGenerator,
    build_generation_messages,
    estimate_max_cost_usd,
    estimate_prompt_tokens_with_margin,
)


class FakeGroqClient:
    def __init__(self):
        self.calls = []

    class _Completions:
        def __init__(self, parent):
            self.parent = parent

        def create(self, **kwargs):
            self.parent.calls.append(kwargs)
            return SimpleNamespace(
                id="request-test",
                choices=[SimpleNamespace(message=SimpleNamespace(content="Revenue was $100 million [Source 1]."))],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=5,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=2),
                ),
            )

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))


def test_prompt_numbers_sources_by_retrieval_order() -> None:
    messages = build_generation_messages(
        "What was revenue?",
        [
            {"doc_name": "report.pdf", "page_number": 3, "text": "First evidence."},
            {"doc_name": "report.pdf", "page_number": 7, "text": "Second evidence."},
        ],
    )

    assert "[Source 1] report.pdf, PDF page 4" in messages[1]["content"]
    assert "[Source 2] report.pdf, PDF page 8" in messages[1]["content"]
    assert "Use only information explicitly stated" in messages[0]["content"]


def test_groq_adapter_uses_one_bounded_request_and_records_usage() -> None:
    client = FakeGroqClient()
    generator = GroqAnswerGenerator(api_key="unit-test-key", client=client)

    result = generator.generate(
        "What was revenue?",
        [{"doc_name": "report.pdf", "page_number": 3, "text": "Revenue was $100 million."}],
    )

    assert len(client.calls) == 1
    assert client.calls[0]["temperature"] == 0
    assert client.calls[0]["max_tokens"] == 1024
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.cached_prompt_tokens == 2
    assert result.provider_request_id == "request-test"
    assert result.estimated_cost_usd == Decimal("0.00000435")


def test_groq_adapter_requires_explicit_api_key() -> None:
    with pytest.raises(ValueError, match="supplied explicitly"):
        GroqAnswerGenerator(api_key="")


def test_preflight_token_and_cost_estimates_include_the_frozen_margin() -> None:
    assert estimate_prompt_tokens_with_margin(100) == 125
    assert estimate_max_cost_usd(prompt_tokens=100, max_output_tokens=100) == Decimal("0.00007875")
