import copy
from typing import Any, cast

from factory_simulator.api.core.numbers import read_json_bytes, validate
from factory_simulator.api.schemas.scenario import ScenarioCreate
from factory_simulator.api.services.examples import EXAMPLES
from factory_simulator.api.services.readers.manifest import read_factory
from factory_simulator.api.services.readers.scenario import to_scenario
from factory_simulator.engine import (
    Factory,
    Scenario,
    World,
    draw_world,
)

# A manifest and a scenario as JSON bodies.
type FactoryBodies = tuple[dict[str, Any], dict[str, Any]]


# One material, component, product, supplier, customer, line and warehouse.
def tiny_manifest() -> dict[str, Any]:
    return {
        "name": "Tiny factory",
        "materials": {
            "chip": {
                "space": "0.010",
                "storage_cost": "0.0020",
                "salvage_value": "0.1000",
            },
        },
        "components": {
            "board": {
                "space": "0.020",
                "storage_cost": "0.0100",
                "salvage_value": "0.5000",
                "recipes": {"standard": {"chip": "2.000"}},
            },
        },
        "products": {
            "monitor": {
                "space": "0.150",
                "storage_cost": "0.1000",
                "salvage_value": "2.0000",
                "recipes": {"standard": {"board": "2.000"}},
            },
        },
        "suppliers": {
            "chip-maker": {
                "catalogue": {
                    "chip": {
                        "price": "0.5000",
                        "lead_time": 2,
                        "max_quantity": "1000.000",
                        "punctuality": "1.0000",
                        "delay": 1,
                        "completeness": "1.0000",
                        "acceptance": "1.0000",
                    },
                },
            },
        },
        "customers": {
            "distributor": {
                "products": {
                    "monitor": {
                        "price": "50.0000",
                        "transport_cost": "1.0000",
                        "demand": "4.000",
                        "lead_time": 0,
                        "patience": 1,
                        "late_penalty": "2.0000",
                        "lost_sale_penalty": "10.0000",
                    },
                },
            },
        },
        "lines": {
            "line-1": {
                "capacity": "10.000",
                "wear_per_period": "0.0100",
                "wear_per_hour": "0.0020",
                "breakdown_chance": "0.0000",
                "breakdown_loss": "0.0000",
                "repair_cost": "0.0000",
                "repair_time": "1.000",
                "repair_limit": "1.0000",
                "items": {
                    "board": {"time": "0.100", "cost": "1.0000", "yield": "0.9000"},
                    "monitor": {"time": "0.500", "cost": "2.0000", "yield": "1.0000"},
                },
            },
        },
        "warehouses": {"main": {"capacity": "100.000"}},
        "cash": {
            "credit_limit": "0.0000",
            "credit_interest": "0.0005",
            "debit_interest": "0.0005",
            "overdraft_interest": "0.0005",
        },
    }


# Five periods starting with cash 1000 and some stock of every item.
def tiny_scenario() -> dict[str, Any]:
    return {
        "name": "Tiny scenario",
        "horizon": 5,
        "start": {
            "cash": "1000",
            "stock": {"main": {"chip": "100", "board": "10", "monitor": "5"}},
        },
    }


# The tiny factory without storage cost, wear, yield loss or interest: demand 4 due at
# once and lost at the end of its period, chips one period away.
def plain_tiny_manifest() -> dict[str, Any]:
    manifest = tiny_manifest()
    manifest["name"] = "Plain tiny factory"
    pair = manifest["customers"]["distributor"]["products"]["monitor"]
    pair |= {"demand": "4.000", "lead_time": 0, "patience": 0}
    for kind in ("materials", "components", "products"):
        for item in manifest[kind].values():
            item["storage_cost"] = "0.0000"
    line = manifest["lines"]["line-1"]
    line |= {"wear_per_period": "0.0000", "wear_per_hour": "0.0000"}
    for line_item in line["items"].values():
        line_item["yield"] = "1.0000"
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["lead_time"] = 1
    for rate in ("credit_interest", "debit_interest", "overdraft_interest"):
        manifest["cash"][rate] = "0.0000"
    return manifest


