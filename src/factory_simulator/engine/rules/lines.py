"""The hours of a line: the hours available, repair hours available and overtime hours.

Examples:
    >>> from factory_simulator.engine import Cash, Factory, Scenario
    >>> cash = Cash(
    ...     credit_limit=Decimal(0),
    ...     credit_interest=Decimal(0),
    ...     debit_interest=Decimal(0),
    ...     overdraft_interest=Decimal(0),
    ... )
    >>> factory = Factory(
    ...     materials={},
    ...     components={},
    ...     products={},
    ...     suppliers={},
    ...     customers={},
    ...     lines={},
    ...     warehouses={},
    ...     cash=cash,
    ... )
    >>> world = World(
    ...     factory=factory,
    ...     scenario=Scenario(horizon=4),
    ...     parameters={"lines.press.capacity": Decimal(40)},
    ...     drawn=frozenset(),
    ...     demand={},
    ...     deliveries={},
    ...     yields={},
    ...     breakdowns={},
    ... )
    >>> line_limits("press", 1, Decimal("0.5"), world)
    (Decimal('20.000'), Decimal('40.000'))
"""

from decimal import ROUND_FLOOR, Decimal

from factory_simulator.engine.models.world import World
from factory_simulator.engine.numbers import round_to
from factory_simulator.engine.rules.disruptions import remaining_share


def line_limits(
    line_id: str, period: int, condition: Decimal, world: World
) -> tuple[Decimal, Decimal]:
    """Give the hours available and the repair hours available of a line.

    Each is rounded down to 3 places.

    Args:
        line_id (str): The identifier of the line.
        period (int): The period.
        condition (Decimal): The condition of the line.
        world (World): The world.

    Returns:
        tuple[Decimal, Decimal]: The hours available, `capacity * cut * condition`,
            and the repair hours available, `capacity * cut`, with `cut` the share
            left by the active capacity cuts.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters={"lines.press.capacity": Decimal(40)},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> line_limits("press", 1, Decimal("0.5"), world)
        (Decimal('20.000'), Decimal('40.000'))
    """
    capacity = world.parameters[f"lines.{line_id}.capacity"] * remaining_share(
        "capacity_cut", line_id, period, world
    )
    return (
        round_to(capacity * condition, 3, ROUND_FLOOR),
        round_to(capacity, 3, ROUND_FLOOR),
    )


def overtime_limit(
    line_id: str, period: int, condition: Decimal, world: World
) -> Decimal:
    """Give the overtime hours of a line, rounded down to 3 places.

    Args:
        line_id (str): The identifier of the line.
        period (int): The period.
        condition (Decimal): The condition of the line.
        world (World): The world.

    Returns:
        Decimal: `overtime_hours * cut * condition`, with `cut` the share left by the
            active capacity cuts.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters={"lines.press.overtime_hours": Decimal(8)},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> overtime_limit("press", 1, Decimal("0.5"), world)
        Decimal('4.000')
    """
    hours = world.parameters[f"lines.{line_id}.overtime_hours"] * remaining_share(
        "capacity_cut", line_id, period, world
    )
    return round_to(hours * condition, 3, ROUND_FLOOR)
