"""The public set of request lifecycle events."""

from enum import StrEnum


class ResearchProgress(StrEnum):
    UNDERSTANDING_QUESTION = "understanding_question"
    IDENTIFYING_REQUIREMENTS = "identifying_requirements"
    SEARCHING_FILINGS = "searching_filings"
    SEARCHING_STRUCTURED_FACTS = "searching_structured_facts"
    INSPECTING_TABLES = "inspecting_tables"
    ADDITIONAL_RETRIEVAL = "additional_retrieval"
    CHECKING_COVERAGE = "checking_coverage"
    MISSING_EVIDENCE = "missing_evidence"
    CALCULATIONS_VERIFIED = "calculations_verified"
    CHECKING_CLAIMS = "checking_claims"
    CLAIM_CHECKS_COMPLETE = "claim_checks_complete"
    FINALIZING_ANSWER = "finalizing_answer"
