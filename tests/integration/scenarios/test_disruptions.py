from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    get,
    post,
    run_to_the_end,
    start_run,
    tiny_manifest,
    tiny_scenario,
)


def scenario_with(*disruptions: dict[str, Any]) -> dict[str, Any]:
    scenario = tiny_scenario()
    scenario["disruptions"] = list(disruptions)
    return scenario


def test_the_world_lists_the_written_disruptions_in_scenario_order():
    scenario = scenario_with(
        {"kind": "line_breakdown", "target": ["line-1"], "start": 3, "loss": "0.3"},
        {
            "kind": "transport_delay",
            "target": "all",
            "start": 2,
            "duration": 2,
            "delay": 1,
        },
    )
    with api_client() as client:
        run = start_run(client, scenario=scenario)
        run_to_the_end(client, run)
        _, world = get(client, f"/runs/{run['id']}/world")

    # The list keeps its order; the numbers follow the period each is visible.
    assert world["disruptions"] == [
        {
            "id": "disruption-2",
            "kind": "line_breakdown",
            "target": ["line-1"],
            "start": 3,
            "loss": Decimal("0.3"),
            "visible": 3,
        },
        {
            "id": "disruption-1",
            "kind": "transport_delay",
            "target": ["chip-maker"],
            "start": 2,
            "duration": 2,
            "delay": 1,
            "visible": 2,
        },
    ]


def test_a_demand_shock_doubles_new_orders_in_its_window_only():
    shock = {
        "kind": "demand_shock",
        "target": ["monitor"],
        "start": 2,
        "duration": 2,
        "factor": "2.0000",
    }
    with api_client() as client:
        run = start_run(client, scenario=scenario_with(shock))
        run_to_the_end(client, run)
        _, periods = get(client, f"/runs/{run['id']}/periods")

    ordered = [
        event["quantity"]
        for period in periods["periods"]
        for step in period["steps"]
        for event in step.get("events", [])
        if event["kind"] == "customer_order"
    ]
    assert ordered == [4, 8, 8, 4, 4]


def test_a_strength_with_5_places_is_refused_at_its_path():
    outage = {
        "kind": "supplier_outage",
        "target": ["chip-maker"],
        "start": 1,
        "duration": 1,
        "strength": "0.80001",
    }
    with api_client() as client:
        _, manifest = post(client, "/manifests", tiny_manifest())
        status, answer = post(
            client, f"/manifests/{manifest['id']}/scenarios", scenario_with(outage)
        )

    assert status == 422
    assert answer["detail"].startswith("disruptions.0.strength: ")
