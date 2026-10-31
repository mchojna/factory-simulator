import copy
from collections.abc import Callable
from typing import Any

from factories.bodies import tiny_manifest
from factory_simulator.api.core.json import write_json

# Invalid manifests and scenarios: each example changes the tiny factory or its
# scenario and gives the whole message of the problem it causes, path and problem.

Change = Callable[[dict[str, Any]], None]
ScenarioChange = Callable[[dict[str, Any], dict[str, Any]], None]


# The tiny manifest after a change, as JSON bytes.
def changed(change: Change) -> bytes:
    manifest = tiny_manifest()
    change(manifest)
    return write_json(manifest)


# Set the key at a dotted path of a document.
def set_key(path: str, value: object) -> Change:
    def change(document: dict[str, Any]) -> None:
        *parents, key = path.split(".")
        for parent in parents:
            document = document[parent]
        document[key] = value

    return change


# Delete the key at a dotted path of a document.
def delete_key(path: str) -> Change:
    def change(document: dict[str, Any]) -> None:
        *parents, key = path.split(".")
        for parent in parents:
            document = document[parent]
        del document[key]

    return change


# Rename a key of the object at a dotted path of a document.
def rename(path: str, old: str, new: str) -> Change:
    def change(document: dict[str, Any]) -> None:
        for part in path.split("."):
            document = document[part]
        document[new] = document.pop(old)

    return change


# Add a component `chip`, a copy of the component `board`.
def add_component_chip(manifest: dict[str, Any]) -> None:
    manifest["components"]["chip"] = copy.deepcopy(manifest["components"]["board"])


# Make two changes of a document, in order.
def both(first: Change, second: Change) -> Change:
    def change(document: dict[str, Any]) -> None:
        first(document)
        second(document)

    return change


# Copy the value at one dotted path of a document to another.
def copy_key(source: str, target: str) -> Change:
    def change(document: dict[str, Any]) -> None:
        value: Any = document
        for part in source.split("."):
            value = value[part]
        set_key(target, copy.deepcopy(value))(document)

    return change


# Add a product `tablet` of one board, made on `line-1` like the monitor.
def add_tablet(manifest: dict[str, Any]) -> None:
    manifest["products"]["tablet"] = copy.deepcopy(manifest["products"]["monitor"])
    manifest["products"]["tablet"]["recipes"]["standard"] = {"board": "1.000"}
    items = manifest["lines"]["line-1"]["items"]
    items["tablet"] = copy.deepcopy(items["monitor"])


# Set the credit, debit and overdraft interest of the cash.
def rates(credit: str, debit: str, overdraft: str) -> Change:
    def change(document: dict[str, Any]) -> None:
        document["cash"] |= {
            "credit_interest": credit,
            "debit_interest": debit,
            "overdraft_interest": overdraft,
        }

    return change


# Add an empty warehouse `spare` of capacity 10.
def add_second_warehouse(manifest: dict[str, Any]) -> None:
    manifest["warehouses"]["spare"] = {"capacity": "10.000"}


# Add a warehouse `centre`, put `line-1` in `main` and move the monitor to a copy
# `line-2` in `centre`.
def split_lines_across_warehouses(manifest: dict[str, Any]) -> None:
    manifest["warehouses"]["centre"] = {"capacity": "100.000"}
    line = manifest["lines"]["line-1"]
    monitor = line["items"].pop("monitor")
    line["warehouse"] = "main"
    manifest["lines"]["line-2"] = copy.deepcopy(line) | {
        "warehouse": "centre",
        "items": {"monitor": monitor},
    }


ROUTE = {"cost": "0.2000", "lead_time": 1}


# Add the material `glue`, in the catalogue and in no recipe, and let `main` accept
# only the material `chip` of the group `chips`.
def add_glue_outside_every_recipe(manifest: dict[str, Any]) -> None:
    manifest["materials"]["glue"] = copy.deepcopy(manifest["materials"]["chip"])
    catalogue = manifest["suppliers"]["chip-maker"]["catalogue"]
    catalogue["glue"] = copy.deepcopy(catalogue["chip"])
    manifest["materials"]["chip"]["groups"] = ["chips"]
    manifest["groups"] = {"chips": {"kind": "category"}}
    accepts = ["components", "products", {"group": "chips"}]
    manifest["warehouses"]["main"]["accepts"] = accepts


# Split the lines across `main` and `centre`, then write the routes.
def routed(routes: dict[str, dict[str, Any]]) -> Change:
    return both(split_lines_across_warehouses, set_key("routes", routes))


# Split the lines across `main` and `centre` and route them through a warehouse `hub`
# that accepts products only.
def through_a_hub_of_products(manifest: dict[str, Any]) -> None:
    split_lines_across_warehouses(manifest)
    manifest["warehouses"]["hub"] = {"capacity": "100.000", "accepts": ["products"]}
    manifest["routes"] = {"main": {"hub": ROUTE}, "hub": {"centre": ROUTE}}


# Write groups, and list them on objects named by their paths with `/`. The object
# `suppliers/chip-maker` is written as the key `suppliers__chip_maker`: the key holds
# the path of the object with `__` for `.` and `_` for `-`.
def grouped(groups: dict[str, Any], **listed: list[str]) -> Change:
    def change(manifest: dict[str, Any]) -> None:
        manifest["groups"] = groups
        for key, group_ids in listed.items():
            kind, object_id = key.split("__")
            manifest[kind][object_id.replace("_", "-")]["groups"] = group_ids

    return change


APAC = {"kind": "region"}


CHIP_ENTRY = "suppliers.chip-maker.catalogue.chip"


# The chip entry at price 5.0000, max quantity 20000, with (from, price) tiers.
def discounted(*tiers: tuple[object, str], **terms: object) -> Change:
    def change(document: dict[str, Any]) -> None:
        entry = document["suppliers"]["chip-maker"]["catalogue"]["chip"]
        entry.update(price="5.0000", max_quantity="20000.000")
        entry["discounts"] = [{"from": start, "price": price} for start, price in tiers]
        entry.update(terms)

    return change


# Material chip-b from chip-maker and board recipes standard and alternative.
def with_alternative_recipe(
    alternative: dict[str, str], default_recipe: str | None = "standard"
) -> Change:
    def change(document: dict[str, Any]) -> None:
        document["materials"]["chip-b"] = copy.deepcopy(document["materials"]["chip"])
        catalogue = document["suppliers"]["chip-maker"]["catalogue"]
        catalogue["chip-b"] = copy.deepcopy(catalogue["chip"])
        board = document["components"]["board"]
        board["recipes"]["alternative"] = alternative
        if default_recipe is not None:
            board["default_recipe"] = default_recipe

    return change


# Line 1 at capacity 10, wear 0.0100 a period and 0.0700 an hour, in overtime.
def overtime_wear(overtime_hours: str) -> Change:
    return both(
        set_key("lines.line-1.wear_per_hour", "0.0700"),
        both(
            set_key("lines.line-1.overtime_hours", overtime_hours),
            set_key("lines.line-1.overtime_cost", "45.0000"),
        ),
    )


# Give the chip entry express at the lead time and an express cost of 1.0000.
def express(lead_time: int) -> Change:
    return both(
        set_key(f"{CHIP_ENTRY}.express_lead_time", lead_time),
        set_key(f"{CHIP_ENTRY}.express_cost", "1.0000"),
    )


# Empty the six maps of objects of the factory.
def without_objects(manifest: dict[str, Any]) -> None:
    for kind in ("materials", "components", "products", "suppliers", "customers"):
        manifest[kind] = {}
    manifest["lines"] = {}


# A material glass in no catalogue, and chip-maker in two groups of kind region.
def unbought_glass_and_two_regions(manifest: dict[str, Any]) -> None:
    manifest["materials"]["glass"] = copy.deepcopy(manifest["materials"]["chip"])
    grouped({"apac": APAC, "emea": APAC}, suppliers__chip_maker=["apac", "emea"])(
        manifest
    )


MONITOR_DEMAND = "customers.distributor.products.monitor.demand"


