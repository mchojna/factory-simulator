from decimal import Decimal

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

HORIZON = 12


DECISIONS = {
    1: [buy("1200")],
    2: [cancel("buy-1-1", "200")],
    4: [buy("5500"), buy("600")],
    5: [cancel("buy-4-1", "500"), cancel("buy-4-2", "600")],
    7: [buy("800")],
    8: [cancel("buy-7-1", "300")],
    10: [buy("2000")],
}


def test_an_integer_run_of_tiered_buys_and_cancels_balances_and_keeps_its_profit():
    manifest = tiny_manifest()
    manifest["warehouses"]["main"]["capacity"] = "1000.000"
    manifest["cash"]["credit_limit"] = "100000.0000"
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"].update(
        price="5.0000",
        lead_time=3,
        max_quantity="20000.000",
        min_quantity="500.000",
        cancellation_fee="0.1000",
        discounts=[
            {"from": "1000.000", "price": "4.6000"},
            {"from": "5000.000", "price": "4.3000"},
        ],
    )
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, DECISIONS)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")
    end = periods["periods"][-1]["steps"][-1]["state"]

    assert run["description"]["linear"] is False
    assert len(accepted_decisions_of_periods(periods, "buy")) == 5
    assert len(accepted_decisions_of_periods(periods, "cancel")) == 4
    orders = listed_supplier_orders(periods)
    unit_prices = {order_id: order["unit_price"] for order_id, order in orders.items()}
    assert unit_prices == {
        "buy-1-1": Decimal("4.6000"),
        "buy-4-1": Decimal("4.3000"),
        "buy-4-2": Decimal("5.0000"),
        "buy-7-1": Decimal("5.0000"),
        "buy-10-1": Decimal("4.6000"),
    }

    bought = {order_id: order["quantity"] for order_id, order in orders.items()}
    assert sorted(bought.values()) == sorted(
        decision["quantity"]
        for decision in accepted_decisions_of_periods(periods, "buy")
    )
    settled = dict.fromkeys(bought, Decimal(0))
    for event in events_of_periods(periods, "delivery"):
        settled[event["reference"]] += event["arrived"] + event["lost"]
    for decision in accepted_decisions_of_periods(periods, "cancel"):
        settled[decision["order"]] += decision["quantity"]
    for order in end["supplier_orders"]:
        settled[order["id"]] += order["open_quantity"]
    assert settled == bought

    assert_run_balances(periods, result)
