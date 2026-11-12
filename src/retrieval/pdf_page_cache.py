"""Bounded random access to physical pages from a frozen PDF extraction."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path


class FrozenPdfPages:
    def __init__(self, path: Path, *, expected_sha256: str):
        self.path = path
        self._locations: dict[tuple[str, int], tuple[int, int, bytes]] = {}
        sha256 = hashlib.sha256()
        offset = 0
        with path.open("rb") as stream:
            for line in stream:
                sha256.update(line)
                row = json.loads(line)
                key = row["doc_name"], row["page_number"]
                if key in self._locations:
                    raise ValueError(f"Duplicate extracted physical page: {key}")
                self._locations[key] = offset, len(line), hashlib.sha256(line).digest()
                offset += len(line)
        if f"sha256:{sha256.hexdigest()}" != expected_sha256:
            raise ValueError("PDF page cache differs from the pinned extraction")
        self._cached_read = lru_cache(maxsize=64)(self._read_page)

    @classmethod
    def from_run(cls, path: Path, run_directory: Path) -> FrozenPdfPages:
        manifest = json.loads((run_directory / "run_manifest.json").read_text(encoding="utf-8"))
        return cls(path, expected_sha256=manifest["extracted_page_cache_sha256"])

    def get(self, document: str, page_number: int) -> str | None:
        key = document, page_number
        return self._cached_read(key) if key in self._locations else None

    def _read_page(self, key: tuple[str, int]) -> str:
        offset, length, expected = self._locations[key]
        with self.path.open("rb") as stream:
            stream.seek(offset)
            line = stream.read(length)
        if hashlib.sha256(line).digest() != expected:
            raise ValueError("Extracted page changed after index validation")
        return json.loads(line)["text"]
