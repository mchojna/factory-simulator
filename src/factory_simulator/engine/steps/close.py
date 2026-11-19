"""The close of a period: production, wear, storage, penalties, interest and measures.

Examples:
    >>> from factory_simulator.engine import (
    ...     Cash,
    ...     Factory,
    ...     Scenario,
    ...     build_state,
    ...     draw_world,
    ... )
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
    >>> close_period(replace(build_state(world), period=4), world).finished
    True
"""

from collections.abc import Mapping
from dataclasses import replace
from decimal import ROUND_FLOOR, Decimal
from types import MappingProxyType

from factory_simulator.engine.changes import Ledger, add_events, identifier_numbers
from factory_simulator.engine.measures.period import record_measures
from factory_simulator.engine.models.manifest import read_only_copy
from factory_simulator.engine.models.state import (
    CustomerOrder,
    EventValue,
    Production,
    State,
)
from factory_simulator.engine.models.world import World
from factory_simulator.engine.money import compute_interest
from factory_simulator.engine.numbers import round_to
from factory_simulator.engine.rules.disruptions import remaining_share
from factory_simulator.engine.rules.items import item_path, line_warehouse


def close_period(state: State, world: World) -> State:
    """Close the period: finish production, wear lines, pay costs and interest.

    The costs are storage and penalties. Units on the way in a transfer pay storage at
    its destination. The run ends after the last period.

    Args:
        state (State): The state after the decisions.
        world (World): The world.

    Returns:
        State: The state at the close of the period.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Factory,
        ...     Line,
        ...     LineItem,
        ...     Material,
        ...     Product,
        ...     Scenario,
        ...     Warehouse,
        ...     build_state,
        ...     draw_world,
        ... )
        >>> zero, one = Decimal(0), Decimal(1)
        >>> stored = {"space": one, "storage_cost": zero, "salvage_value": zero}
        >>> press = Line(
        ...     capacity=Decimal(40),
        ...     wear_per_period=zero,
        ...     wear_per_hour=zero,
        ...     breakdown_chance=zero,
        ...     breakdown_loss=zero,
        ...     repair_cost=zero,
        ...     repair_time=zero,
        ...     repair_limit=one,
        ...     items={"bolt": LineItem(time=one, cost=one, yield_=one)},
        ... )
        >>> factory = Factory(
        ...     materials={"steel": Material(**stored)},
        ...     components={},
        ...     products={"bolt": Product(**stored, recipes={"r": {"steel": one}})},
        ...     suppliers={},
        ...     customers={},
        ...     lines={"press": press},
        ...     warehouses={"main": Warehouse(capacity=Decimal(1000))},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), seed=0)
        >>> state = replace(build_state(world), period=1)
        >>> close_period(state, world).finished
        True
    """
    executed = state
    period = state.period
    horizon = world.scenario.horizon
    ledger = Ledger(period, "close_period", state.cash, list(state.ledger))
    stock = {warehouse: dict(items) for warehouse, items in state.stock.items()}
    production = finish_production(state, stock, ledger, world)
    condition = wear_lines(state, world)
    for warehouse_id in sorted(stock):
        for item_id in sorted(stock[warehouse_id]):
            quantity = stock[warehouse_id][item_id]
            storage_cost = world.parameters[f"{item_path(item_id, world)}.storage_cost"]
            storage_factor = world.factory.warehouses[warehouse_id].storage_factor
            reference = f"{warehouse_id}/{item_id}"
            cost = quantity * storage_cost * storage_factor
            ledger.book(
                "storage_cost", -cost, reference, "storage_cost", {"amount": cost}
            )
    for transfer in state.transfers:
        storage_cost = world.parameters[
            f"{item_path(transfer.item, world)}.storage_cost"
        ]
        storage_factor = world.factory.warehouses[transfer.destination].storage_factor
        cost = transfer.quantity * storage_cost * storage_factor
        ledger.book(
            "storage_cost", -cost, transfer.id, "storage_cost", {"amount": cost}
        )
    open_orders: list[CustomerOrder] = []
    for order in state.customer_orders:
        path = f"customers.{order.customer}.products.{order.product}"
        missing = order.quantity - order.shipped
        # An order is lost at the close of its last period, or at the end of the run
        # once its due period has come; `at_end` marks an order the end of the run
        # loses before its last period.
        if period == order.last or (period == horizon and order.due <= period):
            penalty = missing * world.parameters[f"{path}.lost_sale_penalty"]
            book_penalty(
                order,
                missing,
                penalty,
                "lost_sale_penalty",
                "lost_sale",
                {"at_end": period < order.last},
                ledger,
            )
            continue
        if period >= order.due:
            penalty = missing * world.parameters[f"{path}.late_penalty"]
            book_penalty(
                order, missing, penalty, "late_penalty", "late_penalty", {}, ledger
            )
        open_orders.append(order)
    interest = compute_interest(ledger.cash, world.factory.cash)
    kind = "interest_earned" if interest > 0 else "interest_paid"
    ledger.book(kind, interest, "", "interest", {"amount": interest})
    state = add_events(state, ledger.events)
    closed = replace(
        state,
        cash=ledger.cash,
        stock=read_only_copy(stock),
        condition=MappingProxyType(condition),
        production=production,
        repairs=MappingProxyType({}),
        customer_orders=tuple(open_orders),
        ledger=tuple(ledger.rows),
        finished=period == horizon,
    )
    return record_measures(executed, closed, world)


