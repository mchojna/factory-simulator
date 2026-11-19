from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    assert_run_balances,
    get,
    produce,
    run_to_the_end,
    ship,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 10


# The decisions of a period: ship its order and make the next one, 4 monitors of it in
# overtime.
def decisions_of(period: int) -> list[dict[str, Any]]:
    return [
        ship(f"order-{period}-1", "24"),
        produce("monitor", "20"),
        produce("monitor", "4", overtime=True),
    ]


def test_a_run_with_demand_above_regular_capacity_ships_every_order_in_overtime():
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "24.000"
    manifest["lines"]["line-1"].update(
        wear_per_period="0.0000",
        wear_per_hour="0.0000",
        overtime_hours="4.000",
        overtime_cost="45.0000",
    )
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["start"]["stock"]["main"].update(board="600", monitor="24")
    decisions = {period: decisions_of(period) for period in range(1, HORIZON + 1)}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    total = result["measures"]["total"]
    terms = result["terms"]
    assert total["units_shipped"] == HORIZON * 24
    assert total["units_lost"] == 0
    assert terms["overtime_cost"] == HORIZON * 2 * Decimal(45)
    assert_run_balances(periods, result)
