import copy
from typing import Any

import pytest
from factories import (
    api_client,
    assert_run_balances,
    get,
    rows_of_run,
    run_to_the_end,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 52


def three_lines() -> dict[str, Any]:
    manifest = tiny_manifest()
    for number in (2, 3):
        manifest["lines"][f"line-{number}"] = copy.deepcopy(manifest["lines"]["line-1"])
    return manifest


def trouble_scenario() -> dict[str, Any]:
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["random_disruptions"] = [
        {
            "name": "line-trouble",
            "kind": "line_breakdown",
            "target": "all",
            "chance": "0.0500",
            "loss": "0.3000",
            "choose": "one",
        }
    ]
    return scenario


@pytest.mark.slow
@pytest.mark.parametrize("seed", [1, 2])
def test_line_trouble_draws_the_same_breakdowns_and_shows_them_in_the_condition(
    seed: int,
):
    with api_client() as client:
        runs = [
            start_run(client, three_lines(), trouble_scenario(), seed=seed)
            for _ in range(2)
        ]
        for run in runs:
            run_to_the_end(client, run)
        _, world = get(client, f"/runs/{runs[0]['id']}/world")
        _, periods = get(client, f"/runs/{runs[0]['id']}/periods")
        _, result = get(client, f"/runs/{runs[0]['id']}/result")
        rows = [rows_of_run(client, run["id"]) for run in runs]

    assert world["disruptions"]
    assert rows[0] == rows[1]
    assert_run_balances(periods, result)
    for disruption in world["disruptions"]:
        [line_id] = disruption["target"]
        steps = {
            step["step"]: step
            for step in periods["periods"][disruption["start"] - 1]["steps"]
        }
        references = [
            event["reference"]
            for event in steps["apply_events"]["events"]
            if event["kind"] == "breakdown" and event["line"] == line_id
        ]
        assert disruption["id"] in references
