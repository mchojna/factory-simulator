import copy
from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest
from factories import (
    FactoryBodies,
    closed_periods,
    draw_world_of_bodies,
    drawn_run,
    example_count,
    seeds,
    ship,
    small_factories,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.engine import (
    LedgerRow,
    Receivable,
    State,
    World,
    build_state,
    start_period,
)
from factory_simulator.engine.steps.events import apply_events

SHIP_IN_PERIOD_3 = {3: [ship("order-0-1", "10")]}


def start(world: World, period: int) -> State:
    return start_period(replace(build_state(world), period=period - 1), world)


def two_customers_of_monitor() -> dict[str, Any]:
    manifest = tiny_manifest()
    distributor = manifest["customers"]["distributor"]
    manifest["customers"]["retailer"] = copy.deepcopy(distributor)
    manifest["customers"]["retailer"]["products"]["monitor"]["demand"] = "6.000"
    return manifest


def with_terms(terms: object) -> dict[str, Any]:
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["payment_terms"] = terms
    return manifest


def shipment_world(terms: int, orders: int = 1) -> World:
    manifest = with_terms(terms)
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0"
    scenario = tiny_scenario()
    scenario["horizon"] = 6
    scenario["start"]["stock"]["main"]["monitor"] = "20"
    scenario["start"]["customer_orders"] = [
        {"customer": "distributor", "product": "monitor", "quantity": "10", "due": 3}
        for _ in range(orders)
    ]
    return draw_world_of_bodies(manifest, scenario)


def interest_earned_after_a_shipment_in_period_1(terms: int) -> Decimal:
    world = shipment_world(terms)
    for kind in ("materials", "components", "products"):
        items = getattr(world.factory, kind)
        for item_id in items:
            world = with_parameter_at_0(world, f"{kind}.{item_id}.storage_cost")
    first = closed_periods(world, {1: [ship("order-0-1", "10")]})[0]
    return first.measures["interest_earned"]["total"] or Decimal(0)


def with_parameter_at_0(world: World, path: str) -> World:
    parameters = dict(world.parameters) | {path: Decimal(0)}
    return replace(world, parameters=MappingProxyType(parameters))


def ledger_total(rows: tuple[LedgerRow, ...], kind: str) -> Decimal:
    return sum((row.amount for row in rows if row.kind == kind), Decimal(0))


def test_breakdowns_come_written_by_line_then_random_then_drawn_from_the_chance():
    manifest = tiny_manifest()
    line = manifest["lines"].pop("line-1")
    manifest["lines"]["a-line"] = copy.deepcopy(line) | {
        "breakdown_chance": "1.0000",
        "breakdown_loss": "0.5000",
    }
    manifest["lines"]["b-line"] = copy.deepcopy(line)
    scenario = tiny_scenario()
    scenario["disruptions"] = [
        {"kind": "line_breakdown", "target": ["b-line"], "start": 3, "loss": "0.3000"},
        {"kind": "line_breakdown", "target": ["a-line"], "start": 3, "loss": "0.1000"},
    ]
    scenario["random_disruptions"] = [
        {
            "name": "trouble",
            "kind": "line_breakdown",
            "target": ["a-line"],
            "chance": "1.0000",
            "loss": "0.2000",
        }
    ]
    world = draw_world_of_bodies(manifest, scenario)

    state = start(world, 3)

    assert [
        (event["line"], event["reference"], event["loss"], event["condition"])
        for event in state.period_events
        if event["kind"] == "breakdown"
    ] == [
        ("a-line", "disruption-2", Decimal("0.1000"), Decimal("0.9")),
        ("b-line", "disruption-1", Decimal("0.3000"), Decimal("0.7")),
        ("a-line", "trouble/3/a-line", Decimal("0.2000"), Decimal("0.72")),
        ("a-line", "a-line", Decimal("0.5000"), Decimal("0.36")),
    ]


def test_11_disruptions_start_in_the_order_of_their_numbers_not_their_text():
    scenario = tiny_scenario()
    scenario["disruptions"] = [
        {
            "kind": "supplier_outage",
            "target": ["chip-maker"],
            "start": 2,
            "duration": 1,
            "strength": "0.1000",
        }
        for _ in range(11)
    ]
    world = draw_world_of_bodies(tiny_manifest(), scenario)

    state = start(world, 2)

    assert [
        event["reference"]
        for event in state.period_events
        if event["kind"] == "disruption_started"
    ] == [f"disruption-{number}" for number in range(1, 12)]


# 0.999600059996 * 0.9905 = 0.990103859426, then * 0.9983 = 0.988420682864, each
# rounded down to 12 places; the other order gives 0.988420682865.
def test_a_random_rule_named_disruption_z_breaks_down_as_a_random_rule():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"] |= {
        "wear_per_period": "0.0000",
        "wear_per_hour": "0.0000",
    }
    scenario = tiny_scenario() | {"horizon": 1}
    scenario["random_disruptions"] = [
        {
            "name": name,
            "kind": "line_breakdown",
            "target": ["line-1"],
            "start": 1,
            "loss": loss,
        }
        for name, loss in (("disruption-z", "0.0017"), ("beta", "0.0095"))
    ]
    world = draw_world_of_bodies(manifest, scenario)
    state = replace(build_state(world), condition={"line-1": Decimal("0.999600059996")})

    state = apply_events(replace(state, period=1), world)

    assert state.condition["line-1"] == Decimal("0.988420682864")


