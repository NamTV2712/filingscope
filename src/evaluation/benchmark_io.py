"""Shared local reporting helpers without retrieval or model dependencies."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def peak_memory_bytes() -> int | None:
    if sys.platform == "win32":
        try:
            import psutil
        except ImportError:
            return None
        return psutil.Process().memory_info().peak_wset
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
