from decimal import Decimal
from itertools import permutations
from typing import Any, cast

import pytest
from factories import (
    ReferenceQuality,
    benchmark_client,
    changeover_manifest,
    example_count,
    full_warehouse_bodies,
    future_choice_bodies,
    future_minimum_bodies,
    ordered_transfer_bodies,
    plain_tiny_manifest,
    plain_tiny_scenario,
    reference_quality_of,
    routes_of_world,
    start_cancellation_control,
    start_transfer_order_control,
    starting_order_bodies,
    tiny_scenario,
    transfer_networks,
    two_warehouse_manifest,
    unwanted_order_bodies,
    without_integer_keys,
)
from fastapi.testclient import TestClient
from hypothesis import example, given, settings
from hypothesis import strategies as st

from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.services.examples import EXAMPLES
from factory_simulator.benchmark import client as benchmark

INTEGER_KEYS = ("min_quantity", "discounts", "changeover_time", "changeover_cost")

# The legal decisions of the world of a future minimum, which buy 20 chips in period 1.
EARLY_BUY: dict[int, list[dict[str, Any]]] = {
    1: [
        {
            "kind": "buy",
            "supplier": "chip-maker",
            "material": "chip",
            "quantity": 20,
            "warehouse": "main",
        }
    ],
    2: [{"kind": "produce", "line": "line-1", "item": "board", "quantity": 8}],
    3: [{"kind": "produce", "line": "line-1", "item": "monitor", "quantity": 4}],
    4: [{"kind": "ship", "order": "order-0-1", "quantity": 4, "warehouse": "main"}],
    5: [],
}

# The legal decisions of the world of a full warehouse: the monitor of period 1 frees
# the space of the two boards made after it, which make the two monitors of period 2.
FULL_WAREHOUSE_DECISIONS: dict[int, list[dict[str, Any]]] = {
    1: [
        {"kind": "produce", "line": "line-1", "item": "monitor", "quantity": 1},
        {"kind": "produce", "line": "line-1", "item": "board", "quantity": 2},
    ],
    2: [
        {"kind": "ship", "order": "order-0-1", "quantity": 1},
        {"kind": "produce", "line": "line-1", "item": "monitor", "quantity": 2},
    ],
    3: [{"kind": "ship", "order": "order-0-2", "quantity": 2}],
}


# A world stored over the client of the benchmark.
def stored_scenario(
    client: TestClient, manifest: dict[str, Any], scenario: dict[str, Any]
) -> str:
    stored = benchmark.send(client, "POST", "/manifests", manifest)
    path = f"/manifests/{stored['id']}/scenarios"
    return benchmark.send(client, "POST", path, scenario)["id"]


# The result of a run of seed 0 that submits the decisions written for each period.
def played_decisions(
    client: TestClient, scenario_id: str, decisions: dict[int, list[dict[str, Any]]]
) -> dict[str, Any]:
    run = benchmark.start_run(client, scenario_id, 0)
    return benchmark.play_run(
        client, run, lambda description, observation: decisions[observation["period"]]
    )


# Every run played only decisions the engine accepts as planned.
def assert_feasible(quality: ReferenceQuality, *results: dict[str, Any]) -> None:
    assert quality.fitted == quality.dropped == 0
    assert quality.quantity_lost == 0
    assert quality.exact_fitted == quality.exact_dropped == 0
    for result in results:
        assert result["measures"]["total"]["decisions_rejected"] == 0


# A world of seed 0 played with no decisions, then by the reference and by the exact
# control: the quality of the reference and the periods of its run.
def played_reference(
    manifest: dict[str, Any], scenario: dict[str, Any]
) -> tuple[ReferenceQuality, list[dict[str, Any]]]:
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, scenario)
        quality = reference_quality_of(client, scenario_id, 0)
        periods = benchmark.read_periods(client, quality.reference_run_id)
    return quality, periods


# The exact control earns what the value of its exact program of period 1 counts, and
# the reference earns what the exact control earns; neither changes a decision of its
# plan. The value of the program of the reference, whose later choices take any value
# from 0 to 1, is no part of the contract.
def assert_kept(quality: ReferenceQuality) -> None:
    assert abs(quality.decimal_effects) < 1
    assert abs(quality.policy_gap) < 1
    assert_feasible(quality)


