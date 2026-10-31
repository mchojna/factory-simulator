import math
from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

import numpy
import pytest
from factories import (
    benchmark_client,
    example_count,
    full_warehouse_bodies,
    groups_written_out,
    largest,
    linear_factories,
    number_text,
    plain_tiny_manifest,
    plain_tiny_scenario,
    play_no_decisions,
    produce,
    recording_program_values,
    recording_solutions,
    records,
    seeds,
    small_factories,
    solver_scale_bodies,
    start_reference,
    yield_partition_bodies,
)
from fastapi.testclient import TestClient
from hypothesis import example, given, settings
from hypothesis import strategies as st
from scipy.optimize import OptimizeResult, milp

from factory_simulator.api.record.models.run import Interaction, Run
from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.models.outputs import Solution
from factory_simulator.benchmark.program import solve as solve_module
from factory_simulator.benchmark.program.decisions import Optimizer
from factory_simulator.benchmark.program.solve import (
    GAP_LIMIT,
    TIME_LIMIT,
    UnsupportedScaleError,
)
from factory_simulator.benchmark.program.world_source import state_of


# The decisions of a stored submission with the keys a test names.
def submitted_keys(
    period: dict[str, Any], keys: tuple[str, ...]
) -> list[dict[str, Any]]:
    step = next(step for step in period["steps"] if step["step"] == "make_decisions")
    return [
        {key: decision[key] for key in keys if key in decision}
        for decision in step["submission"]["decisions"]
    ]


def stored_scenario(
    client: TestClient, manifest: dict[str, Any], scenario: dict[str, Any]
) -> str:
    stored = benchmark.send(client, "POST", "/manifests", manifest)
    path = f"/manifests/{stored['id']}/scenarios"
    return benchmark.send(client, "POST", path, scenario)["id"]


# The run of the reference of a seed of a scenario, started after a run of no
# decisions, and the reference.
def reference_of(
    client: TestClient, scenario_id: str, seed: int, time_limit: float = TIME_LIMIT
) -> tuple[dict[str, Any], Optimizer]:
    nothing, _ = play_no_decisions(client, scenario_id, seed)
    return start_reference(client, scenario_id, seed, nothing["id"], time_limit)


# The plain tiny factory whose line pays a changeover to each of its items.
def plain_changeover_manifest() -> dict[str, Any]:
    manifest = plain_tiny_manifest()
    for item in manifest["lines"]["line-1"]["items"].values():
        item |= {"changeover_time": "0.500", "changeover_cost": "3.0000"}
    return manifest


# `main` starts with 6.209 of its space of 1788 free. The program frees space by making
# `product-1` from `component-1` and fills it with `component-2`; the productions that
# free space round down and free less than the program counts.
def filling_warehouse_bodies() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest: dict[str, Any] = {
        "materials": {
            "material-1": {"space": "2.156", "storage_cost": "1", "salvage_value": "0"}
        },
        "components": {
            "component-1": {
                "space": "1.642",
                "storage_cost": "0",
                "recipes": {"standard": {"material-1": "1"}},
                "salvage_value": "0",
            },
            "component-2": {
                "space": "4.9",
                "storage_cost": "1",
                "recipes": {"standard": {"material-1": "1.033"}},
                "salvage_value": "0",
            },
        },
        "products": {
            "product-1": {
                "space": "1",
                "storage_cost": "1",
                "recipes": {"standard": {"component-1": "3.4"}},
                "salvage_value": "0",
            }
        },
        "suppliers": {
            "supplier-1": {
                "catalogue": {
                    "material-1": {
                        "price": "0",
                        "lead_time": "3",
                        "max_quantity": "1",
                        "punctuality": "1",
                        "delay": "1",
                        "completeness": "1",
                        "acceptance": "1",
                        "express_lead_time": "1",
                        "express_cost": "0",
                    }
                }
            }
        },
        "customers": {
            "customer-1": {
                "products": {
                    "product-1": {
                        "price": "0",
                        "transport_cost": "0",
                        "demand": "0",
                        "lead_time": "0",
                        "patience": "0",
                        "late_penalty": "0",
                        "lost_sale_penalty": "0",
                    }
                }
            }
        },
        "lines": {
            "line-1": {
                "overtime_hours": {"min": "0", "max": "142.4"},
                "overtime_cost": "0",
                "capacity": "0.166",
                "wear_per_period": "0",
                "wear_per_hour": "0",
                "breakdown_chance": "0",
                "breakdown_loss": "0",
                "repair_cost": "0",
                "repair_time": "1",
                "repair_limit": "1",
                "items": {
                    "component-1": {"time": "1", "cost": "6", "yield": "0"},
                    "component-2": {
                        "time": {"min": "2", "max": "3.091"},
                        "cost": "1",
                        "yield": "0.0328",
                    },
                    "product-1": {
                        "time": {
                            "min": "1",
                            "max": "2",
                            "distribution": "triangular",
                            "mode": "2",
                        },
                        "cost": "0",
                        "yield": "0",
                    },
                },
                "warehouse": "main",
            }
        },
        "warehouses": {
            "main": {"storage_factor": "0.7", "capacity": "1788"},
            "warehouse-2": {"capacity": "979"},
        },
        "cash": {
            "credit_limit": "0",
            "credit_interest": "0",
            "debit_interest": "0",
            "overdraft_interest": "0",
        },
        "routes": {"warehouse-2": {"main": {"cost": "0", "lead_time": "1"}}},
    }
    scenario: dict[str, Any] = {
        "horizon": 2,
        "start": {
            "stock": {
                "main": {"material-1": "76", "component-1": "985.344"},
                "warehouse-2": {"material-1": "3"},
            },
            "condition": {"line-1": "0.021"},
        },
    }
    return manifest, scenario


# A linear factory whose line wears, so from period 2 on its hours
# `capacity * condition` fall off the grid of 3 places that the engine rounds them
# down to. Each period it can make less than a thousandth of a unit fewer than the
# program counts. Each unit made uses 1 of the 640 units of `material-2` in stock and
# saves its storage of 99.9999 a period, paid from cash at an overdraft interest of
# 0.7229.
def storing_on_overdraft_bodies() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest: dict[str, Any] = {
        "materials": {
            "material-2": {
                "space": "1.025",
                "storage_cost": "99.9999",
                "salvage_value": "0",
            }
        },
        "components": {
            "component-2": {
                "space": "1",
                "storage_cost": "0",
                "recipes": {"alternative": {"material-2": "1"}},
                "salvage_value": "0",
            }
        },
        "products": {
            "product-1": {
                "space": "1",
                "storage_cost": "0",
                "recipes": {"standard": {"component-2": "1"}},
                "salvage_value": "0",
            }
        },
        "suppliers": {
            "supplier-1": {
                "catalogue": {
                    "material-2": {
                        "price": "0.0246",
                        "lead_time": "1",
                        "max_quantity": "0.273",
                        "punctuality": "0",
                        "delay": "1",
                        "completeness": "0",
                        "acceptance": "0",
                    }
                }
            }
        },
        "customers": {
            "customer-1": {
                "products": {
                    "product-1": {
                        "price": "0",
                        "transport_cost": "0",
                        "demand": "0",
                        "lead_time": "0",
                        "patience": "0",
                        "late_penalty": "0",
                        "lost_sale_penalty": "0",
                    }
                }
            }
        },
        "lines": {
            "line-1": {
                "capacity": "10",
                "wear_per_period": "0.0853",
                "wear_per_hour": "0",
                "breakdown_chance": "0",
                "breakdown_loss": "0",
                "repair_cost": "0",
                "repair_time": "0.001",
                "repair_limit": "0.0001",
                "items": {
                    "component-2": {
                        "time": "1",
                        "cost": "0",
                        "yield": "0",
                        "lead_time": "1",
                    },
                    "product-1": {"time": "1", "cost": "0", "yield": "0"},
                },
            }
        },
        "warehouses": {"main": {"capacity": "656.443"}},
        "cash": {
            "credit_limit": "0",
            "credit_interest": "0.0100",
            "debit_interest": "0.0248",
            "overdraft_interest": "0.7229",
        },
    }
    scenario: dict[str, Any] = {
        "horizon": 5,
        "start": {"cash": "100000", "stock": {"main": {"material-2": "640.432"}}},
    }
    return manifest, scenario


