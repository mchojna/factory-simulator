from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import Any

import pytest
from factories import (
    Client,
    api_client,
    example_bodies,
    get,
    post,
    run_to_the_end,
    start_run,
    stock_sale_decisions,
    submit,
)

from factory_simulator.api.core.json import write_json

HIDDEN_WORDS = (
    "demand",
    "demand_persistence",
    "common_share",
    "punctuality",
    "delay",
    "completeness",
    "acceptance",
    "yield",
    "breakdown_chance",
    "breakdown_loss",
)


# A started run of a scenario of the library, posted with the example manifest.
def start(client: Client, name: str, seed: int = 1) -> dict[str, Any]:
    return start_run(client, *example_bodies(name), seed=seed)


# The stored content of a scenario of the library, posted with the example.
def content_of(client: Client, name: str) -> dict[str, Any]:
    run = start(client, name)
    _, scenario = get(client, f"/scenarios/{run['scenario_id']}")
    return scenario["content"]


def chips(quantity: str) -> dict[str, Any]:
    return {
        "kind": "buy",
        "supplier": "apac-chips",
        "material": "microchip",
        "quantity": quantity,
        "warehouse": "main-plant",
    }


def alternative_chips(quantity: str) -> dict[str, Any]:
    return {
        "kind": "buy",
        "supplier": "emea-electronic-parts",
        "material": "microchip-b",
        "quantity": quantity,
        "warehouse": "main-plant",
    }


@pytest.mark.slow
def test_the_sensor_gateway_is_ordered_no_more_from_period_20():
    with api_client() as client:
        run = start(client, "product-life-cycle")
        run_to_the_end(client, run)
        _, periods = get(client, f"/runs/{run['id']}/periods")

    for period in periods["periods"][19:]:
        measures = period["steps"][-1]["measures"]
        ordered = measures["products"].get("sensor-gateway", {})
        assert ordered.get("units_ordered", 0) == 0


@pytest.mark.slow
def test_a_squeezed_run_refuses_a_buy_then_sells_its_stock_and_buys_again():
    with api_client() as client:
        run = start(client, "cash-squeeze")
        _, observation = submit(client, run["id"], 1, [chips("500")])
        [first] = observation["outcomes"]
        after_period_1 = observation["cash"]
        buys = [first]
        payments = Decimal(0)
        for period in range(2, 53):
            payments += sum(
                (
                    Decimal(str(event["amount"]))
                    for event in observation["events"]
                    if event["kind"] == "customer_payment"
                ),
                Decimal(0),
            )
            decisions = [*stock_sale_decisions(observation), chips("500")]
            _, observation = submit(client, run["id"], period, decisions)
            buys += [
                outcome
                for outcome in observation["outcomes"]
                if outcome["decision"]["kind"] == "buy"
            ]
            if buys[-1]["accepted"]:
                break
        # The cash and the credit of 80000 left before the open order, less half the
        # value of that order, buy LCD panels at 45.6.
        [order] = observation["supplier_orders"]
        committed = Decimal(str(order["open_quantity"])) * Decimal(
            str(order["unit_price"])
        )
        without_order = observation["cash"] + 80000
        quantity = ((without_order - committed / 2) / Decimal("45.6")).quantize(
            Decimal("0.001"), rounding=ROUND_DOWN
        )
        panels = {
            "kind": "buy",
            "supplier": "emea-electronic-parts",
            "material": "lcd-panel",
            "quantity": str(quantity),
            "warehouse": "main-plant",
        }
        check = {"period": observation["period"], "decisions": [panels]}
        _, checked = post(client, f"/runs/{run['id']}/checks", check)

    # -120000 + 80000 - 0 is left for any buy of period 1. Its close: -120000 less
    # storage of 472.3753 is -120472.3753; interest is 80000 * 0.0015 + 40472.3753 *
    # 0.0040 = 281.8895012, rounded up to 281.8896.
    assert (first["reason"], first["available"]) == ("over_credit_limit", -40000)
    assert after_period_1 == Decimal("-120754.2649")
    assert buys[-1]["accepted"]
    assert {buy["reason"] for buy in buys[:-1]} == {"over_credit_limit"}
    assert payments > 0
    # The panels fit the cash and the credit limit, but not with the open order.
    [outcome] = checked["outcomes"]
    assert outcome["asked"] <= without_order
    assert (outcome["reason"], outcome["available"]) == (
        "over_credit_limit",
        without_order - committed,
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    "name",
    [
        "demand-surge",
        "supplier-outage",
        "material-shortage",
        "quality-crisis",
        "transport-delays",
        "line-breakdown",
        "regional-crisis",
        "surge-and-breakdown",
    ],
)
def test_every_written_disruption_starts_and_ends_in_the_periods_it_names(name: str):
    with api_client() as client:
        written = content_of(client, name)["disruptions"]
        run = start(client, name)
        run_to_the_end(client, run)
        _, periods = get(client, f"/runs/{run['id']}/periods")

    told: dict[tuple[str, str], list[int]] = {}
    for period in periods["periods"]:
        for step in period["steps"]:
            if step["step"] != "apply_events":
                continue
            for event in step["events"]:
                if event["kind"] in ("disruption_started", "disruption_ended"):
                    told.setdefault((event["reference"], event["kind"]), []).append(
                        period["period"]
                    )
                if event["kind"] == "breakdown":
                    told.setdefault((event["reference"], "breakdown"), []).append(
                        period["period"]
                    )
    for number, disruption in enumerate(written, start=1):
        reference = f"disruption-{number}"
        start_period = disruption["start"]
        if disruption["kind"] == "line_breakdown":
            assert told[(reference, "breakdown")] == [start_period]
        else:
            assert told[(reference, "disruption_started")] == [start_period]
            ended = start_period + disruption["duration"]
            assert told[(reference, "disruption_ended")] == [ended]


