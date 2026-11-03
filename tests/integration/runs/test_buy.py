from decimal import Decimal
from typing import Any

import pytest
from factories import (
    api_client,
    buy,
    delivery_partition_bodies,
    get,
    produce,
    records,
    run_to_the_end,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)

from factory_simulator.api.record.models.run import Period


# The deliveries of period 2 of the factory of delivery partitions after the buys of
# period 1: the units arrived and accepted, the payments, the chips in stock and the
# cash at the close of period 2.
def second_period_of_chips(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    with api_client() as client:
        run = start_run(client, *delivery_partition_bodies())
        for period, submitted in ((1, decisions), (2, [])):
            status, answer = submit(client, run["id"], period, submitted)
            assert status == 200, answer
        _, periods = get(client, f"/runs/{run['id']}/periods")
    period = periods["periods"][1]
    closed = {step["step"]: step for step in period["steps"]}["close_period"]
    suppliers = closed["measures"]["suppliers"]["chip-maker/chip"]
    return {
        "units_arrived": suppliers["units_arrived"],
        "units_accepted": suppliers["units_accepted"],
        "units_lost_in_delivery": suppliers["units_lost_in_delivery"],
        "material_payment": sum(
            row["amount"]
            for row in period["ledger"]
            if row["kind"] == "material_payment"
        ),
        "chip_stock": closed["state"]["stock"]["main"]["chip"],
        "cash": closed["state"]["cash"],
    }


def test_materials_delivered_at_the_start_of_a_period_feed_production_that_period():
    manifest = tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["lead_time"] = 1
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["chip"] = "0"
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        submit(client, run["id"], 1, [buy("40")])
        status, answer = submit(client, run["id"], 2, [produce("board", "20")])

    assert status == 200
    assert [outcome["accepted"] for outcome in answer["outcomes"]] == [True]


def test_buys_do_not_change_the_world_of_a_run():
    worlds: list[object] = []
    for decisions in ({}, {1: [buy("100")], 2: [buy("50")]}):
        with api_client() as client:
            run = start_run(client, seed=11)
            run_to_the_end(client, run, decisions)
            worlds.append(get(client, f"/runs/{run['id']}/world")[1])

    assert worlds[0] == worlds[1]


def test_a_stored_buy_holds_its_fields_with_express_false_when_left_out():
    with api_client() as client:
        run = start_run(client)
        submit(client, run["id"], 1, [buy("12.5")])
        stored = records(client, Period, run_id=run["id"])

    assert stored[0]["submission"]["decisions"] == [
        {
            "kind": "buy",
            "supplier": "chip-maker",
            "material": "chip",
            "quantity": Decimal("12.5"),
            "express": False,
            "warehouse": "main",
        }
    ]


@pytest.mark.slow
def test_1000_buys_of_a_thousandth_deliver_the_chips_of_one_buy():
    bulk = second_period_of_chips([buy("1.000")])
    split = second_period_of_chips([buy("0.001")] * 1000)

    # 1 * 0.6 = 0.6 chips arrive, are accepted and paid 0.6 * 0.5 = 0.3, and 0.4 are
    # lost; cash is 1000 - 0.3.
    expected = {
        "units_arrived": Decimal("0.6"),
        "units_accepted": Decimal("0.6"),
        "units_lost_in_delivery": Decimal("0.4"),
        "material_payment": Decimal("-0.3"),
        "chip_stock": Decimal("0.6"),
        "cash": Decimal("999.7"),
    }
    assert bulk == expected
    assert split == expected
