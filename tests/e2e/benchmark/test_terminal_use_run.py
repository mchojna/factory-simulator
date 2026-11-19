from decimal import Decimal
from functools import partial
from typing import Any

import pytest
from factories import benchmark_client, plain_tiny_manifest, plain_tiny_scenario

from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.client import JsonObject
from factory_simulator.benchmark.models.inputs import PlanningInput
from factory_simulator.benchmark.optimizers.buffered_rolling import (
    buffered_rolling_optimizer,
)
from factory_simulator.benchmark.program.decisions import Optimizer


# A run of 12 periods of the plain tiny factory with the demand shapes given, played by
# the buffered rolling optimizer, with the expected use of monitors at the end of the
# window of each period, None once the window reaches the horizon.
def played_with_monitor_uses(
    shapes: list[dict[str, Any]],
) -> tuple[dict[str, Any], Optimizer, list[Decimal | None]]:
    scenario = plain_tiny_scenario() | {"horizon": 12, "demand_shapes": shapes}
    uses: list[Decimal | None] = []
    with benchmark_client() as client:
        stored_manifest = benchmark.send(
            client, "POST", "/manifests", plain_tiny_manifest()
        )
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        run = benchmark.start_run(client, scenario_id, 0)
        optimizer = buffered_rolling_optimizer(
            partial(benchmark.create_check, client, run["id"])
        )
        planning_source = optimizer.planning_source

        def recording_source(
            description: JsonObject, observation: JsonObject
        ) -> PlanningInput:
            planning = planning_source(description, observation)
            terminal = planning.terminal_values.get("monitor")
            uses.append(None if terminal is None else terminal.expected_use)
            return planning

        optimizer.planning_source = recording_source
        result = benchmark.play_run(client, run, optimizer)
    return result, optimizer, uses


# The window of period t ends in t + 4 and its expected use counts periods t + 5 to
# t + 7, cut at the horizon of 12. With 4 monitors a period that is 12 up to period 5,
# then 8 and 4; with demand withdrawn from period 8 it is 4 + 4 in period 1, 4 in
# period 2 and 0 from period 3. From period 8 the window reaches the horizon.
@pytest.mark.slow
def test_the_expected_use_of_monitors_falls_to_0_before_a_known_withdrawal():
    withdrawal = {"kind": "step", "target": "all", "period": 8, "factor": "0.0000"}

    steady, steady_optimizer, steady_uses = played_with_monitor_uses([])
    withdrawn, withdrawn_optimizer, withdrawn_uses = played_with_monitor_uses(
        [withdrawal]
    )

    assert steady_uses == [*[Decimal(12)] * 5, Decimal(8), Decimal(4), *[None] * 5]
    assert withdrawn_uses == [Decimal(8), Decimal(4), *[Decimal(0)] * 5, *[None] * 5]
    assert [steady_optimizer.fitted, withdrawn_optimizer.fitted] == [[], []]
    assert [
        result["measures"]["total"]["decisions_rejected"]
        for result in (steady, withdrawn)
    ] == [0, 0]
