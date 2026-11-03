"""The flows of a period: customers, costs, routes, lines, inputs, suppliers, decisions.

Examples:
    >>> state = State(
    ...     period=1, cash=Decimal(0), stock={}, condition={}, customer_orders=()
    ... )
    >>> customer_orders_created(state)
    []
"""

from decimal import Decimal
from typing import cast

from factory_simulator.engine.changes import identifier_numbers
from factory_simulator.engine.measures.closed import (
    ClosedPeriod,
    add,
    costs_by_reference,
    customer_keys,
    customer_product_keys,
    zeros,
)
from factory_simulator.engine.measures.kinds import (
    CAPACITY,
    COST_KINDS,
    CUSTOMER_FLOWS,
    DECISION_FLOWS,
    LATE_UNIT_PERIODS,
    LINE_FLOWS,
    LINE_ITEM_FLOWS,
    ORDERS_CLOSED,
    ORDERS_IN_FULL_ON_TIME,
    REGULAR_AND_CHANGEOVER_HOURS,
    SUPPLIER_FLOWS,
    WAREHOUSE_COST_KINDS,
)
from factory_simulator.engine.models.decisions import (
    Buy,
    Cancel,
    Produce,
    Repair,
    Ship,
    Transfer,
)
from factory_simulator.engine.models.state import CustomerOrder, Outcome, State
from factory_simulator.engine.rules.items import (
    inputs_of,
    is_accepted,
    items_of,
    line_warehouse,
    made_item,
)
from factory_simulator.engine.rules.suppliers import lead_time_used


def customer_orders_created(state: State) -> list[CustomerOrder]:
    """Give the customer orders created in the period, from their events.

    Args:
        state (State): The state at the close.

    Returns:
        list[CustomerOrder]: The new orders, nothing shipped.

    Examples:
        >>> event = {
        ...     "kind": "customer_order",
        ...     "reference": "order-1-1",
        ...     "customer": "shop",
        ...     "product": "bolt",
        ...     "quantity": Decimal("10.000"),
        ...     "due": 2,
        ...     "last": 3,
        ... }
        >>> state = State(
        ...     period=1,
        ...     cash=Decimal(0),
        ...     stock={},
        ...     condition={},
        ...     customer_orders=(),
        ...     period_events=(event,),
        ... )
        >>> customer_orders_created(state)[0].quantity
        Decimal('10.000')
    """
    return [
        CustomerOrder(
            id=str(event["reference"]),
            customer=str(event["customer"]),
            product=str(event["product"]),
            quantity=cast(Decimal, event["quantity"]),
            shipped=Decimal(0),
            arrival=state.period,
            due=cast(int, event["due"]),
            last=cast(int, event["last"]),
        )
        for event in state.period_events
        if event["kind"] == "customer_order"
    ]


