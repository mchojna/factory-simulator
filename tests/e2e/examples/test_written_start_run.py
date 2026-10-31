from typing import Any, cast

import pytest
from factories import (
    api_client,
    assert_run_balances,
    example_scenario,
    get,
    post,
    run_to_the_end,
)

from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.services.examples import EXAMPLES

BUYER_SHOCK = {
    "name": "buyer-shock",
    "kind": "demand_shock",
    "target": {"segment": "new-devices"},
    "start": 25,
    "duration": 4,
    "factor": "1.8000",
}


@pytest.mark.slow
@pytest.mark.parametrize("seed", [0, 1])
def test_a_run_of_the_example_has_one_shock_in_period_25_on_a_new_device(seed: int):
    manifest = cast(
        dict[str, Any], read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    )
    scenario = example_scenario()
    scenario["random_disruptions"] = [BUYER_SHOCK]
    with api_client() as client:
        _, stored_manifest = post(client, "/manifests", manifest)
        _, stored_scenario = post(
            client, f"/manifests/{stored_manifest['id']}/scenarios", scenario
        )
        _, run = post(
            client, "/runs", {"scenario_id": stored_scenario["id"], "seed": seed}
        )
        finished = run_to_the_end(client, run)
        _, result = get(client, f"/runs/{run['id']}/result")
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, world = get(client, f"/runs/{run['id']}/world")

    assert (finished["period"], finished["finished"]) == (52, True)
    shocks = [
        disruption
        for disruption in world["disruptions"]
        if disruption["id"].startswith("buyer-shock/")
    ]
    assert len(shocks) == 1
    assert shocks[0]["start"] == 25
    new_devices = {
        product_id
        for product_id, product in manifest["products"].items()
        if "new-devices" in product.get("groups", [])
    }
    assert shocks[0]["target"][0] in new_devices
    assert_run_balances(periods, result)
