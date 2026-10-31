from collections.abc import Mapping
from decimal import Decimal
from typing import Any, cast

import pytest
from factories import (
    FactoryBodies,
    decide,
    draw_world_of_bodies,
    drawn_run,
    example_count,
    grouped,
    groups_written_out,
    seeds,
    small_factories,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from factory_simulator.api.core.json import write_json
from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.services.groups import resolve_groups
from factory_simulator.api.services.readers.manifest import (
    read_factory,
    resolve_manifest,
    to_factory,
    written_content,
)
from factory_simulator.api.services.writers.world import world_json
from factory_simulator.engine import (
    Factory,
    InputError,
    build_state,
    check_factory,
    start_period,
)

CHIP = "suppliers.chip-maker.catalogue.chip"


PAIR = "customers.distributor.products.monitor"


def grouped_line_items(line_cost: str | None, board_cost: str | None) -> dict[str, Any]:
    manifest = tiny_manifest()
    groups: dict[str, Any] = {}
    if line_cost is not None:
        groups["fast-lines"] = {
            "kind": "tier",
            "defaults": {"line_items": {"cost": line_cost}},
        }
        manifest["lines"]["line-1"]["groups"] = ["fast-lines"]
    if board_cost is not None:
        groups["boards"] = {
            "kind": "family",
            "defaults": {"line_items": {"cost": board_cost}},
        }
        manifest["components"]["board"]["groups"] = ["boards"]
    manifest["groups"] = groups
    return manifest


def cost_and_origin(factory: Factory) -> tuple[object, str]:
    path = "lines.line-1.items.board.cost"
    return factory.lines["line-1"].items["board"].cost, factory.origins[path]


def with_groups(groups: dict[str, Any], **listed: list[str]) -> dict[str, Any]:
    manifest = tiny_manifest()
    grouped(groups, **listed)(manifest)
    return manifest


def without(manifest: dict[str, Any], path: str) -> dict[str, Any]:
    *parents, key = path.split(".")
    parent: Any = manifest
    for part in parents:
        parent = parent[part]
    del parent[key]
    return manifest


def catalogue_group(lead_time: int, kind: str = "region") -> dict[str, Any]:
    return {"kind": kind, "defaults": {"catalogue": {"lead_time": lead_time}}}


def semiconductor_centre(main_accepts: list[Any]) -> dict[str, Any]:
    manifest = tiny_manifest()
    grouped({"semiconductor": {"kind": "category"}}, materials__chip=["semiconductor"])(
        manifest
    )
    manifest["warehouses"]["main"]["accepts"] = main_accepts
    manifest["warehouses"]["centre"] = {
        "capacity": "50.000",
        "accepts": [{"group": "semiconductor"}],
    }
    manifest["lines"]["line-1"]["warehouse"] = "main"
    return manifest


def leaves(value: object, path: str = "") -> dict[str, object]:
    if isinstance(value, dict):
        found: dict[str, object] = {}
        for key, child in cast(dict[str, object], value).items():
            found |= leaves(child, f"{path}.{key}" if path else key)
        return found
    return {path: value}


def without_group_keys(measures: Mapping[str, Mapping[str, object]]) -> object:
    return {
        name: {
            key: value for key, value in values.items() if not key.startswith("groups.")
        }
        for name, values in measures.items()
    }


def test_a_line_item_takes_its_written_cost_then_the_line_group_then_the_item_group():
    written = grouped_line_items("2.0000", "1.5000")
    without_cost = grouped_line_items("2.0000", "1.5000")
    del without_cost["lines"]["line-1"]["items"]["board"]["cost"]
    item_group = grouped_line_items(None, "1.5000")
    del item_group["lines"]["line-1"]["items"]["board"]["cost"]
    no_group = grouped_line_items(None, None)
    del no_group["lines"]["line-1"]["items"]["board"]["cost"]

    assert cost_and_origin(read_factory(written)) == (Decimal("1.0000"), "written")
    assert cost_and_origin(read_factory(without_cost)) == (
        Decimal("2.0000"),
        "fast-lines",
    )
    assert cost_and_origin(read_factory(item_group)) == (Decimal("1.5000"), "boards")
    with pytest.raises(InputError, match=r"^lines\.line-1\.items\.board\.cost: "):
        read_factory(no_group)


def test_a_customer_product_takes_the_defaults_of_the_product_group():
    segment = {
        "kind": "segment",
        "defaults": {"customer_products": {"lead_time": 1, "late_penalty": "8.0000"}},
    }
    manifest = with_groups({"new-devices": segment}, products__monitor=["new-devices"])
    without(manifest, f"{PAIR}.lead_time")
    without(manifest, f"{PAIR}.late_penalty")

    factory = read_factory(manifest)

    terms = factory.customers["distributor"].products["monitor"]
    assert (terms.lead_time, terms.late_penalty) == (1, Decimal("8.0000"))
    assert factory.origins[f"{PAIR}.late_penalty"] == "new-devices"


def test_a_customer_product_asks_the_customer_groups_before_the_product_groups():
    key_accounts = {
        "kind": "tier",
        "defaults": {"customer_products": {"late_penalty": "5.0000"}},
    }
    new_devices = {
        "kind": "segment",
        "defaults": {"customer_products": {"late_penalty": "8.0000"}},
    }
    manifest = with_groups(
        {"key-accounts": key_accounts, "new-devices": new_devices},
        customers__distributor=["key-accounts"],
        products__monitor=["new-devices"],
    )
    without(manifest, f"{PAIR}.late_penalty")

    factory = read_factory(manifest)

    terms = factory.customers["distributor"].products["monitor"]
    assert terms.late_penalty == Decimal("5.0000")
    assert factory.origins[f"{PAIR}.late_penalty"] == "key-accounts"


def test_a_catalogue_entry_asks_the_supplier_groups_before_the_material_groups():
    material_only = with_groups(
        {"semiconductor": catalogue_group(3, "category")},
        materials__chip=["semiconductor"],
    )
    both_groups = with_groups(
        {"semiconductor": catalogue_group(3, "category"), "apac": catalogue_group(4)},
        materials__chip=["semiconductor"],
        suppliers__chip_maker=["apac"],
    )
    for manifest in (material_only, both_groups):
        without(manifest, f"{CHIP}.lead_time")

    first = read_factory(material_only)
    second = read_factory(both_groups)

    assert first.origins[f"{CHIP}.lead_time"] == "semiconductor"
    assert second.suppliers["chip-maker"].catalogue["chip"].lead_time == 4
    assert second.origins[f"{CHIP}.lead_time"] == "apac"


def test_the_groups_of_an_object_give_defaults_in_the_order_it_lists_them():
    manifest = with_groups(
        {"apac": catalogue_group(4), "chip-makers": catalogue_group(3, "industry")},
        suppliers__chip_maker=["chip-makers", "apac"],
    )
    without(manifest, f"{CHIP}.lead_time")

    factory = read_factory(manifest)

    assert factory.suppliers["chip-maker"].catalogue["chip"].lead_time == 3
    assert factory.origins[f"{CHIP}.lead_time"] == "chip-makers"


def test_a_parameter_left_out_everywhere_has_its_built_in_default():
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario())

    parameters = cast(dict[str, dict[str, object]], world_json(world)["parameters"])

    assert parameters[f"{CHIP}.backfill_delay"] == {
        "value": Decimal(0),
        "origin": "default",
        "drawn": False,
    }
    assert parameters[f"{CHIP}.price"]["origin"] == "written"


