from factories import (
    api_client,
    get,
    post,
    run_to_the_end,
    start_run,
    tiny_manifest,
    tiny_scenario,
)


def test_a_season_shapes_the_quantities_of_new_orders():
    scenario = tiny_scenario()
    scenario["horizon"] = 6
    scenario["demand_shapes"] = [
        {
            "kind": "season",
            "target": "all",
            "factors": ["0.5000", "2.0000"],
            "period_length": 2,
        }
    ]
    with api_client() as client:
        run = start_run(client, scenario=scenario)
        run_to_the_end(client, run)
        _, periods = get(client, f"/runs/{run['id']}/periods")

    ordered = [
        event["quantity"]
        for period in periods["periods"]
        for step in period["steps"]
        for event in step.get("events", [])
        if event["kind"] == "customer_order"
    ]
    assert ordered == [2, 2, 8, 8, 2, 2]


def test_a_season_factor_with_5_places_is_refused_at_its_path():
    scenario = tiny_scenario()
    scenario["demand_shapes"] = [
        {"kind": "season", "target": "all", "factors": ["0.80001"], "period_length": 1}
    ]
    with api_client() as client:
        _, manifest = post(client, "/manifests", tiny_manifest())
        status, answer = post(
            client, f"/manifests/{manifest['id']}/scenarios", scenario
        )

    assert status == 422
    assert answer["detail"].startswith("demand_shapes.0.factors.0: ")
