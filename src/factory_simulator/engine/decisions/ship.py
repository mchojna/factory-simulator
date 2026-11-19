"""The decision ship: checks, reasons and execution.

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
    >>> plant = Plant(
    ...     period=1,
    ...     stock={"main": {}},
    ...     customer_orders={},
    ...     receivables=[],
    ...     condition={},
    ...     set_for={},
    ...     hours={},
    ...     changeover_hours={},
    ...     overtime_hours={},
    ...     repair_hours={},
    ...     repairs={},
    ...     production=[],
    ...     plans=[],
    ...     supplier_orders=[],
    ...     transfers=[],
    ... )
    >>> ledger = Ledger(period=1, step="execute_decisions", cash=Decimal(0), rows=[])
    >>> ship = Ship(kind="ship", order="order-1-1", quantity=Decimal(4))
    >>> execute_ship(ship, "1-1", plant, ledger, world).reason
    'unknown_order'
"""

from dataclasses import replace
from decimal import Decimal
from functools import partial

from factory_simulator.engine.changes import Ledger
from factory_simulator.engine.decisions.plant import Plant
from factory_simulator.engine.models.decisions import Ship
from factory_simulator.engine.models.state import Outcome, Receivable
from factory_simulator.engine.models.world import World
from factory_simulator.engine.rules.items import default_warehouse


def execute_ship(
    decision: Ship, decision_id: str, plant: Plant, ledger: Ledger, world: World
) -> Outcome:
    """Execute a ship decision that passes its checks: ship its units.

    Args:
        decision (Ship): The decision.
        decision_id (str): Its identifier, `<period>-<n>`.
        plant (Plant): Stock, open customer orders and receivables, changed in place.
        ledger (Ledger): The ledger of the step, changed in place.
        world (World): The world.

    Returns:
        Outcome: The outcome of the decision.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     CustomerOrder,
        ...     Factory,
        ...     Scenario,
        ...     Warehouse,
        ... )
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
        ...     warehouses={"main": Warehouse(capacity=zero)},
        ...     cash=cash,
        ... )
        >>> path = "customers.shop.products.bolt"
        >>> parameters = {
        ...     f"{path}.price": Decimal(5),
        ...     f"{path}.transport_cost": Decimal(1),
        ...     "customers.shop.payment_terms": zero,
        ... }
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters=parameters,
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> order = CustomerOrder(
        ...     id="order-1-1",
        ...     customer="shop",
        ...     product="bolt",
        ...     quantity=Decimal(4),
        ...     shipped=zero,
        ...     arrival=1,
        ...     due=2,
        ...     last=3,
        ... )
        >>> ledger = Ledger(period=1, step="execute_decisions", cash=zero, rows=[])
        >>> ship = Ship(kind="ship", order="order-1-1", quantity=Decimal(4))
        >>> plant = Plant(
        ...     period=1,
        ...     stock={"main": {"bolt": Decimal(10)}},
        ...     customer_orders={"order-1-1": order},
        ...     receivables=[],
        ...     condition={},
        ...     set_for={},
        ...     hours={},
        ...     changeover_hours={},
        ...     overtime_hours={},
        ...     repair_hours={},
        ...     repairs={},
        ...     production=[],
        ...     plans=[],
        ...     supplier_orders=[],
        ...     transfers=[],
        ... )
        >>> _ = execute_ship(ship, "1-1", plant, ledger, world)
        >>> ledger.cash
        Decimal('16.0000')
    """
    warehouse = decision.warehouse or default_warehouse(world.factory)
    decision = replace(decision, warehouse=warehouse)
    rejected = partial(
        Outcome, decision_id=decision_id, decision=decision, accepted=False
    )
    orders = plant.customer_orders
    order = orders.get(decision.order)
    if order is None:
        return rejected(reason="unknown_order")
    if warehouse is None or warehouse not in world.factory.warehouses:
        return rejected(reason="unknown_warehouse")
    quantity = decision.quantity
    open_quantity = order.quantity - order.shipped
    if quantity > open_quantity:
        return rejected(
            reason="over_open_quantity", asked=quantity, available=open_quantity
        )
    stock = plant.stock[warehouse]
    in_stock = stock.get(order.product, Decimal(0))
    if quantity > in_stock:
        return rejected(reason="not_enough_stock", asked=quantity, available=in_stock)
    stock[order.product] = in_stock - quantity
    if quantity == open_quantity:
        del orders[order.id]
    else:
        orders[order.id] = replace(order, shipped=order.shipped + quantity)
    reference = "ship-" + decision_id
    path = f"customers.{order.customer}.products.{order.product}"
    price = world.parameters[f"{path}.price"]
    transport_cost = (
        world.parameters[f"{path}.transport_cost"]
        * world.factory.warehouses[warehouse].transport_factor
    )
    terms = int(world.parameters[f"customers.{order.customer}.payment_terms"])
    if terms == 0:
        ledger.book("customer_payment", quantity * price, reference)
    else:
        plant.receivables.append(
            Receivable(
                shipment=reference,
                customer=order.customer,
                amount=quantity * price,
                payment_period=ledger.period + terms,
            )
        )
    ledger.book("transport_cost", -quantity * transport_cost, reference)
    return Outcome(
        decision_id=decision_id, decision=decision, accepted=True, reference=reference
    )
