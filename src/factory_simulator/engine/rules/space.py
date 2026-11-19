"""The space in a warehouse: what stock, production, supplier orders and transfers take.

Examples:
    >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
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
    >>> stock_space({}, world)
    Decimal('0')
"""

from collections.abc import Iterable, Mapping
from decimal import Decimal

from factory_simulator.engine.models.state import (
    Production,
    SupplierOrder,
    TransferOnTheWay,
)
from factory_simulator.engine.models.world import World
from factory_simulator.engine.rules.items import line_warehouse, space_of


def stock_space(stock: Mapping[str, Decimal], world: World) -> Decimal:
    """Give the space the stock of a warehouse takes.

    Args:
        stock (Mapping[str, Decimal]): Units in stock per item.
        world (World): The world.

    Returns:
        Decimal: The sum of `quantity * space` over the items.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Material, Scenario
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> steel = Material(space=Decimal(2), storage_cost=zero, salvage_value=zero)
        >>> factory = Factory(
        ...     materials={"steel": steel},
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
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> stock_space({"steel": Decimal(5)}, world)
        Decimal('10')
    """
    return sum(
        (quantity * space_of(item_id, world) for item_id, quantity in stock.items()),
        Decimal(0),
    )


def reserved_space(
    warehouse_id: str,
    production: Iterable[Production],
    supplier_orders: Iterable[SupplierOrder],
    transfers: Iterable[TransferOnTheWay],
    world: World,
) -> Decimal:
    """Give the space a warehouse reserves for what is on its way to it.

    The space of production not yet in stock on the lines of the warehouse, of the
    open quantity of every supplier order to it and of every transfer on the way to
    it is held as if it were in stock.

    Args:
        warehouse_id (str): The identifier of the warehouse.
        production (Iterable[Production]): Production not yet in stock.
        supplier_orders (Iterable[SupplierOrder]): Open supplier orders.
        transfers (Iterable[TransferOnTheWay]): Transfers on the way.
        world (World): The world.

    Returns:
        Decimal: The space reserved.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Material, Scenario
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> steel = Material(space=Decimal(2), storage_cost=zero, salvage_value=zero)
        >>> factory = Factory(
        ...     materials={"steel": steel},
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
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> order = SupplierOrder(
        ...     id="buy-1-1",
        ...     supplier="mill",
        ...     material="steel",
        ...     warehouse="main",
        ...     quantity=Decimal(4),
        ...     open_quantity=Decimal(4),
        ...     unit_price=Decimal(2),
        ...     express=False,
        ...     placed=1,
        ...     arrival=3,
        ... )
        >>> reserved_space("main", [], [order], [], world)
        Decimal('8')
    """
    in_production = sum(
        (
            made.started * space_of(made.item, world)
            for made in production
            if line_warehouse(made.line, world.factory) == warehouse_id
        ),
        Decimal(0),
    )
    on_order = sum(
        (
            order.open_quantity * space_of(order.material, world)
            for order in supplier_orders
            if order.warehouse == warehouse_id
        ),
        Decimal(0),
    )
    on_the_way = sum(
        (
            transfer.quantity * space_of(transfer.item, world)
            for transfer in transfers
            if transfer.destination == warehouse_id
        ),
        Decimal(0),
    )
    return in_production + on_order + on_the_way
