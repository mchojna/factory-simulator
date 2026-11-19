from decimal import Decimal
from typing import Any

import pytest
from factories import (
    FactoryBodies,
    buy,
    cancel,
    closed_period,
    closed_periods,
    decide,
    draw_world_of_bodies,
    drawn_run,
    example_count,
    numbered_outcomes,
    outcome_numbers,
    plan_world,
    produce,
    seeds,
    small_factories,
    starting_chips_scenario,
    supplier_orders_of,
    tiered_chip_world,
    tiny_manifest,
    tiny_scenario,
    unwanted_order_bodies,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.engine import (
    Buy,
    Cancel,
    State,
    World,
    build_state,
    compute_profit,
    start_period,
)


def chip_world(scenario: dict[str, Any] | None = None, **terms: str) -> World:
    manifest = tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"].update(
        {"lead_time": 3, "cancellation_fee": "0.1000"} | terms
    )
    return draw_world_of_bodies(manifest, scenario or tiny_scenario())


def with_starting_chips(quantity: str, cash: str = "1000") -> dict[str, Any]:
    scenario = tiny_scenario()
    scenario["start"]["cash"] = cash
    scenario["start"]["supplier_orders"] = [
        {
            "supplier": "chip-maker",
            "material": "chip",
            "quantity": quantity,
            "arrival": 3,
        }
    ]
    return scenario


def run_through(
    world: World, period: int, decisions: dict[int, list[dict[str, Any]]]
) -> State:
    state = build_state(world)
    while state.period < period:
        state = start_period(state, world)
        state = decide(state, world, decisions.get(state.period, []))
    return state


def open_quantities(state: State) -> dict[str, Decimal]:
    return {order.id: order.open_quantity for order in state.supplier_orders}


def rejection(state: State) -> tuple[str | None, Decimal | None, Decimal | None]:
    outcome = [
        outcome for outcome in state.outcomes if outcome.decision.kind == "cancel"
    ][-1]
    assert not outcome.accepted
    return outcome.reason, outcome.asked, outcome.available


def after_cancels(
    quantity: str, *cancels: str, min_quantity: str | None = None
) -> State:
    world = tiered_chip_world(min_quantity=min_quantity)
    decisions = {
        1: [buy(quantity)],
        2: [cancel("buy-1-1", cancelled) for cancelled in cancels],
    }
    return closed_period(world, 2, decisions)


def deliveries(state: State) -> list[Decimal]:
    return [
        Decimal(str(event["accepted"]))
        for event in state.period_events
        if event["kind"] == "delivery"
    ]


def fees(state: State) -> Decimal:
    rows = [row.amount for row in state.ledger if row.kind == "cancellation_fee"]
    return -sum(rows, Decimal(0))


def test_a_cancellation_before_delivery_costs_its_fee_and_leaves_the_rest_open():
    world = chip_world()

    state = run_through(world, 3, {2: [buy("100")], 3: [cancel("buy-2-1", "60")]})

    assert open_quantities(state) == {"buy-2-1": Decimal("40.000")}
    fee_rows = [row for row in state.ledger if row.kind == "cancellation_fee"]
    assert [(row.amount, row.reference) for row in fee_rows] == [
        (Decimal("-6.0000"), "cancel-3-1")
    ]
    assert [(outcome.accepted, outcome.reference) for outcome in state.outcomes] == [
        (True, "cancel-3-1")
    ]


def test_only_the_open_quantity_is_reserved_arrives_and_is_paid_for():
    world = chip_world()
    decisions = {2: [buy("100")], 3: [cancel("buy-2-1", "60")]}

    state = start_period(run_through(world, 3, decisions), world)
    assert state.observation is not None
    assert state.observation.space["main"].reserved == Decimal("0.400")

    state = start_period(decide(state, world, []), world)
    arrivals = [event for event in state.period_events if event["kind"] == "delivery"]
    assert [
        (event["ordered"], event["arrived"], event["accepted"]) for event in arrivals
    ] == [(Decimal("40.000"), Decimal("40.000"), Decimal("40.000"))]
    payments = [row for row in state.ledger if row.kind == "material_payment"]
    assert [(row.amount, row.reference) for row in payments] == [
        (Decimal("-20.0000"), "buy-2-1")
    ]
    assert state.supplier_orders == ()


def test_cancelling_the_whole_open_quantity_closes_the_order():
    world = chip_world()
    decisions = {2: [buy("100")], 3: [cancel("buy-2-1", "100")]}

    state = run_through(world, 3, decisions)
    assert state.supplier_orders == ()
    fee_amounts = [row.amount for row in state.ledger if row.kind == "cancellation_fee"]
    assert fee_amounts == [Decimal("-10.0000")]

    state = run_through(world, 5, decisions)
    assert [event for event in state.period_events if event["kind"] == "delivery"] == []


