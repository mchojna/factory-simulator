from decimal import Decimal
from typing import Any

import pytest
from factories import (
    back_and_forth_transfers,
    buy,
    closed_period,
    draw_world_of_bodies,
    number_text,
    transfer,
    transfer_bound_bodies,
    transfer_world,
)
from hypothesis import given
from hypothesis import strategies as st

from factory_simulator.api.record.database import recorded_value
from factory_simulator.engine import State, start_period


def outcomes(state: State) -> list[Any]:
    return [
        (
            outcome.accepted,
            outcome.reason,
            outcome.asked,
            outcome.available,
            outcome.reference,
            outcome.item,
        )
        for outcome in state.outcomes
    ]


def rows(state: State, kind: str) -> list[tuple[str, Decimal]]:
    return [(row.reference, row.amount) for row in state.ledger if row.kind == kind]


def arrivals(state: State) -> list[dict[str, Any]]:
    return [
        dict(event)
        for event in state.period_events
        if event["kind"] == "transfer_arrived"
    ]


def test_a_transfer_pays_its_cost_reserves_space_and_arrives_after_its_lead_time():
    world = transfer_world()

    sent = closed_period(world, 1, {1: [transfer("monitor", "6")]})
    second = start_period(sent, world)

    assert outcomes(sent) == [(True, None, None, None, "transfer-1-1", None)]
    assert sent.stock["main"]["monitor"] == Decimal("4.000")
    assert rows(sent, "transfer_cost") == [("transfer-1-1", Decimal("-1.2"))]
    storage = rows(sent, "storage_cost")
    assert storage[-2:] == [
        ("main/monitor", Decimal("-0.4")),
        ("transfer-1-1", Decimal("-0.36")),
    ]
    assert second.stock["centre"]["monitor"] == Decimal("6.000")
    assert second.transfers == ()
    assert arrivals(second) == [
        {
            "kind": "transfer_arrived",
            "step": "receive_deliveries",
            "reference": "transfer-1-1",
            "item": "monitor",
            "quantity": Decimal("6.000"),
            "destination": "centre",
        }
    ]


def test_space_on_the_way_is_reserved_at_the_destination():
    world = transfer_world(lead_time=2)

    on_the_way = start_period(
        closed_period(world, 1, {1: [transfer("monitor", "6")]}), world
    )

    assert on_the_way.observation is not None
    space = on_the_way.observation.space
    assert (space["centre"].reserved, space["main"].reserved) == (
        Decimal("0.900"),
        Decimal(0),
    )


def test_a_transfer_with_lead_time_0_arrives_at_once_without_storage_on_the_way():
    world = transfer_world(lead_time=0)

    state = closed_period(world, 1, {1: [transfer("monitor", "6")]})

    assert outcomes(state) == [(True, None, None, None, "transfer-1-1", None)]
    assert state.stock["centre"]["monitor"] == Decimal("6.000")
    assert state.transfers == ()
    assert ("transfer-1-1", Decimal("-0.36")) not in rows(state, "storage_cost")
    assert arrivals(start_period(state, world)) == []


def test_a_transfer_with_lead_time_2_pays_storage_on_the_way_twice():
    world = transfer_world(lead_time=2)

    first = closed_period(world, 1, {1: [transfer("monitor", "6")]})
    second = closed_period(world, 2, {1: [transfer("monitor", "6")]})
    third = start_period(second, world)

    assert ("transfer-1-1", Decimal("-0.36")) in rows(first, "storage_cost")
    assert ("transfer-1-1", Decimal("-0.36")) in rows(second, "storage_cost")
    assert second.stock["centre"]["monitor"] == 0
    assert third.stock["centre"]["monitor"] == Decimal("6.000")


def test_a_transfer_is_checked_for_its_route_item_stock_and_space():
    world = transfer_world(centre_capacity="9.500", centre_stock={"monitor": "60"})

    state = closed_period(
        world,
        1,
        {
            1: [
                transfer("monitor", "6", "centre", "main"),
                transfer("chip", "6"),
                transfer("gadget", "6"),
                transfer("monitor", "12"),
                transfer("monitor", "6"),
            ]
        },
    )

    assert outcomes(state) == [
        (False, "unknown_route", None, None, None, None),
        (False, "not_accepted", None, None, None, "chip"),
        (False, "not_accepted", None, None, None, "gadget"),
        (False, "not_enough_stock", Decimal("12.000"), Decimal("10.000"), None, None),
        (False, "not_enough_space", Decimal("0.900"), Decimal("0.500"), None, None),
    ]


def test_a_transfer_arriving_after_the_horizon_never_arrives():
    world = transfer_world(lead_time=5)

    last = closed_period(world, 5, {1: [transfer("monitor", "6")]})

    assert last.finished
    assert last.stock["centre"]["monitor"] == 0
    assert [moving.id for moving in last.transfers] == ["transfer-1-1"]


