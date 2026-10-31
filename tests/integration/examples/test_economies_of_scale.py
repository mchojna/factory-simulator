from decimal import Decimal
from typing import Any

from factories import (
    Client,
    api_client,
    example_bodies,
    example_scenario,
    get,
    start_run,
    submit,
)


# The id of a started run of a scenario, posted with the example manifest.
def started_run_id(client: Client, scenario: dict[str, Any], seed: int = 1) -> str:
    manifest, _ = example_bodies("steady-market")
    return start_run(client, manifest, scenario, seed)["id"]


def chips(quantity: str) -> dict[str, Any]:
    return {
        "kind": "buy",
        "supplier": "apac-chips",
        "material": "microchip",
        "quantity": quantity,
        "warehouse": "main-plant",
    }


def test_a_buy_below_the_minimum_is_refused_and_large_buys_get_their_tier_price():
    scenario = example_scenario() | {"start": {"cash": "100000"}}
    with api_client() as client:
        run_id = started_run_id(client, scenario)
        _, first = submit(client, run_id, 1, [chips("499"), chips("1000")])
        _, second = submit(client, run_id, 2, [chips("1500")])

    below, tier_1000 = first["outcomes"]
    [tier_1500] = second["outcomes"]
    assert (below["accepted"], below["reason"]) == (False, "below_min_quantity")
    assert (below["asked"], below["available"]) == (Decimal(499), Decimal(500))
    assert tier_1000["accepted"] and tier_1500["accepted"]
    prices = {
        order["quantity"]: order["unit_price"] for order in second["supplier_orders"]
    }
    assert prices == {Decimal(1000): Decimal("5.85"), Decimal(1500): Decimal("5.7")}


def test_a_power_module_after_control_boards_pays_the_changeover_of_the_smt_line():
    scenario = example_scenario() | {
        "start": {
            "cash": "100000",
            "stock": {
                "main-plant": {
                    "passive-kit": "100",
                    "pcb-blank": "50",
                    "copper-wire": "100",
                }
            },
            "set_for": {"smt-line": "control-board"},
        }
    }
    produce = {
        "kind": "produce",
        "line": "smt-line",
        "item": "power-module",
        "quantity": "10",
    }
    with api_client() as client:
        run_id = started_run_id(client, scenario)
        submit(client, run_id, 1, [produce])
        _, periods = get(client, f"/runs/{run_id}/periods")

    [period] = periods["periods"]
    measures = period["steps"][-1]["measures"]
    line = measures["lines"]["smt-line"]
    assert measures["total"]["changeover_cost"] == Decimal(300)
    assert line["changeover_hours"] == Decimal(2)