MANIFEST_EXAMPLES: list[tuple[str, Change, str]] = [
    (
        "no objects",
        without_objects,
        "products: is empty",
    ),
    (
        "unbought material before two groups of one kind",
        unbought_glass_and_two_regions,
        "materials.glass: is in no catalogue",
    ),
    (
        "pair of a product that does not exist",
        copy_key(
            "customers.distributor.products.monitor",
            "customers.distributor.products.tablet",
        ),
        "customers.distributor.products.tablet: is not a product",
    ),
    (
        "normal range with min equal to max",
        set_key(
            MONITOR_DEMAND,
            {
                "min": "40.000",
                "max": "40.000",
                "distribution": "normal",
                "mean": "40.000",
                "sd": "5.000",
            },
        ),
        f"{MONITOR_DEMAND}: a normal range needs min below max",
    ),
    (
        "lognormal range with min equal to max",
        set_key(
            MONITOR_DEMAND,
            {
                "min": "40.000",
                "max": "40.000",
                "distribution": "lognormal",
                "median": "40.000",
                "spread": "0.5000",
            },
        ),
        f"{MONITOR_DEMAND}: a lognormal range needs min below max",
    ),
    (
        "unknown key",
        set_key("materials.chip.color", "red"),
        "materials.chip.color: Extra inputs are not permitted",
    ),
    (
        "missing key",
        delete_key("cash.credit_limit"),
        "cash.credit_limit: Field required",
    ),
    (
        "second warehouse",
        add_second_warehouse,
        "lines.line-1.warehouse: Field required",
    ),
    (
        "identifier in capitals",
        rename("materials", "chip", "Chip"),
        "materials.Chip: String should match pattern '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'",
    ),
    ("identifier of two items", add_component_chip, "components.chip: names two items"),
    (
        "share above 1",
        set_key("suppliers.chip-maker.catalogue.chip.completeness", "1.2000"),
        (
            "suppliers.chip-maker.catalogue.chip.completeness: Input should be less "
            "than or equal to 1"
        ),
    ),
    (
        "range with min above max",
        set_key(
            "customers.distributor.products.monitor.demand",
            {"min": "9.000", "max": "2.000"},
        ),
        "customers.distributor.products.monitor.demand: min is above max",
    ),
    (
        "fixed parameter as a range",
        set_key("materials.chip.space", {"min": "0.010", "max": "0.020"}),
        "materials.chip.space: is not a decimal number",
    ),
    (
        "negative cost",
        set_key("lines.line-1.items.board.cost", "-1.0000"),
        "lines.line-1.items.board.cost: Input should be greater than or equal to 0",
    ),
    (
        "capacity 0",
        set_key("lines.line-1.capacity", "0"),
        "lines.line-1.capacity: Input should be greater than 0",
    ),
    (
        "max quantity 0",
        set_key("suppliers.chip-maker.catalogue.chip.max_quantity", "0"),
        (
            "suppliers.chip-maker.catalogue.chip.max_quantity: Input should be "
            "greater than 0"
        ),
    ),
    (
        "repair limit 0",
        set_key("lines.line-1.repair_limit", "0"),
        "lines.line-1.repair_limit: Input should be greater than 0",
    ),
    (
        "repair time 0",
        set_key("lines.line-1.repair_time", "0"),
        "lines.line-1.repair_time: Input should be greater than 0",
    ),
    (
        "group default repair time 0",
        grouped(
            {"slow-lines": {"kind": "tier", "defaults": {"lines": {"repair_time": 0}}}},
            lines__line_1=["slow-lines"],
        ),
        "groups.slow-lines.defaults.lines.repair_time: Input should be greater than 0",
    ),
    (
        "lead time 0",
        set_key("suppliers.chip-maker.catalogue.chip.lead_time", 0),
        (
            "suppliers.chip-maker.catalogue.chip.lead_time: Input should be greater "
            "than or equal to 1"
        ),
    ),
    (
        "price with 5 places",
        set_key("suppliers.chip-maker.catalogue.chip.price", "5.00001"),
        "suppliers.chip-maker.catalogue.chip.price: has more than 4 places",
    ),
    (
        "recipe of the wrong kind",
        set_key("components.board.recipes.standard", {"monitor": "1.000"}),
        (
            "components.board.recipes.standard.monitor: is not an input of this "
            "kind of item"
        ),
    ),
    (
        "item without recipes",
        set_key("components.board.recipes", {}),
        "components.board.recipes: has no recipe",
    ),
    (
        "recipe without inputs",
        set_key("components.board.recipes.standard", {}),
        "components.board.recipes.standard: has no input",
    ),
    (
        "catalogue entry of an unknown material",
        copy_key(
            "suppliers.chip-maker.catalogue.chip",
            "suppliers.chip-maker.catalogue.glass",
        ),
        "suppliers.chip-maker.catalogue.glass: is not a material",
    ),
    (
        "line item of an unknown item",
        copy_key("lines.line-1.items.board", "lines.line-1.items.glass"),
        "lines.line-1.items.glass: is not a component or product",
    ),
    (
        "material in no catalogue",
        copy_key("materials.chip", "materials.glass"),
        "materials.glass: is in no catalogue",
    ),
    (
        "product no customer buys",
        add_tablet,
        "products.tablet: is bought by no customer",
    ),
    (
        "empty catalogue",
        set_key("suppliers.glass-maker", {"catalogue": {}}),
        "suppliers.glass-maker.catalogue: is empty",
    ),
    (
        "debit below credit interest",
        rates("0.0040", "0.0030", "0.0200"),
        "cash.debit_interest: is below credit_interest",
    ),
    (
        "overdraft below debit interest",
        rates("0.0005", "0.0040", "0.0030"),
        "cash.overdraft_interest: is below debit_interest",
    ),
    (
        "wear above what a full line can bear",
        set_key("lines.line-1.wear_per_hour", {"min": "0.0010", "max": "0.1000"}),
        "lines.line-1.wear_per_hour: wears more than the condition left",
    ),
    (
        "cancellation fee above the price",
        set_key("suppliers.chip-maker.catalogue.chip.cancellation_fee", "0.6000"),
        (
            "suppliers.chip-maker.catalogue.chip.cancellation_fee: is above the "
            "lowest price"
        ),
    ),
    (
        "cancellation fee above the lowest price of a range",
        both(
            set_key(
                "suppliers.chip-maker.catalogue.chip.price",
                {"min": "0.4500", "max": "0.6000"},
            ),
            set_key("suppliers.chip-maker.catalogue.chip.cancellation_fee", "0.5000"),
        ),
        (
            "suppliers.chip-maker.catalogue.chip.cancellation_fee: is above the "
            "lowest price"
        ),
    ),
    (
        "express lead time not below the lowest lead time",
        both(
            set_key(f"{CHIP_ENTRY}.lead_time", {"min": 2, "max": 4}),
            express(2),
        ),
        (
            "suppliers.chip-maker.catalogue.chip.express_lead_time: is not below "
            "the lead time"
        ),
    ),
    (
        "express lead time 0",
        express(0),
        (
            "suppliers.chip-maker.catalogue.chip.express_lead_time: Input should be "
            "greater than or equal to 1"
        ),
    ),
    (
        "express cost without express lead time",
        set_key(f"{CHIP_ENTRY}.express_cost", "1.0000"),
        "suppliers.chip-maker.catalogue.chip.express_cost: needs express_lead_time",
    ),
    (
        "express lead time without express cost",
        set_key(f"{CHIP_ENTRY}.express_lead_time", 1),
        "suppliers.chip-maker.catalogue.chip.express_cost: is required with express",
    ),
    (
        "negative backfill delay",
        set_key(f"{CHIP_ENTRY}.backfill_delay", -1),
        (
            "suppliers.chip-maker.catalogue.chip.backfill_delay: Input should be "
            "greater than or equal to 0"
        ),
    ),
    (
        "discount tiers without rising from",
        discounted(("5000.000", "4.3000"), ("1000.000", "4.6000")),
        "suppliers.chip-maker.catalogue.chip.discounts.1.from: does not rise",
    ),
    (
        "discount tiers without falling price",
        discounted(("1000.000", "4.6000"), ("5000.000", "4.8000")),
        "suppliers.chip-maker.catalogue.chip.discounts.1.price: does not fall",
    ),
    (
        "first tier not below the price",
        discounted(("1000.000", "5.0000")),
        (
            "suppliers.chip-maker.catalogue.chip.discounts.0.price: is not below "
            "the price"
        ),
    ),
    (
        "first tier not below the lowest price of a range",
        discounted(("1000.000", "4.6000"), price={"min": "4.5000", "max": "5.5000"}),
        (
            "suppliers.chip-maker.catalogue.chip.discounts.0.price: is not below "
            "the price"
        ),
    ),
    (
        "tier from below the min quantity",
        discounted(("800.000", "4.6000"), min_quantity="1000.000"),
        (
            "suppliers.chip-maker.catalogue.chip.discounts.0.from: is outside the "
            "minimum and maximum quantity"
        ),
    ),
    (
        "tier from above the max quantity",
        discounted(("30000.000", "4.6000")),
        (
            "suppliers.chip-maker.catalogue.chip.discounts.0.from: is outside the "
            "minimum and maximum quantity"
        ),
    ),
    (
        "min quantity above the max quantity",
        discounted(min_quantity="30000.000"),
        "suppliers.chip-maker.catalogue.chip.min_quantity: is above max_quantity",
    ),
    (
        "tier from as a range",
        discounted(({"min": "800.000", "max": "900.000"}, "4.6000")),
        (
            "suppliers.chip-maker.catalogue.chip.discounts.0.from: is not a decimal "
            "number"
        ),
    ),
    (
        "cancellation fee above the price of a tier",
        discounted(("1000.000", "4.3000"), cancellation_fee="4.4000"),
        (
            "suppliers.chip-maker.catalogue.chip.cancellation_fee: is above the "
            "lowest price"
        ),
    ),
    (
        "material salvage above the price of a tier",
        both(
            discounted(("1000.000", "4.3000")),
            set_key("materials.chip.salvage_value", "4.5000"),
        ),
        "materials.chip.salvage_value: is above its lowest price",
    ),
    (
        "two recipes without default recipe",
        with_alternative_recipe({"chip-b": "2.000"}, default_recipe=None),
        "components.board.default_recipe: is required with several recipes",
    ),
    (
        "item named twice and two recipes without default recipe",
        both(
            with_alternative_recipe({"chip-b": "2.000"}, default_recipe=None),
            set_key(
                "products.board",
                {
                    "space": "0.010",
                    "storage_cost": "0.0010",
                    "salvage_value": "0.1000",
                    "recipes": {"standard": {"chip": "1.000"}},
                },
            ),
        ),
        "components.board.default_recipe: is required with several recipes",
    ),
    (
        "two warehouses, a line without warehouse and a recipe input ghost",
        both(
            add_second_warehouse,
            set_key("components.board.recipes.standard", {"ghost": "1.000"}),
        ),
        "lines.line-1.warehouse: Field required",
    ),
    (
        "default recipe that is not a recipe",
        with_alternative_recipe({"chip-b": "2.000"}, default_recipe="premium"),
        "components.board.default_recipe: is not one of the recipes",
    ),
    (
        "alternative recipe with an input of 0",
        with_alternative_recipe({"chip-b": "0.000"}),
        "components.board.recipes.alternative.chip-b: Input should be greater than 0",
    ),
    (
        "alternative recipe of a component that lists a product",
        with_alternative_recipe({"monitor": "1.000"}),
        (
            "components.board.recipes.alternative.monitor: is not an input of this "
            "kind of item"
        ),
    ),
    (
        "production lead time 0",
        set_key("lines.line-1.items.monitor.lead_time", 0),
        (
            "lines.line-1.items.monitor.lead_time: Input should be greater than or "
            "equal to 1"
        ),
    ),
    (
        "overtime hours without overtime cost",
        set_key("lines.line-1.overtime_hours", "4.000"),
        "lines.line-1.overtime_cost: is required",
    ),
    (
        "overtime hours as a range without overtime cost",
        set_key("lines.line-1.overtime_hours", {"min": "0.000", "max": "4.000"}),
        "lines.line-1.overtime_cost: is required",
    ),
    (
        "overtime cost without overtime hours",
        set_key("lines.line-1.overtime_cost", "45.0000"),
        "lines.line-1.overtime_cost: needs overtime_hours",
    ),
    (
        "overtime cost with overtime hours 0",
        both(
            set_key("lines.line-1.overtime_hours", "0.000"),
            set_key("lines.line-1.overtime_cost", "45.0000"),
        ),
        "lines.line-1.overtime_cost: needs overtime_hours",
    ),
    (
        "negative overtime hours",
        set_key("lines.line-1.overtime_hours", "-1.000"),
        "lines.line-1.overtime_hours: Input should be greater than or equal to 0",
    ),
    (
        "wear above what a full line with overtime can bear",
        overtime_wear("5.000"),
        "lines.line-1.wear_per_hour: wears more than the condition left",
    ),
    (
        "negative cancellation fee",
        set_key("suppliers.chip-maker.catalogue.chip.cancellation_fee", "-0.1000"),
        (
            "suppliers.chip-maker.catalogue.chip.cancellation_fee: Input should be "
            "greater than or equal to 0"
        ),
    ),
    (
        "material salvage above its price",
        set_key("materials.chip.salvage_value", "0.6000"),
        "materials.chip.salvage_value: is above its lowest price",
    ),
    (
        "product salvage above inputs and cost",
        set_key("products.monitor.salvage_value", "3.5000"),
        (
            "products.monitor.salvage_value: is above the value of its inputs and "
            "the cost of making it"
        ),
    ),
    (
        "model before numbered checks",
        both(
            set_key("lines.line-1.items.board.cost", "-1.0000"),
            rates("0.0040", "0.0030", "0.0200"),
        ),
        "lines.line-1.items.board.cost: Input should be greater than or equal to 0",
    ),
    (
        "first field first",
        both(
            set_key("materials.chip.space", "0.0001"),
            set_key("cash.credit_limit", "1.00001"),
        ),
        "materials.chip.space: has more than 3 places",
    ),
    (
        "line at an unknown warehouse",
        set_key("lines.line-1.warehouse", "north-depot"),
        "lines.line-1.warehouse: names no warehouse",
    ),
    (
        "accepts an unknown kind",
        set_key("warehouses.main.accepts", ["goods"]),
        "warehouses.main.accepts: goods is not one of materials, components, products",
    ),
    (
        "accepts nothing",
        set_key("warehouses.main.accepts", []),
        "warehouses.main.accepts: is empty",
    ),
    (
        "accepts a kind twice",
        set_key("warehouses.main.accepts", ["products", "products"]),
        "warehouses.main.accepts: repeats an entry",
    ),
    (
        "storage factor as a range",
        set_key("warehouses.main.storage_factor", {"min": "0.5000", "max": "0.7000"}),
        "warehouses.main.storage_factor: is not a decimal number",
    ),
    (
        "storage factor of 0",
        set_key("warehouses.main.storage_factor", "0.0000"),
        "warehouses.main.storage_factor: Input should be greater than 0",
    ),
    (
        "transport factor of 0",
        set_key("warehouses.main.transport_factor", "0.0000"),
        "warehouses.main.transport_factor: Input should be greater than 0",
    ),
    (
        "line at a warehouse refusing its output",
        set_key("warehouses.main.accepts", ["materials", "components"]),
        "lines.line-1.warehouse: does not accept monitor",
    ),
    (
        "material accepted by no warehouse, the warehouse of its line included",
        set_key("warehouses.main.accepts", ["components", "products"]),
        "lines.line-1.warehouse: does not accept chip",
    ),
    (
        "material accepted by no warehouse",
        add_glue_outside_every_recipe,
        "materials.glue: is accepted by no warehouse",
    ),
    (
        "component made at another warehouse",
        split_lines_across_warehouses,
        "lines.line-2.warehouse: board is not made at centre",
    ),
    (
        "route to an unknown warehouse",
        routed({"main": {"north-depot": ROUTE}}),
        "routes.main.north-depot: north-depot is not a warehouse",
    ),
    (
        "route from an unknown warehouse",
        routed({"north-depot": {"main": ROUTE}}),
        "routes.north-depot: north-depot is not a warehouse",
    ),
    (
        "routes from an unknown warehouse to no warehouse",
        set_key("routes", {"ghost": {}}),
        "routes.ghost: ghost is not a warehouse",
    ),
    (
        "route from a warehouse to itself",
        routed({"main": {"main": ROUTE}}),
        "routes.main.main: joins a warehouse to itself",
    ),
    (
        "negative route cost",
        routed({"main": {"centre": ROUTE | {"cost": "-0.1000"}}}),
        "routes.main.centre.cost: Input should be greater than or equal to 0",
    ),
    (
        "negative route lead time",
        routed({"main": {"centre": ROUTE | {"lead_time": -1}}}),
        "routes.main.centre.lead_time: Input should be greater than or equal to 0",
    ),
    (
        "component reaching a line only through a hub of products",
        through_a_hub_of_products,
        "lines.line-2.warehouse: board is not made at centre",
    ),
    (
        "group named all",
        grouped({"all": APAC}, suppliers__chip_maker=["all"]),
        "groups.all: is a reserved word",
    ),
    (
        "group named default",
        grouped({"default": APAC}, suppliers__chip_maker=["default"]),
        "groups.default: is a reserved word",
    ),
    (
        "group in capitals",
        grouped({"Apac": APAC}, suppliers__chip_maker=["Apac"]),
        "groups.Apac: String should match pattern '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'",
    ),
    (
        "group of kind product",
        grouped({"apac": {"kind": "product"}}, suppliers__chip_maker=["apac"]),
        "groups.apac.kind: may not be product",
    ),
    (
        "group listed in a manifest without groups",
        set_key("suppliers.chip-maker.groups", ["apac"]),
        "suppliers.chip-maker.groups.0: names no group",
    ),
    (
        "group listed as an object",
        both(
            grouped({"apac": APAC}),
            set_key("suppliers.chip-maker.groups", [{"id": "apac"}]),
        ),
        "suppliers.chip-maker.groups.0: Input should be a valid string",
    ),
    (
        "unknown group listed",
        grouped({"apac": APAC}, suppliers__chip_maker=["emea"]),
        "suppliers.chip-maker.groups.0: names no group",
    ),
    (
        "warehouse accepting a group of suppliers",
        both(
            grouped({"apac": APAC}, suppliers__chip_maker=["apac"]),
            set_key("warehouses.main.accepts", [{"group": "apac"}]),
        ),
        "warehouses.main.accepts.0.group: names no group of items",
    ),
    (
        "warehouse accepting a group twice",
        both(
            grouped({"chips": {"kind": "category"}}, materials__chip=["chips"]),
            set_key(
                "warehouses.main.accepts",
                ["components", "products", {"group": "chips"}, {"group": "chips"}],
            ),
        ),
        "warehouses.main.accepts: repeats an entry",
    ),
    (
        "group default lead time of 0",
        grouped(
            {"apac": APAC | {"defaults": {"catalogue": {"lead_time": 0}}}},
            suppliers__chip_maker=["apac"],
        ),
        (
            "groups.apac.defaults.catalogue.lead_time: Input should be greater than "
            "or equal to 1"
        ),
    ),
    (
        "group default range with min above max",
        grouped(
            {
                "apac": APAC
                | {
                    "defaults": {
                        "catalogue": {"punctuality": {"min": "0.9200", "max": "0.8000"}}
                    }
                }
            },
            suppliers__chip_maker=["apac"],
        ),
        "groups.apac.defaults.catalogue.punctuality: min is above max",
    ),
    (
        "group default price with 5 places",
        grouped(
            {"apac": APAC | {"defaults": {"catalogue": {"price": "5.00001"}}}},
            suppliers__chip_maker=["apac"],
        ),
        "groups.apac.defaults.catalogue.price: has more than 4 places",
    ),
    (
        "group default space as a range",
        grouped(
            {
                "metals": {
                    "kind": "category",
                    "defaults": {"items": {"space": {"min": "0.001", "max": "0.002"}}},
                }
            },
            materials__chip=["metals"],
        ),
        "groups.metals.defaults.items.space: is not a decimal number",
    ),
    (
        "two groups of one kind",
        grouped({"apac": APAC, "amer": APAC}, suppliers__chip_maker=["apac", "amer"]),
        "suppliers.chip-maker.groups.1: a second group of kind region",
    ),
    (
        "group of a supplier and a customer",
        grouped(
            {"mixed": APAC},
            suppliers__chip_maker=["mixed"],
            customers__distributor=["mixed"],
        ),
        "groups.mixed: has members of two types",
    ),
    (
        "group of a material and a component",
        grouped(
            {"parts": APAC}, materials__chip=["parts"], components__board=["parts"]
        ),
        "groups.parts: has members of two types",
    ),
    (
        "group of suppliers giving defaults of lines",
        grouped(
            {"apac": APAC | {"defaults": {"lines": {"capacity": "1.000"}}}},
            suppliers__chip_maker=["apac"],
        ),
        "groups.apac.defaults.lines: is not used by suppliers",
    ),
    (
        "group with defaults and no members",
        grouped({"empty": APAC | {"defaults": {"catalogue": {"price": "1.0000"}}}}),
        "groups.empty: has no members",
    ),
    (
        "group without defaults or members",
        grouped({"bare": APAC}),
        "groups.bare: has no members",
    ),
    (
        "group default discounts",
        grouped(
            {"apac": APAC | {"defaults": {"catalogue": {"discounts": []}}}},
            suppliers__chip_maker=["apac"],
        ),
        "groups.apac.defaults.catalogue.discounts: Extra inputs are not permitted",
    ),
    (
        "group default recipes",
        grouped(
            {"boards": {"kind": "family", "defaults": {"items": {"recipes": {}}}}},
            components__board=["boards"],
        ),
        "groups.boards.defaults.items.recipes: Extra inputs are not permitted",
    ),
    (
        "group overtime cost on a line without overtime",
        grouped(
            {
                "fast-lines": {
                    "kind": "tier",
                    "defaults": {"lines": {"overtime_cost": "45.0000"}},
                }
            },
            lines__line_1=["fast-lines"],
        ),
        "lines.line-1.overtime_cost: needs overtime_hours",
    ),
    (
        "triangular range with min equal to max",
        set_key(
            f"{CHIP_ENTRY}.price",
            {
                "min": "5.0000",
                "max": "5.0000",
                "distribution": "triangular",
                "mode": "5.0000",
            },
        ),
        (
            "suppliers.chip-maker.catalogue.chip.price: a triangular range needs "
            "min below max"
        ),
    ),
    (
        "mode outside its range",
        set_key(
            f"{CHIP_ENTRY}.price",
            {
                "min": "4.8000",
                "max": "5.5000",
                "distribution": "triangular",
                "mode": "6.0000",
            },
        ),
        "suppliers.chip-maker.catalogue.chip.price: mode is outside min to max",
    ),
    (
        "normal range with sd of 0",
        set_key(
            "customers.distributor.products.monitor.demand",
            {
                "min": "30.000",
                "max": "50.000",
                "distribution": "normal",
                "mean": "40.000",
                "sd": "0.000",
            },
        ),
        "customers.distributor.products.monitor.demand: sd is not above 0",
    ),
    (
        "lognormal range with min of 0",
        set_key(
            "customers.distributor.products.monitor.demand",
            {
                "min": "0.000",
                "max": "120.000",
                "distribution": "lognormal",
                "median": "40.000",
                "spread": "0.5000",
            },
        ),
        (
            "customers.distributor.products.monitor.demand: a lognormal range needs "
            "min above 0"
        ),
    ),
    (
        "lognormal median outside its range",
        set_key(
            "customers.distributor.products.monitor.demand",
            {
                "min": "20.000",
                "max": "120.000",
                "distribution": "lognormal",
                "median": "130.000",
                "spread": "0.5000",
            },
        ),
        "customers.distributor.products.monitor.demand: median is outside min to max",
    ),
    (
        "lognormal range with spread of 0",
        set_key(
            "customers.distributor.products.monitor.demand",
            {
                "min": "20.000",
                "max": "120.000",
                "distribution": "lognormal",
                "median": "40.000",
                "spread": "0.0000",
            },
        ),
        "customers.distributor.products.monitor.demand: spread is not above 0",
    ),
    (
        "lognormal range with spread above 10",
        set_key(
            "customers.distributor.products.monitor.demand",
            {
                "min": "20.000",
                "max": "120.000",
                "distribution": "lognormal",
                "median": "40.000",
                "spread": "10.0001",
            },
        ),
        "customers.distributor.products.monitor.demand: spread is above 10",
    ),
    (
        "lognormal range of periods",
        set_key(
            f"{CHIP_ENTRY}.delay",
            {
                "min": 1,
                "max": 3,
                "distribution": "lognormal",
                "median": 2,
                "spread": "0.5000",
            },
        ),
        (
            "suppliers.chip-maker.catalogue.chip.delay: a range of periods is "
            "uniform only"
        ),
    ),
    (
        "median on a normal range",
        set_key(
            "customers.distributor.products.monitor.demand",
            {
                "min": "30.000",
                "max": "50.000",
                "distribution": "normal",
                "mean": "40.000",
                "sd": "5.000",
                "median": "40.000",
            },
        ),
        (
            "customers.distributor.products.monitor.demand.median: Extra inputs are "
            "not permitted"
        ),
    ),
    (
        "range of periods not uniform",
        set_key(
            f"{CHIP_ENTRY}.delay",
            {"min": 1, "max": 3, "distribution": "triangular", "mode": 2},
        ),
        (
            "suppliers.chip-maker.catalogue.chip.delay: a range of periods is "
            "uniform only"
        ),
    ),
    (
        "mode of a uniform range",
        set_key(
            f"{CHIP_ENTRY}.price", {"min": "4.8000", "max": "5.5000", "mode": "5.0000"}
        ),
        (
            "suppliers.chip-maker.catalogue.chip.price.mode: Extra inputs are not "
            "permitted"
        ),
    ),
    (
        "unknown distribution",
        set_key(
            f"{CHIP_ENTRY}.price",
            {"min": "4.8000", "max": "5.5000", "distribution": "beta"},
        ),
        (
            "suppliers.chip-maker.catalogue.chip.price.distribution: Input should "
            "be 'uniform'"
        ),
    ),
    (
        "triangular range without its mode",
        set_key(
            f"{CHIP_ENTRY}.price",
            {"min": "4.8000", "max": "5.5000", "distribution": "triangular"},
        ),
        "suppliers.chip-maker.catalogue.chip.price.mode: Field required",
    ),
    (
        "persistence of a fixed demand",
        set_key("customers.distributor.products.monitor.demand_persistence", "0.5000"),
        (
            "customers.distributor.products.monitor.demand_persistence: is given "
            "for a fixed demand"
        ),
    ),
    (
        "persistence above 1",
        both(
            set_key(
                "customers.distributor.products.monitor.demand",
                {"min": "30.000", "max": "50.000"},
            ),
            set_key(
                "customers.distributor.products.monitor.demand_persistence", "1.2000"
            ),
        ),
        (
            "customers.distributor.products.monitor.demand_persistence: Input "
            "should be less than or equal to 1"
        ),
    ),
    (
        "common share on a material",
        set_key("materials.chip.common_share", "0.5000"),
        "materials.chip.common_share: Extra inputs are not permitted",
    ),
    (
        "common share on a component",
        set_key("components.board.common_share", "0.5000"),
        "components.board.common_share: Extra inputs are not permitted",
    ),
    (
        "common share above 1",
        set_key("products.monitor.common_share", "1.2000"),
        "products.monitor.common_share: Input should be less than or equal to 1",
    ),
    (
        "common share with 5 places",
        set_key("products.monitor.common_share", "0.50000"),
        "products.monitor.common_share: has more than 4 places",
    ),
    (
        "common share of a product with one customer",
        both(
            set_key(
                "customers.distributor.products.monitor.demand",
                {"min": "30.000", "max": "50.000"},
            ),
            set_key("products.monitor.common_share", "0.5000"),
        ),
        (
            "products.monitor.common_share: is above 0 for a product that fewer than "
            "two customers buy with a demand range"
        ),
    ),
    (
        "common share under items of a group of components",
        grouped(
            {
                "boards": {
                    "kind": "family",
                    "defaults": {"items": {"common_share": "0.5000"}},
                }
            },
            components__board=["boards"],
        ),
        "components.board.common_share: Extra inputs are not permitted",
    ),
    (
        "drawn on a yield range",
        set_key(
            "lines.line-1.items.board.yield",
            {"min": "0.8000", "max": "0.9000", "drawn": "period"},
        ),
        "lines.line-1.items.board.yield.drawn: Extra inputs are not permitted",
    ),
    (
        "drawn on a price range of a customer",
        set_key(
            "customers.distributor.products.monitor.price",
            {"min": "40.0000", "max": "60.0000", "drawn": "period"},
        ),
        (
            "customers.distributor.products.monitor.price.drawn: "
            "Extra inputs are not permitted"
        ),
    ),
    (
        "drawn every week",
        set_key(
            f"{CHIP_ENTRY}.price",
            {"min": "0.4000", "max": "0.6000", "drawn": "week"},
        ),
        f"{CHIP_ENTRY}.price: drawn is run or period, got week",
    ),
    (
        "negative changeover time",
        set_key("lines.line-1.items.board.changeover_time", "-1.000"),
        (
            "lines.line-1.items.board.changeover_time: Input should be greater than "
            "or equal to 0"
        ),
    ),
    (
        "negative changeover cost",
        set_key("lines.line-1.items.board.changeover_cost", "-1.0000"),
        (
            "lines.line-1.items.board.changeover_cost: Input should be greater than "
            "or equal to 0"
        ),
    ),
    (
        "identifier longer than 40",
        rename("suppliers", "chip-maker", "c" * 41),
        (
            "suppliers.ccccccccccccccccccccccccccccccccccccccccc: "
            "String should have at most 40 characters"
        ),
    ),
    (
        "identifier with a double hyphen",
        rename("suppliers", "chip-maker", "chip--maker"),
        (
            "suppliers.chip--maker: "
            "String should match pattern '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'"
        ),
    ),
    (
        "identifier with a leading digit",
        rename("customers", "distributor", "1distributor"),
        (
            "customers.1distributor: "
            "String should match pattern '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'"
        ),
    ),
    (
        "group named materials",
        grouped({"materials": APAC}, suppliers__chip_maker=["materials"]),
        "groups.materials: is a reserved word",
    ),
    (
        "group named components",
        grouped({"components": APAC}, suppliers__chip_maker=["components"]),
        "groups.components: is a reserved word",
    ),
    (
        "group named products",
        grouped({"products": APAC}, suppliers__chip_maker=["products"]),
        "groups.products: is a reserved word",
    ),
    (
        "group named written",
        grouped({"written": APAC}, suppliers__chip_maker=["written"]),
        "groups.written: is a reserved word",
    ),
    (
        "group of kind customer",
        grouped({"apac": {"kind": "customer"}}, suppliers__chip_maker=["apac"]),
        "groups.apac.kind: may not be customer",
    ),
    (
        "catalogue entry of a component",
        copy_key(CHIP_ENTRY, "suppliers.chip-maker.catalogue.board"),
        "suppliers.chip-maker.catalogue.board: is not a material",
    ),
    (
        "product recipe with a material",
        set_key("products.monitor.recipes.standard", {"chip": "1.000"}),
        "products.monitor.recipes.standard.chip: is not an input of this kind of item",
    ),
    (
        "material with recipes",
        set_key("materials.chip.recipes", {"standard": {"board": "1.000"}}),
        "materials.chip.recipes: Extra inputs are not permitted",
    ),
    (
        "component made by no line",
        delete_key("lines.line-1.items.board"),
        "components.board: is made by no line",
    ),
    (
        "product made by no line",
        delete_key("lines.line-1.items.monitor"),
        "products.monitor: is made by no line",
    ),
    (
        "line with no items",
        both(
            copy_key("lines.line-1", "lines.line-2"), set_key("lines.line-2.items", {})
        ),
        "lines.line-2.items: is empty",
    ),
    (
        "customer with no products",
        both(
            copy_key("customers.distributor", "customers.shop"),
            set_key("customers.shop.products", {}),
        ),
        "customers.shop.products: is empty",
    ),
    (
        "normal mean outside its range",
        set_key(
            "customers.distributor.products.monitor.demand",
            {
                "min": "2.000",
                "max": "6.000",
                "distribution": "normal",
                "mean": "7.000",
                "sd": "1.000",
            },
        ),
        "customers.distributor.products.monitor.demand: mean is outside min to max",
    ),
    (
        "production time 0",
        set_key("lines.line-1.items.board.time", "0"),
        "lines.line-1.items.board.time: Input should be greater than 0",
    ),
    (
        "space 0",
        set_key("materials.chip.space", "0"),
        "materials.chip.space: Input should be greater than 0",
    ),
    (
        "delay 0",
        set_key(f"{CHIP_ENTRY}.delay", 0),
        f"{CHIP_ENTRY}.delay: Input should be greater than or equal to 1",
    ),
    (
        "warehouse capacity 0",
        set_key("warehouses.main.capacity", "0"),
        "warehouses.main.capacity: Input should be greater than 0",
    ),
    (
        "component salvage above inputs and cost",
        set_key("components.board.salvage_value", "1.3000"),
        (
            "components.board.salvage_value: "
            "is above the value of its inputs and the cost of making it"
        ),
    ),
]


