import copy
from collections.abc import Mapping
from decimal import Decimal

import pytest
from factories import (
    FactoryBodies,
    decide,
    draw_world_of_bodies,
    drawn_run,
    example_count,
    seeds,
    small_factories,
    started,
    tiny_manifest,
    tiny_scenario,
    two_product_manifest,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.engine import (
    MEASURE_KINDS,
    World,
    build_state,
    start_period,
)

# Measures that are neither ratios nor the mean condition.
SUMMED = {
    name
    for name, kind in MEASURE_KINDS.items()
    if kind in ("flow", "level") and name != "condition"
}


def segment_world(orders: list[tuple[str, str]], stock: dict[str, str]) -> World:
    manifest = two_product_manifest()
    manifest["products"]["tablet"]["groups"] = ["new-devices"]
    for terms in manifest["customers"]["distributor"]["products"].values():
        terms["demand"] = "0.000"
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"].update(stock)
    scenario["start"]["customer_orders"] = [
        {"customer": "distributor", "product": product, "quantity": quantity, "due": 1}
        for product, quantity in orders
    ]
    return draw_world_of_bodies(manifest, scenario)


def lines_world(conditions: list[str]) -> World:
    manifest = tiny_manifest()
    line = manifest["lines"]["line-1"]
    line.update(wear_per_period="0.0000", wear_per_hour="0.0000")
    names = [f"line-{number}" for number in range(1, len(conditions) + 1)]
    for name in names:
        manifest["lines"][name] = copy.deepcopy(line) | {"groups": ["fast-lines"]}
    manifest["groups"] = {"fast-lines": {"kind": "tier"}}
    scenario = tiny_scenario()
    scenario["start"]["condition"] = dict(zip(names, conditions, strict=True))
    return draw_world_of_bodies(manifest, scenario)


def member_keys(
    values: Mapping[str, Decimal | None], world: World, group_id: str
) -> list[str]:
    group = world.factory.groups[group_id]
    member_type, members = group.member_type, group.members
    direct = [f"{member_type}.{member}" for member in members]
    if any(key in values for key in direct):
        return [key for key in direct if key in values]
    factory = world.factory
    if member_type == "suppliers":
        keys = [
            f"suppliers.{supplier}/{material}"
            for supplier in members
            for material in factory.materials
        ]
    elif member_type == "lines":
        items = [*factory.components, *factory.products]
        keys = [f"lines.{line}/{item}" for line in members for item in items]
    elif member_type == "customers":
        keys = []
    else:
        places = [f"warehouses.{warehouse}" for warehouse in factory.warehouses]
        places += [f"lines.{line}" for line in factory.lines]
        if member_type == "materials":
            places += [f"suppliers.{supplier}" for supplier in factory.suppliers]
        keys = [f"{place}/{item}" for place in places for item in members]
    return [key for key in keys if key in values]


def test_the_service_of_a_group_divides_its_summed_running_totals():
    world = segment_world(
        [("monitor", "10"), ("tablet", "30")], {"monitor": "7", "tablet": "30"}
    )
    ships = [
        {"kind": "ship", "order": "order-0-1", "quantity": "7"},
        {"kind": "ship", "order": "order-0-2", "quantity": "30"},
    ]

    closed = decide(start_period(build_state(world), world), world, ships)

    assert closed.measures["service"]["groups.new-devices"] == Decimal("0.925")


def test_a_group_with_nothing_past_due_has_no_service():
    world = segment_world([], {})

    closed = decide(start_period(build_state(world), world), world, [])

    assert closed.measures["service"]["groups.new-devices"] is None


def test_a_group_of_materials_sums_the_units_arrived_of_its_members():
    manifest = tiny_manifest()
    manifest["materials"]["chip-b"] = dict(manifest["materials"]["chip"])
    catalogue = manifest["suppliers"]["chip-maker"]["catalogue"]
    catalogue["chip-b"] = dict(catalogue["chip"])
    manifest["materials"]["chip"]["groups"] = ["semiconductor"]
    manifest["materials"]["chip-b"]["groups"] = ["semiconductor"]
    manifest["groups"] = {"semiconductor": {"kind": "category"}}
    world = draw_world_of_bodies(manifest, tiny_scenario())
    buy = {"kind": "buy", "supplier": "chip-maker"}

    second = started(
        world,
        3,
        {
            1: [
                buy | {"material": "chip", "quantity": "50"},
                buy | {"material": "chip-b", "quantity": "30"},
            ]
        },
    )
    closed = decide(second, world, [])

    assert closed.measures["units_arrived"]["groups.semiconductor"] == Decimal(80)


def test_the_condition_of_a_group_of_lines_is_the_mean_of_its_members():
    two = lines_world(["0.9000", "0.7000"])
    three = lines_world(["0.9000", "0.7000", "0.6000"])

    closed = [
        decide(start_period(build_state(world), world), world, [])
        for world in (two, three)
    ]

    assert [state.measures["condition"]["groups.fast-lines"] for state in closed] == [
        Decimal("0.8"),
        Decimal("0.733333333333"),
    ]


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_every_summed_measure_of_a_group_is_the_sum_over_its_members(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world, steps = drawn_run(factory, seed, data.draw)

    for _, _, closed in steps:
        for name in SUMMED & set(closed.measures):
            values = closed.measures[name]
            for group_id in world.factory.groups:
                keys = member_keys(values, world, group_id)
                key = f"groups.{group_id}"
                assert (key in values) == bool(keys)
                if keys:
                    total = sum((Decimal(values[key] or 0) for key in keys), Decimal(0))
                    assert values[key] == total
