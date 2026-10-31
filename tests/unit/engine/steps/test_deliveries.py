from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, cast

import pytest
from factories import (
    DecisionLists,
    FactoryBodies,
    RunStep,
    buy,
    cancel,
    closed_period,
    count_reached,
    decide,
    draw_world_of_bodies,
    drawn_run,
    example_count,
    example_world,
    first_period,
    mixed_decision_lists,
    number_text,
    seeds,
    small_factories,
    spare_world,
    started,
    supplier_orders_of,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.engine import (
    State,
    World,
    build_state,
    is_active,
    start_period,
    targets_of,
)

BUY_IN_PERIOD_2 = {2: [buy("100")]}


SPLIT_BUYS = {2: [buy("0.001")] * 1000}


BULK_BUY = {2: [buy("1.000")]}


# The passive kit of emea-electronic-parts in the steady market with seed 0: lead
# time 2, express lead time 1, punctuality drawn 0.9073, delay 1, backfill delay 1,
# completeness 0.9500 to 1.0000, acceptance 0.9700 to 1.0000, price 2.4332 and express
# cost 0.6000. A normal buy and an express buy of 1.000 are placed in period 1.
PASSIVE_KIT_TERMS = {"supplier": "emea-electronic-parts", "warehouse": "main-plant"}


KIT_BUYS = {
    1: [
        buy("1.000", "passive-kit", **PASSIVE_KIT_TERMS),
        buy("1.000", "passive-kit", express=True, **PASSIVE_KIT_TERMS),
    ]
}


def places(value: Decimal) -> int:
    return max(0, -cast(int, value.normalize().as_tuple().exponent))


def backfill_world(
    horizon: int = 8, disruptions: list[dict[str, Any]] | None = None, **terms: object
) -> World:
    manifest = tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"].update(
        {
            "lead_time": 2,
            "punctuality": "0.0000",
            "delay": 1,
            "completeness": "0.9000",
            "acceptance": "0.9800",
            "backfill_delay": 2,
        }
        | terms
    )
    scenario = tiny_scenario()
    scenario["horizon"] = horizon
    scenario["disruptions"] = disruptions or []
    return draw_world_of_bodies(manifest, scenario)


def chip_maker_disruption(kind: str, start: int, **effect: object) -> dict[str, Any]:
    return {
        "kind": kind,
        "target": ["chip-maker"],
        "start": start,
        "duration": 1,
    } | effect


def backfill_outage_world(start: int) -> World:
    outage = chip_maker_disruption("supplier_outage", start, strength="0.5000")
    return backfill_world(disruptions=[outage])


def deliveries(state: State) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in event.items() if key not in ("kind", "step")}
        for event in state.period_events
        if event["kind"] == "delivery"
    ]


def delivery(
    ordered: str, arrived: str, accepted: str, lost: str, payment: str, backfill: bool
) -> dict[str, Any]:
    return {
        "reference": "buy-2-1",
        "ordered": Decimal(ordered),
        "arrived": Decimal(arrived),
        "accepted": Decimal(accepted),
        "lost": Decimal(lost),
        "payment": Decimal(payment),
        "backfill": backfill,
    }


def open_quantities(state: State) -> dict[str, Decimal]:
    return {order.id: order.open_quantity for order in state.supplier_orders}


def remaining(world: World, kind: str, supplier: str, period: int) -> Decimal:
    share = Decimal(1)
    for disruption in world.disruptions:
        targets = targets_of(disruption, world)
        if (
            disruption.kind == kind
            and supplier in targets
            and is_active(disruption, period)
        ):
            share *= 1 - disruption.effect
    return share


def rounded(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN)


# One catalogue entry of a manifest: its supplier, its material and its terms.
def draw_entry(
    draw: st.DrawFn, manifest: dict[str, Any]
) -> tuple[str, str, dict[str, Any]]:
    supplier_id = draw(st.sampled_from(sorted(manifest["suppliers"])))
    catalogue = manifest["suppliers"][supplier_id]["catalogue"]
    material_id = draw(st.sampled_from(sorted(catalogue)))
    return supplier_id, material_id, catalogue[material_id]


