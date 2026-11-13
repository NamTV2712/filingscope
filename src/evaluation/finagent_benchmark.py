"""Normalize the pinned public FinAgent evaluation release."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.retrieval.canonical_json import sha256_file

FINAGENT_REVISION = "b048668cdd21bf8e7f9a6fec4b770ec44bdb8440"
FINAGENT_SHA256 = "sha256:d3488d49c31b7e71ea90f3faefe7810e68b8a06fce9f518239cf7945820a7cd3"


@dataclass(frozen=True)
class FinAgentCase:
    case_id: str
    question: str
    category: str
    tickers: tuple[str, ...]
    forms: tuple[str, ...]
    evidence: str


def load_finagent(path: Path) -> list[FinAgentCase]:
    if sha256_file(path) != FINAGENT_SHA256:
        raise ValueError("FinAgent v1.1.1 checksum mismatch")
    rows = json.loads(path.read_bytes())
    cases = [
        FinAgentCase(row["id"], row["question"], row["type"], tuple(row["source_companies"]),
                     tuple(row["source_filing_types"]), row["gold_evidence"])
        for row in rows
    ]
    if len(cases) != 133 or len({case.case_id for case in cases}) != 133:
        raise ValueError("Unexpected FinAgent release membership")
    return cases
