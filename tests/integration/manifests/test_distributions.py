from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    get,
    narrow_demand_bodies,
    post,
    run_to_the_end,
    start_run,
    tiny_manifest,
    tiny_scenario,
)

PRICE = {
    "min": "0.4000",
    "max": "0.6000",
    "distribution": "triangular",
    "mode": "0.5000",
}
PUNCTUALITY = {
    "min": "0.5000",
    "max": "1.0000",
    "distribution": "triangular",
    "mode": "0.9000",
}
DEMAND = {
    "min": "30.000",
    "max": "50.000",
    "distribution": "normal",
    "mean": "40.000",
    "sd": "5.000",
}


def shaped_manifest() -> dict[str, Any]:
    manifest = tiny_manifest()
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    entry["price"] = PRICE
    entry["punctuality"] = PUNCTUALITY
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = DEMAND
    return manifest


def test_the_description_shows_a_range_that_may_be_hidden_with_its_distribution():
    with api_client() as client:
        run = start_run(client, shaped_manifest())

    entry = run["description"]["manifest"]["suppliers"]["chip-maker"]["catalogue"][
        "chip"
    ]
    assert entry["punctuality"] == {
        "min": Decimal("0.5"),
        "max": Decimal("1"),
        "distribution": "triangular",
        "mode": Decimal("0.9"),
        "cut_mean": Decimal("0.8"),
    }
    assert isinstance(entry["price"], Decimal)


def test_the_description_shows_a_lognormal_range_with_its_median_and_spread():
    manifest = tiny_manifest()
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    entry["punctuality"] = {
        "min": "0.5000",
        "max": "1.0000",
        "distribution": "lognormal",
        "median": "0.9000",
        "spread": "0.2000",
    }
    with api_client() as client:
        run = start_run(client, manifest)

    described = run["description"]["manifest"]["suppliers"]["chip-maker"]["catalogue"][
        "chip"
    ]
    assert described["punctuality"] == {
        "min": Decimal("0.5"),
        "max": Decimal("1"),
        "distribution": "lognormal",
        "median": Decimal("0.9"),
        "spread": Decimal("0.2"),
        "cut_mean": Decimal("0.823703"),
    }


def test_the_description_gives_the_mean_of_every_range_cut_at_its_min_and_max():
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = {
        "min": 14,
        "max": 70,
        "distribution": "lognormal",
        "median": 35,
        "spread": "0.4",
    }
    hidden = tiny_scenario() | {"hidden": ["customers.products.demand"]}
    with api_client() as client:
        shown = start_run(client, manifest)
        kept = start_run(client, manifest, hidden)

    pair = shown["description"]["manifest"]["customers"]["distributor"]["products"]
    assert pair["monitor"]["demand"]["cut_mean"] == Decimal("36.222159")
    pair = kept["description"]["manifest"]["customers"]["distributor"]["products"]
    assert "demand" not in pair["monitor"]
    assert "cut_mean" not in str(kept["description"])


def test_a_lognormal_range_of_the_largest_spread_starts_a_run():
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = {
        "min": 1,
        "max": 100,
        "distribution": "lognormal",
        "median": 4,
        "spread": 10,
    }
    with api_client() as client:
        manifest_status, created = post(client, "/manifests", manifest)
        path = f"/manifests/{created['id']}/scenarios"
        scenario_status, scenario = post(client, path, tiny_scenario())
        run_status, run = post(
            client, "/runs", {"scenario_id": scenario["id"], "seed": 7}
        )

    assert (manifest_status, scenario_status, run_status) == (201, 201, 201)
    pair = run["description"]["manifest"]["customers"]["distributor"]["products"]
    assert pair["monitor"]["demand"]["cut_mean"] == Decimal("21.145162")


# Across 1 to 9 an sd of 10**20 leaves the cut distribution flat and symmetric about 5.
def test_a_normal_demand_far_narrower_than_its_sd_varies_about_its_mean_of_5():
    with api_client() as client:
        run = start_run(client, *narrow_demand_bodies(), seed=0)
        run_to_the_end(client, run)
        _, world = get(client, f"/runs/{run['id']}/world")

    pair = run["description"]["manifest"]["customers"]["distributor"]["products"]
    assert pair["monitor"]["demand"]["cut_mean"] == 5
    demand = world["demand"]["distributor/monitor"]
    assert len(set(demand)) > 1
    assert all(1 <= quantity <= 9 for quantity in demand)