# Three periods of the plain tiny factory from cash 1000, 16 chips and 8 boards.
def plain_tiny_scenario() -> dict[str, Any]:
    return {
        "name": "Plain tiny scenario",
        "horizon": 3,
        "start": {
            "cash": "1000",
            "stock": {"main": {"chip": "16", "board": "8", "monitor": "0"}},
        },
    }


# The plain tiny factory for 20 periods from cash 1000 and no stock, whose demand of 4
# monitors a period ends in period 2.
def withdrawn_demand_bodies() -> FactoryBodies:
    withdrawal = {"kind": "step", "target": "all", "period": 2, "factor": "0.0000"}
    scenario: dict[str, Any] = plain_tiny_scenario() | {
        "horizon": 20,
        "start": {"cash": "1000", "stock": {}},
        "demand_shapes": [withdrawal],
    }
    return plain_tiny_manifest(), scenario


# The plain tiny factory with a hidden uniform demand from 0 to 10 and seasons of 10
# periods at factors 0.0001 and 1, for 20 periods from cash 1000, 16 chips and 8 boards.
def intermittent_demand_bodies() -> FactoryBodies:
    manifest = plain_tiny_manifest()
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms["demand"] = {"min": "0.000", "max": "10.000"}
    season = {
        "kind": "season",
        "target": "all",
        "factors": ["0.0001", "1.0000"],
        "period_length": 10,
    }
    scenario: dict[str, Any] = plain_tiny_scenario() | {
        "horizon": 20,
        "hidden": ["customers.products.demand"],
        "demand_shapes": [season],
    }
    return manifest, scenario


# The plain tiny factory with a uniform yield of boards from 0.8 to 1, hidden.
def hidden_yield_bodies() -> FactoryBodies:
    manifest = plain_tiny_manifest()
    board = manifest["lines"]["line-1"]["items"]["board"]
    board["yield"] = {"min": "0.8000", "max": "1.0000"}
    scenario = plain_tiny_scenario() | {"hidden": ["lines.items.yield"]}
    return manifest, scenario


# The plain tiny factory with a board yield of 0.6 and no recurring demand, from 2
# chips and an order of one monitor due in period 3.
def yield_partition_bodies() -> FactoryBodies:
    manifest = plain_tiny_manifest()
    manifest["lines"]["line-1"]["items"]["board"]["yield"] = "0.6000"
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    scenario = plain_tiny_scenario()
    scenario["start"] = {
        "cash": "1000",
        "stock": {"main": {"chip": "2"}},
        "customer_orders": [
            {"customer": "distributor", "product": "monitor", "quantity": "1", "due": 3}
        ],
    }
    return manifest, scenario


# The world of a future minimum: the plain tiny factory for 5 periods from an
# empty start, one order of 4 monitors due in period 5 and no other demand. The 16 chips
# it needs come in orders of at least 20, at 0.5000, and at 0.5500 in period 2.
def future_minimum_bodies() -> FactoryBodies:
    manifest = plain_tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["min_quantity"] = "20.000"
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    change = {
        "kind": "price_change",
        "target": ["chip"],
        "start": 2,
        "duration": 1,
        "factor": "1.1000",
        "notice": 0,
    }
    order = {"customer": "distributor", "product": "monitor", "quantity": "4", "due": 5}
    scenario: dict[str, Any] = plain_tiny_scenario() | {
        "horizon": 5,
        "start": {"cash": "1000", "stock": {}, "customer_orders": [order]},
        "disruptions": [change],
    }
    return manifest, scenario


# The plain tiny factory for 3 periods from cash 1000, no stock and no demand: a
# starting order of 10 chips at 0.5000, which no order needs, arrives in period 2, and
# a chip is worth 0.1000 at the end.
def unwanted_order_bodies() -> FactoryBodies:
    manifest = plain_tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    order = {"supplier": "chip-maker", "material": "chip", "quantity": "10"}
    scenario = plain_tiny_scenario()
    scenario["start"] = {
        "cash": "1000",
        "stock": {},
        "supplier_orders": [order | {"arrival": 2}],
    }
    return manifest, scenario


