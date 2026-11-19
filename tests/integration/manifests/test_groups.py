import copy
from decimal import Decimal
from typing import Any

from factories import (
    apac_supplier_manifest,
    api_client,
    buy,
    events_of_periods,
    get,
    rows_of_run,
    run_to_the_end,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)

APAC = {
    "kind": "region",
    "defaults": {
        "catalogue": {
            "price": "0.6000",
            "punctuality": {"min": "0.8000", "max": "0.9200"},
        }
    },
}
BUY = {
    1: [{"kind": "buy", "supplier": "chip-maker", "material": "chip", "quantity": "50"}]
}


def grouped_manifest() -> dict[str, Any]:
    manifest = tiny_manifest()
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    del entry["price"]
    del entry["punctuality"]
    manifest["suppliers"]["chip-maker"]["groups"] = ["apac"]
    manifest["groups"] = {"apac": APAC}
    return manifest


def written_out_manifest() -> dict[str, Any]:
    manifest = tiny_manifest()
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    entry["price"] = "0.6000"
    entry["punctuality"] = {"min": "0.8000", "max": "0.9200"}
    return manifest


def without_groups(measures: dict[str, Any]) -> dict[str, Any]:
    return {family: values for family, values in measures.items() if family != "groups"}


def segments_and_regions() -> dict[str, Any]:
    manifest = tiny_manifest()
    manifest["products"]["tablet"] = copy.deepcopy(manifest["products"]["monitor"])
    manifest["lines"]["line-1"]["items"]["tablet"] = dict(
        manifest["lines"]["line-1"]["items"]["monitor"]
    )
    pairs = manifest["customers"]["distributor"]["products"]
    pairs["tablet"] = dict(pairs["monitor"])
    suppliers = manifest["suppliers"]
    suppliers["chip-house"] = copy.deepcopy(suppliers["chip-maker"])
    manifest["products"]["monitor"]["groups"] = ["new-devices"]
    manifest["products"]["tablet"]["groups"] = ["spare-parts"]
    suppliers["chip-maker"]["groups"] = ["apac"]
    suppliers["chip-house"]["groups"] = ["emea"]
    manifest["groups"] = {
        "new-devices": {"kind": "segment"},
        "spare-parts": {"kind": "segment"},
        "apac": {"kind": "region"},
        "emea": {"kind": "region"},
    }
    return manifest


def test_a_run_describes_groups_as_written_and_its_world_names_every_origin():
    with api_client() as client:
        run = start_run(client, grouped_manifest())
        run_to_the_end(client, run)
        _, world = get(client, f"/runs/{run['id']}/world")

    description = run["description"]["manifest"]
    assert description["groups"] == {
        "apac": {
            "kind": "region",
            "defaults": {
                "catalogue": {
                    "price": Decimal("0.6"),
                    "punctuality": {
                        "min": Decimal("0.8"),
                        "max": Decimal("0.92"),
                        "cut_mean": Decimal("0.86"),
                    },
                }
            },
        }
    }
    entry = description["suppliers"]["chip-maker"]["catalogue"]["chip"]
    assert entry["price"] == Decimal("0.6")
    parameters = world["parameters"]
    path = "suppliers.chip-maker.catalogue.chip"
    assert parameters[f"{path}.price"]["origin"] == "apac"
    assert parameters[f"{path}.punctuality"]["origin"] == "apac"
    assert parameters[f"{path}.punctuality"]["drawn"] is True
    assert parameters[f"{path}.lead_time"]["origin"] == "written"
    assert parameters[f"{path}.backfill_delay"]["origin"] == "default"


def test_a_factory_with_groups_gives_the_same_run_as_written_out():
    rows: list[dict[str, list[Any]]] = []
    drawn: list[dict[str, Any]] = []
    with api_client() as client:
        for manifest in (grouped_manifest(), written_out_manifest()):
            run = start_run(client, manifest, tiny_scenario(), seed=9)
            run_to_the_end(client, run, BUY)
            _, world = get(client, f"/runs/{run['id']}/world")
            drawn.append(
                {path: values["value"] for path, values in world["parameters"].items()}
            )
            run_rows = rows_of_run(client, run["id"])
            results = [
                result | {"measures": without_groups(result["measures"])}
                for result in run_rows["results"]
            ]
            rows.append({"ledger": run_rows["ledger"], "results": results})

    assert drawn[0] == drawn[1]
    assert rows[0] == rows[1]


