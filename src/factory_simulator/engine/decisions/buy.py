"""The decision buy: checks, reasons and execution.

Examples:
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
    >>> committed(plant)
    Decimal('0')
"""

from dataclasses import replace
from decimal import ROUND_FLOOR, Decimal
from functools import partial

from factory_simulator.engine.changes import Ledger
from factory_simulator.engine.decisions.plant import Plant, space_held
from factory_simulator.engine.models.decisions import Buy
from factory_simulator.engine.models.state import Outcome, SupplierOrder
from factory_simulator.engine.models.world import World
from factory_simulator.engine.numbers import round_to
from factory_simulator.engine.rules.disruptions import (
    disruption_factor,
    remaining_share,
    transport_delay,
)
from factory_simulator.engine.rules.items import (
    default_warehouse,
    is_accepted,
    space_of,
)
from factory_simulator.engine.rules.suppliers import (
    catalogue_price,
    delivery_outcome,
    lead_time_used,
)


def execute_buy(
    decision: Buy, decision_id: str, plant: Plant, ledger: Ledger, world: World
) -> Outcome:
    """Execute a buy decision that passes its checks: place its supplier order.

    Args:
        decision (Buy): The decision.
        decision_id (str): Its identifier, `<period>-<n>`.
        plant (Plant): Stock, production and supplier orders, changed in place.
        ledger (Ledger): The ledger of the step, with the cash at the moment of the
            check.
        world (World): The world.

    Returns:
        Outcome: The outcome of the decision.

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
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
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
        >>> buy = Buy(
        ...     kind="buy",
        ...     supplier="mill",
        ...     material="steel",
        ...     quantity=Decimal(5),
        ...     express=False,
        ... )
        >>> ledger = Ledger(period=1, step="execute_decisions", cash=zero, rows=[])
        >>> execute_buy(buy, "1-1", plant, ledger, world).reason
        'unknown_supplier'
    """
    period = plant.period
    warehouse = decision.warehouse or default_warehouse(world.factory)
    decision = replace(decision, warehouse=warehouse)
    rejected = partial(
        Outcome, decision_id=decision_id, decision=decision, accepted=False
    )
    supplier = world.factory.suppliers.get(decision.supplier)
    if supplier is None:
        return rejected(reason="unknown_supplier")
    if decision.material not in supplier.catalogue:
        return rejected(reason="not_in_catalogue")
    if warehouse is None or warehouse not in world.factory.warehouses:
        return rejected(reason="unknown_warehouse")
    if not is_accepted(warehouse, decision.material, world.factory):
        return rejected(reason="not_accepted", item=decision.material)
    path = f"suppliers.{decision.supplier}.catalogue.{decision.material}"
    if decision.express and f"{path}.express_lead_time" not in world.parameters:
        return rejected(reason="no_express")
    min_quantity = world.parameters.get(f"{path}.min_quantity")
    if min_quantity is not None and decision.quantity < min_quantity:
        return rejected(
            reason="below_min_quantity",
            asked=decision.quantity,
            available=min_quantity,
        )
    shortage = remaining_share("material_shortage", decision.material, period, world)
    limit = round_to(
        world.parameters[f"{path}.max_quantity"] * shortage, 3, ROUND_FLOOR
    )
    ordered = sum(
        (
            order.quantity
            for order in plant.supplier_orders
            if order.placed == period
            and order.supplier == decision.supplier
            and order.material == decision.material
        ),
        Decimal(0),
    )
    if decision.quantity > limit - ordered:
        return rejected(
            reason="over_max_quantity",
            asked=decision.quantity,
            available=limit - ordered,
        )
    before = space_held(warehouse, plant, world)
    added = decision.quantity * space_of(decision.material, world)
    capacity = world.factory.warehouses[warehouse].capacity
    if before + added > capacity:
        return rejected(
            reason="not_enough_space", asked=added, available=capacity - before
        )
    tier = tier_of(decision, world)
    price = (
        catalogue_price(decision.supplier, decision.material, period, world)
        if tier is None
        else world.parameters[f"{path}.discounts.{tier}.price"]
    )
    unit_price = round_to(
        price * disruption_factor("price_change", decision.material, period, world), 4
    )
    if decision.express:
        unit_price += world.parameters[f"{path}.express_cost"]
    cost = decision.quantity * unit_price
    available = ledger.cash + world.factory.cash.credit_limit - committed(plant)
    if cost > available:
        return rejected(
            reason="over_credit_limit",
            asked=cost,
            available=available,
        )
    reference = "buy-" + decision_id
    plant.supplier_orders.append(
        SupplierOrder(
            id=reference,
            supplier=decision.supplier,
            material=decision.material,
            warehouse=warehouse,
            quantity=decision.quantity,
            open_quantity=decision.quantity,
            unit_price=unit_price,
            express=decision.express,
            placed=period,
            arrival=arrival_of(decision, period, world),
            tier=tier,
        )
    )
    return Outcome(
        decision_id=decision_id, decision=decision, accepted=True, reference=reference
    )