@pytest.mark.slow
def test_a_material_shortage_stops_every_buy_of_both_microchips_in_its_periods():
    manifest, scenario = example_bodies("material-shortage")
    # Cash to stay within the credit line through period 42.
    scenario["start"]["cash"] = "10000000"
    with api_client() as client:
        run = start_run(client, manifest, scenario, seed=1)
        for period in range(1, 10):
            submit(client, run["id"], period, [])
        check = {
            "period": 10,
            "decisions": [
                chips("200"),
                chips("500"),
                alternative_chips("150"),
                alternative_chips("151"),
            ],
        }
        _, shortage = post(client, f"/runs/{run['id']}/checks", check)
        for period in range(10, 42):
            submit(client, run["id"], period, [])
        check = {"period": 42, "decisions": [chips("500")]}
        _, after = post(client, f"/runs/{run['id']}/checks", check)

    below, over, alternative_max, alternative_over = shortage["outcomes"]
    assert (below["accepted"], below["reason"]) == (False, "below_min_quantity")
    assert (below["asked"], below["available"]) == (Decimal(200), Decimal(500))
    # The largest order is 2000 times the share left, 1 - 1, so 0.
    assert (over["accepted"], over["reason"]) == (False, "over_max_quantity")
    assert (over["asked"], over["available"]) == (Decimal(500), Decimal(0))
    assert (alternative_max["accepted"], alternative_max["reason"]) == (
        False,
        "over_max_quantity",
    )
    assert (alternative_max["asked"], alternative_max["available"]) == (
        Decimal(150),
        Decimal(0),
    )
    assert (alternative_over["accepted"], alternative_over["reason"]) == (
        False,
        "over_max_quantity",
    )
    assert (alternative_over["asked"], alternative_over["available"]) == (
        Decimal(151),
        Decimal(0),
    )
    [bought] = after["outcomes"]
    assert bought["accepted"] is True


def test_the_launched_sensor_gateway_has_no_stock_at_the_close_of_period_1():
    with api_client() as client:
        run = start(client, "product-life-cycle")
        _, observation = submit(client, run["id"], 1, [])

    stock = observation["stock"]
    assert stock["distribution-centre"].get("sensor-gateway", 0) == 0
    assert stock["main-plant"].get("sensor-gateway", 0) == 0


