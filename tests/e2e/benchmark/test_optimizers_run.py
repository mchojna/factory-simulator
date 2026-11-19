from decimal import Decimal
from functools import partial
from typing import Any

import pytest
from factories import (
    benchmark_client,
    example_bodies,
    play_no_decisions,
    records,
    start_reference,
)

from factory_simulator.api.record.models.run import Run
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.optimizers.aligned import aligned_optimizer
from factory_simulator.benchmark.optimizers.buffered_rolling import (
    buffered_rolling_optimizer,
)
from factory_simulator.benchmark.optimizers.full_horizon import full_horizon_optimizer
from factory_simulator.benchmark.optimizers.informed import informed_optimizer
from factory_simulator.benchmark.optimizers.myopic import myopic_optimizer
from factory_simulator.benchmark.optimizers.rolling import rolling_optimizer
from factory_simulator.benchmark.program.decisions import Optimizer


@pytest.mark.slow
def test_every_optimizer_plays_8_periods_of_steady_market_on_the_example():
    manifest, scenario = example_bodies("steady-market")
    scenario["horizon"] = 8
    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        nothing, nothing_result = play_no_decisions(client, scenario_id, 0)
        run, reference = start_reference(client, scenario_id, 0, nothing["id"])
        results = [nothing_result, benchmark.play_run(client, run, reference)]
        optimizers = [reference]
        for make_optimizer in (
            full_horizon_optimizer,
            rolling_optimizer,
            buffered_rolling_optimizer,
            aligned_optimizer,
            myopic_optimizer,
        ):
            run = benchmark.start_run(client, scenario_id, 0)
            check = partial(benchmark.create_check, client, run["id"])
            optimizer = make_optimizer(check)
            results.append(benchmark.play_run(client, run, optimizer))
            optimizers.append(optimizer)
        runs = records(client, Run)

    assert [result["periods"] for result in results] == [8] * 7
    assert [
        result["measures"]["total"]["decisions_rejected"] for result in results[1:]
    ] == [0] * 6
    # Every optimizer submits decisions that the run accepts and earns more than no
    # decisions, which loses every order of the 8 periods.
    assert all(
        result["measures"]["total"]["decisions_accepted"] > 0 for result in results[1:]
    )
    assert all(result["profit"] > nothing_result["profit"] for result in results[1:])
    assert [len(optimizer.solves) for optimizer in optimizers] == [8] * 6
    assert len(runs) == 7


@pytest.mark.slow
def test_the_informed_optimizer_plays_8_periods_of_hidden_groups_at_both_factors():
    manifest, scenario = example_bodies("hidden-groups")
    scenario["horizon"] = 8
    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        results: list[dict[str, Any]] = []
        optimizers: list[Optimizer] = []
        for factor in (Decimal("1.01"), Decimal("1.2")):
            shown = benchmark.create_shown_description(
                client, stored_manifest["id"], 0, scenario
            )
            run = benchmark.start_run(client, scenario_id, 0)
            check = partial(benchmark.create_check, client, run["id"])
            optimizer = informed_optimizer(check, factor, shown)
            results.append(benchmark.play_run(client, run, optimizer))
            optimizers.append(optimizer)

    assert [result["periods"] for result in results] == [8, 8]
    assert [
        result["measures"]["total"]["decisions_rejected"] for result in results
    ] == [0, 0]
    assert all(
        result["measures"]["total"]["decisions_accepted"] > 0 for result in results
    )
    assert [len(optimizer.solves) for optimizer in optimizers] == [8, 8]
