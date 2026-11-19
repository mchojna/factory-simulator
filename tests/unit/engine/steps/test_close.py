from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, cast

import pytest
from factories import (
    FactoryBodies,
    RunStep,
    acting_factor,
    centre_world,
    closed_period,
    closed_periods,
    decide,
    draw_world_of_bodies,
    drawn_run,
    drawn_runs,
    example_count,
    first_period,
    monitor_world,
    produce,
    seeds,
    ship,
    small_factories,
    submission,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.engine import (
    Decisions,
    Produce,
    State,
    World,
    advance_period,
    build_state,
    compute_salvage,
    start_period,
)

MONITORS_IN_PERIOD_3 = {3: [produce("monitor", "10")]}


def one_starting_order(patience: int, due: int) -> World:
    manifest = tiny_manifest()
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms["demand"] = "0.000"
    terms["patience"] = patience
    scenario = tiny_scenario()
    scenario["start"]["customer_orders"] = [
        {"customer": "distributor", "product": "monitor", "quantity": "3", "due": due}
    ]
    return draw_world_of_bodies(manifest, scenario)


def penalties(state: State) -> list[tuple[str, Decimal, str]]:
    return [
        (row.kind, row.amount, row.reference)
        for row in state.ledger
        if row.kind in ("late_penalty", "lost_sale_penalty")
    ]


# Horizon 3; chip at price 5 and salvage value 2, monitor at salvage value 10, made
# and sent with lead time 2.
def end_world() -> World:
    manifest = tiny_manifest()
    manifest["materials"]["chip"]["salvage_value"] = "2.0000"
    manifest["products"]["monitor"]["salvage_value"] = "10.0000"
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["price"] = "5.0000"
    manifest["lines"]["line-1"]["items"]["monitor"]["lead_time"] = 2
    manifest["warehouses"]["centre"] = {"capacity": "50.000", "accepts": ["products"]}
    manifest["lines"]["line-1"]["warehouse"] = "main"
    manifest["routes"] = {"main": {"centre": {"cost": "0.2000", "lead_time": 2}}}
    scenario = tiny_scenario()
    scenario["horizon"] = 3
    scenario["start"]["stock"] = {
        "main": {"chip": "100", "board": "10", "monitor": "10"},
        "centre": {},
    }
    return draw_world_of_bodies(manifest, scenario)


# The end of a run that makes decisions in period 3 only.
def end_of_run(world: World, last: list[dict[str, Any]]) -> State:
    state = start_period(build_state(world), world)
    while True:
        decisions = submission(state.period, last if state.period == 3 else [])
        state = advance_period(state, world, decisions)
        if state.finished:
            return state
        state = start_period(state, world)


def storage(state: State, item_id: str) -> list[tuple[str, Decimal]]:
    return [
        (row.reference, row.amount)
        for row in state.ledger
        if row.kind == "storage_cost" and row.reference.endswith(f"/{item_id}")
    ]


def yield_drop(start: int, strength: str = "0.2000") -> dict[str, Any]:
    return {
        "kind": "yield_drop",
        "target": ["line-1"],
        "start": start,
        "duration": 1,
        "strength": strength,
    }


def breakdown(start: int) -> dict[str, Any]:
    return {"kind": "line_breakdown", "target": ["line-1"], "start": start, "loss": "1"}


def finished(state: State) -> list[tuple[Any, Any, Any]]:
    return [
        (event["reference"], event["good"], event["scrap"])
        for event in state.period_events
        if event["kind"] == "production_finished"
    ]


def finished_in_4(
    quantity: str = "10", disruptions: list[dict[str, Any]] | None = None
) -> list[tuple[Any, Any, Any]]:
    world = monitor_world(disruptions=disruptions)
    return finished(closed_period(world, 4, {3: [produce("monitor", quantity)]}))


def places(value: Decimal) -> int:
    return max(0, -cast(int, value.normalize().as_tuple().exponent))


# The good units of each batch of one line, item and start period follow its yield;
# each production of a batch has good units and scrap of at most 3 places.
def check_good_units(world: World, steps: list[RunStep]) -> None:
    started: dict[str, tuple[int, Produce]] = {}

    for decided, _, closed_state in steps:
        for outcome in closed_state.outcomes:
            if outcome.accepted and isinstance(outcome.decision, Produce):
                started[str(outcome.reference)] = (decided.period, outcome.decision)
        batches: dict[tuple[str, str, int], tuple[Decimal, Decimal]] = {}
        for event in closed_state.period_events:
            if event["kind"] != "production_finished":
                continue
            start, decision = started[str(event["reference"])]
            good = cast(Decimal, event["good"])
            scrap = cast(Decimal, event["scrap"])
            assert scrap == decision.quantity - good
            assert good >= 0 and scrap >= 0
            assert places(good) <= 3 and places(scrap) <= 3
            batch = (decision.line, decision.item, start)
            units, good_so_far = batches.get(batch, (Decimal(0), Decimal(0)))
            batches[batch] = (units + decision.quantity, good_so_far + good)
        for (line_id, item_id, start), (units, good) in batches.items():
            drawn = world.yields[f"{line_id}/{item_id}"][start - 1]
            share = drawn * acting_factor(world, "yield_drop", line_id, start, cut=True)
            assert good == (units * share).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_EVEN
            )


