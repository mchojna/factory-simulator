import copy
from decimal import Decimal
from typing import Any

import httpx2 as httpx
import pytest
from factories import (
    api_client,
    benchmark_client,
    example_count,
    get,
    hidden_yield_bodies,
    linear_factories,
    records,
    run_to_the_end,
    seeds,
    start_run,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given, settings

from factory_simulator.api.record.models.run import Run
from factory_simulator.api.record.models.scenario import Scenario
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.optimizers.no_decisions import no_decisions

FactoryBodies = tuple[dict[str, Any], dict[str, Any]]


def profit_with_empty_submissions(
    manifest: dict[str, Any], scenario: dict[str, Any], seed: int
) -> object:
    with api_client() as client:
        run = start_run(client, manifest, scenario, seed)
        run_to_the_end(client, run)
        _, result = get(client, f"/runs/{run['id']}/result")
        return result["profit"]


def played_with_nothing(
    manifest: dict[str, Any], scenario: dict[str, Any], seed: int
) -> tuple[dict[str, Any], list[str], list[str]]:
    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        stored_scenario = benchmark.send(client, "POST", path, scenario)
        manifest_id = benchmark.find_manifest(client, manifest["name"])
        scenario_id = benchmark.find_scenario(client, manifest_id, scenario["name"])
        run = benchmark.start_run(client, scenario_id, seed)
        result = benchmark.play_run(client, run, no_decisions)
    found = [manifest_id, scenario_id]
    return result, found, [stored_manifest["id"], stored_scenario["id"]]


def without_yields(manifest: dict[str, Any]) -> dict[str, Any]:
    changed = copy.deepcopy(manifest)
    for line_item in changed["lines"]["line-1"]["items"].values():
        line_item.pop("yield", None)
    return changed


# Every description and observation a run of no decisions shows, with its world and
# its result.
def played_and_seen(
    client: httpx.Client, scenario_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def agent(
        description: dict[str, Any], observation: dict[str, Any]
    ) -> list[dict[str, Any]]:
        seen.append({"description": description, "observation": observation})
        return []

    run = benchmark.start_run(client, scenario_id, 0)
    result = benchmark.play_run(client, run, agent)
    return seen, benchmark.read_world(client, run["id"]), result


def test_a_run_played_with_no_decisions_is_the_run_of_empty_submissions():
    manifest, scenario = tiny_manifest(), tiny_scenario()

    result, found, stored = played_with_nothing(manifest, scenario, 0)

    assert found == stored
    assert result["periods"] == 5
    assert str(result["profit"]) == str(
        profit_with_empty_submissions(manifest, scenario, 0)
    )


@pytest.mark.property
@settings(max_examples=example_count(25))
@given(linear_factories(), seeds)
def test_every_run_played_with_no_decisions_ends_with_the_profit_of_empty_submissions(
    factory: FactoryBodies, seed: int
):
    manifest, scenario = factory
    manifest.setdefault("name", "Generated factory")
    scenario.setdefault("name", "Generated scenario")

    result, *_ = played_with_nothing(manifest, scenario, seed)

    assert result["profit"] == profit_with_empty_submissions(manifest, scenario, seed)


def test_the_shown_description_gives_the_range_of_a_hidden_yield_and_nothing_else():
    manifest, scenario = hidden_yield_bodies()
    with benchmark_client() as client:
        stored = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        shown = benchmark.create_shown_description(client, stored["id"], 0, scenario)
        scenarios, runs = records(client, Scenario), records(client, Run)
        hidden = benchmark.start_run(client, scenario_id, 0)["description"]

    shown_board = shown["manifest"]["lines"]["line-1"]["items"]["board"]
    hidden_board = hidden["manifest"]["lines"]["line-1"]["items"]["board"]
    assert shown_board["yield"]["cut_mean"] == Decimal("0.900000")
    assert "yield" not in hidden_board
    assert without_yields(shown["manifest"]) == without_yields(hidden["manifest"])
    assert (len(scenarios), len(runs)) == (2, 1)


# The board yields of seed 0 are drawn per period between 0.8 and 1.0; the description
# the informed optimizer reads holds the range with its cut mean 0.9 and none of them.
def test_the_informed_optimizer_reads_the_range_of_a_hidden_yield_and_no_draw():
    manifest, scenario = hidden_yield_bodies()
    with benchmark_client() as client:
        stored = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        shown = benchmark.create_shown_description(client, stored["id"], 0, scenario)
        _, world, _ = played_and_seen(client, scenario_id)

    shown_board = shown["manifest"]["lines"]["line-1"]["items"]["board"]
    drawn = world["yields"]["line-1/board"]
    assert shown_board["yield"] == {
        "distribution": "uniform",
        "min": Decimal("0.8000"),
        "max": Decimal(1),
        "cut_mean": Decimal("0.9"),
    }
    assert len(drawn) == 3
    assert all(Decimal(value) != Decimal("0.9") for value in drawn)
    assert not any(str(value) in str(shown) for value in drawn)


# The twin of a scenario that hides the yield of boards, played to its end beside the
# scenario: its description shows the range of the yield, and its observations, its
# world and its profit are those of the scenario.
@pytest.mark.slow
def test_the_twin_of_a_hidden_yield_shows_the_range_and_draws_the_same_world():
    manifest, scenario = hidden_yield_bodies()
    with benchmark_client() as client:
        stored = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        benchmark.create_shown_description(client, stored["id"], 0, scenario)
        twin_id = benchmark.find_scenario(
            client, stored["id"], "Plain tiny scenario-shown"
        )
        hidden_seen, hidden_world, hidden_result = played_and_seen(client, scenario_id)
        shown_seen, shown_world, shown_result = played_and_seen(client, twin_id)

    hidden_description = hidden_seen[0]["description"]
    shown_description = shown_seen[0]["description"]
    shown_board = shown_description["manifest"]["lines"]["line-1"]["items"]["board"]
    assert shown_board["yield"]["min"] == Decimal("0.8000")
    assert without_yields(shown_description["manifest"]) == without_yields(
        hidden_description["manifest"]
    )
    assert shown_description["scenario"]["hidden"] == []
    assert hidden_description["scenario"]["hidden"] == ["lines.items.yield"]
    assert (
        shown_description
        | {
            "manifest": hidden_description["manifest"],
            "scenario": hidden_description["scenario"],
        }
        == hidden_description
    )
    assert [step["observation"] for step in shown_seen] == [
        step["observation"] for step in hidden_seen
    ]
    assert len(shown_seen) == 3
    assert shown_world == hidden_world
    assert shown_result["profit"] == hidden_result["profit"]