# Set the key at a dotted path of the scenario; a part in digits is a list index.
def at(path: str, value: object) -> ScenarioChange:
    def change(_manifest: dict[str, Any], scenario: dict[str, Any]) -> None:
        *parents, key = path.split(".")
        document: Any = scenario
        for parent in parents:
            document = document[int(parent)] if parent.isdigit() else document[parent]
        document[key] = value

    return change


# Delete the key at a dotted path of the scenario.
def delete_at(path: str) -> ScenarioChange:
    def change(_manifest: dict[str, Any], scenario: dict[str, Any]) -> None:
        delete_key(path)(scenario)

    return change


FORECAST = {
    "target": "all",
    "periods_ahead": 2,
    "noise": "0.1000",
    "noise_growth": "0.0500",
}


# Set the forecasts of the scenario.
def forecasts(*entries: dict[str, Any]) -> ScenarioChange:
    return at("forecasts", list(entries))


# One starting order of 10 chips from `chip-maker` arriving in period 1, with the
# changes.
def starting_supplier_order(**changes: object) -> ScenarioChange:
    order = {
        "supplier": "chip-maker",
        "material": "chip",
        "quantity": "10",
        "arrival": 1,
    }
    return at("start.supplier_orders", [order | changes])


# One starting order of 1 monitor of `distributor` due in period 1, with the changes.
def starting_customer_order(**changes: object) -> ScenarioChange:
    order = {"customer": "distributor", "product": "monitor", "quantity": "1", "due": 1}
    return at("start.customer_orders", [order | changes])


