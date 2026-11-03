"""The decision transfer: checks, reasons and execution.

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
    >>> transfer = Transfer(
    ...     kind="transfer",
    ...     item="steel",
    ...     quantity=Decimal(5),
    ...     source="main",
    ...     destination="annex",
    ... )
    >>> execute_transfer(transfer, "1-1", plant, ledger, world).reason
    'unknown_route'
"""

from decimal import Decimal
from functools import partial

from factory_simulator.engine.changes import Ledger
from factory_simulator.engine.decisions.plant import Plant, space_held
from factory_simulator.engine.models.decisions import Transfer
from factory_simulator.engine.models.state import Outcome, TransferOnTheWay
from factory_simulator.engine.models.world import World
from factory_simulator.engine.rules.items import is_accepted, items_of, space_of


def execute_transfer(
    decision: Transfer, decision_id: str, plant: Plant, ledger: Ledger, world: World
) -> Outcome:
    """Execute a transfer decision that passes its checks: send its units on the route.

    With a lead time of 0 the units enter the destination at once and no transfer of
    the period takes them on; otherwise a transfer on the way arrives in
    `period + lead_time`.

    Args:
        decision (Transfer): The decision.
        decision_id (str): Its identifier, `<period>-<n>`.
        plant (Plant): Stock, units transferred in and transfers, changed in place.
        ledger (Ledger): The ledger of the step, changed in place.
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
        >>> ledger = Ledger(period=1, step="execute_decisions", cash=zero, rows=[])
        >>> transfer = Transfer(
        ...     kind="transfer",
        ...     item="steel",
        ...     quantity=Decimal(5),
        ...     source="main",
        ...     destination="annex",
        ... )
        >>> execute_transfer(transfer, "1-1", plant, ledger, world).reason
        'unknown_route'
    """
    rejected = partial(
        Outcome, decision_id=decision_id, decision=decision, accepted=False
    )
    factory = world.factory
    source, destination = decision.source, decision.destination
    if destination not in factory.routes.get(source, {}):
        return rejected(reason="unknown_route")
    items = items_of(factory)
    if decision.item not in items or not is_accepted(
        destination, decision.item, factory
    ):
        return rejected(reason="not_accepted", item=decision.item)
    in_stock = plant.stock[source].get(decision.item, Decimal(0))
    if decision.quantity > in_stock:
        return rejected(
            reason="not_enough_stock", asked=decision.quantity, available=in_stock
        )
    arrived_quantity = plant.transferred_in.get(source, {}).get(
        decision.item, Decimal(0)
    )
    if decision.quantity > in_stock - arrived_quantity:
        return rejected(
            reason="transferred_this_period",
            asked=decision.quantity,
            available=in_stock - arrived_quantity,
        )
    before = space_held(destination, plant, world)
    added = decision.quantity * space_of(decision.item, world)
    capacity = factory.warehouses[destination].capacity
    if before + added > capacity:
        return rejected(
            reason="not_enough_space", asked=added, available=capacity - before
        )
    reference = "transfer-" + decision_id
    path = f"routes.{source}.{destination}"
    plant.stock[source][decision.item] = in_stock - decision.quantity
    ledger.book(
        "transfer_cost",
        -decision.quantity * world.parameters[f"{path}.cost"],
        reference,
    )
    lead_time = int(world.parameters[f"{path}.lead_time"])
    if lead_time == 0:
        stock = plant.stock[destination]
        stock[decision.item] = stock.get(decision.item, Decimal(0)) + decision.quantity
        transferred_in = plant.transferred_in.setdefault(destination, {})
        transferred_in[decision.item] = (
            transferred_in.get(decision.item, Decimal(0)) + decision.quantity
        )
    else:
        plant.transfers.append(
            TransferOnTheWay(
                id=reference,
                item=decision.item,
                quantity=decision.quantity,
                source=source,
                destination=destination,
                arrival=plant.period + lead_time,
            )
        )
    return Outcome(
        decision_id=decision_id, decision=decision, accepted=True, reference=reference
    )
