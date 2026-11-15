from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import pytest

from src.ingestion.inline_xbrl import Dimension, FactIdentity, extract_numeric_facts, resolve_inline_fact
from src.ingestion.sec_client import FilingMetadata
from src.retrieval.canonical_json import sha256_file


HTML = """<html xmlns="http://www.w3.org/1999/xhtml"
 xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
 xmlns:link="http://www.xbrl.org/2003/linkbase"
 xmlns:xlink="http://www.w3.org/1999/xlink"
 xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:us-gaap="http://fasb.org/us-gaap/2025" xmlns:ext="https://example.test/2025">
 <head><title>Inline fixture</title></head>
 <body><div style="display:none"><ix:header>
 <ix:references><link:schemaRef xlink:type="simple" xlink:href="sample.xsd"/></ix:references>
 <ix:resources>
 <xbrli:context id="c1">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-03-31</xbrli:endDate></xbrli:period>
 </xbrli:context>
 <xbrli:context id="c2">
  <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
  <xbrli:segment><xbrldi:explicitMember dimension="ext:RegionAxis">ext:Europe</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
  <xbrli:period><xbrli:instant>2025-03-31</xbrli:instant></xbrli:period>
  <xbrli:scenario><xbrldi:typedMember dimension="ext:CustomerAxis"><ext:Customer>Retail</ext:Customer></xbrldi:typedMember></xbrli:scenario>
 </xbrli:context>
 <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
 <xbrli:unit id="perShare"><xbrli:divide>
  <xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>
  <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
 </xbrli:divide></xbrli:unit>
 </ix:resources></ix:header></div>
 <p><ix:nonFraction id="rev" name="us-gaap:Revenues" contextRef="c1" unitRef="usd"
  decimals="-6" scale="6" sign="-" format="ixt:num-dot-decimal">1,230</ix:nonFraction></p>
 <p><ix:nonFraction id="segment" name="ext:ValuePerShare" contextRef="c2" unitRef="perShare"
  decimals="2">2.75</ix:nonFraction></p>
 </body></html>"""


@pytest.fixture
def archive(tmp_path: Path):
    pytest.importorskip("arelle")
    path = tmp_path / "filing.zip"
    with ZipFile(path, "w") as bundle:
        bundle.writestr("sample.htm", HTML)
        bundle.writestr("sample.xsd", '<schema xmlns="http://www.w3.org/2001/XMLSchema" targetNamespace="https://example.test/2025"/>')
    return path


def test_inline_extraction_preserves_financial_identity(archive, tmp_path):
    filing = FilingMetadata("AAPL", 320193, "10-Q/A", "0000320193-25-000100", "2025-05-02", "2025-03-31", "sample.htm")
    result = extract_numeric_facts(archive, filing, cache_directory=tmp_path / "cache")
    by_anchor = {fact["source_anchor"]: fact for fact in result["facts"]}
    revenue = by_anchor["rev"]
    assert revenue["value"] == "-1230000000"
    assert revenue["display_value"] == "1,230"
    assert revenue["identity"]["cik"] == "0000320193"
    assert revenue["identity"]["concept"] == "{http://fasb.org/us-gaap/2025}Revenues"
    assert revenue["identity"]["start"] == "2025-01-01"
    assert revenue["identity"]["end"] == "2025-03-31"
    assert revenue["identity"]["revision"] == "AMENDMENT"
    assert revenue["source_url"].endswith("sample.htm#rev")
    segment = by_anchor["segment"]
    assert segment["identity"]["concept"] == "{https://example.test/2025}ValuePerShare"
    assert segment["identity"]["start"] is None
    assert segment["identity"]["unit_denominator"] == ("{http://www.xbrl.org/2003/instance}shares",)
    dimensions = segment["identity"]["dimensions"]
    assert [(item["kind"], item["location"]) for item in dimensions] == [("typed", "scenario"), ("explicit", "segment")]
    assert dimensions[1]["member"] == "{https://example.test/2025}Europe"
    assert ">Retail<" in dimensions[0]["member"]


