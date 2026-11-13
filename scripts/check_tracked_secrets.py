"""Fail on common credential material and private artifact paths in tracked files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath


_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
    "GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "Groq token": re.compile(rb"\bgsk_[A-Za-z0-9]{25,}\b"),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "literal credential setting": re.compile(
        rb"^\s*(?:export\s+)?(?:GROQ_API_KEY|QDRANT_CLOUD_API_KEY|AWS_SECRET_ACCESS_KEY|HF_TOKEN|GITHUB_TOKEN)\s*=\s*"
        rb"[\"']?[A-Za-z0-9_+/=.\-]{12,}[\"']?\s*$",
    ),
}
_PRIVATE_ROOTS = {"data", "models", ".local", ".venv", ".huggingface", ".cache-huggingface"}
_PRIVATE_SUFFIXES = {".safetensors", ".onnx", ".pt", ".pth", ".sqlite3", ".log", ".p12", ".pfx"}


def findings(path: str, content: bytes) -> list[tuple[int, str]]:
    file = PurePosixPath(path)
    name = file.name.casefold()
    if (file.parts[0].casefold() in _PRIVATE_ROOTS or file.suffix.casefold() in _PRIVATE_SUFFIXES
            or (name == ".env" or name.startswith(".env.")) and name != ".env.example"):
        return [(1, "private artifact path")]
    return [(number, rule) for number, line in enumerate(content.splitlines(), 1)
            for rule, pattern in _PATTERNS.items() if pattern.search(line)]


def main() -> int:
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode("utf-8").split("\0")
    problems = 0
    for name in filter(None, names):
        path = root / name
        content = path.read_bytes() if path.is_file() and not path.is_symlink() else b""
        for line, rule in findings(name, content):
            print(f"{name}:{line}: {rule}")
            problems += 1
    print(f"Tracked-file scan found {problems} issue(s).")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
