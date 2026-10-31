from decimal import Decimal

import pytest
from factories import (
    buy,
    closed_periods,
    draw_world_of_bodies,
    one_order_world,
    ship,
    tiny_manifest,
    tiny_scenario,
)


def test_service_with_nothing_due_is_none():
    world = one_order_world("10", due=3)

    first = closed_periods(world, {})[0]

    assert first.measures["service"]["total"] is None


def test_service_counts_units_shipped_by_the_due_period_of_orders_past_due():
    world = one_order_world("10", due=2)

    closed = closed_periods(
        world,
        {
            1: [ship("order-0-1", "3")],
            2: [ship("order-0-1", "4")],
            3: [ship("order-0-1", "3")],
        },
    )

    second = closed[1].measures
    assert second["units_past_due"]["total"] == Decimal(10)
    assert second["units_past_due_on_time"]["total"] == Decimal(7)
    assert second["service"]["total"] == Decimal("0.7")
    assert closed[2].measures["units_shipped_late"]["total"] == Decimal(3)


def test_on_time_share_is_units_shipped_on_time_over_units_shipped():
    world = one_order_world("3", due=1)

    closed = closed_periods(
        world, {1: [ship("order-0-1", "1")], 2: [ship("order-0-1", "2")]}
    )

    assert closed[1].measures["on_time_share"]["total"] == Decimal("0.333333333333")


def test_mean_lateness_is_the_periods_late_of_each_late_unit_on_average():
    world = one_order_world("3", due=1, patience=2)

    closed = closed_periods(
        world, {2: [ship("order-0-1", "2")], 3: [ship("order-0-1", "1")]}
    )

    assert closed[2].measures["mean_lateness"]["total"] == Decimal("1.333333333333")


def test_orders_in_full_on_time_share_is_closed_orders_shipped_in_full_by_due():
    world = one_order_world("3", due=3, orders=3)
    ships = {
        1: [ship("order-0-1", "3")],
        3: [ship("order-0-2", "3"), ship("order-0-3", "2")],
    }

    fourth = closed_periods(world, ships)[3]

    share = fourth.measures["orders_in_full_on_time_share"]["total"]
    assert share == Decimal("0.666666666667")


def test_running_totals_keep_only_the_keys_of_the_latest_period():
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario())
    too_much = buy("1001")

    closed = closed_periods(world, {1: [too_much, too_much]})

    first = closed[0].tallies.running["decisions_rejected"]
    second = closed[1].tallies.running["decisions_rejected"]
    assert first["reasons.over_max_quantity"] == Decimal(2)
    assert "reasons.over_max_quantity" not in second


def test_an_order_shipped_in_full_on_time_leaves_the_tallies_and_counts_past_due():
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario(), seed=7)

    first = closed_periods(world, {1: [ship("order-1-1", "4")]})[0]

    assert "order-1-1" not in first.tallies.customer_orders
    assert first.measures["units_past_due"]["total"] == Decimal(4)
    assert first.measures["units_past_due_on_time"]["total"] == Decimal(4)


@pytest.mark.slow
def test_the_tallies_of_a_long_run_hold_only_open_or_not_yet_due_orders():
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario() | {"horizon": 520})

    last = closed_periods(world, {})[-1]

    # Each period creates one order, due in its period and lost at the end of the
    # next, so at most 2 orders are open or not yet due at a close.
    assert len(last.tallies.customer_orders) <= 2
    assert not last.tallies.supplier_orders