def test_a_range_given_by_a_group_is_drawn_for_every_member_from_its_own_stream():
    manifest = tiny_manifest()
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    del entry["punctuality"]
    manifest["suppliers"]["display-maker"] = {"catalogue": {"chip": dict(entry)}}
    punctuality_range = {"min": "0.8000", "max": "0.9200"}
    apac = {
        "kind": "region",
        "defaults": {"catalogue": {"punctuality": punctuality_range}},
    }
    grouped(
        {"apac": apac},
        suppliers__chip_maker=["apac"],
        suppliers__display_maker=["apac"],
    )(manifest)

    world = draw_world_of_bodies(manifest, tiny_scenario(), seed=3)

    parameters = cast(dict[str, dict[str, object]], world_json(world)["parameters"])
    paths = [
        f"suppliers.{supplier}.catalogue.chip.punctuality"
        for supplier in ("chip-maker", "display-maker")
    ]
    for path in paths:
        assert parameters[path]["origin"] == "apac"
        assert parameters[path]["drawn"] is True
        assert Decimal("0.8000") <= world.parameters[path] <= Decimal("0.9200")
    assert world.parameters[paths[0]] != world.parameters[paths[1]]


def test_a_warehouse_accepting_a_group_holds_its_members_only():
    manifest = tiny_manifest()
    manifest["materials"]["steel"] = dict(manifest["materials"]["chip"])
    catalogue = manifest["suppliers"]["chip-maker"]["catalogue"]
    catalogue["steel"] = dict(catalogue["chip"])
    semiconductor = {"kind": "category"}
    grouped({"semiconductor": semiconductor}, materials__chip=["semiconductor"])(
        manifest
    )
    manifest["warehouses"]["centre"] = {
        "capacity": "50.000",
        "accepts": [{"group": "semiconductor"}],
    }
    manifest["lines"]["line-1"]["warehouse"] = "main"
    world = draw_world_of_bodies(manifest, tiny_scenario())
    buy = {
        "kind": "buy",
        "supplier": "chip-maker",
        "quantity": "1",
        "warehouse": "centre",
    }

    state = decide(
        start_period(build_state(world), world),
        world,
        [buy | {"material": "chip"}, buy | {"material": "steel"}],
    )

    assert [(outcome.accepted, outcome.reason) for outcome in state.outcomes] == [
        (True, None),
        (False, "not_accepted"),
    ]


