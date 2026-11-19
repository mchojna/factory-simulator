from typing import Any

from factories import (
    api_client,
    assert_run_balances,
    buy,
    get,
    rows_of_run,
    run_to_the_end,
    ship,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

from factory_simulator.api.record.models.run import Run

HORIZON = 8


def test_hiding_groups_writes_the_same_record_but_the_description():
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    decisions = {
        period: [ship(f"order-{period}-1", "4"), buy("10")]
        for period in range(1, HORIZON + 1)
    }
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = {
        "min": "3.000",
        "max": "6.000",
    }
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["punctuality"] = {
        "min": "0.5000",
        "max": "0.9000",
    }
    rows: list[dict[str, list[Any]]] = []
    with api_client() as client:
        for hidden in (
            [],
            ["customers.products.demand", "suppliers.catalogue.punctuality"],
        ):
            run = start_run(client, manifest, scenario | {"hidden": hidden}, seed=3)
            run_to_the_end(client, run, decisions)
            rows.append(rows_of_run(client, run["id"]))
            _, periods = get(client, f"/runs/{run['id']}/periods")
            _, result = get(client, f"/runs/{run['id']}/result")
            assert_run_balances(periods, result)

    plain, hidden_rows = rows
    for table in ("periods", "events", "outcomes", "ledger", "worlds", "results"):
        assert plain[table] == hidden_rows[table]
    measures = [
        [row for row in run_rows["measures"] if row["name"] != "observation_size"]
        for run_rows in rows
    ]
    assert measures[0] == measures[1]
    differing = {
        key
        for key in plain[Run.__tablename__][0]
        if plain[Run.__tablename__][0][key] != hidden_rows[Run.__tablename__][0][key]
    }
    assert differing == {"scenario_id", "description"}
