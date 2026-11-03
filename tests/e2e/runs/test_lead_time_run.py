from decimal import Decimal
from typing import Any

from factories import (
    accepted_decisions_of_periods,
    api_client,
    assert_run_balances,
    get,
    item_balances,
    produce,
    run_to_the_end,
    ship,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 12
DROP_START = 5
DROP_DURATION = 3
START_STOCK = {"chip": Decimal(0), "board": Decimal(150), "monitor": Decimal(10)}
RECIPES = {"monitor": {"board": Decimal(2)}}


# The decisions of a period: ship its order and make 5 monitors.
def decisions_of(period: int) -> list[dict[str, Any]]:
    return [ship(f"order-{period}-1", "4"), produce("monitor", "5")]


def test_a_run_with_production_over_two_periods_and_a_yield_drop_balances():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"]["items"]["monitor"].update(
        lead_time=2, **{"yield": "0.9500"}
    )
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["start"]["stock"] = {
        "main": {item: str(quantity) for item, quantity in START_STOCK.items()}
    }
    scenario["disruptions"] = [
        {
            "kind": "yield_drop",
            "target": ["line-1"],
            "start": DROP_START,
            "duration": DROP_DURATION,
            "strength": "0.5000",
        }
    ]
    decisions = {period: decisions_of(period) for period in range(1, HORIZON + 1)}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    assert len(accepted_decisions_of_periods(periods, "ship")) == HORIZON
    into, out = item_balances(periods, RECIPES, START_STOCK)
    assert into == out

    scrap = [
        period["steps"][-1]["measures"]["lines"]["line-1"]["units_scrap"]
        for period in periods["periods"]
    ]
    dropped = range(DROP_START + 1, DROP_START + DROP_DURATION + 1)
    for period, value in enumerate(scrap, start=1):
        if period == 1:
            assert value == 0
        elif period in dropped:
            assert value == Decimal("2.625")
        else:
            assert value == Decimal("0.25")

    assert_run_balances(periods, result)
