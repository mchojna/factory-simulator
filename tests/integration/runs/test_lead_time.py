from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    get,
    run_to_the_end,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)

PRODUCE = {"kind": "produce", "line": "line-1", "item": "monitor", "quantity": "10"}
BUY = {"kind": "buy", "supplier": "chip-maker", "material": "chip", "quantity": "60"}


def two_period_bodies(
    disruptions: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = tiny_manifest()
    manifest["lines"]["line-1"]["items"]["monitor"].update(
        lead_time=2, **{"yield": "0.9500"}
    )
    manifest["warehouses"]["main"]["capacity"] = "2.000"
    scenario = tiny_scenario()
    scenario["horizon"] = 6
    scenario["start"]["stock"] = {"main": {"board": "20"}}
    scenario["disruptions"] = disruptions or []
    return manifest, scenario


def test_production_not_in_stock_is_observed_and_holds_its_space():
    with api_client() as client:
        run = start_run(client, *two_period_bodies())
        for period in (1, 2):
            submit(client, run["id"], period, [])
        _, period_4 = submit(client, run["id"], 3, [PRODUCE])
        _, period_5 = submit(client, run["id"], 4, [BUY])

    [production] = period_4["production"]
    assert production == {
        "id": "make-3-1",
        "line": "line-1",
        "item": "monitor",
        "recipe": "standard",
        "started": Decimal(10),
        "ready": 4,
    }
    [outcome] = period_5["outcomes"]
    assert (outcome["reason"], outcome["asked"], outcome["available"]) == (
        "not_enough_space",
        Decimal("0.6"),
        Decimal("0.5"),
    )


def test_a_yield_drop_is_reported_as_started_and_ended():
    drop = {
        "kind": "yield_drop",
        "target": ["line-1"],
        "start": 3,
        "duration": 2,
        "strength": "0.2000",
    }
    with api_client() as client:
        run = start_run(client, *two_period_bodies([drop]))
        run_to_the_end(client, run)
        _, periods = get(client, f"/runs/{run['id']}/periods")

    reported = [
        (period["period"], event["kind"], event["reference"])
        for period in periods["periods"]
        for step in period["steps"]
        for event in step.get("events", [])
        if event["kind"].startswith("disruption_")
    ]
    assert reported == [
        (3, "disruption_started", "disruption-1"),
        (5, "disruption_ended", "disruption-1"),
    ]


def test_production_counts_started_in_its_start_and_good_in_its_ready_period():
    with api_client() as client:
        run = start_run(client, *two_period_bodies())
        run_to_the_end(client, run, {3: [PRODUCE]})
        _, periods = get(client, f"/runs/{run['id']}/periods")

    def measures(period: int) -> dict[str, Any]:
        steps = periods["periods"][period - 1]["steps"]
        return steps[-1]["measures"]["lines"]["line-1/monitor"]

    assert measures(3)["units_started"] == Decimal(10)
    assert (measures(3)["units_good"], measures(3)["units_scrap"]) == (0, 0)
    assert measures(4)["units_good"] == Decimal("9.5")
    assert measures(4)["units_scrap"] == Decimal("0.5")


def test_the_public_state_holds_production_with_its_start_and_overtime():
    with api_client() as client:
        run = start_run(client, *two_period_bodies())
        for period in (1, 2):
            submit(client, run["id"], period, [])
        submit(client, run["id"], 3, [PRODUCE])
        _, periods = get(client, f"/runs/{run['id']}/periods")

    [production] = periods["periods"][2]["steps"][-1]["state"]["production"]
    assert set(production) == {
        "id",
        "line",
        "item",
        "recipe",
        "started",
        "start",
        "ready",
        "overtime",
    }
