import copy
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from factories import (
    FactoryBodies,
    RunStep,
    decide,
    demand_shapes,
    draw_world_of_bodies,
    drawn_run,
    example_count,
    seeds,
    small_factories,
    started,
    tiny_manifest,
    tiny_scenario,
    to_engine,
    two_product_manifest,
)
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from factory_simulator.engine import (
    Group,
    State,
    World,
    build_state,
    start_period,
)
from factory_simulator.engine.rules.disruptions import active_disruptions
from factory_simulator.engine.rules.targets import targets_in

GROUP_DISRUPTIONS = {
    "supplier_outage": ("suppliers", {"strength": "0.5000"}),
    "quality_drop": ("suppliers", {"strength": "0.5000"}),
    "transport_delay": ("suppliers", {"delay": "2"}),
    "demand_shock": ("products", {"factor": "1.5000"}),
    "line_breakdown": ("lines", {"loss": "0.5000"}),
    "capacity_cut": ("lines", {"strength": "0.5000"}),
    "yield_drop": ("lines", {"strength": "0.5000"}),
}


def ordered(state: State) -> dict[str, Decimal]:
    return {
        str(event["product"]): Decimal(str(event["quantity"]))
        for event in state.period_events
        if event["kind"] == "customer_order"
    }


def ordered_pairs(state: State) -> dict[tuple[str, str], Decimal]:
    return {
        (str(event["customer"]), str(event["product"])): Decimal(str(event["quantity"]))
        for event in state.period_events
        if event["kind"] == "customer_order"
    }


def regions() -> dict[str, Any]:
    manifest = tiny_manifest()
    suppliers = manifest["suppliers"]
    entry = suppliers["chip-maker"]["catalogue"]["chip"]
    entry["acceptance"] = "0.9800"
    for supplier_id in ("display-maker", "emea-maker"):
        suppliers[supplier_id] = copy.deepcopy(suppliers["chip-maker"])
    suppliers["emea-maker"]["catalogue"]["chip"]["acceptance"] = "1.0000"
    suppliers["chip-maker"]["groups"] = ["apac"]
    suppliers["display-maker"]["groups"] = ["apac"]
    manifest["groups"] = {"apac": {"kind": "region"}}
    return manifest


def without_groups(measures: Mapping[str, Mapping[str, object]]) -> object:
    return {
        name: {
            key: value for key, value in values.items() if not key.startswith("groups.")
        }
        for name, values in measures.items()
    }


# Assert that the decisions of a run played in another world give the same
# observations, ledger and measures, groups left out.
def assert_same_run(steps: list[RunStep], other: World) -> None:
    state = build_state(other)
    for decided, decisions, closed in steps:
        state = start_period(state, other)
        assert state.observation == decided.observation
        state = decide(state, other, decisions)
        assert state.ledger == closed.ledger
        assert without_groups(state.measures) == without_groups(closed.measures)


def orders_of_run(world: World) -> list[tuple[str, Decimal]]:
    state = build_state(world)
    found: list[tuple[str, Decimal]] = []
    while not state.finished:
        state = start_period(state, world)
        found += [
            (str(event["product"]), Decimal(str(event["quantity"])))
            for event in state.period_events
            if event["kind"] == "customer_order"
        ]
        state = decide(state, world, [])
    return found


def effects(kind: str, object_id: str, period: int, world: World) -> list[Decimal]:
    return [
        disruption.effect
        for disruption in active_disruptions(kind, object_id, period, world)
    ]


def test_a_demand_shape_targeting_a_segment_acts_on_its_members_only():
    scenario = tiny_scenario()
    scenario["demand_shapes"] = [
        {
            "kind": "step",
            "target": {"segment": "new-devices"},
            "period": 3,
            "factor": "1.5000",
        }
    ]
    world = draw_world_of_bodies(two_product_manifest(), scenario)

    third = started(world, 3, {})

    assert ordered(third) == {"monitor": Decimal("60.000"), "tablet": Decimal("40.000")}


def test_a_shape_of_a_group_of_products_leaves_a_customer_of_the_same_name():
    manifest = two_product_manifest()
    pairs = manifest["customers"]["distributor"]["products"]
    manifest["customers"]["monitor"] = {"products": {"tablet": dict(pairs["tablet"])}}
    scenario = tiny_scenario()
    scenario["demand_shapes"] = [
        {
            "kind": "step",
            "target": {"segment": "new-devices"},
            "period": 3,
            "factor": "1.5000",
        }
    ]
    world = draw_world_of_bodies(manifest, scenario)

    third = started(world, 3, {})

    assert ordered_pairs(third) == {
        ("distributor", "monitor"): Decimal("60.000"),
        ("distributor", "tablet"): Decimal("40.000"),
        ("monitor", "tablet"): Decimal("40.000"),
    }