def events_of(period: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [
        event
        for step in period["steps"]
        for event in step.get("events", [])
        if event["kind"] == kind
    ]


def submitted_of_kind(period: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    step = next(step for step in period["steps"] if step["step"] == "make_decisions")
    return [
        decision
        for decision in step["submission"]["decisions"]
        if decision["kind"] == kind
    ]


def line_measures(period: dict[str, Any]) -> dict[str, Any]:
    step = next(step for step in period["steps"] if step["step"] == "close_period")
    return step["measures"]["lines"]["line-1"]


def chip_entry_of(manifest: dict[str, Any]) -> dict[str, Any]:
    return manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]


def monitor_terms(manifest: dict[str, Any]) -> dict[str, Any]:
    return manifest["customers"]["distributor"]["products"]["monitor"]


# The template manifest and scenario, without a key that needs a yes-or-no choice in
# the catalogue, the lines or the defaults of the groups.
def linear_template() -> tuple[dict[str, Any], dict[str, Any]]:
    templates = EXAMPLES / "templates"
    manifest = cast(
        dict[str, Any], read_json_bytes((templates / "manifest.json").read_bytes())
    )
    scenario = cast(
        dict[str, Any], read_json_bytes((templates / "scenario.json").read_bytes())
    )
    for group in manifest["groups"].values():
        for defaults in group.get("defaults", {}).values():
            for key in INTEGER_KEYS:
                defaults.pop(key, None)
    return without_integer_keys((manifest, scenario))


# The legal sequence of the world of an ordered transfer: 2 chips leave `main` for
# `buffer`, then the board comes from the remote warehouse into the space they free.
def ordered_transfers(remote: str) -> list[dict[str, Any]]:
    return [
        {
            "kind": "transfer",
            "item": "chip",
            "quantity": 2,
            "source": "main",
            "destination": "buffer",
        },
        {
            "kind": "transfer",
            "item": "board",
            "quantity": 1,
            "source": remote,
            "destination": "main",
        },
    ]


# The network of a full `remote`: 2 periods of the world of an ordered transfer with
# free routes of lead time 0 from `main` to `remote` and back, and none to `buffer`, of
# capacity 0.010. `main` holds 1 chip in its 0.020 and `remote` 1 board in its 0.020
# at a storage factor of 1, so `remote` is full and its space rows have no margin.
def full_remote_network_bodies() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, scenario = ordered_transfer_bodies()
    manifest["warehouses"]["buffer"]["capacity"] = "0.010"
    manifest["warehouses"]["remote"]["storage_factor"] = "1.0000"
    route = {"cost": "0.0000", "lead_time": 0}
    manifest["routes"] = {"remote": {"main": route}, "main": {"remote": route}}
    scenario["horizon"] = 2
    scenario["start"]["stock"] = {
        "main": {"chip": "1", "board": "0"},
        "buffer": {"chip": "0"},
        "remote": {"chip": "0", "board": "1"},
    }
    return manifest, scenario


def observation_of(period: dict[str, Any]) -> dict[str, Any]:
    step = next(step for step in period["steps"] if step["step"] == "build_observation")
    return step["observation"]


def item_spaces(manifest: dict[str, Any]) -> dict[str, Decimal]:
    return {
        item_id: Decimal(item["space"])
        for kind in ("materials", "components", "products")
        for item_id, item in manifest[kind].items()
    }


# The warehouse a transfer or a production adds space to, the space it adds per unit,
# and the routes out of that warehouse that run before it in the order of the routes:
# every route for a production, as the transfers run before the productions.
def space_of_decision(
    manifest: dict[str, Any],
    order: tuple[tuple[str, str], ...],
    decision: dict[str, Any],
) -> tuple[str, Decimal, list[tuple[str, str]]]:
    spaces = item_spaces(manifest)
    if decision["kind"] == "transfer":
        warehouse_id = decision["destination"]
        earlier = order[: order.index((decision["source"], warehouse_id))]
        unit = spaces[decision["item"]]
    else:
        warehouse_id = manifest["lines"][decision["line"]]["warehouse"]
        earlier = order
        item = (
            manifest["components"].get(decision["item"])
            or manifest["products"][decision["item"]]
        )
        recipe = item["recipes"][decision["recipe"]]
        inputs = sum(
            (
                Decimal(quantity) * spaces[input_id]
                for input_id, quantity in recipe.items()
            ),
            Decimal(0),
        )
        unit = spaces[decision["item"]] - inputs
    leaving = [route for route in earlier if route[0] == warehouse_id]
    return warehouse_id, unit, leaving


# The most space the fit may take from a transfer or a production rejected for space.
# Each quantity is rounded down by less than 0.001 units, so each item the warehouse
# holds frees less than 0.001 units of its space less than planned on each route out
# of it that runs before the decision; every other rounding holds less space. The fit
# takes that shortfall over the space of the decision per unit, rounded up to 0.001
# units. The networks have no customer order, so no ship frees space.
def fit_allowance(
    manifest: dict[str, Any],
    order: tuple[tuple[str, str], ...],
    observation: dict[str, Any],
    decision: dict[str, Any],
) -> Decimal:
    spaces = item_spaces(manifest)
    warehouse_id, unit, leaving = space_of_decision(manifest, order, decision)
    held = [
        spaces[item_id]
        for item_id, units in observation["stock"][warehouse_id].items()
        if units > 0
    ]
    return Decimal("0.001") * (len(leaving) * sum(held, Decimal(0)) + unit)


# The world of a future choice with a discount from 20 chips at 0.4000, 4 periods from
# cash 10 and no stock, and 4 monitors due in period 4. HiGHS ends the program of
# period 2 optimal with its bound one rounding of floating point below its value.
def discount_from_little_cash_bodies() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, scenario = future_minimum_bodies()
    entry = chip_entry_of(manifest)
    del entry["min_quantity"]
    entry["discounts"] = [{"from": "20.000", "price": "0.4000"}]
    scenario["horizon"] = 4
    scenario["start"]["cash"] = "10"
    scenario["start"]["customer_orders"][0]["due"] = 4
    return manifest, scenario


# One starting order of 4 monitors, due in period 1 with patience 1, and no demand.
# The 8 boards make the 4 monitors in period 1, ready in period 2, so the order ships
# one period after its due period and pays the late penalty of period 1.
@pytest.mark.slow
def test_the_reference_counts_a_unit_shipped_one_period_late_as_the_engine_does():
    manifest = plain_tiny_manifest()
    monitor_terms(manifest).update(demand="0.000", patience=1)
    scenario = plain_tiny_scenario()
    scenario["start"]["customer_orders"] = [
        {"customer": "distributor", "product": "monitor", "quantity": "4", "due": 1}
    ]

    quality, periods = played_reference(manifest, scenario)

    assert_kept(quality)
    assert [ship["order"] for ship in submitted_of_kind(periods[1], "ship")] == [
        "order-0-1"
    ]
    assert [event["amount"] for event in events_of(periods[0], "late_penalty")] == [8]


# Chips at 2.0000 of which 0.8 pass inspection: the reference buys 20 chips in period 1
# for the 16 that `order-4-1` needs and pays the accepted ones only.
@pytest.mark.slow
def test_the_reference_counts_deliveries_with_rejected_units_as_the_engine_does():
    manifest = plain_tiny_manifest()
    chip_entry_of(manifest).update(price="2.0000", acceptance="0.8000")
    scenario = plain_tiny_scenario() | {"horizon": 4}

    quality, periods = played_reference(manifest, scenario)

    assert_kept(quality)
    deliveries = [
        event for period in periods for event in events_of(period, "delivery")
    ]
    assert any(event["arrived"] > event["accepted"] for event in deliveries)


# The order `order-5-1` needs 16 chips by period 3. A delivery due in period 2 or 3
# arrives one period later, so only the buy of period 1 serves it, and it arrives in
# period 3.
@pytest.mark.slow
def test_the_reference_counts_a_transport_delay_as_the_engine_does():
    delay = {
        "kind": "transport_delay",
        "target": ["chip-maker"],
        "start": 2,
        "duration": 2,
        "delay": 1,
        "notice": 0,
    }
    scenario = plain_tiny_scenario() | {"horizon": 5, "disruptions": [delay]}

    quality, periods = played_reference(plain_tiny_manifest(), scenario)

    assert_kept(quality)
    (delivery,) = events_of(periods[2], "delivery")
    assert delivery["reference"].startswith("buy-1-")


# The order `order-4-1` needs 16 chips by period 2, so the reference buys in period 1,
# while the chip costs 1.5 times its price of 0.5000.
@pytest.mark.slow
def test_the_reference_counts_a_price_change_as_the_engine_does():
    change = {
        "kind": "price_change",
        "target": ["chip"],
        "start": 1,
        "duration": 1,
        "factor": "1.5000",
        "notice": 0,
    }
    scenario = plain_tiny_scenario() | {"horizon": 4, "disruptions": [change]}

    quality, periods = played_reference(plain_tiny_manifest(), scenario)

    assert_kept(quality)
    (delivery,) = events_of(periods[1], "delivery")
    assert delivery["reference"].startswith("buy-1-")
    assert delivery["payment"] == delivery["accepted"] * Decimal("0.75")


# Seed 0 breaks the line in period 2 only and halves its condition. Orders of 40
# monitors need more than the 10 hours of the line, so the reference uses every hour
# the breakdown leaves in period 2.
@pytest.mark.slow
def test_the_reference_counts_a_drawn_breakdown_after_period_1_as_the_engine_does():
    manifest = plain_tiny_manifest()
    manifest["lines"]["line-1"].update(
        breakdown_chance="0.3000", breakdown_loss="0.5000"
    )
    monitor_terms(manifest)["demand"] = "40.000"
    scenario = plain_tiny_scenario() | {
        "start": {"cash": "1000", "stock": {"main": {"board": "200"}}}
    }

    quality, periods = played_reference(manifest, scenario)

    assert_kept(quality)
    assert [len(events_of(period, "breakdown")) for period in periods] == [0, 1, 0]
    measures = line_measures(periods[1])
    assert measures["regular_hours"] == measures["hours_available"] == 5


# A random rule cuts the capacity of the line by half in every period, with notice 2,
# so its starts in periods 1 and 2 are visible from period 1. Orders of 40 monitors
# need more than the 5 hours of the line left.
@pytest.mark.slow
def test_the_reference_counts_a_random_cut_within_its_notice_as_the_engine_does():
    manifest = plain_tiny_manifest()
    monitor_terms(manifest)["demand"] = "40.000"
    cut = {
        "name": "cut",
        "kind": "capacity_cut",
        "target": ["line-1"],
        "chance": "1.0000",
        "duration": 1,
        "strength": "0.5000",
        "notice": 2,
    }
    scenario = plain_tiny_scenario() | {
        "start": {"cash": "1000", "stock": {"main": {"board": "200"}}},
        "random_disruptions": [cut],
    }

    quality, periods = played_reference(manifest, scenario)

    assert_kept(quality)
    first = observation_of(periods[0])
    assert [disruption["start"] for disruption in first["disruptions"]] == [1, 2, 3]
    measures = line_measures(periods[0])
    assert measures["regular_hours"] == measures["hours_available"] == 5


# A line at condition 0.6 that wears with time and with every hour: orders of 40
# monitors make its hours scarce, and a repair at 20.0000 restores them.
@pytest.mark.slow
def test_the_reference_counts_wear_and_repair_as_the_engine_does():
    manifest = plain_tiny_manifest()
    manifest["lines"]["line-1"].update(
        wear_per_period="0.0100", wear_per_hour="0.0200", repair_cost="20.0000"
    )
    monitor_terms(manifest)["demand"] = "40.000"
    scenario = plain_tiny_scenario() | {
        "start": {
            "cash": "1000",
            "stock": {"main": {"board": "200"}},
            "condition": {"line-1": "0.6000"},
        }
    }

    quality, periods = played_reference(manifest, scenario)

    assert_kept(quality)
    assert [submitted_of_kind(period, "repair") != [] for period in periods] == [
        True,
        False,
        False,
    ]
    measures = line_measures(periods[0])
    assert measures["regular_hours"] == measures["hours_available"] < 10


# A shipment from `main` pays 10 times the transport cost, one from `centre` once, so
# the reference sends monitors to `centre` along a route of 2 periods; `centre`
# stores at twice the storage cost.
@pytest.mark.slow
def test_the_reference_counts_storage_in_two_warehouses_as_the_engine_does():
    manifest = two_warehouse_manifest(storage_factor="2.0000")
    manifest["warehouses"]["main"]["transport_factor"] = "10.0000"
    manifest["routes"] = {"main": {"centre": {"cost": "0.1000", "lead_time": 2}}}
    scenario = tiny_scenario() | {"horizon": 4}

    quality, periods = played_reference(manifest, scenario)

    assert_kept(quality)
    on_the_way = [
        transfer
        for period in periods[1:]
        for step in period["steps"]
        if step["step"] == "build_observation"
        for transfer in step["observation"]["transfers"]
    ]
    assert on_the_way != []


# The order `order-2-1` is due in period 2, the last, and its customer waits 1 more
# period; the 4 monitors in stock ship to `order-1-1` at once, as holding them costs
# storage.
@pytest.mark.slow
def test_the_reference_counts_an_order_lost_at_the_end_as_the_engine_does():
    manifest = plain_tiny_manifest()
    monitor_terms(manifest)["patience"] = 1
    manifest["products"]["monitor"]["storage_cost"] = "0.1000"
    scenario = plain_tiny_scenario() | {
        "horizon": 2,
        "start": {"cash": "1000", "stock": {"main": {"monitor": "4"}}},
    }

    quality, periods = played_reference(manifest, scenario)

    assert_kept(quality)
    assert [
        (event["reference"], event["at_end"])
        for event in events_of(periods[1], "lost_sale")
    ] == [("order-2-1", True)]


# Cash before the buys of period 1 is -300 + 200 - 4 - 24 = -128, below the credit
# limit of 0; the sale of period 2 lifts it to 68. The chip costs 1.2 times its price
# in period 2, so the reference would buy in period 1 if it could. From -10000300 the
# 5 periods sell at most 20 monitors for 20 * 50 = 1000, so neither period buys.
@pytest.mark.slow
@pytest.mark.parametrize(
    ("start_cash", "buys_in_period_2"), [("-300", True), ("-10000300", False)]
)
def test_the_reference_counts_a_start_below_the_credit_line_as_the_engine_does(
    start_cash: str, buys_in_period_2: bool
):
    change = {
        "kind": "price_change",
        "target": ["chip"],
        "start": 2,
        "duration": 1,
        "factor": "1.2000",
        "notice": 0,
    }
    scenario = plain_tiny_scenario() | {
        "horizon": 5,
        "start": {
            "cash": start_cash,
            "stock": {"main": {"chip": "16", "board": "16", "monitor": "4"}},
        },
        "disruptions": [change],
    }

    quality, periods = played_reference(plain_tiny_manifest(), scenario)

    assert_kept(quality)
    assert submitted_of_kind(periods[0], "buy") == []
    assert (submitted_of_kind(periods[1], "buy") != []) == buys_in_period_2


# 30 monitors in stock ship 10 a period from cash -1100, so the cash of the closes
# lies below minus the credit limit of 600, between it and 0, then above 0. No buy
# pays within 3 periods.
@pytest.mark.slow
def test_the_reference_counts_every_interest_band_as_the_engine_does():
    manifest = plain_tiny_manifest()
    manifest["cash"] = {
        "credit_limit": "600.0000",
        "credit_interest": "0.0100",
        "debit_interest": "0.0200",
        "overdraft_interest": "0.0500",
    }
    monitor_terms(manifest)["demand"] = "10.000"
    scenario = plain_tiny_scenario() | {
        "start": {"cash": "-1100", "stock": {"main": {"monitor": "30"}}}
    }

    quality, periods = played_reference(manifest, scenario)

    assert_kept(quality)
    closes = [period["ledger"][-1]["cash_after"] for period in periods]
    assert closes[0] < -600 < closes[1] < 0 < closes[2]


# The order `order-4-1` needs 16 chips by period 2; `chip-maker` sells at least 20.
@pytest.mark.slow
def test_the_reference_counts_a_minimum_quantity_as_the_engine_does():
    manifest = plain_tiny_manifest()
    chip_entry_of(manifest)["min_quantity"] = "20.000"
    scenario = plain_tiny_scenario() | {"horizon": 4}

    quality, periods = played_reference(manifest, scenario)

    assert_kept(quality)
    assert [buy["quantity"] for buy in submitted_of_kind(periods[0], "buy")] == [20]


# The order `order-4-1` needs 16 chips by period 2; from 16 chips the chip costs
# 0.4000.
@pytest.mark.slow
def test_the_reference_counts_a_discount_tier_as_the_engine_does():
    manifest = plain_tiny_manifest()
    chip_entry_of(manifest)["discounts"] = [{"from": "16.000", "price": "0.4000"}]
    scenario = plain_tiny_scenario() | {"horizon": 4}

    quality, periods = played_reference(manifest, scenario)

    assert_kept(quality)
    (delivery,) = events_of(periods[1], "delivery")
    assert delivery["payment"] == delivery["accepted"] * Decimal("0.4000")


# Two periods: the 10 boards make 5 monitors in period 1, after a changeover of the
# line, for the orders of period 2.
@pytest.mark.slow
def test_the_reference_counts_a_changeover_as_the_engine_does():
    manifest = changeover_manifest()
    chip_entry_of(manifest)["lead_time"] = 1
    scenario = tiny_scenario() | {
        "horizon": 2,
        "start": {"cash": "1000", "stock": {"main": {"chip": "20", "board": "10"}}},
    }

    quality, periods = played_reference(manifest, scenario)

    assert_kept(quality)
    assert line_measures(periods[0])["changeovers"] == 1


@pytest.mark.slow
def test_the_reference_counts_the_template_world_as_the_engine_does():
    quality, periods = played_reference(*linear_template())

    assert len(periods) == 12
    assert_kept(quality)


# The 4 monitors sell for 200, less 4 of transport and 16 of production. 20 chips at
# 0.5 in period 1 cost 10, at 0.55 in period 2 cost 11; the 4 chips left are worth 0.4.
@pytest.mark.slow
def test_the_exact_control_buys_a_future_minimum_early_where_the_reference_waits():
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, *future_minimum_bodies())
        quality = reference_quality_of(client, scenario_id, 0)
        early = played_decisions(client, scenario_id, EARLY_BUY)

    assert quality.reference_profit == Decimal("169.4")
    assert quality.exact_profit == Decimal("170.4")
    assert early["profit"] == Decimal("170.4")
    # The program of period 1 counts 16 chips of period 2 at 0.55: 180 - 8.8.
    values = (quality.program_value, quality.exact_program_value)
    assert values == pytest.approx((171.2, 170.4))
    assert_feasible(quality, early)