# One period of the plain tiny factory with no demand: `main` holds 2 chips of space
# 0.010 and the line, `buffer` takes materials only, the warehouse `remote` holds 1
# board of space 0.020 at a storage factor of 100, each of capacity 0.020, and a board
# costs 1.0000 a period to store. Free routes of lead time 0 go from `main` to
# `buffer` and from `remote` to `main`.
def ordered_transfer_bodies(
    remote: str = "remote",
) -> FactoryBodies:
    manifest = plain_tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    manifest["components"]["board"]["storage_cost"] = "1.0000"
    manifest["warehouses"] = {
        "main": {"capacity": "0.020"},
        "buffer": {"capacity": "0.020", "accepts": ["materials"]},
        remote: {"capacity": "0.020", "storage_factor": "100.0000"},
    }
    manifest["lines"]["line-1"]["warehouse"] = "main"
    route = {"cost": "0.0000", "lead_time": 0}
    manifest["routes"] = {"main": {"buffer": route}, remote: {"main": route}}
    scenario = plain_tiny_scenario()
    scenario["horizon"] = 1
    scenario["start"] = {
        "cash": "1000",
        "stock": {"main": {"chip": "2"}, "buffer": {}, remote: {"board": "1"}},
    }
    return manifest, scenario


# The world of a full warehouse before a changeover: the plain tiny factory for 3
# periods with no recurring demand, a warehouse of capacity 1, boards of space 0.100
# and monitors of 0.020, and a line of 3 hours that takes 1 hour a unit of either and
# pays a changeover of 0.1000 to either. The start holds 60 chips and 4 boards, which
# fill the warehouse, the line is set for boards, and starting orders ask for 1
# monitor due in period 2 and 2 due in period 3. A changeover time, when given, is
# the hours of a changeover to boards.
def full_warehouse_bodies(
    board_changeover_time: str | None = None,
) -> FactoryBodies:
    manifest = plain_tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    manifest["components"]["board"]["space"] = "0.100"
    manifest["products"]["monitor"]["space"] = "0.020"
    manifest["warehouses"]["main"]["capacity"] = "1.000"
    line = manifest["lines"]["line-1"]
    line["capacity"] = "3.000"
    for line_item in line["items"].values():
        line_item |= {"time": "1.000", "changeover_cost": "0.1000"}
    if board_changeover_time is not None:
        line["items"]["board"]["changeover_time"] = board_changeover_time
    scenario = plain_tiny_scenario()
    order = {"customer": "distributor", "product": "monitor"}
    scenario["start"] = {
        "cash": "1000",
        "stock": {"main": {"chip": "60.000", "board": "4.000"}},
        "set_for": {"line-1": "board"},
        "customer_orders": [
            order | {"quantity": "1.000", "due": 2},
            order | {"quantity": "2.000", "due": 3},
        ],
    }
    return manifest, scenario


# The world of repeated immediate transfers: the plain tiny factory for one period
# from cash 1000, 1 chip in `main` and an empty `annex`, each of capacity 1000, every
# item of space 1000, no demand, buys and line hours of 0.001, and routes both ways of
# lead time 0 at a cost of 20000000000000000000000 a unit.
def transfer_bound_bodies(
    horizon: int = 1, cost: str = "20000000000000000000000.0000"
) -> FactoryBodies:
    manifest = plain_tiny_manifest()
    for kind in ("materials", "components", "products"):
        for item in manifest[kind].values():
            item["space"] = "1000.000"
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["max_quantity"] = "0.001"
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    manifest["lines"]["line-1"] |= {"capacity": "0.001", "warehouse": "main"}
    manifest["warehouses"] = {
        "main": {"capacity": "1000.000"},
        "annex": {"capacity": "1000.000"},
    }
    route = {"cost": cost, "lead_time": 0}
    manifest["routes"] = {"main": {"annex": route}, "annex": {"main": route}}
    scenario = plain_tiny_scenario()
    scenario["horizon"] = horizon
    stock = {"main": {"chip": "1.000"}, "annex": {}}
    scenario["start"] = {"cash": "1000", "stock": stock}
    return manifest, scenario