# The decisions of every kind, with the given buys first in one period.
def with_buys_in(period: int, buys: list[dict[str, Any]]) -> DecisionLists:
    def decision_lists(
        world: World, state: State
    ) -> st.SearchStrategy[list[dict[str, Any]]]:
        drawn = mixed_decision_lists(world, state)
        if state.period != period:
            return drawn
        return drawn.map(lambda decisions: [*buys, *decisions])

    return decision_lists


# A run of a small factory in which one catalogue entry has a lead time of 2 to 4, an
# express lead time below it and an express cost, no minimum quantity or discounts, and
# a drawn period places one express and one normal buy of it into `main`, from enough
# starting cash for both.
@st.composite
def runs_with_express_and_normal_buys(draw: st.DrawFn) -> tuple[World, list[RunStep]]:
    manifest, scenario = draw(small_factories())
    supplier_id, material_id, entry = draw_entry(draw, manifest)
    lead_time = draw(st.integers(min_value=2, max_value=4))
    entry |= {
        "lead_time": str(lead_time),
        "express_lead_time": str(
            draw(st.integers(min_value=1, max_value=lead_time - 1))
        ),
        "express_cost": draw(number_text(4, 0, 100)),
        "max_quantity": "1000.000",
    }
    entry.pop("min_quantity", None)
    entry.pop("discounts", None)
    scenario["start"]["cash"] = "100000.0000"
    normal = buy(
        draw(number_text(3, Decimal("0.001"), Decimal("0.1"))),
        material_id,
        supplier_id,
        warehouse="main",
    )
    buys = [normal | {"express": True}, normal | {"express": False}]
    period = draw(st.integers(min_value=1, max_value=scenario["horizon"]))
    return drawn_run(
        (manifest, scenario), draw(seeds), draw, with_buys_in(period, buys)
    )


# Whether a run holds an accepted express and an accepted normal order of one supplier,
# material and period.
def places_express_and_normal_orders(run: tuple[World, list[RunStep]]) -> bool:
    orders = supplier_orders_of(*run).values()
    placings = {
        (order.supplier, order.material, order.placed, order.express)
        for order in orders
    }
    return any(
        (supplier, material, placed, False) in placings
        for supplier, material, placed, express in placings
        if express
    )


# The world with the drawn outcome of the normal orders of one supplier, material and
# placing period replaced by another: the other punctuality, a delay 1 longer, and
# completeness and acceptance 0.5 higher, less 1 when that passes 1.
def with_other_outcome(world: World, pair: str, placed: int) -> World:
    outcomes = list(world.deliveries[pair])
    drawn = outcomes[placed - 1]
    outcomes[placed - 1] = replace(
        drawn,
        punctual=not drawn.punctual,
        delay=drawn.delay + 1,
        completeness=(drawn.completeness + Decimal("0.5")) % 1,
        acceptance=(drawn.acceptance + Decimal("0.5")) % 1,
    )
    return replace(world, deliveries={**world.deliveries, pair: tuple(outcomes)})


# A run of a small factory of 3 periods or more in which one catalogue entry, always on
# time with a lead time of 1, has a completeness of at most 0.9 and a backfill delay of
# 1 or more, and a drawn period places a buy of it into `main` whose backfill arrives
# within the horizon, from enough starting cash.
@st.composite
def runs_with_a_backfill(draw: st.DrawFn) -> tuple[World, list[RunStep]]:
    factories = small_factories().filter(lambda factory: factory[1]["horizon"] >= 3)
    manifest, scenario = draw(factories)
    horizon = scenario["horizon"]
    supplier_id, material_id, entry = draw_entry(draw, manifest)
    backfill_delay = draw(st.integers(min_value=1, max_value=horizon - 2))
    entry |= {
        "lead_time": "1",
        "punctuality": "1.0000",
        "completeness": draw(number_text(4, 0, Decimal("0.9"))),
        "backfill_delay": str(backfill_delay),
        "max_quantity": "1000.000",
    }
    for key in ("min_quantity", "discounts", "express_lead_time", "express_cost"):
        entry.pop(key, None)
    scenario["start"]["cash"] = "100000.0000"
    quantity = draw(number_text(3, Decimal("0.01"), 1))
    bought = buy(quantity, material_id, supplier_id, warehouse="main")
    period = draw(st.integers(min_value=1, max_value=horizon - 1 - backfill_delay))
    return drawn_run(
        (manifest, scenario), draw(seeds), draw, with_buys_in(period, [bought])
    )


