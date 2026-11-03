import copy
from typing import Any

from factories import (
    api_client,
    records,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)

from factory_simulator.api.record.models.run import Period

PRODUCE = {"kind": "produce", "line": "line-1", "item": "board", "quantity": "10"}


def two_recipe_bodies() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = tiny_manifest()
    manifest["materials"]["chip-b"] = copy.deepcopy(manifest["materials"]["chip"])
    catalogue = manifest["suppliers"]["chip-maker"]["catalogue"]
    catalogue["chip-b"] = copy.deepcopy(catalogue["chip"])
    board = manifest["components"]["board"]
    board["recipes"]["alternative"] = {"chip-b": "2.000"}
    board["default_recipe"] = "standard"
    manifest["lines"]["line-1"]["items"]["board"]["lead_time"] = 2
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["chip-b"] = "100"
    return manifest, scenario


def test_the_observation_shows_the_recipe_and_the_unknown_recipe_outcome():
    with api_client() as client:
        run = start_run(client, *two_recipe_bodies())
        _, second = submit(
            client,
            run["id"],
            1,
            [PRODUCE | {"recipe": "alternative"}, PRODUCE | {"recipe": "premium"}],
        )

    [production] = second["production"]
    assert production["recipe"] == "alternative"
    assert [outcome.get("reason") for outcome in second["outcomes"]] == [
        None,
        "unknown_recipe",
    ]


def test_the_description_shows_every_recipe_and_the_default():
    with api_client() as client:
        run = start_run(client, *two_recipe_bodies())

    board = run["description"]["manifest"]["components"]["board"]
    assert set(board["recipes"]) == {"standard", "alternative"}
    assert board["default_recipe"] == "standard"


def test_a_stored_produce_holds_the_default_recipe_when_it_names_none():
    with api_client() as client:
        run = start_run(client, *two_recipe_bodies())
        submit(client, run["id"], 1, [PRODUCE])
        [stored] = records(client, Period, run_id=run["id"])

    [decision] = stored["submission"]["decisions"]
    assert decision["recipe"] == "standard"