# The most that rounding the quantities of a run down to 3 places can cost, with
# `quantity_counts` the decisions with a quantity in each period. A quantity rounded
# down by less than 0.001 units leaves less than 0.001 units of its item, or of each
# input of its recipe times the recipe quantity, in stock at each close from its
# period to the horizon. A unit of such stock costs at most `most_stored` at a close:
# the largest storage cost of an item or of the inputs of a recipe, times the largest
# storage factor. A cost paid at a close lowers the cash at the end by at most itself
# times 1 plus the highest rate of interest, at that close and at every later one.
def rounding_bound(
    manifest: dict[str, Any], horizon: int, quantity_counts: dict[int, int]
) -> Decimal:
    flat = groups_written_out(manifest)
    items = flat["materials"] | flat["components"] | flat["products"]
    stored = [largest(item["storage_cost"]) for item in items.values()]
    for item in items.values():
        for recipe in item.get("recipes", {}).values():
            inputs = [
                largest(quantity) * largest(items[input_id]["storage_cost"])
                for input_id, quantity in recipe.items()
            ]
            stored.append(sum(inputs, Decimal(0)))
    factors = [
        Decimal(terms.get("storage_factor", "1"))
        for terms in flat["warehouses"].values()
    ]
    most_stored = max(stored) * max(factors)
    rates = ("credit_interest", "debit_interest", "overdraft_interest")
    growth = 1 + max(Decimal(flat["cash"][rate]) for rate in rates)
    bound = Decimal(0)
    for period, count in quantity_counts.items():
        closes = range(period, horizon + 1)
        paid = sum((growth ** (horizon - close + 1) for close in closes), Decimal(0))
        bound += Decimal("0.001") * count * most_stored * paid
    return bound


# The warehouse of a line: the one it names, or the only warehouse of the factory.
def line_warehouse(flat: dict[str, Any], line_id: str) -> str:
    return flat["lines"][line_id].get("warehouse") or next(iter(flat["warehouses"]))


# The space of a unit of a produced item less the space of its inputs, and the space
# of a unit of each input, summed.
def produce_spaces(
    flat: dict[str, Any], decision: dict[str, Any]
) -> tuple[Decimal, Decimal]:
    items = flat["materials"] | flat["components"] | flat["products"]
    recipe = items[decision["item"]]["recipes"][decision["recipe"]]
    inputs = sum(
        (
            Decimal(quantity) * Decimal(items[input_id]["space"])
            for input_id, quantity in recipe.items()
        ),
        Decimal(0),
    )
    each = sum((Decimal(items[input_id]["space"]) for input_id in recipe), Decimal(0))
    return Decimal(items[decision["item"]]["space"]) - inputs, each


# The warehouse a decision frees space in and the space it frees per unit, 0 for a
# decision that frees none. A ship frees at most the space of the largest product.
def freed_space(flat: dict[str, Any], decision: dict[str, Any]) -> tuple[str, Decimal]:
    items = flat["materials"] | flat["components"] | flat["products"]
    if decision["kind"] == "ship":
        largest_space = max(
            Decimal(product["space"]) for product in flat["products"].values()
        )
        return decision["warehouse"], largest_space
    if decision["kind"] == "transfer":
        return decision["source"], Decimal(items[decision["item"]]["space"])
    if decision["kind"] == "produce":
        unit = produce_spaces(flat, decision)[0]
        return line_warehouse(flat, decision["line"]), max(-unit, Decimal(0))
    return "", Decimal(0)


# The warehouse a decision adds space to, the space it adds per unit, and the space of
# a unit of each of its inputs, summed.
def added_space(
    flat: dict[str, Any], decision: dict[str, Any]
) -> tuple[str, Decimal, Decimal]:
    items = flat["materials"] | flat["components"] | flat["products"]
    if decision["kind"] == "transfer":
        return (
            decision["destination"],
            Decimal(items[decision["item"]]["space"]),
            Decimal(0),
        )
    if decision["kind"] == "buy":
        return (
            decision["warehouse"],
            Decimal(items[decision["material"]]["space"]),
            Decimal(0),
        )
    unit, inputs = produce_spaces(flat, decision)
    return line_warehouse(flat, decision["line"]), unit, inputs


# The ships, transfers and productions of a solution as decisions before they are
# rounded down, each one that rounds down to 0 included.
def solution_decisions(solution: Solution) -> list[dict[str, Any]]:
    return [
        *({"kind": "ship", "warehouse": ship.warehouse} for ship in solution.ships),
        *(
            {"kind": "transfer", "source": transfer.source, "item": transfer.item}
            for transfer in solution.transfers
        ),
        *(
            {
                "kind": "produce",
                "line": produced.line,
                "item": produced.item,
                "recipe": produced.recipe,
            }
            for produced in solution.produces
        ),
    ]


# The most space the fit may take from a decision rejected for space. `planned` holds
# the decisions of the solution of its period, also those rounded down to 0, and
# `fits` the fits of the period.
# Each decision that frees space in the warehouse is rounded down by less than 0.001
# units and loses what the fit took from it, and frees that much less than planned.
# The fit takes the shortfall over the space the decision adds per unit, and less than
# 0.001 units more as it rounds down. The inputs of a production are rounded up, and
# at the quantity checked they can free less than 0.001 units of each input more than
# at the quantity kept, which the fit takes too.
def space_fit_allowance(
    manifest: dict[str, Any],
    planned: list[dict[str, Any]],
    fits: list[dict[str, Any]],
    decision: dict[str, Any],
) -> Decimal:
    flat = groups_written_out(manifest)
    warehouse_id, unit, inputs = added_space(flat, decision)
    allowance = Decimal("0.001") * (unit + inputs)
    for other in planned:
        source, freed = freed_space(flat, other)
        if source == warehouse_id:
            allowance += Decimal("0.001") * freed
    for fit in fits:
        source, freed = freed_space(flat, fit["decision"])
        if source == warehouse_id:
            allowance += (fit["before"] - fit["after"]) * freed
    return allowance


