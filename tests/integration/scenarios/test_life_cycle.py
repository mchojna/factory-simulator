import copy
from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    get,
    run_to_the_end,
    start_run,
    tiny_manifest,
    tiny_scenario,
)


def two_products_with_demand_range() -> dict[str, Any]:
    manifest = tiny_manifest()
    manifest["products"]["tablet"] = copy.deepcopy(manifest["products"]["monitor"])
    manifest["lines"]["line-1"]["items"]["tablet"] = dict(
        manifest["lines"]["line-1"]["items"]["monitor"]
    )
    pairs = manifest["customers"]["distributor"]["products"]
    pairs["monitor"]["demand"] = {"min": "30.000", "max": "50.000"}
    pairs["monitor"]["demand_persistence"] = "0.8000"
    pairs["tablet"] = dict(pairs["monitor"])
    del pairs["tablet"]["demand_persistence"]
    return manifest


def ordered_per_period(periods: dict[str, Any], product: str) -> list[Decimal]:
    found: list[Decimal] = []
    for period in periods["periods"]:
        steps = {step["step"]: step for step in period["steps"]}
        found += [
            event["quantity"]
            for event in steps["apply_events"]["events"]
            if event["kind"] == "customer_order" and event["product"] == product
        ]
    return found


def test_each_pair_orders_its_base_demand_of_the_world():
    with api_client() as client:
        run = start_run(
            client, two_products_with_demand_range(), tiny_scenario(), seed=3
        )
        run_to_the_end(client, run)
        _, world = get(client, f"/runs/{run['id']}/world")
        _, periods = get(client, f"/runs/{run['id']}/periods")

    for product in ("monitor", "tablet"):
        demand = world["demand"][f"distributor/{product}"]
        assert ordered_per_period(periods, product) == demand
        assert all(Decimal(30) <= base <= Decimal(50) for base in demand)


def test_an_s_curve_of_one_product_leaves_the_orders_of_another():
    scenario = tiny_scenario()
    shaped = copy.deepcopy(scenario)
    shaped["demand_shapes"] = [
        {
            "kind": "s_curve",
            "target": {"product": "monitor"},
            "middle": 3,
            "steepness": "1.0000",
            "from_factor": "0.0000",
            "to_factor": "1.0000",
        }
    ]
    measured: list[dict[str, Any]] = []
    with api_client() as client:
        for body in (scenario, shaped):
            run = start_run(client, two_products_with_demand_range(), body, seed=3)
            run_to_the_end(client, run)
            _, result = get(client, f"/runs/{run['id']}/result")
            measured.append(result["measures"]["products"])

    assert (
        measured[0]["tablet"]["units_ordered"] == measured[1]["tablet"]["units_ordered"]
    )
    assert (
        measured[0]["monitor"]["units_ordered"]
        != measured[1]["monitor"]["units_ordered"]
    )


def test_the_description_writes_an_s_curve_with_its_kind_as_written():
    scenario = tiny_scenario()
    scenario["demand_shapes"] = [
        {
            "kind": "s_curve",
            "target": {"product": "monitor"},
            "middle": 3,
            "steepness": "1.0000",
            "from_factor": "0.0000",
            "to_factor": "1.0000",
        }
    ]
    with api_client() as client:
        run = start_run(client, tiny_manifest(), scenario)

    [shape] = run["description"]["scenario"]["demand_shapes"]
    assert shape["kind"] == "s_curve"
