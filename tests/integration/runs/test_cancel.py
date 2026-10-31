import copy
from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    buy,
    cancel,
    get,
    run_to_the_end,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)


def chip_and_glass_manifest() -> dict[str, Any]:
    manifest = tiny_manifest()
    chip = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    chip.update(lead_time=3, cancellation_fee="0.1000")
    manifest["materials"]["glass"] = copy.deepcopy(manifest["materials"]["chip"])
    manifest["components"]["board"]["recipes"]["standard"]["glass"] = "1.000"
    glass = copy.deepcopy(chip) | {"cancellation_fee": "0.2000"}
    manifest["suppliers"]["glass-maker"] = {"catalogue": {"glass": glass}}
    return manifest


def chip_manifest(capacity: str = "100.000") -> dict[str, Any]:
    manifest = tiny_manifest()
    chip = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    chip.update(lead_time=3, cancellation_fee="0.1000")
    manifest["warehouses"]["main"]["capacity"] = capacity
    return manifest


def outcomes_of_period_2(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with api_client() as client:
        run = start_run(client, chip_manifest(capacity="12.000"), tiny_scenario())
        submit(client, run["id"], 1, [buy("1000")])
        _, observation = submit(client, run["id"], 2, decisions)
    return observation["outcomes"]


def test_the_measures_count_cancelled_units_and_fees_per_supplier_and_material():
    decisions = {
        1: [buy("100"), buy("50", "glass", "glass-maker")],
        2: [cancel("buy-1-1", "30"), cancel("buy-1-2", "20")],
    }
    with api_client() as client:
        run = start_run(client, chip_and_glass_manifest(), tiny_scenario())
        run_to_the_end(client, run, decisions)
        _, result = get(client, f"/runs/{run['id']}/result")

    suppliers = result["measures"]["suppliers"]
    assert suppliers["chip-maker/chip"]["units_cancelled"] == Decimal(30)
    assert suppliers["glass-maker/glass"]["units_cancelled"] == Decimal(20)
    assert suppliers["chip-maker/chip"]["cancellation_fee"] == Decimal(3)
    assert suppliers["glass-maker/glass"]["cancellation_fee"] == Decimal(4)
    assert result["measures"]["total"]["cancellation_fee"] == Decimal(7)
    assert result["terms"]["cancellation_fee"] == Decimal(7)


def test_a_cancel_frees_space_before_a_buy_of_the_same_submission_is_checked():
    alone = outcomes_of_period_2([buy("1000")])
    with_cancel = outcomes_of_period_2([buy("1000"), cancel("buy-1-1", "1000")])

    assert (alone[0]["accepted"], alone[0]["reason"]) == (False, "not_enough_space")
    assert [
        (outcome["decision_id"], outcome["accepted"]) for outcome in with_cancel
    ] == [
        ("2-2", True),
        ("2-1", True),
    ]


def test_the_observation_after_a_cancel_shows_the_lower_open_quantity_and_outcome():
    with api_client() as client:
        run = start_run(client, chip_manifest(), tiny_scenario())
        submit(client, run["id"], 1, [])
        submit(client, run["id"], 2, [buy("100")])
        _, observation = submit(client, run["id"], 3, [cancel("buy-2-1", "60")])

    [order] = observation["supplier_orders"]
    assert (order["id"], order["quantity"], order["open_quantity"]) == (
        "buy-2-1",
        Decimal(100),
        Decimal(40),
    )
    assert observation["outcomes"] == [
        {
            "decision_id": "3-1",
            "decision": {"kind": "cancel", "order": "buy-2-1", "quantity": Decimal(60)},
            "accepted": True,
            "reference": "cancel-3-1",
        }
    ]
