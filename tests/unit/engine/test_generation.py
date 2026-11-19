import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from factories import generator_counts, seeds
from hypothesis import given

from factory_simulator.api.core.json import write_json
from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.services.examples import EXAMPLES
from factory_simulator.api.services.groups import resolve_groups
from factory_simulator.engine import (
    InputError,
    build_economic_profile,
    generate_manifest,
    open_stream,
)
from factory_simulator.engine.generation import (
    GENERATOR_HALF_WIDTHS,
    GENERATOR_RANGES,
    MATCHED_PRICE_RATIOS,
    Economy,
    draw_line,
    line_capacity,
    material_salvage,
    second_source,
)

SMALL = {
    "materials": 3,
    "components": 2,
    "products": 2,
    "suppliers": 2,
    "customers": 2,
    "lines": 2,
}


FROZEN = Path(__file__).parent / "frozen-generated-manifest.json"


FROZEN_COUNTS = {
    "materials": 4,
    "components": 3,
    "products": 2,
    "suppliers": 2,
    "customers": 2,
    "lines": 2,
}


# The row of `GENERATOR_RANGES` of every drawn key, by the kind of object that holds it.
DRAWN_ROWS = {
    "catalogue": ("punctuality", "delay", "completeness", "acceptance"),
    "customer_products": (
        "price",
        "transport_cost",
        "demand",
        "lead_time",
        "patience",
        "late_penalty",
        "lost_sale_penalty",
    ),
    "lines": (
        "wear_per_period",
        "breakdown_chance",
        "breakdown_loss",
        "repair_cost",
        "repair_time",
        "repair_limit",
    ),
    "line_items": ("time", "cost", "yield"),
}


# Generate a manifest in a process of its own, whose text hashes with a hash seed.
GENERATE = """
import json, sys
from factory_simulator.api.core.json import write_json
from factory_simulator.engine import generate_manifest
counts, seed, economy = json.loads(sys.argv[1])
sys.stdout.buffer.write(write_json(generate_manifest(counts, seed, economy)))
"""


def first_draw(seed: int, path: str) -> Decimal:
    return Decimal(repr(open_stream(seed, "generator", path).random()))


# Every value of a parameter in the example, its groups resolved, by the row it
# belongs to; a range gives both bounds.
def example_values() -> dict[str, list[dict[str, Any] | str | int]]:
    document = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    manifest = cast(dict[str, Any], resolve_groups(document)[0])
    values: dict[str, list[dict[str, Any] | str | int]] = {}

    def add(row: str, value: dict[str, Any] | str | int) -> None:
        values.setdefault(row, []).append(value)

    for kind in ("materials", "components", "products"):
        for item in manifest[kind].values():
            add(f"{kind}.space", item["space"])
    for supplier in manifest["suppliers"].values():
        for entry in supplier["catalogue"].values():
            for key, value in entry.items():
                add(f"catalogue.{key}", value)
    for customer in manifest["customers"].values():
        for pair in customer["products"].values():
            for key, value in pair.items():
                add(f"customer_products.{key}", value)
    for line in manifest["lines"].values():
        for key, value in line.items():
            if key != "items":
                add(f"lines.{key}", value)
        for item in line["items"].values():
            for key, value in item.items():
                add(f"line_items.{key}", value)
    for key, value in manifest["cash"].items():
        add(f"cash.{key}", value)
    return values


def bounds_of(value: dict[str, Any] | str | int) -> list[Decimal]:
    if isinstance(value, dict):
        return [Decimal(str(value["min"])), Decimal(str(value["max"]))]
    return [Decimal(str(value))]


def frozen_text() -> bytes:
    return write_json(generate_manifest(FROZEN_COUNTS, 0)) + b"\n"


def frozen_manifest() -> dict[str, Any]:
    return cast(dict[str, Any], read_json_bytes(FROZEN.read_bytes()))


def assert_within(row: str, value: dict[str, Any] | str | int) -> None:
    smallest, largest = GENERATOR_RANGES[row]
    for bound in bounds_of(value):
        assert Decimal(smallest) <= bound <= Decimal(largest), row


