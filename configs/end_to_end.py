"""Frozen P5 end-to-end benchmark settings and Groq price snapshot."""

from decimal import Decimal

from src.agent.adaptive_retrieval import AdaptiveRetrievalBudget

BENCHMARK_ID = "financebench-e2e-v1"
PROMPT_VERSION = "financial-evidence-grounded-v2"
GENERATOR_MODEL_ID = "openai/gpt-oss-120b"
GENERATOR_TEMPERATURE = 0
GENERATOR_MAX_OUTPUT_TOKENS = 1024
GENERATOR_MAX_INPUT_TOKENS = 20_000
GENERATOR_PROMPT_TOKEN_ESTIMATE_MARGIN = Decimal("0.25")
RETRIEVAL_TOP_K = 10
RETRIEVAL_CANDIDATE_POOL = 50

ADAPTIVE_RETRIEVAL_BUDGET = AdaptiveRetrievalBudget(
    max_rounds=3,
    max_queries=6,
    max_evidence_tokens=16_000,
    time_budget_seconds=30,
    top_k=5,
)

# Groq's public standard on-demand rates for GPT-OSS 120B, checked 2026-11-07.
# These are estimates from reported token counts, not provider invoices.
GENERATOR_PRICE_CHECKED_AT = "2026-11-07"
GENERATOR_INPUT_USD_PER_MILLION = Decimal("0.15")
GENERATOR_CACHED_INPUT_USD_PER_MILLION = Decimal("0.075")
GENERATOR_OUTPUT_USD_PER_MILLION = Decimal("0.60")
