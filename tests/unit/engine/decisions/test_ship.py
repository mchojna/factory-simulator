from dataclasses import asdict
from decimal import Decimal
from typing import Any

import pytest
from factories import (
    FactoryBodies,
    centre_world,
    draw_world_of_bodies,
    first_period,
    outcome_numbers,
    seeds,
    ship,
    ship_lists,
    small_factories,
    submission,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given
from hypothesis import strategies as st

from factory_simulator.engine import (
    Decisions,
    Outcome,
    Ship,
    State,
    World,
    advance_period,
    build_state,
    start_period,
)


# The ships of a period, each an order and a quantity.
def ships_of(period: int, *ships: tuple[str, str]) -> Decisions:
    return submission(period, [ship(order, quantity) for order, quantity in ships])


# The fields of an outcome that are set, its decision included.
def fields_with_decision(outcome: Outcome) -> dict[str, Any]:
    return {key: value for key, value in asdict(outcome).items() if value is not None}


def starting_order_world(
    quantity: str, monitors: str, patience: int = 1, due: int = 1
) -> World:
    manifest = tiny_manifest()
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms["demand"] = "0.000"
    terms["patience"] = patience
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["monitor"] = monitors
    scenario["start"]["customer_orders"] = [
        {
            "customer": "distributor",
            "product": "monitor",
            "quantity": quantity,
            "due": due,
        }
    ]
    return draw_world_of_bodies(manifest, scenario)


def outcomes(state: State) -> list[dict[str, Any]]:
    return [fields_with_decision(outcome) for outcome in state.outcomes]


def started_world(factory: FactoryBodies, seed: int) -> tuple[World, State]:
    world = draw_world_of_bodies(*factory, seed=seed)
    return world, start_period(build_state(world), world)


def transport(state: State) -> list[Decimal]:
    return [row.amount for row in state.ledger if row.kind == "transport_cost"]


def test_a_ship_over_the_stock_is_rejected_with_its_numbers_and_a_smaller_accepted():
    world = starting_order_world(quantity="50", monitors="40")
    state = start_period(build_state(world), world)

    closed = advance_period(
        state, world, ships_of(1, ("order-0-1", "50"), ("order-0-1", "40"))
    )

    assert outcomes(closed) == [
        {
            "decision_id": "1-1",
            "decision": {
                "kind": "ship",
                "order": "order-0-1",
                "quantity": Decimal("50"),
                "warehouse": "main",
            },
            "accepted": False,
            "reason": "not_enough_stock",
            "asked": Decimal("50.000"),
            "available": Decimal("40.000"),
        },
        {
            "decision_id": "1-2",
            "decision": {
                "kind": "ship",
                "order": "order-0-1",
                "quantity": Decimal("40"),
                "warehouse": "main",
            },
            "accepted": True,
            "reference": "ship-1-2",
        },
    ]
    assert closed.stock["main"]["monitor"] == 0


def test_a_ship_over_the_open_quantity_is_rejected_with_its_numbers():
    world = starting_order_world(quantity="10", monitors="40")
    state = start_period(build_state(world), world)

    closed = advance_period(
        state, world, ships_of(1, ("order-0-1", "4"), ("order-0-1", "7"))
    )

    rejected = outcomes(closed)[1]
    assert (rejected["reason"], rejected["asked"], rejected["available"]) == (
        "over_open_quantity",
        Decimal("7"),
        Decimal("6"),
    )


def test_a_ship_of_an_unknown_or_closed_order_is_rejected_without_numbers():
    world = starting_order_world(quantity="10", monitors="40")
    state = start_period(build_state(world), world)

    closed = advance_period(
        state,
        world,
        ships_of(1, ("order-0-1", "10"), ("order-0-1", "1"), ("order-9-9", "1")),
    )

    assert [outcome["accepted"] for outcome in outcomes(closed)] == [True, False, False]
    for rejected in outcomes(closed)[1:]:
        assert rejected["reason"] == "unknown_order"
        assert "asked" not in rejected
        assert "available" not in rejected


def test_late_shipment_stops_later_late_penalties_for_the_shipped_units():
    world = starting_order_world(quantity="10", monitors="40", patience=3)
    state = start_period(build_state(world), world)
    late_penalties: list[list[tuple[str, Decimal, str]]] = []
    for period, ships in [(1, ()), (2, (("order-0-1", "6"),)), (3, ())]:
        closed = advance_period(state, world, ships_of(period, *ships))
        late_penalties.append(
            [
                (row.kind, row.amount, row.reference)
                for row in closed.ledger
                if row.kind == "late_penalty"
            ]
        )
        state = start_period(closed, world)

    assert late_penalties == [
        [("late_penalty", Decimal("-20"), "order-0-1")],
        [("late_penalty", Decimal("-8"), "order-0-1")],
        [("late_penalty", Decimal("-8"), "order-0-1")],
    ]


def test_a_unit_shipped_one_period_after_its_due_period_pays_one_late_penalty():
    world = starting_order_world(quantity="10", monitors="40", patience=3)
    state = start_period(build_state(world), world)
    late_penalties: list[list[Decimal]] = []
    for period, ships in [(1, ()), (2, (("order-0-1", "10"),))]:
        closed = advance_period(state, world, ships_of(period, *ships))
        late_penalties.append(
            [row.amount for row in closed.ledger if row.kind == "late_penalty"]
        )
        state = start_period(closed, world)

    assert late_penalties == [[Decimal(-20)], []]


def test_a_ship_pays_the_transport_factor_of_its_warehouse():
    world = centre_world(transport_factor="0.8000", main_stock={"monitor": "20"})

    from_centre = first_period(world, [ship("order-0-1", "10", warehouse="centre")])
    from_main = first_period(world, [ship("order-0-1", "10", warehouse="main")])

    assert transport(from_centre) == [Decimal(-20)]
    assert transport(from_main) == [Decimal(-25)]


def test_a_ship_takes_only_the_stock_of_its_warehouse():
    world = centre_world()

    state = first_period(
        world,
        [
            ship("order-0-1", "10", warehouse="main"),
            ship("order-0-1", "10", warehouse="north-depot"),
        ],
    )

    assert outcome_numbers(state) == [
        (False, "not_enough_stock", Decimal("10.000"), Decimal("4.000")),
        (False, "unknown_warehouse", None, None),
    ]
    assert state.stock["centre"]["monitor"] == Decimal("20.000")


def test_with_one_warehouse_a_ship_without_one_takes_that_warehouse():
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario())

    state = first_period(world, [ship("order-1-1", "1")])

    decision = state.outcomes[0].decision
    assert isinstance(decision, Ship)
    assert decision.warehouse == "main"


@pytest.mark.property
@given(small_factories(), seeds, st.data())
def test_ships_keep_stock_at_or_above_0_and_every_customer_order_balanced(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world, state = started_world(factory, seed)
    ships = data.draw(ship_lists(world, state))

    closed = advance_period(state, world, submission(state.period, ships))

    for items in closed.stock.values():
        assert all(quantity >= 0 for quantity in items.values())
    shipped_now: dict[str, Decimal] = {}
    for outcome in closed.outcomes:
        decision = outcome.decision
        if outcome.accepted and isinstance(decision, Ship):
            shipped_now[decision.order] = (
                shipped_now.get(decision.order, 0) + decision.quantity
            )
    open_after = {order.id: order for order in closed.customer_orders}
    for order in state.customer_orders:
        shipped = order.shipped + shipped_now.get(order.id, Decimal(0))
        if order.id in open_after:
            assert open_after[order.id].shipped == shipped
        elif shipped != order.quantity:
            assert state.period == order.last or (
                state.period == world.scenario.horizon and order.due <= state.period
            )