def lost_sales(state: State) -> list[tuple[object, ...]]:
    return [
        (event["reference"], event["quantity"], event["amount"], event["at_end"])
        for event in state.period_events
        if event["kind"] == "lost_sale"
    ]


# The tiny factory with the yield of every item of `line-1` set to one value.
def yield_world(share: str) -> World:
    manifest = tiny_manifest()
    for line_item in manifest["lines"]["line-1"]["items"].values():
        line_item["yield"] = share
    return draw_world_of_bodies(manifest, tiny_scenario())


def good_of(state: State, item_id: str) -> Decimal:
    return sum(
        (
            cast(Decimal, event["good"])
            for event in state.period_events
            if event["kind"] == "production_finished" and event["item"] == item_id
        ),
        Decimal(0),
    )


def test_an_order_with_patience_0_is_lost_at_the_close_of_its_due_period():
    closed = closed_periods(one_starting_order(patience=0, due=1), {})

    assert penalties(closed[0]) == [("lost_sale_penalty", Decimal("-30"), "order-0-1")]
    assert closed[0].customer_orders == ()


def test_an_order_pays_late_penalties_from_its_due_period_and_is_lost_in_its_last():
    closed = closed_periods(one_starting_order(patience=2, due=1), {})

    assert [penalties(state) for state in closed[:4]] == [
        [("late_penalty", Decimal("-6"), "order-0-1")],
        [("late_penalty", Decimal("-6"), "order-0-1")],
        [("lost_sale_penalty", Decimal("-30"), "order-0-1")],
        [],
    ]


def test_an_order_unshipped_at_the_close_of_its_due_period_pays_one_late_penalty():
    closed = closed_periods(one_starting_order(patience=1, due=1), {})

    assert [penalties(state) for state in closed[:2]] == [
        [("late_penalty", Decimal("-6"), "order-0-1")],
        [("lost_sale_penalty", Decimal("-30"), "order-0-1")],
    ]


def test_an_order_due_in_the_last_period_is_lost_at_the_end_of_the_run():
    closed = closed_periods(one_starting_order(patience=3, due=5), {})

    assert [penalties(state) for state in closed] == [
        [],
        [],
        [],
        [],
        [("lost_sale_penalty", Decimal("-30"), "order-0-1")],
    ]
    assert closed[-1].finished


def test_the_end_of_the_run_loses_the_orders_due_before_their_last_period():
    manifest = tiny_manifest()
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms |= {"lead_time": 2, "patience": 3}
    scenario = tiny_scenario()
    scenario["horizon"] = 3
    scenario["start"]["customer_orders"] = [
        {"customer": "distributor", "product": "monitor", "quantity": "100", "due": 2}
    ]
    world = draw_world_of_bodies(manifest, scenario)

    closed = closed_periods(world, {1: [ship("order-0-1", "5")]})

    assert [lost_sales(state) for state in closed[:2]] == [[], []]
    # order-0-1 is due 2 and lasts to 5, order-1-1 due 3 and lasts to 6; both lose
    # their units at the close of the horizon, 3, at a lost-sale penalty of 10.
    assert lost_sales(closed[2]) == [
        ("order-0-1", Decimal(95), Decimal(950), True),
        ("order-1-1", Decimal(4), Decimal(40), True),
    ]


