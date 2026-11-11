"""Compact, runtime-only summaries of the documents an index can retrieve."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.decision.company_catalog import CompanyCatalog

CORPUS_MAP_SCHEMA_VERSION = "1.0.0"
_TABLE_SECTION_MARKERS = {"table", "tables", "structured table", "structured tables"}
_FORM_CODE_RE = re.compile(r"\b(10|8)\s*[-–]?\s*([kq])(?:\s*/\s*a)?\b", re.I)


class SourceAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


class MetadataCoverage(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NOT_INDEXED = "NOT_INDEXED"
    UNKNOWN = "UNKNOWN"


class CorpusDocument(BaseModel):
    """One local document with retrieval metadata only; never stores chunk text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str = Field(min_length=1)
    company_names: tuple[str, ...] = ()
    company_entity_ids: tuple[str, ...] = ()
    tickers: tuple[str, ...] = ()
    ciks: tuple[str, ...] = ()
    form_types: tuple[str, ...] = ()
    filing_periods: tuple[str, ...] = ()
    sections: tuple[str, ...] = ()
    table_ids: tuple[str, ...] = ()
    chunk_count: int = Field(ge=1)
    metadata_conflicts: tuple[str, ...] = ()
    table_evidence: SourceAvailability = SourceAvailability.UNKNOWN
    xbrl_evidence: SourceAvailability = SourceAvailability.UNKNOWN


