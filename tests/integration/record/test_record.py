import copy
import hashlib
from decimal import Decimal
from typing import cast

import pytest
from factories import (
    api_client,
    buy,
    engine_of,
    get,
    get_message_by_message,
    measures_of,
    records,
    run_to_the_end,
    start_run,
    submit,
    threaded_api_client,
    tiny_manifest,
    tiny_scenario,
)
from sqlalchemy.pool import QueuePool
from starlette.types import Message

from factory_simulator.api.record.models.run import Event, Measure, Period
from factory_simulator.api.services.runs import periods
from factory_simulator.engine import MEASURE_KINDS

BUY = {"kind": "buy", "supplier": "chip-maker", "material": "chip", "quantity": "40"}
SHIP = {"kind": "ship", "order": "order-1-1", "quantity": "4"}
# The SHA-256 of the periods of the tiny factory run with seed 7, a ship and a buy in
# period 1 and a buy in period 2.
PERIODS_DIGEST = (
    "05bfbb7e145f17dc8fab142759365e00"  # pragma: allowlist secret
    "889c18537f54c877c3716abec391e4c6"  # pragma: allowlist secret
)


def test_the_periods_and_the_table_of_measures_hold_the_same_measures():
    with api_client() as client:
        run = start_run(client)
        run_to_the_end(client, run)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        rows = records(client, Measure, run_id=run["id"])

    for period in periods["periods"]:
        close = period["steps"][-1]
        assert close["measures"] == measures_of(rows, period["period"])
    first = periods["periods"][0]["steps"][-1]["measures"]
    assert first["total"]["units_shipped"] == Decimal(0)
    assert first["total"]["on_time_share"] is None
    assert first["warehouses"]["main/chip"]["stock"] == Decimal(100)


def test_the_result_sums_flows_keeps_levels_at_the_end_and_ratios_of_the_run():
    ship = {"kind": "ship", "order": "order-1-1", "quantity": "4"}
    with api_client() as client:
        run = start_run(client)
        run_to_the_end(client, run, {1: [ship]})
        _, result = get(client, f"/runs/{run['id']}/result")

    total = result["measures"]["total"]
    assert total["units_ordered"] == Decimal(20)
    assert total["units_shipped"] == Decimal(4)
    assert total["cash"] == result["cash_at_end"]
    assert total["on_time_share"] == Decimal(1)
    assert total["service"] == Decimal("0.2")
    assert result["measures"]["pairs"]["distributor/monitor"]["units_lost"] == 16


def test_the_arrival_of_a_buy_is_in_the_private_state_and_not_in_the_public_one():
    manifest = tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["lead_time"] = 3
    scenario = tiny_scenario()
    scenario["start"]["supplier_orders"] = [
        {"supplier": "chip-maker", "material": "chip", "quantity": "10", "arrival": 4}
    ]
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, {2: [buy("100")]})
        second = records(client, Period, run_id=run["id"], period=2)[0]

    assert second["private"] == {
        "supplier_orders": {"buy-2-1": {"arrival": 5, "backfill": None}}
    }
    assert second["state"]["supplier_orders"] == [
        {
            "id": "buy-0-1",
            "supplier": "chip-maker",
            "material": "chip",
            "warehouse": "main",
            "quantity": 10,
            "open_quantity": 10,
            "unit_price": Decimal("0.5"),
            "express": False,
            "placed": 0,
            "arrival": 4,
            "tier": None,
        },
        {
            "id": "buy-2-1",
            "supplier": "chip-maker",
            "material": "chip",
            "warehouse": "main",
            "quantity": 100,
            "open_quantity": 100,
            "unit_price": Decimal("0.5"),
            "express": False,
            "placed": 2,
            "tier": None,
        },
    ]


def test_every_summed_measure_of_a_group_in_the_result_is_the_sum_over_its_members():
    manifest = tiny_manifest()
    suppliers = manifest["suppliers"]
    suppliers["chip-store"] = copy.deepcopy(suppliers["chip-maker"])
    for supplier in suppliers.values():
        supplier["groups"] = ["apac"]
    manifest["groups"] = {"apac": {"kind": "region"}}
    buys = [
        {"kind": "buy", "supplier": supplier, "material": "chip", "quantity": "10"}
        for supplier in ("chip-maker", "chip-store")
    ]
    with api_client() as client:
        run = start_run(client, manifest, tiny_scenario(), seed=5)
        run_to_the_end(client, run, {1: buys})
        _, result = get(client, f"/runs/{run['id']}/result")

    group = result["measures"]["groups"]["apac"]
    members = result["measures"]["suppliers"]
    summed = [
        name
        for name, value in group.items()
        if MEASURE_KINDS.get(name) in ("flow", "level") and value is not None
    ]
    assert summed
    for name in summed:
        total = sum(
            (Decimal(member[name] or 0) for member in members.values()), Decimal(0)
        )
        assert group[name] == total, name


def test_the_deliveries_of_12_buys_are_listed_in_the_order_of_their_numbers():
    manifest = tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["lead_time"] = 1
    chip_buy = {
        "kind": "buy",
        "supplier": "chip-maker",
        "material": "chip",
        "quantity": "10",
    }
    with api_client() as client:
        run = start_run(client, manifest, tiny_scenario())
        run_to_the_end(client, run, {1: [chip_buy] * 12})
        _, periods = get(client, f"/runs/{run['id']}/periods")
        rows = records(client, Event, run_id=run["id"], period=2, kind="delivery")

    numbered = [f"buy-1-{number}" for number in range(1, 13)]
    second = periods["periods"][1]["steps"][0]
    assert [event["reference"] for event in second["events"]] == numbered
    assert sorted((row["position"], row["reference"]) for row in rows) == list(
        zip(range(1, 13), numbered, strict=True)
    )


def test_the_observation_size_of_a_period_is_the_length_of_its_observation():
    with api_client() as client:
        run = start_run(client)
        observation = client.get(f"/api/v1/runs/{run['id']}/observation").text
        submit(client, run["id"], 1, [])
        rows = records(
            client, Measure, run_id=run["id"], period=1, name="observation_size"
        )

    assert [row["value"] for row in rows] == [len(observation)]


def test_reading_the_periods_holds_no_connection_while_it_builds_the_answer(
    monkeypatch: pytest.MonkeyPatch,
):
    with threaded_api_client() as client:
        run = start_run(client)
        run_to_the_end(client, run, {1: [SHIP, BUY], 2: [BUY]})
        connection_pool = cast(QueuePool, engine_of(client).pool)
        counts: list[int] = []
        period_events = periods.period_events

        def counted(stored: list[dict[str, object]]) -> dict[str, list[object]]:
            counts.append(connection_pool.checkedout())
            return period_events(stored)

        monkeypatch.setattr(periods, "period_events", counted)
        response = client.get(f"/api/v1/runs/{run['id']}/periods")

    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == PERIODS_DIGEST
    assert counts == [0] * 5


@pytest.mark.parametrize("route", ["/result", "/export"])
def test_the_answer_of_a_finished_run_is_sent_with_no_connection_held(route: str):
    with api_client() as client:
        run = start_run(client)
        run_to_the_end(client, run)
        connection_pool = cast(QueuePool, engine_of(client).pool)
        statuses: list[int] = []
        counts: list[int] = []

        def read(message: Message) -> None:
            if message["type"] == "http.response.start":
                statuses.append(message["status"])
            if message["type"] == "http.response.body":
                counts.append(connection_pool.checkedout())

        get_message_by_message(client, f"/runs/{run['id']}{route}", read)

    assert statuses == [200]
    assert counts
    assert counts == [0] * len(counts)