def test_a_cancellation_fee_of_0_writes_no_ledger_row():
    world = chip_world(cancellation_fee="0.0000")

    state = run_through(world, 3, {2: [buy("100")], 3: [cancel("buy-2-1", "60")]})

    assert open_quantities(state) == {"buy-2-1": Decimal("40.000")}
    assert [row for row in state.ledger if row.kind == "cancellation_fee"] == []


@pytest.mark.parametrize(
    ("decisions", "period"),
    [
        ({3: [cancel("buy-9-9", "1")]}, 3),
        ({1: [buy("100")], 4: [cancel("buy-1-1", "1")]}, 4),
        ({3: [cancel("ship-1-1", "1")]}, 3),
        ({3: [cancel("make-2-1")]}, 3),
        ({3: [buy("100"), cancel("buy-3-1", "1")]}, 3),
    ],
    ids=["missing", "delivered", "shipment", "plan", "placed-in-the-same-period"],
)
def test_a_cancel_of_no_open_supplier_order_is_an_unknown_order(
    decisions: dict[int, list[dict[str, Any]]], period: int
):
    state = run_through(chip_world(), period, decisions)

    assert rejection(state) == ("unknown_order", None, None)


def test_a_cancel_of_a_supplier_order_without_quantity_is_a_wrong_quantity():
    state = run_through(chip_world(), 3, {2: [buy("100")], 3: [cancel("buy-2-1")]})

    assert rejection(state) == ("wrong_quantity", None, None)


def test_a_cancel_above_the_open_quantity_is_over_open_quantity():
    decisions = {
        2: [buy("100")],
        3: [cancel("buy-2-1", "60"), cancel("buy-2-1", "50")],
    }

    state = run_through(chip_world(), 3, decisions)

    assert rejection(state) == (
        "over_open_quantity",
        Decimal("50.000"),
        Decimal("40.000"),
    )


def test_a_starting_supplier_order_can_be_cancelled_and_delivers_the_rest():
    world = chip_world(with_starting_chips("1000"))
    decisions = {1: [cancel("buy-0-1", "400")]}

    state = start_period(run_through(world, 2, decisions), world)

    arrivals = [event for event in state.period_events if event["kind"] == "delivery"]
    assert [(event["arrived"], event["accepted"]) for event in arrivals] == [
        (Decimal("600.000"), Decimal("600.000"))
    ]


def test_a_cancel_is_accepted_with_cash_below_minus_the_credit_limit():
    world = chip_world(with_starting_chips("100", cash="-500"))

    state = run_through(world, 1, {1: [cancel("buy-0-1", "100")]})

    assert [(outcome.accepted, outcome.reference) for outcome in state.outcomes] == [
        (True, "cancel-1-1")
    ]
    # -500 - fee 100 * 0.1000 - storage 10 * 0.0100 + 100 * 0.0020 + 5 * 0.1000 -
    # late penalty of order-1-1 4 * 2.0000 is -518.8000; interest 518.8000 * 0.0005 =
    # 0.2594 at a credit limit of 0.
    assert state.cash == Decimal("-519.0594")


def test_a_cancel_may_not_take_an_order_below_the_from_of_its_tier():
    rejected = after_cancels("1200", "300")
    accepted = after_cancels("1200", "200")
    whole = after_cancels("1200", "1200")

    assert outcome_numbers(rejected) == [
        (False, "below_discount_tier", Decimal("300.000"), Decimal("200.000"))
    ]
    assert outcome_numbers(accepted) == [(True, None, None, None)]
    assert [order.unit_price for order in accepted.supplier_orders] == [
        Decimal("4.6000")
    ]
    assert outcome_numbers(whole) == [(True, None, None, None)]
    assert whole.supplier_orders == ()


def test_an_order_at_the_from_of_its_tier_can_only_be_cancelled_in_full():
    assert outcome_numbers(after_cancels("1000", "1000")) == [(True, None, None, None)]
    assert outcome_numbers(after_cancels("1000", "1")) == [
        (False, "below_discount_tier", Decimal("1.000"), Decimal("0.000"))
    ]


