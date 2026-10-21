"""Exact finite Decimal operations independent of the caller's precision."""

from decimal import Context, Decimal, Inexact, localcontext


def add(left: Decimal, right: Decimal) -> Decimal:
    precision = max(left.adjusted(), right.adjusted(), 0) - min(
            left.as_tuple().exponent, right.as_tuple().exponent, 0
        ) + 3
    with localcontext(Context(prec=precision)) as context:
        context.traps[Inexact] = True
        return left + right


def subtract(left: Decimal, right: Decimal) -> Decimal:
    return add(left, right.copy_negate())


def multiply(left: Decimal, right: Decimal) -> Decimal:
    precision = len(left.as_tuple().digits) + len(right.as_tuple().digits) + 2
    with localcontext(Context(prec=precision)) as context:
        context.traps[Inexact] = True
        return left * right