def test_starting_customer_orders_are_numbered_and_in_the_state_before_period_1():
    scenario = tiny_scenario()
    scenario["start"]["customer_orders"] = [
        {"customer": "distributor", "product": "monitor", "quantity": "7", "due": 2},
        {"customer": "distributor", "product": "monitor", "quantity": "3", "due": 1},
    ]
    world = draw_world_of_bodies(tiny_manifest(), scenario)

    state = build_state(world)

    assert state.period == 0
    assert [order.id for order in state.customer_orders] == ["order-0-1", "order-0-2"]
    first = state.customer_orders[0]
    assert (first.quantity, first.shipped) == (Decimal("7.000"), Decimal("0.000"))
    assert (first.arrival, first.due, first.last) == (0, 2, 3)


def test_new_customer_orders_are_numbered_in_pair_order():
    world = draw_world_of_bodies(two_customers_of_monitor(), tiny_scenario())

    state = start_period(build_state(world), world)

    assert state.period == 1
    orders = [
        (order.id, order.customer, order.quantity, order.arrival, order.due, order.last)
        for order in state.customer_orders
    ]
    assert orders == [
        ("order-1-1", "distributor", Decimal("4.000"), 1, 1, 2),
        ("order-1-2", "retailer", Decimal("6.000"), 1, 1, 2),
    ]


def test_demand_of_0_creates_no_customer_order():
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    world = draw_world_of_bodies(manifest, tiny_scenario())

    state = start_period(build_state(world), world)

    assert state.customer_orders == ()


def test_a_shipment_with_payment_terms_2_is_a_receivable_paid_in_period_5():
    closed = closed_periods(shipment_world(2), SHIP_IN_PERIOD_3)
    third, fourth, fifth = closed[2], closed[3], closed[4]

    shipment_rows = [
        (row.kind, row.amount) for row in third.ledger if row.reference == "ship-3-1"
    ]
    assert shipment_rows == [("transport_cost", Decimal(-10))]
    assert third.measures["revenue"]["total"] == Decimal(500)
    assert third.receivables == (
        Receivable(
            shipment="ship-3-1",
            customer="distributor",
            amount=Decimal(500),
            payment_period=5,
        ),
    )
    assert fourth.receivables == third.receivables
    paid = [(row.step, row.kind, row.amount, row.reference) for row in fifth.ledger]
    assert paid[0] == ("apply_events", "customer_payment", Decimal(500), "ship-3-1")
    assert fifth.receivables == ()


