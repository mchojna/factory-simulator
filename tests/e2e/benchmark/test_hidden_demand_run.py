from decimal import Decimal
from functools import partial

import pytest
from factories import benchmark_client, intermittent_demand_bodies

from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.client import JsonObject
from factory_simulator.benchmark.models.inputs import PlanningInput
from factory_simulator.benchmark.optimizers.rolling import rolling_optimizer
from factory_simulator.benchmark.program.expected_source import (
    add_demand_samples,
    expected_world,
)


# The rolling optimizer plays 12 periods of the hidden uniform demand from 0 to 10 at
# the factor 0.0001 to period 10 and 1 after. Seed 0 orders 0.001 in periods 1, 2, 4
# and 7 and nothing in the six other periods to 10: the samples 10, 10, 0, 10, 0, 0,
# 10, 0, 0, 0 after the factor is divided out, a mean of 4. The harness reads the
# description and the observations only, so it learns one sample a period, and the
# window of period 10 expects 4 monitors in period 11.
@pytest.mark.slow
def test_the_rolling_optimizer_learns_one_demand_sample_from_every_period():
    manifest, scenario = intermittent_demand_bodies()
    scenario["horizon"] = 12
    demand_samples: dict[str, dict[int, Decimal]] = {}
    counts: list[int] = []
    next_quantities: list[list[Decimal]] = []
    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        run = benchmark.start_run(client, scenario_id, 0)
        optimizer = rolling_optimizer(
            partial(benchmark.create_check, client, run["id"])
        )
        planning_source = optimizer.planning_source

        def recording_source(
            description: JsonObject, observation: JsonObject
        ) -> PlanningInput:
            world = expected_world(observation, description)
            add_demand_samples(demand_samples, observation, description, world)
            counts.append(len(demand_samples["distributor/monitor"]))
            planning = planning_source(description, observation)
            next_quantities.append(
                [
                    order.open_quantity
                    for order in planning.customer_orders
                    if order.arrival == observation["period"] + 1
                ]
            )
            return planning

        optimizer.planning_source = recording_source
        result = benchmark.play_run(client, run, optimizer)

    samples = demand_samples["distributor/monitor"]
    assert counts == list(range(1, 13))
    assert [samples[period] for period in range(1, 11)] == [
        Decimal(10) if period in (1, 2, 4, 7) else Decimal(0) for period in range(1, 11)
    ]
    assert next_quantities[9] == [Decimal("4.000")]
    assert optimizer.fitted == []
    assert result["measures"]["total"]["decisions_rejected"] == 0
