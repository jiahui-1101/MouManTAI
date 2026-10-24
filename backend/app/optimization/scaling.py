"""Exact decimal/integer conversion for CP-SAT. No ambient-context rounding."""

from decimal import Decimal

MAX_INT = 2**62 - 1  # Leave headroom for CP-SAT weighted sums.


class ScalingError(ValueError):
    pass


def scaled(value: Decimal, scale: int, *, nonnegative: bool = True) -> int:
    if not isinstance(value, Decimal) or not value.is_finite() or scale < 1:
        raise ScalingError("SCALING_PRECISION_UNSUPPORTED")
    if nonnegative and value < 0:
        raise ScalingError("NEGATIVE_QUANTITY")
    sign, digits, exponent = value.as_tuple()
    if abs(exponent) > 100:
        raise ScalingError("SCALING_OVERFLOW" if exponent > 0 else "SCALING_PRECISION_UNSUPPORTED")
    coefficient = 0
    for digit in digits:
        coefficient = coefficient * 10 + digit
        if coefficient > MAX_INT * 10**20:
            raise ScalingError("SCALING_OVERFLOW")
    numerator = coefficient * scale
    if exponent >= 0:
        numerator *= 10**exponent
        denominator = 1
    else:
        denominator = 10 ** (-exponent)
    if numerator % denominator:
        raise ScalingError("SCALING_PRECISION_UNSUPPORTED")
    result = numerator // denominator
    if result > MAX_INT:
        raise ScalingError("SCALING_OVERFLOW")
    return -result if sign else result


def unscaled(value: int, scale: int) -> Decimal:
    if not isinstance(value, int) or scale < 1:
        raise ScalingError("SCALING_PRECISION_UNSUPPORTED")
    if abs(value) > MAX_INT:
        raise ScalingError("SCALING_OVERFLOW")
    # Decimal(int) / Decimal(scale) can round under a narrow ambient context.
    # The approved scales are powers of ten, so scaleb is exact.
    power = len(str(scale)) - 1
    if scale != 10**power:
        raise ScalingError("SCALING_PRECISION_UNSUPPORTED")
    digits = tuple(int(digit) for digit in str(abs(value)))
    return Decimal((int(value < 0), digits, -power))
