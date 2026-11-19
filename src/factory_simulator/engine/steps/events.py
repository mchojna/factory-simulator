"""The events of a period: payments, disruptions, breakdowns and new orders.

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
    >>> apply_events(replace(build_state(world), period=1), world).customer_orders
    ()
"""

from dataclasses import replace
from decimal import ROUND_FLOOR, Decimal
from types import MappingProxyType

from factory_simulator.engine.changes import ZERO_QUANTITY, Ledger, add_events
from factory_simulator.engine.models.state import CustomerOrder, Receivable, State
from factory_simulator.engine.models.world import World
from factory_simulator.engine.numbers import round_to
from factory_simulator.engine.rules.demand import demand_factor
from factory_simulator.engine.rules.disruptions import disruption_factor, is_active
from factory_simulator.engine.rules.targets import targets_of


def apply_events(state: State, world: World) -> State:
    """Apply the events of a period: payments, disruptions, breakdowns and orders.

    Payments are collected, disruptions reported, lines broken down and customer
    orders created.

    A disruption that starts or ends acting in the period is reported. A line that
    breaks down in the period loses its drawn share of condition. Every customer
    product, in order of customer identifier, then product identifier, creates an
    order when its demand of the period is above 0.

    Args:
        state (State): The state.
        world (World): The world.

    Returns:
        State: The state with the payments, the breakdowns, the new customer orders
            and their events.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ...     Factory,
        ...     Material,
        ...     Product,
        ...     Scenario,
        ...     Warehouse,
        ...     build_state,
        ...     draw_world,
        ... )
        >>> zero, one = Decimal(0), Decimal(1)
        >>> stored = {"space": one, "storage_cost": zero, "salvage_value": zero}
        >>> terms = CustomerProduct(
        ...     price=Decimal(5),
        ...     transport_cost=zero,
        ...     demand=Decimal(10),
        ...     lead_time=1,
        ...     patience=2,
        ...     late_penalty=zero,
        ...     lost_sale_penalty=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": Material(**stored)},
        ...     components={},
        ...     products={"bolt": Product(**stored, recipes={"r": {"steel": one}})},
        ...     suppliers={},
        ...     customers={"shop": Customer(products={"bolt": terms})},
        ...     lines={},
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
        >>> apply_events(state, world).customer_orders[0].quantity
        Decimal('10.000')
    """
    state = receive_payments(state)
    state = report_disruptions(state, world)
    state = break_down_lines(state, world)
    period = state.period
    new_orders: list[CustomerOrder] = []
    for customer_id in sorted(world.factory.customers):
        for product_id in sorted(world.factory.customers[customer_id].products):
            base = world.demand[f"{customer_id}/{product_id}"][period - 1]
            shape = demand_factor(
                customer_id, product_id, period, world.scenario, world.factory
            )
            shock = disruption_factor("demand_shock", product_id, period, world)
            demand = round_to(base * shape * shock, 3)
            if demand <= 0:
                continue
            path = f"customers.{customer_id}.products.{product_id}"
            lead_time = int(world.parameters[f"{path}.lead_time"])
            order_id = f"order-{period}-{len(new_orders) + 1}"
            new_orders.append(
                build_customer_order(
                    order_id,
                    customer_id,
                    product_id,
                    demand,
                    period,
                    period + lead_time,
                    world,
                )
            )
    state = replace(state, customer_orders=(*state.customer_orders, *new_orders))
    ledger = Ledger(period, "apply_events", state.cash, list(state.ledger))
    for order in new_orders:
        ledger.add_event(
            "customer_order",
            order.id,
            {
                "customer": order.customer,
                "product": order.product,
                "quantity": order.quantity,
                "due": order.due,
                "last": order.last,
            },
        )
    return add_events(state, ledger.events)


def receive_payments(state: State) -> State:
    """Receive every receivable whose payment period is the period.

    Args:
        state (State): The state.

    Returns:
        State: The state with the payments in cash and the paid receivables gone.

    Examples:
        >>> paid = Receivable(
        ...     shipment="ship-1-1",
        ...     customer="shop",
        ...     amount=Decimal(50),
        ...     payment_period=2,
        ... )
        >>> state = State(
        ...     period=2,
        ...     cash=Decimal(0),
        ...     stock={},
        ...     condition={},
        ...     customer_orders=(),
        ...     receivables=(paid,),
        ... )
        >>> receive_payments(state).cash
        Decimal('50')
    """
    ledger = Ledger(state.period, "apply_events", state.cash, list(state.ledger))
    unpaid: list[Receivable] = []
    for receivable in state.receivables:
        if receivable.payment_period != state.period:
            unpaid.append(receivable)
            continue
        amount = receivable.amount
        ledger.book(
            "customer_payment",
            amount,
            receivable.shipment,
            "customer_payment",
            {"amount": amount},
        )
    state = add_events(state, ledger.events)
    return replace(
        state,
        cash=ledger.cash,
        receivables=tuple(unpaid),
        ledger=tuple(ledger.rows),
    )


