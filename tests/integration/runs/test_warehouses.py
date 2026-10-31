from decimal import Decimal

from factories import (
    api_client,
    get,
    records,
    run_to_the_end,
    start_run,
    submit,
    tiny_scenario,
    two_warehouse_manifest,
)

from factory_simulator.api.record.models.run import Interaction


def test_a_ship_without_a_warehouse_among_several_is_refused_whole():
    ship = {"kind": "ship", "order": "order-1-1", "quantity": "1"}
    with api_client() as client:
        run = start_run(client, two_warehouse_manifest(), tiny_scenario())
        status, answer = submit(client, run["id"], 1, [ship])
        _, observation = get(client, f"/runs/{run['id']}/observation")
        rows = records(client, Interaction, run_id=run["id"])

    assert status == 422
    assert answer["detail"] == "decisions.0.warehouse: Field required"
    assert observation["period"] == 1
    assert [row["kind"] for row in rows] == ["refusal"]


def test_a_missing_warehouse_is_refused_before_another_period():
    ship = {"kind": "ship", "order": "order-1-1", "quantity": "1"}
    with api_client() as client:
        run = start_run(client, two_warehouse_manifest(), tiny_scenario())
        status, answer = submit(client, run["id"], 2, [ship])

    assert (status, answer["detail"]) == (422, "decisions.0.warehouse: Field required")


def test_a_run_buys_produces_and_ships_at_one_of_two_warehouses():
    decisions = {
        1: [
            {
                "kind": "ship",
                "order": "order-1-1",
                "quantity": "4",
                "warehouse": "main",
            },
            {"kind": "produce", "line": "line-1", "item": "board", "quantity": "5"},
            {
                "kind": "buy",
                "supplier": "chip-maker",
                "material": "chip",
                "quantity": "50",
                "warehouse": "main",
            },
        ]
    }
    with api_client() as client:
        run = start_run(client, two_warehouse_manifest(), tiny_scenario())
        status, observation = submit(client, run["id"], 1, decisions[1])

    assert status == 200
    assert [outcome["accepted"] for outcome in observation["outcomes"]] == [True] * 3
    assert observation["stock"]["centre"] == {"monitor": 0}
    assert observation["stock"]["main"]["monitor"] == 1
    assert observation["space"]["centre"] == {
        "used": 0,
        "reserved": 0,
        "capacity": 50,
    }
    assert observation["space"]["main"]["reserved"] == Decimal("0.5")


def test_the_result_keeps_storage_transport_and_space_per_warehouse():
    manifest, scenario = two_warehouse_manifest(), tiny_scenario()
    scenario["start"]["stock"]["centre"] = {"monitor": "10"}
    ship = {"kind": "ship", "order": "order-1-1", "quantity": "4"}
    decisions = {1: [ship | {"warehouse": "centre"}]}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, decisions)
        _, result = get(client, f"/runs/{run['id']}/result")

    measures = result["measures"]
    for name in ("storage_cost", "transport_cost"):
        per_warehouse = [
            measures["warehouses"][warehouse][name] for warehouse in ("main", "centre")
        ]
        assert sum(per_warehouse) == measures["total"][name]
    assert measures["warehouses"]["centre"]["transport_cost"] == 4
    assert measures["warehouses"]["centre"]["space_used"] == Decimal("0.9")