# The only buys are of pcb blanks, so every delivery is one of them.
@pytest.mark.slow
def test_a_quality_crisis_accepts_one_thousandth_of_the_pcb_blanks_of_its_periods():
    buys = {
        period: [
            {
                "kind": "buy",
                "supplier": "emea-electronic-parts",
                "material": "pcb-blank",
                "quantity": "100",
                "warehouse": "main-plant",
            }
        ]
        for period in range(5, 43)
    }
    accepted: dict[str, dict[int, Decimal]] = {}
    with api_client() as client:
        for name in ("steady-market", "quality-crisis"):
            manifest, scenario = example_bodies(name)
            scenario["start"]["cash"] = "10000000"
            run = start_run(client, manifest, scenario, seed=3)
            run_to_the_end(client, run, buys)
            _, periods = get(client, f"/runs/{run['id']}/periods")
            accepted[name] = {
                period["period"]: sum(
                    (
                        event["accepted"]
                        for step in period["steps"]
                        for event in step.get("events", [])
                        if event["kind"] == "delivery"
                    ),
                    Decimal(0),
                )
                for period in periods["periods"]
            }

    assert sum(accepted["steady-market"][period] for period in range(9, 41)) > 0
    for period in range(8, 45):
        steady = accepted["steady-market"][period]
        factor = Decimal("0.001") if 9 <= period <= 40 else Decimal(1)
        assert abs(accepted["quality-crisis"][period] - steady * factor) <= 0.01


@pytest.mark.slow
def test_forecasts_cover_the_next_6_periods_of_every_pair_up_to_the_horizon():
    with api_client() as client:
        run = start(client, "forecasts")
        _, first = get(client, f"/runs/{run['id']}/observation")
        observation = first
        for period in range(1, 45):
            _, observation = submit(client, run["id"], period, [])
        run_to_the_end(client, run | {"period": 45})
        _, world = get(client, f"/runs/{run['id']}/world")

    assert observation["period"] == 45
    assert len(first["forecasts"]) == 10
    for pair, forecasts in first["forecasts"].items():
        assert [entry["period"] for entry in forecasts] == list(range(2, 8))
        for entry in forecasts:
            demand = world["demand"][pair][entry["period"] - 1]
            assert abs(entry["quantity"] - demand) <= (
                demand * (Decimal("0.20") + Decimal("0.04") * (entry["period"] - 2))
                + Decimal("0.001")
            )
    for forecasts in observation["forecasts"].values():
        assert [entry["period"] for entry in forecasts] == list(range(46, 52))


@pytest.mark.parametrize(
    ("name", "seen_from"), [("notice", 6), ("supplier-outage", 10)]
)
def test_an_announced_outage_is_seen_4_periods_before_it_starts(
    name: str, seen_from: int
):
    with api_client() as client:
        run = start(client, name)
        _, observation = get(client, f"/runs/{run['id']}/observation")
        seen: list[int] = []
        for period in range(1, 12):
            if observation["disruptions"]:
                seen.append(period)
            _, observation = submit(client, run["id"], period, [])

    assert seen[0] == seen_from


def test_hidden_groups_hide_parameters_but_keep_observed_outcomes():
    with api_client() as client:
        run = start(client, "hidden-groups")
        texts = [write_json(run["description"])]
        produce = {
            "kind": "produce",
            "line": "final-assembly-line",
            "item": "industrial-controller",
            "quantity": "10",
        }
        _, observation = submit(client, run["id"], 1, [produce])
        texts.append(write_json(observation))
        for period in range(2, 4):
            _, observation = submit(client, run["id"], period, [])
            texts.append(write_json(observation))
        _, periods = get(client, f"/runs/{run['id']}/periods")

    for text in texts:
        for word in HIDDEN_WORDS:
            assert f'"{word}"'.encode() not in text
    closed = periods["periods"][0]["steps"][-1]["measures"]
    made = closed["lines"]["final-assembly-line/industrial-controller"]
    assert made["units_good"] + made["units_scrap"] == 10


