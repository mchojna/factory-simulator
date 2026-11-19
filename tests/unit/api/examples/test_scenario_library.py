import copy
from decimal import Decimal
from fractions import Fraction
from typing import Any, cast

import pytest
from factories import REVENUE_WEIGHTS, revenue_bound, to_engine

from factory_simulator.api.core.numbers import read_json_bytes
from factory_simulator.api.services.examples import EXAMPLES
from factory_simulator.engine import demand_factor

# The folder of the scenario library of the example manifest.
LIBRARY_FOLDER = EXAMPLES / "scenarios"


KEYS = {
    "steady-market": [],
    "seasonal-demand": ["demand_shapes"],
    "growth": ["demand_shapes"],
    "decline": ["demand_shapes"],
    "demand-surge": ["disruptions"],
    "product-life-cycle": ["demand_shapes", "start.stock"],
    "supplier-outage": ["disruptions"],
    "material-shortage": ["disruptions"],
    "quality-crisis": ["disruptions"],
    "transport-delays": ["disruptions"],
    "line-breakdown": ["disruptions"],
    "frequent-breakdowns": ["random_disruptions", "disruptions"],
    "cash-squeeze": ["start.cash"],
    "full-warehouse": ["start.stock"],
    "regional-crisis": ["disruptions"],
    "surge-and-breakdown": ["disruptions"],
    "forecasts": ["forecasts", "hidden"],
    "notice": ["disruptions"],
    "hidden-groups": ["demand_shapes", "hidden"],
    "capacity-cut": ["disruptions"],
    "yield-drop": ["disruptions"],
    "price-change": ["disruptions"],
    "demand-step": ["demand_shapes"],
}


# The start periods that written disruptions of more than one scenario share.
SHARED_STARTS = {
    10: {"supplier-outage", "material-shortage", "notice"},
    14: {"demand-surge", "surge-and-breakdown"},
    16: {"regional-crisis", "surge-and-breakdown"},
    18: {"capacity-cut", "line-breakdown"},
}


def read(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any], read_json_bytes((LIBRARY_FOLDER / f"{name}.json").read_bytes())
    )


