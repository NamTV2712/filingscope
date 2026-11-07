"""Safe Decimal arithmetic and financial unit checks for declared operations."""

from __future__ import annotations

from decimal import Decimal, DecimalException, InvalidOperation, ROUND_HALF_UP

from src.verification.models import (
    CalculationOperation,
    CalculationRequest,
    CalculationVerification,
)


_SCALE_FACTOR: dict[str, Decimal] = {
    "unit": Decimal("1"),
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
}


def _quantize(value: Decimal, precision: int) -> Decimal:
    quantum = Decimal(1).scaleb(-precision)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _unverifiable(request: CalculationRequest, reason: str) -> CalculationVerification:
    return CalculationVerification(
        passed=False,
        status="unverifiable",
        operation=request.operation,
        reported_value=request.reported_value,
        reason_code=reason,
    )


class NumericalOperationVerifier:
    """Verify only the registered addition, subtraction, difference and growth operations."""

    def verify(self, request: CalculationRequest) -> CalculationVerification:
        operation = request.operation
        required_operands = 2 if operation != CalculationOperation.ADDITION else None
        if required_operands is not None and len(request.operands) != required_operands:
            return _unverifiable(request, "wrong_operand_count")
        if operation == CalculationOperation.ADDITION and len(request.operands) < 2:
            return _unverifiable(request, "wrong_operand_count")
        if not request.reported_value.is_finite() or any(
            not operand.value.is_finite() for operand in request.operands
        ):
            return _unverifiable(request, "non_finite_value")

        currencies = {operand.currency for operand in request.operands}
        if None in currencies or "" in currencies:
            return _unverifiable(request, "currency_unknown")
        if len(currencies) != 1:
            return _unverifiable(request, "currency_mismatch")
        currency = next(iter(currencies))

        scales = [operand.scale for operand in request.operands]
        if any(scale not in _SCALE_FACTOR for scale in scales):
            return _unverifiable(request, "scale_unknown")
        try:
            base_values = [
                operand.value * _SCALE_FACTOR[operand.scale]
                for operand in request.operands
            ]

            if operation == CalculationOperation.ADDITION:
                expected = sum(base_values, start=Decimal(0))
                expected_kind = "amount"
            elif operation == CalculationOperation.SUBTRACTION:
                expected = base_values[0] - base_values[1]
                expected_kind = "amount"
            elif operation == CalculationOperation.DIFFERENCE:
                expected = abs(base_values[0] - base_values[1])
                expected_kind = "amount"
            else:
                baseline = base_values[0]
                if baseline <= 0:
                    return _unverifiable(request, "nonpositive_growth_baseline")
                expected = (base_values[1] - baseline) / baseline * Decimal(100)
                expected_kind = "percent"
        except DecimalException:
            return _unverifiable(request, "invalid_decimal_value")

        if request.reported_kind != expected_kind:
            return _unverifiable(request, "result_kind_mismatch")

        if expected_kind == "percent":
            if request.reported_currency is not None or request.reported_scale is not None:
                return _unverifiable(request, "unexpected_result_unit")
            reported = request.reported_value
            expected_currency = None
            expected_scale = None
        else:
            if request.reported_currency != currency:
                return _unverifiable(request, "result_currency_mismatch")
            if request.reported_scale not in _SCALE_FACTOR:
                return _unverifiable(request, "result_scale_unknown")
            reported = request.reported_value * _SCALE_FACTOR[request.reported_scale]
            expected_currency = currency
            expected_scale = "unit"

        try:
            rounded_expected = _quantize(expected, request.rounding_precision)
            rounded_reported = _quantize(reported, request.rounding_precision)
        except (DecimalException, InvalidOperation, ValueError):
            return _unverifiable(request, "invalid_decimal_precision")
        passed = rounded_expected == rounded_reported
        return CalculationVerification(
            passed=passed,
            status="verified" if passed else "mismatch",
            operation=operation,
            expected_value=rounded_expected,
            reported_value=request.reported_value,
            expected_kind=expected_kind,
            expected_currency=expected_currency,
            expected_scale=expected_scale,
            reason_code="calculation_matches" if passed else "arithmetic_mismatch",
        )