def committed(plant: Plant) -> Decimal:
    """Give what the open supplier orders still owe when all of them arrive.

    Args:
        plant (Plant): The open supplier orders.

    Returns:
        Decimal: The sum of `open_quantity * unit_price` over the open orders.

    Examples:
        >>> order = SupplierOrder(
        ...     id="buy-0-1",
        ...     supplier="mill",
        ...     material="steel",
        ...     warehouse="main",
        ...     quantity=Decimal(200),
        ...     open_quantity=Decimal(200),
        ...     unit_price=Decimal(2),
        ...     express=False,
        ...     placed=0,
        ...     arrival=3,
        ... )
        >>> plant = Plant(
        ...     period=1,
        ...     stock={},
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
        ...     supplier_orders=[order],
        ...     transfers=[],
        ... )
        >>> committed(plant)
        Decimal('400')
    """
    return sum(
        (order.open_quantity * order.unit_price for order in plant.supplier_orders),
        Decimal(0),
    )


def tier_of(decision: Buy, world: World) -> Decimal | None:
    """Give the discount tier a buy is priced at.

    Args:
        decision (Buy): The decision.
        world (World): The world.

    Returns:
        Decimal | None: The `from` of the highest tier with `from <= quantity`, or
            None below every tier.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     CatalogueEntry,
        ...     DiscountTier,
        ...     Factory,
        ...     Scenario,
        ...     Supplier,
        ... )
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> tier = DiscountTier(from_=Decimal(100), price=Decimal("1.8"))
        >>> entry = CatalogueEntry(
        ...     price=zero,
        ...     lead_time=1,
        ...     max_quantity=zero,
        ...     punctuality=zero,
        ...     delay=0,
        ...     completeness=zero,
        ...     acceptance=zero,
        ...     discounts=(tier,),
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={"mill": Supplier(catalogue={"steel": entry})},
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
        >>> buy = Buy(
        ...     kind="buy",
        ...     supplier="mill",
        ...     material="steel",
        ...     quantity=Decimal(150),
        ...     express=False,
        ... )
        >>> tier_of(buy, world)
        Decimal('100')
    """
    entry = world.factory.suppliers[decision.supplier].catalogue[decision.material]
    reached = [
        tier.from_ for tier in entry.discounts if tier.from_ <= decision.quantity
    ]
    return max(reached, default=None)


def arrival_of(decision: Buy, period: int, world: World) -> int:
    """Give the arrival period of an order placed in a period.

    Args:
        decision (Buy): The decision.
        period (int): The placing period.
        world (World): The world.

    Returns:
        int: `period` plus the lead time used, plus `delay` when the outcome of its
            kind of order is not punctual, plus the delays of the transport delays
            active in that period.

    Examples:
        >>> from factory_simulator.engine import Cash, Delivery, Factory, Scenario
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
        >>> late = Delivery(
        ...     period=1,
        ...     punctual=False,
        ...     delay=1,
        ...     completeness=Decimal(1),
        ...     acceptance=Decimal(1),
        ... )
        >>> lead_time = {"suppliers.mill.catalogue.steel.lead_time": Decimal(2)}
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters=lead_time,
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={"mill/steel": (late,)},
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
        >>> arrival_of(buy, 1, world)
        4
    """
    delivery = delivery_outcome(decision, period, world)
    late = 0 if delivery.punctual else delivery.delay
    arrival = period + lead_time_used(decision, world) + late
    return arrival + transport_delay(decision.supplier, arrival, world)
