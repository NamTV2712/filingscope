"""Locate the SEC filing's financial statement DOM interval."""

import json
import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

logger = logging.getLogger(__name__)


def _candidate_start_snippets(financial_statement_text: str) -> list[str]:
    snippets = []
    normalized = financial_statement_text.strip()
    if normalized:
        snippets.append(normalized[:40].strip())

    for line in normalized.splitlines()[:20]:
        line = line.strip()
        if len(line) >= 12:
            snippets.append(line[:80])

    seen: set[str] = set()
    return [snippet for snippet in snippets if snippet and not (snippet in seen or seen.add(snippet))]


def _find_start_node(
    soup: BeautifulSoup, financial_statement_text: str
) -> NavigableString | None:
    for snippet in _candidate_start_snippets(financial_statement_text):
        node = soup.find(string=lambda text: text and snippet in text)
        if node is not None:
            return node
    return None


def _resolve_toc_link_start(
    soup: BeautifulSoup, start_node: NavigableString
) -> Tag | NavigableString:
    parent = start_node.parent
    while parent is not None:
        if parent.name == "a" and parent.get("href", "").startswith("#"):
            target_id = parent["href"][1:]
            target = soup.find(id=target_id) or soup.find(attrs={"name": target_id})
            return target if target is not None else start_node
        parent = parent.parent
    return start_node


def find_tables_in_financial_section(
    html_path: Path, sections_json_path: Path
) -> list[Tag]:
    """Return tables between the extracted financial section and Item 9."""
    soup = BeautifulSoup(html_path.read_bytes(), "lxml")
    sections = json.loads(sections_json_path.read_text(encoding="utf-8"))
    financial_statement_text = sections["sections"]["financial_statements"]
    start_node = _find_start_node(soup, financial_statement_text)

    if start_node is None:
        first_snippet = financial_statement_text[:40].strip()
        logger.warning("Could not find financial section start anchor %r", first_snippet)
        return []

    start = _resolve_toc_link_start(soup, start_node)
    tables = []
    item_9_pattern = re.compile(r"item\s+9\b", re.IGNORECASE)
    for element in start.next_elements:
        if isinstance(element, NavigableString) and item_9_pattern.search(str(element)):
            break
        if isinstance(element, Tag) and element.name == "table":
            tables.append(element)
    return tables
