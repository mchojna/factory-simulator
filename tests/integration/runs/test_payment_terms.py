from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    get,
    run_to_the_end,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)

SHIP_IN_PERIOD_3 = {3: [{"kind": "ship", "order": "order-0-1", "quantity": "10"}]}


def shipment_bodies(terms: int, horizon: int) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = tiny_manifest()
    customer = manifest["customers"]["distributor"]
    customer["payment_terms"] = terms
    customer["products"]["monitor"]["demand"] = "0"
    for kind in ("materials", "components", "products"):
        for item in manifest[kind].values():
            item["salvage_value"] = "0.0000"
    scenario = tiny_scenario()
    scenario["horizon"] = horizon
    scenario["start"]["stock"]["main"]["monitor"] = "20"
    scenario["start"]["customer_orders"] = [
        {"customer": "distributor", "product": "monitor", "quantity": "10", "due": 3}
    ]
    return manifest, scenario


def result_of(terms: int, horizon: int) -> dict[str, Any]:
    with api_client() as client:
        run = start_run(client, *shipment_bodies(terms, horizon))
        run_to_the_end(client, run, SHIP_IN_PERIOD_3)
        _, result = get(client, f"/runs/{run['id']}/result")
    return result


def test_a_receivable_due_after_the_horizon_counts_in_profit_and_is_not_a_term():
    result = result_of(2, horizon=4)

    assert result["receivables"] == Decimal(500)
    assert "receivables" not in result["terms"]
    assert result["terms"]["revenue"] == Decimal(500)
    assert result["profit"] == (
        result["cash_at_end"] - result["cash_at_start"] + Decimal(500)
    )


def test_a_receivable_due_in_the_last_period_is_paid_and_none_is_left():
    result = result_of(2, horizon=5)

    assert result["receivables"] == Decimal(0)
    assert result["profit"] == result["cash_at_end"] - result["cash_at_start"]


def test_the_observation_lists_the_receivable_until_its_payment():
    with api_client() as client:
        run = start_run(client, *shipment_bodies(2, horizon=6))
        observations: dict[int, Any] = {}
        for period in range(1, 5):
            decisions = SHIP_IN_PERIOD_3.get(period, [])
            _, observations[period + 1] = submit(client, run["id"], period, decisions)

    assert observations[4]["receivables"] == [
        {
            "shipment": "ship-3-1",
            "customer": "distributor",
            "amount": Decimal(500),
            "payment_period": 5,
        }
    ]
    assert observations[5]["receivables"] == []
    assert {
        "kind": "customer_payment",
        "step": "apply_events",
        "reference": "ship-3-1",
        "amount": Decimal(500),
    } in observations[5]["events"]


def test_the_description_shows_the_drawn_payment_terms():
    manifest, scenario = shipment_bodies(2, horizon=6)
    manifest["customers"]["distributor"]["payment_terms"] = {"min": 1, "max": 3}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run)
        _, world = get(client, f"/runs/{run['id']}/world")

    drawn = run["description"]["manifest"]["customers"]["distributor"]["payment_terms"]
    assert drawn in {1, 2, 3}
    parameter = world["parameters"]["customers.distributor.payment_terms"]
    assert drawn == parameter["value"]
