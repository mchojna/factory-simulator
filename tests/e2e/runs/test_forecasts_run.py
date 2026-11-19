from decimal import Decimal
from typing import Any

import pytest
from factories import (
    api_client,
    assert_run_balances,
    buy,
    get,
    produce,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 52
CUSTOMER_PRODUCT = "distributor/monitor"
SEASON = [Decimal("0.8000"), Decimal("1.2000")]
DECISIONS: dict[int, list[dict[str, Any]]] = {
    1: [buy("40")],
    2: [produce("board", "20")],
    3: [produce("monitor", "10")],
    20: [buy("40")],
}


def forecast_scenario() -> dict[str, Any]:
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["demand_shapes"] = [
        {
            "kind": "season",
            "target": "all",
            "factors": [str(factor) for factor in SEASON],
            "period_length": 13,
        }
    ]
    scenario["disruptions"] = [
        {
            "kind": "demand_shock",
            "target": ["monitor"],
            "start": 20,
            "duration": 4,
            "factor": "0.5000",
            "notice": 2,
        }
    ]
    scenario["forecasts"] = [
        {
            "target": "all",
            "periods_ahead": 4,
            "noise": "0.1000",
            "noise_growth": "0.0500",
        }
    ]
    return scenario


def forecast_from_world(world: dict[str, Any], made: int, ahead: int) -> Decimal:
    period = made + ahead
    demand = world["demand"][CUSTOMER_PRODUCT][period - 1]
    demand *= SEASON[((period - 1) // 13) % 2]
    for disruption in world["disruptions"]:
        start, duration = disruption["start"], disruption["duration"]
        if disruption["visible"] <= made and start <= period < start + duration:
            demand *= disruption["factor"]
    error = world["forecast_errors"][CUSTOMER_PRODUCT][made - 1][ahead - 1]
    quantity = demand.quantize(Decimal("0.001")) * (1 + error)
    return max(quantity.quantize(Decimal("0.001")), Decimal(0))


@pytest.mark.slow
def test_every_forecast_of_a_long_run_is_computed_again_from_the_world():
    manifest = tiny_manifest()
    customer_product = manifest["customers"]["distributor"]["products"]["monitor"]
    customer_product["demand"] = {"min": "30.000", "max": "50.000"}
    shown: list[list[dict[str, Any]]] = []
    with api_client() as client:
        run = start_run(client, manifest, forecast_scenario(), seed=3)
        _, observation = get(client, f"/runs/{run['id']}/observation")
        for period in range(1, HORIZON + 1):
            shown.append(observation["forecasts"][CUSTOMER_PRODUCT])
            status, observation = submit(
                client, run["id"], period, DECISIONS.get(period, [])
            )
            assert status == 200, observation
        _, world = get(client, f"/runs/{run['id']}/world")
        _, result = get(client, f"/runs/{run['id']}/result")
        _, periods = get(client, f"/runs/{run['id']}/periods")

    assert observation["finished"]
    assert shown[-1] == []
    for made, forecasts in enumerate(shown, start=1):
        assert [forecast["period"] for forecast in forecasts] == list(
            range(made + 1, min(made + 4, HORIZON) + 1)
        )
        for forecast in forecasts:
            ahead = forecast["period"] - made
            assert forecast["quantity"] == forecast_from_world(world, made, ahead)
    unshocked = world | {"disruptions": []}
    assert shown[16][2]["quantity"] == forecast_from_world(unshocked, 17, 3)
    assert shown[17][1]["quantity"] < forecast_from_world(unshocked, 18, 2)
    assert_run_balances(periods, result)