# The world of a future minimum with a discount from 20 chips at 0.4000 in place of
# the minimum. The reference counts 16 chips of period 2 at the discount price of
# 0.4400, then pays 20 at 0.44; the exact control buys 20 at 0.4 in period 1:
# 180 - 8.8 + 0.4 against 180 - 8 + 0.4.
@pytest.mark.slow
def test_the_exact_control_buys_a_future_discount_early_where_the_reference_waits():
    manifest, scenario = future_minimum_bodies()
    del chip_entry_of(manifest)["min_quantity"]
    chip_entry_of(manifest)["discounts"] = [{"from": "20.000", "price": "0.4000"}]
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, scenario)
        quality = reference_quality_of(client, scenario_id, 0)

    assert quality.reference_profit == Decimal("171.6")
    assert quality.exact_profit == Decimal("172.4")
    # 16 chips at 0.44: 180 - 7.04.
    values = (quality.program_value, quality.exact_program_value)
    assert values == pytest.approx((172.96, 172.4))
    assert_feasible(quality)


# Three periods from 16 chips: 4 monitors due in period 3, no other demand, and a
# changeover of 250 to the monitor. The reference counts the changeover of period 2 at
# its share of the hours of the line, 0.2, so it makes 8 boards for 8 in period 1. In
# period 2 the whole changeover costs more than the order: it loses the order for 40
# and keeps the boards at 0.5 each, -8 - 40 + 4. The exact control decides nothing and
# keeps the chips at 0.1 each, -40 + 1.6.
@pytest.mark.slow
def test_the_exact_control_skips_a_future_changeover_the_reference_starts_for():
    manifest = plain_tiny_manifest()
    manifest["lines"]["line-1"]["items"]["monitor"]["changeover_cost"] = "250.0000"
    monitor_terms(manifest)["demand"] = "0.000"
    order = {"customer": "distributor", "product": "monitor", "quantity": "4", "due": 3}
    scenario = plain_tiny_scenario() | {
        "start": {
            "cash": "1000",
            "stock": {"main": {"chip": "16"}},
            "customer_orders": [order],
        }
    }
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, scenario)
        quality = reference_quality_of(client, scenario_id, 0)

    assert quality.reference_profit == Decimal("-44")
    assert quality.exact_profit == quality.no_decisions_profit == Decimal("-38.4")
    # 200 - 4 - 16 - 0.2 * 250.
    values = (quality.program_value, quality.exact_program_value)
    assert values == pytest.approx((130, -38.4))
    assert_feasible(quality)


