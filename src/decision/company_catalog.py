"""Company aliases reused and extended from the source repository catalog."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


# Reused from Enterprise_Document_QA/src/company_entities.py at
# 2ac043347f57e257dac4e2947a57dfced8709d97, then extended by corpus metadata.
DEFAULT_COMPANY_ALIASES: dict[str, tuple[str, ...]] = {
    "AAPL": ("apple", "aapl"),
    "MSFT": ("microsoft", "msft"),
    "AMZN": ("amazon", "amzn"),
    "GOOGL": ("alphabet", "google", "googl"),
    "META": ("meta", "facebook"),
    "NVDA": ("nvidia", "nvda"),
    "TSLA": ("tesla", "tsla"),
    "MS": ("morgan stanley",),
    "MCD": ("mcdonald's", "mcdonalds"),
    "INTC": ("intel", "intc"),
    "COST": ("costco",),
    "GE": ("general electric", "ge aerospace"),
    "HON": ("honeywell", "hon"),
}

_LEGAL_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company",
    "limited", "ltd", "plc", "llc", "lp", "holdings", "group",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize_entity(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.casefold()))


def _base_company_alias(value: str) -> str:
    tokens = normalize_entity(value).split()
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


@dataclass(frozen=True)
class CompanyMatch:
    entity_id: str
    canonical_name: str
    matched_alias: str


class CompanyCatalog:
    """Resolve query mentions against a caller-supplied document catalog."""

    def __init__(self, aliases: Mapping[str, Iterable[str]] | None = None):
        source = aliases or DEFAULT_COMPANY_ALIASES
        normalized: dict[str, tuple[str, ...]] = {}
        names: dict[str, str] = {}
        alias_owners: dict[str, set[str]] = defaultdict(set)
        for raw_entity_id, raw_aliases in source.items():
            entity_id = str(raw_entity_id).strip()
            if not entity_id:
                continue
            raw_alias_list = [str(alias).strip() for alias in raw_aliases if alias]
            candidates = {entity_id, *raw_alias_list}
            expanded = set(candidates)
            for alias in tuple(candidates):
                base = _base_company_alias(alias)
                if base:
                    expanded.add(base)
            clean_aliases = tuple(
                sorted(
                    {alias.strip() for alias in expanded if normalize_entity(alias)},
                    key=lambda alias: (-len(normalize_entity(alias)), alias.casefold()),
                )
            )
            normalized[entity_id] = clean_aliases
            names[entity_id] = next(
                iter(sorted(raw_alias_list, key=lambda alias: (-len(alias), alias.casefold()))),
                entity_id,
            )
            for alias in clean_aliases:
                alias_owners[normalize_entity(alias)].add(entity_id)
        self._aliases = normalized
        self._names = names
        self._alias_owners = dict(alias_owners)

    @classmethod
    def from_document_rows(
        cls,
        rows: Iterable[Mapping[str, object]],
        *,
        base: Mapping[str, Iterable[str]] | None = None,
    ) -> "CompanyCatalog":
        base_aliases = base or DEFAULT_COMPANY_ALIASES
        aliases: dict[str, set[str]] = {
            entity: set(values) for entity, values in base_aliases.items()
        }
        base_alias_to_ids: dict[str, set[str]] = defaultdict(set)
        for entity_id, values in base_aliases.items():
            for value in values:
                base_alias_to_ids[normalize_entity(_base_company_alias(value))].add(entity_id)
        for row in rows:
            company = row.get("company")
            ticker = row.get("ticker")
            if not isinstance(company, str) or not company.strip():
                continue
            company_key = normalize_entity(_base_company_alias(company))
            base_matches = base_alias_to_ids.get(company_key, set())
            entity_id = (
                ticker.strip().upper()
                if isinstance(ticker, str) and ticker.strip()
                else next(iter(base_matches))
                if len(base_matches) == 1
                else _base_company_alias(company).upper().replace(" ", "_")
            )
            aliases.setdefault(entity_id, set()).add(company.strip())
            base_alias = _base_company_alias(company)
            if base_alias:
                aliases[entity_id].add(base_alias)
            if isinstance(ticker, str) and ticker.strip():
                aliases[entity_id].add(ticker.strip())
        return cls(aliases)

    def identify(self, text: str) -> tuple[CompanyMatch, ...]:
        matches: dict[str, tuple[int, int, str]] = {}
        folded = text.casefold()
        for entity_id, aliases in self._aliases.items():
            for alias in aliases:
                is_short_ticker = (
                    alias == entity_id
                    and bool(re.fullmatch(r"[A-Z]{1,2}", entity_id))
                )
                pattern = re.compile(
                    rf"(?<![\w]){re.escape(alias)}(?![\w])",
                    0 if is_short_ticker else re.I,
                )
                found = pattern.search(text if is_short_ticker else folded)
                if found is None:
                    continue
                current = matches.get(entity_id)
                candidate = (found.start(), -len(alias), alias)
                if current is None or candidate < current:
                    matches[entity_id] = candidate
        ordered = sorted(matches.items(), key=lambda item: (item[1][0], item[0]))
        result = []
        for entity_id, (_, _, alias) in ordered:
            owners = self._alias_owners.get(normalize_entity(alias), set())
            if len(owners) > 1:
                continue
            result.append(
                CompanyMatch(
                    entity_id=entity_id,
                    canonical_name=self._names[entity_id],
                    matched_alias=alias,
                )
            )
        return tuple(result)

    def metadata_entity_id(self, *values: object) -> str | None:
        for raw in values:
            if not isinstance(raw, str) or not raw.strip():
                continue
            normalized = normalize_entity(raw)
            exact = [
                entity_id
                for entity_id, aliases in self._aliases.items()
                if any(normalize_entity(alias) == normalized for alias in aliases)
            ]
            if len(exact) == 1:
                return exact[0]
            # SEC document IDs commonly begin with their ticker.
            prefix = normalized.split()[0].upper() if normalized else ""
            if prefix in self._aliases:
                return prefix
        return None

    def aliases_for(self, entity_id: str) -> tuple[str, ...]:
        return self._aliases.get(entity_id, ())