# A linear factory whose two lines make `component-2` in each period by its
# alternative recipe, 4.233 units of `material-2` a unit, to empty stock of
# `material-2` that costs 100 a period to store. Each produce is rounded down by up to
# a thousandth of a unit, which keeps up to 0.004233 units of `material-2` in stock at
# every close to the horizon.
def emptying_costly_storage_bodies() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest: dict[str, Any] = {
        "materials": {
            "material-1": {
                "salvage_value": "0.0000",
                "space": "1.000",
                "storage_cost": "0.0627",
            },
            "material-2": {
                "salvage_value": "0.0000",
                "space": "1.273",
                "storage_cost": "100.0000",
            },
        },
        "components": {
            "component-1": {
                "default_recipe": "standard",
                "recipes": {
                    "alternative": {"material-1": "4.999"},
                    "standard": {"material-1": "1.785"},
                },
                "salvage_value": "0.0163",
                "space": "1.225",
                "storage_cost": "1.0621",
            },
            "component-2": {
                "default_recipe": "standard",
                "recipes": {
                    "alternative": {"material-2": "4.233"},
                    "standard": {"material-1": "4.401"},
                },
                "salvage_value": "0.0503",
                "space": "2.529",
                "storage_cost": "0.1425",
            },
        },
        "products": {
            "product-1": {
                "default_recipe": "standard",
                "recipes": {
                    "alternative": {"component-1": "1.278"},
                    "standard": {"component-1": "2.752"},
                },
                "salvage_value": "0.0374",
                "space": "3.810",
                "storage_cost": "0.0739",
            },
            "product-2": {
                "default_recipe": "standard",
                "recipes": {
                    "alternative": {"component-1": "1.838"},
                    "standard": {"component-1": "1.357"},
                },
                "salvage_value": "0.0283",
                "space": "1.109",
                "storage_cost": "5.9644",
            },
        },
        "suppliers": {
            "supplier-1": {
                "catalogue": {
                    "material-1": {
                        "acceptance": "0.1486",
                        "backfill_delay": "0",
                        "cancellation_fee": "0.0000",
                        "completeness": "0.0422",
                        "delay": "1",
                        "lead_time": "1",
                        "max_quantity": "217.301",
                        "price": {"max": "86.7874", "min": "0.0000"},
                        "punctuality": "0.0000",
                    },
                    "material-2": {
                        "acceptance": "0.0096",
                        "backfill_delay": "0",
                        "cancellation_fee": "0.0000",
                        "completeness": "0.0084",
                        "delay": "4",
                        "lead_time": "4",
                        "max_quantity": "116.834",
                        "price": {"max": "3.1202", "min": "0.0068"},
                        "punctuality": "1.0000",
                    },
                },
                "groups": ["suppliers-region-1", "suppliers-tier-2"],
            }
        },
        "customers": {
            "customer-1": {
                "payment_terms": {"max": 0, "min": 0},
                "products": {
                    "product-1": {
                        "demand": {"max": "2.703", "min": "0.369"},
                        "demand_persistence": "0.7625",
                        "late_penalty": "52.1844",
                        "lead_time": "0",
                        "lost_sale_penalty": "0.4677",
                        "patience": "0",
                        "price": "0.6711",
                        "transport_cost": "41.5411",
                    },
                    "product-2": {
                        "demand": {"max": "685.602", "min": "0.436"},
                        "late_penalty": "0.1000",
                        "lead_time": "0",
                        "lost_sale_penalty": "17.4909",
                        "patience": "0",
                        "price": "1.3358",
                        "transport_cost": "0.0074",
                    },
                },
            }
        },
        "lines": {
            "line-1": {
                "breakdown_chance": "0.2713",
                "breakdown_loss": "0.6872",
                "capacity": "31.763",
                "groups": ["lines-region-1", "lines-tier-2"],
                "items": {
                    "component-1": {"cost": "0.0163", "time": "2.364"},
                    "component-2": {
                        "cost": "13.1073",
                        "lead_time": "2",
                        "time": "4.652",
                        "yield": "0.0889",
                    },
                    "product-1": {
                        "cost": "0.3638",
                        "lead_time": "1",
                        "time": "4.469",
                        "yield": "0.0202",
                    },
                    "product-2": {"cost": "0.0479", "time": "3.494", "yield": "0.5211"},
                },
                "repair_cost": "14.0428",
                "repair_limit": {
                    "distribution": "triangular",
                    "max": "0.2463",
                    "min": "0.0022",
                    "mode": "0.0150",
                },
                "repair_time": "8.880",
                "warehouse": "main",
                "wear_per_hour": "0.0251",
                "wear_per_period": "0.0599",
            },
            "line-2": {
                "breakdown_chance": "0.1546",
                "breakdown_loss": {
                    "distribution": "triangular",
                    "max": "0.5816",
                    "min": "0.3140",
                    "mode": "0.3140",
                },
                "capacity": "10.000",
                "groups": ["lines-region-1", "lines-tier-2"],
                "items": {
                    "component-2": {
                        "cost": "0.0675",
                        "time": "4.277",
                        "yield": "0.0269",
                    }
                },
                "repair_cost": "0.0500",
                "repair_limit": "0.0550",
                "repair_time": "31.045",
                "wear_per_hour": "0.0000",
                "wear_per_period": "0.0788",
            },
        },
        "warehouses": {"main": {"capacity": "163.883"}},
        "cash": {
            "credit_interest": "0.0287",
            "credit_limit": "1.6818",
            "debit_interest": "0.0507",
            "overdraft_interest": "0.1575",
        },
        "groups": {
            "lines-region-1": {"kind": "region"},
            "lines-tier-2": {
                "defaults": {
                    "line_items": {"yield": "0.1182"},
                    "lines": {
                        "breakdown_loss": {"max": "0.6141", "min": "0.0255"},
                        "repair_cost": "2.6733",
                    },
                },
                "kind": "tier",
            },
            "suppliers-region-1": {"kind": "region"},
            "suppliers-tier-2": {"kind": "tier"},
        },
    }
    scenario: dict[str, Any] = {
        "horizon": 5,
        "demand_shapes": [
            {"kind": "trend", "rate": "-0.0492", "target": {"product": "product-1"}}
        ],
        "forecasts": [],
        "disruptions": [],
        "random_disruptions": [],
        "hidden": [],
        "start": {
            "cash": "14183.1119",
            "condition": {"line-1": "0.1399", "line-2": "0.0186"},
            "customer_orders": [
                {
                    "customer": "customer-1",
                    "due": 3,
                    "product": "product-2",
                    "quantity": "1.668",
                },
                {
                    "customer": "customer-1",
                    "due": 1,
                    "product": "product-1",
                    "quantity": "8.485",
                },
            ],
            "set_for": {},
            "stock": {
                "main": {
                    "component-1": "0.053",
                    "component-2": "16.721",
                    "material-1": "0.015",
                    "material-2": "35.840",
                    "product-1": "4.069",
                    "product-2": "1.636",
                }
            },
            "supplier_orders": [
                {
                    "arrival": 1,
                    "material": "material-1",
                    "quantity": "34.019",
                    "supplier": "supplier-1",
                }
            ],
        },
    }
    return manifest, scenario


