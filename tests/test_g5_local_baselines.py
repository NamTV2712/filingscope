"""Controls for budgeted prompts and scoring raw model drafts."""

import json

from configs.multi_agent_ablation import AblationCase, GoldClaim
from scripts import run_g5_local_baselines as baselines
from scripts.run_g5_groq_baselines import MODEL as GROQ_MODEL, OUTPUT_CAP, _request
from src.agent.complexity_router import ExecutionPath


class LocalFixture:
    def __init__(self, claims):
        self.claims = claims

    def input_tokens(self, messages):
        return len(messages[1]["content"].split())

    def post(self, route, payload):
        assert route == "/v1/chat/completions"
        return {
            "choices": [{"message": {"content": json.dumps({"claims": self.claims})}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": self.input_tokens(payload["messages"]), "completion_tokens": 20},
        }


def _case():
    claim = GoldClaim("USD 100 million", ("Apple", "revenue"), (("Apple#p2",),), ("FY2025",))
    return AblationCase("a", "development", "lookup", "What was Apple's FY2025 revenue?", ExecutionPath.FAST, (claim,))


def test_closed_book_scores_correctness_without_grounding():
    model = LocalFixture([{"statement": "Apple reported revenue of USD 100 million in FY2025", "source": None}])
    row = baselines._run_case(model, _case(), (), source_required=False)
    assert row["exact"] and not row["grounded_exact"]
    assert row["disposition"] == "RAW_MODEL_DRAFT"
    assert row["supplied_pages"] == {}


def test_long_context_keeps_statement_and_original_source_number(monkeypatch):
    monkeypatch.setattr(baselines, "INPUT_BUDGET", 35)
    pages = (baselines.Page("Apple#p1", "long " * 45, False, 1),
             baselines.Page("Apple#p2", "statement", True, 2))
    model = LocalFixture([{"statement": "Apple reported revenue of USD 100 million in FY2025", "source": 2}])
    row = baselines._run_case(model, _case(), pages, source_required=True)
    assert row["supplied_pages"] == {2: "Apple#p2"}
    assert row["truncated_pages"] == 1
    assert row["grounded_exact"]
    model.claims[0]["source"] = 1
    assert not baselines._run_case(model, _case(), pages, source_required=True)["grounded_exact"]


def test_invalid_model_output_counts_as_failure():
    model = LocalFixture([{"statement": "Apple reported USD 100 million [Source 1]", "source": None}])
    row = baselines._run_case(model, _case(), (), source_required=False)
    assert row["response_error"] == "invalid_json_or_claim"
    assert row["answered"] and not row["exact"] and not row["grounded_exact"]


def test_groq_request_uses_strict_claim_schema_and_bounded_reasoning():
    payload = _request([{"role": "user", "content": "A frozen question"}])
    assert payload["model"] == GROQ_MODEL == "openai/gpt-oss-120b"
    assert payload["max_completion_tokens"] == OUTPUT_CAP
    assert payload["reasoning_effort"] == "low" and payload["include_reasoning"] is False
    schema = payload["response_format"]["json_schema"]
    assert schema["strict"] and schema["schema"]["additionalProperties"] is False
    assert schema["schema"]["$defs"]["Claim"]["required"] == ["statement", "source"]
