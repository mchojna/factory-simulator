"""The informed optimizer: the rolling optimizer that knows the ranges a twin shows.

Examples:
    >>> optimizer = informed_optimizer(
    ...     lambda period, decisions: [], Decimal("1.01"), {}
    ... )
    >>> optimizer.relaxed_program_value is None
    True
"""

from decimal import Decimal

from factory_simulator.benchmark.client import Check, JsonObject
from factory_simulator.benchmark.program.decisions import Optimizer
from factory_simulator.benchmark.program.expected_source import (
    informed_planning_source,
)
from factory_simulator.benchmark.program.solve import TIME_LIMIT


def informed_optimizer(
    check: Check,
    terminal_value_factor: Decimal,
    shown_description: JsonObject,
    time_limit: float = TIME_LIMIT,
) -> Optimizer:
    """Give the informed optimizer: the rolling optimizer that plans from a twin.

    It counts every hidden range at the `cut_mean` the description of the twin shows
    and never sees a value drawn for a period. It is a diagnostic, not a limited
    optimizer.

    Args:
        check (Callable[[int, list[dict[str, Any]]], list[dict[str, Any]]]): The
            function that gives the outcomes of decisions of a period of its run.
        terminal_value_factor (Decimal): What one unit at the end of the window, up
            to its expected use, is worth, as a multiple of its replacement cost.
        shown_description (dict[str, Any]): The description of a run of the twin of its
            scenario with nothing hidden, from `create_shown_description`.
        time_limit (float, optional): Seconds every solve of a period may take.

    Returns:
        Optimizer: A new optimizer with the source of `informed_planning_source`.

    Examples:
        >>> optimizer = informed_optimizer(
        ...     lambda period, decisions: [], Decimal("1.01"), {}, 60.0
        ... )
        >>> optimizer.time_limit
        60.0
    """
    return Optimizer(
        planning_source=informed_planning_source(
            terminal_value_factor, shown_description
        ),
        check=check,
        time_limit=time_limit,
    )
