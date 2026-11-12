"""Local filing-graph ranking experiments over an existing candidate pool."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.decision.company_catalog import CompanyCatalog


_FISCAL_YEAR = re.compile(r"\bFY\s*((?:19|20)\d{2})\b", re.I)
_FILING_YEAR = re.compile(r"\b(?:FY\s*)?((?:19|20)\d{2})\s+(?:10\s*[-–]?\s*[KQ]|annual report)\b", re.I)
_FORMS = {
    "10k": re.compile(r"\b(?:10\s*[-–]?\s*k|annual report|audited)\b", re.I),
    "10q": re.compile(r"\b(?:10\s*[-–]?\s*q|quarterly report)\b", re.I),
    "earnings": re.compile(r"\b(?:earnings release|earnings report)\b", re.I),
}
_TOPICS = {
    "revenue": re.compile(r"\b(?:revenues?|net sales)\b", re.I),
    "cash_balance": re.compile(r"\bcash and cash equivalents\b", re.I),
    "assets": re.compile(r"\btotal (?:current )?assets\b", re.I),
    "profit": re.compile(r"\b(?:operating income|operating profit|net income|net earnings)\b", re.I),
    "ebitda": re.compile(r"\bebitda[r]?\b", re.I),
    "cash_flow": re.compile(r"\b(?:investing activities|cash flows?|financing activities|operating activities)\b", re.I),
    "revision": re.compile(r"\b(?:recast|original(?:ly)?|reorganiz(?:ed|ation)|restated)\b", re.I),
}
_DISCLOSURES = {
    "balance": re.compile(r"\b(?:balance sheets?|statements? of financial position)\b", re.I),
    "income": re.compile(r"\b(?:statements? of (?:income|operations|earnings)|income statements?)\b", re.I),
    "cash_flow": re.compile(r"\bstatements? of cash flows?\b", re.I),
    "segment": re.compile(r"\b(?:business segments?|segment reporting|segment reorganization|reportable segments?)\b", re.I),
    "liquidity": re.compile(r"\bliquidity and capital resources\b", re.I),
}


@dataclass(frozen=True)
class FilingUnit:
    company: str | None
    filing: str
    page: int
    form: str
    years: tuple[str, ...]
    topics: tuple[str, ...]
    disclosures: tuple[str, ...]


@dataclass(frozen=True)
class GraphQuery:
    companies: frozenset[str]
    years: frozenset[str]
    forms: frozenset[str]
    topics: frozenset[str]
    disclosures: frozenset[str]


def _matches(text: str, patterns: Mapping[str, re.Pattern]) -> tuple[str, ...]:
    return tuple(label for label, pattern in patterns.items() if pattern.search(text))


class FilingPassageGraph:
    """Project filing metadata and text-unit cues into deterministic links."""

    def __init__(self, chunks: Sequence[Mapping[str, Any]]):
        self.catalog = CompanyCatalog.from_document_rows(chunks)
        self.units = []
        self.filings_by_company = defaultdict(set)
        self.units_by_filing = defaultdict(set)
        self.units_by_relationship = defaultdict(set)
        for position, chunk in enumerate(chunks):
            company = self.catalog.metadata_entity_id(chunk.get("ticker"), chunk.get("company"), chunk.get("doc_name"))
            text = chunk["text"]
            unit = FilingUnit(
                company=company, filing=chunk["document_id"], page=chunk["page_number"],
                form=chunk["doc_type"].casefold().replace("-", ""), years=tuple(chunk["reporting_periods"]),
                topics=_matches(text, _TOPICS), disclosures=_matches(text[:400], _DISCLOSURES),
            )
            self.units.append(unit)
            if company:
                self.filings_by_company[company].add(unit.filing)
            self.units_by_filing[unit.filing].add(position)
            for topic in unit.topics:
                self.units_by_relationship[company, topic].add(position)

    def cues(self, question: str) -> GraphQuery:
        return GraphQuery(
            companies=frozenset(item.entity_id for item in self.catalog.identify(question)),
            years=frozenset(_FILING_YEAR.findall(question) or _FISCAL_YEAR.findall(question)),
            forms=frozenset(_matches(question, _FORMS)), topics=frozenset(_matches(question, _TOPICS)),
            disclosures=frozenset(_matches(question, _DISCLOSURES)),
        )

    def _entity_units(self, query: GraphQuery, pool: Sequence[int]) -> set[int]:
        filings = {filing for company in query.companies for filing in self.filings_by_company.get(company, ())}
        return {item for item in pool if self.units[item].filing in filings}

    def local_search(self, query: GraphQuery, pool: Sequence[int]) -> dict[int, float]:
        """Rank text units reached through company and filing links."""
        local = self._entity_units(query, pool)
        return {
            item: (
                1 / (1 + rank)
                + 0.35 * (item in local)
                + 0.20 * bool(query.years.intersection(unit.years))
                + 0.12 * (unit.form in query.forms)
                + 0.12 * bool(query.disclosures.intersection(unit.disclosures))
                + 0.10 * bool(query.topics.intersection(unit.topics))
            )
            for rank, item in enumerate(pool) for unit in (self.units[item],)
        }

    def personalized_pagerank(self, query: GraphQuery, pool: Sequence[int]) -> dict[int, float]:
        """Diffuse query and dense seeds through the candidate evidence graph."""
        adjacency: dict[tuple, set[tuple]] = defaultdict(set)
        for item in pool:
            unit = self.units[item]
            passage = ("passage", item)
            neighbors = [
                ("filing", unit.filing), ("page", unit.filing, unit.page), ("form", unit.form),
                *(("year", value) for value in unit.years),
                *(("topic", value) for value in unit.topics),
                *(("disclosure", value) for value in unit.disclosures),
            ]
            if unit.company:
                neighbors.append(("company", unit.company))
            for other in neighbors:
                adjacency[passage].add(other)
                adjacency[other].add(passage)
        indexes = {node: index for index, node in enumerate(adjacency)}
        origins, targets, weights = [], [], []
        for node, neighbors in adjacency.items():
            for neighbor in sorted(neighbors, key=indexes.__getitem__):
                origins.append(indexes[node])
                targets.append(indexes[neighbor])
                weights.append(1 / len(neighbors))
        origin_index = np.asarray(origins, dtype=np.intp)
        target_index = np.asarray(targets, dtype=np.intp)
        edge_weights = np.asarray(weights)
        restart = np.zeros(len(indexes))
        for rank, item in enumerate(pool):
            restart[indexes["passage", item]] = 1 / (rank + 1)
        restart /= restart.sum()
        for label, values in (
            ("company", query.companies), ("year", query.years), ("form", query.forms),
            ("topic", query.topics), ("disclosure", query.disclosures),
        ):
            positions = [indexes[label, value] for value in sorted(values) if (label, value) in indexes]
            if positions:
                restart[positions] += 0.2 / len(positions)
        restart /= restart.sum()
        scores = restart.copy()
        for _ in range(20):
            incoming = np.bincount(target_index, weights=edge_weights * scores[origin_index], minlength=len(indexes))
            scores = 0.15 * restart + 0.85 * incoming
        return {item: float(scores[indexes["passage", item]]) for item in pool}

    def dual_level(self, query: GraphQuery, pool: Sequence[int]) -> dict[int, float]:
        """Fuse issuer-local and issuer-topic relationship text-unit rankings."""
        local = self._entity_units(query, pool)
        global_units = {item for company in query.companies for topic in query.topics
                        for item in self.units_by_relationship.get((company, topic), ())}
        dense_rank = {item: rank for rank, item in enumerate(pool)}
        local_ranked = sorted(local, key=lambda item: (
            -len(query.years.intersection(self.units[item].years)),
            -int(self.units[item].form in query.forms), dense_rank[item],
        ))
        related_ranked = sorted(global_units.intersection(pool), key=lambda item: (
            -len(query.disclosures.intersection(self.units[item].disclosures)),
            -len(query.topics.intersection(self.units[item].topics)), dense_rank[item],
        ))
        scores = {item: 1 / (20 + rank) for rank, item in enumerate(pool)}
        for ranking in (local_ranked, related_ranked):
            for rank, item in enumerate(ranking):
                scores[item] += 1 / (20 + rank)
        return scores