# A linear factory whose warehouse `main` has 0.002794 of space free in period 3, less
# than the margin of its rows, so the rows let the productions add no
# space. Both lines make `product-1` by its alternative recipe, each unit freeing
# 24.739456, and `line-1` fills that space with `component-1`, each unit adding
# 1.927296. Rounded down, the productions of `product-1` free less than planned and the
# fit takes 1.245 units of `component-1` to 1.236, then to 1.235, as its inputs,
# rounded up, free less space at 1.236.
def freeing_space_by_products_bodies() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest: dict[str, Any] = {
        "materials": {
            "material-1": {
                "space": "3.153",
                "storage_cost": "0.0881",
                "salvage_value": "0.0119",
            },
            "material-2": {
                "space": "1.000",
                "storage_cost": {"min": "0.0326", "max": "3.7054"},
                "salvage_value": "0.0000",
            },
        },
        "components": {
            "component-1": {
                "space": "5.610",
                "storage_cost": "0.0391",
                "recipes": {
                    "standard": {"material-1": "1.027"},
                    "alternative": {"material-1": "1.168"},
                },
                "default_recipe": "standard",
                "salvage_value": "0.0020",
            },
            "component-2": {
                "space": "8.084",
                "storage_cost": {"min": "0.0644", "max": "50.9574"},
                "recipes": {
                    "standard": {"material-1": "1.029"},
                    "alternative": {"material-2": "4.594"},
                },
                "default_recipe": "standard",
                "salvage_value": "0.0001",
            },
        },
        "products": {
            "product-1": {
                "space": "1.000",
                "storage_cost": "0.9295",
                "recipes": {
                    "standard": {"component-1": "1.113"},
                    "alternative": {"component-2": "3.184"},
                },
                "default_recipe": "standard",
                "salvage_value": "0.0353",
            }
        },
        "suppliers": {
            "supplier-1": {
                "catalogue": {
                    "material-1": {
                        "price": "0.0404",
                        "lead_time": "5",
                        "max_quantity": "510.510",
                        "punctuality": "0.0138",
                        "delay": "5",
                        "completeness": "0.1951",
                        "acceptance": "0.2211",
                        "express_lead_time": "3",
                        "express_cost": "0.0162",
                    },
                    "material-2": {
                        "price": "0.0001",
                        "lead_time": "1",
                        "max_quantity": "4.267",
                        "punctuality": "0.0164",
                        "delay": "4",
                        "acceptance": "0.1484",
                    },
                },
                "groups": ["suppliers-tier-1", "suppliers-segment-2"],
            }
        },
        "customers": {
            "customer-1": {
                "products": {
                    "product-1": {
                        "price": "0.3837",
                        "transport_cost": "0.3043",
                        "demand": "1000.000",
                        "lead_time": "0",
                        "patience": "2",
                        "late_penalty": "0.1639",
                        "lost_sale_penalty": "20.5607",
                    }
                }
            },
            "customer-2": {
                "products": {
                    "product-1": {
                        "price": {
                            "min": "0.0163",
                            "max": "0.1532",
                            "distribution": "triangular",
                            "mode": "0.1320",
                        },
                        "transport_cost": {
                            "min": "0.0346",
                            "max": "1.1539",
                            "distribution": "lognormal",
                            "median": "0.2561",
                            "spread": "0.0223",
                        },
                        "demand": "6.784",
                        "lead_time": "4",
                        "patience": {"min": "0", "max": "5"},
                        "late_penalty": "52.4289",
                        "lost_sale_penalty": "0.5336",
                    }
                }
            },
        },
        "lines": {
            "line-1": {
                "capacity": "510.511",
                "wear_per_period": "0.0663",
                "wear_per_hour": "0.0013",
                "breakdown_chance": {
                    "min": "0.0467",
                    "max": "0.1197",
                    "distribution": "normal",
                    "mean": "0.0835",
                    "sd": "0.0517",
                },
                "repair_time": {"min": "1.691", "max": "3.430"},
                "repair_limit": {
                    "min": "0.0436",
                    "max": "0.1922",
                    "distribution": "lognormal",
                    "median": "0.1016",
                    "spread": "0.3884",
                },
                "items": {
                    "component-2": {
                        "time": {
                            "min": "1.046",
                            "max": "1.622",
                            "distribution": "normal",
                            "mean": "1.527",
                            "sd": "0.065",
                        },
                        "cost": "6.9363",
                        "lead_time": "1",
                    },
                    "product-1": {
                        "time": "4.136",
                        "cost": {
                            "min": "0.4209",
                            "max": "0.4605",
                            "distribution": "triangular",
                            "mode": "0.4428",
                        },
                        "yield": {
                            "min": "0.0204",
                            "max": "0.2645",
                            "distribution": "triangular",
                            "mode": "0.0401",
                        },
                    },
                    "component-1": {"time": "1.215", "cost": "0.0000"},
                },
                "warehouse": "main",
                "groups": ["lines-segment-1"],
            },
            "line-2": {
                "overtime_hours": {
                    "min": "1.973",
                    "max": "1000.000",
                    "distribution": "triangular",
                    "mode": "194.265",
                },
                "overtime_cost": "3.0814",
                "capacity": "0.172",
                "wear_per_period": {
                    "min": "0.0219",
                    "max": "0.0833",
                    "distribution": "lognormal",
                    "median": "0.0392",
                    "spread": "0.0409",
                },
                "wear_per_hour": "0.0002",
                "breakdown_chance": "0.3720",
                "breakdown_loss": {"min": "0.1203", "max": "0.1214"},
                "repair_cost": {
                    "min": "0.0576",
                    "max": "0.2698",
                    "distribution": "triangular",
                    "mode": "0.0909",
                },
                "repair_time": "4.500",
                "repair_limit": {
                    "min": "0.0234",
                    "max": "0.1757",
                    "distribution": "lognormal",
                    "median": "0.0374",
                    "spread": "0.0374",
                },
                "items": {
                    "component-2": {
                        "time": {"min": "1.000", "max": "1.983"},
                        "cost": "0.0134",
                        "yield": {
                            "min": "0.0095",
                            "max": "0.0255",
                            "distribution": "triangular",
                            "mode": "0.0146",
                        },
                        "lead_time": {"min": "1", "max": "2"},
                    },
                    "component-1": {
                        "time": {"min": "2.509", "max": "2.880"},
                        "cost": {
                            "min": "0.5240",
                            "max": "0.7142",
                            "distribution": "normal",
                            "mean": "0.6694",
                            "sd": "0.1268",
                        },
                        "yield": {
                            "min": "0.0183",
                            "max": "0.4420",
                            "distribution": "normal",
                            "mean": "0.0696",
                            "sd": "0.3327",
                        },
                        "lead_time": {"min": "3", "max": "5"},
                    },
                    "product-1": {
                        "time": {"min": "3.122", "max": "4.368"},
                        "cost": {
                            "min": "0.0434",
                            "max": "0.1570",
                            "distribution": "lognormal",
                            "median": "0.1177",
                            "spread": "0.1223",
                        },
                        "yield": "0.3053",
                    },
                },
                "warehouse": "main",
            },
        },
        "warehouses": {
            "main": {"capacity": "15.901"},
            "warehouse-2": {"capacity": "4143.036"},
        },
        "cash": {
            "credit_limit": "0.1266",
            "credit_interest": "0.0115",
            "debit_interest": "0.0621",
            "overdraft_interest": "0.3072",
        },
        "routes": {
            "main": {
                "warehouse-2": {
                    "cost": {"min": "0.0028", "max": "16.0140"},
                    "lead_time": {"min": "0", "max": "5"},
                }
            },
            "warehouse-2": {
                "main": {
                    "cost": {
                        "min": "0.0160",
                        "max": "0.2177",
                        "distribution": "lognormal",
                        "median": "0.0171",
                        "spread": "1.1605",
                    },
                    "lead_time": {"min": "2", "max": "4"},
                }
            },
        },
        "groups": {
            "suppliers-tier-1": {"kind": "tier"},
            "suppliers-segment-2": {
                "kind": "segment",
                "defaults": {
                    "catalogue": {"punctuality": "0.3848", "completeness": "0.8893"}
                },
            },
            "lines-segment-1": {
                "kind": "segment",
                "defaults": {
                    "lines": {
                        "repair_cost": "0.1920",
                        "breakdown_loss": {"min": "0.0000", "max": "0.6016"},
                    },
                    "line_items": {"yield": "0.0223"},
                },
            },
        },
    }
    scenario: dict[str, Any] = {
        "horizon": 4,
        "demand_shapes": [],
        "forecasts": [],
        "disruptions": [
            {
                "kind": "quality_drop",
                "target": "all",
                "start": 2,
                "strength": "0.7421",
                "duration": 4,
                "notice": 0,
            },
            {
                "kind": "material_shortage",
                "target": "all",
                "start": 2,
                "strength": "0.0225",
                "duration": 1,
                "notice": 1,
            },
            {
                "kind": "transport_delay",
                "target": {"segment": "suppliers-segment-2"},
                "start": 3,
                "delay": 3,
                "duration": 1,
                "notice": 0,
            },
        ],
        "random_disruptions": [],
        "hidden": [
            "lines.breakdown_chance",
            "suppliers.catalogue.delay",
            "suppliers.catalogue.punctuality",
            "lines.items.yield",
            "customers.products.demand",
            "suppliers.catalogue.acceptance",
            "lines.breakdown_loss",
            "disruptions.duration",
            "suppliers.catalogue.completeness",
        ],
        "start": {
            "cash": "40645.1809",
            "stock": {
                "main": {"material-1": "0.793"},
                "warehouse-2": {
                    "component-1": "162.819",
                    "material-1": "986.734",
                    "product-1": "46.799",
                    "component-2": "0.540",
                    "material-2": "0.166",
                },
            },
            "customer_orders": [],
            "supplier_orders": [
                {
                    "supplier": "supplier-1",
                    "material": "material-1",
                    "quantity": "4.250",
                    "arrival": 3,
                    "warehouse": "main",
                },
                {
                    "supplier": "supplier-1",
                    "material": "material-1",
                    "quantity": "0.377",
                    "arrival": 3,
                    "warehouse": "warehouse-2",
                },
            ],
            "set_for": {},
            "condition": {"line-2": "0.0703"},
        },
    }
    return manifest, scenario