def test_the_tier_counts_the_quantity_ordered_not_what_arrived():
    world = tiered_chip_world(completeness="0.9000", backfill_delay=2)
    arrived = closed_period(world, 3, {1: [buy("1100")]})

    kept = closed_period(world, 4, {1: [buy("1100")], 4: [cancel("buy-1-1", "100")]})
    below = closed_period(world, 4, {1: [buy("1100")], 4: [cancel("buy-1-1", "101")]})

    assert deliveries(arrived) == [Decimal("990.000")]
    assert outcome_numbers(kept) == [(True, None, None, None)]
    assert outcome_numbers(below) == [
        (False, "below_discount_tier", Decimal("101.000"), Decimal("100.000"))
    ]


def test_the_whole_open_backfill_of_an_order_at_its_tier_can_be_cancelled():
    world = tiered_chip_world(completeness="0.9000", backfill_delay=2)

    whole = closed_period(world, 4, {1: [buy("1000")], 4: [cancel("buy-1-1", "100")]})
    part = closed_period(world, 4, {1: [buy("1000")], 4: [cancel("buy-1-1", "50")]})

    assert outcome_numbers(whole) == [(True, None, None, None)]
    assert whole.supplier_orders == ()
    assert outcome_numbers(part) == [
        (False, "below_discount_tier", Decimal("50.000"), Decimal("0.000"))
    ]


def test_cancelling_the_open_backfill_at_a_tier_pays_its_fee_and_ends_the_order():
    world = tiered_chip_world(
        completeness="0.9000", backfill_delay=2, cancellation_fee="0.1000"
    )
    decisions = {1: [buy("1000")], 4: [cancel("buy-1-1", "100")]}

    payments = closed_period(world, 3, decisions).ledger
    assert [row.amount for row in payments if row.kind == "material_payment"] == [
        Decimal("-4140")
    ]
    assert fees(closed_period(world, 4, decisions)) == Decimal("10")
    later = [closed_period(world, period, decisions) for period in range(5, 9)]
    assert [deliveries(state) for state in later] == [[], [], [], []]


def test_the_whole_open_backfill_of_an_order_at_its_minimum_can_be_cancelled():
    world = tiered_chip_world(
        completeness="0.9000", backfill_delay=2, min_quantity="500.000"
    )

    state = closed_period(world, 4, {1: [buy("500")], 4: [cancel("buy-1-1", "50")]})

    assert outcome_numbers(state) == [(True, None, None, None)]
    assert state.supplier_orders == ()


def test_a_cancel_may_not_take_an_order_below_the_min_quantity():
    assert outcome_numbers(after_cancels("800", "400", min_quantity="500.000")) == [
        (False, "below_min_quantity", Decimal("400.000"), Decimal("500.000"))
    ]
    assert outcome_numbers(after_cancels("800", "300", min_quantity="500.000")) == [
        (True, None, None, None)
    ]
    assert outcome_numbers(after_cancels("800", "800", min_quantity="500.000")) == [
        (True, None, None, None)
    ]


def test_an_order_at_its_min_quantity_can_only_be_cancelled_in_full():
    assert outcome_numbers(after_cancels("500", "500", min_quantity="500.000")) == [
        (True, None, None, None)
    ]
    assert outcome_numbers(after_cancels("500", "1", min_quantity="500.000")) == [
        (False, "below_min_quantity", Decimal("499.000"), Decimal("500.000"))
    ]


def test_a_starting_supplier_order_is_not_checked_against_the_min_quantity():
    world = tiered_chip_world(starting_chips_scenario("1200"), min_quantity="1000.000")

    state = closed_period(world, 1, {1: [cancel("buy-0-1", "400")]})

    assert outcome_numbers(state) == [(True, None, None, None)]
    assert {order.id: order.open_quantity for order in state.supplier_orders} == {
        "buy-0-1": Decimal("800.000")
    }


# Kept, the 10 chips cost 10 * 0.5 = 5 on arrival and are worth 10 * 0.1 = 1 at the
# end: -4. Cancelled in period 1 without a fee they cost nothing: 0. A fee of 0.4500
# a chip costs 10 * 0.45 = 4.5, more than keeping them loses.
@pytest.mark.parametrize(
    ("fee", "kept", "cancelled"),
    [("0.0000", "-4", "0"), ("0.4500", "-4", "-4.5")],
)
def test_cancelling_an_unwanted_starting_order_earns_its_cost_less_salvage_and_fee(
    fee: str, kept: str, cancelled: str
):
    manifest, scenario = unwanted_order_bodies()
    chip = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    chip["cancellation_fee"] = fee
    world = draw_world_of_bodies(manifest, scenario)

    kept_run = closed_periods(world, {})
    cancelled_run = closed_periods(world, {1: [cancel("buy-0-1", "10")]})

    assert compute_profit(kept_run[-1], world) == Decimal(kept)
    assert compute_profit(cancelled_run[-1], world) == Decimal(cancelled)
    assert deliveries(kept_run[1]) == [Decimal(10)]
    assert deliveries(cancelled_run[1]) == []