def add_customer_flows(
    period: ClosedPeriod, shipped_on_time: dict[str, Decimal]
) -> dict[str, dict[str, Decimal]]:
    """Add the units shipped on time to `shipped_on_time` and give the flows.

    The flows are those of customers, products and customer products, and the sums
    of their ratios.

    Args:
        period (ClosedPeriod): The closed period.
        shipped_on_time (dict[str, Decimal]): Units of each order shipped by its due
            period, changed in place.

    Returns:
        dict[str, dict[str, Decimal]]: Values by name and key.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
        >>> zero = Decimal(0)
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), 0)
        >>> state = State(
        ...     period=1, cash=Decimal(-5), stock={}, condition={}, customer_orders=()
        ... )
        >>> period = ClosedPeriod(
        ...     state=state,
        ...     world=world,
        ...     customer_orders={},
        ...     supplier_orders={},
        ...     production={},
        ... )
        >>> add_customer_flows(period, {})["units_ordered"]
        {'total': Decimal('0')}
    """
    current = period.state.period
    orders = period.customer_orders
    names = (*CUSTOMER_FLOWS, LATE_UNIT_PERIODS, ORDERS_CLOSED, ORDERS_IN_FULL_ON_TIME)
    flows = {name: zeros(customer_keys(period.world)) for name in names}

    def keys_of(order_id: str) -> list[str]:
        order = orders[order_id]
        return customer_product_keys(order.customer, order.product)

    for order in orders.values():
        if order.arrival == current or (order.arrival == 0 and current == 1):
            add(flows["units_ordered"], keys_of(order.id), order.quantity)
    shipped_orders: set[str] = set()
    for _, decision in period.accepted(Ship):
        order = orders[decision.order]
        shipped_orders.add(order.id)
        keys = keys_of(order.id)
        path = f"customers.{order.customer}.products.{order.product}.price"
        price = period.world.parameters[path]
        add(flows["revenue"], keys, decision.quantity * price)
        add(flows["units_shipped"], keys, decision.quantity)
        if current <= order.due:
            add(flows["units_shipped_on_time"], keys, decision.quantity)
            shipped_on_time[order.id] = (
                shipped_on_time.get(order.id, Decimal(0)) + decision.quantity
            )
        else:
            add(flows["units_shipped_late"], keys, decision.quantity)
            add(
                flows[LATE_UNIT_PERIODS],
                keys,
                (current - order.due) * decision.quantity,
            )
    for row in period.state.ledger:
        if row.kind in ("late_penalty", "lost_sale_penalty"):
            add(flows[row.kind], keys_of(row.reference), -row.amount)
    lost = {str(event["reference"]) for event in period.events("lost_sale")}
    for event in period.events("lost_sale"):
        quantity = cast(Decimal, event["quantity"])
        add(flows["units_lost"], keys_of(str(event["reference"])), quantity)
    still_open = {order.id for order in period.state.customer_orders}
    shipped_in_full = shipped_orders - still_open - lost
    for order_id in sorted(shipped_in_full | lost):
        add(flows[ORDERS_CLOSED], keys_of(order_id), Decimal(1))
        if order_id in shipped_in_full and current <= orders[order_id].due:
            add(flows[ORDERS_IN_FULL_ON_TIME], keys_of(order_id), Decimal(1))
    for order in orders.values():
        if order.due == current:
            keys = keys_of(order.id)
            add(flows["units_past_due"], keys, order.quantity)
            on_time = shipped_on_time.get(order.id, Decimal(0))
            add(flows["units_past_due_on_time"], keys, on_time)
    return flows


def cost_flows(period: ClosedPeriod) -> dict[str, dict[str, Decimal]]:
    """Give the ledger costs, interest and the periods below the credit limit.

    Args:
        period (ClosedPeriod): The closed period.

    Returns:
        dict[str, dict[str, Decimal]]: Values by name and key.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
        >>> zero = Decimal(0)
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), 0)
        >>> state = State(
        ...     period=1, cash=Decimal(-5), stock={}, condition={}, customer_orders=()
        ... )
        >>> period = ClosedPeriod(
        ...     state=state,
        ...     world=world,
        ...     customer_orders={},
        ...     supplier_orders={},
        ...     production={},
        ... )
        >>> cost_flows(period)["periods_below_credit_limit"]
        {'total': Decimal('1')}
    """
    warehouses = [
        f"warehouses.{warehouse_id}"
        for warehouse_id in sorted(period.world.factory.warehouses)
    ]
    flows = {name: zeros(["total"]) for name in COST_KINDS}
    flows |= {name: zeros(["total", *warehouses]) for name in WAREHOUSE_COST_KINDS}
    destinations = {
        transfer.id: transfer.destination for transfer in period.state.transfers
    }
    # A shipment pays its transport at the warehouse it leaves from.
    shipped_from = {
        str(reference): str(decision.warehouse)
        for reference, decision in period.accepted(Ship)
    }
    for row in period.state.ledger:
        if row.kind in COST_KINDS:
            add(flows[row.kind], ["total"], abs(row.amount))
        if row.kind in WAREHOUSE_COST_KINDS:
            if row.reference in destinations:
                warehouse = destinations[row.reference]
            elif row.kind == "storage_cost":
                warehouse = row.reference.split("/")[0]
            else:
                warehouse = shipped_from[row.reference]
            add(flows[row.kind], ["total", f"warehouses.{warehouse}"], -row.amount)
    credit_limit = period.world.factory.cash.credit_limit
    below = Decimal(1) if period.state.cash < -credit_limit else Decimal(0)
    return flows | {"periods_below_credit_limit": {"total": below}}


