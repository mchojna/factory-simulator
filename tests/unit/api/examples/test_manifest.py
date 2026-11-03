from decimal import Decimal
from typing import Any, cast

from factory_simulator.api.core.json import write_json
from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.services.examples import EXAMPLES
from factory_simulator.api.services.readers.manifest import (
    resolve_manifest,
    written_content,
)

MATERIALS = {
    "microchip",
    "microchip-b",
    "passive-kit",
    "pcb-blank",
    "lcd-panel",
    "connector-pins",
    "copper-wire",
    "plastic-resin",
    "steel-sheet",
}


COMPONENTS = {
    "control-board",
    "power-module",
    "sensor-module",
    "display-unit",
    "enclosure",
    "cable-harness",
}


# The packaged example manifest as the HTTP interface stores it, its numbers exact.
def example_content() -> dict[str, Any]:
    body = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    content = written_content(*resolve_manifest(body))
    return cast(dict[str, Any], read_json_bytes(write_json(content)))


def group_of(members: dict[str, Any], kinds: dict[str, str], kind: str) -> list[str]:
    return [group for group in members.get("groups", []) if kinds.get(group) == kind]


# The middle of a value: the mean of a normal range, the median of a lognormal one,
# the middle of the bounds of any other.
def middle(value: object) -> Decimal:
    if isinstance(value, dict):
        bounds = cast(dict[str, object], value)
        for key in ("mean", "median"):
            if key in bounds:
                return Decimal(str(bounds[key]))
        return (Decimal(str(bounds["min"])) + Decimal(str(bounds["max"]))) / 2
    return Decimal(str(value))


def entries_of(content: dict[str, Any], material: str) -> dict[str, dict[str, Any]]:
    regions = content["groups"]
    entries: dict[str, dict[str, Any]] = {}
    for supplier_id, supplier in content["suppliers"].items():
        if material in supplier["catalogue"]:
            defaults = regions[supplier["groups"][0]]["defaults"]["catalogue"]
            entries[supplier_id] = defaults | supplier["catalogue"][material]
    return entries


def test_every_object_is_in_one_group_of_its_kind():
    content = example_content()

    kinds = {group: terms["kind"] for group, terms in content["groups"].items()}
    for supplier in content["suppliers"].values():
        assert group_of(supplier, kinds, "region") in (["emea"], ["apac"], ["amer"])
    for product in content["products"].values():
        assert group_of(product, kinds, "segment") in (
            ["new-devices"],
            ["spare-parts"],
        )
    for material in content["materials"].values():
        assert len(group_of(material, kinds, "category")) == 1


def test_the_control_board_has_an_alternative_chip_from_another_region():
    content = example_content()

    board = content["components"]["control-board"]
    assert set(board["recipes"]) == {"standard", "alternative"}
    assert board["default_recipe"] == "standard"
    chip_regions = {
        region
        for supplier in content["suppliers"].values()
        if "microchip" in supplier["catalogue"]
        for region in supplier["groups"]
    }
    for supplier in content["suppliers"].values():
        if "microchip-b" in supplier["catalogue"]:
            assert not set(supplier["groups"]) & chip_regions


def test_the_microchip_reaches_every_product():
    content = example_content()

    with_chip = {
        component
        for component, terms in content["components"].items()
        if any("microchip" in recipe for recipe in terms["recipes"].values())
    }
    for product in content["products"].values():
        inputs = set(product["recipes"]["standard"])
        assert inputs & with_chip


def test_the_centre_holds_products_one_period_from_the_plant():
    content = example_content()

    assert content["warehouses"]["distribution-centre"]["accepts"] == ["products"]
    assert content["routes"]["main-plant"]["distribution-centre"]["lead_time"] == 1
    assert {line["warehouse"] for line in content["lines"].values()} == {"main-plant"}


