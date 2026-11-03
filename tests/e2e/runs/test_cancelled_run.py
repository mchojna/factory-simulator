from decimal import Decimal
from typing import Any

from factories import (
    accepted_decisions_of_periods,
    api_client,
    assert_run_balances,
    buy,
    cancel,
    events_of_periods,
    get,
    listed_supplier_orders,
    run_to_the_end,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 10


# The decisions of a period: buy 100 chips and cancel half of the buy of the period
# before.
def decisions_of(period: int) -> list[dict[str, Any]]:
    decisions = [buy("100")]
    if period > 1:
        decisions.append(cancel(f"buy-{period - 1}-1", "50"))
    return decisions


def test_a_run_that_cancels_half_of_every_order_balances_its_orders_items_and_cash():
    manifest = tiny_manifest()
    chip = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    chip.update(lead_time=3, cancellation_fee="0.1000")
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    decisions = {period: decisions_of(period) for period in range(1, HORIZON + 1)}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")
    end = periods["periods"][-1]["steps"][-1]["state"]

    cancels = accepted_decisions_of_periods(periods, "cancel")
    assert len(cancels) == HORIZON - 1
    assert result["terms"]["cancellation_fee"] == (HORIZON - 1) * 50 * Decimal("0.1")

    bought = {
        order_id: order["quantity"]
        for order_id, order in listed_supplier_orders(periods).items()
    }
    assert sorted(bought.values()) == sorted(
        decision["quantity"]
        for decision in accepted_decisions_of_periods(periods, "buy")
    )
    settled = dict.fromkeys(bought, Decimal(0))
    for event in events_of_periods(periods, "delivery"):
        settled[event["reference"]] += event["arrived"] + event["lost"]
    for decision in cancels:
        settled[decision["order"]] += decision["quantity"]
    for order in end["supplier_orders"]:
        settled[order["id"]] += order["open_quantity"]
    assert settled == bought

    delivered = sum(
        (event["accepted"] for event in events_of_periods(periods, "delivery")),
        Decimal(0),
    )
    assert end["stock"]["main"]["chip"] == Decimal(100) + delivered

    assert_run_balances(periods, result)
