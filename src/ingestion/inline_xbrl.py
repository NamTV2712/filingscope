"""Extract numeric Inline XBRL observations from cached SEC filing archives."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.parse import quote
from zipfile import ZipFile

from lxml import etree

from src.ingestion.company_facts import normalize_cik
from src.ingestion.sec_client import FilingMetadata
from src.retrieval.canonical_json import canonical_sha256, sha256_file

PARSER_VERSION = "sec-inline-xbrl-v1"
SEC_CIK_SCHEME = "http://www.sec.gov/CIK"
XBRLDI = "http://xbrl.org/2006/xbrldi"
MAX_UNCOMPRESSED_BYTES = 120 * 1024 * 1024
SEC_TRANSFORM_REVISION = "4891c4c9889c77af247428ceff4fa7cc52d534ea"
SEC_TRANSFORM_FILES = {
    "__init__.py": "sha256:2296586f945ffd95ab37d3d4147c4e45f42ce4e5f397f61143e053208adefbf1",
    "text2num.py": "sha256:6c9b26354320a2fb34fe380cdc71ff7f8d1cc712811e6b10c661e512f0383409",
}
_SEC_TRANSFORM_NAMESPACE = "http://www.sec.gov/inlineXBRL/transformation/2015-08-31"


@dataclass(frozen=True)
class Dimension:
    axis: str
    kind: str
    member: str
    location: str


@dataclass(frozen=True)
class FactIdentity:
    cik: str
    concept: str
    start: str | None
    end: str
    unit_numerator: tuple[str, ...]
    unit_denominator: tuple[str, ...]
    dimensions: tuple[Dimension, ...]
    accession: str
    revision: str
    target: str

    @property
    def fact_id(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True)
class InlineFactResolution:
    reason: str
    value: Decimal | None = None
    source_urls: tuple[str, ...] = ()


def resolve_inline_fact(
    rows: Iterable[dict], identity: FactIdentity, *, filing: FilingMetadata,
) -> InlineFactResolution:
    """Return one accession-bound observation with the complete requested identity."""
    if (identity.cik != normalize_cik(filing.cik) or identity.accession != filing.accession_number
            or identity.revision != ("AMENDMENT" if filing.form_type.endswith("/A") else "FILED")):
        return InlineFactResolution("filing_identity_mismatch")
    expected = identity.fact_id
    values, sources = set(), set()
    for row in rows:
        if row.get("fact_id") != expected:
            continue
        if (canonical_sha256(row["identity"]) != expected or row.get("filed") != filing.filing_date
                or row.get("filing_form") != filing.form_type or row.get("report_date") != filing.report_date):
            return InlineFactResolution("observation_identity_mismatch")
        try:
            value = Decimal(row["value"])
        except (KeyError, InvalidOperation, TypeError):
            return InlineFactResolution("invalid_observation_value")
        if not value.is_finite():
            return InlineFactResolution("invalid_observation_value")
        anchor = row.get("source_anchor")
        source = f"{filing.filing_url}#{quote(anchor, safe='')}" if isinstance(anchor, str) and anchor else filing.filing_url
        if row.get("source_url") != source:
            return InlineFactResolution("observation_source_mismatch")
        values.add(value)
        sources.add(source)
    if not values:
        return InlineFactResolution("identity_unavailable")
    if len(values) != 1:
        return InlineFactResolution("conflicting_observations")
    return InlineFactResolution("resolved", values.pop(), tuple(sorted(sources)))


def _dimensions(context) -> tuple[Dimension, ...]:
    result = []
    for location, container in (("segment", context.segment), ("scenario", context.scenario)):
        if container is None:
            continue
        for value in container.iterchildren(tag=etree.Element):
            axis = value.dimensionQname if value.tag in {
                f"{{{XBRLDI}}}explicitMember", f"{{{XBRLDI}}}typedMember",
            } else None
            if axis is None:
                raise ValueError("unsupported_context_content")
            if value.isExplicit and value.memberQname is not None:
                member, kind = value.memberQname.clarkNotation, "explicit"
            elif value.isTyped and value.typedMember is not None:
                member = etree.tostring(value.typedMember, method="c14n", exclusive=True).decode("utf-8")
                kind = "typed"
            else:
                raise ValueError("invalid_dimension")
            result.append(Dimension(axis.clarkNotation, kind, member, location))
    if len({item.axis for item in result}) != len(result):
        raise ValueError("invalid_dimension")
    return tuple(sorted(result, key=lambda item: item.axis))


def _identity(fact, filing: FilingMetadata) -> FactIdentity:
    context = fact.context
    unit = fact.unit
    if context is None or unit is None or fact.qname is None:
        raise ValueError("missing_context_unit_or_concept")
    scheme, entity = context.entityIdentifier
    if scheme != SEC_CIK_SCHEME or normalize_cik(entity) != normalize_cik(filing.cik):
        raise ValueError("wrong_context_entity")
    start = context.startDatetime.date() if context.isStartEndPeriod and context.startDatetime else None
    end = context.endDate
    if (end is None or not (context.isInstantPeriod or start is not None)
            or (start is not None and start > end)):
        raise ValueError("invalid_period")
    numerator, denominator = unit.measures
    if not numerator:
        raise ValueError("invalid_unit")
    return FactIdentity(
        cik=normalize_cik(filing.cik),
        concept=fact.qname.clarkNotation,
        start=start.isoformat() if start is not None else None,
        end=end.isoformat(),
        unit_numerator=tuple(sorted(measure.clarkNotation for measure in numerator)),
        unit_denominator=tuple(sorted(measure.clarkNotation for measure in denominator)),
        dimensions=_dimensions(context),
        accession=filing.accession_number,
        revision="AMENDMENT" if filing.form_type.endswith("/A") else "FILED",
        target=fact.get("target", ""),
    )


def _record(fact, filing: FilingMetadata) -> dict:
    identity = _identity(fact, filing)
    scale = int(fact.get("scale", "0"))
    if not -30 <= scale <= 30:
        raise ValueError("unsupported_scale")
    if fact.get("sign") not in (None, "-"):
        raise ValueError("invalid_sign")
    # Arelle applies the inline format, scale and sign. Keep base-unit Decimal
    # text and the displayed amount so the transformation can be audited.
    with localcontext() as context:
        context.prec = 128
        value = Decimal(fact.value)
    if not value.is_finite():
        raise ValueError("non_finite_value")
    anchor = fact.get("id")
    return {
        "fact_id": identity.fact_id, "identity": asdict(identity),
        "concept_display": fact.get("name"), "value": format(value, "f"),
        "display_value": fact.rawValue, "format": fact.get("format"),
        "scale": scale, "decimals": fact.get("decimals"),
        "context_id": fact.get("contextRef"), "unit_id": fact.get("unitRef"),
        "filing_form": filing.form_type, "filed": filing.filing_date,
        "report_date": filing.report_date,
        "source_url": f"{filing.filing_url}#{quote(anchor, safe='')}" if anchor else filing.filing_url,
        "source_anchor": anchor, "source_line": fact.sourceline,
    }


@contextmanager
def _stage_sec_transforms(source: Path | None) -> Iterator[Path | None]:
    if source is None:
        yield None
        return
    # Stage verified source bytes so Arelle loads only the pinned plugin and its dependency.
    with TemporaryDirectory(prefix="filingscope-sec-transforms-") as temporary:
        plugin = Path(temporary) / "transform"
        plugin.mkdir()
        for name, expected in SEC_TRANSFORM_FILES.items():
            with (source / name).open("rb") as stream:
                contents = stream.read(65_536)
            if f"sha256:{sha256(contents).hexdigest()}" != expected:
                raise ValueError(f"SEC Inline Transforms checksum mismatch for {name}")
            (plugin / name).write_bytes(contents)
        yield plugin


def extract_numeric_facts(
    archive: Path, filing: FilingMetadata, *, cache_directory: Path, sec_transforms: Path | None = None,
) -> dict:
    """Extract from a local SEC archive with Arelle's network access disabled."""
    from arelle.FunctionIxt import ixtFunctionNotAvailable
    from arelle.RuntimeOptions import RuntimeOptions
    from arelle.api.Session import Session
    from arelle.formula.XPathContext import FunctionArgType

    with ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if len(entries) > 1000 or sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("SEC XBRL archive exceeds expansion limits")
        if len({entry.filename for entry in entries}) != len(entries):
            raise ValueError("SEC XBRL archive contains duplicate members")
        if any("\\" in entry.filename or PurePosixPath(entry.filename).is_absolute()
               or ".." in PurePosixPath(entry.filename).parts for entry in entries):
            raise ValueError("SEC XBRL archive contains unsafe member paths")
        if filing.primary_document not in bundle.namelist():
            raise ValueError("SEC XBRL archive is missing the primary Inline XBRL document")
    date.fromisoformat(filing.filing_date)
    cache_directory.mkdir(parents=True, exist_ok=True)
    skipped: Counter[str] = Counter()
    facts = []
    with _stage_sec_transforms(sec_transforms) as plugin, Session() as session:
        options = RuntimeOptions(
            entrypointFile=f"{archive.resolve().as_posix()}/{filing.primary_document}",
            internetConnectivity="offline", keepOpen=True, logFile="logToBuffer",
            cacheDirectory=str(cache_directory.resolve()),
            plugins=plugin.as_posix() if plugin else None, disablePersistentConfig=plugin is not None,
        )
        if not session.run(options) or len(session.get_models()) != 1:
            raise ValueError("Unable to load Inline XBRL archive")
        model, = session.get_models()
        if plugin is not None and not any(
            name.namespaceURI == _SEC_TRANSFORM_NAMESPACE and name.localName == "numwordsen"
            for name in model.modelManager.customTransforms
        ):
            raise ValueError("Arelle did not load the pinned SEC Inline Transforms")
        diagnostics = dict(Counter(map(str, model.errors)))
        for fact in model.facts:
            if fact.localName != "nonFraction" or fact.isNil:
                skipped["nil_or_non_numeric"] += 1
                continue
            try:
                facts.append(_record(fact, filing))
            except ValueError as error:
                key = str(error)
                skipped[key if key in {
                    "unsupported_context_content", "invalid_dimension", "missing_context_unit_or_concept",
                    "wrong_context_entity", "invalid_period", "invalid_unit", "unsupported_scale",
                    "invalid_sign", "non_finite_value",
                } else "invalid_numeric_or_context"] += 1
            except (InvalidOperation, FunctionArgType, ixtFunctionNotAvailable, KeyError):
                skipped["unsupported_or_invalid_transform"] += 1
    facts.sort(key=lambda row: (row["fact_id"], row["source_anchor"] or "", row["source_line"] or 0, row["value"]))
    return {"parser_version": PARSER_VERSION, "archive_sha256": sha256_file(archive),
            "facts": facts, "skipped": dict(skipped), "arelle_diagnostics": diagnostics}