@pytest.mark.parametrize(("patience", "due"), [(0, 1), (2, 1), (1, 4)])
def test_an_order_lost_in_its_last_period_is_not_lost_at_the_end(
    patience: int, due: int
):
    closed = closed_periods(one_starting_order(patience=patience, due=due), {})

    last = closed[due + patience - 1]
    assert lost_sales(last) == [("order-0-1", Decimal(3), Decimal(30), False)]


def test_storage_of_the_starting_stock_is_stock_times_storage_cost():
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    closed = closed_periods(draw_world_of_bodies(manifest, tiny_scenario()), {})

    storage_rows = [
        (row.reference, row.amount)
        for row in closed[0].ledger
        if row.kind == "storage_cost"
    ]
    assert storage_rows == [
        ("main/board", Decimal("-0.1")),
        ("main/chip", Decimal("-0.2")),
        ("main/monitor", Decimal("-0.5")),
    ]


def test_lost_sale_with_penalty_0_has_its_event_and_no_ledger_row():
    manifest = tiny_manifest()
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms["demand"] = "0.000"
    terms["patience"] = 0
    terms["lost_sale_penalty"] = "0.0000"
    scenario = tiny_scenario()
    scenario["start"]["customer_orders"] = [
        {"customer": "distributor", "product": "monitor", "quantity": "3", "due": 1}
    ]
    world = draw_world_of_bodies(manifest, scenario)

    closed = advance_period(
        start_period(build_state(world), world), world, Decisions(period=1)
    )

    assert [
        dict(event) for event in closed.period_events if event["kind"] == "lost_sale"
    ] == [
        {
            "kind": "lost_sale",
            "step": "close_period",
            "reference": "order-0-1",
            "quantity": Decimal("3.000"),
            "amount": Decimal("0"),
            "at_end": False,
        }
    ]
    assert [row for row in closed.ledger if row.kind == "lost_sale_penalty"] == []


def test_a_buy_arriving_after_the_horizon_is_never_paid_and_worth_nothing():
    world = end_world()
    chips = {
        "kind": "buy",
        "supplier": "chip-maker",
        "material": "chip",
        "quantity": "10",
        "warehouse": "main",
    }

    end = end_of_run(world, [chips])

    assert [order.id for order in end.supplier_orders] == ["buy-3-1"]
    assert [row for row in end.ledger if row.kind == "material_payment"] == []
    assert end.measures["stock_salvage_value"]["warehouses.main/chip"] == 200
    assert compute_salvage(end, world) == Decimal("305")


def test_production_not_in_stock_at_the_end_is_worth_nothing():
    world = end_world()
    monitors = {"kind": "produce", "line": "line-1", "item": "monitor", "quantity": "4"}

    end = end_of_run(world, [monitors])

    assert [production.id for production in end.production] == ["make-3-1"]
    assert end.stock["main"]["board"] == 2
    assert end.measures["stock_salvage_value"]["warehouses.main/monitor"] == 100
    assert compute_salvage(end, world) == Decimal("301")


def test_a_transfer_on_the_way_at_the_end_is_worth_nothing():
    world = end_world()
    sent = {
        "kind": "transfer",
        "item": "monitor",
        "quantity": "6",
        "source": "main",
        "destination": "centre",
    }

    end = end_of_run(world, [sent])

    assert [moving.quantity for moving in end.transfers] == [6]
    assert end.measures["stock_salvage_value"]["warehouses.main/monitor"] == 40
    assert end.measures["stock_salvage_value"]["warehouses.centre"] == 0
    assert compute_salvage(end, world) == Decimal("245")


def test_storage_at_close_pays_the_storage_factor_of_each_warehouse():
    world = centre_world(
        centre_stock={"monitor": "10"},
        main_stock={"monitor": "10"},
        storage_factor="0.6000",
    )

    state = first_period(world, [])

    assert storage(state, "monitor") == [
        ("centre/monitor", Decimal("-0.6")),
        ("main/monitor", Decimal("-1")),
    ]


def test_production_over_two_periods_holds_space_and_ignores_a_later_breakdown():
    world = monitor_world(disruptions=[breakdown(4)])

    period_3 = closed_period(world, 3, MONITORS_IN_PERIOD_3)
    period_4 = start_period(period_3, world)
    closed_4 = decide(period_4, world, [])

    assert finished(period_3) == []
    assert [made.id for made in period_3.production] == ["make-3-1"]
    assert period_4.observation is not None
    assert period_4.observation.space["main"].reserved == Decimal("1.500")
    assert period_4.condition["line-1"] == 0
    assert finished(closed_4) == [("make-3-1", Decimal("9.5"), Decimal("0.5"))]


