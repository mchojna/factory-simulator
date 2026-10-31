"""The terms of supplier orders: the lead time, the delivery outcome and the price.

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
    >>> price = {"suppliers.mill.catalogue.steel.price": Decimal(2)}
    >>> world = World(
    ...     factory=factory,
    ...     scenario=Scenario(horizon=4),
    ...     parameters=price,
    ...     drawn=frozenset(),
    ...     demand={},
    ...     deliveries={},
    ...     yields={},
    ...     breakdowns={},
    ... )
    >>> catalogue_price("mill", "steel", 1, world)
    Decimal('2')
"""

from decimal import Decimal

from factory_simulator.engine.models.decisions import Buy
from factory_simulator.engine.models.state import SupplierOrder
from factory_simulator.engine.models.world import Delivery, World


def lead_time_used(order: Buy | SupplierOrder, world: World) -> int:
    """Give the lead time of an order: express or normal.

    Args:
        order (Buy | SupplierOrder): A buy decision or the order it placed.
        world (World): The world.

    Returns:
        int: `express_lead_time` for an express order, `lead_time` otherwise.

    Examples:
        >>> from decimal import Decimal
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
        >>> lead_time = {"suppliers.mill.catalogue.steel.lead_time": Decimal(3)}
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters=lead_time,
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> buy = Buy(
        ...     kind="buy",
        ...     supplier="mill",
        ...     material="steel",
        ...     quantity=Decimal(5),
        ...     express=False,
        ... )
        >>> lead_time_used(buy, world)
        3
    """
    path = f"suppliers.{order.supplier}.catalogue.{order.material}"
    key = "express_lead_time" if order.express else "lead_time"
    return int(world.parameters[f"{path}.{key}"])


def delivery_outcome(order: Buy | SupplierOrder, placed: int, world: World) -> Delivery:
    """Give the drawn delivery outcome of an order: express or normal.

    Args:
        order (Buy | SupplierOrder): A buy decision or the order it placed.
        placed (int): The placing period, from 1.
        world (World): The world.

    Returns:
        Delivery: The outcome of the express orders of its supplier, material and
            placing period for an express order, of the normal orders otherwise.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario
        >>> zero, one = Decimal(0), Decimal(1)
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
        >>> on_time = Delivery(
        ...     period=1, punctual=True, delay=1, completeness=one, acceptance=one
        ... )
        >>> late = Delivery(
        ...     period=1, punctual=False, delay=1, completeness=one, acceptance=one
        ... )
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=1),
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={"mill/steel": (on_time,)},
        ...     yields={},
        ...     breakdowns={},
        ...     express_deliveries={"mill/steel": (late,)},
        ... )
        >>> buy = Buy(
        ...     kind="buy",
        ...     supplier="mill",
        ...     material="steel",
        ...     quantity=Decimal(5),
        ...     express=True,
        ... )
        >>> delivery_outcome(buy, 1, world).punctual
        False
    """
    outcomes = world.express_deliveries if order.express else world.deliveries
    return outcomes[f"{order.supplier}/{order.material}"][placed - 1]


def catalogue_price(
    supplier_id: str, material_id: str, period: int, world: World
) -> Decimal:
    """Give the catalogue price of a material in a period, before disruptions.

    Args:
        supplier_id (str): The identifier of the supplier.
        material_id (str): The identifier of the material.
        period (int): The period, from 1.
        world (World): The world.

    Returns:
        Decimal: The price drawn for the period when the price is drawn once per
            period, the price drawn once per run otherwise.

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
        ...     scenario=Scenario(horizon=2),
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ...     prices={"mill/steel": (Decimal("2.3"), Decimal("2.56"))},
        ... )
        >>> catalogue_price("mill", "steel", 2, world)
        Decimal('2.56')
    """
    prices = world.prices.get(f"{supplier_id}/{material_id}")
    if prices is not None:
        return prices[period - 1]
    return world.parameters[f"suppliers.{supplier_id}.catalogue.{material_id}.price"]
