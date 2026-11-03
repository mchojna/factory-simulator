from decimal import Decimal
from typing import Any

import pytest
from factories import (
    api_client,
    back_and_forth_transfers,
    get,
    post,
    produce,
    run_to_the_end,
    ship,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
    transfer,
    transfer_bound_bodies,
)


def routed_bodies(
    lead_time: object = 0, centre_accepts: list[str] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = tiny_manifest()
    manifest["warehouses"]["centre"] = {
        "capacity": "100.000",
        "accepts": centre_accepts or ["materials", "components", "products"],
    }
    manifest["lines"]["line-1"]["warehouse"] = "centre"
    manifest["routes"] = {
        "main": {"centre": {"cost": "0.2000", "lead_time": lead_time}}
    }
    scenario = tiny_scenario()
    scenario["start"]["stock"] = {
        "main": {"chip": "100", "board": "10", "monitor": "5"}
    }
    return manifest, scenario


def test_chips_transferred_at_once_feed_a_produce_of_the_same_submission():
    with api_client() as client:
        run = start_run(client, *routed_bodies())
        _, observation = submit(
            client, run["id"], 1, [produce("board", "10"), transfer("chip", "20")]
        )

    assert [
        (outcome["decision"]["kind"], outcome["accepted"])
        for outcome in observation["outcomes"]
    ] == [
        ("transfer", True),
        ("produce", True),
    ]


def test_units_transferred_at_once_ship_only_from_the_next_period():
    with api_client() as client:
        run = start_run(client, *routed_bodies())
        _, first = submit(
            client,
            run["id"],
            1,
            [transfer("monitor", "5"), ship("order-1-1", "4", warehouse="centre")],
        )
        _, second = submit(
            client, run["id"], 2, [ship("order-1-1", "4", warehouse="centre")]
        )

    assert [
        (outcome["decision"]["kind"], outcome["accepted"], outcome.get("reason"))
        for outcome in first["outcomes"]
    ] == [
        ("ship", False, "not_enough_stock"),
        ("transfer", True, None),
    ]
    assert second["outcomes"][0]["accepted"] is True


def test_the_observation_shows_transfers_on_the_way_and_their_arrival():
    with api_client() as client:
        run = start_run(client, *routed_bodies(lead_time=2))
        _, on_the_way = submit(client, run["id"], 1, [transfer("monitor", "2")])
        submit(client, run["id"], 2, [])
        _, arrived = get(client, f"/runs/{run['id']}/observation")

    assert on_the_way["transfers"] == [
        {
            "id": "transfer-1-1",
            "item": "monitor",
            "quantity": 2,
            "source": "main",
            "destination": "centre",
            "arrival": 3,
        }
    ]
    assert on_the_way["space"]["centre"]["reserved"] == Decimal("0.3")
    assert arrived["transfers"] == []
    assert [
        event["reference"]
        for event in arrived["events"]
        if event["kind"] == "transfer_arrived"
    ] == ["transfer-1-1"]


def test_the_result_counts_transfers_per_route_and_storage_at_the_destination():
    with api_client() as client:
        run = start_run(client, *routed_bodies(lead_time=1))
        run_to_the_end(client, run, {1: [transfer("monitor", "2")]})
        _, result = get(client, f"/runs/{run['id']}/result")
        _, periods = get(client, f"/runs/{run['id']}/periods")

    measures = result["measures"]
    route = measures["routes"]["main/centre"]
    assert (route["units_transferred"], route["transfer_cost"]) == (2, Decimal("0.4"))
    storage = [
        measures["warehouses"][warehouse]["storage_cost"]
        for warehouse in ("main", "centre")
    ]
    assert sum(storage) == measures["total"]["storage_cost"]
    # On the way at the close of period 1: 2 * 0.1 = 0.2. At centre at the closes of
    # periods 2 to 5: 4 * 0.2 = 0.8.
    assert storage == [Decimal(3), Decimal("1.0")]
    [on_the_way] = [
        row
        for row in periods["periods"][0]["ledger"]
        if (row["kind"], row["reference"]) == ("storage_cost", "transfer-1-1")
    ]
    assert on_the_way["amount"] == Decimal("-0.2")


def test_a_drawn_route_cost_keeps_its_value_when_another_route_is_added():
    cost = {"min": "0.1000", "max": "0.9000"}
    one, _ = routed_bodies()
    one["routes"]["main"]["centre"]["cost"] = cost
    two, scenario = routed_bodies()
    two["routes"]["main"]["centre"]["cost"] = cost
    two["routes"]["centre"] = {"main": {"cost": cost, "lead_time": 1}}
    drawn: list[object] = []
    with api_client() as client:
        for manifest in (one, two):
            run = start_run(client, manifest, scenario, seed=11)
            run_to_the_end(client, run)
            _, world = get(client, f"/runs/{run['id']}/world")
            drawn.append(world["parameters"]["routes.main.centre.cost"])

    assert drawn[0] == drawn[1]


@pytest.mark.slow
def test_5001_transfers_of_one_chip_are_checked_and_submitted_alike_without_a_500():
    transfers = back_and_forth_transfers()
    with api_client() as client:
        run = start_run(client, *transfer_bound_bodies())
        body = {"period": 1, "decisions": transfers}
        check_status, checked = post(client, f"/runs/{run['id']}/checks", body)
        _, before = get(client, f"/runs/{run['id']}/observation")
        status, finished = submit(client, run["id"], 1, transfers)
        _, periods = get(client, f"/runs/{run['id']}/periods")

    assert (check_status, before["period"], before["cash"]) == (200, 1, 1000)
    assert (status, finished["finished"]) == (200, True)
    steps = {step["step"]: step for step in periods["periods"][0]["steps"]}
    outcomes = steps["execute_decisions"]["outcomes"]
    assert outcomes == checked["outcomes"]
    assert [outcome["accepted"] for outcome in outcomes] == [True] + [False] * 5000
    assert {outcome.get("reason") for outcome in outcomes[1:]} == {
        "transferred_this_period",
        "not_enough_stock",
    }
    costs = [
        (row["amount"], row["cash_after"])
        for row in periods["periods"][0]["ledger"]
        if row["kind"] == "transfer_cost"
    ]
    assert costs == [(-20000000000000000000000, -19999999999999999999000)]
