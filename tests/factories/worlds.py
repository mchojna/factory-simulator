from typing import Any

from factories.bodies import (
    draw_world_of_bodies,
    example_bodies,
    tiny_manifest,
    tiny_scenario,
    two_warehouse_manifest,
)
from factory_simulator.engine import World

# Two discount tiers of the chip: 4.6000 from 1000 units, 4.3000 from 5000.
TIERS = [
    {"from": "1000.000", "price": "4.6000"},
    {"from": "5000.000", "price": "4.3000"},
]


# The tiny factory with the warehouse `centre` for products and a transport cost of
# 2.5000: 20 monitors in `centre`, the rest in `main`, and one order of 10 monitors due
# in period 3. Keys given replace those of `centre`.
def centre_world(
    centre_stock: dict[str, str] | None = None,
    main_stock: dict[str, str] | None = None,
    **centre: object,
) -> World:
    manifest = two_warehouse_manifest(**centre)
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms["transport_cost"] = "2.5000"
    scenario = tiny_scenario()
    scenario["start"]["stock"] = {
        "main": main_stock or {"chip": "100", "board": "10", "monitor": "4"},
        "centre": centre_stock or {"monitor": "20"},
    }
    scenario["start"]["customer_orders"] = [
        {"customer": "distributor", "product": "monitor", "quantity": "10", "due": 3}
    ]
    return draw_world_of_bodies(manifest, scenario)


# The tiny factory with 900 chips of space 0.001 in `main` of capacity 1 and an empty
# warehouse `spare` of capacity 10.
def spare_world() -> World:
    manifest = tiny_manifest()
    manifest["materials"]["chip"]["space"] = "0.001"
    manifest["warehouses"]["main"]["capacity"] = "1.000"
    manifest["warehouses"]["spare"] = {"capacity": "10.000"}
    manifest["lines"]["line-1"]["warehouse"] = "main"
    scenario = tiny_scenario()
    scenario["start"]["stock"] = {"main": {"chip": "900"}}
    return draw_world_of_bodies(manifest, scenario)


# The tiny factory with chips at 5.0000 and the discount tiers, room for 1000 units of
# space, a credit limit of 100000.0000 and 8 periods; keys given replace those of the
# chip entry.
def tiered_chip_world(
    scenario: dict[str, Any] | None = None,
    disruptions: list[dict[str, Any]] | None = None,
    min_quantity: str | None = None,
    **terms: object,
) -> World:
    manifest = tiny_manifest()
    manifest["warehouses"]["main"]["capacity"] = "1000.000"
    manifest["cash"]["credit_limit"] = "100000.0000"
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    entry.update(
        {"price": "5.0000", "max_quantity": "20000.000", "discounts": TIERS} | terms
    )
    if min_quantity is not None:
        entry["min_quantity"] = min_quantity
    scenario = scenario or tiny_scenario()
    scenario["horizon"] = 8
    scenario["disruptions"] = disruptions or []
    return draw_world_of_bodies(manifest, scenario)


# The tiny factory whose line makes boards in 0.600 hours with no wear, 6 periods and
# 200 chips; keys given are added to the scenario.
def plan_world(horizon: int = 6, chips: str = "200", **scenario_keys: object) -> World:
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(wear_per_period="0.0000", wear_per_hour="0.0000")
    manifest["lines"]["line-1"]["items"]["board"]["time"] = "0.600"
    scenario = tiny_scenario()
    scenario["horizon"] = horizon
    scenario["start"]["stock"]["main"]["chip"] = chips
    scenario.update(scenario_keys)
    return draw_world_of_bodies(manifest, scenario)


# The tiny factory whose line has 4 overtime hours at 45.0000 an hour and 100 boards in
# stock; keys given replace those of the line.
def overtime_world(
    condition: str = "1.0000",
    disruptions: list[dict[str, Any]] | None = None,
    **line_terms: object,
) -> World:
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(
        {"overtime_hours": "4.000", "overtime_cost": "45.0000"} | line_terms
    )
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["board"] = "100"
    scenario["start"]["condition"] = {"line-1": condition}
    scenario["disruptions"] = disruptions or []
    return draw_world_of_bodies(manifest, scenario)


# The tiny factory with a route from `main` to `centre`, a warehouse for products with
# a storage factor of 0.6000, and 100 chips and 10 monitors in `main`.
def transfer_world(
    lead_time: int = 1,
    centre_capacity: str = "50.000",
    centre_stock: dict[str, str] | None = None,
) -> World:
    manifest = tiny_manifest()
    manifest["warehouses"]["centre"] = {
        "capacity": centre_capacity,
        "accepts": ["products"],
        "storage_factor": "0.6000",
    }
    manifest["lines"]["line-1"]["warehouse"] = "main"
    manifest["routes"] = {
        "main": {"centre": {"cost": "0.2000", "lead_time": lead_time}}
    }
    scenario = tiny_scenario()
    scenario["start"]["stock"] = {
        "main": {"chip": "100", "monitor": "10"},
        "centre": centre_stock or {},
    }
    return draw_world_of_bodies(manifest, scenario)


# The tiny factory with no demand, 20 monitors in stock and starting orders of a
# quantity of monitors, each due in one period.
def one_order_world(
    quantity: str, due: int, patience: int = 1, orders: int = 1
) -> World:
    manifest = tiny_manifest()
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms.update({"demand": "0", "patience": patience})
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["monitor"] = "20"
    scenario["start"]["customer_orders"] = [
        {
            "customer": "distributor",
            "product": "monitor",
            "quantity": quantity,
            "due": due,
        }
        for _ in range(orders)
    ]
    return draw_world_of_bodies(manifest, scenario)


# The tiny factory whose monitors take 2 periods to make at a yield of 0.9500, 100
# boards and 5 monitors in stock and 6 periods.
def monitor_world(
    lead_time: int = 2,
    horizon: int = 6,
    disruptions: list[dict[str, Any]] | None = None,
    monitors: str = "5",
) -> World:
    manifest = tiny_manifest()
    manifest["lines"]["line-1"]["items"]["monitor"].update(
        lead_time=lead_time, **{"yield": "0.9500"}
    )
    scenario = tiny_scenario()
    scenario["horizon"] = horizon
    scenario["start"]["stock"]["main"].update(board="100", monitor=monitors)
    scenario["disruptions"] = disruptions or []
    return draw_world_of_bodies(manifest, scenario)


# The tiny factory over 6 periods with a rule that starts an outage of one period at
# `chip-maker` in every period it can, at a notice; seed 4.
def random_world(notice: int) -> World:
    rule = {
        "name": "outage",
        "kind": "supplier_outage",
        "target": ["chip-maker"],
        "chance": "1.0000",
        "duration": 1,
        "strength": {"min": "0.1000", "max": "0.9000"},
        "notice": notice,
    }
    scenario = tiny_scenario() | {"horizon": 6, "random_disruptions": [rule]}
    return draw_world_of_bodies(tiny_manifest(), scenario, seed=4)


# Draw the world of the example manifest with a scenario of the library.
def example_world(scenario_name: str, seed: int) -> World:
    return draw_world_of_bodies(*example_bodies(scenario_name), seed=seed)