def test_the_structure_follows_the_counts_and_the_draws_of_the_choices():
    manifest: dict[str, Any] = generate_manifest(SMALL, 0)

    assert list(manifest["lines"]["line-1"]["items"]) == ["component-1", "product-1"]
    assert list(manifest["lines"]["line-2"]["items"]) == ["component-2", "product-2"]
    second = {
        material: first_draw(0, f"materials.{material}.second_source") < Decimal("0.3")
        for material in ("material-1", "material-2", "material-3")
    }
    sold_by_1 = {"material-1", "material-3"}
    if second["material-2"]:
        sold_by_1.add("material-2")
    sold_by_2 = {"material-2"} | {
        material for material in ("material-1", "material-3") if second[material]
    }
    assert set(manifest["suppliers"]["supplier-1"]["catalogue"]) == sold_by_1
    assert set(manifest["suppliers"]["supplier-2"]["catalogue"]) == sold_by_2
    customers = manifest["customers"]
    assert {"product-1"} <= set(customers["customer-1"]["products"])
    assert {"product-2"} <= set(customers["customer-2"]["products"])
    for customer, product in (("customer-1", "product-2"), ("customer-2", "product-1")):
        draw = first_draw(0, f"customers.{customer}.products.{product}")
        assert (product in customers[customer]["products"]) == (draw < Decimal("0.5"))
    assert list(manifest["warehouses"]) == ["plant"]
    assert manifest["name"] == "Generated factory"


def test_every_supplier_and_customer_gets_an_entry_when_they_outnumber_the_items():
    counts = SMALL | {"materials": 1, "products": 1, "suppliers": 3, "customers": 3}

    manifest: dict[str, Any] = generate_manifest(counts, 0)

    for supplier in manifest["suppliers"].values():
        assert list(supplier["catalogue"]) == ["material-1"]
    for customer in manifest["customers"].values():
        assert list(customer["products"]) == ["product-1"]


def test_a_line_needing_60_hours_gets_71_hours_of_capacity():
    assert line_capacity(Decimal("60.000")) == Decimal("71.000")


def test_a_material_at_2_4_keeps_0_96_as_salvage():
    assert material_salvage(Decimal("2.4000")) == Decimal("0.9600")


def test_a_second_source_is_15_percent_dearer_and_one_period_faster_down_to_1():
    assert second_source(Decimal("2.4000"), 2) == (Decimal("2.7600"), 1)
    assert second_source(Decimal("2.4000"), 1) == (Decimal("2.7600"), 1)


def test_every_row_of_the_table_is_the_smallest_and_largest_value_of_the_example():
    values = example_values()

    for row, (smallest, largest) in GENERATOR_RANGES.items():
        found = [bound for value in values[row] for bound in bounds_of(value)]
        assert (Decimal(smallest), Decimal(largest)) == (min(found), max(found)), row


def test_every_half_width_is_the_middle_of_those_of_the_example_ranges():
    values = example_values()
    ranged = {
        row
        for row in GENERATOR_RANGES
        if any(isinstance(value, dict) for value in values[row])
    }

    assert set(GENERATOR_HALF_WIDTHS) == ranged
    for row in ranged:
        widths = [
            (high - low) / (high + low)
            for low, high in (
                bounds_of(value) for value in values[row] if isinstance(value, dict)
            )
        ]
        middle = ((min(widths) + max(widths)) / 2).quantize(Decimal("0.0001"))
        assert GENERATOR_HALF_WIDTHS[row] == middle, row


def test_the_frozen_generated_manifest_is_generated_byte_for_byte_the_same():
    assert frozen_text() == FROZEN.read_bytes()


def test_a_second_source_of_the_frozen_manifest_is_dearer_and_one_period_faster():
    suppliers = frozen_manifest()["suppliers"]

    first = suppliers["supplier-1"]["catalogue"]["material-3"]
    second = suppliers["supplier-2"]["catalogue"]["material-3"]

    assert (first["price"], first["lead_time"]) == (
        {"min": "39.4311", "max": "45.6000"},
        {"min": 1, "max": 1},
    )
    # 39.4311 * 1.15 = 45.345765, half to even 45.3458; 45.6000 * 1.15 = 52.4400. The
    # lead time 1 - 1 = 0 is raised to 1.
    assert (second["price"], second["lead_time"]) == (
        {"min": "45.3458", "max": "52.4400"},
        {"min": 1, "max": 1},
    )


