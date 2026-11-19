from dataclasses import replace
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any, cast

from factories.decisions import decide, submission
from factories.strategies import RunStep
from factory_simulator.engine import (
    CONTEXT,
    Buy,
    Cancel,
    DemandShape,
    Disruption,
    Observation,
    Produce,
    Ramp,
    Repair,
    Season,
    State,
    Step,
    SupplierOrder,
    Trend,
    World,
    build_state,
    start_period,
)
from factory_simulator.engine.steps.close import close_period
from factory_simulator.engine.steps.deliveries import receive_deliveries
from factory_simulator.engine.steps.events import apply_events
from factory_simulator.engine.steps.execution import execute_decisions
from factory_simulator.engine.steps.observation import build_observation

# Every reason a decision may be refused for; only `over_credit_limit` is about cash.
REASONS = {
    "over_credit_limit",
    "unknown_order",
    "unknown_line",
    "unknown_supplier",
    "not_in_catalogue",
    "line_cannot_make_item",
    "over_open_quantity",
    "not_enough_stock",
    "transferred_this_period",
    "over_repair_limit",
    "over_full_condition",
    "not_enough_hours",
    "not_enough_input",
    "not_enough_space",
    "over_max_quantity",
    "no_express",
    "below_min_quantity",
    "below_discount_tier",
    "unknown_recipe",
    "start_outside_horizon",
    "wrong_quantity",
    "unknown_warehouse",
    "not_accepted",
    "unknown_route",
}


# The twelve kinds of cost that a profit subtracts.
COST_KINDS = (
    "material_payment",
    "production_cost",
    "transport_cost",
    "storage_cost",
    "repair_cost",
    "cancellation_fee",
    "overtime_cost",
    "changeover_cost",
    "transfer_cost",
    "interest_paid",
    "late_penalty",
    "lost_sale_penalty",
)


# Every supplier order of a run, the starting ones and those placed, by identifier.
def supplier_orders_of(world: World, steps: list[RunStep]) -> dict[str, SupplierOrder]:
    orders = {order.id: order for order in build_state(world).supplier_orders}
    for _, _, closed in steps:
        orders |= {order.id: order for order in closed.supplier_orders}
    return orders


# The observation of a period of a run with no decisions.
def observation_in(world: World, period: int) -> Observation:
    state = start_period(build_state(world), world)
    while state.period < period:
        state = start_period(decide(state, world, []), world)
    assert state.observation is not None
    return state.observation


# The warehouse a line names, or the only warehouse of the manifest.
def warehouse_of_line(world: World, line_id: str) -> str:
    return world.factory.lines[line_id].warehouse or next(
        iter(world.factory.warehouses)
    )


# The accepted produce decisions that started in the period of a closed state.
def started_produces(state: State) -> list[Produce]:
    return [
        outcome.decision
        for outcome in state.outcomes
        if outcome.accepted
        and isinstance(outcome.decision, Produce)
        and outcome.decision.start == state.period
    ]


# Every property of the rule pages that one run of the engine must hold.
def assert_every_property_of_a_run(world: World, steps: list[RunStep]) -> None:
    assert_stock_condition_and_space(world, steps)
    assert_amounts(world, steps)
    assert_hours(world, steps)
    assert_item_balances(world, steps)
    assert_customer_orders(world, steps)
    assert_supplier_orders(world, steps)
    assert_disruptions_act(world, steps)
    assert_credit_limit(world, steps)


# The events of a kind of the closed periods of a run.
def events_of_steps(steps: list[RunStep], kind: str) -> list[Any]:
    return [
        event
        for _, _, closed in steps
        for event in closed.period_events
        if event["kind"] == kind
    ]


# The reference and the decision of every accepted decision of a kind of a run.
def accepted_decisions_of_steps(steps: list[RunStep], kind: str) -> list[Any]:
    return [
        (outcome.reference, outcome.decision)
        for _, _, closed in steps
        for outcome in closed.outcomes
        if outcome.accepted and outcome.decision.kind == kind
    ]