TEN_TO_THE_30 = "1" + "0" * 30


# A demand of 10**20 a period at a price of 50.
def huge_demand(manifest: dict[str, Any], _scenario: dict[str, Any]) -> None:
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms["demand"] = "100000000000000000000.000"


# Interest of 1 a period over 100 periods doubles any amount 100 times.
def doubling_debt(manifest: dict[str, Any], scenario: dict[str, Any]) -> None:
    manifest["cash"]["overdraft_interest"] = "1.0000"
    scenario["horizon"] = 100


# Set a key of the manifest of a scenario.
def in_manifest(path: str, value: object) -> ScenarioChange:
    def change(manifest: dict[str, Any], _scenario: dict[str, Any]) -> None:
        set_key(path, value)(manifest)

    return change


# Set every amount of money of the tiny factory to 0 and the demand to 10**30 a
# period.
def huge_demand_at_no_money(
    manifest: dict[str, Any], _scenario: dict[str, Any]
) -> None:
    for kind in ("materials", "components", "products"):
        for item in manifest[kind].values():
            item |= {"storage_cost": "0.0000", "salvage_value": "0.0000"}
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["price"] = "0.0000"
    manifest["customers"]["distributor"]["products"]["monitor"] |= {
        "price": "0.0000",
        "transport_cost": "0.0000",
        "late_penalty": "0.0000",
        "lost_sale_penalty": "0.0000",
        "demand": TEN_TO_THE_30,
    }
    for line_item in manifest["lines"]["line-1"]["items"].values():
        line_item["cost"] = "0.0000"


