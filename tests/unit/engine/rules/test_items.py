from decimal import Decimal

import pytest
from factories import (
    draw_world_of_bodies,
    first_period,
    outcome_numbers,
    produce,
    split_lines_across_warehouses,
    tiny_manifest,
    tiny_scenario,
    two_warehouse_manifest,
)

from factory_simulator.api.services.readers.manifest import read_factory
from factory_simulator.engine import (
    InputError,
    World,
    build_state,
    check_factory,
    start_period,
)
from factory_simulator.engine.rules.items import inputs_of, items_of


def plant_world(chips_at: str) -> World:
    manifest = tiny_manifest()
    manifest["warehouses"] = {
        "plant-a": {"capacity": "100.000"},
        "plant-b": {"capacity": "100.000"},
    }
    manifest["lines"]["line-1"]["warehouse"] = "plant-a"
    scenario = tiny_scenario()
    scenario["start"]["stock"] = {chips_at: {"chip": "100"}}
    return draw_world_of_bodies(manifest, scenario)


def test_a_line_takes_its_inputs_from_its_warehouse_and_fills_it():
    board = produce("board", "20")

    elsewhere = first_period(plant_world("plant-b"), [board])
    at_the_line = first_period(plant_world("plant-a"), [board])

    assert outcome_numbers(elsewhere) == [
        (False, "not_enough_input", Decimal("40.000"), Decimal("0.000")),
    ]
    assert outcome_numbers(at_the_line) == [(True, None, None, None)]
    assert at_the_line.stock["plant-a"]["board"] == Decimal("18.000")
    assert at_the_line.stock["plant-b"]["board"] == Decimal(0)


def test_a_warehouse_of_products_starts_with_0_of_each_and_holds_no_material():
    world = draw_world_of_bodies(two_warehouse_manifest(), tiny_scenario())

    state = start_period(build_state(world), world)

    assert state.observation is not None
    assert dict(state.observation.stock["centre"]) == {"monitor": Decimal(0)}
    assert set(state.observation.stock["main"]) == {"board", "chip", "monitor"}


def test_a_component_reaches_a_line_at_another_warehouse_only_along_a_route():
    manifest = tiny_manifest()
    split_lines_across_warehouses(manifest)
    without_route = read_factory(manifest)
    manifest["routes"] = {"main": {"centre": {"cost": "0.2000", "lead_time": 1}}}

    check_factory(read_factory(manifest))
    with pytest.raises(InputError) as refusal:
        check_factory(without_route)
    assert str(refusal.value) == "lines.line-2.warehouse: board is not made at centre"


def test_the_items_of_a_factory_are_its_materials_components_and_products():
    factory = read_factory(tiny_manifest())
    assert sorted(items_of(factory)) == ["board", "chip", "monitor"]


def test_the_inputs_of_a_quantity_are_rounded_up_to_3_places():
    inputs = inputs_of(Decimal("7"), {"chip": Decimal("0.3333")})
    assert inputs == {"chip": Decimal("2.334")}
