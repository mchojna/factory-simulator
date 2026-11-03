import copy
from typing import Any

from factories import (
    api_client,
    assert_run_balances,
    buy,
    get,
    produce,
    run_to_the_end,
    ship,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

HORIZON = 10


def regional_manifest() -> dict[str, Any]:
    manifest = tiny_manifest()
    manifest["products"]["tablet"] = copy.deepcopy(manifest["products"]["monitor"])
    line_items = manifest["lines"]["line-1"]["items"]
    line_items["tablet"] = dict(line_items["monitor"])
    customer_products = manifest["customers"]["distributor"]["products"]
    customer_products["tablet"] = dict(customer_products["monitor"])
    suppliers = manifest["suppliers"]
    suppliers["chip-house"] = copy.deepcopy(suppliers["chip-maker"])
    for supplier_id, region in (("chip-maker", "apac"), ("chip-house", "emea")):
        del suppliers[supplier_id]["catalogue"]["chip"]["punctuality"]
        suppliers[supplier_id]["groups"] = [region]
    for product_id, segment in (("monitor", "new-devices"), ("tablet", "legacy")):
        del manifest["products"][product_id]["storage_cost"]
        del customer_products[product_id]["late_penalty"]
        manifest["products"][product_id]["groups"] = [segment]
    manifest["groups"] = {
        "apac": {
            "kind": "region",
            "defaults": {"catalogue": {"punctuality": "0.9000"}},
        },
        "emea": {
            "kind": "region",
            "defaults": {
                "catalogue": {"punctuality": {"min": "0.5000", "max": "1.0000"}}
            },
        },
        "new-devices": {
            "kind": "segment",
            "defaults": {
                "items": {"storage_cost": "0.1000"},
                "customer_products": {"late_penalty": "3.0000"},
            },
        },
        "legacy": {
            "kind": "segment",
            "defaults": {
                "items": {"storage_cost": "0.0500"},
                "customer_products": {"late_penalty": "1.0000"},
            },
        },
    }
    return manifest


def decisions_of(period: int) -> list[dict[str, Any]]:
    return [
        ship(f"order-{period}-1", "4"),
        produce("monitor", "4"),
        produce("board", "9"),
        buy("10", supplier="chip-maker"),
        buy("10", supplier="chip-house"),
    ]


def test_a_factory_of_regions_and_segments_runs_with_every_origin_known():
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["start"]["stock"]["main"]["board"] = "40"
    decisions = {period: decisions_of(period) for period in range(1, HORIZON + 1)}
    with api_client() as client:
        run = start_run(client, regional_manifest(), scenario)
        finished = run_to_the_end(client, run, decisions)
        _, result = get(client, f"/runs/{run['id']}/result")
        _, periods = get(client, f"/runs/{run['id']}/periods")
        _, world = get(client, f"/runs/{run['id']}/world")

    assert finished["finished"] is True
    assert_run_balances(periods, result)
    origins = {values["origin"] for values in world["parameters"].values()}
    assert origins <= {"written", "default", "apac", "emea", "new-devices", "legacy"}
    assert {"apac", "emea", "new-devices", "legacy"} <= origins


def test_a_regional_outage_and_a_segment_step_act_on_their_groups_only():
    manifest = regional_manifest()
    scenario = tiny_scenario()
    scenario["horizon"] = HORIZON
    scenario["start"]["stock"]["main"]["board"] = "40"
    scenario["disruptions"] = [
        {
            "kind": "supplier_outage",
            "target": {"region": "apac"},
            "start": 3,
            "duration": 2,
            "strength": "1.0000",
        }
    ]
    scenario["demand_shapes"] = [
        {
            "kind": "step",
            "target": {"segment": "legacy"},
            "period": 2,
            "factor": "2.0000",
        }
    ]
    plain_scenario = tiny_scenario()
    plain_scenario["horizon"] = HORIZON
    decisions = {period: decisions_of(period) for period in range(1, HORIZON + 1)}
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        run_to_the_end(client, run, decisions)
        _, result = get(client, f"/runs/{run['id']}/result")
        _, periods = get(client, f"/runs/{run['id']}/periods")
        base = start_run(client, manifest, plain_scenario)
        run_to_the_end(client, base, decisions)
        _, plain = get(client, f"/runs/{base['id']}/result")

    groups, plain_groups = result["measures"]["groups"], plain["measures"]["groups"]
    # 8 orders of 10 from apac arrive by period 10; the 2 that arrive in periods 3
    # and 4 of the outage arrive as 0. 7 orders of 10 from emea arrive.
    assert (groups["apac"]["units_arrived"], plain_groups["apac"]["units_arrived"]) == (
        60,
        80,
    )
    assert (groups["emea"]["units_arrived"], plain_groups["emea"]["units_arrived"]) == (
        70,
        70,
    )
    # Demand of 4 a period; the step doubles legacy demand from period 2: 4 + 9 * 8.
    assert (
        groups["legacy"]["units_ordered"],
        plain_groups["legacy"]["units_ordered"],
    ) == (76, 40)
    assert (
        groups["new-devices"]["units_ordered"],
        plain_groups["new-devices"]["units_ordered"],
    ) == (40, 40)
    assert_run_balances(periods, result)