# The world of a large selling price: the plain tiny factory for one period from cash
# 1000, 0.001 chip and 1 monitor, a starting order of 1 monitor due now at a price, no
# demand, chips up to a largest quantity, line hours of 0.001 and a warehouse of
# capacity 1.
def solver_scale_bodies(
    price: str = "1000000000000000000.0000", max_quantity: str = "0.001"
) -> FactoryBodies:
    manifest = plain_tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["max_quantity"] = (
        max_quantity
    )
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms |= {"price": price, "demand": "0.000"}
    manifest["lines"]["line-1"]["capacity"] = "0.001"
    manifest["warehouses"]["main"]["capacity"] = "1.000"
    scenario = plain_tiny_scenario()
    scenario["horizon"] = 1
    stock = {"main": {"chip": "0.001", "monitor": "1.000"}}
    order = {"customer": "distributor", "product": "monitor", "quantity": "1.000"}
    scenario["start"] = {
        "cash": "1000",
        "stock": stock,
        "customer_orders": [order | {"due": 1}],
    }
    return manifest, scenario


# The 5001 transfers of one chip of the world of repeated immediate transfers, from
# `main` to `annex` and back in turn.
def back_and_forth_transfers(count: int = 5001) -> list[dict[str, Any]]:
    ends = [("main", "annex"), ("annex", "main")]
    return [
        {
            "kind": "transfer",
            "item": "chip",
            "quantity": "1.000",
            "source": ends[position % 2][0],
            "destination": ends[position % 2][1],
        }
        for position in range(count)
    ]


# The plain tiny factory with chips of completeness 0.6 and at most 1 bought a period,
# and no demand, from cash 1000 and no stock.
def delivery_partition_bodies() -> FactoryBodies:
    manifest = plain_tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"] |= {
        "completeness": "0.6000",
        "max_quantity": "1.000",
    }
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    scenario = plain_tiny_scenario()
    scenario["start"] = {"cash": "1000", "stock": {}}
    return manifest, scenario


# A test scenario of the example manifest: 52 periods from an empty start.
def example_scenario() -> dict[str, Any]:
    return {"horizon": 52, "start": {"cash": "0"}}


EXAMPLE_BUYS = [
    ("apac-chips", "microchip", "500"),
    ("emea-electronic-parts", "passive-kit", "800"),
    ("emea-electronic-parts", "pcb-blank", "600"),
    ("emea-electronic-parts", "connector-pins", "700"),
    ("amer-metals", "copper-wire", "1500"),
    ("amer-metals", "steel-sheet", "600"),
    ("apac-displays-plastics", "lcd-panel", "100"),
    ("apac-displays-plastics", "plastic-resin", "150"),
    ("amer-metals", "passive-kit", "200"),
    ("emea-electronic-parts", "lcd-panel", "20"),
    ("emea-electronic-parts", "copper-wire", "300"),
]
EXAMPLE_COMPONENTS = [
    ("smt-line", "control-board", "180"),
    ("smt-line", "power-module", "250"),
    ("smt-line", "sensor-module", "80"),
    ("module-assembly-line", "display-unit", "90"),
    ("module-assembly-line", "cable-harness", "160"),
    ("moulding-line", "enclosure", "250"),
    ("module-assembly-line", "power-module", "40"),
]
EXAMPLE_PRODUCTS = [
    ("final-assembly-line", "industrial-controller", "80"),
    ("final-assembly-line", "smart-monitor", "80"),
    ("final-assembly-line", "sensor-gateway", "70"),
]


