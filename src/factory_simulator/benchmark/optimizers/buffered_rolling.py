"""The buffered rolling optimizer: the rolling optimizer that keeps a buffer of stock.

Examples:
    >>> optimizer = buffered_rolling_optimizer(lambda period, decisions: [])
    >>> optimizer.relaxed_program_value is None
    True
"""

from factory_simulator.benchmark.client import Check
from factory_simulator.benchmark.program.decisions import Optimizer
from factory_simulator.benchmark.program.expected_source import (
    BUFFERED_TERMINAL_VALUE_FACTOR,
    expected_planning_source,
)
from factory_simulator.benchmark.program.solve import TIME_LIMIT


def buffered_rolling_optimizer(
    check: Check, time_limit: float = TIME_LIMIT
) -> Optimizer:
    """Give the buffered rolling optimizer: the rolling optimizer at the factor 1.2.

    Args:
        check (Callable[[int, list[dict[str, Any]]], list[dict[str, Any]]]): The
            function that gives the outcomes of decisions of a period of its run.
        time_limit (float, optional): Seconds every solve of a period may take.

    Returns:
        Optimizer: A new optimizer with window `lead_chain`, demand `expected` and the
            terminal value factor `BUFFERED_TERMINAL_VALUE_FACTOR`, 1.2.

    Examples:
        >>> optimizer = buffered_rolling_optimizer(lambda period, decisions: [], 60.0)
        >>> optimizer.time_limit
        60.0
    """
    return Optimizer(
        planning_source=expected_planning_source(
            "lead_chain", "expected", BUFFERED_TERMINAL_VALUE_FACTOR
        ),
        check=check,
        time_limit=time_limit,
    )
