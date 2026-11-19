import copy
from decimal import ROUND_CEILING, Decimal
from typing import Any

from factories import (
    accepted_decisions_of_periods,
    api_client,
    assert_run_balances,
    buy,
    events_of_periods,
    get,
    produce,
    run_to_the_end,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 10
OUTAGE = range(5, 8)
RECIPES = {
    ("board", "standard"): {"chip": Decimal(2)},
    ("board", "alternative"): {"chip-b": Decimal(2)},
    ("monitor", "standard"): {"board": Decimal(2)},
}
START_STOCK = {
    "chip": Decimal(0),
    "chip-b": Decimal(60),
    "board": Decimal(10),
    "monitor": Decimal(5),
}


def decisions_of(period: int) -> list[dict[str, Any]]:
    decisions = [buy("20")]
    recipe = "alternative" if period in OUTAGE else "standard"
    if period >= 3:
        decisions.append(produce("board", "10", recipe=recipe))
    return decisions


def test_a_run_switches_to_the_alternative_recipe_during_an_outage_and_balances():
    manifest = tiny_manifest()
    manifest["materials"]["chip-b"] = copy.deepcopy(manifest["materials"]["chip"])
    entry = copy.deepcopy(manifest["suppliers"]["chip-maker"]["catalogue"]["chip"])
    manifest["suppliers"]["chip-b-maker"] = {"catalogue": {"chip-b": entry}}
    board = manifest["components"]["board"]
    board["recipes"]["alternative"] = {"chip-b": "2.000"}
    board["default_recipe"] = "standard"
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["start"]["stock"] = {
        "main": {item: str(quantity) for item, quantity in START_STOCK.items()}
    }
    scenario["disruptions"] = [
        {
            "kind": "supplier_outage",
            "target": ["chip-maker"],
            "start": OUTAGE.start,
            "duration": len(OUTAGE),
            "strength": "1.0000",
        }
    ]
    decisions = {period: decisions_of(period) for period in range(1, HORIZON + 1)}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")
    end = periods["periods"][-1]["steps"][-1]["state"]

    produced = accepted_decisions_of_periods(periods, "produce")
    assert [decision["recipe"] for decision in produced] == [
        "standard",
        "standard",
        "alternative",
        "alternative",
        "alternative",
        "standard",
        "standard",
        "standard",
    ]
    into = dict(START_STOCK)
    out = dict(end["stock"]["main"])
    for event in events_of_periods(periods, "delivery"):
        into["chip"] += event["accepted"]
    for event in events_of_periods(periods, "production_finished"):
        into[event["item"]] += event["good"]
    for decision in produced:
        for input_id, per_unit in RECIPES[decision["item"], decision["recipe"]].items():
            used = decision["quantity"] * per_unit
            out[input_id] += used.quantize(Decimal("0.001"), rounding=ROUND_CEILING)
    assert into == out

    assert_run_balances(periods, result)