def test_a_yield_drop_active_at_the_start_lowers_the_good_units():
    assert finished_in_4(disruptions=[yield_drop(3)]) == [
        ("make-3-1", Decimal("7.6"), Decimal("2.4"))
    ]
    assert finished_in_4(
        disruptions=[yield_drop(3, "0.5000"), yield_drop(3, "0.5000")]
    ) == [("make-3-1", Decimal("2.375"), Decimal("7.625"))]


def test_good_units_round_to_3_places():
    assert finished_in_4("10.001") == [("make-3-1", Decimal("9.501"), Decimal("0.5"))]
    assert finished_in_4("10.001", [yield_drop(3)]) == [
        ("make-3-1", Decimal("7.601"), Decimal("2.4"))
    ]


def test_good_units_on_a_tie_round_to_the_even_last_place():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"]["items"]["monitor"].update(**{"yield": "0.5000"})
    world = draw_world_of_bodies(manifest, tiny_scenario())
    one = closed_period(world, 1, {1: [produce("monitor", "0.001")]})
    three = closed_period(world, 1, {1: [produce("monitor", "0.003")]})

    assert finished(one) == [("make-1-1", Decimal("0.000"), Decimal("0.001"))]
    assert finished(three) == [("make-1-1", Decimal("0.002"), Decimal("0.001"))]


@pytest.mark.slow
def test_a_batch_of_1000_productions_gives_the_good_units_of_one_production():
    world = yield_world("0.6000")
    one = closed_period(world, 1, {1: [produce("board", "1.000")]})
    split = closed_period(world, 1, {1: [produce("board", "0.001")] * 1000})

    assert good_of(one, "board") == Decimal("0.600")
    assert good_of(split, "board") == Decimal("0.600")
    assert split.stock["main"]["board"] == one.stock["main"]["board"] == Decimal("10.6")
    assert finished(split)[:3] == [
        ("make-1-1", Decimal("0.001"), Decimal("0")),
        ("make-1-2", Decimal("0"), Decimal("0.001")),
        ("make-1-3", Decimal("0.001"), Decimal("0")),
    ]


def test_a_batch_rounds_its_ties_once_to_the_even_last_place():
    world = yield_world("0.5000")
    state = closed_period(world, 1, {1: [produce("monitor", "0.001")] * 3})

    assert finished(state) == [
        ("make-1-1", Decimal("0"), Decimal("0.001")),
        ("make-1-2", Decimal("0.001"), Decimal("0")),
        ("make-1-3", Decimal("0.001"), Decimal("0")),
    ]
    assert good_of(state, "monitor") == Decimal("0.002")


def test_each_item_and_each_start_period_is_a_batch_of_its_own():
    world = yield_world("0.5000")
    decisions = {
        1: [produce("board", "0.001"), produce("monitor", "0.001")] * 2,
        2: [produce("board", "0.001")],
    }
    period_1 = closed_period(world, 1, decisions)
    period_2 = closed_period(world, 2, decisions)

    assert finished(period_1) == [
        ("make-1-1", Decimal("0"), Decimal("0.001")),
        ("make-1-2", Decimal("0"), Decimal("0.001")),
        ("make-1-3", Decimal("0.001"), Decimal("0")),
        ("make-1-4", Decimal("0.001"), Decimal("0")),
    ]
    assert finished(period_2) == [("make-2-1", Decimal("0"), Decimal("0.001"))]


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(
    st.decimals(min_value=0, max_value=1, places=4),
    st.lists(st.integers(min_value=1, max_value=1000), min_size=1, max_size=20),
)
def test_every_partition_of_a_batch_gives_the_good_units_of_one_production(
    share: Decimal, parts: list[int]
):
    world = yield_world(str(share))
    total = sum(parts)
    thousandth = Decimal("0.001")
    one = closed_period(world, 1, {1: [produce("board", str(total * thousandth))]})
    split = closed_period(
        world, 1, {1: [produce("board", str(part * thousandth)) for part in parts]}
    )

    assert good_of(split, "board") == good_of(one, "board")
    assert split.stock["main"]["board"] == one.stock["main"]["board"]
    for _, good, scrap in finished(split):
        assert good >= 0 and scrap >= 0


