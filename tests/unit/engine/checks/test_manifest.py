import copy
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast

import pytest
from factories import (
    MANIFEST_EXAMPLES,
    Change,
    FactoryBodies,
    both,
    changed,
    overtime_wear,
    set_key,
    small_factories,
    tiny_manifest,
    two_recipe_manifest,
)
from hypothesis import given
from hypothesis import strategies as st

from factory_simulator.api.core.json import write_json
from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.services.groups import resolve_groups
from factory_simulator.api.services.readers.manifest import read_factory
from factory_simulator.engine import (
    InputError,
    check_factory,
)

# Keys under these hold identifiers, not fields; renaming one is not an error.
IDENTIFIER_HOLDERS = {
    "materials",
    "components",
    "products",
    "suppliers",
    "catalogue",
    "customers",
    "lines",
    "items",
    "warehouses",
    "recipes",
    "routes",
    "groups",
}


# Keys a manifest may leave out. Deleting one is valid, or is refused at the path of
# the key it goes with, such as `express_cost` without `express_lead_time`.
OPTIONAL_KEYS = {
    "payment_terms",
    "cancellation_fee",
    "backfill_delay",
    "express_lead_time",
    "express_cost",
    "min_quantity",
    "discounts",
    "overtime_hours",
    "overtime_cost",
    "default_recipe",
    "changeover_time",
    "changeover_cost",
    "storage_factor",
    "transport_factor",
    "accepts",
    "routes",
    "groups",
    "defaults",
    "distribution",
    "demand_persistence",
    "common_share",
    "drawn",
}


def read_manifest(body: bytes) -> None:
    check_factory(read_factory(read_json_bytes(body)))


def refusal_message(body: bytes) -> str:
    with pytest.raises(InputError) as refusal:
        read_manifest(body)
    return str(refusal.value)


def refused_path(body: bytes) -> str:
    return refusal_message(body).split(": ")[0]


