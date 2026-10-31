from decimal import Decimal
from typing import Any

import pytest
from factories import (
    api_client,
    get,
    produce,
    records,
    ship,
    start_run,
    submit,
    tiny_scenario,
    yield_partition_bodies,
)

from factory_simulator.api.record.models.run import Period


# The ledger rows of production cost, the chips used and the boards made and in stock
# at the close of period 1 of the factory of yield partitions, after the decisions.
def first_period_of_boards(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    with api_client() as client:
        run = start_run(client, *yield_partition_bodies())
        status, answer = submit(client, run["id"], 1, decisions)
        assert status == 200, answer
        _, periods = get(client, f"/runs/{run['id']}/periods")
    period = periods["periods"][0]
    closed = {step["step"]: step for step in period["steps"]}["close_period"]
    return {
        "production_cost": sum(
            row["amount"]
            for row in period["ledger"]
            if row["kind"] == "production_cost"
        ),
        "chips_used": closed["measures"]["warehouses"]["main/chip"]["units_used"],
        "boards": closed["measures"]["lines"]["line-1/board"],
        "board_stock": closed["state"]["stock"]["main"]["board"],
    }


def test_output_enters_stock_at_the_close_and_ships_from_the_next_period():
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["monitor"] = "0"
    with api_client() as client:
        run = start_run(client, scenario=scenario)
        _, first = submit(
            client, run["id"], 1, [produce("monitor", "4"), ship("order-1-1", "4")]
        )
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, second = submit(client, run["id"], 2, [ship("order-1-1", "4")])

    closed = {step["step"]: step for step in periods["periods"][0]["steps"]}
    assert [
        outcome["reason"] for outcome in first["outcomes"] if "reason" in outcome
    ] == ["not_enough_stock"]
    assert closed["close_period"]["state"]["stock"]["main"]["monitor"] == 4
    assert closed["close_period"]["state"]["production"] == []
    assert [outcome["accepted"] for outcome in second["outcomes"]] == [True]


def test_a_stored_produce_holds_its_fields_with_their_defaults_when_left_out():
    with api_client() as client:
        run = start_run(client)
        submit(client, run["id"], 1, [produce("board", "2.5")])
        stored = records(client, Period, run_id=run["id"])

    assert stored[0]["submission"]["decisions"] == [
        {
            "kind": "produce",
            "line": "line-1",
            "item": "board",
            "quantity": Decimal("2.5"),
            "recipe": "standard",
            "overtime": False,
            "start": 1,
        }
    ]


@pytest.mark.slow
def test_1000_productions_of_a_thousandth_make_the_boards_of_one_production():
    one = first_period_of_boards([produce("board", "1.000")])
    split = first_period_of_boards([produce("board", "0.001")] * 1000)

    expected = {
        "production_cost": Decimal(-1),
        "chips_used": Decimal(2),
        "boards": {
            "units_good": Decimal("0.6"),
            "units_scrap": Decimal("0.4"),
            "units_started": Decimal(1),
        },
        "board_stock": Decimal("0.6"),
    }
    assert one == expected
    assert split == expected
