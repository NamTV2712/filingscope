from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.verification.models import (
    CalculationOperand,
    CalculationOperation,
    CalculationRequest,
)
from src.verification.numerical_verifier import NumericalOperationVerifier


def _operand(value: str, *, scale: str = "unit", currency: str = "USD") -> CalculationOperand:
    return CalculationOperand(value=Decimal(value), scale=scale, currency=currency)


def test_decimal_operations_normalize_scales_and_check_reported_units() -> None:
    verifier = NumericalOperationVerifier()
    addition = verifier.verify(CalculationRequest(
        operation=CalculationOperation.ADDITION,
        operands=(_operand("1", scale="billion"), _operand("250", scale="million")),
        reported_value=Decimal("1250"), reported_currency="USD", reported_scale="million",
    ))
    subtraction = verifier.verify(CalculationRequest(
        operation=CalculationOperation.SUBTRACTION,
        operands=(_operand("1.5", scale="billion"), _operand("250", scale="million")),
        reported_value=Decimal("1.25"), reported_currency="USD", reported_scale="billion",
    ))
    difference = verifier.verify(CalculationRequest(
        operation=CalculationOperation.DIFFERENCE,
        operands=(_operand("250", scale="million"), _operand("1", scale="billion")),
        reported_value=Decimal("750"), reported_currency="USD", reported_scale="million",
    ))

    assert addition.passed and addition.expected_value == Decimal("1250000000.00")
    assert subtraction.passed and subtraction.expected_value == Decimal("1250000000.00")
    assert difference.passed and difference.expected_value == Decimal("750000000.00")


def test_percentage_growth_is_signed_and_requires_compatible_baseline() -> None:
    verifier = NumericalOperationVerifier()
    growth = verifier.verify(CalculationRequest(
        operation=CalculationOperation.PERCENTAGE_GROWTH,
        operands=(_operand("100", scale="million"), _operand("110", scale="million")),
        reported_value=Decimal("10"), reported_kind="percent",
    ))
    decline = verifier.verify(CalculationRequest(
        operation=CalculationOperation.PERCENTAGE_GROWTH,
        operands=(_operand("100"), _operand("90")),
        reported_value=Decimal("-10"), reported_kind="percent",
    ))
    bad_currency = verifier.verify(CalculationRequest(
        operation=CalculationOperation.ADDITION,
        operands=(_operand("1", currency="USD"), _operand("1", currency="EUR")),
        reported_value=Decimal("2"), reported_currency="USD", reported_scale="unit",
    ))

    assert growth.passed and growth.expected_kind == "percent"
    assert decline.passed and decline.expected_value == Decimal("-10.00")
    assert not bad_currency.passed and bad_currency.reason_code == "currency_mismatch"


def test_non_finite_inputs_fail_closed() -> None:
    with pytest.raises(ValidationError):
        CalculationOperand(value=Decimal("NaN"), currency="USD", scale="unit")
