import copy
from dataclasses import replace
from decimal import Decimal
from typing import cast

import pytest
from factories import (
    FactoryBodies,
    RunStep,
    buy,
    cancel,
    closed_period,
    closed_periods,
    decide,
    draw_world_of_bodies,
    example_count,
    mixed_decision_lists,
    one_order_world,
    produce,
    repair,
    seeds,
    ship,
    small_factories,
    tiny_manifest,
    tiny_scenario,
    transfer,
    transfer_world,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.engine import State, Transfer, build_state, start_period
from factory_simulator.engine.measures.closed import ClosedPeriod
from factory_simulator.engine.measures.flows import line_flows

# Up to 3 transfers from main to centre of 1 to 10 units of chip, board or monitor.
whole_transfers = st.lists(
    st.builds(
        transfer,
        st.sampled_from(["chip", "board", "monitor"]),
        st.integers(min_value=1, max_value=10).map(str),
    ),
    max_size=3,
)


# Warehouses main and centre that accept every kind, line 1 in centre, and a route from
# main to centre of lead time 1.
def routed_factory() -> FactoryBodies:
    manifest = tiny_manifest()
    manifest["warehouses"]["centre"] = {
        "capacity": "100.000",
        "accepts": ["materials", "components", "products"],
    }
    manifest["lines"]["line-1"]["warehouse"] = "centre"
    manifest["routes"] = {"main": {"centre": {"cost": "0.2000", "lead_time": 1}}}
    scenario = tiny_scenario()
    scenario["start"]["stock"] = {
        "main": {"chip": "100", "board": "10", "monitor": "5"}
    }
    return manifest, scenario


def add(totals: dict[str, Decimal], key: str, amount: Decimal) -> None:
    totals[key] = totals.get(key, Decimal(0)) + amount


# The closed period 1 of the tiny factory with ship 4, produce 4 monitors and 20 boards
# and buy 50 chips.
def tiny_period_1() -> State:
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario())
    decisions = [
        ship("order-1-1", "4"),
        produce("monitor", "4"),
        produce("board", "20"),
        buy("50"),
    ]
    return closed_period(world, 1, {1: decisions})


def test_units_used_counts_the_inputs_taken_in_period_1_of_the_tiny_factory():
    measures = tiny_period_1().measures

    # 4 monitors take 4 * 2 = 8 boards; 20 boards take 20 * 2 = 40 chips.
    assert measures["units_used"]["warehouses.main/chip"] == Decimal(40)
    assert measures["units_used"]["warehouses.main/board"] == Decimal(8)
    assert measures["units_used"]["warehouses.main/monitor"] == Decimal(0)


def test_a_line_uses_4_of_its_10_hours_in_period_1_of_the_tiny_factory():
    measures = tiny_period_1().measures

    # 4 monitors take 4 * 0.5 = 2 hours, 20 boards 20 * 0.1 = 2 hours, no changeover.
    assert measures["hours_available"]["lines.line-1"] == Decimal(10)
    assert measures["utilisation"]["lines.line-1"] == Decimal("0.4")


def test_a_stopped_line_has_no_hours_and_its_repair_hours_count_in_neither_measure():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(
        repair_time="40.000", repair_cost="1000.0000", repair_limit="0.5000"
    )
    scenario = tiny_scenario()
    scenario["start"]["condition"] = {"line-1": "0"}
    world = draw_world_of_bodies(manifest, scenario)

    stopped, repaired = closed_periods(world, {1: [repair("0.2000")]})[:2]

    assert stopped.measures["repair_hours"]["lines.line-1"] == Decimal(8)
    assert stopped.measures["hours_available"]["lines.line-1"] == Decimal(0)
    assert stopped.measures["utilisation"]["lines.line-1"] == Decimal(0)
    # Condition 0.2 at the close of period 1 gives 10 * 0.2 = 2 hours in period 2.
    assert repaired.measures["hours_available"]["lines.line-1"] == Decimal(2)


def test_a_state_closed_without_an_observation_has_no_hours_available():
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario())
    state = replace(build_state(world), period=1)

    closed = ClosedPeriod(
        state=state, world=world, customer_orders={}, supplier_orders={}, production={}
    )

    # The line has 10 hours, but only an observation shows them.
    assert line_flows(closed)["hours_available"] == {"lines.line-1": Decimal(0)}


def test_a_starting_supplier_order_arriving_after_the_lead_time_is_not_late():
    scenario = tiny_scenario()
    scenario["start"]["supplier_orders"] = [
        {"supplier": "chip-maker", "material": "chip", "quantity": "10", "arrival": 4}
    ]
    world = draw_world_of_bodies(tiny_manifest(), scenario)

    fourth = closed_periods(world, {})[3]

    # Placed in period 0 with lead time 2, it arrives in period 4 as written.
    key = "suppliers.chip-maker/chip"
    assert fourth.measures["units_arrived"][key] == Decimal(10)
    assert fourth.measures["units_arrived_late"][key] == Decimal(0)


def test_the_measures_count_transfers_per_route_and_storage_at_the_destination():
    world = transfer_world()

    state = closed_period(world, 1, {1: [transfer("monitor", "6")]})

    route = "routes.main/centre"
    assert state.measures["units_transferred"][route] == Decimal(6)
    assert state.measures["transfer_cost"][route] == Decimal("1.2")
    assert state.measures["transfer_cost"]["total"] == Decimal("1.2")
    storage = state.measures["storage_cost"]
    assert storage["warehouses.centre"] == Decimal("0.36")
    per_warehouse = [storage["warehouses.main"], storage["warehouses.centre"]]
    assert sum(Decimal(cost or 0) for cost in per_warehouse) == storage["total"]