# Fixed buys, produces and shipments of the example manifest in a period.
def example_decisions(period: int) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    if period % 4 == 1 and period <= 45:
        decisions += [
            {
                "kind": "buy",
                "supplier": supplier,
                "material": material,
                "quantity": quantity,
                "warehouse": "main-plant",
            }
            for supplier, material, quantity in EXAMPLE_BUYS
        ]
    if period >= 6:
        decisions += [
            {"kind": "produce", "line": line, "item": item, "quantity": quantity}
            for line, item, quantity in EXAMPLE_COMPONENTS
        ]
    if period >= 8:
        decisions += [
            {"kind": "produce", "line": line, "item": item, "quantity": quantity}
            for line, item, quantity in EXAMPLE_PRODUCTS
        ]
    if period >= 10:
        decisions += [
            {
                "kind": "ship",
                "order": f"order-{period}-{number}",
                "quantity": "5",
                "warehouse": "main-plant",
            }
            for number in range(1, 11)
        ]
    return decisions


# The tiny factory whose line pays a changeover of 1 hour and 50.0000 to each item.
def changeover_manifest() -> dict[str, Any]:
    manifest = tiny_manifest()
    for terms in manifest["lines"]["line-1"]["items"].values():
        terms.update(changeover_time="1.000", changeover_cost="50.0000")
    return manifest


# The tiny factory whose chips cost 5.0000, 4.6000 from 1000 units and the given price
# from 5000 units, with room and credit for such buys.
def discounted_manifest(high_tier_price: object = "4.3000") -> dict[str, Any]:
    manifest = tiny_manifest()
    manifest["warehouses"]["main"]["capacity"] = "1000.000"
    manifest["cash"]["credit_limit"] = "100000.0000"
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"].update(
        price="5.0000",
        max_quantity="20000.000",
        lead_time=3,
        discounts=[
            {"from": "1000.000", "price": "4.6000"},
            {"from": "5000.000", "price": high_tier_price},
        ],
    )
    return manifest


# The tiny factory with a second warehouse `centre` of capacity 50 for products, the
# line in `main`; keys given replace those of `centre`.
def two_warehouse_manifest(**centre: object) -> dict[str, Any]:
    manifest = tiny_manifest()
    manifest["warehouses"]["centre"] = {
        "capacity": "50.000",
        "accepts": ["products"],
    } | centre
    manifest["lines"]["line-1"]["warehouse"] = "main"
    return manifest


# The tiny factory whose chip maker is in the region `apac`, which gives the chip its
# price 0.5000 and a punctuality from 0 to 0.0100.
def apac_supplier_manifest() -> dict[str, Any]:
    manifest = tiny_manifest()
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    del entry["price"]
    del entry["punctuality"]
    manifest["suppliers"]["chip-maker"]["groups"] = ["apac"]
    manifest["groups"] = {
        "apac": {
            "kind": "region",
            "defaults": {
                "catalogue": {
                    "price": "0.5000",
                    "punctuality": {"min": "0.0000", "max": "0.0100"},
                }
            },
        }
    }
    return manifest


# The tiny factory of the frozen test world: normal demand, triangular price and yield,
# 12 periods.
def frozen_bodies() -> FactoryBodies:
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = {
        "min": "30.000",
        "max": "50.000",
        "distribution": "normal",
        "mean": "40.000",
        "sd": "5.000",
    }
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["price"] = {
        "min": "0.4000",
        "max": "0.6000",
        "distribution": "triangular",
        "mode": "0.5000",
    }
    manifest["lines"]["line-1"]["items"]["board"]["yield"] = {
        "min": "0.8000",
        "max": "0.9500",
        "distribution": "triangular",
        "mode": "0.9000",
    }
    scenario = tiny_scenario()
    scenario["horizon"] = 12
    return manifest, scenario


# The frozen factory with a lognormal demand and a lognormal yield.
def lognormal_bodies() -> FactoryBodies:
    manifest, scenario = frozen_bodies()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = {
        "min": "20.000",
        "max": "120.000",
        "distribution": "lognormal",
        "median": "40.000",
        "spread": "0.5000",
    }
    manifest["lines"]["line-1"]["items"]["board"]["yield"] = {
        "min": "0.8000",
        "max": "0.9500",
        "distribution": "lognormal",
        "median": "0.9000",
        "spread": "0.0500",
    }
    return manifest, scenario


