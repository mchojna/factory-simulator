from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    assert_run_balances,
    buy,
    get,
    run_to_the_end,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 10
BUYS = [buy("50"), buy("30", express=True)]
# An express unit costs the price 0.5000 plus the express cost 1.5000.
UNIT_PRICE = {False: Decimal("0.5000"), True: Decimal("2.0000")}
LEAD_TIME = {False: 3, True: 1}


# The delivery events of a run, each with the period it happened in.
def dated_deliveries(periods: dict[str, Any]) -> list[tuple[int, Any]]:
    return [
        (period["period"], event)
        for period in periods["periods"]
        for step in period["steps"]
        for event in step.get("events", [])
        if event["kind"] == "delivery"
    ]


def test_a_run_of_express_buys_and_backfills_under_an_outage_balances():
    manifest = tiny_manifest()
    manifest["cash"]["credit_limit"] = "100000.0000"
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"].update(
        lead_time=3,
        express_lead_time=1,
        express_cost="1.5000",
        completeness="0.9000",
        acceptance="0.9800",
        backfill_delay=3,
    )
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["disruptions"] = [
        {
            "kind": "supplier_outage",
            "target": ["chip-maker"],
            "start": 4,
            "duration": 2,
            "strength": "0.5000",
        }
    ]
    decisions = dict.fromkeys(range(1, HORIZON + 1), BUYS)
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")
    end = periods["periods"][-1]["steps"][-1]["state"]
    deliveries = dated_deliveries(periods)

    placed = {
        outcome["reference"]: (period["period"], outcome["decision"])
        for period in periods["periods"]
        for step in period["steps"]
        for outcome in step.get("outcomes", [])
        if outcome["accepted"]
    }
    assert len(placed) == 2 * HORIZON
    bought = {reference: buy["quantity"] for reference, (_, buy) in placed.items()}
    settled = dict.fromkeys(bought, Decimal(0))
    for _, event in deliveries:
        settled[event["reference"]] += event["arrived"] + event["lost"]
    for order in end["supplier_orders"]:
        settled[order["id"]] += order["open_quantity"]
    assert settled == bought

    first_delivery: dict[str, int] = {}
    for period, event in deliveries:
        first_delivery.setdefault(event["reference"], period)
    assert first_delivery == {
        reference: period + LEAD_TIME[buy["express"]]
        for reference, (period, buy) in placed.items()
        if period + LEAD_TIME[buy["express"]] <= HORIZON
    }

    backfilled = {event["reference"] for _, event in deliveries if event["backfill"]}
    waiting = {order["id"] for order in end["supplier_orders"]}
    assert backfilled
    assert waiting
    assert not backfilled & waiting
    unit_price = {
        reference: UNIT_PRICE[buy["express"]] for reference, (_, buy) in placed.items()
    }
    accepted = dict.fromkeys(bought, Decimal(0))
    for _, event in deliveries:
        accepted[event["reference"]] += event["accepted"]
        assert event["payment"] == event["accepted"] * unit_price[event["reference"]]
    paid = dict.fromkeys(bought, Decimal(0))
    for period in periods["periods"]:
        for row in period["ledger"]:
            if row["kind"] == "material_payment":
                paid[row["reference"]] -= row["amount"]
    backfills_open = {
        order["id"]
        for order in end["supplier_orders"]
        if order["open_quantity"] < order["quantity"]
    }
    assert backfills_open
    for reference in backfills_open:
        assert paid[reference] == accepted[reference] * unit_price[reference]
    payments = [
        row["amount"]
        for period in periods["periods"]
        for row in period["ledger"]
        if row["kind"] == "material_payment"
    ]
    assert -sum(payments, Decimal(0)) == sum(
        (event["payment"] for _, event in deliveries), Decimal(0)
    )

    assert_run_balances(periods, result)
