from decimal import Decimal
from typing import Any, cast

import pytest
from factories import (
    api_client,
    assert_run_balances,
    example_decisions,
    example_scenario,
    get,
    post,
    rows_of_run,
    run_to_the_end,
)

from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.services.examples import EXAMPLES


@pytest.mark.slow
def test_a_run_of_the_example_pays_each_buy_at_the_price_of_its_placing_period():
    manifest = cast(
        dict[str, Any], read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    )
    entry = manifest["suppliers"]["emea-electronic-parts"]["catalogue"]["passive-kit"]
    entry["price"] = {"min": "2.2000", "max": "2.6000", "drawn": "period"}
    scenario = example_scenario() | {"start": {"cash": "500000"}}
    with api_client() as client:
        _, stored_manifest = post(client, "/manifests", manifest)
        _, stored_scenario = post(
            client, f"/manifests/{stored_manifest['id']}/scenarios", scenario
        )
        _, run = post(
            client, "/runs", {"scenario_id": stored_scenario["id"], "seed": 2}
        )
        decisions = {period: example_decisions(period) for period in range(1, 53)}
        finished = run_to_the_end(client, run, decisions)
        _, result = get(client, f"/runs/{run['id']}/result")
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, world = get(client, f"/runs/{run['id']}/world")
        rows = rows_of_run(client, run["id"])

    assert (finished["period"], finished["finished"]) == (52, True)
    assert_run_balances(periods, result)
    prices = world["prices"]["emea-electronic-parts/passive-kit"]
    kits = {
        f"buy-{row['decision_id']}"
        for row in rows["outcomes"]
        if row["kind"] == "buy"
        and row["accepted"]
        and row["outcome"]["decision"]["material"] == "passive-kit"
        and row["outcome"]["decision"]["supplier"] == "emea-electronic-parts"
    }
    accepted = {
        (row["period"], row["reference"]): row["fields"]["accepted"]
        for row in rows["events"]
        if row["kind"] == "delivery" and row["reference"] in kits
    }
    payments = {
        (row["period"], row["reference"]): row["amount"]
        for row in rows["ledger"]
        if row["kind"] == "material_payment" and row["reference"] in kits
    }
    assert len(payments) >= 10
    assert payments.keys() == accepted.keys()
    for (period, reference), amount in payments.items():
        placed = int(reference.split("-")[1])
        assert amount == -accepted[period, reference] * Decimal(prices[placed - 1])
