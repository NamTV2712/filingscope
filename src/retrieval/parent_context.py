"""Expand retrieved PDF chunks to bounded source-page context."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from src.ingestion.chunker import count_tokens


PageKey = tuple[str, int]
ContextMode = Literal["children", "parents", "selective"]


@dataclass(frozen=True)
class PageParent:
    document: str
    page: int
    text: str
    chunk_ids: tuple[str, ...]
    token_count: int


@dataclass(frozen=True)
class RetrievedContext:
    document: str
    page: int
    source_url: str | None
    text: str
    chunk_ids: tuple[str, ...]
    token_count: int
    expanded: bool


def page_key(chunk: Mapping[str, Any]) -> PageKey:
    return chunk["doc_name"], chunk["page_number"]


def expand_contexts(
    ranked: Sequence[Mapping[str, Any]],
    parents: Mapping[PageKey, PageParent],
    *,
    mode: ContextMode,
    max_contexts: int = 10,
    token_budget: int = 4500,
) -> tuple[RetrievedContext, ...]:
    """Select context in child rank order using only observed source IDs."""
    if mode not in {"children", "parents", "selective"} or max_contexts < 1 or token_budget < 1:
        raise ValueError("Invalid context expansion limits")
    top = ranked[:max_contexts]
    repeated_pages = Counter(page_key(chunk) for chunk in top)
    selected = ranked if mode == "parents" else top
    contexts: list[RetrievedContext] = []
    included: set[str] = set()
    visited_parents: set[PageKey] = set()
    for chunk in selected:
        if len(contexts) >= max_contexts:
            break
        key = page_key(chunk)
        chunk_id = chunk["chunk_id"]
        if chunk_id in included or (mode == "parents" and key in visited_parents):
            continue
        parent = parents.get(key) if mode == "parents" or (mode == "selective" and repeated_pages[key] >= 2) else None
        if parent is not None and (
            key != (parent.document, parent.page) or chunk_id not in parent.chunk_ids
        ):
            raise ValueError(f"Parent context does not contain its ranked child: {chunk_id}")
        if parent is not None and parent.token_count <= token_budget:
            text, chunk_ids, tokens = parent.text, parent.chunk_ids, parent.token_count
            expanded = True
        else:
            text, chunk_ids = chunk["text"], (chunk_id,)
            tokens = chunk.get("token_count") or count_tokens(text)
            expanded = False
        if tokens > token_budget:
            continue
        contexts.append(RetrievedContext(*key, chunk.get("source_url"), text, chunk_ids, tokens, expanded))
        included.update(chunk_ids)
        visited_parents.add(key)
        token_budget -= tokens
    return tuple(contexts)
