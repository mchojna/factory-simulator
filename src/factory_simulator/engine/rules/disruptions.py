"""The rules of a disruption: when it acts, what it acts on, and its effect.

Examples:
    >>> cut = Disruption(
    ...     id="disruption-1",
    ...     kind="capacity_cut",
    ...     target=("press",),
    ...     start=2,
    ...     duration=3,
    ...     effect=Decimal("0.25"),
    ... )
    >>> is_active(cut, 4)
    True
"""

from decimal import Decimal

from factory_simulator.engine.models.scenario import Disruption
from factory_simulator.engine.models.world import World
from factory_simulator.engine.rules.targets import targets_of


def is_active(disruption: Disruption, period: int) -> bool:
    """Tell whether a disruption acts in a period.

    Args:
        disruption (Disruption): The disruption.
        period (int): The period.

    Returns:
        bool: True when the period is the start of a line breakdown, or, for any
            other kind, from the start to `start + duration - 1`.

    Examples:
        >>> outage = Disruption(
        ...     id="disruption-1",
        ...     kind="supplier_outage",
        ...     target=None,
        ...     start=10,
        ...     duration=3,
        ...     effect=Decimal("0.5"),
        ... )
        >>> [is_active(outage, period) for period in (9, 10, 12, 13)]
        [False, True, True, False]
    """
    if disruption.kind == "line_breakdown":
        return period == disruption.start
    return disruption.start <= period <= disruption.start + disruption.duration - 1


def is_visible(disruption: Disruption, period: int) -> bool:
    """Tell whether the agent knows of a disruption in a period.

    Args:
        disruption (Disruption): The disruption.
        period (int): The period.

    Returns:
        bool: True when the period is at least `start - notice`.

    Examples:
        >>> shock = Disruption(
        ...     id="disruption-1",
        ...     kind="demand_shock",
        ...     target=None,
        ...     start=7,
        ...     duration=1,
        ...     effect=Decimal("0.5"),
        ...     notice=2,
        ... )
        >>> [is_visible(shock, period) for period in (4, 5)]
        [False, True]
    """
    return disruption.start - disruption.notice <= period


def active_disruptions(
    kind: str, target: str, period: int, world: World
) -> list[Disruption]:
    """Give the disruptions of a kind that act on a target in a period.

    Args:
        kind (str): The kind of disruption.
        target (str): The identifier of the target.
        period (int): The period.
        world (World): The world.

    Returns:
        list[Disruption]: The disruptions, written then drawn.

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
        >>> cut = Disruption(
        ...     id="disruption-1",
        ...     kind="capacity_cut",
        ...     target=("press",),
        ...     start=2,
        ...     duration=3,
        ...     effect=Decimal("0.25"),
        ... )
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ...     disruptions=(cut,),
        ... )
        >>> active = active_disruptions("capacity_cut", "press", 3, world)
        >>> [disruption.id for disruption in active]
        ['disruption-1']
    """
    return [
        disruption
        for disruption in world.disruptions
        if disruption.kind == kind
        and is_active(disruption, period)
        and target in targets_of(disruption, world)
    ]


def remaining_share(kind: str, target: str, period: int, world: World) -> Decimal:
    """Give the product of `1 - strength` of the active disruptions of a kind.

    Args:
        kind (str): The kind of disruption, one with a strength.
        target (str): The identifier of the target.
        period (int): The period.
        world (World): The world.

    Returns:
        Decimal: The share left, 1 when none acts.

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
        >>> cut = Disruption(
        ...     id="disruption-1",
        ...     kind="capacity_cut",
        ...     target=("press",),
        ...     start=2,
        ...     duration=3,
        ...     effect=Decimal("0.25"),
        ... )
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ...     disruptions=(cut,),
        ... )
        >>> remaining_share("capacity_cut", "press", 3, world)
        Decimal('0.75')
    """
    share = Decimal(1)
    for disruption in active_disruptions(kind, target, period, world):
        share *= 1 - disruption.effect
    return share


def transport_delay(supplier_id: str, period: int, world: World) -> int:
    """Give the extra periods of the transport delays that act on a supplier.

    Args:
        supplier_id (str): The identifier of the supplier.
        period (int): The period a delivery would arrive.
        world (World): The world.

    Returns:
        int: Extra periods, 0 when none acts.

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
        >>> delay = Disruption(
        ...     id="disruption-1",
        ...     kind="transport_delay",
        ...     target=("mill",),
        ...     start=2,
        ...     duration=3,
        ...     effect=Decimal(2),
        ... )
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ...     disruptions=(delay,),
        ... )
        >>> transport_delay("mill", 3, world)
        2
    """
    return sum(
        int(disruption.effect)
        for disruption in active_disruptions(
            "transport_delay", supplier_id, period, world
        )
    )


def disruption_factor(kind: str, target: str, period: int, world: World) -> Decimal:
    """Give the product of the factors of the active disruptions of a kind.

    Args:
        kind (str): The kind of disruption, one with a factor.
        target (str): The identifier of the target.
        period (int): The period.
        world (World): The world.

    Returns:
        Decimal: The product, 1 when none acts.

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
        >>> change = Disruption(
        ...     id="disruption-1",
        ...     kind="price_change",
        ...     target=("steel",),
        ...     start=2,
        ...     duration=3,
        ...     effect=Decimal("1.5"),
        ... )
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ...     disruptions=(change,),
        ... )
        >>> disruption_factor("price_change", "steel", 3, world)
        Decimal('1.5')
    """
    factor = Decimal(1)
    for disruption in active_disruptions(kind, target, period, world):
        factor *= disruption.effect
    return factor