# The kind of an item: `materials`, `components` or `products`.
def kind_of(world: World, item_id: str) -> str:
    factory = world.factory
    if item_id in factory.materials:
        return "materials"
    return "components" if item_id in factory.components else "products"


# The number of decimal places of a value, trailing zeros left out.
def places(value: Decimal) -> int:
    return max(0, -cast(int, value.normalize().as_tuple().exponent))


# No stock is below 0, every warehouse holds only what it accepts within its capacity,
# every condition lies from 0 to 1, and each observation shows the space in use.
def assert_stock_condition_and_space(world: World, steps: list[RunStep]) -> None:
    for state in every_step(world, steps):
        for warehouse_id, items in state.stock.items():
            assert all(quantity >= 0 for quantity in items.values())
            warehouse = world.factory.warehouses[warehouse_id]
            for item_id in items:
                assert kind_of(world, item_id) in warehouse.accepts or any(
                    item_id in world.factory.groups[group_id].members
                    for group_id in warehouse.accepted_groups
                )
            used, reserved = space_used(world, state, warehouse_id)
            assert used + reserved <= warehouse.capacity
        assert all(0 <= value <= 1 for value in state.condition.values())
    for decided, _, _ in steps:
        assert decided.observation is not None
        for warehouse_id, space in decided.observation.space.items():
            used, reserved = space_used(world, decided, warehouse_id)
            assert (space.used, space.reserved) == (used, reserved)


# The state after each step of every period of a run: deliveries, events, observation,
# decisions and close.
def every_step(world: World, steps: list[RunStep]) -> list[State]:
    states: list[State] = []
    state = build_state(world)
    with localcontext(CONTEXT):
        for _, decisions, closed in steps:
            state = replace(state, period=state.period + 1, ledger=(), period_events=())
            state = receive_deliveries(state, world)
            states.append(state)
            state = apply_events(state, world)
            states.append(state)
            state = build_observation(state, world)
            states.append(state)
            submitted = submission(state.period, decisions)
            state = execute_decisions(state, world, submitted)
            states.append(state)
            state = close_period(state, world)
            assert state == closed
            states.append(state)
    return states


# The space of the stock of a warehouse, and the space it holds for production not yet
# in stock, open supplier orders and transfers on the way to it.
def space_used(
    world: World, state: State, warehouse_id: str
) -> tuple[Decimal, Decimal]:
    factory = world.factory
    items = {**factory.materials, **factory.components, **factory.products}
    used = sum(
        (
            quantity * items[item_id].space
            for item_id, quantity in state.stock[warehouse_id].items()
        ),
        Decimal(0),
    )
    reserved = sum(
        (
            made.started * items[made.item].space
            for made in state.production
            if warehouse_of_line(world, made.line) == warehouse_id
        ),
        Decimal(0),
    )
    reserved += sum(
        (
            order.open_quantity * items[order.material].space
            for order in state.supplier_orders
            if order.warehouse == warehouse_id
        ),
        Decimal(0),
    )
    reserved += sum(
        (
            transfer.quantity * items[transfer.item].space
            for transfer in state.transfers
            if transfer.destination == warehouse_id
        ),
        Decimal(0),
    )
    return used, reserved


# Every cash, ledger amount and measure stays below 10**24, and cash has at most 11
# places.
def assert_amounts(_world: World, steps: list[RunStep]) -> None:
    for _, _, closed in steps:
        assert abs(closed.cash) < Decimal(10) ** 24
        assert places(closed.cash) <= 11
        assert all(abs(row.amount) < Decimal(10) ** 24 for row in closed.ledger)
        assert all(
            abs(value) < Decimal(10) ** 24
            for values in closed.measures.values()
            for value in values.values()
            if value is not None
        )