def test_periods_below_credit_limit_counts_closes_below_minus_the_limit():
    manifest = tiny_manifest()
    manifest["cash"] = {
        "credit_limit": "100.0000",
        "credit_interest": "0.0000",
        "debit_interest": "0.0000",
        "overdraft_interest": "0.0000",
    }
    manifest["products"]["monitor"]["storage_cost"] = "0.0000"
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms.update({"demand": "0", "price": "10.0000", "transport_cost": "0.0000"})
    manifest["lines"]["line-1"]["repair_cost"] = "1000.0000"
    scenario = tiny_scenario()
    scenario["start"] = {
        "cash": "-50",
        "stock": {"main": {"monitor": "20"}},
        "condition": {"line-1": "0.8000"},
        "customer_orders": [
            {
                "customer": "distributor",
                "product": "monitor",
                "quantity": "20",
                "due": 5,
            }
        ],
    }
    world = draw_world_of_bodies(manifest, scenario)
    # Cash at the close: -50, then -150 after a repair of 100, -120 after a shipment
    # of 30, and 20 after a shipment of 140.
    decisions = {
        2: [repair("0.1")],
        3: [ship("order-0-1", "3")],
        4: [ship("order-0-1", "14")],
    }

    closed = closed_periods(world, decisions)[:4]

    assert [state.cash for state in closed] == [-50, -150, -120, 20]
    below = [state.measures["periods_below_credit_limit"]["total"] for state in closed]
    assert below == [0, 1, 1, 0]
    assert closed[3].tallies.running["periods_below_credit_limit"]["total"] == 2


def test_plans_cancelled_counts_cancels_of_plans_only():
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario())
    plan = produce("board", "1", start=4)
    decisions = {
        1: [plan, plan],
        2: [cancel("make-1-1"), produce("board", "1")],
    }

    closed = closed_periods(world, decisions)

    assert all(outcome.accepted for outcome in closed[1].outcomes)
    assert [plan.id for plan in closed[1].plans] == ["make-1-2"]
    assert closed[1].measures["plans_cancelled"]["total"] == 1
    assert closed[3].tallies.running["plans_cancelled"]["total"] == 1


def test_decisions_rejected_counts_each_reason_under_its_key():
    world = one_order_world("30", due=3)
    too_much = buy("1001")

    first = closed_periods(world, {1: [too_much, too_much, ship("order-0-1", "30")]})[0]

    assert first.measures["decisions_rejected"] == {
        "total": 3,
        "reasons.not_enough_stock": 1,
        "reasons.over_max_quantity": 2,
    }


def test_units_ordered_counts_each_pair_under_its_key():
    manifest = tiny_manifest()
    distributor = manifest["customers"]["distributor"]
    manifest["customers"]["retailer"] = copy.deepcopy(distributor)
    manifest["customers"]["retailer"]["products"]["monitor"]["demand"] = "6.000"
    world = draw_world_of_bodies(manifest, tiny_scenario())

    ordered = closed_periods(world, {})[0].measures["units_ordered"]

    assert ordered["total"] == 10
    assert ordered["pairs.distributor/monitor"] == 4
    assert ordered["pairs.retailer/monitor"] == 6


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(st.one_of(small_factories(), st.builds(routed_factory)), seeds, st.data())
def test_per_route_units_sent_equal_units_arrived_plus_units_on_the_way(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world = draw_world_of_bodies(*factory, seed=seed)
    state = build_state(world)
    steps: list[RunStep] = []
    while not state.finished:
        decided = start_period(state, world)
        decisions = data.draw(
            st.one_of(mixed_decision_lists(world, decided), whole_transfers)
        )
        state = decide(decided, world, decisions)
        steps.append((decided, decisions, state))

    measured: dict[str, Decimal] = {}
    sent: dict[str, Decimal] = {}
    routes: dict[str, str] = {}
    arrived: dict[str, Decimal] = {}
    for decided, _, closed in steps:
        for event in decided.period_events:
            if event["kind"] == "transfer_arrived":
                route = routes[str(event["reference"])]
                add(arrived, route, cast(Decimal, event["quantity"]))
        for key, units in closed.measures["units_transferred"].items():
            add(measured, key.removeprefix("routes."), Decimal(units or 0))
        on_the_way = {moving.id for moving in closed.transfers}
        for outcome in closed.outcomes:
            decision = outcome.decision
            if not outcome.accepted or not isinstance(decision, Transfer):
                continue
            route = f"{decision.source}/{decision.destination}"
            routes[str(outcome.reference)] = route
            add(sent, route, decision.quantity)
            if outcome.reference not in on_the_way:
                add(arrived, route, decision.quantity)
    waiting: dict[str, Decimal] = {}
    for transfer_on_the_way in steps[-1][2].transfers:
        route = f"{transfer_on_the_way.source}/{transfer_on_the_way.destination}"
        add(waiting, route, transfer_on_the_way.quantity)

    assert {route: units for route, units in measured.items() if units} == sent
    for route, units in sent.items():
        assert units == arrived.get(route, 0) + waiting.get(route, 0)
