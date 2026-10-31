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

DEMAND = {"min": "30.000", "max": "50.000"}


def shared_manifest() -> dict[str, Any]:
    manifest = tiny_manifest()
    distributor = manifest["customers"]["distributor"]
    distributor["products"]["monitor"]["demand"] = DEMAND
    manifest["customers"]["retailer"] = copy.deepcopy(distributor)
    manifest["products"]["monitor"]["common_share"] = "0.6000"
    return manifest


def test_the_description_shows_the_common_share_as_written():
    with api_client() as client:
        run = start_run(client, shared_manifest(), tiny_scenario())

    product = run["description"]["manifest"]["products"]["monitor"]
    assert product["common_share"] == Decimal("0.6000")


def test_hiding_demand_hides_the_common_share_of_every_product():
    scenario = tiny_scenario() | {"hidden": ["customers.products.demand"]}
    with api_client() as client:
        run = start_run(client, shared_manifest(), scenario)

    product = run["description"]["manifest"]["products"]["monitor"]
    assert "common_share" not in product
    assert "space" in product


def test_the_world_of_a_run_names_the_written_common_share():
    with api_client() as client:
        run = start_run(client, shared_manifest(), tiny_scenario(), seed=12)
        run_to_the_end(client, run)
        _, world = get(client, f"/runs/{run['id']}/world")

    assert world["parameters"]["products.monitor.common_share"] == {
        "value": Decimal("0.6000"),
        "origin": "written",
        "drawn": False,
    }