def test_the_storage_cost_of_the_frozen_manifest_is_a_share_of_the_value_held():
    manifest = frozen_manifest()

    # 0.005 * 39.4311 = 0.1971555 and 0.005 * (39.4311 + 8.4857) = 0.239584.
    assert manifest["materials"]["material-3"]["storage_cost"] == "0.1972"
    assert manifest["components"]["component-1"]["storage_cost"] == "0.2396"


def test_the_max_quantity_of_the_frozen_manifest_covers_twice_the_need_or_1():
    suppliers = frozen_manifest()["suppliers"]

    # 2 * ((78.536 + 80.000) + 51.712) = 420.496, rounded up; no recipe holds
    # material-4, so its need is 0 and its max quantity at least 1.
    assert [
        suppliers[supplier]["catalogue"][material]["max_quantity"]
        for material in ("material-3", "material-4")
        for supplier in ("supplier-1", "supplier-2")
    ] == ["421.000", "421.000", "1.000", "1.000"]


def test_the_plant_and_the_credit_limit_of_the_frozen_manifest_follow_the_needs():
    manifest = frozen_manifest()

    # Space of 3 periods of every need 39.364857, of the materials over their longest
    # lead time 5.763399 and of 1 period of the made items 9.864084:
    # 54.992340 / 0.75 = 73.32312, rounded up.
    assert manifest["warehouses"]["plant"]["capacity"] == "73.324"
    # 2 * (120.5180 * 51.220 + 165.9913 * 53.191 + 193.0771 * 33.726)
    # = 43027.7869458, half to even.
    assert manifest["cash"]["credit_limit"] == "43027.7869"


def test_a_line_gets_its_capacity_and_a_wear_per_hour_that_lasts_a_period():
    small = draw_line("line-1", Decimal(60), 0)
    large = draw_line("line-1", Decimal(3000), 0)

    assert (small["capacity"], small["wear_per_period"], small["wear_per_hour"]) == (
        Decimal("71.000"),
        Decimal("0.0049"),
        Decimal("0.0005"),
    )
    # The drawn 0.0005 is cut to (1 - 0.0049) / 3530 = 0.000282, rounded down.
    assert (large["capacity"], large["wear_per_hour"]) == (
        Decimal("3530.000"),
        Decimal("0.0002"),
    )


def test_a_matched_price_is_the_lowest_cost_times_a_ratio_drawn_from_the_example():
    counts = dict.fromkeys(SMALL, 1)

    manifest: dict[str, Any] = generate_manifest(counts, 0, "matched")

    pair = manifest["customers"]["customer-1"]["products"]["product-1"]
    # The draw 0.136808 of the price gives 120.5180 in the unrestricted economy and
    # the ratio 1.8124 + 0.6126 * 0.136808 = 1.8962 here; the lowest cost is
    # 16.7208 + 8.4857 + 10.1711 = 35.3776, and 35.3776 * 1.8962 = 67.08300512.
    assert pair["price"] == "67.0830"
    assert generate_manifest(counts, 0)["customers"] == {
        "customer-1": {"products": {"product-1": pair | {"price": "120.5180"}}}
    }
    # 2 * 67.0830 * (23.904 + 78.536) / 2 = 6871.98252, half to even.
    assert manifest["cash"]["credit_limit"] == "6871.9825"
    assert manifest["description"] == (
        "Generated from 1 materials, 1 components, 1 products, 1 suppliers, "
        "1 customers, 1 lines with seed 0 and matched prices."
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"lines": 0}, "lines: must be at least 1"),
        ({"materials": 0}, "materials: must be at least 1"),
        (
            {"components": 1, "products": 1, "lines": 3},
            "lines: must be at most components + products",
        ),
    ],
)
def test_counts_outside_their_bounds_are_refused(changes: dict[str, int], message: str):
    with pytest.raises(InputError) as refusal:
        generate_manifest(SMALL | changes, 0)

    assert str(refusal.value) == message