def test_inline_extraction_rejects_wrong_context_cik(archive, tmp_path):
    filing = FilingMetadata("MSFT", 789019, "10-Q", "0000789019-25-000100", "2025-05-02", "2025-03-31", "sample.htm")
    result = extract_numeric_facts(archive, filing, cache_directory=tmp_path / "cache")
    assert result["facts"] == []
    assert result["skipped"]["wrong_context_entity"] == 2


def test_inline_extraction_loads_verified_transforms_and_rejects_changed_bytes(archive, tmp_path, monkeypatch):
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "__init__.py").write_text(
        """from arelle.ModelValue import qname
from .text2num import to_number

def load_custom(known):
    known[qname("http://www.sec.gov/inlineXBRL/transformation/2015-08-31", "ixt-sec:numwordsen")] = to_number

__pluginInfo__ = {
    "name": "SEC test transform",
    "version": "1",
    "ModelManager.LoadCustomTransforms": load_custom,
}
""",
        encoding="utf-8",
    )
    (plugin / "text2num.py").write_text(
        """from arelle.formula.XPathContext import FunctionArgType

def to_number(value):
    if value != "two":
        raise FunctionArgType(0, "expected a supported number")
    return "2"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.ingestion.inline_xbrl.SEC_TRANSFORM_FILES", {
        part.name: sha256_file(part) for part in plugin.iterdir()
    })
    transformed = HTML.replace(
        'xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"',
        'xmlns:ixt="http://www.sec.gov/inlineXBRL/transformation/2015-08-31"',
    ).replace('format="ixt:num-dot-decimal">1,230', 'format="ixt:numwordsen">two')
    transformed = transformed.replace("</body>", """
 <ix:nonFraction id="invalid" name="us-gaap:Revenues" contextRef="c1" unitRef="usd"
  decimals="0" format="ixt:numwordsen">several</ix:nonFraction>
 </body>""")
    with ZipFile(archive, "r") as original:
        schema = original.read("sample.xsd")
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("sample.htm", transformed)
        bundle.writestr("sample.xsd", schema)
    filing = FilingMetadata("AAPL", 320193, "10-Q", "0000320193-25-000100", "2025-05-02", "2025-03-31", "sample.htm")

    parsed = extract_numeric_facts(archive, filing, cache_directory=tmp_path / "cache", sec_transforms=plugin)

    by_anchor = {row["source_anchor"]: row for row in parsed["facts"]}
    assert by_anchor["rev"]["value"] == "-2000000"
    assert by_anchor["rev"]["display_value"] == "two"
    assert "invalid" not in by_anchor
    assert parsed["skipped"]["unsupported_or_invalid_transform"] == 1

    (plugin / "text2num.py").write_text("raise AssertionError('unexpected execution')", encoding="utf-8")
    with pytest.raises(ValueError, match=r"checksum mismatch for text2num\.py"):
        extract_numeric_facts(archive, filing, cache_directory=tmp_path / "cache", sec_transforms=plugin)


def test_inline_resolution_checks_duplicate_values_and_source_identity():
    filing = FilingMetadata("AAPL", 320193, "10-K", "0000320193-25-000100", "2025-10-31", "2025-09-27", "sample.htm")
    identity = FactIdentity(
        "0000320193", "{us-gaap}Revenues", "2024-09-29", "2025-09-27", ("{iso4217}USD",), (),
        (Dimension("{ext}Axis", "explicit", "{ext}Member", "segment"),), filing.accession_number, "FILED", "",
    )
    row = {"fact_id": identity.fact_id, "identity": asdict(identity), "filed": filing.filing_date,
           "filing_form": filing.form_type, "report_date": filing.report_date, "source_anchor": "fact",
           "source_url": filing.filing_url + "#fact", "value": "109158000000"}
    resolved = resolve_inline_fact([row, row], identity, filing=filing)
    assert resolved.value == Decimal("109158000000")
    assert resolved.source_urls == (row["source_url"],)
    assert resolve_inline_fact([row, {**row, "value": "5"}], identity, filing=filing).reason == "conflicting_observations"
    assert resolve_inline_fact([{**row, "source_url": filing.filing_url}], identity,
                               filing=filing).reason == "observation_source_mismatch"
    forged = {**row, "identity": {**row["identity"], "dimensions": []}}
    assert resolve_inline_fact([forged], identity, filing=filing).reason == "observation_identity_mismatch"