def test_profit_so_far_counts_the_open_receivable_until_it_is_paid():
    closed = closed_periods(shipment_world(2), SHIP_IN_PERIOD_3)
    # Revenue 500 and transport 10 in period 3. Storage 2.3 in periods 1 and 2, then
    # 1.3. Interest earned 0.4988, 0.4979, 0.4925, 0.4921 and 0.7417 in periods 1 to 5.
    by_period_3 = 500 - 10 - Decimal("5.9") + Decimal("1.4892")
    by_period_5 = 500 - 10 - Decimal("8.5") + Decimal("2.7230")

    third, fifth = closed[2], closed[4]
    assert third.measures["receivables"]["total"] == Decimal(500)
    assert third.measures["receivables"]["customers.distributor"] == Decimal(500)
    assert third.measures["profit_so_far"]["total"] == by_period_3
    assert fifth.measures["receivables"]["total"] == Decimal(0)
    assert fifth.measures["profit_so_far"]["total"] == by_period_5


def test_with_payment_terms_0_revenue_is_paid_before_transport_without_an_event():
    third = closed_periods(shipment_world(0), SHIP_IN_PERIOD_3)[2]

    rows = [
        (row.kind, row.amount) for row in third.ledger if row.reference == "ship-3-1"
    ]
    assert rows == [
        ("customer_payment", Decimal(500)),
        ("transport_cost", Decimal(-10)),
    ]
    assert all(event["kind"] != "customer_payment" for event in third.period_events)
    assert third.receivables == ()


def test_interest_is_earned_on_the_cash_left_after_the_shipment():
    assert interest_earned_after_a_shipment_in_period_1(0) == Decimal("0.7450")
    assert interest_earned_after_a_shipment_in_period_1(2) == Decimal("0.4950")


def test_two_receivables_due_in_one_period_are_paid_in_shipment_order():
    world = shipment_world(2, orders=2)
    decisions = {3: [ship("order-0-1", "10"), ship("order-0-2", "10")]}

    fifth = closed_periods(world, decisions)[4]

    paid = [row.reference for row in fifth.ledger if row.kind == "customer_payment"]
    assert paid == ["ship-3-1", "ship-3-2"]


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_revenue_so_far_is_payments_so_far_plus_open_receivables(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    _, steps = drawn_run(factory, seed, data.draw)

    revenue = paid = Decimal(0)
    for _, _, closed in steps:
        earned = closed.measures["revenue"]["total"]
        assert earned is not None
        revenue += earned
        paid += ledger_total(closed.ledger, "customer_payment")
        open_receivables = sum(
            (receivable.amount for receivable in closed.receivables), Decimal(0)
        )
        assert revenue == paid + open_receivables


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_a_receivable_is_paid_once_in_its_payment_period_and_cash_follows_the_ledger(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world, steps = drawn_run(factory, seed, data.draw)

    due: dict[str, int] = {}
    paid: list[str] = []
    cash = world.scenario.start.cash
    for decided, _, closed in steps:
        for receivable in decided.receivables:
            due.setdefault(receivable.shipment, receivable.payment_period)
        for receivable in closed.receivables:
            due.setdefault(receivable.shipment, receivable.payment_period)
        for row in closed.ledger:
            if row.kind == "customer_payment" and row.step == "apply_events":
                assert due[row.reference] == closed.period
                paid.append(row.reference)
        cash += sum((row.amount for row in closed.ledger), Decimal(0))
        assert cash == closed.cash
    assert len(paid) == len(set(paid))


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_with_payment_terms_0_every_revenue_is_paid_at_its_shipment(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    for customer in manifest["customers"].values():
        customer["payment_terms"] = 0
    _, steps = drawn_run((manifest, scenario), seed, data.draw)

    for _, _, closed in steps:
        assert closed.receivables == ()
        earned = closed.measures["revenue"]["total"]
        assert earned == ledger_total(closed.ledger, "customer_payment")
        kinds = {event["kind"] for event in closed.period_events}
        assert "customer_payment" not in kinds


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_receivables_per_customer_sum_to_their_total(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    _, steps = drawn_run(factory, seed, data.draw)

    for _, _, closed in steps:
        receivables = dict(closed.measures["receivables"])
        total = receivables.pop("total")
        assert total == sum(
            (value or Decimal(0) for value in receivables.values()), Decimal(0)
        )