@pytest.mark.slow
@pytest.mark.parametrize("economy", ["unrestricted", "matched"])
def test_the_same_counts_and_seed_give_the_same_manifest_under_every_hash_seed(
    economy: Economy,
):
    counts = SMALL | {"materials": 6, "suppliers": 3, "customers": 3}
    arguments = json.dumps([counts, 7, economy])
    source = str(Path(__file__).resolve().parents[3] / "src")
    python_path = os.pathsep.join(
        part for part in (source, os.environ.get("PYTHONPATH", "")) if part
    )

    generated = [
        subprocess.run(
            [sys.executable, "-c", GENERATE, arguments],
            env=os.environ | {"PYTHONHASHSEED": hash_seed, "PYTHONPATH": python_path},
            capture_output=True,
            check=True,
        ).stdout
        for hash_seed in ("0", "1", "2")
    ]

    expected = write_json(generate_manifest(counts, 7, economy))
    assert generated == [expected, expected, expected]


@pytest.mark.property
@given(generator_counts(), seeds)
def test_every_drawn_number_lies_within_its_row_and_every_other_follows_its_rule(
    counts: dict[str, int], seed: int
):
    manifest: dict[str, Any] = generate_manifest(counts, seed)

    for kind in ("materials", "components", "products"):
        for item in manifest[kind].values():
            assert_within(f"{kind}.space", item["space"])
    for position, material in enumerate(manifest["materials"]):
        first = f"supplier-{position % counts['suppliers'] + 1}"
        first_entry = manifest["suppliers"][first]["catalogue"][material]
        assert_within("catalogue.price", first_entry["price"])
        assert_within("catalogue.lead_time", first_entry["lead_time"])
        for supplier in manifest["suppliers"].values():
            entry = supplier["catalogue"].get(material)
            if entry is None:
                continue
            for key in DRAWN_ROWS["catalogue"]:
                assert_within(f"catalogue.{key}", entry[key])
    for customer in manifest["customers"].values():
        for pair in customer["products"].values():
            for key in DRAWN_ROWS["customer_products"]:
                assert_within(f"customer_products.{key}", pair[key])
    for line in manifest["lines"].values():
        for key in DRAWN_ROWS["lines"]:
            assert_within(f"lines.{key}", line[key])
        largest_wear = GENERATOR_RANGES["lines.wear_per_hour"][1]
        assert 0 <= Decimal(line["wear_per_hour"]) <= Decimal(largest_wear)
        for item in line["items"].values():
            for key in DRAWN_ROWS["line_items"]:
                assert_within(f"line_items.{key}", item[key])
    for key in ("credit_interest", "debit_interest", "overdraft_interest"):
        assert_within(f"cash.{key}", manifest["cash"][key])


# The contract of the matched economy: every price lies within the ratios of the
# example times the lowest cost of its product, up to the rounding to 4 places, so
# every best margin is above 0 (at least 1.8124 * 8.29 - 8.29 - 5.04 = 1.69) and the
# whole demand is useful.
@pytest.mark.property
@given(generator_counts(), seeds)
def test_every_matched_price_earns_a_margin_within_the_ratios_of_the_example(
    counts: dict[str, int], seed: int
):
    manifest: dict[str, Any] = generate_manifest(counts, seed, "matched")

    profile = build_economic_profile(manifest)
    rounding = Decimal("0.00005")
    for pair in profile.customer_products:
        price = Decimal(
            manifest["customers"][pair.customer]["products"][pair.product]["price"]
        )
        assert MATCHED_PRICE_RATIOS.min * pair.lowest_cost - rounding <= price
        assert price <= MATCHED_PRICE_RATIOS.max * pair.lowest_cost + rounding
        assert pair.best_margin > Decimal("1.69")
    assert profile.useful_demand_coverage == 1
    assert profile.economic_class == "profitable"


@pytest.mark.property
@given(generator_counts(), seeds)
def test_the_matched_economy_changes_only_prices_credit_limit_and_description(
    counts: dict[str, int], seed: int
):
    unrestricted: dict[str, Any] = generate_manifest(counts, seed)
    matched: dict[str, Any] = generate_manifest(counts, seed, "matched")

    for manifest in (unrestricted, matched):
        for held in manifest["customers"].values():
            for terms in held["products"].values():
                terms.pop("price")
        manifest["cash"].pop("credit_limit")
        manifest.pop("description")
    assert matched == unrestricted