# Whether a run delivers a backfill.
def delivers_a_backfill(run: tuple[World, list[RunStep]]) -> bool:
    return any(
        event["kind"] == "delivery" and event["backfill"]
        for decided, _, _ in run[1]
        for event in decided.period_events
    )


# The total arrived, accepted, lost and paid over the deliveries of a state, and its
# stock of chips.
def delivered(state: State) -> dict[str, Decimal]:
    totals = {
        key: sum((event[key] for event in deliveries(state)), Decimal(0))
        for key in ("arrived", "accepted", "lost", "payment")
    }
    return totals | {"stock": state.stock["main"]["chip"]}


def kit_delivery(
    reference: str, arrived: str, accepted: str, payment: str, backfill: bool = False
) -> dict[str, Any]:
    ordered = "1.000" if not backfill else arrived
    return delivery(ordered, arrived, accepted, "0.000", payment, backfill) | {
        "reference": reference
    }


def test_12_deliveries_come_in_the_order_of_their_numbers_not_their_text():
    manifest = tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["lead_time"] = 1
    world = draw_world_of_bodies(manifest, tiny_scenario())
    chip_buy = {
        "kind": "buy",
        "supplier": "chip-maker",
        "material": "chip",
        "quantity": "10",
    }

    first = start_period(build_state(world), world)
    second = start_period(decide(first, world, [chip_buy] * 12), world)

    numbered = [f"buy-1-{number}" for number in range(1, 13)]
    assert second.observation is not None
    assert [
        event["reference"]
        for event in second.observation.events
        if event["kind"] == "delivery"
    ] == numbered
    assert [
        event["reference"]
        for event in second.period_events
        if event["kind"] == "delivery"
    ] == numbered


def test_a_delivery_reserves_space_in_its_warehouse_and_enters_it_on_arrival():
    world = spare_world()

    first = first_period(world, [buy("200", warehouse="spare")])
    second = start_period(first, world)
    arrived = start_period(decide(second, world, []), world)

    assert second.observation is not None
    space = second.observation.space
    assert (space["spare"].reserved, space["main"].reserved) == (
        Decimal("0.200"),
        Decimal(0),
    )
    assert arrived.stock["spare"]["chip"] == Decimal("200.000")
    assert arrived.stock["main"]["chip"] == Decimal("900.000")


def test_the_part_missing_by_completeness_arrives_as_a_backfill():
    world = backfill_world()

    period_5 = started(world, 5, BUY_IN_PERIOD_2)
    period_6 = started(world, 6, BUY_IN_PERIOD_2)
    period_7 = started(world, 7, BUY_IN_PERIOD_2)

    assert deliveries(period_5) == [delivery("100", "90", "88.2", "0", "44.1", False)]
    assert open_quantities(period_5) == {"buy-2-1": Decimal("10.000")}
    assert deliveries(period_6) == []
    assert deliveries(period_7) == [delivery("10", "10", "9.8", "0", "4.9", True)]
    assert period_7.supplier_orders == ()


def test_arrived_accepted_and_the_backfill_have_3_places():
    decisions = {2: [buy("100.001")]}

    state = started(backfill_world(), 5, decisions)

    assert deliveries(state) == [
        delivery("100.001", "90.001", "88.201", "0", "44.1005", False)
    ]
    assert open_quantities(state) == {"buy-2-1": Decimal("10.000")}