# Make several changes of a manifest and a scenario, in order.
def all_of(*changes: ScenarioChange) -> ScenarioChange:
    def change(manifest: dict[str, Any], scenario: dict[str, Any]) -> None:
        for scenario_change in changes:
            scenario_change(manifest, scenario)

    return change


# Add a warehouse `centre` that accepts products, then make the change.
def with_centre(
    scenario_change: ScenarioChange, capacity: str = "50.000"
) -> ScenarioChange:
    def change(manifest: dict[str, Any], scenario: dict[str, Any]) -> None:
        manifest["warehouses"]["centre"] = {
            "capacity": capacity,
            "accepts": ["products"],
        }
        manifest["lines"]["line-1"]["warehouse"] = "main"
        scenario_change(manifest, scenario)

    return change


# Put the supplier in a group `apac` of kind `region`, then make the change.
def with_apac(scenario_change: ScenarioChange) -> ScenarioChange:
    def change(manifest: dict[str, Any], scenario: dict[str, Any]) -> None:
        manifest["groups"] = {"apac": {"kind": "region"}}
        manifest["suppliers"]["chip-maker"]["groups"] = ["apac"]
        scenario_change(manifest, scenario)

    return change


RANDOM_OUTAGE = {
    "name": "outage",
    "kind": "supplier_outage",
    "target": ["chip-maker"],
    "chance": "0.0100",
    "duration": 2,
    "strength": "0.5000",
}
RANDOM_DELAY = {
    "name": "delays",
    "kind": "transport_delay",
    "target": ["chip-maker"],
    "chance": "0.0100",
    "duration": 2,
    "delay": 1,
}
RANDOM_BREAKDOWN = {
    "name": "line-trouble",
    "kind": "line_breakdown",
    "target": ["line-1"],
    "chance": "0.0100",
    "loss": "0.4000",
}


