from dataclasses import asdict, replace
from decimal import Decimal
from typing import Any

import pytest
from factories import (
    FactoryBodies,
    buy,
    draw_world_of_bodies,
    produce,
    seeds,
    small_factories,
    started,
    submission,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given
from hypothesis import strategies as st

from factory_simulator.engine import (
    Disruption,
    State,
    World,
    advance_period,
    build_state,
    is_active,
    start_period,
    targets_of,
)
from factory_simulator.engine.rules.disruptions import (
    disruption_factor,
    remaining_share,
    transport_delay,
)

ONE_KIND_TARGETS = {
    "supplier_outage": (["chip-maker"], "strength", "chip-maker"),
    "demand_shock": (["monitor"], "factor", "monitor"),
    "price_change": (["chip"], "factor", "chip"),
    "transport_delay": (["chip-maker"], "delay", "chip-maker"),
}


BUYS_DUE_IN_2_TO_5 = {period: [buy("100")] for period in range(1, 5)}


def disrupted_world(
    *disruptions: dict[str, Any], horizon: int = 5, **chip_terms: str
) -> World:
    manifest = tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"].update(chip_terms)
    scenario = tiny_scenario()
    scenario["horizon"] = horizon
    scenario["disruptions"] = list(disruptions)
    return draw_world_of_bodies(manifest, scenario)


def events_of(state: State, kind: str) -> list[dict[str, Any]]:
    return [dict(event) for event in state.period_events if event["kind"] == kind]


def outage(strength: str, start: int, duration: int = 1) -> dict[str, Any]:
    return {
        "kind": "supplier_outage",
        "target": ["chip-maker"],
        "start": start,
        "duration": duration,
        "strength": strength,
    }


def started_periods(
    world: World, decisions: dict[int, list[dict[str, Any]]]
) -> list[State]:
    state = start_period(build_state(world), world)
    states = [state]
    while True:
        state = advance_period(
            state, world, submission(state.period, decisions.get(state.period, []))
        )
        if state.finished:
            return states
        state = start_period(state, world)
        states.append(state)


def shortage(strength: str) -> dict[str, Any]:
    return {
        "kind": "material_shortage",
        "target": ["chip"],
        "start": 1,
        "duration": 5,
        "strength": strength,
    }


def first_outcomes(world: World, *decisions: dict[str, Any]) -> list[dict[str, Any]]:
    state = start_period(build_state(world), world)
    closed = advance_period(state, world, submission(1, list(decisions)))
    return [
        {
            key: value
            for key, value in asdict(outcome).items()
            if value is not None and key not in ("decision", "decision_id")
        }
        for outcome in closed.outcomes
    ]


def on_chip_maker(kind: str, start: int, **effect: object) -> dict[str, Any]:
    return {
        "kind": kind,
        "target": ["chip-maker"],
        "start": start,
        "duration": 1,
        **effect,
    }


def arrival_periods(periods: list[State]) -> list[tuple[int, str]]:
    return [
        (state.period, str(event["reference"]))
        for state in periods
        for event in events_of(state, "delivery")
    ]


def cut(strength: str) -> dict[str, Any]:
    return {
        "kind": "capacity_cut",
        "target": ["line-1"],
        "start": 1,
        "duration": 1,
        "strength": strength,
    }


def with_boards(world: World) -> World:
    stock = dict(world.scenario.start.stock["main"]) | {"board": Decimal(30)}
    start = replace(world.scenario.start, stock={"main": stock})
    return replace(world, scenario=replace(world.scenario, start=start))


@st.composite
def overlapping_disruptions(draw: st.DrawFn) -> tuple[str, list[dict[str, Any]]]:
    kind = draw(st.sampled_from(sorted(ONE_KIND_TARGETS)))
    target, key, _ = ONE_KIND_TARGETS[kind]
    values = {
        "strength": st.sampled_from(["0.2500", "0.5000", "0.7500"]),
        "factor": st.sampled_from(["0.5000", "1.2500", "2.0000"]),
        "delay": st.integers(min_value=1, max_value=3),
    }[key]
    count = draw(st.integers(min_value=2, max_value=4))
    written = [
        {
            "kind": kind,
            "target": target,
            "start": draw(st.integers(min_value=1, max_value=3)),
            "duration": draw(st.integers(min_value=1, max_value=3)),
            key: draw(values),
        }
        for _ in range(count)
    ]
    return kind, written


def from_3_for_2(kind: str, target: str, **effect: object) -> dict[str, Any]:
    return {"kind": kind, "target": [target], "start": 3, "duration": 2, **effect}


def period_pairs(
    world: World, decisions: dict[int, list[dict[str, Any]]]
) -> list[tuple[State, State]]:
    state = build_state(world)
    periods: list[tuple[State, State]] = []
    while not state.finished:
        opened = start_period(state, world)
        state = advance_period(
            opened,
            world,
            submission(opened.period, decisions.get(opened.period, [])),
        )
        periods.append((opened, state))
    return periods


def deliveries_by_period(
    world: World, decisions: dict[int, list[dict[str, Any]]], key: str
) -> dict[int, Decimal]:
    return {
        opened.period: event[key]
        for opened, _ in period_pairs(world, decisions)
        for event in events_of(opened, "delivery")
    }


def test_an_outage_cuts_the_quantity_that_arrives_from_its_supplier():
    world = disrupted_world(outage("0.8000", 3), acceptance="0.9800")

    state = started(world, 3, {1: [buy("100")]})

    delivery = events_of(state, "delivery")[0]
    assert (delivery["arrived"], delivery["accepted"], delivery["payment"]) == (
        Decimal("20.000"),
        Decimal("19.600"),
        Decimal("9.8"),
    )


def test_a_disruption_acts_from_its_start_for_its_duration_and_says_so():
    world = disrupted_world(outage("0.5000", 10, duration=3), horizon=14)
    buys = {period: [buy("10")] for period in range(7, 12)}

    periods = started_periods(world, buys)

    arrived = {
        state.period: event["arrived"]
        for state in periods
        for event in events_of(state, "delivery")
    }
    told = [
        (state.period, event["kind"], event["reference"], event["target"])
        for state in periods
        for event in state.period_events
        if str(event["kind"]).startswith("disruption_")
    ]
    assert arrived == {
        9: Decimal("10.000"),
        10: Decimal("5.000"),
        11: Decimal("5.000"),
        12: Decimal("5.000"),
        13: Decimal("10.000"),
    }
    assert told == [
        (10, "disruption_started", "disruption-1", ("chip-maker",)),
        (13, "disruption_ended", "disruption-1", ("chip-maker",)),
    ]


def test_the_events_of_a_disruption_name_its_kind():
    world = disrupted_world(outage("0.5000", 3, duration=2), horizon=6)

    periods = started_periods(world, {})

    told = [
        (state.period, event["kind"], event["disruption"])
        for state in periods
        for event in state.period_events
        if str(event["kind"]).startswith("disruption_")
    ]
    assert told == [
        (3, "disruption_started", "supplier_outage"),
        (5, "disruption_ended", "supplier_outage"),
    ]


def test_a_material_shortage_lowers_the_buy_limit():
    world = disrupted_world(shortage("0.5000"))

    assert first_outcomes(world, buy("600")) == [
        {
            "accepted": False,
            "reason": "over_max_quantity",
            "asked": Decimal("600.000"),
            "available": Decimal("500.000"),
        }
    ]


def test_two_shortages_multiply_and_the_buy_limit_is_rounded_down():
    world = disrupted_world(shortage("0.3333"), shortage("0.3333"))

    accepted = first_outcomes(world, buy("444.488"))
    rejected = first_outcomes(world, buy("444.489"))

    assert accepted[0]["accepted"] is True
    assert rejected == [
        {
            "accepted": False,
            "reason": "over_max_quantity",
            "asked": Decimal("444.489"),
            "available": Decimal("444.488"),
        }
    ]


def test_a_transport_delay_moves_an_arrival_in_its_window_later():
    world = disrupted_world(
        on_chip_maker("transport_delay", 6, delay=2), horizon=9, lead_time="2"
    )

    periods = started_periods(world, {4: [buy("10")]})

    assert arrival_periods(periods) == [(8, "buy-4-1")]


def test_a_starting_supplier_order_is_not_disrupted():
    manifest = tiny_manifest()
    scenario = tiny_scenario()
    scenario["horizon"] = 10
    scenario["start"]["supplier_orders"] = [
        {"supplier": "chip-maker", "material": "chip", "quantity": "100", "arrival": 10}
    ]
    scenario["disruptions"] = [
        on_chip_maker("supplier_outage", 10, strength="0.5000"),
        on_chip_maker("quality_drop", 10, strength="0.5000"),
        on_chip_maker("transport_delay", 10, delay=2),
    ]
    world = draw_world_of_bodies(manifest, scenario)

    state = started(world, 10, {})

    delivery = events_of(state, "delivery")[0]
    assert (delivery["arrived"], delivery["accepted"]) == (
        Decimal("100.000"),
        Decimal("100.000"),
    )


def test_a_price_change_prices_orders_placed_while_it_acts():
    change = {
        "kind": "price_change",
        "target": ["chip"],
        "start": 2,
        "duration": 1,
        "factor": "1.2000",
    }
    world = disrupted_world(change, price="0.5123", lead_time="5")

    state = started(world, 3, {1: [buy("10")], 2: [buy("10")]})

    assert [(order.id, order.unit_price) for order in state.supplier_orders] == [
        ("buy-1-1", Decimal("0.5123")),
        ("buy-2-1", Decimal("0.6148")),
    ]


def test_a_capacity_cut_takes_its_share_of_the_hours_of_a_line():
    world = with_boards(disrupted_world(cut("0.5000")))

    assert first_outcomes(world, produce("monitor", "10.002")) == [
        {
            "accepted": False,
            "reason": "not_enough_hours",
            "asked": Decimal("5.001"),
            "available": Decimal("5.000"),
        }
    ]


def test_two_capacity_cuts_multiply_and_the_limits_are_rounded_down():
    world = with_boards(disrupted_world(cut("0.3333"), cut("0.3333")))

    accepted = first_outcomes(world, produce("monitor", "8.888"))
    rejected = first_outcomes(world, produce("monitor", "8.890"))

    assert accepted[0]["accepted"] is True
    assert rejected == [
        {
            "accepted": False,
            "reason": "not_enough_hours",
            "asked": Decimal("4.445"),
            "available": Decimal("4.444"),
        }
    ]


def test_a_written_line_breakdown_takes_its_loss_once_with_a_breakdown_event():
    breakdown = {
        "kind": "line_breakdown",
        "target": ["line-1"],
        "start": 1,
        "loss": "0.3000",
    }
    world = disrupted_world(breakdown)

    state = start_period(build_state(world), world)

    assert state.condition["line-1"] == Decimal("0.7")
    assert [
        dict(event)
        for event in state.period_events
        if event["kind"] != "customer_order"
    ] == [
        {
            "kind": "breakdown",
            "step": "apply_events",
            "reference": "disruption-1",
            "line": "line-1",
            "loss": Decimal("0.3000"),
            "condition": Decimal("0.7"),
        }
    ]


def test_a_demand_shock_on_all_names_every_product_and_multiplies_demand():
    manifest = tiny_manifest()
    manifest["products"]["keyboard"] = dict(manifest["products"]["monitor"])
    scenario = tiny_scenario()
    scenario["disruptions"] = [
        {
            "kind": "demand_shock",
            "target": "all",
            "start": 2,
            "duration": 1,
            "factor": "2.0000",
        }
    ]
    world = draw_world_of_bodies(manifest, scenario)

    periods = started_periods(world, {})

    started_events = [
        dict(event) for event in events_of(periods[1], "disruption_started")
    ]
    ordered = [
        [event["quantity"] for event in events_of(state, "customer_order")]
        for state in periods[:3]
    ]
    assert started_events[0]["target"] == ("keyboard", "monitor")
    assert ordered == [[Decimal("4.000")], [Decimal("8.000")], [Decimal("4.000")]]


def test_two_outages_on_one_supplier_multiply():
    world = disrupted_world(outage("0.5000", 3), outage("0.5000", 3))

    state = started(world, 3, {1: [buy("100")]})

    assert events_of(state, "delivery")[0]["arrived"] == Decimal("25.000")


def test_a_quality_drop_cuts_the_acceptance_of_its_supplier():
    world = disrupted_world(on_chip_maker("quality_drop", 3, strength="0.5000"))

    state = started(world, 3, {1: [buy("100")]})

    assert events_of(state, "delivery")[0]["accepted"] == Decimal("50.000")


def test_two_transport_delays_add_their_periods():
    world = disrupted_world(
        on_chip_maker("transport_delay", 3, delay=1),
        on_chip_maker("transport_delay", 3, delay=2),
        horizon=7,
    )

    periods = started_periods(world, {1: [buy("10")]})

    assert arrival_periods(periods) == [(6, "buy-1-1")]


def test_a_supplier_outage_cuts_arrivals_only_in_periods_3_and_4():
    world = disrupted_world(
        from_3_for_2("supplier_outage", "chip-maker", strength="0.5000"),
        lead_time="1",
    )

    arrived = deliveries_by_period(world, BUYS_DUE_IN_2_TO_5, "arrived")

    assert arrived == {
        2: Decimal("100.000"),
        3: Decimal("50.000"),
        4: Decimal("50.000"),
        5: Decimal("100.000"),
    }


def test_a_quality_drop_cuts_acceptance_only_in_periods_3_and_4():
    world = disrupted_world(
        from_3_for_2("quality_drop", "chip-maker", strength="0.2000"),
        lead_time="1",
    )

    accepted = deliveries_by_period(world, BUYS_DUE_IN_2_TO_5, "accepted")

    assert accepted == {
        2: Decimal("100.000"),
        3: Decimal("80.000"),
        4: Decimal("80.000"),
        5: Decimal("100.000"),
    }


def test_a_transport_delay_moves_only_orders_due_in_periods_3_and_4():
    world = disrupted_world(
        from_3_for_2("transport_delay", "chip-maker", delay=2),
        horizon=6,
        lead_time="1",
    )

    periods = started_periods(world, BUYS_DUE_IN_2_TO_5)

    assert dict(
        (reference, period) for period, reference in arrival_periods(periods)
    ) == {
        "buy-1-1": 2,
        "buy-2-1": 5,
        "buy-3-1": 6,
        "buy-4-1": 5,
    }


def test_a_material_shortage_lowers_the_buy_limit_only_in_periods_3_and_4():
    world = disrupted_world(
        from_3_for_2("material_shortage", "chip", strength="0.5000")
    )
    buys = {period: [buy("600")] for period in range(2, 6)}

    outcomes = {
        closed.period: (
            outcome.accepted,
            outcome.reason,
            outcome.asked,
            outcome.available,
        )
        for _, closed in period_pairs(world, buys)
        for outcome in closed.outcomes
    }

    rejected = (False, "over_max_quantity", Decimal("600.000"), Decimal("500.000"))
    assert outcomes == {
        2: (True, None, None, None),
        3: rejected,
        4: rejected,
        5: (True, None, None, None),
    }


def test_a_price_change_prices_only_buys_placed_in_periods_3_and_4():
    world = disrupted_world(
        from_3_for_2("price_change", "chip", factor="1.2000"),
        price="5.0000",
        lead_time="2",
        horizon=6,
    )
    buys = {period: [buy("10")] for period in range(2, 6)}

    prices = {
        order.id: order.unit_price
        for _, closed in period_pairs(world, buys)
        for order in closed.supplier_orders
        if order.placed == closed.period
    }

    assert prices == {
        "buy-2-1": Decimal("5.0000"),
        "buy-3-1": Decimal("6.0000"),
        "buy-4-1": Decimal("6.0000"),
        "buy-5-1": Decimal("5.0000"),
    }


def test_a_yield_drop_cuts_good_units_only_of_production_started_in_3_and_4():
    world = disrupted_world(from_3_for_2("yield_drop", "line-1", strength="0.5000"))
    boards = {
        period: [
            {"kind": "produce", "line": "line-1", "item": "board", "quantity": "10"}
        ]
        for period in range(2, 6)
    }

    good = {
        closed.period: event["good"]
        for _, closed in period_pairs(world, boards)
        for event in events_of(closed, "production_finished")
    }

    assert good == {
        2: Decimal("9.000"),
        3: Decimal("4.500"),
        4: Decimal("4.500"),
        5: Decimal("9.000"),
    }


def test_a_capacity_cut_lowers_the_three_limits_only_in_periods_3_and_4():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(
        wear_per_period="0.0000",
        wear_per_hour="0.0000",
        overtime_hours="2.000",
        overtime_cost="1.0000",
    )
    scenario = tiny_scenario()
    scenario["disruptions"] = [
        from_3_for_2("capacity_cut", "line-1", strength="0.5000")
    ]
    world = draw_world_of_bodies(manifest, scenario)

    hours: dict[int, tuple[Decimal, Decimal, Decimal]] = {}
    for opened, _ in period_pairs(world, {}):
        assert opened.observation is not None
        line = opened.observation.lines["line-1"]
        hours[opened.period] = (
            line.regular_hours_available,
            line.repair_hours_available,
            line.overtime_hours_available,
        )

    assert {period: hours[period] for period in range(2, 6)} == {
        2: (Decimal("10.000"), Decimal("10.000"), Decimal("2.000")),
        3: (Decimal("5.000"), Decimal("5.000"), Decimal("1.000")),
        4: (Decimal("5.000"), Decimal("5.000"), Decimal("1.000")),
        5: (Decimal("10.000"), Decimal("10.000"), Decimal("2.000")),
    }


def test_no_disruption_acts_on_a_transfer():
    manifest = tiny_manifest()
    manifest["warehouses"]["centre"] = {"capacity": "50.000", "accepts": ["products"]}
    manifest["lines"]["line-1"]["warehouse"] = "main"
    manifest["routes"] = {"main": {"centre": {"cost": "0.2000", "lead_time": 1}}}
    scenario = tiny_scenario()
    scenario["start"]["stock"] = {"main": {"chip": "100", "monitor": "10"}}
    scenario["disruptions"] = [
        from_3_for_2("supplier_outage", "chip-maker", strength="0.5000"),
        from_3_for_2("quality_drop", "chip-maker", strength="0.5000"),
        from_3_for_2("transport_delay", "chip-maker", delay=2),
        from_3_for_2("material_shortage", "chip", strength="0.5000"),
        from_3_for_2("price_change", "chip", factor="2.0000"),
        from_3_for_2("demand_shock", "monitor", factor="2.0000"),
        from_3_for_2("capacity_cut", "line-1", strength="0.5000"),
        from_3_for_2("yield_drop", "line-1", strength="0.5000"),
        {"kind": "line_breakdown", "target": ["line-1"], "start": 3, "loss": "0.5000"},
    ]
    world = draw_world_of_bodies(manifest, scenario)
    send = {
        "kind": "transfer",
        "item": "monitor",
        "quantity": "6",
        "source": "main",
        "destination": "centre",
    }

    periods = period_pairs(world, {3: [send]})

    _, sent = periods[2]
    arrived, _ = periods[3]
    assert [
        (row.reference, row.amount)
        for row in sent.ledger
        if row.kind == "transfer_cost"
    ] == [("transfer-3-1", Decimal("-1.2"))]
    assert [
        (event["step"], event["reference"], event["quantity"])
        for event in events_of(arrived, "transfer_arrived")
    ] == [("receive_deliveries", "transfer-3-1", Decimal("6.000"))]
    assert arrived.stock["centre"]["monitor"] == Decimal("6.000")


def test_a_line_breakdown_acts_in_its_start_period_only():
    breakdown = Disruption(
        id="disruption-1",
        kind="line_breakdown",
        target=("line-1",),
        start=3,
        duration=2,
        effect=Decimal("0.1000"),
    )

    assert [is_active(breakdown, period) for period in (3, 4)] == [True, False]


@pytest.mark.property
@given(small_factories(), seeds)
def test_a_disruption_is_reported_exactly_where_it_starts_and_ends(
    factory: FactoryBodies, seed: int
):
    world = draw_world_of_bodies(*factory, seed=seed)
    horizon = world.scenario.horizon

    periods = started_periods(world, {})
    identifiers = {disruption.id for disruption in world.disruptions}

    told = {
        (state.period, str(event["kind"]), str(event["reference"]))
        for state in periods
        for event in state.period_events
        if str(event["reference"]) in identifiers
    }
    expected: set[tuple[int, str, str]] = set()
    for disruption in world.disruptions:
        if disruption.kind == "line_breakdown":
            expected |= {
                (disruption.start, "breakdown", disruption.id)
                for _ in targets_of(disruption, world)
            }
            continue
        expected.add((disruption.start, "disruption_started", disruption.id))
        end = disruption.start + disruption.duration
        if end <= horizon:
            expected.add((end, "disruption_ended", disruption.id))
    assert told == expected
    for state in periods:
        for disruption in world.disruptions:
            assert is_active(disruption, state.period) == (
                disruption.start
                <= state.period
                < disruption.start + disruption.duration
            )


@pytest.mark.property
@given(overlapping_disruptions())
def test_overlapping_disruptions_of_one_kind_multiply_and_delays_add(
    drawn: tuple[str, list[dict[str, Any]]],
):
    kind, written = drawn
    _, key, target = ONE_KIND_TARGETS[kind]
    scenario = tiny_scenario()
    scenario["disruptions"] = written
    world = draw_world_of_bodies(tiny_manifest(), scenario)

    for period in range(1, 6):
        acting = [
            entry
            for entry in written
            if entry["start"] <= period < entry["start"] + entry["duration"]
        ]
        if key == "delay":
            expected_delay = sum(int(entry["delay"]) for entry in acting)
            assert transport_delay(target, period, world) == expected_delay
        elif key == "strength":
            expected = Decimal(1)
            for entry in acting:
                expected *= 1 - Decimal(entry["strength"])
            assert remaining_share(kind, target, period, world) == expected
        else:
            expected = Decimal(1)
            for entry in acting:
                expected *= Decimal(entry["factor"])
            assert disruption_factor(kind, target, period, world) == expected
