"""Pinned FinanceBench acquisition and retrieval evaluation settings."""

FINANCEBENCH_GITHUB_REPOSITORY = "patronus-ai/financebench"
FINANCEBENCH_GITHUB_REVISION = "cc39aeb4afdf33909ee1412188bf89035950c2eb"
FINANCEBENCH_HUGGINGFACE_REVISION = "e04404e3a97f69f79c14d42f24981a1c9c3bcd18"
FINANCEBENCH_LICENSE = "CC BY-NC 4.0"
FINANCEBENCH_LICENSE_URL = "https://creativecommons.org/licenses/by-nc/4.0/"
FINANCEBENCH_EXPECTED_CASES = 150
FINANCEBENCH_EXPECTED_DOCUMENTS = 84

SPLIT_SEED = "filingscope-financebench-company-split-v1"
SPLIT_TARGETS = {
    "development": 60,
    "validation": 45,
    "held_out": 45,
}

PDF_CHUNK_SIZE = 450
PDF_CHUNK_OVERLAP = 75
RETRIEVAL_TOP_K = 10
RETRIEVAL_CANDIDATE_POOL = 50