# Five periods from cash 10 and a credit limit of 0: a starting order of 1 monitor due
# in period 1 is lost for 10, which leaves cash 0 from period 2. 4 monitors due in
# period 5 need 16 chips, at 0.5000 and at 0.2500 in period 2. The reference counts
# the credit choice of period 2 from 0 to 1, waits for the price of 4, and then may
# not buy, so it loses the order for 40, as no decisions does. The exact control buys
# the 16 chips for 8 in period 1: 200 - 4 - 16 - 8 - 10.
@pytest.mark.slow
def test_the_exact_control_buys_before_a_future_credit_limit_binds():
    manifest, scenario = future_minimum_bodies()
    del chip_entry_of(manifest)["min_quantity"]
    scenario["disruptions"][0]["factor"] = "0.5000"
    first = {"customer": "distributor", "product": "monitor", "quantity": "1", "due": 1}
    scenario["start"]["cash"] = "10"
    scenario["start"]["customer_orders"].insert(0, first)
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, scenario)
        quality = reference_quality_of(client, scenario_id, 0)

    assert quality.reference_profit == quality.no_decisions_profit == Decimal("-50")
    assert quality.exact_profit == Decimal("162")
    # The 16 chips of period 2 at 0.25: 200 - 4 - 16 - 4 - 10.
    values = (quality.program_value, quality.exact_program_value)
    assert values == pytest.approx((166, 162))
    assert_feasible(quality)