def test_a_warehouse_that_accepts_only_a_group_passes_the_checks():
    manifest = semiconductor_centre(["materials", "components", "products"])

    factory = read_factory(manifest)
    check_factory(factory)

    assert factory.warehouses["centre"].accepted_groups == ("semiconductor",)


def test_a_material_accepted_only_through_a_group_has_a_warehouse():
    manifest = semiconductor_centre(
        ["components", "products", {"group": "semiconductor"}]
    )

    factory = read_factory(manifest)
    check_factory(factory)

    assert factory.warehouses["main"].accepts == ("components", "products")


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(small_factories())
def test_group_defaults_never_override_a_written_value(bodies: FactoryBodies):
    manifest = bodies[0]

    filled, _ = resolve_groups(manifest)

    written = leaves(manifest)
    assert {path: leaves(filled)[path] for path in written} == written


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(defaults_only=True), seeds, st.data())
def test_a_factory_with_groups_runs_as_the_same_factory_written_out(
    bodies: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = bodies
    world, steps = drawn_run(bodies, seed, data.draw)
    flat = draw_world_of_bodies(groups_written_out(manifest), scenario, seed=seed)

    assert dict(flat.parameters) == dict(world.parameters)
    state = build_state(flat)
    for _, decisions, closed in steps:
        state = decide(start_period(state, flat), flat, decisions)
        assert state.ledger == closed.ledger
        assert without_group_keys(state.measures) == without_group_keys(closed.measures)


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(small_factories(), seeds)
def test_a_value_drawn_from_a_group_range_lies_within_it(
    bodies: FactoryBodies, seed: int
):
    manifest, scenario = bodies
    world = draw_world_of_bodies(manifest, scenario, seed=seed)
    groups = manifest.get("groups", {})

    for path, origin in world.factory.origins.items():
        if origin == "written" or path not in world.drawn:
            continue
        name = path.rsplit(".", 1)[-1]
        defaults = [
            values[name]
            for values in groups[origin]["defaults"].values()
            if name in values
        ]
        low, high = Decimal(defaults[0]["min"]), Decimal(defaults[0]["max"])
        value = world.parameters[path]
        assert low <= value <= high
        assert value == value.quantize(Decimal(defaults[0]["min"]))


@pytest.mark.property
@settings(
    max_examples=example_count(100),
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
@given(small_factories(), seeds, st.data())
def test_adding_a_member_to_a_group_leaves_the_draws_of_the_others(
    bodies: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = bodies
    groups = manifest.get("groups", {})
    candidates = [
        (group_id, supplier_id)
        for group_id in groups
        if group_id.startswith("suppliers-")
        for supplier_id, supplier in manifest["suppliers"].items()
        if group_id not in supplier.get("groups", [])
        and all(
            groups[other]["kind"] != groups[group_id]["kind"]
            for other in supplier.get("groups", [])
        )
    ]
    assume(candidates)
    group_id, supplier_id = data.draw(st.sampled_from(candidates))
    before = draw_world_of_bodies(manifest, scenario, seed=seed)
    supplier = manifest["suppliers"][supplier_id]
    supplier["groups"] = [*supplier.get("groups", []), group_id]
    after = draw_world_of_bodies(manifest, scenario, seed=seed)

    changed_prefix = f"suppliers.{supplier_id}."
    assert {
        path: value
        for path, value in after.parameters.items()
        if not path.startswith(changed_prefix)
    } == {
        path: value
        for path, value in before.parameters.items()
        if not path.startswith(changed_prefix)
    }


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(small_factories())
def test_a_manifest_with_groups_reads_back_as_the_same_model(bodies: FactoryBodies):
    model, origins = resolve_manifest(bodies[0])
    check_factory(to_factory(model, origins))

    content = written_content(model, origins)
    again, _ = resolve_manifest(read_json_bytes(write_json(content)))

    assert again == model
