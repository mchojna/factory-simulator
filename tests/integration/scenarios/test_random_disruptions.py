from decimal import Decimal
from typing import Any

from factories import (
    api_client,
    get,
    run_to_the_end,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)

from factory_simulator.api.core.json import write_json

EVERY_DISRUPTION_KIND: list[dict[str, Any]] = [
    {"kind": "supplier_outage", "target": ["chip-maker"], "strength": "0.5000"},
    {"kind": "material_shortage", "target": ["chip"], "strength": "0.5000"},
    {"kind": "quality_drop", "target": ["chip-maker"], "strength": "0.5000"},
    {"kind": "transport_delay", "target": ["chip-maker"], "delay": 1},
    {"kind": "demand_shock", "target": ["monitor"], "factor": "1.5000"},
    {"kind": "line_breakdown", "target": ["line-1"], "loss": "0.1000"},
    {"kind": "price_change", "target": ["chip"], "factor": "1.2000"},
    {"kind": "capacity_cut", "target": ["line-1"], "strength": "0.5000"},
    {"kind": "yield_drop", "target": ["line-1"], "strength": "0.5000"},
]


def every_kind_scenario() -> dict[str, Any]:
    scenario = tiny_scenario()
    scenario["horizon"] = 6
    rules: list[dict[str, Any]] = []
    for position, rule in enumerate(EVERY_DISRUPTION_KIND):
        written = rule | {"name": f"rule-{position}", "chance": "0.4000"}
        if rule["kind"] != "line_breakdown":
            written["duration"] = {"min": 1, "max": 2}
        rules.append(written)
    scenario["random_disruptions"] = rules
    return scenario


def test_a_run_with_a_random_disruption_of_every_kind_shows_each_from_its_start():
    with api_client() as client:
        run = start_run(client, tiny_manifest(), every_kind_scenario(), seed=7)
        observations = [get(client, f"/runs/{run['id']}/observation")[1]]
        for period in range(1, 6):
            observations.append(submit(client, run["id"], period, [])[1])
        run_to_the_end(client, run | {"period": 6})
        _, world = get(client, f"/runs/{run['id']}/world")

    texts = [write_json(answer) for answer in [run, *observations]]
    drawn = [item for item in world["disruptions"] if "/" in item["id"]]
    assert {item["kind"] for item in drawn} == {
        rule["kind"] for rule in EVERY_DISRUPTION_KIND
    }
    for disruption in drawn:
        observation = observations[disruption["start"] - 1]
        shown = {item["id"]: item for item in observation["disruptions"]}
        expected = {key: value for key, value in disruption.items() if key != "visible"}
        assert shown[disruption["id"]] == expected
        before = texts[: disruption["start"]]
        assert all(disruption["id"].encode() not in text for text in before)


def test_a_written_start_shows_its_one_disruption_from_start_less_notice_only():
    manifest = tiny_manifest()
    manifest["lines"]["line-2"] = manifest["lines"]["line-1"]
    rule = {
        "name": "cut",
        "kind": "capacity_cut",
        "target": "all",
        "start": 5,
        "notice": 2,
        "duration": 2,
        "strength": "0.5000",
    }
    scenario = tiny_scenario() | {"horizon": 6, "random_disruptions": [rule]}
    with api_client() as client:
        run = start_run(client, manifest, scenario, seed=7)
        texts = [write_json(run)]
        texts.append(write_json(get(client, f"/runs/{run['id']}/observation")[1]))
        for period in range(1, 7):
            texts.append(write_json(submit(client, run["id"], period, [])[1]))
        _, world = get(client, f"/runs/{run['id']}/world")

    [disruption] = world["disruptions"]
    assert disruption["start"] == 5
    assert disruption["id"] in ("cut/5/line-1", "cut/5/line-2")
    assert all(disruption["id"].encode() not in text for text in texts[:3])
    assert disruption["id"].encode() in texts[3]
    assert run["description"]["scenario"]["random_disruptions"] == [
        rule
        | {"strength": Decimal("0.5"), "chance": None, "choose": None, "raises": None}
    ]


def test_a_cascade_is_described_as_written_and_both_rules_draw_into_the_world():
    outage = {
        "name": "outage",
        "kind": "supplier_outage",
        "target": ["chip-maker"],
        "chance": "0.5000",
        "duration": 1,
        "strength": "0.5000",
        "raises": {"rule": "delays", "factor": "5.0000", "periods": 2},
    }
    delays = {
        "name": "delays",
        "kind": "transport_delay",
        "target": ["chip-maker"],
        "chance": "0.1000",
        "duration": 1,
        "delay": 1,
    }
    scenario = tiny_scenario() | {"horizon": 8, "random_disruptions": [outage, delays]}
    with api_client() as client:
        run = start_run(client, tiny_manifest(), scenario, seed=7)
        run_to_the_end(client, run)
        _, world = get(client, f"/runs/{run['id']}/world")

    [described, _] = run["description"]["scenario"]["random_disruptions"]
    assert described["raises"] == {
        "rule": "delays",
        "factor": Decimal("5"),
        "periods": 2,
    }
    names = {item["id"].split("/")[0] for item in world["disruptions"]}
    assert names == {"outage", "delays"}