def book_penalty(
    order: CustomerOrder,
    missing: Decimal,
    penalty: Decimal,
    ledger_kind: str,
    event_kind: str,
    fields: Mapping[str, EventValue],
    ledger: Ledger,
) -> None:
    """Book a penalty of a customer order.

    The event is added when units are missing, the row when the penalty is not 0.

    Args:
        order (CustomerOrder): The order.
        missing (Decimal): Units not shipped.
        penalty (Decimal): The penalty, as a positive number.
        ledger_kind (str): The kind of the ledger row.
        event_kind (str): The kind of the event.
        fields (Mapping[str, str | int | Decimal | tuple[str, ...]]): The fields
            of the event besides `quantity` and `amount`.
        ledger (Ledger): The ledger of the step, changed in place.

    Examples:
        >>> ledger = Ledger(period=3, step="close_period", cash=Decimal(100), rows=[])
        >>> order = CustomerOrder(
        ...     id="order-1-1",
        ...     customer="shop",
        ...     product="bolt",
        ...     quantity=Decimal(10),
        ...     shipped=Decimal(4),
        ...     arrival=1,
        ...     due=2,
        ...     last=4,
        ... )
        >>> book_penalty(
        ...     order,
        ...     Decimal(6),
        ...     Decimal(12),
        ...     "late_penalty",
        ...     "late_penalty",
        ...     {},
        ...     ledger,
        ... )
        >>> ledger.cash
        Decimal('88')
    """
    if missing > 0:
        ledger.add_event(
            event_kind,
            order.id,
            {"quantity": missing, "amount": penalty} | dict(fields),
        )
    ledger.book(ledger_kind, -penalty, order.id)