def test_a_yield_drop_active_only_after_the_start_changes_nothing():
    assert finished_in_4(disruptions=[yield_drop(4)]) == [
        ("make-3-1", Decimal("9.5"), Decimal("0.5"))
    ]


def test_production_can_be_shipped_only_after_the_close_of_its_ready_period():
    world = monitor_world(lead_time=3, monitors="0")
    decisions = {
        2: [produce("monitor", "10")],
        4: [ship("order-4-1", "4")],
        5: [ship("order-5-1", "4")],
    }

    period_4 = closed_period(world, 4, decisions)
    period_5 = closed_period(world, 5, decisions)

    assert finished(period_4) == [("make-2-1", Decimal("9.5"), Decimal("0.5"))]
    assert [
        outcome.reason
        for outcome in period_4.outcomes
        if outcome.decision.kind == "ship"
    ] == ["not_enough_stock"]
    assert [
        outcome.accepted
        for outcome in period_5.outcomes
        if outcome.decision.kind == "ship"
    ] == [True]


def test_production_ready_after_the_horizon_never_enters_stock():
    world = monitor_world(lead_time=3)
    last = closed_period(world, 6, {5: [produce("monitor", "2")]})

    assert last.finished
    assert [made.ready for made in last.production] == [7]
    assert last.stock["main"]["monitor"] == Decimal(5)
    assert last.tallies.running["units_good"]["lines.line-1"] == 0
    assert last.tallies.running["units_scrap"]["lines.line-1"] == 0


@pytest.mark.property
@given(
    st.integers(min_value=1, max_value=4),
    st.integers(min_value=1, max_value=3),
    st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("0.9999"), places=4),
    st.sampled_from([["line-1"], "all"]),
    st.integers(min_value=1, max_value=4),
)
def test_a_yield_drop_acts_on_production_started_while_it_is_active(
    drop_start: int, duration: int, strength: Decimal, target: object, made: int
):
    drop = {
        "kind": "yield_drop",
        "target": target,
        "start": drop_start,
        "duration": duration,
        "strength": str(strength),
    }
    world = monitor_world(lead_time=2, horizon=6, disruptions=[drop])
    state = closed_period(world, made + 1, {made: [produce("monitor", "10")]})

    active = drop_start <= made < drop_start + duration
    share = Decimal("0.9500") * ((1 - strength) if active else 1)
    good = (10 * share).quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN)
    assert finished(state) == [(f"make-{made}-1", good, Decimal(10) - good)]


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_good_units_follow_the_yield_and_the_yield_drops_of_the_start_period(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    check_good_units(*drawn_run(factory, seed, data.draw))


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_a_breakdown_never_changes_production_already_started(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    for line in manifest["lines"].values():
        line["breakdown_chance"] = "0.5000"
        for terms in line["items"].values():
            terms["lead_time"] = data.draw(st.sampled_from([2, 3]))
    check_good_units(*drawn_run((manifest, scenario), seed, data.draw))


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(drawn_runs())
def test_every_order_pays_its_late_penalty_from_its_due_period(
    run: tuple[World, list[RunStep]],
):
    world, steps = run

    for decided, _, closed_state in steps:
        period = decided.period
        booked: dict[str, Decimal] = {}
        for row in closed_state.ledger:
            if row.kind == "late_penalty":
                booked[row.reference] = booked.get(row.reference, 0) + row.amount
        open_after = {order.id: order for order in closed_state.customer_orders}
        for order in decided.customer_orders:
            path = f"customers.{order.customer}.products.{order.product}"
            # An order still open after the close of a period from its due period
            # pays for the units not shipped; the close that loses it pays none.
            expected = Decimal(0)
            if order.id in open_after and period >= order.due:
                missing = order.quantity - open_after[order.id].shipped
                expected = -missing * world.parameters[f"{path}.late_penalty"]
            assert booked.get(order.id, Decimal(0)) == expected


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_started_units_are_good_scrap_or_not_yet_in_stock_at_the_end(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world, steps = drawn_run(factory, seed, data.draw)
    last = steps[-1][2]
    running = last.tallies.running

    for line_id, line in world.factory.lines.items():
        for item_id in line.items:
            key = f"lines.{line_id}/{item_id}"
            waiting = sum(
                (
                    made.started
                    for made in last.production
                    if (made.line, made.item) == (line_id, item_id)
                ),
                Decimal(0),
            )
            assert running["units_started"][key] == (
                running["units_good"][key] + running["units_scrap"][key] + waiting
            )
