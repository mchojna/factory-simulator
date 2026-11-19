from decimal import Decimal
from typing import Any

import pytest
from factories import (
    accepted_decisions_of_periods,
    api_client,
    assert_run_balances,
    buy,
    events_of_periods,
    get,
    item_balances,
    produce,
    repair,
    rows_of_run,
    run_to_the_end,
    ship,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 12
RECIPES = {"board": {"chip": Decimal(2)}, "monitor": {"board": Decimal(2)}}
START_STOCK = {"chip": Decimal(100), "board": Decimal(10), "monitor": Decimal(5)}
SALVAGE = {"chip": Decimal("0.1"), "board": Decimal("0.5"), "monitor": Decimal(2)}
Decisions = dict[int, list[dict[str, Any]]]
STEADY: Decisions = {
    period: [
        ship(f"order-{period}-1", "4"),
        produce("monitor", "4"),
        produce("board", "10"),
        buy("20"),
    ]
    for period in range(1, HORIZON + 1)
}
REPAIRED: Decisions = STEADY | {5: [*STEADY[5], repair("0.3000")]}
OUTAGE = {
    "kind": "supplier_outage",
    "target": ["chip-maker"],
    "start": 5,
    "duration": 3,
    "strength": "0.5000",
}
BREAKDOWN = {
    "kind": "line_breakdown",
    "target": ["line-1"],
    "start": 4,
    "loss": "0.6000",
}
SCENARIOS: dict[str, tuple[list[dict[str, Any]], Decisions]] = {
    "steady": ([], STEADY),
    "supplier_outage": ([OUTAGE], STEADY),
    "line_breakdown": ([BREAKDOWN], REPAIRED),
}


@pytest.mark.parametrize(
    ("disruptions", "decisions"), list(SCENARIOS.values()), ids=list(SCENARIOS)
)
def test_a_scenario_of_the_tiny_factory_balances_and_keeps_its_profit(
    disruptions: list[Any], decisions: Decisions
):
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["disruptions"] = disruptions
    with api_client() as client:
        runs = [start_run(client, tiny_manifest(), scenario, seed=11) for _ in range(2)]
        for run in runs:
            run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{runs[0]['id']}/periods")
        _, result = get(client, f"/runs/{runs[0]['id']}/result")
        rows = [rows_of_run(client, run["id"]) for run in runs]
    states = [period["steps"][-1]["state"] for period in periods["periods"]]

    assert_run_balances(periods, result)
    into, out = item_balances(periods, RECIPES, START_STOCK)
    assert into == out
    ordered = {
        event["reference"]: event["quantity"]
        for event in events_of_periods(periods, "customer_order")
    }
    settled = dict.fromkeys(ordered, Decimal(0))
    for decision in accepted_decisions_of_periods(periods, "ship"):
        settled[decision["order"]] += decision["quantity"]
    for event in events_of_periods(periods, "lost_sale"):
        settled[event["reference"]] += event["quantity"]
    for order in states[-1]["customer_orders"]:
        settled[order["id"]] += order["quantity"] - order["shipped"]
    assert settled == ordered
    bought = {
        order["id"]: order["quantity"]
        for state in states
        for order in state["supplier_orders"]
    }
    assert sorted(bought.values()) == sorted(
        decision["quantity"]
        for decision in accepted_decisions_of_periods(periods, "buy")
    )
    received = dict.fromkeys(bought, Decimal(0))
    for event in events_of_periods(periods, "delivery"):
        received[event["reference"]] += event["arrived"] + event["lost"]
    for order in states[-1]["supplier_orders"]:
        received[order["id"]] += order["open_quantity"]
    assert received == bought
    stock = states[-1]["stock"]["main"]
    salvage = sum((stock[item] * value for item, value in SALVAGE.items()), Decimal(0))
    assert result["terms"]["salvage"] == salvage
    assert rows[0] == rows[1]
