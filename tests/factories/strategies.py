import copy
import functools
import os
from collections.abc import Callable, Mapping
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from random import Random
from typing import Any, cast

import hypothesis
from hypothesis import HealthCheck, Phase, settings
from hypothesis import strategies as st

from factories.bodies import (
    FactoryBodies,
    draw_world_of_bodies,
    future_minimum_bodies,
    ordered_transfer_bodies,
    unwanted_order_bodies,
)
from factories.decisions import decide
from factory_simulator.engine import (
    State,
    World,
    build_state,
    start_period,
)

IN_CI = os.environ.get("CI", "").lower() in {"true", "1", "yes"}

# The kinds of the generated groups.
GROUP_KINDS = ("region", "segment", "tier")

# The parameters a generated scenario may hide.
HIDDEN_GROUPS = (
    "customers.products.demand",
    "suppliers.catalogue.punctuality",
    "suppliers.catalogue.delay",
    "suppliers.catalogue.completeness",
    "suppliers.catalogue.acceptance",
    "lines.items.yield",
    "lines.breakdown_chance",
    "lines.breakdown_loss",
    "disruptions.duration",
)

# A local run draws a tenth of the examples; CI uses the built-in profile "ci". Neither
# has a deadline.
settings.register_profile(
    "local",
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("ci" if IN_CI else "local")

# One period of a run: the state the decisions are made in, the decisions, the close.
type RunStep = tuple[State, list[dict[str, Any]], State]

# A function that draws one value from a strategy: `draw` of a composite strategy or
# `data.draw` of a test.
type Draw = Callable[[st.SearchStrategy[Any]], Any]

# A function that gives the strategy of the decisions of a period from its state.
type DecisionLists = Callable[[World, State], st.SearchStrategy[list[dict[str, Any]]]]


# The examples of a property: all of them in CI, a tenth and at least 5 locally.
def example_count(count: int) -> int:
    return count if IN_CI else max(count // 10, 5)


# Decimal text from low to high with exactly the given places.
@functools.cache
def number_text(
    places: int, low: int | Decimal, high: int | Decimal
) -> st.SearchStrategy[str]:
    numbers = st.decimals(min_value=low, max_value=high, places=places)
    return numbers.map(lambda value: format(value, "f"))


# A fixed value or a range of two values. A range of decimals is uniform, triangular,
# normal or, when its min is above 0, lognormal; a range of periods is uniform.
@functools.cache
def parameter_values(values: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    ranges = st.lists(values, min_size=2, max_size=2).map(
        lambda pair: {"min": min(pair, key=Decimal), "max": max(pair, key=Decimal)}
    )
    return st.one_of(values, ranges.flatmap(with_distribution))


# The range as it is, or triangular, normal or lognormal when it holds decimals.
def with_distribution(value_range: dict[str, Any]) -> st.SearchStrategy[dict[str, Any]]:
    low, high = str(value_range["min"]), str(value_range["max"])
    if "." not in low or Decimal(low) == Decimal(high):
        return st.just(value_range)
    places = len(low.split(".")[1])
    unit = Decimal(1).scaleb(-places)
    within = number_text(places, Decimal(low), Decimal(high))
    triangular = within.map(
        lambda mode: value_range | {"distribution": "triangular", "mode": mode}
    )
    normal = st.tuples(
        within, number_text(places, unit, Decimal(high) - Decimal(low))
    ).map(
        lambda pair: (
            value_range | {"distribution": "normal", "mean": pair[0], "sd": pair[1]}
        )
    )
    if Decimal(low) == 0:
        return st.one_of(st.just(value_range), triangular, normal)
    lognormal = st.tuples(within, number_text(4, Decimal("0.0001"), 2)).map(
        lambda pair: (
            value_range
            | {"distribution": "lognormal", "median": pair[0], "spread": pair[1]}
        )
    )
    return st.one_of(st.just(value_range), triangular, normal, lognormal)


quantities = number_text(3, 0, 1000)
money = number_text(4, 0, 100)
shares = number_text(4, 0, 1)
seeds = st.integers(min_value=0, max_value=2**128 - 1)


# The largest value of a fixed number or a range.
def largest(value: str | dict[str, str]) -> Decimal:
    return Decimal(value["max"]) if isinstance(value, dict) else Decimal(value)


# Wear per hour up to `(1 - wear_per_period) / (capacity + overtime_hours)`. Each value
# is taken at its largest. The bound is rounded down to 4 places, so a line worked at
# full capacity and overtime never wears below 0.
def wear_per_hour(
    capacity: str | dict[str, str],
    wear_per_period: str | dict[str, str],
    overtime_hours: str | dict[str, str] = "0",
) -> st.SearchStrategy[str]:
    hours = largest(capacity) + largest(overtime_hours)
    bound = (1 - largest(wear_per_period)) / hours
    return number_text(4, 0, bound.quantize(Decimal("0.0001"), rounding=ROUND_FLOOR))


# A demand shape of any kind, with any target form.
def demand_shapes(
    horizon: int, customers: list[str], products: list[str]
) -> st.SearchStrategy[dict[str, Any]]:
    targets = st.one_of(
        st.just("all"),
        st.sampled_from(customers).map(lambda customer: {"customer": customer}),
        st.sampled_from(products).map(lambda product: {"product": product}),
        st.tuples(st.sampled_from(customers), st.sampled_from(products)).map(
            lambda pair: {"customer": pair[0], "product": pair[1]}
        ),
    )
    factors = number_text(4, 0, 3)
    periods = st.integers(min_value=0, max_value=horizon + 1)
    ramps = st.tuples(periods, periods).filter(lambda pair: pair[0] < pair[1])
    return st.one_of(
        st.fixed_dictionaries(
            {
                "kind": st.just("trend"),
                "rate": number_text(4, Decimal("-0.5"), Decimal("0.5")),
            }
        ),
        st.fixed_dictionaries(
            {
                "kind": st.just("season"),
                "factors": st.lists(factors, min_size=1, max_size=4),
                "period_length": st.integers(min_value=1, max_value=13),
            }
        ),
        st.fixed_dictionaries(
            {"kind": st.just("step"), "period": periods, "factor": factors}
        ),
        st.tuples(ramps, factors, factors).map(
            lambda ramp: {
                "kind": "ramp",
                "first": ramp[0][0],
                "last": ramp[0][1],
                "from_factor": ramp[1],
                "to_factor": ramp[2],
            }
        ),
        st.fixed_dictionaries(
            {
                "kind": st.just("s_curve"),
                "middle": st.integers(min_value=-horizon, max_value=2 * horizon),
                "steepness": number_text(4, Decimal("0.0001"), 5),
                "from_factor": number_text(4, 0, 2),
                "to_factor": number_text(4, 0, 2),
            }
        ),
    ).flatmap(lambda shape: targets.map(lambda target: shape | {"target": target}))


# The smallest value of a fixed number or a range.
def smallest(value: str | dict[str, str]) -> Decimal:
    return Decimal(value["min"]) if isinstance(value, dict) else Decimal(value)


# The smallest price of a catalogue entry, its discount tiers included.
def lowest_price(entry: dict[str, Any]) -> Decimal:
    tier_prices = [smallest(tier["price"]) for tier in entry.get("discounts", [])]
    return min([smallest(entry["price"]), *tier_prices])


# Draw 0 to 2 discount tiers that fit their catalogue entry. Each `from` lies from the
# largest `min_quantity` to the smallest `max_quantity` and rises; each fixed price lies
# below the one before, the first below `price`.
def draw_discount_tiers(draw: st.DrawFn, entry: dict[str, Any]) -> list[dict[str, str]]:
    low = largest(entry.get("min_quantity", "0"))
    high = smallest(entry["max_quantity"])
    count = draw(st.integers(min_value=0, max_value=2))
    starts = sorted(
        set(
            draw(
                st.lists(
                    number_text(3, low, high).map(Decimal),
                    min_size=count,
                    max_size=count,
                )
            )
        )
    )
    tiers: list[dict[str, str]] = []
    ceiling = smallest(entry["price"]) - Decimal("0.0001")
    for start in starts:
        if ceiling < 0:
            break
        price = draw(number_text(4, 0, ceiling))
        tiers.append({"from": str(start), "price": price})
        ceiling = Decimal(price) - Decimal("0.0001")
    return tiers


# Draw salvage values no larger than the cost to buy or make each item. A material is
# worth at most its lowest price; a component or product at most its inputs at their
# salvage values plus the cost of the cheapest line that makes it.
def draw_salvage_values(draw: st.DrawFn, manifest: dict[str, Any]) -> None:
    for material_id, material in manifest["materials"].items():
        bound = min(
            lowest_price(supplier["catalogue"][material_id])
            for supplier in manifest["suppliers"].values()
        )
        material["salvage_value"] = draw(number_text(4, 0, bound))
    worth = {
        material_id: Decimal(material["salvage_value"])
        for material_id, material in manifest["materials"].items()
    }
    for kind in ("components", "products"):
        for item_id, item in manifest[kind].items():
            from_inputs = min(
                sum(
                    (
                        Decimal(quantity) * worth[input_id]
                        for input_id, quantity in recipe.items()
                    ),
                    Decimal(0),
                )
                for recipe in item["recipes"].values()
            )
            bound = min(
                from_inputs + smallest(line["items"][item_id]["cost"])
                for line in manifest["lines"].values()
                if item_id in line["items"]
            )
            item["salvage_value"] = draw(
                number_text(
                    4, 0, bound.quantize(Decimal("0.0001"), rounding=ROUND_FLOOR)
                )
            )
            worth[item_id] = Decimal(item["salvage_value"])


# Capacities from the space of the starting stock and orders to 100 more. The lower
# bound is that space rounded up to 3 places, and at least 0.001.
def warehouse_capacities(
    manifest: dict[str, Any],
    stock: dict[str, str],
    supplier_orders: list[dict[str, Any]],
) -> st.SearchStrategy[str]:
    items = manifest["materials"] | manifest["components"] | manifest["products"]
    held = [(item_id, quantity) for item_id, quantity in stock.items()] + [
        (order["material"], order["quantity"]) for order in supplier_orders
    ]
    space = sum(
        (
            Decimal(quantity) * Decimal(items[item_id]["space"])
            for item_id, quantity in held
        ),
        Decimal(0),
    )
    lowest = max(
        Decimal("0.001"), space.quantize(Decimal("0.001"), rounding=ROUND_CEILING)
    )
    return number_text(3, lowest, lowest + 100)


# 1 to 3 warehouses; `main` holds every kind, the others some kinds or all. Factors are
# left out or drawn from 0.0001 to 2.0000. The capacity is drawn later from the starting
# stock and orders.
def draw_warehouses(draw: st.DrawFn) -> dict[str, dict[str, Any]]:
    count = draw(st.integers(min_value=1, max_value=3))
    names = ["main", *(f"warehouse-{number}" for number in range(2, count + 1))]
    warehouses: dict[str, dict[str, Any]] = {}
    for name in names:
        terms: dict[str, Any] = {}
        if name != "main" and draw(st.booleans()):
            terms["accepts"] = draw(
                st.lists(
                    st.sampled_from(["materials", "components", "products"]),
                    min_size=1,
                    unique=True,
                )
            )
        for factor in ("storage_factor", "transport_factor"):
            if draw(st.booleans()):
                terms[factor] = draw(number_text(4, Decimal("0.0001"), 2))
        warehouses[name] = terms
    return warehouses


# The kinds of item a warehouse written as JSON holds, its groups left out.
def accepted_kinds(terms: dict[str, Any]) -> list[str]:
    accepts = terms.get("accepts", ["materials", "components", "products"])
    return [entry for entry in accepts if isinstance(entry, str)]


# The items a warehouse written as JSON holds: its kinds and its groups.
def accepted_items(terms: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    items = [
        item_id for kind in accepted_kinds(terms) for item_id in sorted(manifest[kind])
    ]
    groups: list[str] = [
        entry["group"] for entry in terms.get("accepts", []) if isinstance(entry, dict)
    ]
    for kind in ("materials", "components", "products"):
        for item_id, item in sorted(manifest[kind].items()):
            listed = set(item.get("groups", []))
            if listed & set(groups) and item_id not in items:
                items.append(item_id)
    return items


# The parameters a generated group may give, by the type of its members and the key
# of its defaults, each with its values. None of them meets a check that joins keys.
GROUP_PARAMETERS: dict[str, dict[str, dict[str, st.SearchStrategy[Any]]]] = {
    "suppliers": {
        "catalogue": {
            "punctuality": parameter_values(shares),
            "completeness": parameter_values(shares),
            "acceptance": parameter_values(shares),
        }
    },
    "products": {
        "items": {"storage_cost": parameter_values(money)},
        "customer_products": {
            "late_penalty": parameter_values(money),
            "lost_sale_penalty": parameter_values(money),
        },
    },
    "lines": {
        "lines": {
            "breakdown_chance": parameter_values(shares),
            "breakdown_loss": parameter_values(shares),
            "repair_cost": parameter_values(money),
        },
        "line_items": {"yield": parameter_values(shares)},
    },
}


# Add 0 to 2 groups each of suppliers, products and lines, with defaults; with
# `required`, one type drawn first has 1 to 2. The groups of one type have different
# kinds, 1 to 2 members and defaults of 0 to 2 parameters of `GROUP_PARAMETERS`. A
# member may leave out a value its group gives.
def draw_groups(
    draw: st.DrawFn, manifest: dict[str, Any], required: bool = False
) -> None:
    groups: dict[str, Any] = {}
    first_type = draw(st.sampled_from(sorted(GROUP_PARAMETERS))) if required else None
    for member_type, keys in GROUP_PARAMETERS.items():
        least = 1 if member_type == first_type else 0
        count = draw(st.integers(min_value=least, max_value=2))
        kinds = draw(st.permutations(GROUP_KINDS))[:count]
        for number, kind in enumerate(kinds, start=1):
            group_id = f"{member_type}-{kind}-{number}"
            members = draw(
                st.lists(
                    st.sampled_from(sorted(manifest[member_type])),
                    min_size=1,
                    max_size=2,
                    unique=True,
                )
            )
            defaults: dict[str, dict[str, Any]] = {}
            for key, values in keys.items():
                names = draw(
                    st.lists(st.sampled_from(sorted(values)), max_size=2, unique=True)
                )
                if names:
                    defaults[key] = {name: draw(values[name]) for name in names}
            groups[group_id] = {"kind": kind}
            if defaults:
                groups[group_id]["defaults"] = defaults
            for member_id in members:
                member = manifest[member_type][member_id]
                member["groups"] = [*member.get("groups", []), group_id]
                for key, given in defaults.items():
                    for target in group_targets(manifest, member_type, member_id, key):
                        for name in given:
                            if draw(st.booleans()):
                                target.pop(name, None)
    if groups:
        manifest["groups"] = groups


# The objects of the manifest that take the defaults of a member under a key.
def group_targets(
    manifest: dict[str, Any], member_type: str, member_id: str, key: str
) -> list[dict[str, Any]]:
    if key in ("items", "lines"):
        return [manifest[member_type][member_id]]
    if key == "catalogue":
        return list(manifest["suppliers"][member_id]["catalogue"].values())
    if key == "customer_products":
        return [
            customer["products"][member_id]
            for customer in manifest["customers"].values()
            if member_id in customer["products"]
        ]
    if member_type == "lines":
        return list(manifest["lines"][member_id]["items"].values())
    return [
        line["items"][member_id]
        for line in manifest["lines"].values()
        if member_id in line["items"]
    ]


# The manifest with the defaults of its groups written into members, no groups. A member
# takes each value it leaves out from the first group it lists that gives it. A
# catalogue entry asks the supplier's groups, then the material's; a customer product
# the customer's, then the product's; a line item the line's, then the item's.
def groups_written_out(manifest: dict[str, Any]) -> dict[str, Any]:
    flat = copy.deepcopy(manifest)
    groups = flat.pop("groups", {})
    items = flat["materials"] | flat["components"] | flat["products"]

    def listed(*members: dict[str, Any]) -> list[str]:
        return [group_id for member in members for group_id in member.get("groups", [])]

    def fill(target: dict[str, Any], group_ids: list[str], key: str) -> None:
        for group_id in group_ids:
            given = groups[group_id].get("defaults", {}).get(key, {})
            for name, value in given.items():
                target.setdefault(name, copy.deepcopy(value))

    for item in items.values():
        fill(item, listed(item), "items")
    for supplier in flat["suppliers"].values():
        for material_id, entry in supplier["catalogue"].items():
            fill(entry, listed(supplier, items[material_id]), "catalogue")
    for customer in flat["customers"].values():
        fill(customer, listed(customer), "customers")
        for product_id, terms in customer["products"].items():
            fill(terms, listed(customer, items[product_id]), "customer_products")
    for line in flat["lines"].values():
        fill(line, listed(line), "lines")
        for item_id, terms in line["items"].items():
            fill(terms, listed(line, items[item_id]), "line_items")
    members = [*items.values(), *flat["suppliers"].values()]
    members += [*flat["customers"].values(), *flat["lines"].values()]
    for member in members:
        member.pop("groups", None)
    return flat


# The pairs of customer and product a target of a shape or a forecast names.
def pairs_of_target(
    manifest: dict[str, Any], target: object, pairs: list[tuple[str, str]]
) -> set[tuple[str, str]]:
    if target == "all":
        return set(pairs)
    named = cast(dict[str, str], target)
    if "customer" in named or "product" in named:
        return {
            (customer, product)
            for customer, product in pairs
            if named.get("customer", customer) == customer
            and named.get("product", product) == product
        }
    group_id = next(iter(named.values()))
    return {
        (customer, product)
        for customer, product in pairs
        if group_id in manifest["products"][product].get("groups", [])
    }


# 0 to 2 forecast entries that target different pairs, with any target form.
def draw_forecasts(
    draw: st.DrawFn,
    manifest: dict[str, Any],
    horizon: int,
    pairs: list[tuple[str, str]],
    product_groups: list[dict[str, str]],
) -> list[dict[str, Any]]:
    customers = sorted(manifest["customers"])
    products = sorted({product for _, product in pairs})
    targets = st.one_of(
        st.just("all"),
        st.sampled_from(customers).map(lambda customer: {"customer": customer}),
        st.sampled_from(products).map(lambda product: {"product": product}),
        st.sampled_from(pairs).map(
            lambda pair: {"customer": pair[0], "product": pair[1]}
        ),
        *([st.sampled_from(product_groups)] if product_groups else []),
    )
    entries: list[dict[str, Any]] = []
    taken: set[tuple[str, str]] = set()
    for _ in range(draw(st.integers(min_value=0, max_value=2))):
        target = draw(targets)
        targeted = pairs_of_target(manifest, target, pairs)
        if targeted & taken:
            continue
        taken |= targeted
        entries.append(
            {
                "target": target,
                "periods_ahead": draw(st.integers(min_value=1, max_value=horizon)),
                "noise": draw(shares),
                "noise_growth": draw(shares),
            }
        )
    return entries


# A manifest and a scenario with 1 to 2 objects of each kind and one warehouse. With
# `defaults_only`, the manifest has at least one group, and groups only give defaults:
# no warehouse accepts a group and no target of the scenario names one.
@st.composite
def small_factories(draw: st.DrawFn, defaults_only: bool = False) -> FactoryBodies:
    horizon = draw(st.integers(min_value=1, max_value=8))
    periods = st.integers(min_value=0, max_value=horizon + 1).map(str)
    lead_times = st.integers(min_value=1, max_value=horizon + 1).map(str)

    def names(prefix: str) -> list[str]:
        count = draw(st.integers(min_value=1, max_value=2))
        return [f"{prefix}-{number}" for number in range(1, count + 1)]

    materials, components, products = (
        names("material"),
        names("component"),
        names("product"),
    )

    def item() -> dict[str, Any]:
        return {
            "space": draw(number_text(3, 1, 10)),
            "storage_cost": draw(parameter_values(money)),
        }

    def made_item(inputs: list[str]) -> dict[str, Any]:
        names = ["standard", "alternative"][
            : draw(st.integers(min_value=1, max_value=2))
        ]
        recipes = {
            name: {draw(st.sampled_from(inputs)): draw(number_text(3, 1, 5))}
            for name in names
        }
        made = item() | {"recipes": recipes}
        if len(names) > 1 or draw(st.booleans()):
            made["default_recipe"] = draw(st.sampled_from(names))
        return made

    def catalogue_entry() -> dict[str, Any]:
        entry = {
            "price": draw(parameter_values(money)),
            "lead_time": draw(parameter_values(lead_times)),
            "max_quantity": draw(
                parameter_values(number_text(3, Decimal("0.001"), 1000))
            ),
            "punctuality": draw(parameter_values(shares)),
            "delay": draw(parameter_values(lead_times)),
            "completeness": draw(parameter_values(shares)),
            "acceptance": draw(parameter_values(shares)),
        }
        if isinstance(entry["price"], dict) and draw(st.booleans()):
            entry["price"]["drawn"] = draw(st.sampled_from(["run", "period"]))
        if draw(st.booleans()):
            minimum = number_text(3, 0, smallest(entry["max_quantity"]))
            entry["min_quantity"] = draw(parameter_values(minimum))
        entry["discounts"] = draw_discount_tiers(draw, entry)
        if draw(st.booleans()):
            fee = number_text(4, 0, lowest_price(entry))
            entry["cancellation_fee"] = draw(parameter_values(fee))
        if draw(st.booleans()):
            backfill_delays = st.integers(min_value=0, max_value=horizon + 1)
            entry["backfill_delay"] = draw(parameter_values(backfill_delays.map(str)))
        shortest = int(smallest(entry["lead_time"]))
        if shortest > 1 and draw(st.booleans()):
            express_lead_times = st.integers(min_value=1, max_value=shortest - 1)
            entry["express_lead_time"] = draw(
                parameter_values(express_lead_times.map(str))
            )
            entry["express_cost"] = draw(parameter_values(money))
        return entry

    def customer_product() -> dict[str, Any]:
        terms = {
            "price": draw(parameter_values(money)),
            "transport_cost": draw(parameter_values(money)),
            "demand": draw(parameter_values(quantities)),
            "lead_time": draw(parameter_values(periods)),
            "patience": draw(parameter_values(periods)),
            "late_penalty": draw(parameter_values(money)),
            "lost_sale_penalty": draw(parameter_values(money)),
        }
        if isinstance(terms["demand"], dict) and draw(st.booleans()):
            terms["demand_persistence"] = draw(shares)
        return terms

    def line_item() -> dict[str, Any]:
        made = {
            "time": draw(parameter_values(number_text(3, 1, 5))),
            "cost": draw(parameter_values(money)),
            "yield": draw(parameter_values(shares)),
        }
        if draw(st.booleans()):
            lead_times = st.integers(min_value=1, max_value=horizon + 1)
            made["lead_time"] = draw(parameter_values(lead_times.map(str)))
        if draw(st.booleans()):
            made["changeover_time"] = draw(parameter_values(number_text(3, 0, 5)))
        if draw(st.booleans()):
            made["changeover_cost"] = draw(parameter_values(money))
        return made

    def line() -> dict[str, Any]:
        made = draw(
            st.lists(st.sampled_from(components + products), min_size=1, unique=True)
        )
        # A capacity of at least 10 hours lets most produces start.
        capacity = draw(
            parameter_values(
                st.one_of(
                    number_text(3, Decimal(10), 1000),
                    number_text(3, Decimal("0.001"), 1000),
                )
            )
        )
        wear_per_period = draw(parameter_values(shares))
        overtime: dict[str, Any] = {}
        if draw(st.booleans()):
            overtime["overtime_hours"] = draw(parameter_values(quantities))
            if largest(overtime["overtime_hours"]) > 0:
                overtime["overtime_cost"] = draw(parameter_values(money))
        overtime_hours = overtime.get("overtime_hours", "0")
        return overtime | {
            "capacity": capacity,
            "wear_per_period": wear_per_period,
            "wear_per_hour": draw(
                wear_per_hour(capacity, wear_per_period, overtime_hours)
            ),
            "breakdown_chance": draw(parameter_values(shares)),
            "breakdown_loss": draw(parameter_values(shares)),
            "repair_cost": draw(parameter_values(money)),
            "repair_time": draw(
                parameter_values(number_text(3, Decimal("0.001"), 1000))
            ),
            "repair_limit": draw(
                parameter_values(number_text(4, Decimal("0.0001"), 1))
            ),
            "items": {item_id: line_item() for item_id in made},
        }

    rates = sorted(draw(st.lists(shares, min_size=3, max_size=3)), key=Decimal)
    manifest: dict[str, Any] = {
        "materials": {material: item() for material in materials},
        "components": {component: made_item(materials) for component in components},
        "products": {product: made_item(components) for product in products},
        "suppliers": {
            supplier: {
                "catalogue": {material: catalogue_entry() for material in materials}
            }
            for supplier in names("supplier")
        },
        "customers": {
            customer: {
                "products": {
                    product: customer_product()
                    for product in draw(
                        st.lists(st.sampled_from(products), min_size=1, unique=True)
                    )
                }
            }
            for customer in names("customer")
        },
        "lines": {line_id: line() for line_id in names("line")},
        "warehouses": draw_warehouses(draw),
        "cash": {
            "credit_limit": draw(money),
            "credit_interest": rates[0],
            "debit_interest": rates[1],
            "overdraft_interest": rates[2],
        },
    }
    warehouses = manifest["warehouses"]
    routes = {
        source: {
            destination: {
                "cost": draw(parameter_values(money)),
                "lead_time": draw(parameter_values(periods)),
            }
            for destination in sorted(warehouses)
            if destination != source and draw(st.booleans())
        }
        for source in sorted(warehouses)
    }
    routes = {source: reached for source, reached in routes.items() if reached}
    if routes:
        manifest["routes"] = routes
    # Every line stands in one warehouse that holds every kind, so every line can
    # reach its items.
    full = [name for name, terms in warehouses.items() if "accepts" not in terms]
    home = draw(st.sampled_from(full))
    for line_terms in manifest["lines"].values():
        if len(warehouses) > 1 or draw(st.booleans()):
            line_terms["warehouse"] = home
    first_line = manifest["lines"][sorted(manifest["lines"])[0]]["items"]
    for item_id in components + products:
        if all(item_id not in line["items"] for line in manifest["lines"].values()):
            first_line[item_id] = line_item()
    terms = st.integers(min_value=0, max_value=horizon + 1)
    for customer in manifest["customers"].values():
        choice = draw(st.sampled_from(["left out", "fixed", "range"]))
        if choice == "fixed":
            customer["payment_terms"] = draw(terms)
        if choice == "range":
            low, high = sorted(draw(st.lists(terms, min_size=2, max_size=2)))
            customer["payment_terms"] = {"min": low, "max": high}
    first_customer = manifest["customers"][sorted(manifest["customers"])[0]]
    for product in products:
        if all(
            product not in customer["products"]
            for customer in manifest["customers"].values()
        ):
            first_customer["products"][product] = customer_product()
    for product in products:
        buyers = [
            customer
            for customer in manifest["customers"].values()
            if isinstance(customer["products"].get(product, {}).get("demand"), dict)
        ]
        if len(buyers) >= 2 and draw(st.booleans()):
            manifest["products"][product]["common_share"] = draw(shares)
    draw_salvage_values(draw, manifest)
    draw_groups(draw, manifest, defaults_only)
    product_groups = sorted(
        group_id
        for group_id in manifest.get("groups", {})
        if group_id.startswith("products-")
    )
    for terms in manifest["warehouses"].values():
        if (
            "accepts" in terms
            and product_groups
            and not defaults_only
            and draw(st.booleans())
        ):
            terms["accepts"].append({"group": draw(st.sampled_from(product_groups))})
    pairs = [
        (customer, product)
        for customer, terms in manifest["customers"].items()
        for product in terms["products"]
    ]
    starting_orders = [
        {
            "customer": customer,
            "product": product,
            "quantity": draw(number_text(3, Decimal("0.001"), 1000)),
            "due": draw(st.integers(min_value=1, max_value=horizon)),
        }
        for customer, product in draw(st.lists(st.sampled_from(pairs), max_size=2))
    ]
    catalogue_pairs = [
        (supplier, material)
        for supplier, terms in manifest["suppliers"].items()
        for material in terms["catalogue"]
    ]
    holding_materials = sorted(
        name
        for name, terms in warehouses.items()
        if "materials" in accepted_kinds(terms)
    )
    starting_supplier_orders = [
        {
            "supplier": supplier,
            "material": material,
            "quantity": draw(number_text(3, Decimal("0.001"), 1000)),
            "arrival": draw(st.integers(min_value=1, max_value=horizon)),
            "warehouse": draw(st.sampled_from(holding_materials)),
        }
        for supplier, material in draw(
            st.lists(st.sampled_from(catalogue_pairs), max_size=2)
        )
    ]
    if len(warehouses) == 1:
        for order in starting_supplier_orders:
            if draw(st.booleans()):
                del order["warehouse"]
    targets = {
        "supplier_outage": sorted(manifest["suppliers"]),
        "material_shortage": materials,
        "quality_drop": sorted(manifest["suppliers"]),
        "transport_delay": sorted(manifest["suppliers"]),
        "demand_shock": products,
        "line_breakdown": sorted(manifest["lines"]),
        "price_change": materials,
        "capacity_cut": sorted(manifest["lines"]),
        "yield_drop": sorted(manifest["lines"]),
    }
    effects = {
        "supplier_outage": ("strength", shares),
        "material_shortage": ("strength", shares),
        "quality_drop": ("strength", shares),
        "transport_delay": ("delay", st.integers(min_value=1, max_value=3)),
        "demand_shock": ("factor", number_text(4, Decimal("0.0001"), 3)),
        "line_breakdown": ("loss", shares),
        "price_change": ("factor", number_text(4, 1, 3)),
        "capacity_cut": ("strength", shares),
        "yield_drop": ("strength", shares),
    }

    group_targets_of_type = {
        member_type: [
            {group["kind"]: group_id}
            for group_id, group in sorted(manifest.get("groups", {}).items())
            if group_id.startswith(f"{member_type}-") and not defaults_only
        ]
        for member_type in ("suppliers", "products", "lines")
    }
    target_types = {
        "supplier_outage": "suppliers",
        "quality_drop": "suppliers",
        "transport_delay": "suppliers",
        "demand_shock": "products",
        "line_breakdown": "lines",
        "capacity_cut": "lines",
        "yield_drop": "lines",
    }

    def disruption(kind: str) -> dict[str, Any]:
        key, values = effects[kind]
        group_targets = group_targets_of_type.get(target_types.get(kind, ""), [])
        choices: list[st.SearchStrategy[Any]] = [
            st.just("all"),
            st.lists(st.sampled_from(targets[kind]), min_size=1, unique=True),
        ]
        if group_targets:
            choices.append(st.sampled_from(group_targets))
        written: dict[str, Any] = {
            "kind": kind,
            "target": draw(st.one_of(choices)),
            "start": draw(st.integers(min_value=1, max_value=horizon)),
            key: draw(values),
        }
        if kind != "line_breakdown":
            written["duration"] = draw(st.integers(min_value=1, max_value=horizon))
        written["notice"] = draw(
            st.integers(min_value=0, max_value=written["start"] - 1)
        )
        return written

    disruptions = [
        disruption(kind)
        for kind in draw(st.lists(st.sampled_from(sorted(effects)), max_size=3))
    ]
    random_effects: dict[str, st.SearchStrategy[Any]] = {
        "supplier_outage": parameter_values(shares),
        "material_shortage": parameter_values(shares),
        "quality_drop": parameter_values(shares),
        "transport_delay": parameter_values(
            st.integers(min_value=1, max_value=3).map(str)
        ),
        "demand_shock": parameter_values(number_text(4, Decimal("0.0001"), 3)),
        "line_breakdown": parameter_values(shares),
        "price_change": parameter_values(number_text(4, 1, 3)),
        "capacity_cut": parameter_values(shares),
        "yield_drop": parameter_values(shares),
    }

    # A rule starts by chance, by chance on one chosen target, or at a written start.
    # Half the rules of a scenario with written disruptions take the kind, the
    # target and the start of one of them, so that both act on one object in one period.
    def random_disruption(name: str) -> dict[str, Any]:
        copied = bool(disruptions) and draw(st.booleans())
        if copied:
            written = draw(st.sampled_from(disruptions))
            kind = written["kind"]
            starts = "start"
        else:
            kind = draw(st.sampled_from(sorted(random_effects)))
            written = disruption(kind)
            starts = draw(st.sampled_from(["chance", "choose", "start"]))
        key = effects[kind][0]
        rule: dict[str, Any] = {"name": name, "kind": kind, "target": written["target"]}
        if starts != "start":
            rule["chance"] = draw(shares)
        rule[key] = draw(random_effects[kind])
        if kind != "line_breakdown":
            rule["duration"] = draw(
                parameter_values(st.integers(min_value=1, max_value=3).map(str))
            )
        if starts == "choose":
            rule["choose"] = "one"
        if copied:
            rule["notice"] = draw(
                st.integers(min_value=0, max_value=written["start"] - 1)
            )
            rule["start"] = written["start"]
        elif starts == "start":
            rule["notice"] = draw(st.integers(min_value=0, max_value=horizon - 1))
            rule["start"] = draw(
                st.integers(min_value=rule["notice"] + 1, max_value=horizon)
            )
        else:
            rule["notice"] = draw(st.integers(min_value=0, max_value=horizon))
        return rule

    random_disruptions = [
        random_disruption(name)
        for name in draw(
            st.lists(
                st.sampled_from(["rule-a", "rule-b", "disruption-9"]),
                max_size=2,
                unique=True,
            )
        )
    ]
    # With two rules, the first sometimes raises the chance of the second.
    if (
        len(random_disruptions) == 2
        and "start" not in random_disruptions[1]
        and draw(st.booleans())
    ):
        random_disruptions[0]["raises"] = {
            "rule": random_disruptions[1]["name"],
            "factor": draw(number_text(4, Decimal("1.0001"), 5)),
            "periods": draw(st.integers(min_value=1, max_value=3)),
        }
    customers = sorted(manifest["customers"])
    shapes = draw(st.lists(demand_shapes(horizon, customers, products), max_size=3))
    for shape in shapes:
        target = shape["target"]
        if isinstance(target, dict) and len(cast(dict[str, str], target)) == 2:
            customer, product = draw(st.sampled_from(pairs))
            shape["target"] = {"customer": customer, "product": product}
        if group_targets_of_type["products"] and draw(st.booleans()):
            shape["target"] = draw(st.sampled_from(group_targets_of_type["products"]))
    forecasts = draw_forecasts(
        draw, manifest, horizon, pairs, group_targets_of_type["products"]
    )
    scenario_stock: dict[str, dict[str, str]] = {
        warehouse_id: {
            item_id: draw(quantities)
            for item_id in draw(
                st.lists(
                    st.sampled_from(accepted_items(terms, manifest)),
                    unique=True,
                )
            )
        }
        for warehouse_id, terms in warehouses.items()
    }
    for material in materials:
        fastest = min(
            largest(supplier["catalogue"][material]["lead_time"])
            for supplier in manifest["suppliers"].values()
        )
        stock = scenario_stock[home]
        if fastest >= horizon and Decimal(stock.get(material, "0")) == 0:
            stock[material] = draw(number_text(3, Decimal("0.001"), 1000))
    for warehouse_id, terms in warehouses.items():
        orders = [
            order
            for order in starting_supplier_orders
            if order.get("warehouse", "main") == warehouse_id
        ]
        terms["capacity"] = draw(
            warehouse_capacities(manifest, scenario_stock[warehouse_id], orders)
        )
    set_for = {
        line_id: draw(st.sampled_from(sorted(line["items"])))
        for line_id, line in manifest["lines"].items()
        if draw(st.booleans())
    }
    condition = {
        line_id: draw(shares)
        for line_id in sorted(manifest["lines"])
        if draw(st.booleans())
    }
    # Starting cash from 1000 to 100000, so that most buys pass the credit limit; one in
    # five from 100 below minus the credit limit to 100, so that some runs refuse a buy
    # for cash.
    low_cash = -Decimal(manifest["cash"]["credit_limit"]) - 100
    cash = one_in_five(number_text(4, 1000, 100000), number_text(4, low_cash, 100))
    scenario = {
        "horizon": horizon,
        "demand_shapes": shapes,
        "forecasts": forecasts,
        "disruptions": disruptions,
        "random_disruptions": random_disruptions,
        "hidden": draw(st.lists(st.sampled_from(HIDDEN_GROUPS), unique=True)),
        "start": {
            "cash": draw(cash),
            "stock": scenario_stock,
            "customer_orders": starting_orders,
            "supplier_orders": starting_supplier_orders,
            "set_for": set_for,
            "condition": condition,
        },
    }
    return manifest, scenario


# Counts of a generated manifest, each from 1 to 8, with no more lines than made items.
@st.composite
def generator_counts(draw: st.DrawFn) -> dict[str, int]:
    counts = {
        kind: draw(st.integers(min_value=1, max_value=8))
        for kind in ("materials", "components", "products", "suppliers", "customers")
    }
    made = counts["components"] + counts["products"]
    counts["lines"] = draw(st.integers(min_value=1, max_value=min(8, made)))
    return counts


# The same factory without minimum quantities, discounts and changeovers. Without them
# the factory is linear.
def without_integer_keys(
    bodies: FactoryBodies,
) -> FactoryBodies:
    manifest, scenario = bodies
    for supplier in manifest["suppliers"].values():
        for entry in supplier["catalogue"].values():
            entry.pop("min_quantity", None)
            entry.pop("discounts", None)
    for line in manifest["lines"].values():
        for terms in line["items"].values():
            terms.pop("changeover_time", None)
            terms.pop("changeover_cost", None)
    return manifest, scenario


# The bodies of small worlds of a future minimum whose later yes-or-no choices can bind:
# 3 to 5 periods; chips without terms, with a minimum quantity or with a discount tier;
# a price change of chips in period 2; a changeover cost of the monitor or none; a
# starting cash that a starting order lost in period 1 can use up; and one order of 4 or
# 8 monitors due in the last period, from no chips or 16.
@st.composite
def future_choice_bodies(draw: st.DrawFn) -> FactoryBodies:
    manifest, scenario = future_minimum_bodies()
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    del entry["min_quantity"]
    terms = draw(st.sampled_from(("none", "minimum", "discount")))
    if terms == "minimum":
        entry["min_quantity"] = draw(st.sampled_from(("10.000", "20.000", "30.000")))
    if terms == "discount":
        start = draw(st.sampled_from(("20.000", "30.000")))
        entry["discounts"] = [{"from": start, "price": "0.4000"}]
    changeover_cost = draw(st.sampled_from((None, "50.0000", "250.0000")))
    if changeover_cost is not None:
        monitor = manifest["lines"]["line-1"]["items"]["monitor"]
        monitor["changeover_cost"] = changeover_cost
    horizon = draw(st.integers(min_value=3, max_value=5))
    factor = draw(st.sampled_from(("0.5000", "0.8000", "1.1000", "1.5000")))
    scenario["horizon"] = horizon
    scenario["disruptions"][0]["factor"] = factor
    start = scenario["start"]
    start["cash"] = draw(st.sampled_from(("10", "20", "1000")))
    if draw(st.booleans()):
        start["stock"] = {"main": {"chip": "16"}}
    order = start["customer_orders"][0]
    order |= {"quantity": draw(st.sampled_from(("4", "8"))), "due": horizon}
    if draw(st.booleans()):
        lost = {"customer": "distributor", "product": "monitor", "quantity": "1"}
        start["customer_orders"].insert(0, lost | {"due": 1})
    return manifest, scenario


# The bodies of small worlds of starting supplier orders: 3 to 5 periods of the plain
# tiny factory with one or two starting orders of chips arriving from period 2; a
# minimum quantity, a discount tier at 0.4000 or neither; a cancellation fee from 0 to
# the lowest price; demand of 0 or 4 monitors; cash of 10 or 1000 and a credit limit of
# 0 or 100; a warehouse of capacity 1 or 100, from no stock or 16 chips.
@st.composite
def starting_order_bodies(draw: st.DrawFn) -> FactoryBodies:
    manifest, scenario = unwanted_order_bodies()
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    fees = ["0.0000", "0.1000", "0.4000", "0.4500", "0.5000"]
    terms = draw(st.sampled_from(("none", "minimum", "discount")))
    if terms == "minimum":
        entry["min_quantity"] = "20.000"
    if terms == "discount":
        entry["discounts"] = [{"from": "20.000", "price": "0.4000"}]
        fees = fees[:3]
    entry["cancellation_fee"] = draw(st.sampled_from(fees))
    pair = manifest["customers"]["distributor"]["products"]["monitor"]
    pair["demand"] = draw(st.sampled_from(("0.000", "4.000")))
    manifest["cash"]["credit_limit"] = draw(st.sampled_from(("0.0000", "100.0000")))
    capacity = draw(st.sampled_from(("1.000", "100.000")))
    manifest["warehouses"]["main"]["capacity"] = capacity
    horizon = draw(st.integers(min_value=3, max_value=5))
    scenario["horizon"] = horizon
    start = scenario["start"]
    start["cash"] = draw(st.sampled_from(("10", "1000")))
    if draw(st.booleans()):
        start["stock"] = {"main": {"chip": "16"}}
    count = draw(st.integers(min_value=1, max_value=2))
    order = {"supplier": "chip-maker", "material": "chip"}
    start["supplier_orders"] = [
        order
        | {
            "quantity": draw(st.sampled_from(("10", "20", "40"))),
            "arrival": draw(st.integers(min_value=2, max_value=horizon)),
        }
        for _ in range(count)
    ]
    return manifest, scenario


# Small networks of warehouses: 1 or 2 periods of the world of an ordered transfer,
# with 1 to 3 routes among main, buffer and remote, each of lead time 0 or 1; a buffer
# that takes materials only or every item; up to 3 chips and 1 board in each warehouse
# that takes them, at least 1 chip in main; remote at a storage factor of 1 or 100; in
# 2 periods a starting order of 2 chips into one warehouse, arriving in period 2; and
# each capacity 0, 0.010, 0.020 or 1 above the space its stock and starting order
# take, and at least 0.010.
@st.composite
def transfer_networks(draw: st.DrawFn) -> FactoryBodies:
    manifest, scenario = ordered_transfer_bodies()
    warehouses = manifest["warehouses"]
    if draw(st.booleans()):
        del warehouses["buffer"]["accepts"]
    warehouses["remote"]["storage_factor"] = draw(
        st.sampled_from(("1.0000", "100.0000"))
    )
    ends = [
        (source, destination)
        for source in sorted(warehouses)
        for destination in sorted(warehouses)
        if source != destination
    ]
    chosen = draw(st.lists(st.sampled_from(ends), min_size=1, max_size=3, unique=True))
    routes: dict[str, dict[str, Any]] = {}
    for source, destination in chosen:
        lead_time = draw(st.sampled_from((0, 1)))
        route = {"cost": "0.0000", "lead_time": lead_time}
        routes.setdefault(source, {})[destination] = route
    manifest["routes"] = routes
    horizon = draw(st.sampled_from((1, 2)))
    scenario["horizon"] = horizon
    start = scenario["start"]
    space = {"chip": Decimal("0.010"), "board": Decimal("0.020")}
    held = dict.fromkeys(warehouses, Decimal(0))
    for warehouse_id in warehouses:
        items = ["chip"] if "accepts" in warehouses[warehouse_id] else ["chip", "board"]
        # A horizon of 1 needs a chip at hand, as no buy arrives within it.
        least = 1 if warehouse_id == "main" else 0
        stock = {
            "chip": draw(st.integers(min_value=least, max_value=3)),
            "board": draw(st.integers(min_value=0, max_value=1)),
        }
        stock = {item: units for item, units in stock.items() if item in items}
        start["stock"][warehouse_id] = {
            item: str(units) for item, units in stock.items()
        }
        held[warehouse_id] = sum(
            (units * space[item] for item, units in stock.items()), Decimal(0)
        )
    if horizon == 2 and draw(st.booleans()):
        warehouse_id = draw(st.sampled_from(sorted(warehouses)))
        start["supplier_orders"] = [
            {
                "supplier": "chip-maker",
                "material": "chip",
                "warehouse": warehouse_id,
                "quantity": "2",
                "arrival": 2,
            }
        ]
        held[warehouse_id] += 2 * space["chip"]
    for warehouse_id, warehouse in warehouses.items():
        extra = draw(st.sampled_from(("0.000", "0.010", "0.020", "1.000")))
        warehouse["capacity"] = str(
            max(held[warehouse_id], Decimal("0.010")) + Decimal(extra)
        )
    return manifest, scenario


# Small factories without minimum quantities, discounts and changeovers.
def linear_factories() -> st.SearchStrategy[FactoryBodies]:
    return small_factories().map(without_integer_keys)


# `unknown` one time in five and `known` otherwise. The choice is among five equal
# values, so Hypothesis cannot merge the two branches.
def one_in_five[T](
    known: st.SearchStrategy[T], unknown: st.SearchStrategy[T]
) -> st.SearchStrategy[T]:
    return st.sampled_from((False, False, False, False, True)).flatmap(
        lambda is_unknown: unknown if is_unknown else known
    )


# A `warehouse` key of a ship or buy; one in five names an unknown warehouse. With one
# warehouse the key may also be left out.
def warehouse_keys(world: World) -> st.SearchStrategy[dict[str, str]]:
    names = st.sampled_from(sorted(world.factory.warehouses))
    named = one_in_five(names, st.just("north-depot")).map(
        lambda warehouse: {"warehouse": warehouse}
    )
    if len(world.factory.warehouses) == 1:
        left_out: dict[str, str] = {}
        return st.one_of(st.just(left_out), named)
    return named


# Decisions with a `warehouse` key drawn by `warehouse_keys`.
def with_warehouse(
    decisions: st.SearchStrategy[dict[str, Any]], world: World
) -> st.SearchStrategy[dict[str, Any]]:
    return st.tuples(decisions, warehouse_keys(world)).map(
        lambda pair: pair[0] | pair[1]
    )


# Up to 6 ship decisions; one in five, or all when no order is open, is unknown. A ship
# of a known order names a warehouse that holds its product and ships 0.001 to its open
# quantity or that stock; one in five takes its warehouse key from `warehouse_keys`, and
# one in five ships 0.001 to 1000 units.
def ship_lists(world: World, state: State) -> st.SearchStrategy[list[dict[str, Any]]]:
    orders = {order.id: order for order in state.customer_orders}
    order_ids = st.sampled_from(sorted(orders)) if orders else st.just("order-99-1")
    order_or_unknown = one_in_five(order_ids, st.just("order-99-1"))
    any_quantity = number_text(3, Decimal("0.001"), 1000)

    def ship(order_id: str) -> st.SearchStrategy[dict[str, Any]]:
        anywhere = st.fixed_dictionaries(
            {
                "kind": st.just("ship"),
                "order": st.just(order_id),
                "quantity": any_quantity,
            }
        )
        order = orders.get(order_id)
        if order is None:
            return with_warehouse(anywhere, world)
        held = {
            warehouse_id: min(order.quantity - order.shipped, items[order.product])
            for warehouse_id, items in state.stock.items()
            if items.get(order.product, Decimal(0)) > 0
        }
        held = {key: most for key, most in held.items() if most >= Decimal("0.001")}
        if not held:
            return with_warehouse(anywhere, world)
        held_ship = st.sampled_from(sorted(held)).flatmap(
            lambda warehouse_id: st.fixed_dictionaries(
                {
                    "kind": st.just("ship"),
                    "order": st.just(order_id),
                    "quantity": one_in_five(
                        number_text(3, Decimal("0.001"), held[warehouse_id]),
                        any_quantity,
                    ),
                    "warehouse": st.just(warehouse_id),
                }
            )
        )
        return one_in_five(held_ship, with_warehouse(anywhere, world))

    return st.lists(order_or_unknown.flatmap(ship), max_size=6)


# Up to 6 produces of items the lines make, 0.001 to 100 units, often below 2. One in
# five names `line-9` or an item its line does not make. A produce names one of the
# recipes of its item, an unknown recipe, or none, and a start from 1 to the horizon,
# one in five 0 or horizon + 1, or none.
def produce_lists(world: World) -> st.SearchStrategy[list[dict[str, Any]]]:
    horizon = world.scenario.horizon
    starts = one_in_five(
        st.integers(min_value=1, max_value=horizon), st.sampled_from((0, horizon + 1))
    )
    factory = world.factory
    pairs = [
        (line_id, item_id)
        for line_id, line in factory.lines.items()
        for item_id in line.items
    ]
    items = [*factory.materials, *factory.components, *factory.products]
    unknown_pairs = [("line-9", item_id) for _, item_id in pairs] + [
        (line_id, item_id)
        for line_id, line in factory.lines.items()
        for item_id in items
        if item_id not in line.items
    ]

    def produce(pair: tuple[str, str]) -> st.SearchStrategy[dict[str, Any]]:
        made = factory.components.get(pair[1]) or factory.products.get(pair[1])
        names = sorted(made.recipes) if made else []
        recipes = st.sampled_from([*names, "premium"])
        return st.fixed_dictionaries(
            {
                "kind": st.just("produce"),
                "line": st.just(pair[0]),
                "item": st.just(pair[1]),
                # Small quantities fit the hours of a line, large ones test the limit.
                "quantity": st.one_of(
                    number_text(3, Decimal("0.001"), 2),
                    number_text(3, Decimal("0.001"), 100),
                ),
                "overtime": st.booleans(),
            },
            optional={"recipe": recipes, "start": starts},
        )

    named = one_in_five(st.sampled_from(pairs), st.sampled_from(unknown_pairs))
    return st.lists(named.flatmap(produce), max_size=6)


# Up to 6 buys of materials in a catalogue, from the drawn `min_quantity` of the entry,
# or 0.001, to 10 units more within its drawn `max_quantity`, which fit space and cash
# more often, or to its `max_quantity`, or from the `from` of one of its discount tiers
# to 10 units more; one in five 0.001 to 1000 units. Express or not when the entry has
# express, one in five express when it has not. One in five names `supplier-9` or a
# material outside the catalogue, `material-9`.
def buy_lists(world: World) -> st.SearchStrategy[list[dict[str, Any]]]:
    pairs = [
        (supplier_id, material_id)
        for supplier_id, supplier in world.factory.suppliers.items()
        for material_id in supplier.catalogue
    ]
    unknown_pairs = [("supplier-9", material_id) for _, material_id in pairs] + [
        (supplier_id, "material-9") for supplier_id in world.factory.suppliers
    ]
    named = one_in_five(st.sampled_from(pairs), st.sampled_from(unknown_pairs))

    def buy(pair: tuple[str, str]) -> st.SearchStrategy[dict[str, Any]]:
        supplier = world.factory.suppliers.get(pair[0])
        entry = supplier.catalogue.get(pair[1]) if supplier else None
        path = f"suppliers.{pair[0]}.catalogue.{pair[1]}"
        most = world.parameters.get(f"{path}.max_quantity", Decimal(1000))
        least = world.parameters.get(f"{path}.min_quantity", Decimal("0.001"))
        low = max(min(least, most), Decimal("0.001"))
        tiers = [max(tier.from_, low) for tier in entry.discounts] if entry else []
        at_tiers = st.sampled_from(tiers or [low]).flatmap(
            lambda start: number_text(3, start, max(min(start + 10, most), start))
        )
        buy_quantities = st.one_of(
            number_text(3, low, max(min(low + 10, most), low)),
            number_text(3, low, max(most, low)),
            at_tiers,
        )
        has_express = entry is not None and entry.express_lead_time is not None
        return st.fixed_dictionaries(
            {
                "kind": st.just("buy"),
                "supplier": st.just(pair[0]),
                "material": st.just(pair[1]),
                "quantity": one_in_five(
                    buy_quantities, number_text(3, Decimal("0.001"), 1000)
                ),
                "express": st.booleans()
                if has_express
                else one_in_five(st.just(False), st.just(True)),
            }
        )

    return st.lists(with_warehouse(named.flatmap(buy), world), max_size=6)


# Up to 6 ships of the open orders an observation shows, produces, buys and transfers of
# its stock.
def observed_decision_lists(
    world: World, observation: dict[str, Any]
) -> st.SearchStrategy[list[dict[str, Any]]]:
    known = [order["id"] for order in observation["customer_orders"]]
    order_ids = st.sampled_from(known) if known else st.just("order-99-1")
    ships = st.fixed_dictionaries(
        {
            "kind": st.just("ship"),
            "order": order_ids,
            "quantity": number_text(3, Decimal("0.001"), 100),
        }
    )
    parts = st.tuples(
        st.lists(with_warehouse(ships, world), max_size=6),
        produce_lists(world),
        buy_lists(world),
        transfer_lists(world, observation["stock"]),
    )
    return parts.map(lambda lists: [*lists[0], *lists[1], *lists[2], *lists[3]][:6])


# Up to 4 cancels of open supplier orders and plans. A supplier order is cancelled by
# 0.001 to its open quantity, or all of it; a plan without a quantity or, to be
# refused, with one.
def cancel_lists(state: State) -> st.SearchStrategy[list[dict[str, Any]]]:
    sources: list[st.SearchStrategy[dict[str, Any]]] = []
    if state.supplier_orders:
        sources.append(
            st.sampled_from(state.supplier_orders).flatmap(
                lambda order: st.fixed_dictionaries(
                    {
                        "kind": st.just("cancel"),
                        "order": st.just(order.id),
                        "quantity": st.one_of(
                            number_text(3, Decimal("0.001"), order.open_quantity),
                            st.just(str(order.open_quantity)),
                        ),
                    }
                )
            )
        )
    if state.plans:
        sources.append(
            st.sampled_from(state.plans).flatmap(
                lambda plan: st.fixed_dictionaries(
                    {"kind": st.just("cancel"), "order": st.just(plan.id)},
                    optional={"quantity": st.just("1")},
                )
            )
        )
    if not sources:
        return st.just([])
    return st.lists(st.one_of(sources), max_size=4)


# Up to 4 transfers of items in stock, 0.001 to that stock, to another warehouse. The
# destination is any other warehouse, so some transfers name no route.
def transfer_lists(
    world: World, stock: Mapping[str, Mapping[str, Decimal]]
) -> st.SearchStrategy[list[dict[str, Any]]]:
    held = [
        (warehouse_id, item_id, quantity)
        for warehouse_id, items in stock.items()
        for item_id, quantity in items.items()
        if quantity > 0
    ]
    others = {
        warehouse_id: sorted(set(world.factory.warehouses) - {warehouse_id})
        for warehouse_id in world.factory.warehouses
    }
    held = [entry for entry in held if others[entry[0]]]
    if not held:
        return st.just([])
    transfers = st.sampled_from(held).flatmap(
        lambda entry: st.fixed_dictionaries(
            {
                "kind": st.just("transfer"),
                "item": st.just(entry[1]),
                "quantity": number_text(3, Decimal("0.001"), entry[2]),
                "source": st.just(entry[0]),
                "destination": st.sampled_from(others[entry[0]]),
            }
        )
    )
    return st.lists(transfers, max_size=4)


# Up to 6 decisions of every kind in one submission, in any order.
def mixed_decision_lists(
    world: World, state: State
) -> st.SearchStrategy[list[dict[str, Any]]]:
    parts = st.tuples(
        ship_lists(world, state),
        cancel_lists(state),
        transfer_lists(world, state.stock),
        repair_lists(world),
        produce_lists(world),
        buy_lists(world),
    )
    every = parts.map(lambda lists: [decision for part in lists for decision in part])
    return every.flatmap(st.permutations).map(lambda decisions: decisions[:6])


# Decisions of every kind, or up to 10 repairs and produces, or up to 12 produces and
# buys, which fill the hours of lines further than 6 decisions can.
def long_decision_lists(
    world: World, state: State
) -> st.SearchStrategy[list[dict[str, Any]]]:
    return st.one_of(
        mixed_decision_lists(world, state),
        st.tuples(repair_lists(world), produce_lists(world)).map(
            lambda lists: [*lists[0], *lists[1]]
        ),
        st.tuples(produce_lists(world), buy_lists(world)).map(
            lambda lists: [*lists[0], *lists[1]]
        ),
    )


# Run the bodies of a factory with decisions drawn from each period's state, of every
# kind unless another strategy is given.
def drawn_run(
    bodies: FactoryBodies,
    seed: int,
    draw: Draw,
    decision_lists: DecisionLists = mixed_decision_lists,
) -> tuple[World, list[RunStep]]:
    world = draw_world_of_bodies(*bodies, seed=seed)
    state = build_state(world)
    steps: list[RunStep] = []
    while not state.finished:
        decided = start_period(state, world)
        decisions = draw(decision_lists(world, decided))
        state = decide(decided, world, decisions)
        steps.append((decided, decisions, state))
    return world, steps


# A run of a small factory with decisions of every kind drawn in each period.
@st.composite
def drawn_runs(draw: st.DrawFn) -> tuple[World, list[RunStep]]:
    return drawn_run(draw(small_factories()), draw(seeds), draw)


# Starting cash from -3 to 3 times the credit limit, and in half of the draws at or
# below minus the limit, so that many runs go below the credit limit.
def start_cash(limit: Decimal) -> st.SearchStrategy[str]:
    return st.one_of(
        number_text(4, -3 * limit, 3 * limit), number_text(4, -3 * limit, -limit)
    )


# A run of a small factory, in half of the draws from a starting cash near its credit
# limit, with decisions of every kind or with long lists of repairs, produces and buys.
@st.composite
def small_factory_runs(draw: st.DrawFn) -> tuple[World, list[RunStep]]:
    manifest, scenario = draw(small_factories())
    if draw(st.booleans()):
        limit = Decimal(manifest["cash"]["credit_limit"])
        scenario["start"]["cash"] = draw(start_cash(limit))
    decision_lists = (
        long_decision_lists if draw(st.booleans()) else mixed_decision_lists
    )
    return drawn_run((manifest, scenario), draw(seeds), draw, decision_lists)


# How many of the 200 examples CI draws of a strategy reach a case, and how many were
# drawn, from the generate phase only. A local run draws the same 200 examples.
def count_reached[T](
    strategy: st.SearchStrategy[T], reaches: Callable[[T], bool]
) -> tuple[int, int]:
    reached: list[bool] = []

    @settings(
        max_examples=200,
        phases=[Phase.generate],
        database=None,
        deadline=None,
        derandomize=True,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )
    @hypothesis.given(strategy)
    def measure(value: T) -> None:
        reached.append(reaches(value))

    measure()
    return sum(reached), len(reached)


# A quantity from one unit of the last place up to `high`.
def random_quantity(generator: Random, high: Decimal, places: int = 3) -> str:
    steps = max(1, int(high * 10**places))
    return str(Decimal(generator.randint(1, steps)).scaleb(-places))


# Up to 8 decisions of every kind for a state, drawn from a random generator. The
# decisions scale to a factory of any size: ships of open orders, produces up to the
# capacity of a line, buys up to the largest quantity, transfers along routes, repairs
# and cancels, in random order.
def random_decisions(
    generator: Random, world: World, state: State
) -> list[dict[str, Any]]:
    factory = world.factory
    parameters = world.parameters
    warehouses = sorted(factory.warehouses)
    decisions: list[dict[str, Any]] = []
    open_orders = list(state.customer_orders)
    for order in generator.sample(open_orders, k=min(3, len(open_orders))):
        decisions.append(
            {
                "kind": "ship",
                "order": order.id,
                "quantity": random_quantity(generator, order.quantity - order.shipped),
                "warehouse": generator.choice(warehouses),
            }
        )
    for _ in range(generator.randint(0, 2)):
        line_id = generator.choice(sorted(factory.lines))
        item_id = generator.choice(sorted(factory.lines[line_id].items))
        path = f"lines.{line_id}.items.{item_id}.time"
        hours = parameters[f"lines.{line_id}.capacity"] / parameters[path]
        decisions.append(
            {
                "kind": "produce",
                "line": line_id,
                "item": item_id,
                "quantity": random_quantity(generator, hours),
                "overtime": generator.random() < 0.2,
            }
        )
    for _ in range(generator.randint(0, 2)):
        supplier_id = generator.choice(sorted(factory.suppliers))
        material = generator.choice(sorted(factory.suppliers[supplier_id].catalogue))
        path = f"suppliers.{supplier_id}.catalogue.{material}.max_quantity"
        decisions.append(
            {
                "kind": "buy",
                "supplier": supplier_id,
                "material": material,
                "quantity": random_quantity(generator, parameters[path]),
                "express": generator.random() < 0.2,
                "warehouse": generator.choice(warehouses),
            }
        )
    held = [
        (source, item_id, quantity)
        for source, items in state.stock.items()
        for item_id, quantity in items.items()
        if quantity > 0 and factory.routes.get(source)
    ]
    if held and generator.random() < 0.5:
        source, item_id, quantity = generator.choice(held)
        decisions.append(
            {
                "kind": "transfer",
                "item": item_id,
                "quantity": random_quantity(generator, quantity),
                "source": source,
                "destination": generator.choice(sorted(factory.routes[source])),
            }
        )
    if generator.random() < 0.3:
        decisions.append(
            {
                "kind": "repair",
                "line": generator.choice(sorted(factory.lines)),
                "amount": random_quantity(generator, Decimal("0.2"), places=4),
            }
        )
    if state.supplier_orders and generator.random() < 0.2:
        order = generator.choice(state.supplier_orders)
        decisions.append(
            {
                "kind": "cancel",
                "order": order.id,
                "quantity": random_quantity(generator, order.open_quantity),
            }
        )
    generator.shuffle(decisions)
    return decisions[:8]


# Run a world with decisions drawn from a random generator in each period.
def random_run(world: World, generator: Random) -> tuple[World, list[RunStep]]:
    state = build_state(world)
    steps: list[RunStep] = []
    while not state.finished:
        decided = start_period(state, world)
        decisions = random_decisions(generator, world, decided)
        state = decide(decided, world, decisions)
        steps.append((decided, decisions, state))
    return world, steps


# Up to 4 repairs; about one in five names an unknown line.
def repair_lists(world: World) -> st.SearchStrategy[list[dict[str, Any]]]:
    lines = st.sampled_from(sorted(world.factory.lines))
    line_or_unknown = one_in_five(lines, st.just("line-9"))
    repairs = st.fixed_dictionaries(
        {
            "kind": st.just("repair"),
            "line": line_or_unknown,
            "amount": number_text(4, Decimal("0.0001"), 1),
        }
    )
    return st.lists(repairs, max_size=4)
