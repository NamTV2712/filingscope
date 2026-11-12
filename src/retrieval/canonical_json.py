"""Shared deterministic JSON serialization used by fingerprint helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize to stable UTF-8 bytes for hashing (sorted keys, compact)."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return f"sha256:{hashlib.file_digest(handle, 'sha256').hexdigest()}"