# The hours each observation shows, the hours each line uses and its utilisation follow
# the capacity, the condition and the capacity cuts of each period.
def assert_hours(world: World, steps: list[RunStep]) -> None:
    hours_so_far: dict[str, Decimal] = {}
    capacity_so_far: dict[str, Decimal] = {}
    for decided, _, closed in steps:
        period = decided.period
        assert decided.observation is not None
        used = hours_used(world, closed)
        for line_id, hours in decided.observation.lines.items():
            path = f"lines.{line_id}"
            cut = acting_factor(world, "capacity_cut", line_id, period, cut=True)
            condition = decided.condition[line_id]
            capacity = world.parameters[f"{path}.capacity"] * cut
            overtime_hours = world.parameters.get(f"{path}.overtime_hours", 0) * cut
            regular_limit = down_to_3_places(capacity * condition)
            repair_limit = down_to_3_places(capacity)
            overtime_limit = down_to_3_places(overtime_hours * condition)
            assert hours.regular_hours_available == regular_limit
            assert hours.repair_hours_available == repair_limit
            assert hours.overtime_hours_available == overtime_limit
            regular, repair, overtime = used.get(line_id, (0, 0, 0))
            changeover = closed.measures["changeover_hours"][path]
            assert changeover is not None
            assert closed.measures["regular_hours"][path] == regular
            assert closed.measures["repair_hours"][path] == repair
            assert closed.measures["overtime_hours"][path] == overtime
            assert regular + changeover <= regular_limit
            assert closed.measures["hours_available"][path] == regular_limit
            assert regular_limit <= world.parameters[f"{path}.capacity"]
            # Utilisation is the regular and changeover hours over the capacity, each
            # summed over the periods so far.
            hours_before = hours_so_far.get(path, Decimal(0))
            hours_so_far[path] = hours_before + regular + changeover
            capacity_before = capacity_so_far.get(path, Decimal(0))
            capacity_so_far[path] = (
                capacity_before + world.parameters[f"{path}.capacity"]
            )
            assert closed.measures["utilisation"][path] == share_of(
                hours_so_far[path], capacity_so_far[path]
            )
            assert regular + changeover + repair <= repair_limit
            assert overtime <= overtime_limit
            assert places(regular_limit) <= 3
            assert places(repair_limit) <= 3
            assert places(overtime_limit) <= 3
        for outcome in closed.outcomes:
            if outcome.reason == "over_max_quantity":
                assert outcome.available is not None
                assert places(outcome.available) <= 3


# A running total over another, half to even to 12 places, or None over 0.
def share_of(above: Decimal, below: Decimal) -> Decimal | None:
    if below == 0:
        return None
    with localcontext(CONTEXT):
        return (above / below).quantize(Decimal("1E-12"), rounding=ROUND_HALF_EVEN)


# The regular, repair and overtime hours that the accepted decisions of a closed period
# use on each line, changeovers left out.
def hours_used(world: World, closed: State) -> dict[str, tuple[Decimal, ...]]:
    used: dict[str, tuple[Decimal, ...]] = {}
    for outcome in closed.outcomes:
        decision = outcome.decision
        if not outcome.accepted:
            continue
        hours = [Decimal(0), Decimal(0), Decimal(0)]
        if isinstance(decision, Produce) and decision.start == closed.period:
            path = f"lines.{decision.line}.items.{decision.item}.time"
            hours[2 if decision.overtime else 0] = (
                decision.quantity * world.parameters[path]
            )
        elif isinstance(decision, Repair):
            path = f"lines.{decision.line}.repair_time"
            hours[1] = decision.amount * world.parameters[path]
        else:
            continue
        before = used.get(decision.line, (Decimal(0),) * 3)
        used[decision.line] = tuple(
            used_hours + added_hours
            for used_hours, added_hours in zip(before, hours, strict=True)
        )
    return used