def cut(scenario: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    left = copy.deepcopy(scenario)
    for key in ["name", "description", *keys]:
        if key.startswith("start."):
            left["start"].pop(key.removeprefix("start."), None)
        else:
            left.pop(key, None)
    return left


# The middle of a number or a range: its mode, mean or median, or the middle of its
# bounds.
def middle_value(value: object) -> Decimal:
    if not isinstance(value, dict):
        return Decimal(str(value))
    bounds = cast(dict[str, Any], value)
    for key in ("mode", "mean", "median"):
        if key in bounds:
            return Decimal(str(bounds[key]))
    return (Decimal(str(bounds["min"])) + Decimal(str(bounds["max"]))) / 2


# The lowest middle price of each material over its suppliers.
def lowest_prices(manifest: dict[str, Any]) -> dict[str, Decimal]:
    prices: dict[str, Decimal] = {}
    for supplier in manifest["suppliers"].values():
        for material, entry in supplier["catalogue"].items():
            price = middle_value(entry["price"])
            prices[material] = min(prices.get(material, price), price)
    return prices


# The worth of one unit at the middle prices: the lowest middle price of a material;
# the inputs of the standard recipe of a component plus its cost on its cheaper line.
def unit_values(manifest: dict[str, Any]) -> dict[str, Decimal]:
    values = lowest_prices(manifest)
    costs: dict[str, Decimal] = {}
    for line in manifest["lines"].values():
        for item, terms in line["items"].items():
            cost = Decimal(str(terms["cost"]))
            costs[item] = min(costs.get(item, cost), cost)
    for component, terms in manifest["components"].items():
        recipe = terms["recipes"]["standard"]
        values[component] = costs[component] + sum(
            (
                Decimal(str(quantity)) * values[item_id]
                for item_id, quantity in recipe.items()
            ),
            Decimal(0),
        )
    return values


def test_the_library_holds_its_scenarios_by_file_name():
    assert sorted(path.stem for path in LIBRARY_FOLDER.glob("*.json")) == sorted(KEYS)
    for name in KEYS:
        assert read(name)["name"] == name


def test_every_scenario_has_a_description_and_52_periods_and_the_steady_one_is_plain():
    scenarios = {name: read(name) for name in KEYS}

    assert all(scenario["description"] for scenario in scenarios.values())
    assert {scenario["horizon"] for scenario in scenarios.values()} == {52}
    steady = scenarios["steady-market"]
    for key in (
        "demand_shapes",
        "forecasts",
        "disruptions",
        "random_disruptions",
        "hidden",
    ):
        assert not steady.get(key), key


@pytest.mark.parametrize("name", [name for name in KEYS if name != "steady-market"])
def test_a_scenario_differs_from_the_steady_market_only_in_its_keys(name: str):
    keys = KEYS[name]

    assert cut(read(name), keys) == cut(read("steady-market"), keys)


def test_every_written_disruption_ends_by_period_41_and_starts_apart_but_those_named():
    by_start: dict[int, set[str]] = {}
    for path in sorted(LIBRARY_FOLDER.glob("*.json")):
        name = path.stem
        written = read(name).get("disruptions", [])
        for disruption in written:
            last = disruption["start"] + disruption.get("duration", 1) - 1
            assert last <= 41
            expected_notice = {"notice": 4}.get(name, 0)
            assert disruption["notice"] == expected_notice
        for disruption in written:
            by_start.setdefault(disruption["start"], set()).add(name)

    shared = {start: names for start, names in by_start.items() if len(names) > 1}
    assert shared == SHARED_STARTS


def test_the_full_warehouse_fills_at_least_99_5_percent_without_changing_stock_value():
    manifest = cast(
        dict[str, Any], read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    )
    values = unit_values(manifest)
    spaces = {
        item: Decimal(str(terms["space"]))
        for kind in ("materials", "components")
        for item, terms in manifest[kind].items()
    }
    full = read("full-warehouse")["start"]["stock"]["main-plant"]
    steady = read("steady-market")["start"]["stock"]["main-plant"]

    def worth(stock: dict[str, Any]) -> Decimal:
        return sum(
            (
                Decimal(str(quantity)) * values[item_id]
                for item_id, quantity in stock.items()
            ),
            Decimal(0),
        )

    space = sum(
        (
            Decimal(str(quantity)) * spaces[item_id]
            for item_id, quantity in full.items()
        ),
        Decimal(0),
    )
    capacity = Decimal(str(manifest["warehouses"]["main-plant"]["capacity"]))
    assert abs(worth(full) - worth(steady)) <= 1
    assert space == capacity


def test_notice_is_the_supplier_outage_announced_4_periods_ahead():
    notice = cut(read("notice"), [])
    outage = cut(read("supplier-outage"), [])
    announced = notice.pop("disruptions")
    plain = outage.pop("disruptions")

    assert notice == outage
    assert announced == [disruption | {"notice": 4} for disruption in plain]


def test_the_demand_step_multiplies_every_pair_by_6_from_period_11():
    manifest = cast(
        dict[str, Any], read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    )
    factory, scenario = to_engine(manifest, read("demand-step"))

    for customer, terms in factory.customers.items():
        for product in terms.products:
            factors = [
                demand_factor(customer, product, period, scenario, factory)
                for period in (10, 11, 52)
            ]
            assert factors == [Decimal(1), Decimal(6), Decimal(6)]


def test_hidden_groups_include_a_higher_hidden_demand_level_from_period_1():
    scenario = read("hidden-groups")
    manifest = cast(
        dict[str, Any], read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    )
    factory, engine_scenario = to_engine(manifest, scenario)

    for customer, terms in factory.customers.items():
        for product in terms.products:
            assert demand_factor(customer, product, 1, engine_scenario, factory) == 2.5


def test_the_common_start_has_no_cash_and_a_quarter_period_of_products():
    start = read("steady-market")["start"]

    assert Decimal(str(start["cash"])) == 0
    assert {
        item: Decimal(str(quantity))
        for item, quantity in start["stock"]["distribution-centre"].items()
    } == {
        "industrial-controller": Decimal("22.500"),
        "smart-monitor": Decimal("23.750"),
        "sensor-gateway": Decimal("20.000"),
    }


# A start of -900000 plus every unit of the stock of the cash squeeze sold at its
# revenue weight, with no cost: -900000 + 274845.625 = -625154.375, below -80000.
def test_the_cash_squeeze_stock_leaves_a_start_of_minus_900000_below_the_credit_limit():
    manifest = cast(
        dict[str, Any], read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    )
    for kind in ("components", "products"):
        for item, terms in manifest[kind].items():
            for recipe in terms["recipes"].values():
                inputs = sum(
                    Fraction(str(quantity)) * REVENUE_WEIGHTS[input_id]
                    for input_id, quantity in recipe.items()
                )
                assert REVENUE_WEIGHTS[item] <= inputs, item
    for customer in manifest["customers"].values():
        for product, terms in customer["products"].items():
            assert REVENUE_WEIGHTS[product] >= Fraction(str(terms["price"])), product
    stock = read("cash-squeeze")["start"]["stock"]

    assert revenue_bound(stock) == Fraction(2198765, 8)
    assert -900000 + revenue_bound(stock) == Fraction(-5001235, 8)
    assert -900000 + revenue_bound(stock) < -80000


# The stock sale at the middle of demand, with every yield at the middle of its range
# and no breakdown, from a start of -120000: each period ships every open order from
# stock, customers of the shortest payment terms first, and makes one period of the
# middle demand of each product from the starting components, as the hours allow. Per
# period, to 2 places: the payments of step 2, the transport and production of step
# 5, and the storage, penalties and interest of the close.
STOCK_SALE = [
    (Decimal("0.00"), Decimal("3004.52"), Decimal("761.41")),
    (Decimal("0.00"), Decimal("3729.81"), Decimal("1399.63")),
    (Decimal("4800.00"), Decimal("3715.22"), Decimal("1405.47")),
    (Decimal("6000.00"), Decimal("1331.37"), Decimal("1766.84")),
    (Decimal("10968.75"), Decimal("36.88"), Decimal("2353.68")),
    (Decimal("29066.85"), Decimal("0.00"), Decimal("4905.82")),
    (Decimal("17933.72"), Decimal("0.00"), Decimal("0.00")),
]


# Room for a buy before the close of each period: cash less open orders plus the credit
# limit of 80000. 500 microchips at the middle price of 6.5 cost 3250.
def test_the_squeeze_lets_the_stock_sale_buy_500_microchips_first_in_period_7():
    cash = Decimal(str(read("cash-squeeze")["start"]["cash"]))
    available: list[Decimal] = []
    for payments, decisions, close in STOCK_SALE:
        cash += payments - decisions
        available.append(cash + 80000)
        cash -= close

    assert available == [
        Decimal("-43004.52"),
        Decimal("-47495.74"),
        Decimal("-47810.59"),
        Decimal("-44547.43"),
        Decimal("-35382.40"),
        Decimal("-8669.23"),
        Decimal("4358.67"),
    ]
    assert [room >= 3250 for room in available] == [False] * 6 + [True]


# The margin of one unit of each product at the middle of demand, prices and yields,
# to 2 places: its prices less transport costs, weighted by the middle demand of each
# customer, less its cost. The cost of a made item is the inputs of its recipe and its
# line cost, on the line item of the lowest cost, over the middle yield of that item.
def product_margins(
    prices: dict[str, Decimal], recipes: dict[str, str], manifest: dict[str, Any]
) -> dict[str, Decimal]:
    lines: dict[str, tuple[Decimal, Decimal]] = {}
    for line in manifest["lines"].values():
        for item, terms in line["items"].items():
            cost = Decimal(str(terms["cost"]))
            if item not in lines or cost < lines[item][0]:
                lines[item] = (cost, middle_value(terms["yield"]))
    costs = dict(prices)
    for kind in ("components", "products"):
        for item, terms in manifest[kind].items():
            recipe = terms["recipes"][recipes.get(item, "standard")]
            cost, good = lines[item]
            inputs = sum(
                (
                    Decimal(str(quantity)) * costs[item_id]
                    for item_id, quantity in recipe.items()
                ),
                Decimal(0),
            )
            costs[item] = (inputs + cost) / good
    margins: dict[str, Decimal] = {}
    for product in manifest["products"]:
        pairs = [
            customer["products"][product]
            for customer in manifest["customers"].values()
            if product in customer["products"]
        ]
        demand = sum((middle_value(pair["demand"]) for pair in pairs), Decimal(0))
        revenue = sum(
            (
                middle_value(pair["demand"])
                * (Decimal(str(pair["price"])) - Decimal(str(pair["transport_cost"])))
                for pair in pairs
            ),
            Decimal(0),
        )
        margins[product] = (revenue / demand - costs[product]).quantize(Decimal("0.01"))
    return margins


def margins_of(controller: str, monitor: str, gateway: str) -> dict[str, Decimal]:
    return {
        "industrial-controller": Decimal(controller),
        "smart-monitor": Decimal(monitor),
        "sensor-gateway": Decimal(gateway),
    }


def test_the_microchip_price_change_leaves_a_switch_and_a_buy_ahead_that_pay():
    manifest = cast(
        dict[str, Any], read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    )
    [change] = read("price-change")["disruptions"]
    factor = Decimal(str(change["factor"]))
    usual = lowest_prices(manifest)
    changed = {
        material: price * factor
        if change["target"] == "all" or material in change["target"]
        else price
        for material, price in usual.items()
    }
    storage = Decimal(str(manifest["materials"]["microchip"]["storage_cost"]))
    # A microchip bought before the change and stored through its 32 periods.
    ahead = usual | {"microchip": usual["microchip"] + change["duration"] * storage}
    switched = {"control-board": "alternative"}

    assert (change["start"], change["duration"], factor) == (8, 32, 4)
    assert product_margins(usual, {}, manifest) == margins_of("77.56", "80.95", "56.19")
    assert product_margins(changed, {}, manifest) == margins_of(
        "36.96", "40.34", "35.89"
    )
    assert product_margins(changed, switched, manifest) == margins_of(
        "75.07", "78.45", "35.89"
    )
    assert product_margins(ahead, {}, manifest) == margins_of("75.40", "78.79", "55.11")


def test_the_chips_sold_before_the_price_change_cover_25_88_of_its_32_periods():
    manifest = cast(
        dict[str, Any], read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
    )
    scenario = read("price-change")
    [change] = scenario["disruptions"]
    entry = manifest["suppliers"]["apac-chips"]["catalogue"]["microchip"]
    most = Decimal(str(entry["max_quantity"]))
    stock = Decimal(str(scenario["start"]["stock"]["main-plant"]["microchip"]))
    # Microchips a period at the middle of demand and yields: 2 for each control board
    # of 90 controllers and 95 monitors, 1 for each sensor module of 80 gateways, over
    # the yields 0.975 of the SMT line and 0.985 of the final assembly line.
    need = Decimal(2 * 185 + 80) / (Decimal("0.975") * Decimal("0.985"))
    before = change["start"] - 1
    left = most * before - (need * before - stock)

    assert need.quantize(Decimal("0.001")) == Decimal("468.567")
    assert left.quantize(Decimal("0.001")) == Decimal("12126.031")
    assert (left / need).quantize(Decimal("0.01")) == Decimal("25.88")
    assert left / need < change["duration"]
