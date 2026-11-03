import copy
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import Any

import pytest
from factories import (
    benchmark_client,
    example_count,
    linear_factories,
    plain_tiny_manifest,
    plain_tiny_scenario,
    seeds,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given, settings

from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.optimizers.full_horizon import full_horizon_optimizer
from stress.checks import (
    Play,
    replay_violations,
    violations_of_play,
    violations_of_run,
)


# A run of a factory played by the full-horizon optimizer, its description, result and
# periods.
def played_by_the_full_horizon_optimizer(
    manifest: dict[str, Any], scenario: dict[str, Any], seed: int = 0
) -> tuple[str, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        run = benchmark.start_run(client, scenario_id, seed)
        check = partial(benchmark.create_check, client, run["id"])
        result = benchmark.play_run(client, run, full_horizon_optimizer(check))
        periods = benchmark.read_periods(client, run["id"])
    return run["id"], run["description"], result, periods


def test_a_run_that_ships_balances_and_each_broken_balance_is_named():
    manifest = tiny_manifest()
    distributor = manifest["customers"]["distributor"]
    distributor["payment_terms"] = 2
    distributor["products"]["monitor"]["patience"] = 2
    manifest["warehouses"]["store"] = {"capacity": "50.000", "accepts": ["products"]}
    manifest["lines"]["line-1"]["warehouse"] = "main"
    manifest["routes"] = {"main": {"store": {"cost": "0.1000", "lead_time": 1}}}
    scenario = tiny_scenario()
    scenario["horizon"] = 6
    scenario["start"]["stock"]["store"] = {"monitor": "3"}
    scenario["start"]["customer_orders"] = [
        {"customer": "distributor", "product": "monitor", "quantity": "7.000", "due": 1}
    ]
    _, description, result, periods = played_by_the_full_horizon_optimizer(
        manifest, scenario
    )

    def violations_with(
        change_result: Callable[[dict[str, Any]], None] | None = None,
        change_periods: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> list[str]:
        changed_result = copy.deepcopy(result)
        changed_periods = copy.deepcopy(periods)
        if change_result is not None:
            change_result(changed_result)
        if change_periods is not None:
            change_periods(changed_periods)
        return violations_of_run(
            "full_horizon_optimizer", description, changed_result, changed_periods
        )

    def add_to_revenue(changed: dict[str, Any]) -> None:
        changed["terms"]["revenue"] += 1

    def add_to_the_last_profit_so_far(changed: list[dict[str, Any]]) -> None:
        closing = next(
            step for step in changed[-1]["steps"] if step["step"] == "close_period"
        )
        closing["measures"]["total"]["profit_so_far"] += 1

    def add_to_the_first_ledger_amount(changed: list[dict[str, Any]]) -> None:
        changed[0]["ledger"][0]["amount"] += 1

    def add_to_units_shipped(changed: dict[str, Any]) -> None:
        changed["measures"]["total"]["units_shipped"] += 1

    def reject_a_decision(changed: dict[str, Any]) -> None:
        changed["measures"]["total"]["decisions_rejected"] = 1

    def end_after_period_5(changed: dict[str, Any]) -> None:
        changed["periods"] = 5

    def add_a_chip_to_the_last_stock_of_main(changed: list[dict[str, Any]]) -> None:
        closing = next(
            step for step in changed[-1]["steps"] if step["step"] == "close_period"
        )
        closing["state"]["stock"]["main"]["chip"] += 1

    def move_a_chip_of_main_to_the_way(changed: list[dict[str, Any]]) -> None:
        closing = next(
            step for step in changed[-1]["steps"] if step["step"] == "close_period"
        )
        closing["state"]["stock"]["main"]["chip"] -= 1
        closing["state"]["transfers"].append({"item": "chip", "quantity": 1})

    def take_a_chip_from_the_units_used_in_main(changed: dict[str, Any]) -> None:
        changed["measures"]["warehouses"]["main/chip"]["units_used"] -= 1

    profit = result["profit"]
    salvage = result["terms"]["salvage"]
    change = result["cash_at_end"] - result["cash_at_start"]
    totals = result["measures"]["total"]
    ordered, shipped, lost = (
        totals["units_ordered"],
        totals["units_shipped"],
        totals["units_lost"],
    )
    assert shipped > 0
    assert ordered == shipped + lost
    assert violations_with() == []
    assert violations_with(change_result=add_to_revenue) == [
        f"profit {profit} is not revenue less costs plus interest earned and salvage "
        f"{profit + 1}"
    ]
    assert violations_with(change_periods=add_to_the_last_profit_so_far) == [
        f"profit so far {profit - salvage + 1} plus salvage {salvage} is not the "
        f"profit {profit}"
    ]
    assert violations_with(change_periods=add_to_the_first_ledger_amount) == [
        f"ledger sums to {change + 1}, cash changed by {change}"
    ]
    assert violations_with(change_result=add_to_units_shipped) == [
        f"customer units do not balance: ordered {ordered}, shipped {shipped + 1}, "
        f"lost {lost}, open 0"
    ]
    assert violations_with(change_result=reject_a_decision) == ["decisions rejected: 1"]
    assert violations_with(change_result=end_after_period_5) == [
        "ended after period 5 of 6"
    ]
    added = violations_with(change_periods=add_a_chip_to_the_last_stock_of_main)
    taken = violations_with(change_result=take_a_chip_from_the_units_used_in_main)
    assert violations_with(change_periods=move_a_chip_of_main_to_the_way) == []
    assert len(added) == 1
    assert added[0].startswith("units of chip do not balance")
    assert len(taken) == 1
    assert taken[0].startswith("units of chip do not balance")


@pytest.mark.property
@settings(max_examples=example_count(25))
@given(linear_factories().filter(lambda factory: factory[1]["horizon"] <= 6), seeds)
def test_every_run_of_the_full_horizon_optimizer_on_a_small_factory_has_no_violation(
    factory: tuple[dict[str, Any], dict[str, Any]], seed: int
):
    _, description, result, periods = played_by_the_full_horizon_optimizer(
        *factory, seed
    )

    assert (
        violations_of_run("full_horizon_optimizer", description, result, periods) == []
    )


def test_two_plays_of_one_world_are_equal_unless_a_solve_stopped_at_the_time_limit():
    played = [
        played_by_the_full_horizon_optimizer(
            plain_tiny_manifest(), plain_tiny_scenario()
        )
        for _ in range(2)
    ]
    description = played[0][1]
    plays = [
        Play(
            run_id=run_id,
            result=result,
            periods=periods,
            solves_at_time_limit=0,
        )
        for run_id, _, result, periods in played
    ]
    first, second = plays
    changed = copy.deepcopy(second.result)
    changed["profit"] += 1
    differing = replace(second, result=changed)

    assert first.run_id != second.run_id
    assert replay_violations(first, second) == []
    assert replay_violations(first, differing) == [
        f"second play differs from the first, run {second.run_id}"
    ]
    assert replay_violations(first, replace(differing, solves_at_time_limit=1)) == []
    agent = "full_horizon_optimizer"
    profit, salvage = second.result["profit"], second.result["terms"]["salvage"]
    # A profit 1 above the formula breaks two checks of the run.
    broken = [
        f"profit {profit + 1} is not revenue less costs plus interest earned and "
        f"salvage {profit}",
        f"profit so far {profit - salvage} plus salvage {salvage} is not the profit "
        f"{profit + 1}",
    ]
    assert violations_of_play(agent, description, second, first) == []
    assert violations_of_play(agent, description, differing, None) == broken
    assert violations_of_play(agent, description, differing, first) == [
        *broken,
        f"second play differs from the first, run {second.run_id}",
    ]
