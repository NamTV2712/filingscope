"""Prioritize retrieved pages that contain the requested financial statement slots."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from functools import lru_cache
from typing import Any

from src.decision.filing_tables import parse_revenue_table
from src.decision.requirement_extractor import EvidenceRequirementExtractor
from src.decision.statement_columns import parse_statement_columns, statement_report_date
from src.retrieval.pdf_page_cache import FrozenPdfPages


STATEMENT_CANDIDATE_POOL = 100
StatementSlots = frozenset[tuple[str, str | None]]


class FinancialStatementRanker:
    def __init__(self, pages: FrozenPdfPages, extractor: EvidenceRequirementExtractor):
        self.pages = pages
        self.extractor = extractor
        self.statement_pages = {(doc, page) for doc, items in pages.statements.items() for page, _ in items}
        self._slots = lru_cache(maxsize=256)(self._read_slots)

    def requirements(self, query: str) -> StatementSlots:
        return frozenset((slot.metric_id, slot.period) for slot in self.extractor.extract(query).evidence
                         if slot.quantitative)

    def _read_slots(
        self, document: str, page: int, form: str, year: int, report_end: date | None,
    ) -> frozenset[tuple[str, str]]:
        if (text := self.pages.get(document, page)) is None:
            return frozenset()
        quarter = re.search(r"(?:19|20)\d{2}Q([1-4])(?:_|$)", document, re.I)
        statement = parse_statement_columns(
            text, form=form, fiscal_year=year, quarter=int(quarter[1]) if quarter else None,
            confirmed_period_end=report_end,
        )
        if not statement.recognized:
            statement = parse_revenue_table(
                text, form=form, fiscal_year=year, declaration=self.pages.monetary_declaration(document),
            )
        return frozenset((cell.metric_id, cell.period) for cell in statement.values if not cell.restated)

    def priority(self, chunk: Mapping[str, Any], wanted: StatementSlots) -> int:
        if not wanted:
            return 0
        document, page = chunk.get("doc_name"), chunk.get("page_number")
        periods, form = chunk.get("reporting_periods"), chunk.get("doc_type")
        if (not isinstance(document, str) or chunk.get("document_id") != document
                or type(page) is not int or not isinstance(form, str)
                or not isinstance(periods, (list, tuple)) or len(periods) != 1
                or not re.fullmatch(r"(?:19|20)\d{2}", str(periods[0]))):
            return 0
        observed = self._slots(document, page, form, int(periods[0]), statement_report_date(chunk))
        return sum(any(metric == candidate and (period is None or period == observed_period)
                       for candidate, observed_period in observed) for metric, period in wanted)
