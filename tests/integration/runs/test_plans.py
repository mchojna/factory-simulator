from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    get,
    produce,
    run_to_the_end,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)

PLAN = {
    "kind": "produce",
    "line": "line-1",
    "item": "board",
    "quantity": "10",
    "start": 4,
}


def total(periods: dict[str, Any], period: int, name: str) -> Decimal:
    measures = periods["periods"][period - 1]["steps"][-1]["measures"]
    return Decimal(measures["total"][name])


def test_the_observation_lists_a_plan_until_it_runs_and_then_its_outcome():
    with api_client() as client:
        run = start_run(client, tiny_manifest(), tiny_scenario())
        submit(client, run["id"], 1, [])
        _, third = submit(client, run["id"], 2, [PLAN])
        submit(client, run["id"], 3, [])
        _, fifth = submit(client, run["id"], 4, [])

    assert third["plans"] == [
        {
            "id": "make-2-1",
            "start": 4,
            "line": "line-1",
            "item": "board",
            "quantity": Decimal(10),
            "recipe": "standard",
            "overtime": False,
        }
    ]
    assert fifth["plans"] == []
    [outcome] = fifth["outcomes"]
    assert (outcome["decision_id"], outcome["reference"]) == ("2-1", "make-2-1")


def test_the_measures_count_a_plan_when_made_and_when_run():
    with api_client() as client:
        run = start_run(client, tiny_manifest(), tiny_scenario())
        run_to_the_end(client, run, {2: [PLAN]})
        _, periods = get(client, f"/runs/{run['id']}/periods")

    assert total(periods, 2, "plans_made") == 1
    assert total(periods, 4, "plans_run") == 1
    assert total(periods, 2, "decisions_accepted") == 1
    assert total(periods, 4, "decisions_accepted") == 1
    assert total(periods, 3, "decisions_accepted") == 0


def test_a_start_sent_as_text_is_read_as_a_period():
    with api_client() as client:
        run = start_run(client, tiny_manifest(), tiny_scenario())
        status, second = submit(client, run["id"], 1, [PLAN | {"start": "3"}])

    assert status == 200
    [plan] = second["plans"]
    assert plan["start"] == 3


# The plan of 90 boards takes 90 * 0.100 = 9 of the 10 hours of period 2, so a produce
# of 20 boards decided in period 2 asks 2 hours and finds 1.
def test_a_plan_runs_before_a_produce_decided_in_its_start_period():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(wear_per_period="0.0000", wear_per_hour="0.0000")
    scenario = tiny_scenario()
    scenario["horizon"] = 2
    scenario["start"]["stock"]["main"]["chip"] = "300"
    decisions = {1: [produce("board", "90", start=2)], 2: [produce("board", "20")]}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")

    outcomes = [
        outcome
        for step in periods["periods"][1]["steps"]
        for outcome in step.get("outcomes", [])
    ]
    assert [(outcome["decision_id"], outcome["accepted"]) for outcome in outcomes] == [
        ("1-1", True),
        ("2-1", False),
    ]
    rejected = outcomes[1]
    assert (rejected["reason"], rejected["asked"], rejected["available"]) == (
        "not_enough_hours",
        Decimal("2.000"),
        Decimal(1),
    )