def test_a_tie_of_arrived_rounds_half_to_even_and_the_backfill_takes_the_rest():
    world = backfill_world(completeness="0.5000")
    decisions = {2: [buy("0.005")]}

    period_5 = started(world, 5, decisions)
    period_7 = started(world, 7, decisions)

    # 0.005 * 0.5 = 0.0025 arrives as 0.002, where half up would give 0.003;
    # 0.002 * 0.98 = 0.00196 is accepted as 0.002 and paid at 0.5000.
    assert deliveries(period_5) == [
        delivery("0.005", "0.002", "0.002", "0", "0.001", False)
    ]
    assert open_quantities(period_5) == {"buy-2-1": Decimal("0.003")}
    # 0.003 * 0.98 = 0.00294 is accepted as 0.003.
    assert deliveries(period_7) == [
        delivery("0.003", "0.003", "0.003", "0", "0.0015", True)
    ]


def test_with_backfill_delay_0_the_missing_part_is_lost_and_the_order_closes():
    state = started(backfill_world(backfill_delay=0), 5, BUY_IN_PERIOD_2)

    assert deliveries(state) == [delivery("100", "90", "88.2", "10", "44.1", False)]
    assert state.supplier_orders == ()


def test_a_complete_delivery_leaves_no_backfill():
    world = backfill_world(completeness="1.0000")

    period_5 = started(world, 5, BUY_IN_PERIOD_2)
    period_7 = started(world, 7, BUY_IN_PERIOD_2)

    assert deliveries(period_5) == [delivery("100", "100", "98", "0", "49", False)]
    assert period_5.supplier_orders == ()
    assert deliveries(period_7) == []


def test_a_backfill_after_the_horizon_never_arrives_and_is_never_paid():
    world = backfill_world(horizon=6)

    period_5 = started(world, 5, BUY_IN_PERIOD_2)
    closed_5 = decide(period_5, world, [])
    closed_6 = decide(start_period(closed_5, world), world, [])

    [order] = closed_5.supplier_orders
    assert (order.arrival, order.backfill) == (5, 7)
    assert closed_6.finished
    assert open_quantities(closed_6) == {"buy-2-1": Decimal("10.000")}
    assert [row for row in closed_6.ledger if row.kind == "material_payment"] == []


def test_an_outage_at_the_first_delivery_loses_its_share_and_keeps_the_backfill():
    world = backfill_outage_world(start=5)

    period_5 = started(world, 5, BUY_IN_PERIOD_2)
    period_7 = started(world, 7, BUY_IN_PERIOD_2)

    assert deliveries(period_5) == [delivery("100", "45", "44.1", "45", "22.05", False)]
    assert deliveries(period_7) == [delivery("10", "10", "9.8", "0", "4.9", True)]


def test_an_outage_at_the_backfill_loses_its_share_of_the_backfill():
    state = started(backfill_outage_world(start=7), 7, BUY_IN_PERIOD_2)

    assert deliveries(state) == [delivery("10", "5", "4.9", "5", "2.45", True)]
    assert state.supplier_orders == ()


def test_a_backfill_can_be_cancelled_in_part():
    world = backfill_world(cancellation_fee="0.1000")
    decisions = {**BUY_IN_PERIOD_2, 6: [cancel("buy-2-1", "4")]}

    closed_6 = closed_period(world, 6, decisions)
    period_7 = started(world, 7, decisions)

    fees = [row.amount for row in closed_6.ledger if row.kind == "cancellation_fee"]
    assert fees == [Decimal("-0.4")]
    assert open_quantities(closed_6) == {"buy-2-1": Decimal("6.000")}
    assert deliveries(period_7) == [delivery("6", "6", "5.88", "0", "2.94", True)]


def test_a_transport_delay_never_moves_a_backfill():
    delay = chip_maker_disruption("transport_delay", 7, delay=2)

    state = started(backfill_world(disruptions=[delay]), 7, BUY_IN_PERIOD_2)

    assert deliveries(state) == [delivery("10", "10", "9.8", "0", "4.9", True)]