def report_disruptions(state: State, world: World) -> State:
    """Report every disruption that starts or ends acting in the period.

    A line breakdown is reported by its breakdown event instead.

    Args:
        state (State): The state.
        world (World): The world.

    Returns:
        State: The state with a `disruption_started` or `disruption_ended` event per
            such disruption, written in scenario order, then drawn.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Disruption,
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
        >>> cut = Disruption(
        ...     id="disruption-1",
        ...     kind="capacity_cut",
        ...     target=("press",),
        ...     start=1,
        ...     duration=1,
        ...     effect=Decimal("0.5"),
        ... )
        >>> scenario = Scenario(horizon=2, disruptions=(cut,))
        >>> world = draw_world(factory, scenario, seed=0)
        >>> state = replace(build_state(world), period=1)
        >>> report_disruptions(state, world).events[0]["kind"]
        'disruption_started'
    """
    ledger = Ledger(state.period, "apply_events", state.cash, list(state.ledger))
    for disruption in world.disruptions:
        if disruption.kind == "line_breakdown":
            continue
        acts_now = is_active(disruption, state.period)
        acted_before = is_active(disruption, state.period - 1)
        if acts_now and not acted_before:
            kind = "disruption_started"
        elif acted_before and not acts_now:
            kind = "disruption_ended"
        else:
            continue
        ledger.add_event(
            kind,
            disruption.id,
            {"disruption": disruption.kind, "target": targets_of(disruption, world)},
        )
    return add_events(state, ledger.events)


def break_down_lines(state: State, world: World) -> State:
    """Break down lines: multiply the condition of each that breaks by `1 - loss`.

    Written line breakdowns acting in the period come first, by line, then by their
    position in the scenario; then random ones, by name and target; then breakdowns
    drawn from `breakdown_chance`, by line.

    Args:
        state (State): The state.
        world (World): The world.

    Returns:
        State: The state with the new conditions and a `breakdown` event per
            breakdown.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Disruption,
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
        >>> breakdown = Disruption(
        ...     id="disruption-1",
        ...     kind="line_breakdown",
        ...     target=("press",),
        ...     start=1,
        ...     duration=1,
        ...     effect=Decimal("0.25"),
        ... )
        >>> scenario = Scenario(horizon=2, disruptions=(breakdown,))
        >>> world = draw_world(factory, scenario, seed=0)
        >>> state = replace(build_state(world), period=1)
        >>> break_down_lines(state, world).condition["press"]
        Decimal('0.750000000000')
    """
    condition = dict(state.condition)
    ledger = Ledger(state.period, "apply_events", state.cash, list(state.ledger))

    def break_down(line_id: str, loss: Decimal, reference: str) -> None:
        condition[line_id] = round_to(condition[line_id] * (1 - loss), 12, ROUND_FLOOR)
        ledger.add_event(
            "breakdown",
            reference,
            {"line": line_id, "loss": loss, "condition": condition[line_id]},
        )

    acting = [
        disruption
        for disruption in world.disruptions
        if disruption.kind == "line_breakdown" and is_active(disruption, state.period)
    ]
    written = [
        disruption for disruption in acting if disruption in world.scenario.disruptions
    ]
    for line_id in sorted(condition):
        for disruption in written:
            if line_id in targets_of(disruption, world):
                break_down(line_id, disruption.effect, disruption.id)
    for disruption in acting:
        if disruption not in written:
            for line_id in targets_of(disruption, world):
                break_down(line_id, disruption.effect, disruption.id)
    for line_id in sorted(condition):
        breakdown = world.breakdowns[line_id][state.period - 1]
        if breakdown.breaks:
            break_down(line_id, breakdown.loss, line_id)
    state = replace(state, condition=MappingProxyType(condition))
    return add_events(state, ledger.events)


def build_customer_order(
    order_id: str,
    customer_id: str,
    product_id: str,
    quantity: Decimal,
    arrival: int,
    due: int,
    world: World,
) -> CustomerOrder:
    """Build a customer order with the patience of its customer product.

    Args:
        order_id (str): The identifier of the order.
        customer_id (str): The identifier of the customer.
        product_id (str): The identifier of the product.
        quantity (Decimal): Units ordered.
        arrival (int): The period the order arrived.
        due (int): The due period.
        world (World): The world.

    Returns:
        CustomerOrder: The open order, nothing shipped.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ...     Factory,
        ...     Material,
        ...     Product,
        ...     Scenario,
        ...     Warehouse,
        ...     draw_world,
        ... )
        >>> zero, one = Decimal(0), Decimal(1)
        >>> stored = {"space": one, "storage_cost": zero, "salvage_value": zero}
        >>> terms = CustomerProduct(
        ...     price=Decimal(5),
        ...     transport_cost=zero,
        ...     demand=Decimal(10),
        ...     lead_time=1,
        ...     patience=2,
        ...     late_penalty=zero,
        ...     lost_sale_penalty=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": Material(**stored)},
        ...     components={},
        ...     products={"bolt": Product(**stored, recipes={"r": {"steel": one}})},
        ...     suppliers={},
        ...     customers={"shop": Customer(products={"bolt": terms})},
        ...     lines={},
        ...     warehouses={"main": Warehouse(capacity=Decimal(1000))},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), seed=0)
        >>> order = build_customer_order(
        ...     "order-1-1", "shop", "bolt", Decimal(10), 1, 2, world
        ... )
        >>> order.last
        4
    """
    path = f"customers.{customer_id}.products.{product_id}"
    patience = world.parameters[f"{path}.patience"]
    return CustomerOrder(
        id=order_id,
        customer=customer_id,
        product=product_id,
        quantity=quantity,
        shipped=ZERO_QUANTITY,
        arrival=arrival,
        due=due,
        last=due + int(patience),
    )