def test_a_cancel_removes_a_plan_without_a_fee_or_a_trace():
    world = plan_world()
    plan = {2: [produce("board", "10", start=4)]}

    in_3 = closed_period(world, 3, plan | {3: [cancel("make-2-1")]})
    in_4 = closed_period(world, 4, plan | {4: [cancel("make-2-1")]})

    assert numbered_outcomes(in_3) == [("3-1", True, "cancel-3-1", None, None, None)]
    assert in_3.plans == ()
    assert in_3.ledger == closed_period(world, 3, plan).ledger
    assert [
        event for event in in_3.period_events if event["step"] == "execute_decisions"
    ] == []
    assert numbered_outcomes(in_4) == [("4-1", True, "cancel-4-1", None, None, None)]
    assert in_4.tallies.running["units_started"]["lines.line-1"] == 0


def test_a_cancel_of_a_plan_with_a_quantity_or_of_no_plan_is_rejected():
    world = plan_world()
    plan = {2: [produce("board", "10", start=4), cancel("make-2-1")]}

    same_period = closed_period(world, 2, plan)
    with_quantity = closed_period(world, 3, plan | {3: [cancel("make-2-1", "10")]})
    after_run = closed_period(world, 5, plan | {5: [cancel("make-2-1")]})
    production = closed_period(
        world, 3, plan | {3: [produce("board", "1"), cancel("make-3-1")]}
    )

    assert [outcome.reason for outcome in same_period.outcomes] == [
        "unknown_order",
        None,
    ]
    assert [outcome.reason for outcome in with_quantity.outcomes] == ["wrong_quantity"]
    assert [outcome.reason for outcome in after_run.outcomes] == ["unknown_order"]
    assert [outcome.reason for outcome in production.outcomes] == [
        "unknown_order",
        None,
    ]


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_orders_keep_their_minimum_and_their_tier_through_buys_and_cancels(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world, steps = drawn_run(factory, seed, data.draw)
    cancelled: dict[str, Decimal] = {}
    # A cancel of the whole open quantity is accepted whatever arrived before it, so
    # its order may end below its minimum or tier.
    emptied: set[str] = set()

    for decided, _, closed_state in steps:
        open_now = {order.id: order.open_quantity for order in decided.supplier_orders}
        for outcome in closed_state.outcomes:
            decision = outcome.decision
            if not outcome.accepted:
                continue
            if isinstance(decision, Buy):
                path = f"suppliers.{decision.supplier}.catalogue.{decision.material}"
                minimum = world.parameters.get(f"{path}.min_quantity")
                assert minimum is None or decision.quantity >= minimum
            if isinstance(decision, Cancel):
                still_open = open_now.get(decision.order, Decimal(0))
                quantity = decision.quantity or still_open
                if quantity == still_open:
                    emptied.add(decision.order)
                open_now[decision.order] = still_open - quantity
                cancelled[decision.order] = (
                    cancelled.get(decision.order, Decimal(0)) + quantity
                )
    for order in supplier_orders_of(world, steps).values():
        left = order.quantity - cancelled.get(order.id, Decimal(0))
        if order.placed == 0 or left == 0 or order.id in emptied:
            continue
        path = f"suppliers.{order.supplier}.catalogue.{order.material}"
        minimum = world.parameters.get(f"{path}.min_quantity", Decimal(0))
        assert left >= minimum
        assert order.tier is None or left >= order.tier


@pytest.mark.property
@given(
    st.integers(min_value=1, max_value=6000000),
    st.integers(min_value=1, max_value=1000),
    st.sampled_from([None, "500.000", "2000.000"]),
)
def test_a_cancel_is_accepted_exactly_when_it_keeps_the_minimum_and_the_tier(
    thousandths: int, share: int, minimum: str | None
):
    quantity = Decimal(thousandths) / 1000
    cancelled = max(
        Decimal("0.001"), (quantity * share / 1000).quantize(Decimal("0.001"))
    )
    world = tiered_chip_world(min_quantity=minimum, lead_time=3)
    decisions = {1: [buy(str(quantity))], 2: [cancel("buy-1-1", str(cancelled))]}

    state = closed_period(world, 2, decisions)

    placed = closed_period(world, 1, decisions).supplier_orders
    if not placed:
        return
    [order] = placed
    left = quantity - cancelled
    keeps = left == 0 or (
        left >= Decimal(minimum or 0) and (order.tier is None or left >= order.tier)
    )
    [outcome] = state.outcomes
    assert outcome.accepted == keeps