# The plain tiny factory with a normal demand from 1 to 9, mean 5 and sd 10**20, so
# narrow that its cut distribution is flat, over 10 periods.
def narrow_demand_bodies() -> FactoryBodies:
    manifest = plain_tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = {
        "min": "1.000",
        "max": "9.000",
        "distribution": "normal",
        "mean": "5.000",
        "sd": "100000000000000000000.000",
    }
    return manifest, plain_tiny_scenario() | {"horizon": 10}


# The JSON bodies of the example manifest and of a scenario of its library.
def example_bodies(scenario_name: str) -> FactoryBodies:
    manifest = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    scenario = read_json_bytes(
        (EXAMPLES / "scenarios" / f"{scenario_name}.json").read_bytes()
    )
    return cast(dict[str, Any], manifest), cast(dict[str, Any], scenario)


# Validate a manifest and a scenario given as JSON bodies and convert them.
def to_engine(
    manifest: dict[str, Any], scenario: dict[str, Any]
) -> tuple[Factory, Scenario]:
    factory = read_factory(manifest)
    return factory, to_scenario(validate(ScenarioCreate, scenario))


# Draw the world of a manifest and a scenario given as JSON bodies.
def draw_world_of_bodies(
    manifest: dict[str, Any], scenario: dict[str, Any], seed: int = 0
) -> World:
    factory, read_scenario = to_engine(manifest, scenario)
    return draw_world(factory, read_scenario, seed)


# The tiny factory with two more materials, `chip-b` and `pcb`, and two recipes of the
# board: `standard` of 2 chips and 1 pcb, the default, and `alternative` of 1 pcb and
# 2 of `chip-b`.
def two_recipe_manifest() -> dict[str, Any]:
    manifest = tiny_manifest()
    for material_id in ("chip-b", "pcb"):
        manifest["materials"][material_id] = copy.deepcopy(
            manifest["materials"]["chip"]
        )
        manifest["suppliers"]["chip-maker"]["catalogue"][material_id] = copy.deepcopy(
            manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
        )
    manifest["components"]["board"]["recipes"] = {
        "standard": {"chip": "2.000", "pcb": "1.000"},
        "alternative": {"pcb": "1.000", "chip-b": "2.000"},
    }
    manifest["components"]["board"]["default_recipe"] = "standard"
    manifest["lines"]["line-1"]["items"]["board"]["time"] = "0.050"
    manifest["warehouses"]["main"]["capacity"] = "1000.000"
    return manifest


# The tiny factory with a second product `tablet` made and bought as the monitor,
# demand 40 of each, and the monitor alone in the segment `new-devices`.
def two_product_manifest() -> dict[str, Any]:
    manifest = tiny_manifest()
    manifest["products"]["tablet"] = copy.deepcopy(manifest["products"]["monitor"])
    manifest["lines"]["line-1"]["items"]["tablet"] = dict(
        manifest["lines"]["line-1"]["items"]["monitor"]
    )
    pairs = manifest["customers"]["distributor"]["products"]
    pairs["monitor"]["demand"] = "40.000"
    pairs["tablet"] = dict(pairs["monitor"])
    manifest["products"]["monitor"]["groups"] = ["new-devices"]
    manifest["groups"] = {"new-devices": {"kind": "segment"}}
    return manifest


# The tiny scenario with a starting order of chips arriving in period 3.
def starting_chips_scenario(quantity: str) -> dict[str, Any]:
    scenario = tiny_scenario()
    scenario["start"]["supplier_orders"] = [
        {
            "supplier": "chip-maker",
            "material": "chip",
            "quantity": quantity,
            "arrival": 3,
        }
    ]
    return scenario


# The scenarios of the library of the example factory, as the library names them.
LIBRARY = (
    "steady-market",
    "seasonal-demand",
    "growth",
    "decline",
    "demand-surge",
    "product-life-cycle",
    "supplier-outage",
    "material-shortage",
    "quality-crisis",
    "transport-delays",
    "line-breakdown",
    "frequent-breakdowns",
    "cash-squeeze",
    "full-warehouse",
    "regional-crisis",
    "surge-and-breakdown",
    "forecasts",
    "notice",
    "hidden-groups",
    "capacity-cut",
    "yield-drop",
    "price-change",
    "demand-step",
)