# The world of an unwanted starting order: 10 chips at 0.5000 arrive in period 2 and
# no order needs them. Kept, they cost 5 and are worth 1 at the end, so no decisions,
# the reference and the exact control earn -4; cancelled in period 1 they cost the fee
# of 10 chips. Without a fee the cancellation control earns 0, 4 more than the exact
# control. At 0.4500 a chip the fee of 4.5 costs more than keeping, so the
# cancellation control keeps the order and earns -4.
@pytest.mark.slow
@pytest.mark.parametrize(
    ("fee", "cancelled", "cancellation_profit"),
    [("0.0000", ("buy-0-1",), "0"), ("0.4500", (), "-4")],
)
def test_the_cancellation_control_names_a_useful_cancellation_the_reference_omits(
    fee: str, cancelled: tuple[str, ...], cancellation_profit: str
):
    manifest, scenario = unwanted_order_bodies()
    chip_entry_of(manifest)["cancellation_fee"] = fee

    quality, _ = played_reference(manifest, scenario)

    assert quality.no_decisions_profit == quality.reference_profit == Decimal(-4)
    assert quality.exact_profit == Decimal(-4)
    assert quality.cancelled == cancelled
    assert quality.cancellation_profit == Decimal(cancellation_profit)
    assert quality.cancellation_gap == Decimal(cancellation_profit) + 4
    assert_feasible(quality)