def test_the_result_and_the_periods_keep_measures_per_segment_and_region():
    buy = {"kind": "buy", "material": "chip", "quantity": "10"}
    decisions = {
        1: [
            {"kind": "ship", "order": "order-1-1", "quantity": "4"},
            buy | {"supplier": "chip-maker"},
            buy | {"supplier": "chip-house"},
        ]
    }
    with api_client() as client:
        run = start_run(client, segments_and_regions())
        run_to_the_end(client, run, decisions)
        _, result = get(client, f"/runs/{run['id']}/result")
        _, periods = get(client, f"/runs/{run['id']}/periods")

    groups = result["measures"]["groups"]
    for segment in ("new-devices", "spare-parts"):
        for name in ("revenue", "units_ordered", "units_shipped", "units_lost"):
            assert name in groups[segment]
        assert "service" in groups[segment]
    for region in ("apac", "emea"):
        assert {"units_arrived", "units_accepted"} <= set(groups[region])
    first = periods["periods"][0]["steps"][-1]["measures"]["groups"]
    assert first["new-devices"]["units_ordered"] == 4


def test_a_disruption_of_a_region_shows_its_members_as_target():
    scenario = tiny_scenario()
    scenario["disruptions"] = [
        {
            "kind": "supplier_outage",
            "target": {"region": "apac"},
            "start": 2,
            "duration": 1,
            "strength": "0.5000",
        }
    ]
    with api_client() as client:
        run = start_run(client, segments_and_regions(), scenario)
        submit(client, run["id"], 1, [])
        _, observation = get(client, f"/runs/{run['id']}/observation")

    [disruption] = observation["disruptions"]
    assert (disruption["id"], disruption["target"]) == ("disruption-1", ["chip-maker"])


def test_the_description_shows_the_groups_each_member_lists():
    manifest = grouped_manifest()
    manifest["products"]["monitor"]["groups"] = ["new-devices"]
    manifest["groups"]["new-devices"] = {"kind": "segment"}
    with api_client() as client:
        run = start_run(client, manifest)

    described = run["description"]["manifest"]
    assert described["suppliers"]["chip-maker"]["groups"] == ["apac"]
    assert described["products"]["monitor"]["groups"] == ["new-devices"]
    assert "groups" not in described["materials"]["chip"]
    assert "groups" not in described["customers"]["distributor"]


def test_a_price_given_by_a_group_is_paid_by_its_members_only():
    def payments(group_price: str, own_price: str | None) -> list[object]:
        manifest = apac_supplier_manifest()
        manifest["groups"]["apac"]["defaults"]["catalogue"]["price"] = group_price
        manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["punctuality"] = (
            "1.0000"
        )
        if own_price is not None:
            manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["price"] = (
                own_price
            )
        decisions = {1: [buy("10")]}
        with api_client() as client:
            run = start_run(client, manifest, tiny_scenario(), seed=5)
            run_to_the_end(client, run, decisions)
            _, periods = get(client, f"/runs/{run['id']}/periods")
        return [
            (event["payment"], event["accepted"])
            for event in events_of_periods(periods, "delivery")
        ]

    assert payments("5.0000", None) == [(Decimal("50"), Decimal("10"))]
    assert payments("5.5000", None) == [(Decimal("55"), Decimal("10"))]
    assert payments("5.5000", "5.0000") == [(Decimal("50"), Decimal("10"))]


def test_a_group_default_of_whole_numbers_starts_a_run_with_its_cut_mean():
    completeness = {
        "min": "0.0360",
        "max": "1.0000",
        "distribution": "lognormal",
        "median": "1.0000",
        "spread": "0.0001",
    }
    manifest = tiny_manifest()
    del manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["completeness"]
    manifest["suppliers"]["chip-maker"]["groups"] = ["apac"]
    manifest["groups"] = {
        "apac": {
            "kind": "region",
            "defaults": {"catalogue": {"completeness": completeness}},
        }
    }
    with api_client() as client:
        run = start_run(client, manifest)

    groups = run["description"]["manifest"]["groups"]
    written = groups["apac"]["defaults"]["catalogue"]["completeness"]
    assert written["cut_mean"] == Decimal("0.99992")
