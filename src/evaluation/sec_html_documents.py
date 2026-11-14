"""Visible text and table blocks from accession-bound SEC HTML archives."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from zipfile import ZipFile

from lxml import etree

from src.ingestion.chunker import chunk_text, count_tokens
from src.ingestion.sec_corpus import MAX_ARCHIVE_BYTES, SourceCache


_OMIT = {"head", "script", "style", "ix:header", "ix:hidden"}
_BLOCK = {"div", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr"}
_HIDDEN = re.compile(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\b", re.I)
_MAX_MEMBER_BYTES = 16 * 1024 * 1024


def _text(value: str) -> str:
    return " ".join(value.split())


def _visible(root) -> None:
    for element in list(root.iter()):
        parent = element.getparent()
        if parent is None or not isinstance(element.tag, str):
            continue
        if element.tag in _OMIT or "hidden" in element.attrib or _HIDDEN.search(element.get("style", "")):
            if element.tail:
                previous = element.getprevious()
                if previous is None:
                    parent.text = (parent.text or "") + element.tail
                else:
                    previous.tail = (previous.tail or "") + element.tail
            parent.remove(element)


def _table_lines(table) -> list[str]:
    rows = []
    for row in table.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr"):
        cells = [_text("".join(cell.itertext())) for cell in row.xpath("./td|./th")]
        if cells := [cell for cell in cells if cell]:
            rows.append("  ".join(cells))
    return rows


def _blocks(root):
    fragments = []

    def flush():
        value = _text("".join(fragments))
        fragments.clear()
        if value:
            yield False, value

    def visit(element):
        if not isinstance(element.tag, str):
            return
        if element.tag == "table":
            yield from flush()
            if rows := _table_lines(element):
                yield True, "\n".join(rows)
            return
        if element.tag in _BLOCK:
            yield from flush()
        if element.text:
            fragments.append(element.text)
        for child in element:
            yield from visit(child)
            if child.tail:
                fragments.append(child.tail)
        if element.tag in _BLOCK:
            yield from flush()

    yield from visit(root)
    yield from flush()


def filing_blocks(root) -> list[tuple[str, str]]:
    """Preserve adjacent table headings and emit stable logical blocks."""
    _visible(root)
    blocks, prose = [], []
    for is_table, text in _blocks(root):
        if not is_table:
            prose.append(text)
            continue
        blocks.extend(("document", piece) for piece in chunk_text("\n\n".join(prose), 500, 75))
        prefix = [line for line in prose[-4:] if len(line) <= 180]
        prose.clear()
        blocks.append(("document", "\n".join([*prefix, text])))
    blocks.extend(("document", piece) for piece in chunk_text("\n\n".join(prose), 500, 75))
    return blocks


def _dei(root, name: str) -> str:
    values = {_text("".join(el.itertext())) for el in root.iter()
              if (el.get("name") or "").casefold() == f"dei:{name}"}
    if len(values) != 1 or not all(values):
        raise ValueError(f"Missing or ambiguous SEC cover metadata: {name}")
    return values.pop()


def read_filing(filing: dict, cache: SourceCache) -> tuple[list[dict], list[dict], dict]:
    path, receipt = cache.source(filing["archive"]["url"], MAX_ARCHIVE_BYTES)
    if receipt != filing["archive"]:
        raise ValueError("Archive receipt differs from frozen manifest")
    member = filing["primary_document"]
    with ZipFile(path) as archive:
        if (PurePosixPath(member).name != member or archive.namelist().count(member) != 1
                or archive.getinfo(member).file_size > _MAX_MEMBER_BYTES):
            raise ValueError("Unsafe or oversized primary SEC HTML member")
        root = etree.HTML(archive.read(member), parser=etree.HTMLParser(no_network=True))
    company = _dei(root, "entityregistrantname")
    year = int(_dei(root, "documentfiscalyearfocus"))
    focus = _dei(root, "documentfiscalperiodfocus")
    report_date = datetime.strptime(_dei(root, "documentperiodenddate"), "%B %d, %Y").date().isoformat()
    form, accession, ticker = (filing[key] for key in ("form_type", "accession_number", "ticker"))
    quarterly = form == "10-Q" and focus in {"Q1", "Q2", "Q3"}
    if report_date != filing["report_date"] or not (quarterly or form in {"10-K", "10-K/A"} and focus == "FY"):
        raise ValueError(f"Filing period metadata conflict: {accession}")
    name = f"{ticker}_{year}{focus if quarterly else ''}_{form.replace('-', '').replace('/', '')}_{accession}"
    metadata = {
        "doc_name": name, "document_id": name, "company": company, "ticker": ticker, "cik": str(filing["cik"]),
        "doc_type": form, "reporting_periods": [year], "filing_periods": [f"{focus} FY{year}" if quarterly else f"FY{year}"],
        "accession": accession, "source_revision": accession, "filing_date": filing["filing_date"],
        "report_date": report_date, "source_url": filing["source_url"], "dataset_id": "g2_sec_html",
    }
    pages, chunks = [], []
    for number, (section, text) in enumerate(filing_blocks(root)):
        if not text.strip():
            continue
        pages.append({"doc_name": name, "page_number": number, "text": text})
        for index, piece in enumerate(chunk_text(text, 500, 75)):
            chunks.append({**metadata, "page_number": number, "section": section, "text": piece,
                           "chunk_id": f"{name}:{number}:{index}", "token_count": count_tokens(piece)})
    if not chunks:
        raise ValueError(f"No visible filing text: {accession}")
    return chunks, pages, metadata