# The world of an ordered transfer: stock is worth 2 * 0.1 + 0.5 = 0.7 at the end,
# and the board costs 100 to store in `remote` and 1 in `main`. No decisions earns
# 0.7 - 100 and the legal sequence 0.7 - 1. Run the other way round, the board finds
# `main` full and is rejected. The routes of the reference run from `main` first, so
# it sends the chips first; `buffer` keeps a margin of 0.001 chips, so 1.999 chips
# leave, 0.999 boards follow and 0.001 board stays in `remote`: 0.7 - 0.999 - 0.1.
@pytest.mark.slow
def test_the_reference_frees_a_full_warehouse_before_a_transfer_into_it():
    manifest, scenario = ordered_transfer_bodies()
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, scenario)
        legal = played_decisions(client, scenario_id, {1: ordered_transfers("remote")})
        reversed_run = benchmark.start_run(client, scenario_id, 0)
        reversed_outcomes = benchmark.create_check(
            client, reversed_run["id"], 1, ordered_transfers("remote")[::-1]
        )
        quality = reference_quality_of(client, scenario_id, 0)
        periods = benchmark.read_periods(client, quality.reference_run_id)

    assert quality.no_decisions_profit == Decimal("-99.3")
    assert legal["profit"] == Decimal("-0.3")
    assert legal["measures"]["total"]["storage_cost"] == 1
    assert [outcome["accepted"] for outcome in reversed_outcomes] == [False, True]
    assert reversed_outcomes[0]["reason"] == "not_enough_space"
    assert quality.reference_profit == quality.exact_profit == Decimal("-0.399")
    assert quality.program_value == pytest.approx(-0.3495)
    assert [
        (decision["item"], decision["quantity"])
        for decision in submitted_of_kind(periods[0], "transfer")
    ] == [("chip", Decimal("1.999")), ("board", Decimal("0.999"))]
    assert quality.transfer_order == ()
    assert quality.transfer_order_gap == Decimal(0)
    assert_feasible(quality, legal)


# The same world with the remote warehouse named `annex`: its route to `main` now runs
# first, so the board would come into a `main` still full of chips. The reference and
# the exact control move nothing and earn what no decisions earns, -99.3, so the world
# is unscorable. The transfer order control that runs the route from `main` first
# earns -0.399 as above, 98.901 more, with no decision fitted or dropped.
@pytest.mark.slow
def test_the_transfer_order_control_names_an_order_of_routes_the_reference_misses():
    manifest, scenario = ordered_transfer_bodies("annex")
    order = (("main", "buffer"), ("annex", "main"))
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, scenario)
        legal = played_decisions(client, scenario_id, {1: ordered_transfers("annex")})
        quality = reference_quality_of(client, scenario_id, 0)
        nothing = benchmark.start_run(client, scenario_id, 0)
        benchmark.play_run(client, nothing, lambda description, observation: [])
        run, control = start_transfer_order_control(
            client, scenario_id, 0, nothing["id"], order
        )
        result = benchmark.play_run(client, run, control)

    assert legal["profit"] == Decimal("-0.3")
    assert quality.no_decisions_profit == quality.reference_profit == Decimal("-99.3")
    assert quality.exact_profit == Decimal("-99.3")
    assert quality.transfer_order == order
    assert quality.transfer_order_profit == result["profit"] == Decimal("-0.399")
    assert quality.transfer_order_gap == Decimal("98.901")
    assert control.fitted == control.dropped == []
    assert_feasible(quality, legal, result)


