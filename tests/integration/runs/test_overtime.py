from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    get,
    run_to_the_end,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

PRODUCE = {"kind": "produce", "line": "line-1", "item": "monitor"}
IN_OVERTIME = {
    1: [PRODUCE | {"quantity": "20"}, PRODUCE | {"quantity": "8", "overtime": True}]
}


def overtime_bodies(
    disruptions: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(overtime_hours="4.000", overtime_cost="45.0000")
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["board"] = "100"
    scenario["disruptions"] = disruptions or []
    return manifest, scenario


def test_the_observation_shows_the_overtime_hours_left_after_a_breakdown():
    breakdown = {
        "kind": "line_breakdown",
        "target": ["line-1"],
        "start": 1,
        "loss": "0.5000",
    }
    with api_client() as client:
        run = start_run(client, *overtime_bodies([breakdown]))
        _, observation = get(client, f"/runs/{run['id']}/observation")

    assert observation["lines"]["line-1"]["overtime_hours_available"] == Decimal(2)


def test_an_overtime_production_books_its_production_then_its_overtime_cost():
    with api_client() as client:
        run = start_run(client, *overtime_bodies())
        run_to_the_end(client, run, IN_OVERTIME)
        _, periods = get(client, f"/runs/{run['id']}/periods")

    first = periods["periods"][0]
    rows = [
        (row["kind"], row["reference"], row["amount"])
        for row in first["ledger"]
        if row["kind"] in ("production_cost", "overtime_cost")
    ]
    assert rows == [
        ("production_cost", "make-1-1", Decimal(-40)),
        ("production_cost", "make-1-2", Decimal(-16)),
        ("overtime_cost", "make-1-2", Decimal(-180)),
    ]
    submission = first["steps"][3]["submission"]["decisions"]
    assert [decision["overtime"] for decision in submission] == [False, True]


def test_the_measures_keep_overtime_hours_and_cost_apart_from_regular_hours():
    with api_client() as client:
        run = start_run(client, *overtime_bodies())
        run_to_the_end(client, run, IN_OVERTIME)
        _, result = get(client, f"/runs/{run['id']}/result")

    line = result["measures"]["lines"]["line-1"]
    assert line["regular_hours"] == Decimal(10)
    assert line["overtime_hours"] == Decimal(4)
    assert line["overtime_cost"] == Decimal(180)
    assert result["measures"]["total"]["overtime_cost"] == Decimal(180)
    assert result["terms"]["overtime_cost"] == Decimal(180)
