"""The numbers of the engine: decimal context, its decorator, rounding, input error.

Examples:
    >>> round_to(Decimal("2.345"), 2)
    Decimal('2.34')
"""

from collections.abc import Callable
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    getcontext,
    localcontext,
)
from functools import wraps

CONTEXT = Context(
    prec=50,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, DivisionByZero],
)


class InputError(ValueError):
    """An input that breaks a rule, with the text `<path>: <problem>`.

    Examples:
        >>> str(InputError("decisions.0.quantity: has more than 3 places"))
        'decisions.0.quantity: has more than 3 places'
    """


def in_decimal_context[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Run a function inside the decimal context of the engine.

    Args:
        function (Callable[P, R]): The function to run.

    Returns:
        Callable[P, R]: The function, entering the context on a call made outside it.

    Examples:
        >>> @in_decimal_context
        ... def third() -> Decimal:
        ...     return Decimal(1) / 3
        >>> len(str(third()))
        52
    """

    @wraps(function)
    def run_in_context(*args: P.args, **kwargs: P.kwargs) -> R:
        if is_engine_context():
            return function(*args, **kwargs)
        with localcontext(CONTEXT):
            return function(*args, **kwargs)

    return run_in_context


def is_engine_context() -> bool:
    """Tell whether the current decimal context computes as the context of the engine.

    Returns:
        bool: True when precision, rounding, exponents, clamping and traps are those
            of the engine.

    Examples:
        >>> is_engine_context()
        False
        >>> with localcontext(CONTEXT):
        ...     is_engine_context()
        True
    """
    current = getcontext()
    return (
        current.prec == CONTEXT.prec
        and current.rounding == CONTEXT.rounding
        and current.Emin == CONTEXT.Emin
        and current.Emax == CONTEXT.Emax
        and current.clamp == CONTEXT.clamp
        and current.traps == CONTEXT.traps
    )


def round_to(value: Decimal, places: int, rounding: str = ROUND_HALF_EVEN) -> Decimal:
    """Round a decimal to a number of places.

    Args:
        value (Decimal): The value.
        places (int): Places after the point.
        rounding (str, optional): A rounding mode of `decimal`, half to even when not
            given.

    Returns:
        Decimal: The value with exactly `places` places.

    Examples:
        >>> round_to(Decimal("0.58359"), 4)
        Decimal('0.5836')
        >>> from decimal import ROUND_FLOOR
        >>> round_to(Decimal("0.58359"), 4, ROUND_FLOOR)
        Decimal('0.5835')
    """
    return value.quantize(Decimal(1).scaleb(-places), rounding=rounding)
