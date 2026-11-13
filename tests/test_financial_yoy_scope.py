import pytest

from src.decision.requirement_extractor import EvidenceRequirementExtractor


@pytest.mark.parametrize(("period", "expected"), [
    ("Q2 YTD FY2025", ("Q2 YTD FY2024", "Q2 YTD FY2025")),
    ("Q2 FY2025", ("Q2 FY2024", "Q2 FY2025")),
    ("CY2025", ("CY2024", "CY2025")),
    ("FY2025", ("FY2024", "FY2025")),
])
def test_yoy_prior_period_preserves_the_requested_reporting_scope(period, expected):
    result = EvidenceRequirementExtractor().extract(f"What was Apple's {period} revenue growth year over year?")
    assert result.supported
    assert result.periods == expected
    assert tuple(slot.period for slot in result.evidence) == expected
