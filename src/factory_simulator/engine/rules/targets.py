"""The targets of disruptions, demand shapes and forecasts: what each names.

Examples:
    >>> from decimal import Decimal
    >>> from factory_simulator.engine import Cash, Scenario, draw_world
    >>> world = draw_world(
    ...     Factory(
    ...         materials={},
    ...         components={},
    ...         products={},
    ...         suppliers={},
    ...         customers={},
    ...         lines={},
    ...         warehouses={},
    ...         cash=Cash(
    ...             credit_limit=Decimal(0),
    ...             credit_interest=Decimal(0),
    ...             debit_interest=Decimal(0),
    ...             overdraft_interest=Decimal(0),
    ...         ),
    ...     ),
    ...     Scenario(horizon=4),
    ...     seed=0,
    ... )
    >>> targets_of(
    ...     Disruption(
    ...         id="cut",
    ...         kind="capacity_cut",
    ...         target=None,
    ...         start=1,
    ...         duration=1,
    ...         effect=Decimal(1),
    ...     ),
    ...     world,
    ... )
    ()
"""

from factory_simulator.engine.models.manifest import Factory
from factory_simulator.engine.models.scenario import DemandShape, Disruption, Forecast
from factory_simulator.engine.models.world import World

# The kind of identifier each kind of disruption targets.
TARGET_KINDS = {
    "supplier_outage": "suppliers",
    "material_shortage": "materials",
    "quality_drop": "suppliers",
    "transport_delay": "suppliers",
    "demand_shock": "products",
    "line_breakdown": "lines",
    "price_change": "materials",
    "capacity_cut": "lines",
    "yield_drop": "lines",
}


def targets_of(disruption: Disruption, world: World) -> tuple[str, ...]:
    """Give the sorted identifiers a disruption acts on, `all` and groups expanded.

    Args:
        disruption (Disruption): The disruption.
        world (World): The world.

    Returns:
        tuple[str, ...]: The identifiers.

    Examples:
        >>> from decimal import Decimal
        >>> from factory_simulator.engine import Cash, Scenario, Supplier
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
        ...     suppliers={"mill": Supplier(catalogue={})},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
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
        ... )
        >>> outage = Disruption(
        ...     id="disruption-1",
        ...     kind="supplier_outage",
        ...     target=None,
        ...     start=2,
        ...     duration=1,
        ...     effect=Decimal(1),
        ... )
        >>> targets_of(outage, world)
        ('mill',)
    """
    return targets_in(
        disruption.kind, disruption.target, disruption.group, world.factory
    )


def targets_in(
    kind: str,
    target: tuple[str, ...] | None,
    group: tuple[str, str] | None,
    factory: Factory,
) -> tuple[str, ...]:
    """Give the sorted identifiers a target names: a list, all of its kind, or a group.

    Args:
        kind (str): The kind of disruption.
        target (tuple[str, ...] | None): The listed identifiers; None for all or a
            group.
        group (tuple[str, str] | None): The kind and identifier of a group, or None.
        factory (Factory): The factory.

    Returns:
        tuple[str, ...]: The identifiers.

    Examples:
        >>> from decimal import Decimal
        >>> from factory_simulator.engine import Cash
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
        >>> targets_in("supplier_outage", ("west", "east"), None, factory)
        ('east', 'west')
    """
    if group is not None:
        return tuple(sorted(factory.groups[group[1]].members))
    if target is not None:
        return tuple(sorted(target))
    every: dict[str, object] = getattr(factory, TARGET_KINDS[kind])
    return tuple(sorted(every))


def is_customer_product_targeted(
    entry: DemandShape | Forecast, customer_id: str, product_id: str, factory: Factory
) -> bool:
    """Tell whether a demand shape or a forecast entry targets a customer product.

    Args:
        entry (Trend | Season | Step | Ramp | SCurve | Forecast): The shape or the
            entry.
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product.
        factory (Factory): The factory, which holds the members of groups.

    Returns:
        bool: True when it names the customer product, its customer, its product, a
            group that holds its customer or its product, or every customer product.

    Examples:
        >>> from decimal import Decimal
        >>> from factory_simulator.engine import Cash, Step
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
        >>> step = Step(customer="shop", product=None, period=3, factor=Decimal(2))
        >>> is_customer_product_targeted(step, "shop", "bolt", factory)
        True
    """
    if entry.group is not None:
        group = factory.groups[entry.group[1]]
        member = customer_id if group.member_type == "customers" else product_id
        if member not in group.members:
            return False
    return entry.customer in (None, customer_id) and entry.product in (None, product_id)