def route_flows(period: ClosedPeriod) -> dict[str, dict[str, Decimal]]:
    """Give the units and the cost of transfers per route, in the period sent.

    Args:
        period (ClosedPeriod): The closed period.

    Returns:
        dict[str, dict[str, Decimal]]: Values by name and key.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
        >>> zero = Decimal(0)
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), 0)
        >>> state = State(
        ...     period=1, cash=Decimal(-5), stock={}, condition={}, customer_orders=()
        ... )
        >>> period = ClosedPeriod(
        ...     state=state,
        ...     world=world,
        ...     customer_orders={},
        ...     supplier_orders={},
        ...     production={},
        ... )
        >>> route_flows(period)
        {'units_transferred': {}, 'transfer_cost': {'total': Decimal('0')}}
    """
    routes = period.world.factory.routes
    route_keys = [
        f"routes.{source}/{destination}"
        for source in sorted(routes)
        for destination in sorted(routes[source])
    ]
    flows = {
        "units_transferred": zeros(route_keys),
        "transfer_cost": zeros(["total", *route_keys]),
    }
    costs = costs_by_reference("transfer_cost", period.state)
    for reference, decision in period.accepted(Transfer):
        key = f"routes.{decision.source}/{decision.destination}"
        add(flows["units_transferred"], [key], decision.quantity)
        cost = costs.get(str(reference), Decimal(0))
        add(flows["transfer_cost"], ["total", key], cost)
    return flows


def line_flows(period: ClosedPeriod) -> dict[str, dict[str, Decimal]]:
    """Give the flows of lines and of lines with their items.

    The hours available of each line are `regular_hours_available` of the observation
    of the period; a state closed without an observation has none.

    Args:
        period (ClosedPeriod): The closed period.

    Returns:
        dict[str, dict[str, Decimal]]: Values by name and key.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
        >>> zero = Decimal(0)
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), 0)
        >>> state = State(
        ...     period=1, cash=Decimal(-5), stock={}, condition={}, customer_orders=()
        ... )
        >>> period = ClosedPeriod(
        ...     state=state,
        ...     world=world,
        ...     customer_orders={},
        ...     supplier_orders={},
        ...     production={},
        ... )
        >>> line_flows(period)["overtime_cost"]
        {'total': Decimal('0')}
    """
    lines = period.world.factory.lines
    line_keys = [f"lines.{line_id}" for line_id in sorted(lines)]
    item_keys = [
        f"lines.{line_id}/{item_id}"
        for line_id in sorted(lines)
        for item_id in sorted(lines[line_id].items)
    ]
    flows = {name: zeros(line_keys) for name in LINE_FLOWS}
    flows |= {name: zeros(line_keys + item_keys) for name in LINE_ITEM_FLOWS}
    flows["overtime_cost"] = zeros(["total", *line_keys])
    flows["changeover_cost"] = zeros(["total", *line_keys])
    parameters = period.world.parameters
    overtime_costs = costs_by_reference("overtime_cost", period.state)
    changeover_costs = costs_by_reference("changeover_cost", period.state)
    for reference, decision in period.accepted(Produce):
        if decision.start != period.state.period:
            continue
        keys = [f"lines.{decision.line}", f"lines.{decision.line}/{decision.item}"]
        add(flows["units_started"], keys, decision.quantity)
        time = parameters[f"lines.{decision.line}.items.{decision.item}.time"]
        hours = "overtime_hours" if decision.overtime else "regular_hours"
        add(flows[hours], keys[:1], decision.quantity * time)
        cost = overtime_costs.get(str(reference), Decimal(0))
        add(flows["overtime_cost"], ["total", keys[0]], cost)
        changeover_hours = period.production[str(reference)].changeover_hours
        if changeover_hours is not None:
            add(flows["changeovers"], keys[:1], Decimal(1))
            add(flows["changeover_hours"], keys[:1], changeover_hours)
        cost = changeover_costs.get(str(reference), Decimal(0))
        add(flows["changeover_cost"], ["total", keys[0]], cost)
    for _, decision in period.accepted(Repair):
        repair_time = parameters[f"lines.{decision.line}.repair_time"]
        add(
            flows["repair_hours"],
            [f"lines.{decision.line}"],
            decision.amount * repair_time,
        )
    for event in period.events("breakdown"):
        add(flows["breakdowns"], [f"lines.{event['line']}"], Decimal(1))
    for event in period.events("production_finished"):
        production = period.production[str(event["reference"])]
        keys = [
            f"lines.{production.line}",
            f"lines.{production.line}/{production.item}",
        ]
        add(flows["units_good"], keys, cast(Decimal, event["good"]))
        add(flows["units_scrap"], keys, cast(Decimal, event["scrap"]))
    observation = period.state.observation
    if observation is not None:
        for line_id, hours in observation.lines.items():
            line_key = [f"lines.{line_id}"]
            add(flows["hours_available"], line_key, hours.regular_hours_available)
    flows[CAPACITY] = {key: parameters[f"{key}.capacity"] for key in line_keys}
    flows[REGULAR_AND_CHANGEOVER_HOURS] = {
        key: flows["regular_hours"][key] + flows["changeover_hours"][key]
        for key in line_keys
    }
    return flows


