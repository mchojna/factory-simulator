from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    assert_run_balances,
    buy,
    get,
    produce,
    ship,
    start_run,
    submit,
    tiny_manifest,
)

DECISIONS: dict[int, list[dict[str, Any]]] = {
    1: [
        ship("order-1-1", "4"),
        produce("monitor", "4"),
        produce("board", "20"),
        buy("50"),
    ],
    2: [ship("order-2-1", "4"), produce("monitor", "4")],
    3: [ship("order-3-1", "4"), produce("monitor", "4"), produce("board", "20")],
    4: [ship("order-4-1", "4"), produce("monitor", "4")],
    5: [ship("order-5-1", "4")],
}


def names_only_what_is_seen(
    decision: dict[str, Any], observation: dict[str, Any], manifest: dict[str, Any]
) -> bool:
    if decision["kind"] == "ship":
        return decision["order"] in {
            order["id"] for order in observation["customer_orders"]
        }
    if decision["kind"] == "produce":
        line = manifest["lines"][decision["line"]]
        return (
            decision["line"] in observation["lines"]
            and decision["item"] in (line["items"])
        )
    catalogue = manifest["suppliers"][decision["supplier"]]["catalogue"]
    return decision["material"] in catalogue


def test_a_run_decided_from_its_observations_accepts_everything_and_keeps_profit():
    with api_client() as client:
        run = start_run(client)
        manifest = run["description"]["manifest"]
        _, observation = get(client, f"/runs/{run['id']}/observation")
        for period, decisions in DECISIONS.items():
            for decision in decisions:
                assert names_only_what_is_seen(decision, observation, manifest)
            _, observation = submit(client, run["id"], period, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, result = get(client, f"/runs/{run['id']}/result")

    outcomes = [
        outcome
        for period in periods["periods"]
        for step in period["steps"]
        for outcome in step.get("outcomes", [])
    ]
    ledger = [row for period in periods["periods"] for row in period["ledger"]]
    end = periods["periods"][-1]["steps"][-1]["state"]["stock"]["main"]
    salvage_values = {
        item_id: item["salvage_value"]
        for kind in ("materials", "components", "products")
        for item_id, item in tiny_manifest()[kind].items()
    }
    salvage = sum(
        (end[item_id] * Decimal(value) for item_id, value in salvage_values.items()),
        Decimal(0),
    )
    revenue = sum(row["amount"] for row in ledger if row["kind"] == "customer_payment")
    costs = sum(-row["amount"] for row in ledger if row["amount"] < 0)
    earned = sum(
        row["amount"]
        for row in ledger
        if row["kind"] == "interest_earned" and row["amount"] > 0
    )

    assert [outcome["accepted"] for outcome in outcomes] == [True] * 12
    assert result["profit"] == revenue - costs + earned + salvage
    assert_run_balances(periods, result)
