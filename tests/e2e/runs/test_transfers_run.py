from typing import Any

from factories import (
    api_client,
    assert_run_balances,
    events_of_periods,
    get,
    produce,
    run_to_the_end,
    ship,
    start_run,
    tiny_manifest,
    tiny_scenario,
    transfer,
)

HORIZON = 12


def decisions_of(period: int) -> list[dict[str, Any]]:
    decisions = [produce("monitor", "4"), transfer("monitor", "4", source="plant")]
    if period > 1:
        decisions.insert(0, ship(f"order-{period}-1", "4", warehouse="centre"))
    return decisions


def test_a_plant_feeds_a_centre_one_period_away_with_balanced_routes_and_items():
    manifest = tiny_manifest()
    manifest["warehouses"] = {
        "plant": {"capacity": "100.000"},
        "centre": {"capacity": "100.000", "accepts": ["products"]},
    }
    manifest["lines"]["line-1"]["warehouse"] = "plant"
    manifest["routes"] = {"plant": {"centre": {"cost": "0.2000", "lead_time": 1}}}
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["start"]["stock"] = {
        "plant": {"chip": "100", "board": "100", "monitor": "5"}
    }
    decisions = {period: decisions_of(period) for period in range(1, HORIZON + 1)}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    arrived = sum(
        event["quantity"] for event in events_of_periods(periods, "transfer_arrived")
    )
    last_state = periods["periods"][-1]["steps"][-1]["state"]
    on_the_way = sum(transfer["quantity"] for transfer in last_state["transfers"])
    measures = result["measures"]
    sent = measures["routes"]["plant/centre"]["units_transferred"]
    assert sent == arrived + on_the_way
    end = measures["warehouses"]
    good = measures["lines"]["line-1/monitor"]["units_good"]
    assert 5 + good == (
        end["plant/monitor"]["stock"]
        + end["centre/monitor"]["stock"]
        + on_the_way
        + measures["total"]["units_shipped"]
    )
    assert_run_balances(periods, result)