# A linear factory where the program of the reference plans, in period 2, 0.393934
# units of `component-1` into `main`, each adding 8.971 - 3.197 * 1.844 = 3.075732 of
# space, and 0.000934 units of `product-1` by its alternative recipe, each freeing
# 3.211 * 8.971 - 1.303 = 27.502881. That production rounds down to 0 and frees
# nothing, so the 0.393 units of `component-1` ask 1.207695 of the 1.198059 free, and
# the fit takes them to 0.389.
def skipping_a_production_that_frees_space_bodies() -> tuple[
    dict[str, Any], dict[str, Any]
]:
    manifest: dict[str, Any] = {
        "materials": {
            "material-1": {
                "space": "1.844",
                "storage_cost": "100.0000",
                "salvage_value": "0.0017",
            }
        },
        "components": {
            "component-1": {
                "space": "8.971",
                "storage_cost": "0.5445",
                "recipes": {"standard": {"material-1": "3.197"}},
                "default_recipe": "standard",
                "salvage_value": "0.1281",
            }
        },
        "products": {
            "product-1": {
                "space": "1.303",
                "recipes": {
                    "standard": {"component-1": "1.095"},
                    "alternative": {"component-1": "3.211"},
                },
                "default_recipe": "standard",
                "salvage_value": "0.0000",
                "groups": ["products-region-1", "products-segment-2"],
            }
        },
        "suppliers": {
            "supplier-1": {
                "catalogue": {
                    "material-1": {
                        "price": "100.0000",
                        "lead_time": {"min": "1", "max": "2"},
                        "max_quantity": "188.293",
                        "delay": "3",
                        "completeness": "0.1329",
                        "cancellation_fee": "0.0036",
                        "backfill_delay": "0",
                    }
                },
                "groups": ["suppliers-region-1", "suppliers-tier-2"],
            },
            "supplier-2": {
                "catalogue": {
                    "material-1": {
                        "price": {"min": "22.7279", "max": "100.0000"},
                        "lead_time": "4",
                        "max_quantity": "0.610",
                        "punctuality": "0.0059",
                        "delay": "2",
                        "completeness": "0.0130",
                        "cancellation_fee": "0.0144",
                        "express_lead_time": {"min": "1", "max": "1"},
                        "express_cost": "0.0224",
                    }
                },
                "groups": ["suppliers-region-1", "suppliers-tier-2"],
            },
        },
        "customers": {
            "customer-1": {
                "products": {
                    "product-1": {
                        "price": {"min": "0.1640", "max": "1.6878"},
                        "transport_cost": "8.6165",
                        "demand": "0.175",
                        "lead_time": "2",
                        "patience": {"min": "1", "max": "4"},
                        "late_penalty": "0.8660",
                        "lost_sale_penalty": {
                            "min": "0.0768",
                            "max": "2.8273",
                            "distribution": "normal",
                            "mean": "0.5288",
                            "sd": "0.3094",
                        },
                    }
                },
                "payment_terms": 0,
            }
        },
        "lines": {
            "line-1": {
                "overtime_hours": "2.332",
                "overtime_cost": {
                    "min": "0.2847",
                    "max": "17.7012",
                    "distribution": "triangular",
                    "mode": "3.4754",
                },
                "capacity": "407.692",
                "wear_per_period": "0.0187",
                "wear_per_hour": "0.0015",
                "breakdown_chance": "0.0288",
                "breakdown_loss": {
                    "min": "0.0378",
                    "max": "0.5627",
                    "distribution": "normal",
                    "mean": "0.4361",
                    "sd": "0.0216",
                },
                "repair_cost": "0.1294",
                "repair_time": "0.698",
                "repair_limit": {"min": "0.2238", "max": "0.3396"},
                "items": {
                    "component-1": {
                        "time": "1.220",
                        "cost": "2.3745",
                        "yield": {"min": "0.0163", "max": "0.0343"},
                    },
                    "product-1": {
                        "time": {
                            "min": "1.784",
                            "max": "2.690",
                            "distribution": "normal",
                            "mean": "2.283",
                            "sd": "0.085",
                        },
                        "cost": "8.1241",
                        "yield": {
                            "min": "0.0093",
                            "max": "0.4453",
                            "distribution": "triangular",
                            "mode": "0.0599",
                        },
                        "lead_time": "4",
                    },
                },
                "warehouse": "main",
                "groups": ["lines-region-1"],
            }
        },
        "warehouses": {
            "main": {"transport_factor": "0.6311", "capacity": "3.967"},
            "warehouse-2": {
                "accepts": [
                    "products",
                    "components",
                    "materials",
                    {"group": "products-segment-2"},
                ],
                "storage_factor": "0.0279",
                "transport_factor": "0.0301",
                "capacity": "3928.516",
            },
        },
        "cash": {
            "credit_limit": "0.0503",
            "credit_interest": "0.0313",
            "debit_interest": "0.1234",
            "overdraft_interest": "0.6282",
        },
        "routes": {
            "warehouse-2": {
                "main": {
                    "cost": {
                        "min": "1.1598",
                        "max": "7.1990",
                        "distribution": "normal",
                        "mean": "3.3038",
                        "sd": "0.1294",
                    },
                    "lead_time": {"min": "0", "max": "1"},
                }
            }
        },
        "groups": {
            "suppliers-region-1": {
                "kind": "region",
                "defaults": {
                    "catalogue": {
                        "acceptance": "0.0559",
                        "punctuality": {"min": "0.1093", "max": "0.6142"},
                    }
                },
            },
            "suppliers-tier-2": {"kind": "tier"},
            "products-region-1": {
                "kind": "region",
                "defaults": {"items": {"storage_cost": "2.0271"}},
            },
            "products-segment-2": {
                "kind": "segment",
                "defaults": {"items": {"storage_cost": "0.0563"}},
            },
            "lines-region-1": {
                "kind": "region",
                "defaults": {
                    "lines": {"repair_cost": {"min": "0.0316", "max": "0.8031"}}
                },
            },
        },
    }
    scenario: dict[str, Any] = {
        "horizon": 3,
        "demand_shapes": [
            {
                "factors": ["0.0907"],
                "period_length": 9,
                "kind": "season",
                "target": "all",
            },
            {
                "rate": "0.0184",
                "kind": "trend",
                "target": {"segment": "products-segment-2"},
            },
        ],
        "forecasts": [
            {
                "target": {"segment": "products-segment-2"},
                "periods_ahead": 2,
                "noise": "0.0516",
                "noise_growth": "0.0237",
            }
        ],
        "disruptions": [
            {
                "kind": "demand_shock",
                "target": {"region": "products-region-1"},
                "start": 3,
                "factor": "0.2130",
                "duration": 3,
                "notice": 0,
            }
        ],
        "random_disruptions": [
            {
                "name": "rule-b",
                "kind": "demand_shock",
                "target": {"region": "products-region-1"},
                "factor": "1.3353",
                "duration": {"min": "1", "max": "2"},
                "notice": 1,
                "start": 3,
                "raises": {"rule": "disruption-9", "factor": "2.1737", "periods": 2},
            },
            {
                "name": "disruption-9",
                "kind": "capacity_cut",
                "target": "all",
                "chance": "0.0246",
                "strength": "0.9735",
                "duration": {"min": "2", "max": "2"},
                "choose": "one",
                "notice": 0,
            },
        ],
        "hidden": [
            "suppliers.catalogue.punctuality",
            "suppliers.catalogue.delay",
            "lines.breakdown_chance",
            "lines.items.yield",
            "suppliers.catalogue.acceptance",
            "disruptions.duration",
            "lines.breakdown_loss",
            "customers.products.demand",
            "suppliers.catalogue.completeness",
        ],
        "start": {
            "cash": "10000.0000",
            "stock": {
                "main": {},
                "warehouse-2": {
                    "material-1": "1000.000",
                    "component-1": "228.992",
                    "product-1": "0.210",
                },
            },
            "customer_orders": [
                {
                    "customer": "customer-1",
                    "product": "product-1",
                    "quantity": "0.974",
                    "due": 2,
                },
                {
                    "customer": "customer-1",
                    "product": "product-1",
                    "quantity": "0.158",
                    "due": 2,
                },
            ],
            "supplier_orders": [
                {
                    "supplier": "supplier-2",
                    "material": "material-1",
                    "quantity": "1.647",
                    "arrival": 1,
                    "warehouse": "main",
                },
                {
                    "supplier": "supplier-2",
                    "material": "material-1",
                    "quantity": "0.272",
                    "arrival": 2,
                    "warehouse": "main",
                },
            ],
            "set_for": {"line-1": "product-1"},
            "condition": {},
        },
    }
    return manifest, scenario


