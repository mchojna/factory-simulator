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


@pytest.mark.slow
def test_a_run_of_the_example_with_a_shared_product_keeps_its_profit_formula():
    manifest = cast(
        dict[str, Any], read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    )
    manifest["products"]["smart-monitor"]["common_share"] = "0.7000"
    with api_client() as client:
        _, stored_manifest = post(client, "/manifests", manifest)
        _, stored_scenario = post(
            client,
            f"/manifests/{stored_manifest['id']}/scenarios",
            example_scenario(),
        )
        _, run = post(
            client, "/runs", {"scenario_id": stored_scenario["id"], "seed": 2}
        )
        finished = run_to_the_end(client, run)
        _, result = get(client, f"/runs/{run['id']}/result")
        _, periods = get(client, f"/runs/{run['id']}/periods")

    assert (finished["period"], finished["finished"]) == (52, True)
    assert_run_balances(periods, result)