def test_an_outage_targeting_a_region_cuts_the_deliveries_of_its_members():
    scenario = tiny_scenario()
    scenario["horizon"] = 4
    scenario["disruptions"] = [
        {
            "kind": "supplier_outage",
            "target": {"region": "apac"},
            "start": 3,
            "duration": 1,
            "strength": "0.8000",
        }
    ]
    world = draw_world_of_bodies(regions(), scenario)
    buys = [
        {"kind": "buy", "supplier": supplier, "material": "chip", "quantity": "100"}
        for supplier in ("chip-maker", "display-maker", "emea-maker")
    ]

    third = started(world, 3, {1: buys})

    deliveries = {
        str(event["reference"]): (event["arrived"], event["accepted"])
        for event in third.period_events
        if event["kind"] == "delivery"
    }
    assert deliveries == {
        "buy-1-1": (Decimal("20.000"), Decimal("19.600")),
        "buy-1-2": (Decimal("20.000"), Decimal("19.600")),
        "buy-1-3": (Decimal("100.000"), Decimal("100.000")),
    }


def test_the_members_of_a_group_are_targeted_in_identifier_order():
    group = Group(kind="region", members=("b", "a"), member_type="lines")
    factory = to_engine(tiny_manifest(), tiny_scenario())[0]
    factory = replace(factory, groups={"west": group})

    assert targets_in("line_breakdown", None, ("region", "west"), factory) == (
        "a",
        "b",
    )


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_a_target_of_a_group_acts_as_its_members_written_out(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    groups = manifest.get("groups", {})

    def members_of(target: dict[str, str]) -> list[str]:
        [group_id] = target.values()
        kind = group_id.split("-")[0]
        return sorted(
            object_id
            for object_id, made in manifest[kind].items()
            if group_id in made.get("groups", [])
        )

    shapes = [
        shape
        for shape in scenario.get("demand_shapes", [])
        if isinstance(shape["target"], dict)
        and set(shape["target"]) - {"customer", "product"}
    ]
    disruptions = [
        disruption
        for disruption in scenario.get("disruptions", [])
        if isinstance(disruption["target"], dict)
    ]
    assume(groups and (shapes or disruptions))
    _, steps = drawn_run(factory, seed, data.draw)
    written = copy.deepcopy(scenario)
    written_shapes: list[dict[str, Any]] = []
    for shape in scenario.get("demand_shapes", []):
        if shape in shapes:
            written_shapes += [
                shape | {"target": {"product": member}}
                for member in members_of(shape["target"])
            ]
        else:
            written_shapes.append(shape)
    written["demand_shapes"] = written_shapes
    for number, disruption in enumerate(scenario.get("disruptions", [])):
        if disruption in disruptions:
            written["disruptions"][number] = disruption | {
                "target": members_of(disruption["target"])
            }
    other = draw_world_of_bodies(manifest, written, seed=seed)

    assert_same_run(steps, other)


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_a_shape_of_a_group_leaves_the_demand_outside_it(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    groups = manifest.get("groups", {})
    product_groups = sorted(
        group_id for group_id in groups if group_id.startswith("products-")
    )
    assume(product_groups)
    group_id = data.draw(st.sampled_from(product_groups))
    shape = data.draw(
        demand_shapes(
            scenario["horizon"],
            sorted(manifest["customers"]),
            sorted(manifest["products"]),
        )
    )
    shape["target"] = {groups[group_id]["kind"]: group_id}
    shaped_scenario = copy.deepcopy(scenario)
    shaped_scenario["demand_shapes"] = [*scenario.get("demand_shapes", []), shape]
    members = {
        product_id
        for product_id, product in manifest["products"].items()
        if group_id in product.get("groups", [])
    }

    shaped = orders_of_run(draw_world_of_bodies(manifest, shaped_scenario, seed=seed))
    plain = orders_of_run(draw_world_of_bodies(manifest, scenario, seed=seed))

    outside = [order for order in shaped if order[0] not in members]
    assert outside == [order for order in plain if order[0] not in members]


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_a_disruption_of_a_group_leaves_the_objects_outside_it(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    groups = manifest.get("groups", {})
    kinds = [
        kind
        for kind, (member_type, _) in GROUP_DISRUPTIONS.items()
        if any(group_id.startswith(f"{member_type}-") for group_id in groups)
    ]
    assume(kinds)
    kind = data.draw(st.sampled_from(kinds))
    member_type, effect = GROUP_DISRUPTIONS[kind]
    group_id = data.draw(
        st.sampled_from(
            sorted(
                group_id
                for group_id in groups
                if group_id.startswith(f"{member_type}-")
            )
        )
    )
    written = {
        "kind": kind,
        "target": {groups[group_id]["kind"]: group_id},
        "start": 1,
    } | effect
    if kind != "line_breakdown":
        written["duration"] = scenario["horizon"]
    disrupted_scenario = copy.deepcopy(scenario)
    disrupted_scenario["disruptions"] = [*scenario.get("disruptions", []), written]
    disrupted = draw_world_of_bodies(manifest, disrupted_scenario, seed=seed)
    plain = draw_world_of_bodies(manifest, scenario, seed=seed)

    members = set(disrupted.factory.groups[group_id].members)
    outside = set(getattr(disrupted.factory, member_type)) - members
    for object_id in outside:
        for period in range(1, scenario["horizon"] + 1):
            assert effects(kind, object_id, period, disrupted) == effects(
                kind, object_id, period, plain
            )
    for object_id in members:
        assert effects(kind, object_id, 1, disrupted) != effects(
            kind, object_id, 1, plain
        )