# A small factory with changeovers where no decisions earns
# 6191.2708 and the reference 6191.3986, after a solve of period 1 that stops at the
# gap limit with a gap of 0.0076.
def ending_within_the_gap_bodies() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest: dict[str, Any] = {
        "materials": {
            "material-1": {
                "space": "7.355",
                "storage_cost": {
                    "min": "2.2757",
                    "max": "2.5805",
                    "distribution": "normal",
                    "mean": "2.5042",
                    "sd": "0.0227",
                },
                "salvage_value": "0.0272",
            }
        },
        "components": {
            "component-1": {
                "space": "1.052",
                "storage_cost": "0.2800",
                "recipes": {"standard": {"material-1": "2.146"}},
                "salvage_value": "0.0120",
            },
            "component-2": {
                "space": "1.991",
                "storage_cost": "0.0511",
                "recipes": {"standard": {"material-1": "1.472"}},
                "salvage_value": "0.4539",
            },
        },
        "products": {
            "product-1": {
                "space": "2.042",
                "recipes": {"standard": {"component-1": "1.000"}},
                "salvage_value": "0.0137",
                "groups": ["products-region-1"],
            }
        },
        "suppliers": {
            "supplier-1": {
                "catalogue": {
                    "material-1": {
                        "price": "0.6446",
                        "lead_time": "1",
                        "max_quantity": "0.038",
                        "punctuality": "0.6741",
                        "delay": "3",
                        "completeness": "0.0406",
                        "acceptance": "0.1669",
                    }
                }
            }
        },
        "customers": {
            "customer-1": {
                "products": {
                    "product-1": {
                        "price": "1.3091",
                        "transport_cost": "26.9019",
                        "demand": "3.192",
                        "lead_time": "0",
                        "patience": "0",
                        "late_penalty": "0.0259",
                        "lost_sale_penalty": "0.1933",
                    }
                }
            }
        },
        "lines": {
            "line-1": {
                "overtime_hours": "0.602",
                "overtime_cost": "0.0225",
                "capacity": "1.090",
                "wear_per_period": "0.0040",
                "wear_per_hour": "0.4198",
                "breakdown_loss": "0.0014",
                "repair_cost": "0.0018",
                "repair_time": "0.652",
                "repair_limit": "0.0263",
                "items": {
                    "component-2": {
                        "time": "1.777",
                        "cost": "7.5295",
                        "changeover_time": "0.284",
                        "changeover_cost": "13.1209",
                    },
                    "component-1": {
                        "time": "3.869",
                        "cost": "0.0289",
                        "changeover_time": "0.147",
                        "changeover_cost": "0.0757",
                    },
                    "product-1": {
                        "time": "4.695",
                        "cost": "0.0447",
                        "changeover_time": "1.072",
                    },
                },
                "groups": ["lines-region-1", "lines-segment-2"],
            }
        },
        "warehouses": {"main": {"storage_factor": "0.0520", "capacity": "13.916"}},
        "cash": {
            "credit_limit": "83.5874",
            "credit_interest": "0.0305",
            "debit_interest": "0.0966",
            "overdraft_interest": "0.1237",
        },
        "groups": {
            "products-region-1": {
                "kind": "region",
                "defaults": {"items": {"storage_cost": "0.0042"}},
            },
            "lines-region-1": {
                "kind": "region",
                "defaults": {"lines": {"breakdown_chance": "0.1622"}},
            },
            "lines-segment-2": {
                "kind": "segment",
                "defaults": {"line_items": {"yield": "0.0035"}},
            },
        },
    }
    scenario: dict[str, Any] = {
        "horizon": 2,
        "start": {"cash": "100000", "stock": {"main": {"material-1": "1.892"}}},
    }
    return manifest, scenario


# The plain tiny factory whose line pays a changeover of 1 hour to the board and a
# changeover of no time and no cost to the monitor.
def free_changeover_manifest() -> dict[str, Any]:
    manifest = plain_tiny_manifest()
    items = manifest["lines"]["line-1"]["items"]
    items["board"]["changeover_time"] = "1.000"
    items["monitor"]["changeover_time"] = "0.000"
    return manifest


# The changeovers of a period that cost neither time nor money, per line: a produce of
# an item whose written changeover time and cost are 0, on a line set for another item
# or for none.
def free_changeovers(
    period: dict[str, Any], parameters: dict[str, Any]
) -> dict[str, int]:
    observation = next(
        step["observation"]
        for step in period["steps"]
        if step["step"] == "build_observation"
    )
    set_for = {
        line_id: line["set_for"] for line_id, line in observation["lines"].items()
    }
    changeovers = dict.fromkeys(set_for, 0)
    for decision in submitted_keys(period, ("kind", "line", "item")):
        if decision["kind"] != "produce":
            continue
        line_id, item_id = decision["line"], decision["item"]
        path = f"lines.{line_id}.items.{item_id}"
        written = [
            parameters[f"{path}.{key}"]["value"]
            for key in ("changeover_time", "changeover_cost")
            if f"{path}.{key}" in parameters
        ]
        if written and not any(written) and set_for[line_id] != item_id:
            changeovers[line_id] += 1
        set_for[line_id] = item_id
    return changeovers


# Two productions of 0.001 boards at a yield of 0.6 are one batch, ready in period 2.
# The batch so far is 0.0006 and 0.0012, both rounded to 0.001, so the engine gives
# the first 0.001 good units and the second 0.
def test_the_reference_projects_a_batch_on_the_way_as_the_engine_finishes_it():
    manifest, scenario = yield_partition_bodies()
    manifest["lines"]["line-1"]["items"]["board"]["lead_time"] = 2
    projected: list[Decimal] = []

    def agent(
        description: dict[str, Any], observation: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if observation["period"] == 1:
            return [produce("board", "0.001")] * 2
        if observation["period"] == 2:
            state = state_of(observation, world, description["manifest"])
            projected.extend(made.good for made in state.production)
        return []

    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, scenario)
        nothing, _ = play_no_decisions(client, scenario_id, 0)
        world = benchmark.read_world(client, nothing["id"])
        run = benchmark.start_run(client, scenario_id, 0)
        benchmark.play_run(client, run, agent)
        periods = benchmark.read_periods(client, run["id"])

    close = next(step for step in periods[1]["steps"] if step["step"] == "close_period")
    finished = [
        Decimal(event["good"])
        for event in close["events"]
        if event["kind"] == "production_finished"
    ]
    assert finished == projected == [Decimal("0.001"), Decimal(0)]


def test_the_reference_of_the_plain_tiny_factory_reaches_the_value_of_its_program():
    with benchmark_client() as client:
        manifest = benchmark.send(client, "POST", "/manifests", plain_tiny_manifest())
        path = f"/manifests/{manifest['id']}/scenarios"
        scenario = benchmark.send(client, "POST", path, plain_tiny_scenario())
        nothing, _ = play_no_decisions(client, scenario["id"], 0)
        run, reference = start_reference(client, scenario["id"], 0, nothing["id"])
        result = benchmark.play_run(client, run, reference)
        periods = benchmark.read_periods(client, run["id"])
        checks = records(client, Interaction, run_id=run["id"])
        runs = records(client, Run)

    keys = ("kind", "order", "line", "item", "quantity", "warehouse")
    assert [submitted_keys(period, keys) for period in periods] == [
        [
            {
                "kind": "produce",
                "line": "line-1",
                "item": "board",
                "quantity": Decimal("8.000"),
            },
            {
                "kind": "produce",
                "line": "line-1",
                "item": "monitor",
                "quantity": Decimal("4.000"),
            },
        ],
        [
            {
                "kind": "ship",
                "order": "order-2-1",
                "quantity": Decimal("4.000"),
                "warehouse": "main",
            },
            {
                "kind": "produce",
                "line": "line-1",
                "item": "monitor",
                "quantity": Decimal("4.000"),
            },
        ],
        [
            {
                "kind": "ship",
                "order": "order-3-1",
                "quantity": Decimal("4.000"),
                "warehouse": "main",
            },
        ],
    ]
    assert result["profit"] == Decimal(328)
    assert reference.relaxed_program_value == pytest.approx(328)
    assert reference.dropped == []
    assert reference.fitted == []
    assert [check["kind"] for check in checks] == ["check", "check", "check"]
    assert len(runs) == 2


# Cash 100, no credit and nothing owed: 100 - 0 - 10 * 10 = 0 is the lowest that the
# rule allows, so at most 10 chips at 10.0000 in period 1.
def test_the_reference_buys_no_more_than_the_credit_limit_allows():
    manifest = plain_tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["price"] = "10.0000"
    scenario = plain_tiny_scenario()
    scenario["horizon"] = 6
    scenario["start"] = {"cash": "100.0000", "stock": {}}

    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, scenario)
        run, reference = reference_of(client, scenario_id, 0)
        benchmark.play_run(client, run, reference)
        periods = benchmark.read_periods(client, run["id"])

    bought = [
        decision["quantity"]
        for decision in submitted_keys(periods[0], ("kind", "quantity"))
        if decision["kind"] == "buy"
    ]
    assert sum(bought, Decimal(0)) <= Decimal("10.000")
    assert reference.dropped == []


# No demand, no stock, no rate, no credit and cash 10000001 below 0: doing nothing
# earns 0, and every program of the reference has that plan.
@pytest.mark.slow
def test_the_reference_plays_an_idle_world_far_below_the_credit_line_for_0():
    manifest = plain_tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "0.000"
    scenario = plain_tiny_scenario()
    scenario["start"] = {"cash": "-10000001.0000", "stock": {}}

    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, scenario)
        run, reference = reference_of(client, scenario_id, 0)
        result = benchmark.play_run(client, run, reference)

    assert result["periods"] == 3
    assert result["profit"] == Decimal(0)
    assert result["measures"]["total"]["decisions_rejected"] == 0
    assert (reference.fitted, reference.dropped) == ([], [])
    assert [solve.solution_found for solve in reference.solves] == [True] * 3