def finish_production(
    state: State,
    stock: dict[str, dict[str, Decimal]],
    ledger: Ledger,
    world: World,
) -> tuple[Production, ...]:
    """Finish production: put production ready in the period into stock, good units.

    The productions of one line and item started in one period form a batch, whose
    good units are rounded once.

    Args:
        state (State): The state after the decisions.
        stock (dict[str, dict[str, Decimal]]): Stock per warehouse and item, changed
            in place.
        ledger (Ledger): The ledger of the step, which gets the events, changed in
            place.
        world (World): The world.

    Returns:
        tuple[Production, ...]: The production still not in stock.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Factory,
        ...     Line,
        ...     LineItem,
        ...     Material,
        ...     Product,
        ...     Scenario,
        ...     Warehouse,
        ...     draw_world,
        ... )
        >>> zero, one = Decimal(0), Decimal(1)
        >>> stored = {"space": one, "storage_cost": zero, "salvage_value": zero}
        >>> press = Line(
        ...     capacity=Decimal(40),
        ...     wear_per_period=zero,
        ...     wear_per_hour=zero,
        ...     breakdown_chance=zero,
        ...     breakdown_loss=zero,
        ...     repair_cost=zero,
        ...     repair_time=zero,
        ...     repair_limit=one,
        ...     items={"bolt": LineItem(time=one, cost=one, yield_=one)},
        ... )
        >>> factory = Factory(
        ...     materials={"steel": Material(**stored)},
        ...     components={},
        ...     products={"bolt": Product(**stored, recipes={"r": {"steel": one}})},
        ...     suppliers={},
        ...     customers={},
        ...     lines={"press": press},
        ...     warehouses={"main": Warehouse(capacity=Decimal(1000))},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), seed=0)
        >>> made = Production(
        ...     id="make-1-1",
        ...     line="press",
        ...     item="bolt",
        ...     recipe="r",
        ...     started=Decimal(5),
        ...     start=1,
        ...     ready=1,
        ...     overtime=False,
        ... )
        >>> state = State(
        ...     period=1,
        ...     cash=zero,
        ...     stock={"main": {}},
        ...     condition={"press": one},
        ...     customer_orders=(),
        ...     production=(made,),
        ... )
        >>> stock = {"main": {}}
        >>> ledger = Ledger(period=1, step="close_period", cash=zero, rows=[])
        >>> finish_production(state, stock, ledger, world)
        ()
        >>> stock
        {'main': {'bolt': Decimal('5.000')}}
    """
    waiting: list[Production] = []
    batch_started: dict[tuple[str, str, int], Decimal] = {}
    for production in sorted(
        state.production, key=lambda production: identifier_numbers(production.id)
    ):
        if production.ready != state.period:
            waiting.append(production)
            continue
        drawn = world.yields[f"{production.line}/{production.item}"]
        drop = remaining_share("yield_drop", production.line, production.start, world)
        share = drawn[production.start - 1] * drop
        # The good units of a batch are its started units times the share, rounded
        # once. Each production gets the rise of the rounded good units of the batch
        # over the productions before it.
        batch = (production.line, production.item, production.start)
        before = batch_started.get(batch, Decimal(0))
        batch_started[batch] = before + production.started
        good = round_to(batch_started[batch] * share, 3) - round_to(before * share, 3)
        scrap = production.started - good
        warehouse = line_warehouse(production.line, world.factory)
        stock[warehouse][production.item] = (
            stock[warehouse].get(production.item, Decimal(0)) + good
        )
        ledger.add_event(
            "production_finished",
            production.id,
            {
                "item": production.item,
                "started": production.started,
                "good": good,
                "scrap": scrap,
            },
        )
    return tuple(waiting)


def wear_lines(state: State, world: World) -> dict[str, Decimal]:
    """Wear every line by the period and its production hours; add repairs.

    Args:
        state (State): The state after the decisions.
        world (World): The world.

    Returns:
        dict[str, Decimal]: The condition of each line, rounded down to 12 places.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Factory,
        ...     Line,
        ...     LineItem,
        ...     Material,
        ...     Product,
        ...     Scenario,
        ...     Warehouse,
        ...     draw_world,
        ... )
        >>> zero, one = Decimal(0), Decimal(1)
        >>> stored = {"space": one, "storage_cost": zero, "salvage_value": zero}
        >>> press = Line(
        ...     capacity=Decimal(40),
        ...     wear_per_period=zero,
        ...     wear_per_hour=zero,
        ...     breakdown_chance=zero,
        ...     breakdown_loss=zero,
        ...     repair_cost=zero,
        ...     repair_time=zero,
        ...     repair_limit=one,
        ...     items={"bolt": LineItem(time=one, cost=one, yield_=one)},
        ... )
        >>> factory = Factory(
        ...     materials={"steel": Material(**stored)},
        ...     components={},
        ...     products={"bolt": Product(**stored, recipes={"r": {"steel": one}})},
        ...     suppliers={},
        ...     customers={},
        ...     lines={"press": press},
        ...     warehouses={"main": Warehouse(capacity=Decimal(1000))},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), seed=0)
        >>> state = State(
        ...     period=1,
        ...     cash=zero,
        ...     stock={},
        ...     condition={"press": Decimal("0.5")},
        ...     customer_orders=(),
        ...     repairs={"press": Decimal("0.25")},
        ... )
        >>> wear_lines(state, world)
        {'press': Decimal('0.750000000000')}
    """
    condition: dict[str, Decimal] = {}
    for line_id in sorted(state.condition):
        path = f"lines.{line_id}"
        hours = sum(
            (
                production.started
                * world.parameters[f"{path}.items.{production.item}.time"]
                for production in state.production
                if production.line == line_id and production.start == state.period
            ),
            Decimal(0),
        )
        worn = (
            state.condition[line_id] * (1 - world.parameters[f"{path}.wear_per_period"])
            - world.parameters[f"{path}.wear_per_hour"] * hours
            + state.repairs.get(line_id, Decimal(0))
        )
        condition[line_id] = round_to(worn, 12, ROUND_FLOOR)
    return condition
