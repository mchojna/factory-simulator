import pytest
from factories import (
    api_client,
    assert_run_balances,
    example_bodies,
    example_scenario,
    get,
    post,
    rows_of_run,
    run_to_the_end,
)

APAC_OUTAGE = {
    "name": "apac-outage",
    "kind": "supplier_outage",
    "target": {"region": "apac"},
    "chance": "0.0500",
    "duration": 2,
    "strength": "0.6000",
    "raises": {"rule": "apac-transport", "factor": "5.0000", "periods": 4},
}
APAC_TRANSPORT = {
    "name": "apac-transport",
    "kind": "transport_delay",
    "target": {"region": "apac"},
    "chance": "0.0400",
    "duration": 1,
    "delay": 1,
}


@pytest.mark.slow
@pytest.mark.parametrize("seed", [0, 1])
def test_a_run_of_the_example_with_a_cascade_repeats_and_keeps_its_profit_formula(
    seed: int,
):
    manifest, _ = example_bodies("steady-market")
    scenario = example_scenario()
    scenario["random_disruptions"] = [APAC_OUTAGE, APAC_TRANSPORT]
    with api_client() as client:
        _, stored_manifest = post(client, "/manifests", manifest)
        _, stored_scenario = post(
            client, f"/manifests/{stored_manifest['id']}/scenarios", scenario
        )
        start = {"scenario_id": stored_scenario["id"], "seed": seed}
        runs = [post(client, "/runs", start)[1] for _ in range(2)]
        finished = [run_to_the_end(client, run) for run in runs]
        _, result = get(client, f"/runs/{runs[0]['id']}/result")
        _, periods = get(client, f"/runs/{runs[0]['id']}/periods")
        _, world = get(client, f"/runs/{runs[0]['id']}/world")
        rows = [rows_of_run(client, run["id"]) for run in runs]

    assert [(run["period"], run["finished"]) for run in finished] == [(52, True)] * 2
    assert world["disruptions"]
    assert rows[0] == rows[1]
    assert_run_balances(periods, result)