# The world of a large selling price, accepted by the HTTP interface: no decisions
# loses the order for 10, keeps the monitor at 2 and the chip at 0.0001, -7.9999. At a
# price of 10**18 the relaxed program of period 1, solved first, counts money in units
# of 10**9, where the chip salvage of 0.1 falls to 1e-10: the reference stops with
# the scale of its program, not with an error of HiGHS.
@pytest.mark.slow
def test_the_reference_names_a_price_of_10_to_18_outside_the_scale_of_its_program():
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, *solver_scale_bodies())
        nothing, nothing_result = play_no_decisions(client, scenario_id, 0)
        run, reference = start_reference(client, scenario_id, 0, nothing["id"])
        with pytest.raises(UnsupportedScaleError) as raised:
            benchmark.play_run(client, run, reference)

    assert nothing_result["profit"] == Decimal("-7.9999")
    assert str(raised.value) == (
        "period 1: the money of the program runs from 0.1 to 1e+18; in units of "
        "1e+09 its smallest coefficient is 1e-10, at most 1e-09"
    )


# At a price of 10**15 with chips up to 1 a period, money is counted in units of
# 10**7, and the reference ships the monitor: 10**15 - 1 of transport + 0.0001 of
# chip salvage.
@pytest.mark.slow
def test_the_reference_ships_a_monitor_at_a_price_of_10_to_15():
    bodies = solver_scale_bodies("1000000000000000.0000", "1.000")
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, *bodies)
        run, reference = reference_of(client, scenario_id, 0)
        result = benchmark.play_run(client, run, reference)

    assert result["profit"] == Decimal("999999999999999.0001")
    assert (reference.fitted, reference.dropped) == ([], [])
    assert reference.relaxed_program_value == pytest.approx(1e15, rel=1e-12)


def test_the_reference_solves_a_minimum_quantity_as_an_integer_program():
    manifest = plain_tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["min_quantity"] = "10.000"

    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, plain_tiny_scenario())
        run, reference = reference_of(client, scenario_id, 0)
        result = benchmark.play_run(client, run, reference)

    assert result["periods"] == 3
    assert reference.dropped == []
    assert [solve.period for solve in reference.solves] == [1, 2, 3]
    assert all(0 <= solve.gap <= GAP_LIMIT for solve in reference.solves)


def test_a_solve_without_a_solution_leaves_its_period_without_decisions(
    monkeypatch: pytest.MonkeyPatch,
):
    manifest = plain_tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["min_quantity"] = "10.000"
    calls: list[int] = []

    def second_without_solution(costs: numpy.ndarray, **keys: object) -> OptimizeResult:
        calls.append(len(calls) + 1)
        if len(calls) == 2:
            result = OptimizeResult()
            result.update({"status": 1, "x": None})
            return result
        return cast(Callable[..., OptimizeResult], milp)(costs, **keys)

    monkeypatch.setattr(solve_module, "milp", second_without_solution)
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, plain_tiny_scenario())
        run, reference = reference_of(client, scenario_id, 0)
        result = benchmark.play_run(client, run, reference)
        periods = benchmark.read_periods(client, run["id"])

    assert result["periods"] == 3
    assert submitted_keys(periods[1], ("kind",)) == []
    assert [solve.solution_found for solve in reference.solves] == [True, False, True]


# The plain tiny factory is a linear manifest, yet every period has a buy option, so
# every program is an integer one: its credit choice is binary in its first period.
def test_the_reference_of_a_linear_manifest_solves_one_credit_choice_a_period():
    with benchmark_client() as client:
        scenario_id = stored_scenario(
            client, plain_tiny_manifest(), plain_tiny_scenario()
        )
        run, reference = reference_of(client, scenario_id, 0)
        benchmark.play_run(client, run, reference)

    assert [solve.period for solve in reference.solves] == [1, 2, 3]


def test_the_reference_with_a_tiny_time_limit_still_finishes_its_run():
    with benchmark_client() as client:
        scenario_id = stored_scenario(
            client, plain_changeover_manifest(), plain_tiny_scenario()
        )
        run, reference = reference_of(client, scenario_id, 0, time_limit=0.01)
        result = benchmark.play_run(client, run, reference)

    assert result["periods"] == 3
    assert len(reference.solves) == 3
    assert all(
        0 <= solve.gap < math.inf for solve in reference.solves if solve.solution_found
    )


def test_the_world_of_the_run_of_the_reference_stays_closed_until_it_ends():
    with benchmark_client() as client:
        scenario_id = stored_scenario(
            client, plain_tiny_manifest(), plain_tiny_scenario()
        )
        run, reference = reference_of(client, scenario_id, 0)
        world_path = f"/runs/{run['id']}/world"
        statuses: list[int] = []

        def watched(
            description: dict[str, Any], observation: dict[str, Any]
        ) -> list[dict[str, Any]]:
            statuses.append(client.get(world_path).status_code)
            return reference(description, observation)

        benchmark.play_run(client, run, watched)
        after = client.get(world_path).status_code

    assert statuses == [409, 409, 409]
    assert after == 200


@pytest.mark.property
@settings(max_examples=example_count(25))
@given(linear_factories().filter(lambda factory: factory[1]["horizon"] <= 6), seeds)
def test_the_reference_drops_no_decision_on_a_linear_factory(
    factory: tuple[dict[str, Any], dict[str, Any]], seed: int
):
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, *factory)
        run, reference = reference_of(client, scenario_id, seed)
        benchmark.play_run(client, run, reference)

    assert reference.dropped == []


def test_the_reference_drops_no_production_when_a_full_warehouse_rounds_it_down():
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, *filling_warehouse_bodies())
        run, reference = reference_of(client, scenario_id, 123046465)
        benchmark.play_run(client, run, reference)

    assert reference.dropped == []


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(
    linear_factories().filter(lambda factory: factory[1]["horizon"] <= 6),
    seeds,
    st.data(),
)
def test_the_reference_submits_no_buy_beyond_the_credit_limit(
    factory: tuple[dict[str, Any], dict[str, Any]], seed: int, data: st.DataObject
):
    manifest, scenario = factory
    limit = Decimal(manifest["cash"]["credit_limit"])
    near = number_text(4, -2 * limit - 100, limit)
    far = number_text(4, -(10**9), -2 * limit - 100)
    scenario["start"]["cash"] = data.draw(near | far)
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, scenario)
        run, reference = reference_of(client, scenario_id, seed)
        benchmark.play_run(client, run, reference)
        periods = benchmark.read_periods(client, run["id"])

    reasons = {
        outcome.get("reason")
        for period in periods
        for step in period["steps"]
        if step["step"] == "execute_decisions"
        for outcome in step["outcomes"]
    }
    assert "over_credit_limit" not in reasons
    assert all(drop["reason"] != "over_credit_limit" for drop in reference.dropped)


# With cash that no cost uses up, no buy meets the credit limit, so the credit choices
# of later periods, the only yes-or-no choices of a linear factory, never bind, and
# the program of the reference is exact but for rounding. The credit check holds only
# when a period buys, so it is not linear: where it binds in a later period, a credit
# choice from 0 to 1 lets the program value a plan no run can follow. Let the
# tolerance be the `rounding_bound` of the stock that quantities rounded down keep,
# plus the gaps of the integer solves of the run, the most each solve may leave below
# the best plan of its program, plus 1 unit for the rounding the bound leaves out: of
# good units, inputs, hours, repairs and the value of a unit not made or not sold. The
# run profit is within the tolerance of that value; no decision is dropped; a decision
# fitted for space loses at most the `space_fit_allowance` of the decisions that free
# its warehouse, rounded down, and any other fit at most the 0.002 units of a
# rounding; and the reference ends at least at no decisions, less the tolerance.
@pytest.mark.property
@settings(max_examples=example_count(25))
@given(linear_factories().filter(lambda factory: factory[1]["horizon"] <= 6), seeds)
@example(factory=storing_on_overdraft_bodies(), seed=0)
@example(factory=emptying_costly_storage_bodies(), seed=122730)
@example(factory=freeing_space_by_products_bodies(), seed=349)
@example(factory=skipping_a_production_that_frees_space_bodies(), seed=935)
def test_the_reference_program_counts_a_linear_factory_as_the_engine_does(
    factory: tuple[dict[str, Any], dict[str, Any]], seed: int
):
    manifest, scenario = factory
    scenario["start"]["cash"] = "100000"
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, manifest, scenario)
        nothing, floor = play_no_decisions(client, scenario_id, seed)
        run, reference = start_reference(client, scenario_id, seed, nothing["id"])
        with recording_solutions() as solutions:
            result = benchmark.play_run(client, run, reference)
        periods = benchmark.read_periods(client, run["id"])

    value = next(solution.value for period, solution in solutions if period == 1)
    assert value is not None
    planned = {period: solution_decisions(solution) for period, solution in solutions}
    quantity_counts = {
        period["period"]: sum(
            1 for decision in submitted_keys(period, ("quantity",)) if decision
        )
        for period in periods
    }
    gaps = sum(solve.gap for solve in reference.solves)
    tolerance = Decimal(1) + Decimal(str(gaps))
    tolerance += rounding_bound(manifest, scenario["horizon"], quantity_counts)
    assert abs(Decimal(str(value)) - result["profit"]) < tolerance
    assert reference.dropped == []
    flat = groups_written_out(manifest)
    for fit in reference.fitted:
        taken = fit["before"] - fit["after"]
        assert taken > 0
        if fit["reason"] != "not_enough_space":
            assert taken <= Decimal("0.002")
            continue
        fits = [other for other in reference.fitted if other["period"] == fit["period"]]
        allowance = space_fit_allowance(
            manifest, planned[fit["period"]], fits, fit["decision"]
        )
        assert taken * added_space(flat, fit["decision"])[1] <= allowance
    assert floor["profit"] <= result["profit"] + tolerance