# The units of each item and warehouse that came in equal those that went out or
# stayed.
def assert_item_balances(world: World, steps: list[RunStep]) -> None:
    into = stock_per_place(build_state(world))
    out = stock_per_place(steps[-1][2])
    orders = supplier_orders_of(world, steps)
    for event in events_of_steps(steps, "delivery"):
        order = orders[str(event["reference"])]
        add(into, (order.warehouse, order.material), cast(Decimal, event["accepted"]))
    lines = {
        str(reference): decision.line
        for reference, decision in accepted_decisions_of_steps(steps, "produce")
    }
    for event in events_of_steps(steps, "production_finished"):
        warehouse_id = warehouse_of_line(world, lines[str(event["reference"])])
        add(into, (warehouse_id, str(event["item"])), cast(Decimal, event["good"]))
    for _, _, closed in steps:
        for key, used in closed.measures["units_used"].items():
            if key.startswith("warehouses.") and used:
                warehouse_id, item_id = key.removeprefix("warehouses.").split("/")
                add(out, (warehouse_id, item_id), used)
    customer_orders = run_customer_orders(world, steps)
    for _, decision in accepted_decisions_of_steps(steps, "ship"):
        product = customer_orders[decision.order][1]
        add(out, (decision.warehouse, product), decision.quantity)
    for reference, decision in accepted_decisions_of_steps(steps, "transfer"):
        add(out, (decision.source, decision.item), decision.quantity)
        if all(transfer.id != reference for transfer in steps[-1][2].transfers):
            add(into, (decision.destination, decision.item), decision.quantity)

    assert into == out


# The stock of a state by warehouse and item.
def stock_per_place(state: State) -> dict[tuple[str, str], Decimal]:
    return {
        (warehouse_id, item_id): quantity
        for warehouse_id, items in state.stock.items()
        for item_id, quantity in items.items()
    }


# Add an amount to the total of a key.
def add(totals: dict[Any, Decimal], key: object, amount: Decimal) -> None:
    totals[key] = totals.get(key, Decimal(0)) + amount


# Every customer order of a run, the starting ones and those that arrive, by
# identifier: its customer, product and quantity.
def run_customer_orders(
    world: World, steps: list[RunStep]
) -> dict[str, tuple[str, str, Decimal]]:
    orders = {
        order.id: (order.customer, order.product, order.quantity)
        for order in build_state(world).customer_orders
    }
    for event in events_of_steps(steps, "customer_order"):
        orders[str(event["reference"])] = (
            str(event["customer"]),
            str(event["product"]),
            cast(Decimal, event["quantity"]),
        )
    return orders


# Every customer order is shipped, lost or still open, in its whole quantity; an order
# is lost at the end only in the last period.
def assert_customer_orders(world: World, steps: list[RunStep]) -> None:
    orders = run_customer_orders(world, steps)

    settled = dict.fromkeys(orders, Decimal(0))
    for _, decision in accepted_decisions_of_steps(steps, "ship"):
        settled[decision.order] += decision.quantity
    for event in events_of_steps(steps, "lost_sale"):
        settled[str(event["reference"])] += cast(Decimal, event["quantity"])
    horizon = world.scenario.horizon
    for _, _, closed in steps:
        for event in closed.period_events:
            if event["kind"] == "lost_sale" and event["at_end"]:
                assert closed.period == horizon
    for order in steps[-1][2].customer_orders:
        settled[order.id] += order.quantity - order.shipped

    assert settled == {order_id: order[2] for order_id, order in orders.items()}


# Every supplier order is delivered, lost, cancelled or still open, in its whole
# quantity, and each delivery has at most 3 places.
def assert_supplier_orders(world: World, steps: list[RunStep]) -> None:
    ordered = {order.id: order.quantity for order in build_state(world).supplier_orders}
    for reference, decision in accepted_decisions_of_steps(steps, "buy"):
        ordered[str(reference)] = decision.quantity
    orders = supplier_orders_of(world, steps)
    assert {order_id: order.quantity for order_id, order in orders.items()} == ordered

    settled = dict.fromkeys(ordered, Decimal(0))
    for decided, _, _ in steps:
        for event in decided.period_events:
            if event["kind"] != "delivery":
                continue
            order = orders[str(event["reference"])]
            accepted = cast(Decimal, event["accepted"])
            lost = cast(Decimal, event["lost"])
            arrived = cast(Decimal, event["arrived"])
            assert 0 <= accepted <= arrived and lost >= 0
            settled[order.id] += arrived + lost
            assert all(places(value) <= 3 for value in (accepted, arrived, lost))
            assert places(cast(Decimal, event["payment"])) <= 11
    for _, decision in accepted_decisions_of_steps(steps, "cancel"):
        if not decision.order.startswith("make-"):
            settled[decision.order] += decision.quantity
    for order in steps[-1][2].supplier_orders:
        settled[order.id] += order.open_quantity

    assert settled == ordered