# The world of a full warehouse. No decisions loses the 3 monitors for 30 and keeps 60
# chips and 4 boards worth 8: -22. The legal decisions sell 3 monitors at 50 less 1 of
# transport, 147, pays 2 + 2 * 1 + 2 * 2 = 8 of production and 3 changeovers of 0.1,
# and keeps 56 chips worth 5.6: 144.3. Boards first, as the changeover order puts
# them, find the warehouse full. The reference makes the monitor first and pays the
# second changeover of period 1, which its program does not count, and earns 144.3;
# it loses no planned quantity to the fit.
@pytest.mark.slow
def test_the_reference_makes_the_monitor_that_frees_space_before_its_boards():
    manifest, scenario = full_warehouse_bodies()
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, scenario)
        legal = played_decisions(client, scenario_id, FULL_WAREHOUSE_DECISIONS)
        boards_first = benchmark.start_run(client, scenario_id, 0)
        boards_first_outcomes = benchmark.create_check(
            client, boards_first["id"], 1, FULL_WAREHOUSE_DECISIONS[1][::-1]
        )
        quality = reference_quality_of(client, scenario_id, 0)
        periods = benchmark.read_periods(client, quality.reference_run_id)

    assert quality.no_decisions_profit == Decimal(-22)
    assert legal["profit"] == Decimal("144.3")
    assert legal["measures"]["total"]["changeover_cost"] == Decimal("0.3")
    assert [outcome["accepted"] for outcome in boards_first_outcomes] == [False, True]
    assert boards_first_outcomes[0]["reason"] == "not_enough_space"
    assert [
        (decision["item"], decision["quantity"])
        for decision in submitted_of_kind(periods[0], "produce")
    ] == [("monitor", Decimal(1)), ("board", Decimal(2))]
    assert quality.reference_profit == quality.exact_profit == Decimal("144.3")
    assert (quality.extra_changeovers, quality.quantity_lost) == (1, Decimal(0))
    assert_feasible(quality, legal)


# In the network of a full `remote`, with the route from `remote` first, the chips sent
# to `remote` follow the boards that leave it. `remote` holds boards in period 1, so the
# fit may take 0.001 * (0.020 + 0.010) of space, 0.003 chips; in period 2 it holds
# boards and chips, 0.001 * (0.020 + 0.010 + 0.010), 0.004 chips.
def test_the_fit_allowance_counts_the_items_that_leave_before_a_transfer():
    manifest, _ = full_remote_network_bodies()
    order = (("remote", "main"), ("main", "remote"))
    chips = {
        "kind": "transfer",
        "item": "chip",
        "quantity": Decimal("0.357"),
        "source": "main",
        "destination": "remote",
    }
    first = {"stock": {"remote": {"board": 1, "chip": 0, "monitor": 0}}}
    second = {
        "stock": {
            "remote": {
                "board": Decimal("0.822"),
                "chip": Decimal("0.356"),
                "monitor": 0,
            }
        }
    }

    assert fit_allowance(manifest, order, first, chips) == Decimal("0.00003")
    assert fit_allowance(manifest, order, second, chips) == Decimal("0.00004")
    assert fit_allowance(manifest, order[::-1], first, chips) == Decimal("0.00001")


# The network of a full `remote`. No decisions stores the board at 2 closes and keeps
# 0.6 of stock: -1.4. With the route from `remote` first, period 1 plans 0.178545
# boards to `main`, 0.357091 chips to `remote`, which the boards free exactly, and
# 0.089273 monitors of the boards. Rounded down, 0.178 boards free 0.00356 of `remote`
# and 0.357 chips ask 0.00357, so the fit takes 0.001 chips; in period 2, 0.001 boards
# free 0.00002 and 0.003 chips ask 0.00003, and it takes 0.001 again. The run stores
# 0.822 boards at each close, makes 0.089 monitors for 0.178 and keeps 0.689 of stock:
# -1.133. A chip costs nothing to store, so the fit costs nothing. With the route from
# `main` first the chips would come into a full `remote`, none move, and nothing is
# fitted.
@pytest.mark.slow
def test_a_transfer_into_a_full_warehouse_loses_what_rounding_frees_less():
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, *full_remote_network_bodies())
        nothing = benchmark.start_run(client, scenario_id, 0)
        floor = benchmark.play_run(client, nothing, lambda description, observation: [])
        results = {}
        for order in (
            (("remote", "main"), ("main", "remote")),
            (("main", "remote"), ("remote", "main")),
        ):
            run, control = start_transfer_order_control(
                client, scenario_id, 0, nothing["id"], order
            )
            profit = benchmark.play_run(client, run, control)["profit"]
            fits = [
                (fit["period"], fit["before"], fit["after"]) for fit in control.fitted
            ]
            results[order[0][0]] = (profit, fits, control.dropped)

    assert floor["profit"] == Decimal("-1.4")
    assert results["remote"] == (
        Decimal("-1.133"),
        [
            (1, Decimal("0.357"), Decimal("0.356")),
            (2, Decimal("0.003"), Decimal("0.002")),
        ],
        [],
    )
    assert results["main"] == (Decimal("-1.189"), [], [])