def test_transfers_arriving_together_are_reported_by_identifier_after_deliveries():
    world = transfer_world()

    state = closed_period(
        world,
        2,
        {
            1: [buy("10", warehouse="main")],
            2: [transfer("monitor", "2"), transfer("monitor", "3")],
        },
    )
    third = start_period(state, world)

    kinds = [
        (event["kind"], event["reference"])
        for event in third.period_events
        if event["kind"] in ("delivery", "transfer_arrived")
    ]
    assert kinds == [
        ("delivery", "buy-1-1"),
        ("transfer_arrived", "transfer-2-1"),
        ("transfer_arrived", "transfer-2-2"),
    ]


@pytest.mark.slow
def test_a_chip_sent_back_and_forth_5001_times_moves_once_and_pays_one_cost():
    world = draw_world_of_bodies(*transfer_bound_bodies())

    state = closed_period(world, 1, {1: back_and_forth_transfers()})

    found = outcomes(state)
    one = Decimal("1.000")
    assert len(found) == 5001
    assert found[:4] == [
        (True, None, None, None, "transfer-1-1", None),
        (False, "transferred_this_period", one, Decimal(0), None, None),
        (False, "not_enough_stock", one, Decimal(0), None, None),
        (False, "transferred_this_period", one, Decimal(0), None, None),
    ]
    assert sum(accepted for accepted, *_ in found) == 1
    assert rows(state, "transfer_cost") == [
        ("transfer-1-1", Decimal("-20000000000000000000000"))
    ]
    assert state.cash == Decimal("-19999999999999999999000")
    assert state.stock["annex"]["chip"] == one


def test_a_cycle_moves_the_stock_it_started_with_and_not_a_unit_more():
    manifest, scenario = transfer_bound_bodies()
    manifest["materials"]["chip"]["space"] = "1.000"
    for routes in manifest["routes"].values():
        for route in routes.values():
            route["cost"] = "0.0001"
    scenario["start"]["stock"] = {"main": {"chip": "2"}, "annex": {"chip": "1"}}
    world = draw_world_of_bodies(manifest, scenario)

    state = closed_period(
        world,
        1,
        {
            1: [
                transfer("chip", "2", "main", "annex"),
                transfer("chip", "1", "annex", "main"),
                transfer("chip", "0.001", "annex", "main"),
            ]
        },
    )

    assert outcomes(state) == [
        (True, None, None, None, "transfer-1-1", None),
        (True, None, None, None, "transfer-1-2", None),
        (False, "transferred_this_period", Decimal("0.001"), Decimal(0), None, None),
    ]
    assert rows(state, "transfer_cost") == [
        ("transfer-1-1", Decimal("-0.0002")),
        ("transfer-1-2", Decimal("-0.0001")),
    ]
    assert state.stock["main"]["chip"] == Decimal("1.000")
    assert state.stock["annex"]["chip"] == Decimal("2.000")


# Up to 20 transfers of 0.001 to 3 chips between main and annex in any order.
back_and_forth_lists = st.lists(
    st.tuples(number_text(3, Decimal("0.001"), 3), st.booleans()).map(
        lambda pair: transfer(
            "chip", pair[0], *(("main", "annex")[:: 1 if pair[1] else -1])
        )
    ),
    max_size=20,
)


@pytest.mark.property
@given(
    number_text(3, Decimal("0.001"), 3),
    number_text(3, 0, 3),
    back_and_forth_lists,
)
def test_repeated_transfers_move_at_most_the_stock_and_a_rejection_changes_nothing(
    main: str, annex: str, transfers: list[dict[str, Any]]
):
    manifest, scenario = transfer_bound_bodies()
    manifest["materials"]["chip"]["space"] = "1.000"
    scenario["start"]["stock"] = {"main": {"chip": main}, "annex": {"chip": annex}}
    world = draw_world_of_bodies(manifest, scenario)

    state = closed_period(world, 1, {1: transfers})
    accepted = [
        decision
        for decision, outcome in zip(transfers, state.outcomes, strict=True)
        if outcome.accepted
    ]
    only_accepted = closed_period(world, 1, {1: accepted})

    transferred = sum(
        (Decimal(decision["quantity"]) for decision in accepted), Decimal(0)
    )
    assert transferred <= Decimal(main) + Decimal(annex)
    assert state.stock == only_accepted.stock
    assert state.cash == only_accepted.cash
    assert [row.amount for row in state.ledger] == [
        row.amount for row in only_accepted.ledger
    ]
    for row in state.ledger:
        recorded_value("ledger.amount", row.amount)
        recorded_value("ledger.cash_after", row.cash_after)
