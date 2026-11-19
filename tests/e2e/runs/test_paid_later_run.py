from decimal import Decimal

from factories import (
    api_client,
    assert_run_balances,
    get,
    run_to_the_end,
    ship,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 10


def test_a_run_paid_two_periods_late_keeps_the_last_two_revenues_as_receivables():
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["payment_terms"] = 2
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["start"]["stock"]["main"]["monitor"] = "40"
    decisions = {
        period: [ship(f"order-{period}-1", "4")] for period in range(1, HORIZON + 1)
    }
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    payments = [
        period["period"]
        for period in periods["periods"]
        for row in period["ledger"]
        if row["kind"] == "customer_payment"
    ]
    terms = result["terms"]
    assert payments == list(range(3, HORIZON + 1))
    assert result["receivables"] == 2 * 4 * Decimal(50)
    assert terms["revenue"] == HORIZON * 4 * Decimal(50)
    assert result["profit"] == (
        result["cash_at_end"]
        - result["cash_at_start"]
        + result["receivables"]
        + terms["salvage"]
    )
    assert_run_balances(periods, result)