# Every order of the routes of a small network of warehouses gives a plan the engine
# accepts as planned: the transfer order control submits its transfers in that order,
# and each finds its stock in its source and its space in its destination, beside
# the stock, the starting order and the transfers on the way held there. Rounded down
# to 3 places, a transfer out of a warehouse frees up to 0.001 units less than
# planned; where the warehouse has less space free than the margin of its rows, as a
# full `remote`, a later decision into it can find it short, and the fit takes no more
# than `fit_allowance` from that decision.
@pytest.mark.property
@settings(max_examples=example_count(25))
@given(transfer_networks())
@example(ordered_transfer_bodies())
@example(ordered_transfer_bodies("annex"))
@example(full_remote_network_bodies())
def test_every_order_of_the_routes_runs_its_transfers_as_planned(
    factory: tuple[dict[str, Any], dict[str, Any]],
):
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, *factory)
        nothing = benchmark.start_run(client, scenario_id, 0)
        benchmark.play_run(client, nothing, lambda description, observation: [])
        routes = routes_of_world(benchmark.read_world(client, nothing["id"]))
        for order in permutations(routes):
            run, control = start_transfer_order_control(
                client, scenario_id, 0, nothing["id"], order
            )
            result = benchmark.play_run(client, run, control)
            periods = benchmark.read_periods(client, run["id"])

            assert control.dropped == []
            assert result["measures"]["total"]["decisions_rejected"] == 0
            for fit in control.fitted:
                decision = fit["decision"]
                observation = observation_of(periods[int(fit["period"]) - 1])
                unit = space_of_decision(factory[0], order, decision)[1]
                allowance = fit_allowance(factory[0], order, observation, decision)
                assert fit["reason"] == "not_enough_space"
                assert decision["kind"] in ("transfer", "produce")
                assert (fit["before"] - fit["after"]) * unit <= allowance
            for period in periods:
                sent = [
                    (decision["source"], decision["destination"])
                    for decision in submitted_of_kind(period, "transfer")
                ]
                assert sent == sorted(sent, key=order.index)


# Each gap belongs to its own program. The exact program is the problem the exact
# control plays, so its value is the profit of the exact control, within 1 and the
# gaps of its solves. The program of the reference relaxes the exact one, so its value
# is no lower, within the gaps of both; its own gaps bound only it. The exact control
# bounds the reference in the engine.
@pytest.mark.property
@settings(max_examples=example_count(25))
@given(future_choice_bodies())
@example(future_minimum_bodies())
@example(discount_from_little_cash_bodies())
def test_each_gap_bounds_the_program_it_belongs_to_and_no_other_policy(
    factory: tuple[dict[str, Any], dict[str, Any]],
):
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, *factory)
        quality = reference_quality_of(client, scenario_id, 0)

    value = Decimal(str(quality.program_value))
    exact_value = Decimal(str(quality.exact_program_value))
    exact_tolerance = Decimal(str(quality.exact_gap_sum))
    tolerance = exact_tolerance + Decimal(str(quality.gap_sum))
    assert abs(quality.decimal_effects) < 1 + exact_tolerance
    assert value >= exact_value - tolerance
    assert quality.reference_profit <= quality.exact_profit + 1 + exact_tolerance
    assert_feasible(quality)


# A cancel of the whole open quantity of a starting order ends it: the order leaves the
# observation of period 2, so the run owes nothing for it, and no delivery or payment
# names it. The exact control inside plays its plan unchanged, so its program counts
# the fee, the space and the credit the cancels release as the engine does.
@pytest.mark.property
@settings(max_examples=example_count(25))
@given(starting_order_bodies(), st.data())
@example(unwanted_order_bodies(), None)
def test_the_cancellation_control_never_receives_or_owes_what_it_cancels(
    factory: tuple[dict[str, Any], dict[str, Any]], data: st.DataObject | None
):
    count = len(factory[1]["start"]["supplier_orders"])
    orders = [f"buy-0-{number}" for number in range(1, count + 1)]
    cancelled = ("buy-0-1",)
    if data is not None:
        chosen = data.draw(st.sets(st.sampled_from(orders), min_size=1))
        cancelled = tuple(sorted(chosen))
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, *factory)
        nothing = benchmark.start_run(client, scenario_id, 0)
        benchmark.play_run(client, nothing, lambda description, observation: [])
        run, control, exact_control = start_cancellation_control(
            client, scenario_id, 0, nothing["id"], cancelled
        )
        result = benchmark.play_run(client, run, control)
        periods = benchmark.read_periods(client, run["id"])

    cancels = [
        outcome
        for step in periods[0]["steps"]
        if step["step"] == "execute_decisions"
        for outcome in step["outcomes"]
        if outcome["decision"]["kind"] == "cancel"
    ]
    assert [outcome["decision"]["order"] for outcome in cancels] == list(cancelled)
    assert all(outcome["accepted"] for outcome in cancels)
    for period in periods[1:]:
        seen = observation_of(period)
        assert {order["id"] for order in seen["supplier_orders"]}.isdisjoint(cancelled)
    named = {
        event["reference"]
        for period in periods
        for event in events_of(period, "delivery")
    } | {
        row["reference"]
        for period in periods
        for row in period["ledger"]
        if row["kind"] == "material_payment"
    }
    assert named.isdisjoint(cancelled)
    assert exact_control.fitted == exact_control.dropped == []
    assert result["measures"]["total"]["decisions_rejected"] == 0