class CorpusMap(BaseModel):
    """Versioned metadata inventory passed to a research planner."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0.0"] = CORPUS_MAP_SCHEMA_VERSION
    index_generation_id: str | None = None
    collection_name: str | None = None
    documents: tuple[CorpusDocument, ...] = ()
    chunk_count: int = Field(ge=0)
    metadata_coverage: dict[str, MetadataCoverage] = Field(default_factory=dict)
    source_coverage: dict[str, SourceAvailability] = Field(default_factory=dict)

    @classmethod
    def from_chunks(
        cls,
        chunks: Iterable[Mapping[str, Any]],
        *,
        index_generation_id: str | None = None,
        collection_name: str | None = None,
        xbrl_coverage: SourceAvailability = SourceAvailability.UNKNOWN,
        table_coverage: SourceAvailability | None = None,
    ) -> "CorpusMap":
        """Aggregate chunk payload metadata while discarding all text and labels.

        `MISSING` means the source is absent from this indexed corpus. `UNKNOWN`
        means the index does not contain enough inventory metadata to establish
        absence. In particular, no XBRL inventory defaults to UNKNOWN.
        """
        grouped: dict[str, dict[str, Any]] = {}
        chunk_count = 0
        has_filing_text = False
        has_section_inventory = True
        has_table_marker = False
        explicit_xbrl_states: set[SourceAvailability] = set()

        for row in chunks:
            if not isinstance(row, Mapping):
                raise ValueError("corpus chunks must be metadata mappings")
            document_id = _first_text(row, "document_id", "doc_name", "filing_id")
            if not document_id:
                raise ValueError("every indexed chunk must have a document_id or doc_name")

            record = grouped.setdefault(document_id, {
                "company_names": set(),
                "tickers": set(),
                "ciks": set(),
                "form_types": set(),
                "filing_periods": set(),
                "sections": set(),
                "table_ids": set(),
                "conflicts": set(),
                "field_values": {
                    "company": set(),
                    "ticker": set(),
                    "cik": set(),
                    "form_type": set(),
                },
                "table_marked": False,
                "xbrl_states": set(),
                "chunk_count": 0,
            })
            chunk_count += 1
            chunk_text = row.get("text")
            has_filing_text = has_filing_text or (
                isinstance(chunk_text, str) and bool(chunk_text.strip())
            )
            record["chunk_count"] += 1

            companies = _values(row.get("company_names")) or _values(
                row.get("company") or row.get("company_name") or row.get("issuer")
            )
            tickers = _values(row.get("tickers")) or _values(row.get("ticker"))
            ciks = _values(row.get("ciks")) or _values(row.get("cik"))
            forms = _values(row.get("form_types")) or _values(
                row.get("form_type") or row.get("doc_type") or row.get("form")
            )
            forms = {_normalize_form_type(form) for form in forms}
            periods = (
                _values(row.get("filing_periods"))
                or _values(row.get("reporting_periods"))
                or _values(row.get("fiscal_period"))
                or _values(row.get("reporting_period"))
                or _values(row.get("report_date"))
            )
            sections = _values(row.get("sections")) or _values(row.get("section"))
            table_ids = _values(row.get("table_ids")) or _values(row.get("table_id"))

            for field, values in (
                ("company_names", companies),
                ("tickers", tickers),
                ("ciks", ciks),
                ("form_types", forms),
                ("filing_periods", periods),
                ("sections", sections),
                ("table_ids", table_ids),
            ):
                record[field].update(values)
            record["field_values"]["company"].update(companies)
            record["field_values"]["ticker"].update(tickers)
            record["field_values"]["cik"].update(ciks)
            record["field_values"]["form_type"].update(forms)

            if not sections:
                has_section_inventory = False
            table_marked = bool(table_ids) or any(
                section.casefold().strip() in _TABLE_SECTION_MARKERS for section in sections
            ) or _is_true(row.get("is_table")) or _is_true(row.get("has_table_evidence"))
            record["table_marked"] = record["table_marked"] or table_marked
            has_table_marker = has_table_marker or table_marked
            record["conflicts"].update(
                _normalize_conflict_fields(_conflict_fields(row.get("metadata_conflicts")))
            )

            for key in ("xbrl_evidence", "xbrl_coverage", "xbrl_status"):
                if key in row:
                    parsed = _availability(row.get(key))
                    if parsed is not None:
                        record["xbrl_states"].add(parsed)
                        explicit_xbrl_states.add(parsed)
            if "has_xbrl_facts" in row and isinstance(row["has_xbrl_facts"], bool):
                state = (
                    SourceAvailability.AVAILABLE
                    if row["has_xbrl_facts"]
                    else SourceAvailability.MISSING
                )
                record["xbrl_states"].add(state)
                explicit_xbrl_states.add(state)

        company_catalog = CompanyCatalog.from_document_rows(
            [
                {"company": company, "ticker": ticker}
                for record in grouped.values()
                for company in record["company_names"]
                for ticker in (tuple(record["tickers"]) or (None,))
            ]
        )
        documents: list[CorpusDocument] = []
        for document_id, record in sorted(grouped.items()):
            conflicts = set(record["conflicts"])
            for field, values in record["field_values"].items():
                if len(values) > 1:
                    conflicts.add(field)
            company_ids = {
                entity_id
                for company in record["company_names"]
                for entity_id in (
                    company_catalog.metadata_entity_id(company, *record["tickers"]),
                )
                if entity_id
            }
            documents.append(CorpusDocument(
                document_id=document_id,
                company_names=tuple(sorted(record["company_names"], key=str.casefold)),
                company_entity_ids=tuple(sorted(company_ids)),
                tickers=tuple(sorted(record["tickers"], key=str.casefold)),
                ciks=tuple(sorted(record["ciks"])),
                form_types=tuple(sorted(record["form_types"], key=str.casefold)),
                filing_periods=tuple(sorted(record["filing_periods"], key=str.casefold)),
                sections=tuple(sorted(record["sections"], key=str.casefold)),
                table_ids=tuple(sorted(record["table_ids"], key=str.casefold)),
                chunk_count=record["chunk_count"],
                metadata_conflicts=tuple(sorted(conflicts)),
                table_evidence=(
                    SourceAvailability.AVAILABLE
                    if record["table_marked"]
                    else SourceAvailability.MISSING
                    if record["sections"]
                    else SourceAvailability.UNKNOWN
                ),
                xbrl_evidence=_combined_availability(record["xbrl_states"]),
            ))

        metadata_fields = {
            "company": "company_names",
            "ticker": "tickers",
            "cik": "ciks",
            "form_type": "form_types",
            "filing_period": "filing_periods",
            "section": "sections",
            "table_id": "table_ids",
        }
        metadata_coverage = {
            field: _metadata_coverage(documents, attribute)
            for field, attribute in metadata_fields.items()
        }
        structured_table_coverage = (
            SourceAvailability.AVAILABLE
            if has_table_marker
            else SourceAvailability.MISSING
            if has_section_inventory and documents
            else SourceAvailability.UNKNOWN
        )
        source_coverage = {
            "filing_text": (
                SourceAvailability.AVAILABLE
                if has_filing_text
                else SourceAvailability.UNKNOWN
                if documents
                else SourceAvailability.MISSING
            ),
            "structured_tables": table_coverage or structured_table_coverage,
            "xbrl_facts": xbrl_coverage,
        }
        if explicit_xbrl_states and xbrl_coverage == SourceAvailability.UNKNOWN:
            source_coverage["xbrl_facts"] = _combined_availability(explicit_xbrl_states)

        return cls(
            index_generation_id=index_generation_id,
            collection_name=collection_name,
            documents=tuple(documents),
            chunk_count=chunk_count,
            metadata_coverage=metadata_coverage,
            source_coverage=source_coverage,
        )

    @property
    def company_catalog(self) -> CompanyCatalog:
        return CompanyCatalog.from_document_rows(
            [
                {"company": company, "ticker": ticker}
                for document in self.documents
                for company in document.company_names
                for ticker in (document.tickers or (None,))
            ]
        )

    @property
    def indexed_company_entity_ids(self) -> frozenset[str]:
        return frozenset(
            entity_id
            for document in self.documents
            for entity_id in document.company_entity_ids
        )

    def documents_for_company(self, entity_id: str) -> tuple[CorpusDocument, ...]:
        return tuple(
            document
            for document in self.documents
            if entity_id in document.company_entity_ids
        )

    def runtime_payload(self) -> dict[str, Any]:
        """Return the planner-visible map, with no text or evaluation labels."""
        return self.model_dump(mode="json")


def _values(value: Any) -> set[str]:
    if isinstance(value, str):
        candidates = (value,)
    elif isinstance(value, (list, tuple, set, frozenset)):
        candidates = value
    else:
        return set()
    return {candidate.strip() for candidate in candidates if isinstance(candidate, str) and candidate.strip()}


def _first_text(row: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _conflict_fields(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple)):
        return set()
    fields = set()
    for item in value:
        if isinstance(item, Mapping) and isinstance(item.get("field"), str):
            fields.add(item["field"].strip())
        elif isinstance(item, str) and item.strip():
            fields.add(item.strip())
    return fields


def _availability(value: Any) -> SourceAvailability | None:
    if isinstance(value, bool):
        return SourceAvailability.AVAILABLE if value else SourceAvailability.MISSING
    if isinstance(value, SourceAvailability):
        return value
    if isinstance(value, str):
        try:
            return SourceAvailability(value.strip().upper())
        except ValueError:
            return None
    return None


def _combined_availability(values: Iterable[SourceAvailability]) -> SourceAvailability:
    states = set(values)
    if states == {SourceAvailability.AVAILABLE}:
        return SourceAvailability.AVAILABLE
    if states == {SourceAvailability.MISSING}:
        return SourceAvailability.MISSING
    return SourceAvailability.UNKNOWN


def _is_true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().casefold() == "true")


def _metadata_coverage(
    documents: list[CorpusDocument],
    attribute: str,
) -> MetadataCoverage:
    if not documents:
        return MetadataCoverage.UNKNOWN
    present = sum(bool(getattr(document, attribute)) for document in documents)
    conflict_field = {
        "company_names": "company",
        "tickers": "ticker",
        "ciks": "cik",
        "form_types": "form_type",
        "filing_periods": "filing_period",
        "sections": "section",
        "table_ids": "table_id",
    }[attribute]
    has_conflicts = any(conflict_field in document.metadata_conflicts for document in documents)
    if present == len(documents) and not has_conflicts:
        return MetadataCoverage.COMPLETE
    if present == 0 and not has_conflicts:
        return MetadataCoverage.NOT_INDEXED
    return MetadataCoverage.PARTIAL


def _normalize_conflict_fields(fields: set[str]) -> set[str]:
    aliases = {
        "company_name": "company",
        "issuer": "company",
        "tickers": "ticker",
        "ciks": "cik",
        "form": "form_type",
        "doc_type": "form_type",
        "form_types": "form_type",
        "reporting_period": "filing_period",
        "reporting_periods": "filing_period",
        "fiscal_period": "filing_period",
        "report_date": "filing_period",
        "filing_periods": "filing_period",
        "sections": "section",
        "table_ids": "table_id",
    }
    return {aliases.get(field.casefold(), field.casefold()) for field in fields}


def _normalize_form_type(value: str) -> str:
    match = _FORM_CODE_RE.search(value)
    if match:
        suffix = "a" if re.search(r"/\s*a\b", value, re.I) else ""
        return f"{match.group(1)}{match.group(2).casefold()}{suffix}"
    folded = value.casefold().strip()
    if folded in {"annual report", "annual filing"}:
        return "10k"
    if folded in {"quarterly report", "quarterly filing"}:
        return "10q"
    if folded in {"earnings release", "earnings report"}:
        return "earnings"
    return folded


__all__ = [
    "CORPUS_MAP_SCHEMA_VERSION",
    "CorpusDocument",
    "CorpusMap",
    "MetadataCoverage",
    "SourceAvailability",
]
