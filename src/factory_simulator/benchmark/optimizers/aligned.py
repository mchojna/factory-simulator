"""The aligned optimizer: the profit program over a window of known orders.

Examples:
    >>> optimizer = aligned_optimizer(lambda period, decisions: [])
    >>> optimizer.relaxed_program_value is None
    True
"""

from factory_simulator.benchmark.client import Check
from factory_simulator.benchmark.program.decisions import Optimizer
from factory_simulator.benchmark.program.expected_source import (
    LEAN_TERMINAL_VALUE_FACTOR,
    expected_planning_source,
)
from factory_simulator.benchmark.program.solve import TIME_LIMIT


def aligned_optimizer(check: Check, time_limit: float = TIME_LIMIT) -> Optimizer:
    """Give the aligned optimizer: the program over a window, with known orders.

    Args:
        check (Callable[[int, list[dict[str, Any]]], list[dict[str, Any]]]): The
            function that gives the outcomes of decisions of a period of its run.
        time_limit (float, optional): Seconds every solve of a period may take.

    Returns:
        Optimizer: A new optimizer with window `lead_chain`, demand `order_book` and the
            terminal value factor `LEAN_TERMINAL_VALUE_FACTOR`, 1.01.

    Examples:
        >>> optimizer = aligned_optimizer(lambda period, decisions: [], 60.0)
        >>> optimizer.time_limit
        60.0
    """
    return Optimizer(
        planning_source=expected_planning_source(
            "lead_chain", "order_book", LEAN_TERMINAL_VALUE_FACTOR
        ),
        check=check,
        time_limit=time_limit,
    )
