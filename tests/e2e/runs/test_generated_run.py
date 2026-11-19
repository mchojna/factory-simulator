import pytest
from factories import (
    api_client,
    assert_run_balances,
    get,
    post,
    run_to_the_end,
)

COUNTS = {
    "materials": 10,
    "components": 8,
    "products": 4,
    "suppliers": 3,
    "customers": 5,
    "lines": 3,
}


@pytest.mark.slow
def test_a_generated_manifest_runs_52_periods_and_keeps_its_profit_formula():
    with api_client() as client:
        status, manifest = post(
            client, "/manifests/generated", {"counts": COUNTS, "seed": 7}
        )
        path = f"/manifests/{manifest['id']}/scenarios"
        _, scenario = post(client, path, {"horizon": 52})
        _, run = post(client, "/runs", {"scenario_id": scenario["id"], "seed": 0})
        finished = run_to_the_end(client, run)
        _, result = get(client, f"/runs/{run['id']}/result")
        _, periods = get(client, f"/runs/{run['id']}/periods")

    assert status == 201
    assert (finished["period"], finished["finished"]) == (52, True)
    assert_run_balances(periods, result)