# The random disruption without its chance.
def without_chance(rule: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in rule.items() if key != "chance"}


# A raise of the chance of a rule by a factor for a number of periods.
def raise_of(rule: str, factor: str = "3.0000", periods: int = 2) -> dict[str, Any]:
    return {"rule": rule, "factor": factor, "periods": periods}


# Set the random disruptions of the scenario.
def random_disruptions(*rules: dict[str, Any]) -> ScenarioChange:
    return at("random_disruptions", list(rules))


# One written disruption that starts in period 1 and, unless it is a breakdown, lasts
# 1 period.
def disruption(kind: str, target: object, **keys: object) -> ScenarioChange:
    written: dict[str, object] = {"kind": kind, "target": target, "start": 1}
    if kind != "line_breakdown":
        written["duration"] = 1
    return at("disruptions", [written | keys])


# Make the change, then drop the duration of every written disruption.
def without_duration(scenario_change: ScenarioChange) -> ScenarioChange:
    def change(manifest: dict[str, Any], scenario: dict[str, Any]) -> None:
        scenario_change(manifest, scenario)
        scenario["disruptions"] = [
            {key: value for key, value in written.items() if key != "duration"}
            for written in scenario["disruptions"]
        ]

    return change


# One demand shape of a kind that targets every pair.
def shape(kind: str, **keys: object) -> ScenarioChange:
    return at("demand_shapes", [{"kind": kind, "target": "all"} | keys])


# Add a material `glass`, a supplier `glass-maker` of it and a starting order of glass.
def add_glass_maker(manifest: dict[str, Any], scenario: dict[str, Any]) -> None:
    manifest["materials"]["glass"] = copy.deepcopy(manifest["materials"]["chip"])
    entry = copy.deepcopy(manifest["suppliers"]["chip-maker"]["catalogue"]["chip"])
    manifest["suppliers"]["glass-maker"] = {"catalogue": {"glass": entry}}
    starting_supplier_order(material="glass")(manifest, scenario)


# 5000 chips in stock and a starting order of 6000 more.
def stock_and_orders_over_capacity(
    manifest: dict[str, Any], scenario: dict[str, Any]
) -> None:
    at("start.stock.main.chip", "5000")(manifest, scenario)
    starting_supplier_order(quantity="6000")(manifest, scenario)


# A cancellation fee of 0.4000 on chips and a price change of 0.7000 of every
# material.
def price_cut_below_cancellation_fee(
    manifest: dict[str, Any], scenario: dict[str, Any]
) -> None:
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["cancellation_fee"] = (
        "0.4000"
    )
    disruption("price_change", "all", factor="0.7000")(manifest, scenario)


# 4 periods from no chips, with the lead time of chips and, when given, an express
# lead time.
def chips_in_lead_time(lead_time: int, express_lead_time: object) -> ScenarioChange:
    def change(manifest: dict[str, Any], scenario: dict[str, Any]) -> None:
        scenario["horizon"] = 4
        scenario["start"]["stock"]["main"]["chip"] = "0"
        entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
        entry["lead_time"] = lead_time
        if express_lead_time is not None:
            entry.update(express_lead_time=express_lead_time, express_cost="1.0000")

    return change


# A tier at 4.3000 from 1000 chips, a salvage value of 4.0000 and a price change of
# 0.9000 of every material.
def price_cut_below_salvage_value_at_a_tier(
    manifest: dict[str, Any], scenario: dict[str, Any]
) -> None:
    discounted(("1000.000", "4.3000"))(manifest)
    manifest["materials"]["chip"]["salvage_value"] = "4.0000"
    disruption("price_change", "all", factor="0.9000")(manifest, scenario)


# 4 periods, with an alternative recipe of 2 `chip-b` whose lead time is 6.
def no_alternative_chips_in_time(
    manifest: dict[str, Any], scenario: dict[str, Any]
) -> None:
    with_alternative_recipe({"chip-b": "2.000"})(manifest)
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip-b"]["lead_time"] = 6
    scenario["horizon"] = 4


# 2 periods from no chips.
def no_chips_in_time(_manifest: dict[str, Any], scenario: dict[str, Any]) -> None:
    scenario["horizon"] = 2
    scenario["start"]["stock"]["main"]["chip"] = "0"


# The message of the model for a kind of disruption it does not know.
UNKNOWN_KIND = (
    "Input tag 'flood' found using 'kind' does not match any of the expected tags: "
    "'supplier_outage', 'material_shortage', 'quality_drop', 'transport_delay', "
    "'demand_shock', 'line_breakdown', 'price_change', 'capacity_cut', 'yield_drop'"
)