@pytest.mark.slow
def test_a_24_period_capacity_cut_stops_the_smt_line():
    with api_client() as client:
        run = start(client, "capacity-cut")
        _, observation = get(client, f"/runs/{run['id']}/observation")
        seen: dict[int, dict[str, Any]] = {}
        for period in range(1, 42):
            seen[period] = observation["lines"]["smt-line"]
            _, observation = submit(client, run["id"], period, [])

    for period in range(18, 42):
        line = seen[period]
        assert line["regular_hours_available"] == 0
        assert line["overtime_hours_available"] == 0


@pytest.mark.slow
def test_a_yield_drop_keeps_one_twentieth_of_the_good_boards_of_its_periods():
    produce = {
        "kind": "produce",
        "line": "smt-line",
        "item": "control-board",
        "quantity": "50",
    }
    with api_client() as client:
        run = start(client, "yield-drop", seed=2)
        run_to_the_end(client, run, {7: [produce]})
        _, world = get(client, f"/runs/{run['id']}/world")
        _, periods = get(client, f"/runs/{run['id']}/periods")

    drawn = world["yields"]["smt-line/control-board"][6]
    measures = periods["periods"][6]["steps"][-1]["measures"]
    good = measures["lines"]["smt-line/control-board"]["units_good"]
    expected = (50 * drawn * Decimal("0.05")).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_EVEN
    )
    assert good == expected


@pytest.mark.slow
def test_a_price_change_quadruples_the_microchip_from_period_8_and_leaves_microchip_b():
    with api_client() as client:
        # Cash for the three buys and the rest of the run.
        scenario = content_of(client, "price-change")
        scenario["start"]["cash"] = "10000000"
        _, manifests = get(client, "/manifests")
        [manifest_id] = [manifest["id"] for manifest in manifests["manifests"]]
        _, stored = post(client, f"/manifests/{manifest_id}/scenarios", scenario)
        _, run = post(client, "/runs", {"scenario_id": stored["id"], "seed": 2})
        _, observation = get(client, f"/runs/{run['id']}/observation")
        seen: list[int] = []
        prices: dict[tuple[int, str], Decimal] = {}
        for period in range(1, 10):
            if observation["disruptions"]:
                seen.append(period)
            decisions = [chips("500")] if period in (7, 8, 9) else []
            if period == 8:
                decisions.append(alternative_chips("500"))
            _, observation = submit(client, run["id"], period, decisions)
            for order in observation["supplier_orders"]:
                if order["placed"] == period:
                    prices[period, order["material"]] = order["unit_price"]
        run_to_the_end(client, run | {"period": 10})
        _, world = get(client, f"/runs/{run['id']}/world")

    path = "suppliers.apac-chips.catalogue.microchip.price"
    drawn = world["parameters"][path]["value"]
    # 500 chips are below the first tier of 1000, so they pay the drawn price.
    assert seen[0] == 8
    assert prices[7, "microchip"] == drawn
    assert prices[8, "microchip"] == drawn * Decimal("4")
    assert prices[9, "microchip"] == drawn * Decimal("4")
    assert prices[8, "microchip"] == (drawn * Decimal("4.0")).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_EVEN
    )
    # microchip-b keeps its catalogue price of 7.7000 during the change.
    assert prices[8, "microchip-b"] == Decimal("7.7000")


def test_harness_production_releases_space_for_a_minimum_chip_order():
    with api_client() as client:
        run = start(client, "full-warehouse")
        for period, quantity in ((1, "400"), (2, "100")):
            _, observation = submit(
                client,
                run["id"],
                period,
                [
                    {
                        "kind": "produce",
                        "line": "module-assembly-line",
                        "item": "cable-harness",
                        "quantity": quantity,
                    }
                ],
            )
            assert observation["outcomes"][0]["accepted"] is True
        _, checked = post(
            client,
            f"/runs/{run['id']}/checks",
            {"period": 3, "decisions": [chips("500")]},
        )

    assert checked["outcomes"][0]["accepted"] is True