def field_paths(value: object, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    if not isinstance(value, dict):
        return [path]
    found: list[tuple[str, ...]] = []
    holds_identifiers = bool(path) and (
        path[-1] in IDENTIFIER_HOLDERS or path[-2:-1] in (("recipes",), ("routes",))
    )
    for key, child in cast(dict[str, object], value).items():
        here = (*path, key)
        if not holds_identifiers:
            found.append(here)
        found.extend(below for below in field_paths(child, here) if below != here)
    return found


def is_optional(path: tuple[str, ...], manifest: dict[str, Any]) -> bool:
    if path[-1] == "lead_time" and path[-3:-2] == ("items",):
        return True
    if path[-1] == "warehouse":
        return len(manifest["warehouses"]) == 1
    if path[:1] == ("groups",) and "defaults" in path:
        return True
    return path[-1] in OPTIONAL_KEYS or given_by_a_group(path, manifest)


def given_by_a_group(path: tuple[str, ...], manifest: dict[str, Any]) -> bool:
    document = copy.deepcopy(manifest)
    parent: Any = document
    for part in path[:-1]:
        parent = parent[part]
    del parent[path[-1]]
    try:
        _, given = resolve_groups(document)
    except InputError:
        return False
    return ".".join(path) in given


def broken(manifest: dict[str, Any], path: tuple[str, ...], how: str) -> bytes:
    document = copy.deepcopy(manifest)
    parent: Any = document
    for part in path[:-1]:
        parent = parent[part]
    key = path[-1]
    value = parent[key]
    if how == "delete":
        del parent[key]
    elif how == "rename":
        parent[f"{key}-unknown"] = parent.pop(key)
    elif how == "below":
        parent[key] = -1 if isinstance(value, int) else "-1"
    else:
        whole = isinstance(value, int) or "." not in str(value)
        parent[key] = f"{value}.5" if whole else f"{value}1"
    return write_json(document)


def with_two_customers_of_the_monitor(common_share: str) -> dict[str, Any]:
    manifest = tiny_manifest()
    distributor = manifest["customers"]["distributor"]
    distributor["products"]["monitor"]["demand"] = {"min": "30.000", "max": "50.000"}
    manifest["customers"]["retailer"] = copy.deepcopy(distributor)
    manifest["products"]["monitor"]["common_share"] = common_share
    return manifest


def salvage_manifest(salvage_value: str) -> dict[str, Any]:
    manifest = two_recipe_manifest()
    catalogue = manifest["suppliers"]["chip-maker"]["catalogue"]
    for material_id, price, salvage in (
        ("chip", "5.0000", "3.0000"),
        ("chip-b", "4.0000", "2.0000"),
        ("pcb", "2.0000", "1.0000"),
    ):
        catalogue[material_id]["price"] = price
        manifest["materials"][material_id]["salvage_value"] = salvage
    manifest["lines"]["line-1"]["items"]["board"]["cost"] = "1.5000"
    manifest["components"]["board"]["salvage_value"] = salvage_value
    return manifest


@pytest.mark.parametrize(
    ("change", "message"),
    [(change, message) for _, change, message in MANIFEST_EXAMPLES],
    ids=[name for name, _, _ in MANIFEST_EXAMPLES],
)
def test_an_invalid_manifest_is_refused_with_the_message_of_its_problem(
    change: Change, message: str
):
    assert refusal_message(changed(change)) == message


def test_the_tiny_manifest_passes_every_check():
    read_manifest(copy.deepcopy(write_json(tiny_manifest())))


def test_a_common_share_of_a_product_two_customers_buy_with_a_range_passes():
    read_manifest(write_json(with_two_customers_of_the_monitor("0.5000")))


def test_a_common_share_of_0_passes_for_a_product_with_one_customer():
    manifest = tiny_manifest()
    manifest["products"]["monitor"]["common_share"] = "0.0000"

    read_manifest(write_json(manifest))


def test_a_common_share_may_come_from_a_group_of_products():
    manifest = with_two_customers_of_the_monitor("0.5000")
    del manifest["products"]["monitor"]["common_share"]
    manifest["products"]["monitor"]["groups"] = ["devices"]
    manifest["groups"] = {
        "devices": {
            "kind": "segment",
            "defaults": {"items": {"common_share": "0.5000"}},
        }
    }

    factory = read_factory(read_json_bytes(write_json(manifest)))

    assert factory.products["monitor"].common_share == Decimal("0.5000")
    assert factory.origins["products.monitor.common_share"] == "devices"


def test_a_line_whose_wear_with_overtime_stays_within_its_condition_passes():
    read_manifest(changed(overtime_wear("4.000")))


# A range of overtime hours from 0 to 0 is neither left out nor fixed at 0.
def test_overtime_hours_from_0_to_0_take_an_overtime_cost():
    read_manifest(
        changed(
            both(
                set_key(
                    "lines.line-1.overtime_hours", {"min": "0.000", "max": "0.000"}
                ),
                set_key("lines.line-1.overtime_cost", "1.0000"),
            )
        )
    )


def test_an_item_of_one_recipe_without_a_default_recipe_is_refused_as_required():
    factory = read_factory(tiny_manifest())
    board = replace(factory.components["board"], default_recipe=None)
    factory = replace(factory, components={"board": board})

    with pytest.raises(InputError) as refusal:
        check_factory(factory)

    assert str(refusal.value) == "components.board.default_recipe: Field required"


def test_a_default_recipe_written_as_null_is_filled_with_the_only_recipe():
    manifest = tiny_manifest()
    manifest["components"]["board"]["default_recipe"] = None

    factory = read_factory(read_json_bytes(write_json(manifest)))
    check_factory(factory)

    assert factory.components["board"].default_recipe == "standard"


# An order of patience 0 is lost at the close of its due period without a late penalty.
def test_a_late_penalty_with_a_patience_of_0_is_accepted():
    manifest = tiny_manifest()
    pair = manifest["customers"]["distributor"]["products"]["monitor"]
    pair |= {"patience": 0, "late_penalty": "2.0000"}

    read_manifest(write_json(manifest))


def test_the_salvage_value_of_an_item_is_bounded_by_its_cheapest_recipe():
    check_factory(read_factory(salvage_manifest("6.5000")))

    with pytest.raises(InputError, match=r"^components\.board\.salvage_value: "):
        check_factory(read_factory(salvage_manifest("6.5001")))


def test_payment_terms_below_0_are_refused_at_their_path():
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["payment_terms"] = -1

    with pytest.raises(InputError) as refusal:
        check_factory(read_factory(manifest))

    assert str(refusal.value).startswith("customers.distributor.payment_terms: ")


def test_a_range_of_payment_terms_that_is_not_uniform_is_refused_at_its_path():
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["payment_terms"] = {
        "min": 1,
        "max": 3,
        "distribution": "normal",
        "mean": 2,
        "sd": 1,
    }

    with pytest.raises(InputError) as refusal:
        check_factory(read_factory(manifest))

    assert str(refusal.value).startswith("customers.distributor.payment_terms: ")


@pytest.mark.property
@given(small_factories())
def test_every_generated_manifest_passes_every_check(factory: FactoryBodies):
    read_manifest(write_json(factory[0]))


@pytest.mark.property
@given(small_factories(), st.data())
def test_breaking_any_single_key_is_refused_at_its_path(
    factory: FactoryBodies, data: st.DataObject
):
    manifest = factory[0]
    path = data.draw(st.sampled_from(field_paths(manifest)))
    parent: Any = manifest
    for part in path[:-1]:
        parent = parent[part]
    value = parent[path[-1]]
    # A word, such as `drawn: run`, has no bound or places to break.
    word = isinstance(value, str) and not value.lstrip("-").replace(".", "").isdigit()
    numeric = not isinstance(value, dict) and not word
    ways = ["rename", "below", "places"] if numeric else ["rename"]
    if not is_optional(path, manifest):
        ways.append("delete")
    how = data.draw(st.sampled_from(ways))

    refused = refused_path(broken(manifest, path, how))

    if path[-1] == "groups":
        # Without its groups a member misses the values they gave, wherever they went.
        listed = parent[path[-1]]
        _, given = resolve_groups(manifest)
        missed = [where for where, group_id in given.items() if group_id in listed]
        assert refused.startswith(".".join(path)) or refused in missed
    else:
        assert refused.startswith(".".join(path))