SCENARIO_EXAMPLES: list[tuple[str, ScenarioChange, str]] = [
    (
        "unknown key",
        at("start.money", "1"),
        "start.money: Extra inputs are not permitted",
    ),
    (
        "unknown kind of disruption",
        disruption("flood", "all", strength="0.5000"),
        f"disruptions.0: {UNKNOWN_KIND}",
    ),
    (
        "unknown kind of random disruption",
        at(
            "random_disruptions",
            [
                {
                    "name": "flood",
                    "kind": "flood",
                    "target": "all",
                    "chance": "0.5000",
                    "duration": 1,
                    "strength": "0.5000",
                }
            ],
        ),
        f"random_disruptions.0: {UNKNOWN_KIND}",
    ),
    (
        "set for an item the line does not make",
        at("start.set_for", {"line-1": "chip"}),
        "start.set_for.line-1: is not made by the line",
    ),
    (
        "set for on an unknown line",
        at("start.set_for", {"line-9": "board"}),
        "start.set_for.line-9: is not a line",
    ),
    (
        "negative starting stock",
        at("start.stock.main.chip", "-5"),
        "start.stock.main.chip: Input should be greater than or equal to 0",
    ),
    (
        "starting condition above 1",
        at("start.condition", {"line-1": "1.5000"}),
        "start.condition.line-1: Input should be less than or equal to 1",
    ),
    (
        "starting condition below 0",
        at("start.condition", {"line-1": "-0.5000"}),
        "start.condition.line-1: Input should be greater than or equal to 0",
    ),
    (
        "starting condition of an unknown line",
        at("start.condition", {"line-9": "0.5000"}),
        "start.condition.line-9: is not a line",
    ),
    (
        "demand too large for the record",
        huge_demand,
        "horizon: a run of this scenario can exceed the numbers the record holds",
    ),
    (
        "overdraft interest that grows past the record",
        doubling_debt,
        "horizon: a run of this scenario can exceed the numbers the record holds",
    ),
    (
        "warehouse storage factor too large for the record",
        in_manifest("warehouses.main.storage_factor", TEN_TO_THE_30),
        "horizon: a run of this scenario can exceed the numbers the record holds",
    ),
    (
        "warehouse transport factor too large for the record",
        in_manifest("warehouses.main.transport_factor", TEN_TO_THE_30),
        "horizon: a run of this scenario can exceed the numbers the record holds",
    ),
    (
        "credit limit too large for the record",
        in_manifest("cash.credit_limit", TEN_TO_THE_30),
        "horizon: a run of this scenario can exceed the numbers the record holds",
    ),
    (
        "demand too large for the record at no money",
        huge_demand_at_no_money,
        "horizon: a run of this scenario can exceed the numbers the record holds",
    ),
    (
        "starting customer order of an unknown customer",
        starting_customer_order(customer="shop"),
        "start.customer_orders.0.customer: is not a customer",
    ),
    (
        "random rule choosing one of no target",
        at(
            "random_disruptions",
            [
                {
                    "name": "trouble",
                    "kind": "line_breakdown",
                    "target": list[str](),
                    "chance": "0.1000",
                    "loss": "0.1000",
                    "choose": "one",
                }
            ],
        ),
        "random_disruptions.0.target: names nothing",
    ),
    (
        "random rule naming a line twice",
        at(
            "random_disruptions",
            [
                {
                    "name": "trouble",
                    "kind": "line_breakdown",
                    "target": ["line-1", "line-1"],
                    "chance": "0.1000",
                    "loss": "0.1000",
                }
            ],
        ),
        "random_disruptions.0.target.1: repeats line-1",
    ),
    (
        "written disruption of no target",
        at(
            "disruptions",
            [
                {
                    "kind": "line_breakdown",
                    "target": list[str](),
                    "start": 1,
                    "loss": "0.1000",
                }
            ],
        ),
        "disruptions.0.target: names nothing",
    ),
    (
        "unknown item in stock",
        at("start.stock.main.glass", "1"),
        "start.stock.main.glass: is not an item",
    ),
    (
        "pair the manifest lacks",
        starting_customer_order(product="board"),
        "start.customer_orders.0.product: is not bought by the customer",
    ),
    (
        "unknown supplier",
        starting_supplier_order(supplier="north-chips"),
        "start.supplier_orders.0.supplier: is not a supplier",
    ),
    (
        "material not in the catalogue",
        add_glass_maker,
        "start.supplier_orders.0.material: is not in the catalogue of the supplier",
    ),
    (
        "outage of an unknown supplier",
        disruption("supplier_outage", ["north-chips"], strength="0.5000"),
        "disruptions.0.target: names north-chips, not one of its kind",
    ),
    (
        "shape of a pair the manifest lacks",
        at(
            "demand_shapes",
            [
                {
                    "kind": "step",
                    "target": {"customer": "distributor", "product": "tablet"},
                    "period": 1,
                    "factor": "1",
                }
            ],
        ),
        "demand_shapes.0.target: names a pair the manifest lacks",
    ),
    (
        "disruption start 0",
        disruption("supplier_outage", "all", strength="0.5", start=0),
        "disruptions.0.start: is not from 1 to the horizon",
    ),
    (
        "due 0",
        starting_customer_order(due=0),
        "start.customer_orders.0.due: is not from 1 to the horizon",
    ),
    (
        "arrival after the horizon",
        starting_supplier_order(arrival=6),
        "start.supplier_orders.0.arrival: is not from 1 to the horizon",
    ),
    (
        "stock over the capacity",
        at("start.stock.main.chip", "20000"),
        "start.stock.main: takes more space than the warehouse has",
    ),
    (
        "stock and orders over the capacity",
        stock_and_orders_over_capacity,
        "start.stock.main: takes more space than the warehouse has",
    ),
    (
        "shape of a group of another kind",
        with_apac(
            at(
                "demand_shapes",
                [
                    {
                        "kind": "step",
                        "target": {"segment": "apac"},
                        "period": 1,
                        "factor": "1.5000",
                    }
                ],
            )
        ),
        "demand_shapes.0.target: apac is of kind region, not segment",
    ),
    (
        "demand shock of a group of suppliers",
        with_apac(disruption("demand_shock", {"region": "apac"}, factor="1.5000")),
        "disruptions.0.target: apac holds suppliers",
    ),
    (
        "disruption of an unknown group",
        with_apac(
            disruption("supplier_outage", {"region": "nowhere"}, strength="0.5000")
        ),
        "disruptions.0.target: names no group nowhere",
    ),
    (
        "s-curve of steepness 0",
        shape(
            "s_curve",
            middle=10,
            steepness="0.0000",
            from_factor="0.0000",
            to_factor="1.0000",
        ),
        "demand_shapes.0.steepness: Input should be greater than 0",
    ),
    (
        "s-curve factor below 0",
        shape(
            "s_curve",
            middle=10,
            steepness="0.5000",
            from_factor="-0.1000",
            to_factor="1.0000",
        ),
        "demand_shapes.0.from_factor: Input should be greater than or equal to 0",
    ),
    (
        "random target naming nothing",
        random_disruptions(RANDOM_OUTAGE | {"target": ["nowhere"]}),
        "random_disruptions.0.target: names nowhere, not one of its kind",
    ),
    (
        "random breakdown of a group of suppliers",
        with_apac(
            random_disruptions(RANDOM_BREAKDOWN | {"target": {"region": "apac"}})
        ),
        "random_disruptions.0.target: apac holds suppliers",
    ),
    (
        "random chance above 1",
        random_disruptions(RANDOM_OUTAGE | {"chance": "1.2000"}),
        "random_disruptions.0.chance: Input should be less than or equal to 1",
    ),
    (
        "random strength range above 1",
        random_disruptions(
            RANDOM_OUTAGE | {"strength": {"min": "0.5000", "max": "1.2000"}}
        ),
        "random_disruptions.0.strength.max: Input should be less than or equal to 1",
    ),
    (
        "random delay range not uniform",
        random_disruptions(
            RANDOM_DELAY
            | {"delay": {"min": 1, "max": 3, "distribution": "triangular", "mode": 2}}
        ),
        "random_disruptions.0.delay: a range of periods is uniform only",
    ),
    (
        "random breakdown with a duration",
        random_disruptions(RANDOM_BREAKDOWN | {"duration": 2}),
        "random_disruptions.0.duration: Extra inputs are not permitted",
    ),
    (
        "two random rules of one name",
        random_disruptions(RANDOM_BREAKDOWN, RANDOM_BREAKDOWN),
        "random_disruptions.1.name: repeats line-trouble",
    ),
    (
        "random choose two",
        random_disruptions(RANDOM_BREAKDOWN | {"choose": "two"}),
        "random_disruptions.0.choose: Input should be 'one'",
    ),
    (
        "random start after the horizon",
        random_disruptions(without_chance(RANDOM_OUTAGE) | {"start": 60}),
        "random_disruptions.0.start: is not from 1 to the horizon",
    ),
    (
        "random start seen before period 1",
        random_disruptions(without_chance(RANDOM_OUTAGE) | {"start": 2, "notice": 2}),
        "random_disruptions.0.notice: is visible before period 1",
    ),
    (
        "random start with a chance",
        random_disruptions(RANDOM_OUTAGE | {"start": 2}),
        "random_disruptions.0.chance: is not allowed with start",
    ),
    (
        "random start with choose",
        random_disruptions(
            without_chance(RANDOM_OUTAGE) | {"start": 2, "choose": "one"}
        ),
        "random_disruptions.0.choose: is not allowed with start",
    ),
    (
        "random outage without a chance or a start",
        random_disruptions(without_chance(RANDOM_OUTAGE)),
        "random_disruptions.0.chance: Field required",
    ),
    (
        "raises of an unknown rule",
        random_disruptions(RANDOM_OUTAGE | {"raises": raise_of("nowhere")}),
        "random_disruptions.0.raises.rule: names no random disruption",
    ),
    (
        "raises of its own rule",
        random_disruptions(RANDOM_OUTAGE | {"raises": raise_of("outage")}),
        "random_disruptions.0.raises.rule: names its own rule",
    ),
    (
        "raises of a rule that raises",
        random_disruptions(
            RANDOM_OUTAGE | {"raises": raise_of("delays")},
            RANDOM_DELAY | {"raises": raise_of("line-trouble")},
            RANDOM_BREAKDOWN,
        ),
        "random_disruptions.1.raises: is not allowed on a raised rule",
    ),
    (
        "raises of a rule with a written start",
        random_disruptions(
            RANDOM_OUTAGE | {"raises": raise_of("delays")},
            without_chance(RANDOM_DELAY) | {"start": 2},
        ),
        "random_disruptions.0.raises.rule: names a rule with a written start",
    ),
    (
        "raises by a factor of 1",
        random_disruptions(
            RANDOM_OUTAGE | {"raises": raise_of("delays", factor="1.0000")},
            RANDOM_DELAY,
        ),
        "random_disruptions.0.raises.factor: Input should be greater than 1",
    ),
    (
        "raises for 0 periods",
        random_disruptions(
            RANDOM_OUTAGE | {"raises": raise_of("delays", periods=0)}, RANDOM_DELAY
        ),
        "random_disruptions.0.raises.periods: is below 1",
    ),
    (
        "random outage without a duration",
        random_disruptions(
            {key: value for key, value in RANDOM_OUTAGE.items() if key != "duration"}
        ),
        "random_disruptions.0.duration: Field required",
    ),
    (
        "random name in capitals",
        random_disruptions(RANDOM_BREAKDOWN | {"name": "Line_Trouble"}),
        (
            "random_disruptions.0.name: String should match pattern "
            "'^[a-z][a-z0-9]*(-[a-z0-9]+)*$'"
        ),
    ),
    (
        "random price change below the salvage value",
        random_disruptions(
            {
                "name": "prices",
                "kind": "price_change",
                "target": ["chip"],
                "chance": "0.0100",
                "duration": 1,
                "factor": {"min": "0.1000", "max": "1.2000"},
            }
        ),
        "random_disruptions.0.factor: takes the price of chip below its salvage value",
    ),
    (
        "random duration that may be 0",
        random_disruptions(RANDOM_OUTAGE | {"duration": {"min": 0, "max": 3}}),
        "random_disruptions.0.duration: is below 1",
    ),
    (
        "random delay that may be 0",
        random_disruptions(RANDOM_DELAY | {"delay": {"min": 0, "max": 2}}),
        "random_disruptions.0.delay: is below 1",
    ),
    (
        "two forecasts of one pair",
        forecasts(FORECAST, FORECAST | {"target": {"product": "monitor"}}),
        "forecasts.1.target: targets a pair of an earlier entry",
    ),
    (
        "forecast 0 periods ahead",
        forecasts(FORECAST | {"periods_ahead": 0}),
        "forecasts.0.periods_ahead: is below 1",
    ),
    (
        "forecast past the horizon",
        forecasts(FORECAST | {"periods_ahead": 60}),
        "forecasts.0.periods_ahead: is above the horizon",
    ),
    (
        "forecast of an unknown product",
        forecasts(FORECAST | {"target": {"product": "nowhere"}}),
        "forecasts.0.target: names a pair the manifest lacks",
    ),
    (
        "forecast of an unknown group",
        forecasts(FORECAST | {"target": {"region": "apac"}}),
        "forecasts.0.target: names no group apac",
    ),
    (
        "forecast of a group of suppliers",
        with_apac(forecasts(FORECAST | {"target": {"region": "apac"}})),
        "forecasts.0.target: apac holds suppliers",
    ),
    (
        "forecast noise above 1",
        forecasts(FORECAST | {"noise": "1.2000"}),
        "forecasts.0.noise: Input should be less than or equal to 1",
    ),
    (
        "forecast noise growth below 0",
        forecasts(FORECAST | {"noise_growth": "-0.1000"}),
        "forecasts.0.noise_growth: Input should be greater than or equal to 0",
    ),
    (
        "hidden price and set for on an unknown line",
        all_of(
            at("hidden", ["customers.products.price"]),
            at("start.set_for", {"line-9": "board"}),
        ),
        "hidden.0: is not a group that may be hidden",
    ),
    (
        "hidden price",
        at("hidden", ["customers.products.price"]),
        "hidden.0: is not a group that may be hidden",
    ),
    (
        "hidden capacity",
        at("hidden", ["lines.capacity"]),
        "hidden.0: is not a group that may be hidden",
    ),
    (
        "hidden yield twice",
        at("hidden", ["lines.items.yield", "lines.items.yield"]),
        "hidden.1: repeats lines.items.yield",
    ),
    (
        "stock in an unknown warehouse",
        at("start.stock.north-depot", {"chip": "1"}),
        "start.stock.north-depot: is not a warehouse",
    ),
    (
        "stock of an item the warehouse does not accept",
        with_centre(at("start.stock.centre", {"chip": "1"})),
        "start.stock.centre.chip: is not accepted by the warehouse",
    ),
    (
        "stock over the capacity of a second warehouse",
        with_centre(at("start.stock.centre", {"monitor": "30"}), capacity="4.000"),
        "start.stock.centre: takes more space than the warehouse has",
    ),
    (
        "order into a warehouse that does not accept it",
        with_centre(starting_supplier_order(warehouse="centre")),
        "start.supplier_orders.0.warehouse: does not accept the material",
    ),
    (
        "order into an unknown warehouse",
        with_centre(starting_supplier_order(warehouse="north-depot")),
        "start.supplier_orders.0.warehouse: is not a warehouse",
    ),
    (
        "order without a warehouse among several",
        with_centre(starting_supplier_order()),
        "start.supplier_orders.0.warehouse: Field required",
    ),
    (
        "strength above 1",
        disruption("supplier_outage", "all", strength="1.2000"),
        "disruptions.0.strength: Input should be less than or equal to 1",
    ),
    (
        "shape factor below 0",
        shape("step", period=1, factor="-0.1000"),
        "demand_shapes.0.factor: Input should be greater than or equal to 0",
    ),
    (
        "disruption factor 0",
        disruption("price_change", "all", factor="0.0000"),
        "disruptions.0.factor: Input should be greater than 0",
    ),
    (
        "price cut below the cancellation fee",
        price_cut_below_cancellation_fee,
        "disruptions.0.factor: takes the price of chip below its cancellation fee",
    ),
    (
        "price cut below the salvage value at a tier",
        price_cut_below_salvage_value_at_a_tier,
        "disruptions.0.factor: takes the price of chip below its salvage value",
    ),
    (
        "yield drop above 1",
        disruption("yield_drop", "all", strength="1.2000"),
        "disruptions.0.strength: Input should be less than or equal to 1",
    ),
    (
        "yield drop on a supplier",
        disruption("yield_drop", ["chip-maker"], strength="0.2000"),
        "disruptions.0.target: names chip-maker, not one of its kind",
    ),
    (
        "yield drop without duration",
        without_duration(disruption("yield_drop", "all", strength="0.2000")),
        "disruptions.0.duration: Field required",
    ),
    (
        "yield drop with duration 0",
        disruption("yield_drop", "all", strength="0.2000", duration=0),
        "disruptions.0.duration: Input should be greater than or equal to 1",
    ),
    (
        "visible before period 1",
        disruption("yield_drop", "all", strength="0.2000", notice=1),
        "disruptions.0.notice: is visible before period 1",
    ),
    (
        "notice above the start",
        disruption("supplier_outage", "all", strength="0.5000", start=2, notice=3),
        "disruptions.0.notice: is visible before period 1",
    ),
    (
        "notice below 0",
        disruption("supplier_outage", "all", strength="0.5000", notice=-1),
        "disruptions.0.notice: Input should be greater than or equal to 0",
    ),
    (
        "line breakdown with duration",
        disruption("line_breakdown", "all", loss="0.5", duration=1),
        "disruptions.0.duration: Extra inputs are not permitted",
    ),
    (
        "cash with 5 places",
        at("start.cash", "1.00001"),
        "start.cash: has more than 4 places",
    ),
    (
        "empty season",
        shape("season", factors=[], period_length=1),
        (
            "demand_shapes.0.factors: Value should have at least 1 item after "
            "validation, not 0"
        ),
    ),
    (
        "season period length 0",
        shape("season", factors=["1"], period_length=0),
        "demand_shapes.0.period_length: Input should be greater than or equal to 1",
    ),
    (
        "ramp backwards",
        shape("ramp", first=9, last=5, from_factor="1", to_factor="2"),
        "demand_shapes.0.last: is not after first",
    ),
    (
        "trend rate -1",
        shape("trend", rate="-1.0000"),
        "demand_shapes.0.rate: Input should be greater than -1",
    ),
    (
        "price change below salvage",
        disruption("price_change", ["chip"], factor="0.1000"),
        "disruptions.0.factor: takes the price of chip below its salvage value",
    ),
    (
        "no chips in time",
        no_chips_in_time,
        "horizon: chip cannot arrive within it and is not at hand",
    ),
    (
        "no alternative chips in time",
        no_alternative_chips_in_time,
        "horizon: chip-b cannot arrive within it and is not at hand",
    ),
    (
        "no chips in time without express",
        chips_in_lead_time(6, None),
        "horizon: chip cannot arrive within it and is not at hand",
    ),
    (
        "no chips in time at the largest express lead time",
        chips_in_lead_time(6, {"min": 1, "max": 4}),
        "horizon: chip cannot arrive within it and is not at hand",
    ),
    (
        "horizon 0",
        at("horizon", 0),
        "horizon: Input should be greater than or equal to 1",
    ),
    (
        "horizon 521",
        at("horizon", 521),
        "horizon: Input should be less than or equal to 520",
    ),
    (
        "duration 0",
        disruption("supplier_outage", "all", strength="0.5", duration=0),
        "disruptions.0.duration: Input should be greater than or equal to 1",
    ),
    (
        "delay 0",
        disruption("transport_delay", "all", delay=0),
        "disruptions.0.delay: Input should be greater than or equal to 1",
    ),
    (
        "supplier order of 0",
        starting_supplier_order(quantity="0"),
        "start.supplier_orders.0.quantity: Input should be greater than 0",
    ),
    (
        "customer order of 0",
        starting_customer_order(quantity="0"),
        "start.customer_orders.0.quantity: Input should be greater than 0",
    ),
    ("missing horizon", delete_at("horizon"), "horizon: Field required"),
    (
        "written target naming a supplier twice",
        disruption("supplier_outage", ["chip-maker", "chip-maker"], strength="0.5000"),
        "disruptions.0.target.1: repeats chip-maker",
    ),
    (
        "disruption start after the horizon",
        disruption("supplier_outage", ["chip-maker"], strength="0.5000", start=6),
        "disruptions.0.start: is not from 1 to the horizon",
    ),
    (
        "due after the horizon",
        starting_customer_order(due=6),
        "start.customer_orders.0.due: is not from 1 to the horizon",
    ),
]