def test_deliveries_arrive_before_backfills():
    decisions = {**BUY_IN_PERIOD_2, 4: [buy("100")]}

    state = started(backfill_world(), 7, decisions)

    references = [event["reference"] for event in deliveries(state)]
    payments = [row.reference for row in state.ledger if row.kind == "material_payment"]
    assert references == ["buy-4-1", "buy-2-1"]
    assert payments == ["buy-4-1", "buy-2-1"]


def test_the_open_quantity_of_a_backfill_keeps_its_reserved_space():
    state = started(backfill_world(), 6, BUY_IN_PERIOD_2)

    assert state.observation is not None
    assert state.observation.space["main"].reserved == Decimal("0.100")


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_deliveries_have_3_places_and_unit_prices_4_places(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world, steps = drawn_run(factory, seed, data.draw)

    for decided, _, _ in steps:
        for event in decided.period_events:
            if event["kind"] == "delivery":
                for key in ("ordered", "arrived", "accepted", "lost"):
                    assert places(cast(Decimal, event[key])) <= 3
    for order in supplier_orders_of(world, steps).values():
        assert places(order.unit_price) <= 4


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(runs_with_express_and_normal_buys())
def test_without_transport_delays_an_express_order_on_time_comes_before_a_normal_one(
    run: tuple[World, list[RunStep]],
):
    world, steps = run
    kinds = {disruption.kind for disruption in world.disruptions}
    if "transport_delay" in kinds:
        return

    orders = supplier_orders_of(world, steps).values()
    for express in orders:
        if not express.express:
            continue
        pair = f"{express.supplier}/{express.material}"
        path = f"suppliers.{express.supplier}.catalogue.{express.material}"
        drawn = world.express_deliveries[pair][express.placed - 1]
        late = 0 if drawn.punctual else drawn.delay
        lead_time = int(world.parameters[f"{path}.express_lead_time"])
        assert express.arrival == express.placed + lead_time + late
        for normal in orders:
            same_placing = (express.supplier, express.material, express.placed) == (
                normal.supplier,
                normal.material,
                normal.placed,
            )
            if same_placing and not normal.express and drawn.punctual:
                assert express.arrival < normal.arrival


@pytest.mark.property
def test_express_and_normal_orders_of_one_placing_are_reached():
    reached, drawn = count_reached(
        runs_with_express_and_normal_buys(), places_express_and_normal_orders
    )

    assert reached * 10 >= drawn, (reached, drawn)


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(runs_with_express_and_normal_buys())
def test_no_decision_shows_the_outcome_of_a_normal_order_before_it_arrives(
    run: tuple[World, list[RunStep]],
):
    world, steps = run

    for order in supplier_orders_of(world, steps).values():
        if order.express or order.placed == 0:
            continue
        pair = f"{order.supplier}/{order.material}"
        other = with_other_outcome(world, pair, order.placed)
        state = build_state(other)
        other_arrival = None
        for decided, decisions, _ in steps:
            replayed = start_period(state, other)
            if replayed.period >= min(order.arrival, other_arrival or order.arrival):
                break
            assert replayed.observation == decided.observation
            state = decide(replayed, other, decisions)
            if replayed.period == order.placed:
                placed = {placed.id: placed for placed in state.supplier_orders}
                other_arrival = placed[order.id].arrival


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(runs_with_a_backfill())
def test_only_outages_and_quality_drops_act_on_backfills_in_their_active_periods(
    run: tuple[World, list[RunStep]],
):
    world, steps = run
    first_delivery: dict[str, int] = {}

    for decided, _, _ in steps:
        period = decided.period
        # The backfills of one supplier, material, warehouse and kind of order placed
        # in one period form a batch: its units ordered, arrived and accepted.
        batches: dict[tuple[str, str, str, int, bool], list[Decimal]] = {}
        for event in decided.period_events:
            if event["kind"] != "delivery":
                continue
            reference = str(event["reference"])
            if not event["backfill"]:
                first_delivery[reference] = period
                continue
            order = decided.tallies.supplier_orders[reference]
            path = f"suppliers.{order.supplier}.catalogue.{order.material}"
            delay = int(world.parameters[f"{path}.backfill_delay"])
            assert period == first_delivery[reference] + delay
            batch = (
                order.supplier,
                order.material,
                order.warehouse,
                order.placed,
                order.express,
            )
            totals = batches.setdefault(batch, [Decimal(0)] * 3)
            for position, key in enumerate(("ordered", "arrived", "accepted")):
                totals[position] += cast(Decimal, event[key])
        for (supplier, material, _, placed, express), totals in batches.items():
            ordered, arrived, accepted = totals
            outage = remaining(world, "supplier_outage", supplier, period)
            quality = remaining(world, "quality_drop", supplier, period)
            outcomes = world.express_deliveries if express else world.deliveries
            drawn = outcomes[f"{supplier}/{material}"][placed - 1]
            assert arrived == rounded(ordered * outage)
            assert accepted == rounded(arrived * drawn.acceptance * quality)


@pytest.mark.property
def test_backfills_are_reached():
    reached, drawn = count_reached(runs_with_a_backfill(), delivers_a_backfill)

    assert reached * 10 >= drawn, (reached, drawn)


@pytest.mark.property
@given(
    st.sampled_from(["supplier_outage", "quality_drop", "transport_delay"]),
    st.integers(min_value=1, max_value=8),
    st.integers(min_value=1, max_value=9999),
)
def test_a_disruption_acts_on_the_backfill_only_when_active_in_its_period(
    kind: str, start: int, effect: int
):
    disruption = chip_maker_disruption(kind, start)
    if kind == "transport_delay":
        # A delay from period 6 on can only meet the backfill, not the first delivery.
        disruption["start"] = max(start, 6)
        disruption["delay"] = 1 + effect % 3
    else:
        disruption["strength"] = str(Decimal(effect) / 10000)
    world = backfill_world(disruptions=[disruption])

    state = started(world, 7, BUY_IN_PERIOD_2)

    share = remaining(world, kind, "chip-maker", 7) if kind != "transport_delay" else 1
    arrived = rounded(Decimal(10) * share) if kind == "supplier_outage" else Decimal(10)
    [event] = deliveries(state)
    assert (event["arrived"], event["backfill"]) == (arrived, True)
    quality = share if kind == "quality_drop" else 1
    assert event["accepted"] == rounded(arrived * Decimal("0.98") * quality)


@pytest.mark.slow
def test_1000_orders_of_a_thousandth_deliver_the_units_of_one_order():
    world = backfill_world(
        completeness="0.6000",
        acceptance="1.0000",
        backfill_delay=0,
        max_quantity="1.000",
    )

    bulk = started(world, 5, BULK_BUY)
    split = started(world, 5, SPLIT_BUYS)

    # 1 * 0.6 = 0.6 arrive and are accepted, paid at 0.5000; 0.4 are lost.
    expected = {
        "arrived": Decimal("0.6"),
        "accepted": Decimal("0.6"),
        "lost": Decimal("0.4"),
        "payment": Decimal("0.3"),
        "stock": Decimal("100.6"),
    }
    assert delivered(bulk) == expected
    assert delivered(split) == expected


@pytest.mark.slow
def test_the_backfills_of_1000_orders_bring_the_units_of_one_backfill():
    world = backfill_world(completeness="0.6000", max_quantity="1.000")

    bulk = [started(world, period, BULK_BUY) for period in (5, 7)]
    split = [started(world, period, SPLIT_BUYS) for period in (5, 7)]

    # Period 5: 1 * 0.6 = 0.6 arrive, 0.6 * 0.98 = 0.588 are accepted and paid 0.294,
    # and 0.4 stay open. Period 7: 0.4 arrive, 0.4 * 0.98 = 0.392 are accepted and
    # paid 0.196.
    first = {
        "arrived": Decimal("0.6"),
        "accepted": Decimal("0.588"),
        "lost": Decimal(0),
        "payment": Decimal("0.294"),
        "stock": Decimal("100.588"),
    }
    backfill = {
        "arrived": Decimal("0.4"),
        "accepted": Decimal("0.392"),
        "lost": Decimal(0),
        "payment": Decimal("0.196"),
        "stock": Decimal("100.98"),
    }
    for states in (bulk, split):
        assert [delivered(state) for state in states] == [first, backfill]
        assert sum(open_quantities(states[0]).values()) == Decimal("0.4")
        assert states[1].supplier_orders == ()


def test_an_outage_holds_back_a_share_of_the_units_a_batch_sends():
    outage = chip_maker_disruption("supplier_outage", 5, strength="0.5000")
    world = backfill_world(
        disruptions=[outage], completeness="0.6000", acceptance="1.0000"
    )

    state = started(world, 5, {2: [buy("0.001")] * 3})

    # The batch so far sends 0.0006, 0.0012 and 0.0018, rounded 0.001, 0.001 and
    # 0.002, so the orders send 0.001, 0 and 0.001 and keep 0, 0.001 and 0 open. Half
    # of what the batch sent so far, 0.0005, 0.0005 and 0.001, rounds half to even to
    # 0, 0 and 0.001, so they get 0, 0 and 0.001 and lose 0.001, 0 and 0.
    assert deliveries(state) == [
        delivery("0.001", "0", "0", "0.001", "0", False) | {"reference": "buy-2-1"},
        delivery("0.001", "0", "0", "0", "0", False) | {"reference": "buy-2-2"},
        delivery("0.001", "0.001", "0.001", "0", "0.0005", False)
        | {"reference": "buy-2-3"},
    ]
    assert open_quantities(state) == {"buy-2-2": Decimal("0.001")}


@pytest.mark.slow
def test_a_batch_accepts_the_units_of_one_order_and_rounds_its_ties_once():
    world = backfill_world(
        completeness="1.0000", acceptance="0.6000", max_quantity="1.000"
    )
    tie_world = backfill_world(completeness="1.0000", acceptance="0.5000")

    bulk = started(world, 5, BULK_BUY)
    split = started(world, 5, SPLIT_BUYS)
    ties = started(tie_world, 5, {2: [buy("0.001")] * 3})

    # 1 * 0.6 = 0.6 accepted of 1 arrived, paid 0.3.
    for state in (bulk, split):
        assert delivered(state) == {
            "arrived": Decimal(1),
            "accepted": Decimal("0.6"),
            "lost": Decimal(0),
            "payment": Decimal("0.3"),
            "stock": Decimal("100.6"),
        }
    # Half of the 0.001, 0.002 and 0.003 arrived so far rounds half to even to 0,
    # 0.001 and 0.002, so the orders accept 0, 0.001 and 0.001.
    assert [event["accepted"] for event in deliveries(ties)] == [
        Decimal(0),
        Decimal("0.001"),
        Decimal("0.001"),
    ]


def test_each_placing_period_and_each_warehouse_is_a_batch_of_its_own():
    world = backfill_world(
        completeness="0.5000",
        backfill_delay=0,
        express_lead_time=1,
        express_cost="0.1000",
    )
    manifest = tiny_manifest()
    manifest["warehouses"]["spare"] = {"capacity": "10.000"}
    manifest["lines"]["line-1"]["warehouse"] = "main"
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["completeness"] = "0.5000"
    two_warehouses = draw_world_of_bodies(manifest, tiny_scenario())

    # Late by 1, a buy of period 2 arrives in period 5, as an express buy of period 3.
    periods = started(world, 5, {2: [buy("0.001")], 3: [buy("0.001", express=True)]})
    warehouses = started(
        two_warehouses,
        3,
        {1: [buy("0.001", warehouse="main"), buy("0.001", warehouse="spare")]},
    )

    # Each batch sends 0.001 * 0.5 = 0.0005, which rounds half to even to 0.
    for state in (periods, warehouses):
        assert [event["arrived"] for event in deliveries(state)] == [
            Decimal(0),
            Decimal(0),
        ]


def test_an_express_and_a_normal_order_arriving_in_one_period_are_two_batches():
    delay = chip_maker_disruption("transport_delay", 3, delay=1)
    world = backfill_world(
        disruptions=[delay],
        punctuality="1.0000",
        completeness="0.6000",
        backfill_delay=0,
        express_lead_time=1,
        express_cost="0.1000",
    )

    # Placed in period 2, the normal order arrives in period 2 + 2 and the express
    # order in period 2 + 1, moved by the transport delay to period 4.
    state = started(world, 4, {2: [buy("0.001"), buy("0.001", express=True)]})

    # Each batch sends 0.001 * 0.6 = 0.0006, which rounds to 0.001.
    assert [event["arrived"] for event in deliveries(state)] == [
        Decimal("0.001"),
        Decimal("0.001"),
    ]


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(
    st.decimals(min_value=0, max_value=1, places=4),
    st.decimals(min_value=0, max_value=1, places=4),
    st.decimals(min_value=0, max_value=1, places=4),
    st.sampled_from([5, 7]),
    st.sampled_from([0, 2]),
    st.lists(st.integers(min_value=1, max_value=1000), min_size=1, max_size=20),
)
def test_every_partition_of_a_buy_delivers_the_units_of_one_order(
    completeness: Decimal,
    acceptance: Decimal,
    strength: Decimal,
    outage_start: int,
    backfill_delay: int,
    parts: list[int],
):
    outage = chip_maker_disruption("supplier_outage", outage_start, strength=strength)
    world = backfill_world(
        disruptions=[outage],
        completeness=str(completeness),
        acceptance=str(acceptance),
        backfill_delay=backfill_delay,
    )
    thousandth = Decimal("0.001")
    bulk = {2: [buy(str(sum(parts) * thousandth))]}
    split = {2: [buy(str(part * thousandth)) for part in parts]}

    for period in (5, 7):
        one = started(world, period, bulk)
        many = started(world, period, split)
        assert delivered(many) == delivered(one)
        assert many.cash == one.cash
        assert sum(open_quantities(many).values()) == sum(open_quantities(one).values())
        for event in deliveries(many):
            assert 0 <= event["accepted"] <= event["arrived"] <= event["ordered"]
            assert event["lost"] >= 0


def test_an_express_order_shows_its_own_outcome_and_not_that_of_the_normal_order():
    world = example_world("steady-market", 0)

    express_arrived = started(world, 2, KIT_BUYS)
    normal_arrived = started(world, 3, KIT_BUYS)

    # The express stream of period 1 draws u = 0.6895, 0.2200, 0.2330 and 0.5701. On
    # time, as 0.6895 < 0.9073, the order arrives in period 1 + 1. Completeness
    # 0.95 + 0.05 * 0.2330 = 0.9616 sends 0.962, the rest 0.038 is its backfill, and
    # acceptance 0.97 + 0.03 * 0.5701 = 0.9871 accepts 0.962 * 0.9871 = 0.9496, so
    # 0.950, paid at 2.4332 + 0.6000 = 3.0332.
    assert deliveries(express_arrived) == [
        kit_delivery("buy-1-2", "0.962", "0.950", "2.88154")
    ]
    # The normal stream of period 1 draws u = 0.3953, 0.3876, 0.3141 and 0.6463. On
    # time, as 0.3953 < 0.9073, the order arrives in period 1 + 2. Completeness
    # 0.95 + 0.05 * 0.3141 = 0.9657 sends 0.966, and acceptance 0.97 + 0.03 * 0.6463 =
    # 0.9894 accepts 0.966 * 0.9894 = 0.9558, so 0.956, paid at 2.4332. The backfill of
    # the express order, 0.038 at acceptance 0.9871, accepts 0.0375, so 0.038.
    assert deliveries(normal_arrived) == [
        kit_delivery("buy-1-1", "0.966", "0.956", "2.3261392"),
        kit_delivery("buy-1-2", "0.038", "0.038", "0.1152616", backfill=True),
    ]