def input_flows(period: ClosedPeriod) -> dict[str, dict[str, Decimal]]:
    """Give the units of each item productions started in the period take as inputs.

    Args:
        period (ClosedPeriod): The closed period.

    Returns:
        dict[str, dict[str, Decimal]]: `units_used` by warehouse with item, 0 for every
            item a warehouse accepts.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
        >>> zero = Decimal(0)
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), 0)
        >>> state = State(
        ...     period=1, cash=zero, stock={}, condition={}, customer_orders=()
        ... )
        >>> period = ClosedPeriod(
        ...     state=state,
        ...     world=world,
        ...     customer_orders={},
        ...     supplier_orders={},
        ...     production={},
        ... )
        >>> input_flows(period)
        {'units_used': {}}
    """
    factory = period.world.factory
    keys = [
        f"warehouses.{warehouse_id}/{item_id}"
        for warehouse_id in sorted(factory.warehouses)
        for item_id in sorted(items_of(factory))
        if is_accepted(warehouse_id, item_id, factory)
    ]
    units_used = zeros(keys)
    for _, decision in period.accepted(Produce):
        if decision.start != period.state.period:
            continue
        warehouse_id = line_warehouse(decision.line, factory)
        recipe = made_item(decision.item, period.world).recipes[str(decision.recipe)]
        for input_id, used in inputs_of(decision.quantity, recipe).items():
            add(units_used, [f"warehouses.{warehouse_id}/{input_id}"], used)
    return {"units_used": units_used}


def supplier_flows(period: ClosedPeriod) -> dict[str, dict[str, Decimal]]:
    """Give the flows of suppliers with their materials.

    Args:
        period (ClosedPeriod): The closed period.

    Returns:
        dict[str, dict[str, Decimal]]: Values by name and key.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
        >>> zero = Decimal(0)
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), 0)
        >>> state = State(
        ...     period=1, cash=Decimal(-5), stock={}, condition={}, customer_orders=()
        ... )
        >>> period = ClosedPeriod(
        ...     state=state,
        ...     world=world,
        ...     customer_orders={},
        ...     supplier_orders={},
        ...     production={},
        ... )
        >>> supplier_flows(period)["cancellation_fee"]
        {'total': Decimal('0')}
    """
    suppliers = period.world.factory.suppliers
    keys = [
        f"suppliers.{supplier_id}/{material_id}"
        for supplier_id in sorted(suppliers)
        for material_id in sorted(suppliers[supplier_id].catalogue)
    ]
    flows = {name: zeros(keys) for name in SUPPLIER_FLOWS}
    flows["cancellation_fee"] = zeros(["total", *keys])
    for _, decision in period.accepted(Buy):
        key = [f"suppliers.{decision.supplier}/{decision.material}"]
        add(flows["units_ordered_from_suppliers"], key, decision.quantity)
    fees = costs_by_reference("cancellation_fee", period.state)
    for reference, decision in period.accepted(Cancel):
        if decision.order.startswith("make-"):
            continue
        order = period.supplier_orders[decision.order]
        key = [f"suppliers.{order.supplier}/{order.material}"]
        add(flows["units_cancelled"], key, cast(Decimal, decision.quantity))
        fee = fees.get(str(reference), Decimal(0))
        add(flows["cancellation_fee"], ["total", *key], fee)
    for event in period.events("delivery"):
        order = period.supplier_orders[str(event["reference"])]
        key = [f"suppliers.{order.supplier}/{order.material}"]
        arrived = cast(Decimal, event["arrived"])
        accepted = cast(Decimal, event["accepted"])
        add(flows["units_arrived"], key, arrived)
        add(flows["units_accepted"], key, accepted)
        add(flows["units_rejected_at_inspection"], key, arrived - accepted)
        add(flows["units_lost_in_delivery"], key, cast(Decimal, event["lost"]))
        if order.placed > 0:
            expected = order.placed + lead_time_used(order, period.world)
            if period.state.period > expected:
                add(flows["units_arrived_late"], key, arrived)
    return flows


