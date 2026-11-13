from pathlib import Path
from zipfile import ZipFile

import pytest

from src.ingestion.inline_xbrl import extract_numeric_facts
from src.ingestion.sec_client import FilingMetadata


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