# The kind of object each kind of disruption targets.
TARGET_TYPES = {
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


# The disruptions of a kind that act on a target in a period.
def acting(world: World, kind: str, target: str, period: int) -> list[Disruption]:
    found: list[Disruption] = []
    for disruption in world.disruptions:
        if disruption.kind != kind:
            continue
        if not disruption.start <= period < disruption.start + disruption.duration:
            continue
        if disruption.group is not None:
            targets = world.factory.groups[disruption.group[1]].members
        elif disruption.target is not None:
            targets = disruption.target
        else:
            targets = tuple(getattr(world.factory, TARGET_TYPES[kind]))
        if target in targets:
            found.append(disruption)
    return found


# The product of the effects of the disruptions of a kind that act on a target in a
# period, or of 1 less each effect for a cut.
def acting_factor(
    world: World, kind: str, target: str, period: int, cut: bool = False
) -> Decimal:
    result = Decimal(1)
    for disruption in acting(world, kind, target, period):
        result *= 1 - disruption.effect if cut else disruption.effect
    return result


# The product of the factors of the demand shapes that target a pair in a period, each
# by the formula of its kind.
def shape_factor_of(world: World, customer: str, product: str, period: int) -> Decimal:
    result = Decimal(1)
    with localcontext(CONTEXT):
        for shape in world.scenario.demand_shapes:
            if shape.group is not None:
                group = world.factory.groups[shape.group[1]]
                member = customer if group.member_type == "customers" else product
                if member not in group.members:
                    continue
            if shape.customer not in (None, customer):
                continue
            if shape.product not in (None, product):
                continue
            result *= factor_by_kind(shape, period)
    return result


# The factor of a demand shape in a period, by the formula of its kind.
def factor_by_kind(shape: DemandShape, period: int) -> Decimal:
    if isinstance(shape, Trend):
        return (1 + shape.rate) ** (period - 1)
    if isinstance(shape, Season):
        return shape.factors[(period - 1) // shape.period_length % len(shape.factors)]
    if isinstance(shape, Step):
        return shape.factor if period >= shape.period else Decimal(1)
    if isinstance(shape, Ramp):
        if period <= shape.first:
            return shape.from_factor
        if period >= shape.last:
            return shape.to_factor
        share = Decimal(period - shape.first) / (shape.last - shape.first)
        return shape.from_factor + (shape.to_factor - shape.from_factor) * share
    rise = shape.to_factor - shape.from_factor
    return shape.from_factor + rise / (
        1 + (-shape.steepness * (period - shape.middle)).exp()
    )


# Every disruption acts on deliveries, buys, yields, hours and demand as its kind
# says, is seen from its notice and starts in its period.
def assert_disruptions_act(world: World, steps: list[RunStep]) -> None:
    written = world.disruptions
    orders = {order.id: order for order in build_state(world).supplier_orders}
    production_starts: dict[str, tuple[str, str, int]] = {}

    for decided, _, closed in steps:
        period = decided.period
        assert_deliveries_disrupted(world, decided, orders)
        assert_buys_disrupted(world, closed)
        assert_yields_disrupted(world, closed, production_starts)
        orders |= {order.id: order for order in closed.supplier_orders}
        assert decided.observation is not None
        seen = [disruption.id for disruption in decided.observation.disruptions]
        assert seen == [
            disruption.id
            for disruption in written
            if disruption.start - disruption.notice
            <= period
            <= disruption.start + disruption.duration - 1
        ]
        for line_id, hours in decided.observation.lines.items():
            cut = acting_factor(world, "capacity_cut", line_id, period, cut=True)
            condition = decided.condition[line_id]
            capacity = world.parameters[f"lines.{line_id}.capacity"]
            overtime = world.parameters.get(f"lines.{line_id}.overtime_hours", 0)
            assert hours.regular_hours_available == down_to_3_places(
                capacity * cut * condition
            )
            assert hours.repair_hours_available == down_to_3_places(capacity * cut)
            assert hours.overtime_hours_available == down_to_3_places(
                overtime * cut * condition
            )
        for event in decided.period_events:
            if event["kind"] == "customer_order":
                customer, product = str(event["customer"]), str(event["product"])
                base = world.demand[f"{customer}/{product}"][period - 1]
                shape = shape_factor_of(world, customer, product, period)
                shock = acting_factor(world, "demand_shock", product, period)
                expected = (base * shape * shock).quantize(Decimal("0.001"))
                assert event["quantity"] == expected
        broken = {
            str(event["reference"])
            for event in decided.period_events
            if event["kind"] == "breakdown"
        }
        assert broken & {disruption.id for disruption in written} == {
            disruption.id
            for disruption in written
            if disruption.kind == "line_breakdown" and disruption.start == period
        }
        started = {
            str(event["reference"])
            for event in closed.period_events
            if event["kind"] == "disruption_started"
        }
        assert started == {
            disruption.id
            for disruption in written
            if disruption.kind != "line_breakdown" and disruption.start == period
        }


# A value rounded down to 3 places.
def down_to_3_places(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_FLOOR)


# The periods of transport delay that act on a supplier in a period.
def acting_delay(world: World, supplier: str, period: int) -> int:
    return sum(
        int(disruption.effect)
        for disruption in acting(world, "transport_delay", supplier, period)
    )


# The normal or the express deliveries of one supplier, material and warehouse placed
# in one period form a batch, and so do their backfills; each batch rounds its shares
# once, with the outcome of its kind of order.
def assert_deliveries_disrupted(
    world: World, decided: State, orders: dict[str, SupplierOrder]
) -> None:
    period = decided.period
    batches: dict[tuple[str, str, str, int, bool, bool], tuple[Decimal, ...]] = {}
    for event in decided.period_events:
        if event["kind"] != "delivery":
            continue
        order = orders[str(event["reference"])]
        ordered = cast(Decimal, event["ordered"])
        if order.placed == 0:
            assert (event["arrived"], event["accepted"]) == (ordered, ordered)
            continue
        batch = (
            order.supplier,
            order.material,
            order.warehouse,
            order.placed,
            order.express,
            cast(bool, event["backfill"]),
        )
        units, arrived, accepted = batches.get(batch, (Decimal(0),) * 3)
        batches[batch] = (
            units + ordered,
            arrived + cast(Decimal, event["arrived"]),
            accepted + cast(Decimal, event["accepted"]),
        )
    for (supplier, material, _, placed, express, backfill), totals in batches.items():
        units, arrived, accepted = totals
        outcomes = world.express_deliveries if express else world.deliveries
        delivery = outcomes[f"{supplier}/{material}"][placed - 1]
        completeness = Decimal(1) if backfill else delivery.completeness
        outage = acting_factor(world, "supplier_outage", supplier, period, cut=True)
        quality = acting_factor(world, "quality_drop", supplier, period, cut=True)
        sent = (units * completeness).quantize(Decimal("0.001"))
        assert arrived == (sent * outage).quantize(Decimal("0.001"))
        share = delivery.acceptance * quality
        assert accepted == (arrived * share).quantize(Decimal("0.001"))


# Every accepted buy stays within its largest quantity after shortages and is priced
# and arrives as its tier, price changes and delays say.
def assert_buys_disrupted(world: World, closed: State) -> None:
    period = closed.period
    placed = {order.id: order for order in closed.supplier_orders}
    bought: dict[tuple[str, str], Decimal] = {}
    for outcome in closed.outcomes:
        decision = outcome.decision
        if not isinstance(decision, Buy):
            continue
        if not outcome.accepted and outcome.reason != "over_max_quantity":
            continue
        path = f"suppliers.{decision.supplier}.catalogue.{decision.material}"
        share = acting_factor(
            world, "material_shortage", decision.material, period, cut=True
        )
        limit = down_to_3_places(world.parameters[f"{path}.max_quantity"] * share)
        pair = (decision.supplier, decision.material)
        before = bought.get(pair, Decimal(0))
        if not outcome.accepted:
            assert outcome.available == limit - before
            continue
        bought[pair] = before + decision.quantity
        assert bought[pair] <= limit
        order = placed[str(outcome.reference)]
        prices = world.prices.get(f"{order.supplier}/{order.material}")
        if order.tier is not None:
            written = world.parameters[f"{path}.discounts.{order.tier}.price"]
        elif prices is not None:
            written = prices[period - 1]
        else:
            written = world.parameters[f"{path}.price"]
        change = acting_factor(world, "price_change", decision.material, period)
        price = (written * change).quantize(Decimal("0.0001"))
        if order.express:
            price += world.parameters[f"{path}.express_cost"]
        assert order.unit_price == price
        lead_time = "express_lead_time" if order.express else "lead_time"
        outcomes = world.express_deliveries if order.express else world.deliveries
        delivery = outcomes[f"{order.supplier}/{order.material}"][period - 1]
        arrival = period + int(world.parameters[f"{path}.{lead_time}"])
        if not delivery.punctual:
            arrival += delivery.delay
        assert order.arrival == arrival + acting_delay(world, order.supplier, arrival)


# The good units of each batch of production follow the drawn yield and the yield
# drops of its start period.
def assert_yields_disrupted(
    world: World, closed: State, production_starts: dict[str, tuple[str, str, int]]
) -> None:
    for outcome in closed.outcomes:
        decision = outcome.decision
        if (
            outcome.accepted
            and isinstance(decision, Produce)
            and decision.start == closed.period
        ):
            made = (decision.line, decision.item, closed.period)
            production_starts[str(outcome.reference)] = made
    # The good units of each batch of one line, item and start period.
    batches: dict[tuple[str, str, int], tuple[Decimal, Decimal]] = {}
    for event in closed.period_events:
        if event["kind"] != "production_finished":
            continue
        made = production_starts[str(event["reference"])]
        started, good = batches.get(made, (Decimal(0), Decimal(0)))
        units = cast(Decimal, event["started"])
        batches[made] = (started + units, good + cast(Decimal, event["good"]))
    for (line_id, item_id, start), (started, good) in batches.items():
        drawn = world.yields[f"{line_id}/{item_id}"][start - 1]
        drop = acting_factor(world, "yield_drop", line_id, start, cut=True)
        assert good == (started * drawn * drop).quantize(Decimal("0.001"))


# Each buy is checked against the cash after the other decisions of the period and
# against what the open supplier orders owe after the cancels and earlier buys.
def assert_credit_limit(world: World, steps: list[RunStep]) -> None:
    limit = world.factory.cash.credit_limit
    for decided, _, closed in steps:
        assert {outcome.reason for outcome in closed.outcomes if outcome.reason} <= (
            REASONS
        )
        cash = decided.cash + sum(
            (
                row.amount
                for row in closed.ledger
                if row.period == decided.period and row.step == "execute_decisions"
            ),
            Decimal(0),
        )
        orders = {order.id: order for order in decided.supplier_orders}
        committed = sum(
            (order.open_quantity * order.unit_price for order in orders.values()),
            Decimal(0),
        )
        placed = {order.id: order for order in closed.supplier_orders}
        for outcome in closed.outcomes:
            decision = outcome.decision
            if outcome.reason == "over_credit_limit":
                assert isinstance(decision, Buy)
                assert outcome.asked is not None and outcome.available is not None
                assert outcome.available == cash + limit - committed
                assert outcome.asked > outcome.available
                assert places(outcome.asked) <= 7
                assert places(outcome.available) <= 11
            elif isinstance(decision, Cancel) and outcome.accepted:
                if decision.order in orders:
                    assert decision.quantity is not None
                    committed -= decision.quantity * orders[decision.order].unit_price
            elif isinstance(decision, Buy) and outcome.accepted:
                assert outcome.reference is not None
                order = placed[outcome.reference]
                cost = order.quantity * order.unit_price
                assert cash - committed - cost >= -limit
                committed += cost


# The events of a kind of the periods of a run, as the HTTP interface answers them.
def events_of_periods(periods: dict[str, Any], kind: str) -> list[Any]:
    return [
        event
        for period in periods["periods"]
        for step in period["steps"]
        for event in step.get("events", [])
        if event["kind"] == kind
    ]


# The accepted decisions of a kind of the periods of a run.
def accepted_decisions_of_periods(periods: dict[str, Any], kind: str) -> list[Any]:
    return [
        outcome["decision"]
        for period in periods["periods"]
        for step in period["steps"]
        for outcome in step.get("outcomes", [])
        if outcome["accepted"] and outcome["decision"]["kind"] == kind
    ]


# The ledger of the periods of a run summed by kind, the terms of its result and its
# profit by the formula of the terms: the revenue earned, less the twelve kinds of
# cost, plus the interest earned and the salvage of the stock left.
def assert_run_balances(periods: dict[str, Any], result: dict[str, Any]) -> None:
    sums: dict[str, Decimal] = {}
    for period in periods["periods"]:
        for row in period["ledger"]:
            sums[row["kind"]] = sums.get(row["kind"], Decimal(0)) + row["amount"]
    terms = result["terms"]
    assert set(terms) == {*COST_KINDS, "revenue", "interest_earned", "salvage"}
    for cost in COST_KINDS:
        assert terms[cost] == -sums.get(cost, Decimal(0)), cost
    assert terms["interest_earned"] == sums.get("interest_earned", Decimal(0))
    # Revenue is earned at a shipment and paid at once or later, as a receivable.
    paid = sums.get("customer_payment", Decimal(0))
    assert terms["revenue"] == paid + result["receivables"]
    assert result["profit"] == (
        terms["revenue"]
        - sum(terms[cost] for cost in COST_KINDS)
        + terms["interest_earned"]
        + terms["salvage"]
    )
    assert sum(sums.values(), Decimal(0)) == (
        result["cash_at_end"] - result["cash_at_start"]
    )


# The units of each item of a run of one warehouse that came in (the start, accepted
# deliveries and good production) and that went out or stayed (the stock at the end,
# the inputs of every accepted produce and every accepted ship). The two are equal.
def item_balances(
    periods: dict[str, Any],
    recipes: dict[str, dict[str, Decimal]],
    start: dict[str, Decimal],
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    end = periods["periods"][-1]["steps"][-1]["state"]
    [stock] = end["stock"].values()
    items = items_of_orders(periods)
    into = dict(start)
    out = dict(stock)
    for event in events_of_periods(periods, "delivery"):
        into[items[event["reference"]]] += event["accepted"]
    for event in events_of_periods(periods, "production_finished"):
        into[event["item"]] += event["good"]
    for decision in accepted_decisions_of_periods(periods, "produce"):
        for input_id, per_unit in recipes[decision["item"]].items():
            used = decision["quantity"] * per_unit
            out[input_id] += used.quantize(Decimal("0.001"), rounding=ROUND_CEILING)
    for decision in accepted_decisions_of_periods(periods, "ship"):
        out[items[decision["order"]]] += decision["quantity"]
    return into, out


# The item of every supplier and customer order that a closed state, an accepted buy
# or a new customer order of the run names.
def items_of_orders(periods: dict[str, Any]) -> dict[str, str]:
    items: dict[str, str] = {}
    for period in periods["periods"]:
        for step in period["steps"]:
            state = step.get("state", {})
            for order in state.get("supplier_orders", []):
                items[order["id"]] = order["material"]
            for order in state.get("customer_orders", []):
                items[order["id"]] = order["product"]
            for outcome in step.get("outcomes", []):
                if outcome["accepted"] and outcome["decision"]["kind"] == "buy":
                    items[outcome["reference"]] = outcome["decision"]["material"]
            for event in step.get("events", []):
                if event["kind"] == "customer_order":
                    items[event["reference"]] = event["product"]
    return items


# Every supplier order that a closed state of a run lists, as last listed, by
# identifier.
def listed_supplier_orders(periods: dict[str, Any]) -> dict[str, Any]:
    return {
        order["id"]: order
        for period in periods["periods"]
        for order in period["steps"][-1]["state"]["supplier_orders"]
    }