def decision_flows(period: ClosedPeriod) -> dict[str, dict[str, Decimal]]:
    """Give the decisions accepted and rejected, the rejected also by reason.

    Args:
        period (ClosedPeriod): The closed period.

    Returns:
        dict[str, dict[str, Decimal]]: Values by name and key.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
        >>> zero = Decimal(0)
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> repair = Repair(kind="repair", line="press", amount=Decimal("0.5"))
        >>> outcome = Outcome(
        ...     decision_id="1-1",
        ...     decision=repair,
        ...     accepted=False,
        ...     reason="unknown_line",
        ... )
        >>> state = State(
        ...     period=1,
        ...     cash=zero,
        ...     stock={},
        ...     condition={},
        ...     customer_orders=(),
        ...     outcomes=(outcome,),
        ... )
        >>> period = ClosedPeriod(
        ...     state=state,
        ...     world=draw_world(factory, Scenario(horizon=1), 0),
        ...     customer_orders={},
        ...     supplier_orders={},
        ...     production={},
        ... )
        >>> decision_flows(period)["decisions_rejected"]
        {'total': Decimal('1'), 'reasons.unknown_line': Decimal('1')}
    """
    flows = {name: zeros(["total"]) for name in DECISION_FLOWS}
    for outcome in period.state.outcomes:
        if outcome.accepted:
            add(flows["decisions_accepted"], ["total"], Decimal(1))
        else:
            keys = ["total", f"reasons.{outcome.reason}"]
            add(flows["decisions_rejected"], keys, Decimal(1))
        plan = plan_flow(outcome, period.state.period)
        if plan is not None:
            add(flows[plan], ["total"], Decimal(1))
    return flows


def plan_flow(outcome: Outcome, period: int) -> str | None:
    """Give the name of the count of plans an outcome adds to.

    Args:
        outcome (Outcome): An outcome reported in the period.
        period (int): The period.

    Returns:
        str | None: `plans_made`, `plans_run`, `plans_rejected`, `plans_cancelled`,
            or None for an outcome of no plan.

    Examples:
        >>> plan = Produce(
        ...     kind="produce",
        ...     line="press",
        ...     item="bolt",
        ...     quantity=Decimal("5.000"),
        ...     recipe=None,
        ...     overtime=False,
        ...     start=3,
        ... )
        >>> outcome = Outcome(decision_id="1-1", decision=plan, accepted=True)
        >>> plan_flow(outcome, 1), plan_flow(outcome, 3)
        ('plans_made', 'plans_run')
    """
    decision = outcome.decision
    if isinstance(decision, Cancel):
        is_plan = outcome.accepted and decision.order.startswith("make-")
        return "plans_cancelled" if is_plan else None
    if not isinstance(decision, Produce):
        return None
    # A plan reports a second outcome in its start period, under the identifier of
    # the period it was decided in.
    decided_in, _ = identifier_numbers(outcome.decision_id)
    if decided_in < period:
        return "plans_run" if outcome.accepted else "plans_rejected"
    if outcome.accepted and decision.start != period:
        return "plans_made"
    return None