# A thousandth of a unit of `component-2` not made by its alternative recipe keeps
# 0.004233 units of `material-2` in stock, which costs 0.4233 at a close; no other
# item or recipe stores more. The highest rate of interest is the overdraft interest
# of 0.1575. A quantity of period 5 costs at most 0.4233 * 1.1575 = 0.48996975. The
# run of seed 122730 submits 3 quantities in period 1 and 2 in each later period, so
# the bound is 0.4233 * (3 * 7.92101878 + 2 * (5.84321277 + 4.04813198 + 2.49730625 +
# 1.1575)) = 21.5271, with 7.92101878 = 1.1575 + 1.1575^2 + ... + 1.1575^5 and so on.
def test_the_rounding_bound_counts_the_storage_of_the_inputs_kept_at_each_close():
    manifest, _ = emptying_costly_storage_bodies()

    period_5 = rounding_bound(manifest, 5, {5: 1})
    run = rounding_bound(manifest, 5, {1: 3, 2: 2, 3: 2, 4: 2, 5: 2})

    assert period_5 == Decimal("0.48996975")
    assert round(run, 4) == Decimal("21.5271")


# In period 3 of the factory freeing space by products, `line-1` and `line-2` make
# 0.091 and 0.005 units of `product-1` by its alternative recipe, 3.184 units of
# `component-2` of space 8.084 a unit: each unit frees 3.184 * 8.084 - 1.000 =
# 24.739456 of `main`. `component-1` adds 5.610 - 1.168 * 3.153 = 1.927296 a unit,
# from one input of space 3.153. The allowance is 0.001 * (24.739456 + 24.739456) +
# 0.001 * (1.927296 + 3.153) = 0.054559208 of space. The fit takes 0.009 units, then
# 0.001, of 1.927296 each.
def test_the_space_fit_allowance_counts_the_productions_that_free_space():
    manifest, _ = freeing_space_by_products_bodies()
    products = [
        produce("product-1", "0.091", "line-1", recipe="alternative"),
        produce("product-1", "0.005", "line-2", recipe="alternative"),
    ]
    component = produce("component-1", "1.245", recipe="alternative")
    fits = [
        {"decision": component, "before": Decimal("1.245"), "after": Decimal("1.236")}
    ]

    allowance = space_fit_allowance(manifest, [*products, component], fits, component)

    assert allowance == Decimal("0.054559208")


@pytest.mark.slow
def test_the_integer_reference_ends_within_its_gap_of_no_decisions():
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, *ending_within_the_gap_bodies())
        nothing, floor = play_no_decisions(client, scenario_id, 0)
        run, reference = start_reference(client, scenario_id, 0, nothing["id"])
        with recording_program_values() as values:
            result = benchmark.play_run(client, run, reference)

    value = next(value for period, value in values if period == 1)
    assert value is not None
    tolerance = Decimal(str(sum(solve.gap for solve in reference.solves)))
    assert floor["profit"] <= result["profit"] + tolerance


@pytest.mark.property
@settings(max_examples=example_count(25))
@given(small_factories().filter(lambda factory: factory[1]["horizon"] <= 6), seeds)
@example(factory=(free_changeover_manifest(), plain_tiny_scenario()), seed=0)
@example(factory=full_warehouse_bodies(), seed=0)
@example(factory=full_warehouse_bodies(board_changeover_time="0.500"), seed=0)
@example(factory=freeing_space_by_products_bodies(), seed=349)
def test_the_reference_fits_space_within_its_allowance_and_keeps_its_changeovers(
    factory: tuple[dict[str, Any], dict[str, Any]], seed: int
):
    manifest, _ = factory
    with benchmark_client() as client:
        scenario_id = stored_scenario(client, *factory)
        run, reference = reference_of(client, scenario_id, seed)
        with recording_solutions() as solutions:
            benchmark.play_run(client, run, reference)
        periods = benchmark.read_periods(client, run["id"])
        parameters = benchmark.read_world(client, run["id"])["parameters"]

    # Each production fits the space left before it in the plan. The decisions of its
    # period that free space in its warehouse are rounded down, so the fit may take
    # from it at most the `space_fit_allowance` of the period, and drops none for
    # space. Where no order that fits pays only the changeovers of the program, the
    # hours of one more can be missing, and the check rejects a production for them.
    planned = {period: solution_decisions(solution) for period, solution in solutions}
    flat = groups_written_out(manifest)
    for fit in reference.fitted:
        if (fit["decision"]["kind"], fit["reason"]) != ("produce", "not_enough_space"):
            continue
        fits = [other for other in reference.fitted if other["period"] == fit["period"]]
        allowance = space_fit_allowance(
            manifest, planned[fit["period"]], fits, fit["decision"]
        )
        taken = fit["before"] - fit["after"]
        assert taken * added_space(flat, fit["decision"])[1] <= allowance
    extra = {
        solve.period
        for solve in reference.solves
        if any(
            changeovers > solve.planned_changeovers[line_id]
            for line_id, changeovers in solve.changeovers.items()
        )
    }
    for drop in reference.dropped:
        assert (drop["decision"]["kind"], drop["reason"]) == (
            "produce",
            "not_enough_hours",
        )
        assert drop["period"] in extra
    changed = {entry["period"] for entry in reference.dropped + reference.fitted}
    for solve in reference.solves:
        if solve.period in changed:
            continue
        period = periods[solve.period - 1]
        measures = next(
            step["measures"]
            for step in period["steps"]
            if step["step"] == "close_period"
        )
        # The engine counts a changeover of no time and no cost; the program has none.
        free = free_changeovers(period, parameters)
        for line_id, counted in solve.changeovers.items():
            changeovers = measures["lines"][line_id]["changeovers"]
            assert changeovers - free[line_id] == counted


# The plain tiny scenario, and the same with 10**7 more monitors ordered for period 1,
# when none can ship, and 10**8 more starting cash. The order is lost for 10 a monitor,
# so both runs reach period 2 with the same state, and every later program of the
# second counts 10**8 less profit before it starts: an offset that no decision
# changes. Every solve of both stops within the gap limit, and the second run earns
# 10**8 less, within 1 for rounding and the gaps of the two runs.
@pytest.mark.slow
def test_a_loss_before_a_period_keeps_the_reference_within_its_gap_limit():
    scenario = plain_tiny_scenario()
    lost = plain_tiny_scenario()
    lost["start"]["cash"] = "100001000"
    order = {"customer": "distributor", "product": "monitor", "quantity": "10000000"}
    lost["start"]["customer_orders"] = [order | {"due": 1}]

    with benchmark_client() as client:
        first, first_reference = reference_of(
            client, stored_scenario(client, plain_tiny_manifest(), scenario), 0
        )
        first_result = benchmark.play_run(client, first, first_reference)
        second, second_reference = reference_of(
            client, stored_scenario(client, plain_tiny_manifest(), lost), 0
        )
        second_result = benchmark.play_run(client, second, second_reference)

    solves = first_reference.solves + second_reference.solves
    assert len(solves) == 6
    assert all(0 <= solve.gap <= GAP_LIMIT for solve in solves)
    difference = first_result["profit"] - second_result["profit"] - 10**8
    assert abs(difference) <= 1 + Decimal(str(sum(solve.gap for solve in solves)))
