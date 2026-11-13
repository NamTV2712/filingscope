"""Accession-bound Inline XBRL evidence for the validated Tesla segment."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from src.ingestion.company_facts import FactRevision, InlineXbrlProvenance, ResolvedCompanyFact, RevisionKind, RevisionPolicy
from src.ingestion.inline_xbrl import Dimension, FactIdentity, resolve_inline_fact
from src.ingestion.sec_client import FilingMetadata

ENERGY_METRIC = "energy_segment_revenue"
ENERGY_SECTION = "xbrl_inline_segment"
ENERGY_ENTITY = "TSLA"
ENERGY_LABEL = "energy generation and storage segment revenue"
ENERGY_ALIASES = (ENERGY_LABEL, "energy generation and storage revenue")
ENERGY_PERIOD = "FY2024"
ENERGY_FILING = FilingMetadata(
    ENERGY_ENTITY, 1318605, "10-K", "0001628280-25-003063", "2025-01-30", "2024-12-31", "tsla-20241231.htm",
)
ENERGY_IDENTITY = FactIdentity(
    "0001318605", "{http://fasb.org/us-gaap/2024}Revenues", "2024-01-01", "2024-12-31",
    ("{http://www.xbrl.org/2003/iso4217}USD",), (),
    (Dimension("{http://fasb.org/us-gaap/2024}StatementBusinessSegmentsAxis", "explicit",
               "{http://www.tesla.com/20241231}EnergyGenerationAndStorageSegmentMember", "segment"),),
    ENERGY_FILING.accession_number, "FILED", "",
)


def load_energy_revenue(extract: Path, expected_hash: str) -> ResolvedCompanyFact:
    """Load the reviewed fact from a caller-pinned SEC extraction."""
    content = extract.read_bytes()
    if f"sha256:{hashlib.sha256(content).hexdigest()}" != expected_hash:
        raise ValueError("Segment extract differs from the pinned filing")
    result = resolve_inline_fact(json.loads(content)["facts"], ENERGY_IDENTITY, filing=ENERGY_FILING)
    if result.value is None or not result.source_urls or not all("#" in url for url in result.source_urls):
        raise ValueError(f"Segment observation could not be resolved with an anchor: {result.reason}")
    raw = format(result.value, "f")
    filing = ENERGY_FILING
    return ResolvedCompanyFact(
        value=result.value, raw_value=raw, currency="USD", fiscal_period=ENERGY_PERIOD,
        filing_date=filing.filing_date, form=filing.form_type, filing_url=result.source_urls[0],
        provenance=InlineXbrlProvenance(
            policy_version="sec-inline-segment-v1", taxonomy="us-gaap", tag="Revenues",
            label=ENERGY_LABEL, period_start=ENERGY_IDENTITY.start,
            period_end=ENERGY_IDENTITY.end, period_alignment="filing_report_date", raw_unit="USD",
            accession=filing.accession_number, filing_fiscal_year=2024, filing_fiscal_period="FY",
            company_facts_url=None, revision_policy=RevisionPolicy.AS_REPORTED, revision_kind=RevisionKind.ORIGINAL,
            original_accession=filing.accession_number, inline_identity_sha256=ENERGY_IDENTITY.fact_id,
            dimensions=tuple((item.axis, item.member) for item in ENERGY_IDENTITY.dimensions),
            history=(FactRevision(accession=filing.accession_number, filing_date=filing.filing_date,
                                  form=filing.form_type, raw_value=raw),),
        ),
    )


def matches_energy_provenance(source: object) -> bool:
    return (
        isinstance(source, InlineXbrlProvenance) and source.inline_identity_sha256 == ENERGY_IDENTITY.fact_id
        and source.dimensions == tuple((item.axis, item.member) for item in ENERGY_IDENTITY.dimensions)
        and (source.accession, source.period_start, source.period_end, source.raw_unit, source.taxonomy, source.tag)
        == (ENERGY_IDENTITY.accession, ENERGY_IDENTITY.start, ENERGY_IDENTITY.end, "USD", "us-gaap", "Revenues")
        and source.revision_kind == RevisionKind.ORIGINAL and source.revision_policy == RevisionPolicy.AS_REPORTED
    )


def is_energy_revenue(fact: ResolvedCompanyFact) -> bool:
    return (
        matches_energy_provenance(fact.provenance)
        and fact.fiscal_period == ENERGY_PERIOD and fact.currency == "USD" and fact.form == "10-K"
        and fact.filing_date == ENERGY_FILING.filing_date
        and _has_filing_anchor(fact.filing_url)
        and fact.value.is_finite()
    )


def is_energy_evidence(chunk: Mapping[str, object]) -> bool:
    return (
        chunk.get("section") == ENERGY_SECTION and chunk.get("source_type") == "XBRL_FACT"
        and matches_energy_provenance(chunk.get("inline_provenance")) and _has_filing_anchor(chunk.get("source_url"))
    )


def _has_filing_anchor(value: object) -> bool:
    prefix = ENERGY_FILING.filing_url + "#"
    return isinstance(value, str) and value.startswith(prefix) and len(value) > len(prefix)
