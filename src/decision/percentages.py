"""Bind the numerator and denominator named by a same-period percentage question."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext

from src.decision.models import CoverageStatus, EvidenceFact, EvidenceFinding, MetricRequirement, OperationRequirement


_FORWARD = re.compile(r"\bas (?:a )?(?:percentage|percent|%) of\b", re.I)
_REVERSE = re.compile(r"\bwhat (?:percentage|percent) of\b", re.I)


def requests_percentage(question: str) -> bool:
    return bool(_FORWARD.search(question) or _REVERSE.search(question))


def percentage_operands(question: str, metrics: tuple[MetricRequirement, ...]) -> tuple[str, str] | None:
    """Recognize both 'X as a percentage of Y' and 'what percentage of Y is X'."""
    if len(metrics) != 2 or not all(metric.quantitative for metric in metrics):
        return None
    text = question.casefold()
    boundary = _FORWARD.search(text)
    reverse = False
    if boundary is None:
        boundary = _REVERSE.search(text)
        reverse = boundary is not None
    if boundary is None:
        return None
    if reverse:
        rest = text[boundary.end():]
        verb = re.search(r"\b(?:was|were|is|are|consisted of|represented by)\b", rest)
        if verb is None:
            return None
        left, right = rest[:verb.start()], rest[verb.end():]
    else:
        left, right = text[:boundary.start()], text[boundary.end():]

    def metric_id(fragment: str) -> str | None:
        matches = {metric.metric_id for metric in metrics if any(
            re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", fragment, re.I) for alias in metric.aliases
        )}
        return next(iter(matches)) if len(matches) == 1 else None

    first, second = metric_id(left), metric_id(right)
    if first is None or second is None or first == second:
        return None
    return (second, first) if reverse else (first, second)


def requested_statement_date(question: str) -> date | None:
    """Read a single explicitly named balance date without assigning its fiscal basis."""
    months = {month.casefold(): index for index, month in enumerate(
        "January February March April May June July August September October November December".split(), 1,
    )}
    pattern = re.compile(r"\b(?:at|on|as of)\s+(" + "|".join(months) + r")\s+(\d{1,2}),?\s+((?:19|20)\d{2})\b", re.I)
    matches = list(pattern.finditer(question))
    if len(matches) != 1:
        return None
    match = matches[0]
    try:
        return date(int(match[3]), months[match[1].casefold()], int(match[2]))
    except ValueError:
        return None


def percentage_cells(
    operation: OperationRequirement, findings: list[EvidenceFinding] | tuple[EvidenceFinding, ...],
) -> tuple[EvidenceFact, EvidenceFact] | None:
    """Select compatible filed cells for the two explicitly requested metrics."""
    by_metric = {finding.metric_id: finding for finding in findings if finding.status == CoverageStatus.FOUND}
    numerator = by_metric.get(operation.numerator_metric_id or "")
    denominator = by_metric.get(operation.denominator_metric_id or "")
    if numerator is None or denominator is None:
        return None
    for left in numerator.facts:
        for right in denominator.facts:
            a, b = left.period_identity, right.period_identity
            if (left.entity_id == right.entity_id and left.document_id == right.document_id
                    and left.filing_accession and left.filing_accession == right.filing_accession
                    and left.source_url and left.source_url == right.source_url
                    and left.currency and left.currency == right.currency and left.scale == right.scale == "unit"
                    and left.value_kind == right.value_kind == "amount" and a and b
                    and left.period == right.period and a.kind == b.kind and a.scope == b.scope
                    and a.end is not None and a.end == b.end and a.start == b.start
                    and left.table_title and left.table_title == right.table_title
                    and left.table_row is not None and right.table_row is not None
                    and left.table_column is not None and right.table_column is not None
                    and (left.page_number, left.table_row, left.table_column) != (right.page_number, right.table_row, right.table_column)
                    and percentage_value(left, right) is not None):
                return left, right
    return None


def percentage_value(numerator: EvidenceFact, denominator: EvidenceFact) -> Decimal | None:
    try:
        with localcontext() as context:
            context.prec = 28
            left, right = Decimal(numerator.numeric_value or "NaN"), Decimal(denominator.numeric_value or "NaN")
            if not left.is_finite() or not right.is_finite() or right <= 0:
                return None
            return (left / right * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except DecimalException:
        return None


def percentage_statement(company: str, numerator: str, denominator: str, value: Decimal, period: str) -> str:
    return f"{company.rstrip('.')}'s {numerator} represented {value:.2f}% of {denominator} for {period}."