def test_the_main_plant_keeps_a_quarter_free_with_stock_orders_and_production():
    content = example_content()

    items = {**content["materials"], **content["components"], **content["products"]}
    space = {item_id: Decimal(item["space"]) for item_id, item in items.items()}
    # An item made on two lines counts at the yield of its cheaper line.
    terms: dict[str, Any] = {}
    for line in content["lines"].values():
        for item_id, item_terms in line["items"].items():
            known = terms.get(item_id)
            if known is None or item_terms["cost"] < known["cost"]:
                terms[item_id] = item_terms
    started: dict[str, Decimal] = {}
    for customer in content["customers"].values():
        for product, pair in customer["products"].items():
            demand = middle(pair["demand"]) / middle(terms[product]["yield"])
            started[product] = started.get(product, Decimal(0)) + demand
    for made_kind, input_kind in (
        ("products", "components"),
        ("components", "materials"),
    ):
        for made_id, made in content[made_kind].items():
            if made_id not in started:
                continue
            for input_id, quantity in made["recipes"]["standard"].items():
                need = started[made_id] * Decimal(str(quantity))
                if input_kind == "components":
                    need /= middle(terms[input_id]["yield"])
                started[input_id] = started.get(input_id, Decimal(0)) + need
    regions = content["groups"]
    lead_times: dict[str, Decimal] = {}
    for supplier in content["suppliers"].values():
        defaults = regions[supplier["groups"][0]]["defaults"]["catalogue"]
        for material, entry in supplier["catalogue"].items():
            periods = middle(entry.get("lead_time", defaults["lead_time"]))
            lead_times[material] = max(lead_times.get(material, periods), periods)
    stored = MATERIALS | COMPONENTS
    stock = 3 * sum(
        started[item_id] * space[item_id] for item_id in stored if item_id in started
    )
    on_the_way = sum(
        started[material] * space[material] * lead_times[material]
        for material in lead_times
        if material in started
    )
    production = sum(
        started[item_id] * space[item_id]
        for item_id in started
        if item_id not in MATERIALS
    )
    capacity = content["warehouses"]["main-plant"]["capacity"]

    assert stock + on_the_way + production <= capacity * Decimal("0.75")


def test_the_distribution_centre_is_larger_than_the_main_plant():
    warehouses = example_content()["warehouses"]

    centre = warehouses["distribution-centre"]["capacity"]
    assert centre > warehouses["main-plant"]["capacity"]


def test_3_materials_have_a_second_source_that_is_faster_and_dearer():
    content = example_content()

    for material, first, second in (
        ("passive-kit", "emea-electronic-parts", "amer-metals"),
        ("lcd-panel", "apac-displays-plastics", "emea-electronic-parts"),
        ("copper-wire", "amer-metals", "emea-electronic-parts"),
    ):
        entries = entries_of(content, material)
        assert set(entries) == {first, second}
        assert middle(entries[second]["lead_time"]) < middle(
            entries[first]["lead_time"]
        )
        first_price = entries[first]["price"]
        if isinstance(first_price, dict):
            first_price = cast(dict[str, Decimal], first_price)["min"]
        assert entries[second]["price"] > first_price
    for material in ("microchip", "pcb-blank"):
        assert len(entries_of(content, material)) == 1


def test_the_power_module_is_made_on_2_lines_the_second_slower_and_dearer():
    lines = example_content()["lines"]

    smt = lines["smt-line"]["items"]["power-module"]
    module = lines["module-assembly-line"]["items"]["power-module"]
    assert module["time"] > smt["time"]
    assert module["cost"] > smt["cost"]


def test_the_4_lines_have_capacities_of_80_64_64_and_72_hours():
    lines = example_content()["lines"]

    assert {line_id: line["capacity"] for line_id, line in lines.items()} == {
        "smt-line": Decimal(80),
        "module-assembly-line": Decimal(64),
        "moulding-line": Decimal(64),
        "final-assembly-line": Decimal(72),
    }


def test_10_pairs_without_spare_parts_for_retail_or_monitors_for_integrators():
    customers = example_content()["customers"]

    pairs = [
        (customer, product)
        for customer, terms in customers.items()
        for product in terms["products"]
    ]
    assert len(pairs) == 10
    assert "industrial-controller" not in customers["retail-chain"]["products"]
    assert "smart-monitor" not in customers["system-integrator"]["products"]
