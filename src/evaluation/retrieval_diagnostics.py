"""Pure ranking helpers for stage-level retrieval experiments."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence

from src.decision.company_catalog import CompanyCatalog
from src.retrieval.query_shaper import shape_retrieval_query

from src.retrieval.hybrid_retriever import RRF_K, CE_RELATIVE_CUTOFF

_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_FORM_PATTERNS = (
    ("10k", re.compile(r"\b(?:10\s*[-–]?\s*k|annual report)\b", re.I)),
    ("10q", re.compile(r"\b(?:10\s*[-–]?\s*q|quarterly report)\b", re.I)),
    ("8k", re.compile(r"\b(?:8\s*[-–]?\s*k|current report)\b", re.I)),
    ("earnings", re.compile(r"\bearnings (?:release|report|call)\b", re.I)),
)
_FILTER_PROFILES = {
    "company": ("company",),
    "period": ("reporting_periods",),
    "form": ("doc_type",),
    "company_period": ("company", "reporting_periods"),
    "company_period_form": ("company", "reporting_periods", "doc_type"),
}


def ranked_ids_from_trace(trace: Mapping[str, object], rank_key: str) -> list[str]:
    """Extract a stable ordered ID list from a HybridRetriever inspection trace."""
    candidates = trace.get("candidates", ())
    if not isinstance(candidates, Sequence):
        return []
    ranked = [
        (int(candidate[rank_key]), str(candidate["chunk_id"]))
        for candidate in candidates
        if isinstance(candidate, Mapping)
        and isinstance(candidate.get(rank_key), int)
        and isinstance(candidate.get("chunk_id"), str)
    ]
    return [chunk_id for _, chunk_id in sorted(ranked)]


def route_aware_fusion_weights(query: str) -> tuple[str, dict[str, float]]:
    """Select a fixed fusion profile from runtime query-shaping observations.

    Filing-native phrase hints identify queries where the existing lexical
    ladder has an explicit phrase to protect. Other queries use the
    dense-priority profile, which matches the current weighted-RRF experiment.
    """
    shaped = shape_retrieval_query(query)
    if shaped.exact_phrases:
        return "filing_native_phrase", {"bm25": 1.0, "dense": 1.0, "lexical": 2.0}
    return "dense_priority", {"bm25": 1.0, "dense": 2.0, "lexical": 0.5}


def metadata_filters_from_question(
    question: str,
    *,
    company_catalog: CompanyCatalog,
    company_values_by_entity: Mapping[str, Collection[str]],
    available_periods: Collection[str],
    available_doc_types: Collection[str],
) -> dict[str, tuple[str, ...]]:
    """Derive only exact metadata values explicitly recoverable from a query.

    The caller supplies values from the runtime corpus map. Gold benchmark
    company, period, form, and evidence annotations are not consulted.
    """
    filters: dict[str, tuple[str, ...]] = {}
    entity_ids = {match.entity_id for match in company_catalog.identify(question)}
    companies = tuple(sorted({
        company
        for entity_id in entity_ids
        for company in company_values_by_entity.get(entity_id, ())
    }))
    if companies:
        filters["company"] = companies

    observed_periods = set(available_periods)
    periods = tuple(sorted({
        year for year in _YEAR_RE.findall(question) if year in observed_periods
    }))
    if periods:
        filters["reporting_periods"] = periods

    doc_types_by_key = {value.casefold(): value for value in available_doc_types}
    requested_doc_types = {
        doc_type
        for doc_type, pattern in _FORM_PATTERNS
        if pattern.search(question)
    }
    doc_types = tuple(sorted(
        doc_types_by_key[doc_type]
        for doc_type in requested_doc_types
        if doc_type in doc_types_by_key
    ))
    if doc_types:
        filters["doc_type"] = doc_types
    return filters


def metadata_filter_profiles(
    filters: Mapping[str, Sequence[str]],
) -> dict[str, dict[str, Sequence[str]]]:
    """Return the single-field and explicitly supported joint filter profiles."""
    return {
        profile: {field: filters[field] for field in fields}
        for profile, fields in _FILTER_PROFILES.items()
        if all(field in filters for field in fields)
    }


def fuse_ranked_ids(
    *,
    bm25_ids: Sequence[str],
    dense_ids: Sequence[str],
    lexical_ids: Sequence[str],
    bm25_candidates: int,
    dense_candidates: int,
    lexical_candidates: int,
    fusion_candidates: int,
    weights: Mapping[str, float] | None = None,
    dense_preserving: bool = False,
) -> tuple[list[str], dict[str, float]]:
    """Fuse ranked sources, optionally reserving dense candidates in the pool.

    The dense-preserving mode reserves the configured dense prefix in the
    candidate pool, then fills the remaining slots by weighted RRF. The output
    order within that candidate set remains RRF-scored.
    """
    limits = (bm25_candidates, dense_candidates, lexical_candidates, fusion_candidates)
    if any(limit < 0 for limit in limits) or fusion_candidates < 1:
        raise ValueError("candidate limits must be non-negative and fusion_candidates positive")
    source_lists = {
        "bm25": list(bm25_ids[:bm25_candidates]),
        "dense": list(dense_ids[:dense_candidates]),
        "lexical": list(lexical_ids[:lexical_candidates]),
    }
    source_weights = {"bm25": 1.0, "dense": 1.0, "lexical": 1.0}
    if weights is not None:
        unknown = set(weights) - set(source_weights)
        if unknown:
            raise ValueError(f"unknown fusion weight source(s): {', '.join(sorted(unknown))}")
        for source, weight in weights.items():
            if weight < 0:
                raise ValueError("fusion weights must be non-negative")
            source_weights[source] = float(weight)

    scores: dict[str, float] = {}
    for source, ids in source_lists.items():
        weight = source_weights[source]
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (RRF_K + rank)
    ordered = sorted(scores, key=scores.get, reverse=True)
    if not dense_preserving:
        return ordered[:fusion_candidates], scores

    reserved = source_lists["dense"][:fusion_candidates]
    reserved_set = set(reserved)
    selected = list(reserved)
    for chunk_id in ordered:
        if len(selected) >= fusion_candidates:
            break
        if chunk_id not in reserved_set:
            selected.append(chunk_id)
            reserved_set.add(chunk_id)
    selected.sort(key=scores.get, reverse=True)
    return selected, scores


def rerank_candidate_ids(
    candidate_ids: Sequence[str],
    cross_encoder_scores: Mapping[str, float],
    *,
    top_k: int,
    relative_cutoff: float = CE_RELATIVE_CUTOFF,
) -> list[str]:
    """Apply the production rerank cutoff and top-k to pre-scored candidates."""
    if top_k < 1:
        raise ValueError("top_k must be positive")
    ranked = [
        (chunk_id, float(cross_encoder_scores[chunk_id]))
        for chunk_id in candidate_ids
        if chunk_id in cross_encoder_scores
    ]
    ranked.sort(key=lambda item: item[1], reverse=True)
    if ranked and ranked[0][1] > 0:
        cutoff = ranked[0][1] * relative_cutoff
        ranked = [(chunk_id, score) for chunk_id, score in ranked if score >= cutoff]
    return [chunk_id for chunk_id, _ in ranked[:top_k]]
