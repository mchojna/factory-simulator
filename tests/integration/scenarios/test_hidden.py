from decimal import Decimal
from typing import Any, cast

import pytest
from factories import (
    api_client,
    draw_world_of_bodies,
    example_count,
    get,
    observed_decision_lists,
    seeds,
    small_factories,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.engine import World

PAIR_KEYS = ("customers", "distributor", "products", "monitor")
# For each hidden group, the paths of the description it removes: a pattern of
# keys, `*` for any key, and the keys removed at its end.
HIDDEN_PATHS: dict[str, list[tuple[tuple[str, ...], tuple[str, ...]]]] = {
    "customers.products.demand": [
        (
            ("manifest", "customers", "*", "products", "*"),
            ("demand", "demand_persistence"),
        ),
        (
            ("manifest", "groups", "*", "defaults", "customer_products"),
            ("demand", "demand_persistence"),
        ),
        (("manifest", "products", "*"), ("common_share",)),
        (("manifest", "groups", "*", "defaults", "items"), ("common_share",)),
    ],
    **{
        f"suppliers.catalogue.{key}": [
            (("manifest", "suppliers", "*", "catalogue", "*"), (key,)),
            (("manifest", "groups", "*", "defaults", "catalogue"), (key,)),
        ]
        for key in ("punctuality", "delay", "completeness", "acceptance")
    },
    "lines.items.yield": [
        (("manifest", "lines", "*", "items", "*"), ("yield",)),
        (("manifest", "groups", "*", "defaults", "line_items"), ("yield",)),
    ],
    **{
        f"lines.{key}": [
            (("manifest", "lines", "*"), (key,)),
            (("manifest", "groups", "*", "defaults", "lines"), (key,)),
        ]
        for key in ("breakdown_chance", "breakdown_loss")
    },
    "disruptions.duration": [
        (("scenario", "random_disruptions", "*"), ("duration",)),
    ],
}
ALL_NINE = [
    "customers.products.demand",
    "suppliers.catalogue.punctuality",
    "suppliers.catalogue.delay",
    "suppliers.catalogue.completeness",
    "suppliers.catalogue.acceptance",
    "lines.items.yield",
    "lines.breakdown_chance",
    "lines.breakdown_loss",
    "disruptions.duration",
]


def hidden_run(
    hidden: list[str],
    manifest: dict[str, Any] | None = None,
    scenario: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenario = scenario or tiny_scenario()
    scenario["hidden"] = hidden
    with api_client() as client:
        return start_run(client, manifest or tiny_manifest(), scenario)


def at(document: dict[str, Any], *path: str) -> dict[str, Any]:
    for key in path:
        document = cast(dict[str, Any], document[key])
    return document


def world_of(factory: tuple[dict[str, Any], dict[str, Any]], seed: int) -> World:
    return draw_world_of_bodies(*factory, seed=seed)


def leaves(
    document: object, path: tuple[str, ...] = ()
) -> dict[tuple[str, ...], object]:
    if isinstance(document, dict):
        found: dict[tuple[str, ...], object] = {}
        for key, child in cast(dict[str, object], document).items():
            found |= leaves(child, (*path, key))
        return found
    if isinstance(document, list):
        found = {}
        for position, child in enumerate(cast(list[object], document)):
            found |= leaves(child, (*path, str(position)))
        return found
    return {path: document}


def is_hidden(path: tuple[str, ...], hidden: list[str]) -> bool:
    for group in hidden:
        for pattern, keys in HIDDEN_PATHS[group]:
            head = path[: len(pattern)]
            if (
                len(path) > len(pattern)
                and all(
                    part in ("*", key) for part, key in zip(pattern, head, strict=True)
                )
                and path[len(pattern)] in keys
            ):
                return True
    return False


def shows_a_duration(path: tuple[str, ...]) -> bool:
    return len(path) >= 3 and path[-3] == "disruptions" and path[-1] == "duration"


def test_hidden_demand_leaves_the_other_terms_of_the_pair():
    manifest = tiny_manifest()
    terms = at(manifest, *PAIR_KEYS)
    terms["demand"] = {"min": "30.000", "max": "50.000"}
    terms["demand_persistence"] = "0.5000"

    run = hidden_run(["customers.products.demand"], manifest)

    shown = at(run["description"]["manifest"], *PAIR_KEYS)
    assert set(shown) == {
        "price",
        "transport_cost",
        "lead_time",
        "patience",
        "late_penalty",
        "lost_sale_penalty",
    }
    assert run["description"]["scenario"]["hidden"] == ["customers.products.demand"]


def test_a_hidden_default_of_a_group_leaves_no_empty_defaults():
    manifest = tiny_manifest()
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    del entry["punctuality"]
    manifest["suppliers"]["chip-maker"]["groups"] = ["apac"]
    manifest["groups"] = {
        "apac": {
            "kind": "region",
            "defaults": {
                "catalogue": {"punctuality": {"min": "0.8000", "max": "0.9200"}}
            },
        }
    }

    run = hidden_run(["suppliers.catalogue.punctuality"], manifest)

    described = run["description"]["manifest"]
    assert described["groups"]["apac"] == {"kind": "region"}
    assert (
        "punctuality" not in described["suppliers"]["chip-maker"]["catalogue"]["chip"]
    )


def test_hidden_line_keys_leave_capacity_wear_and_repair():
    run = hidden_run(
        ["lines.items.yield", "lines.breakdown_chance", "lines.breakdown_loss"]
    )

    line = run["description"]["manifest"]["lines"]["line-1"]
    assert {"capacity", "wear_per_period", "wear_per_hour", "repair_cost"} <= set(line)
    assert not {"breakdown_chance", "breakdown_loss"} & set(line)
    assert all("yield" not in terms for terms in line["items"].values())


def test_hidden_durations_leave_the_rest_of_a_disruption():
    scenario = tiny_scenario()
    scenario["horizon"] = 10
    scenario["disruptions"] = [
        {
            "kind": "transport_delay",
            "target": ["chip-maker"],
            "start": 1,
            "duration": 6,
            "delay": 3,
        }
    ]
    scenario["random_disruptions"] = [
        {
            "name": "outage",
            "kind": "supplier_outage",
            "target": ["chip-maker"],
            "chance": "0.0100",
            "duration": 2,
            "strength": "0.5000",
        }
    ]
    scenario["hidden"] = ["disruptions.duration", "suppliers.catalogue.delay"]
    with api_client() as client:
        run = start_run(client, tiny_manifest(), scenario)
        _, observation = get(client, f"/runs/{run['id']}/observation")
        _, second = submit(client, run["id"], 1, [])

    for seen in (observation, second):
        [disruption] = seen["disruptions"]
        assert "duration" not in disruption
        assert disruption["delay"] == 3
    [rule] = run["description"]["scenario"]["random_disruptions"]
    assert "duration" not in rule


def test_a_realized_breakdown_still_shows_its_loss():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(
        breakdown_chance="1.0000", breakdown_loss="0.5000"
    )
    scenario = tiny_scenario()
    scenario["hidden"] = ["lines.breakdown_loss"]
    with api_client() as client:
        run = start_run(client, manifest, scenario)
        _, observation = get(client, f"/runs/{run['id']}/observation")

    [breakdown] = [
        event for event in observation["events"] if event["kind"] == "breakdown"
    ]
    assert breakdown["loss"] == Decimal("0.5")


def test_with_all_nine_hidden_no_route_shows_them_and_the_world_holds_them():
    scenario = tiny_scenario()
    scenario["horizon"] = 10
    scenario["hidden"] = ALL_NINE
    scenario["disruptions"] = [
        {
            "kind": "supplier_outage",
            "target": ["chip-maker"],
            "start": 1,
            "duration": 2,
            "strength": "0.5000",
        }
    ]
    with api_client() as client:
        run = start_run(client, tiny_manifest(), scenario)
        responses: list[Any] = [run, get(client, f"/runs/{run['id']}/observation")[1]]
        for period in range(1, 10):
            responses.append(submit(client, run["id"], period, [])[1])
            responses.append(get(client, f"/runs/{run['id']}/periods")[1])
        submit(client, run["id"], 10, [])
        _, world = get(client, f"/runs/{run['id']}/world")

    paths = [path for response in responses for path in leaves(response)]
    assert ("disruptions", "0", "kind") in paths
    for path in paths:
        description = (
            path[path.index("description") + 1 :] if "description" in path else ()
        )
        assert not is_hidden(description, ALL_NINE)
        assert not shows_a_duration(path)
    parameters = world["parameters"]
    assert parameters["suppliers.chip-maker.catalogue.chip.punctuality"]["value"] == 1
    assert parameters["lines.line-1.breakdown_chance"]["value"] == 0
    assert world["demand"] == {"distributor/monitor": [4] * 10}
    assert world["deliveries"] == {
        "chip-maker/chip": [
            {
                "period": period,
                "punctual": True,
                "delay": 1,
                "completeness": 1,
                "acceptance": 1,
            }
            for period in range(1, 11)
        ]
    }
    assert world["yields"] == {
        "line-1/board": [Decimal("0.9")] * 10,
        "line-1/monitor": [1] * 10,
    }
    assert world["breakdowns"] == {
        "line-1": [
            {"period": period, "breaks": False, "loss": 0} for period in range(1, 11)
        ]
    }
    assert world["disruptions"][0]["duration"] == 2


def test_hidden_delivery_terms_leave_the_delivery_event_as_it_is():
    def delivery_events(hidden: list[str]) -> list[dict[str, Any]]:
        manifest = tiny_manifest()
        entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
        entry.update(completeness="0.9000", acceptance="0.8000")
        scenario = tiny_scenario()
        scenario["hidden"] = hidden
        buy = {"kind": "buy", "supplier": "chip-maker", "material": "chip"}
        with api_client() as client:
            run = start_run(client, manifest, scenario, seed=5)
            for period in range(1, scenario["horizon"] + 1):
                decisions = [buy | {"quantity": "100"}] if period == 1 else []
                submit(client, run["id"], period, decisions)
            _, periods = get(client, f"/runs/{run['id']}/periods")
        return [
            {key: event[key] for key in ("ordered", "arrived", "accepted", "lost")}
            for period_entry in periods["periods"]
            for step in period_entry["steps"]
            for event in step.get("events", [])
            if event["kind"] == "delivery"
        ]

    hidden = [
        "suppliers.catalogue.delay",
        "suppliers.catalogue.completeness",
        "suppliers.catalogue.acceptance",
    ]
    seen = delivery_events([])
    assert seen
    assert delivery_events(hidden) == seen


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_no_response_during_a_run_holds_a_hidden_parameter(
    factory: tuple[dict[str, Any], dict[str, Any]], seed: int, data: st.DataObject
):
    manifest, scenario = factory
    hidden = scenario["hidden"]
    plain_scenario: dict[str, Any] = {**scenario, "hidden": []}
    world = world_of(factory, seed)
    with api_client() as client:
        run = start_run(client, manifest, scenario, seed)
        plain_run = start_run(client, manifest, plain_scenario, seed)
        responses: list[Any] = [get(client, f"/runs/{run['id']}/observation")[1]]
        period = 1
        while not responses[-1].get("finished", False):
            decisions = data.draw(observed_decision_lists(world, responses[-1]))
            _, answer = submit(client, run["id"], period, decisions)
            responses.append(answer)
            period += 1

    described = leaves(run["description"])
    for path in leaves(plain_run["description"]):
        if is_hidden(path, hidden):
            assert path not in described
        elif path[-1:] != ("hidden",) and path[:2] != ("scenario", "hidden"):
            assert described.get(path) == leaves(plain_run["description"])[path]
    if "disruptions.duration" in hidden:
        for response in responses:
            for disruption in response.get("disruptions", []):
                assert "duration" not in disruption
