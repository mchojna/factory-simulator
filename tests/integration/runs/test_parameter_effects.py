import copy
from collections.abc import Callable
from typing import Any

import pytest
from factories import (
    FORECAST,
    apac_supplier_manifest,
    api_client,
    changeover_manifest,
    get,
    run_to_the_end,
    start_run,
    submit,
    tiny_manifest,
    tiny_scenario,
    two_warehouse_manifest,
)

from factory_simulator.engine import MEASURE_KINDS

LINE_MEASURES = "lines.line-1"
SUPPLIER_MEASURES = "suppliers.chip-maker/chip"
UNITS_STARTED = f"{LINE_MEASURES}.units_started"
CONDITION = f"{LINE_MEASURES}.condition"
ARRIVED = f"{SUPPLIER_MEASURES}.units_arrived"
ARRIVED_LATE = f"{SUPPLIER_MEASURES}.units_arrived_late"
REJECTED_AT_INSPECTION = f"{SUPPLIER_MEASURES}.units_rejected_at_inspection"
REJECTED = "total.decisions_rejected"
ORDERED = "total.units_ordered"
SHIP_FIRST_ORDER = {1: [{"kind": "ship", "order": "order-1-1", "quantity": "4"}]}
LINE = "lines.line-1"
CHIP = "suppliers.chip-maker.catalogue.chip"
BUY_FIRST = {
    1: [
        {"kind": "buy", "supplier": "chip-maker", "material": "chip", "quantity": "100"}
    ]
}
BUY_SECOND = {2: BUY_FIRST[1]}
SEASON = {"factors": ["0.5000", "2.0000"], "period_length": 2}
RAMP = {"first": 1, "last": 4, "from_factor": "1.0000", "to_factor": "2.0000"}
STARTING_ORDER = {
    "supplier": "chip-maker",
    "material": "chip",
    "quantity": "100",
    "arrival": 2,
}
PAIR_PATH = "customers.distributor.products.monitor"
BUY = BUY_FIRST[1][0]
BUY_TWICE = {1: [BUY], 2: [BUY]}
BUY_1200_FIRST = {1: [BUY | {"quantity": "1200"}]}
BOARDS_IN_OVERTIME = {
    1: [
        {
            "kind": "produce",
            "line": "line-1",
            "item": "board",
            "quantity": "30",
            "overtime": True,
        }
    ]
}
EXPRESS_FIRST = {1: [BUY | {"express": True}]}
BUY_THEN_CANCEL = {
    1: [BUY],
    2: [{"kind": "cancel", "order": "buy-1-1", "quantity": "50"}],
}
BIG_BUYS = {1: [BUY | {"quantity": "600"}], 2: [BUY | {"quantity": "600"}]}
BOARDS_TWICE = {
    period: [{"kind": "produce", "line": "line-1", "item": "board", "quantity": "15"}]
    for period in (1, 2)
}
PATIENT_PAIR = tiny_manifest()["customers"]["distributor"]["products"]["monitor"] | {
    "patience": 2
}
STARTING_CUSTOMER_ORDER = {
    "customer": "distributor",
    "product": "monitor",
    "quantity": "3",
    "due": 2,
}
Effect = tuple[str, tuple[object, object], dict[int, list[Any]], str]
DEMAND_RANGE = {"min": "30.000", "max": "50.000"}
TROUBLE_RULE = {
    "name": "trouble",
    "kind": "line_breakdown",
    "target": ["line-1"],
    "chance": "0.0100",
    "loss": "0.4000",
}
OUTAGE_RULE = {
    "name": "outage",
    "kind": "supplier_outage",
    "target": ["chip-maker"],
    "chance": "1.0000",
    "duration": 1,
    "strength": {"min": "0.1000", "max": "0.2000"},
}
CASCADE_OUTAGE = OUTAGE_RULE | {"chance": "0.5000"}
CASCADE = {"rule": "delays", "factor": "5.0000", "periods": 2}
RAISED_DELAYS = {
    "name": "delays",
    "kind": "transport_delay",
    "target": ["chip-maker"],
    "chance": "0.2000",
    "duration": 1,
    "delay": 1,
}
SHOCK_RULE = {
    "name": "shock",
    "kind": "demand_shock",
    "target": ["monitor"],
    "chance": "1.0000",
    "duration": 1,
    "factor": "1.5000",
}
TRIANGULAR = "triangular"
DEMAND = "customers.distributor.products.monitor.demand"
# Rates of cash, each a whole `cash` mapping, in runs that start with cash -500.
NEGATIVE_CASH_EFFECTS: dict[str, tuple[object, object]] = {
    "credit_limit": ({"credit_limit": "0.0000"}, {"credit_limit": "300.0000"}),
    "debit_interest": ({"debit_interest": "0.0010"}, {"debit_interest": "0.0020"}),
    "overdraft_interest": (
        {"overdraft_interest": "0.0100"},
        {"overdraft_interest": "0.0200"},
    ),
}
RISING_RATES = {
    "credit_limit": "300.0000",
    "credit_interest": "0.0005",
    "debit_interest": "0.0010",
    "overdraft_interest": "0.0100",
}
BOARD = {"kind": "produce", "line": "line-1", "item": "board"}
BOARDS_THEN_MONITORS = {
    1: [
        BOARD | {"quantity": "46"},
        {"kind": "produce", "line": "line-1", "item": "monitor", "quantity": "5"},
    ]
}
ONE_BOARD = {1: [BOARD | {"quantity": "1"}]}
BOARD_CHANGEOVER = "lines.line-1.items.board"
EVERY_ITEM_KIND = ["materials", "components", "products"]
TRANSFER_TO_CENTRE = {
    1: [
        {
            "kind": "transfer",
            "item": "monitor",
            "quantity": "2",
            "source": "main",
            "destination": "centre",
        }
    ]
}
APAC_CATALOGUE = "groups.apac.defaults.catalogue"
SHIP_FROM_MAIN = {1: [SHIP_FIRST_ORDER[1][0] | {"warehouse": "main"}]}
BUY_INTO_CENTRE = {1: [BUY_FIRST[1][0] | {"warehouse": "centre"}]}
TEN_BOARDS = {1: [BOARD | {"quantity": "10"}]}
# Each forecast key with two values, read from `observation.forecasts`: the number
# of forecasts per pair, or the forecasts for k = 1 and for k of 2 and above.
FORECAST_EFFECTS: list[tuple[str, tuple[object, object], str]] = [
    ("periods_ahead", (2, 4), "count"),
    ("noise", ("0.0000", "0.2000"), "next"),
    ("noise_growth", ("0.0000", "0.1000"), "further"),
]


def produce_first(item: str, quantity: str) -> dict[int, list[Any]]:
    decision = {"kind": "produce", "line": "line-1", "item": item, "quantity": quantity}
    return {1: [decision]}


def repair_first(*extra: dict[str, Any]) -> dict[int, list[Any]]:
    repair = {"kind": "repair", "line": "line-1", "amount": "0.0100"}
    return {2: [repair, *extra]}


def breaking_line(loss: str) -> dict[str, Any]:
    line = tiny_manifest()["lines"]["line-1"]
    return line | {"breakdown_chance": "1.0000", "breakdown_loss": loss}


def written(kind: str, target: str, start: int = 3, **effect: object) -> list[Any]:
    disruption: dict[str, Any] = {"kind": kind, "target": [target], "start": start}
    if kind != "line_breakdown":
        disruption["duration"] = effect.pop("duration", 1)
    return [disruption | effect]


def shaped(kind: str, **keys: object) -> list[Any]:
    return [{"kind": kind, "target": "all"} | keys]


def late_chip_entry(delay: int) -> dict[str, Any]:
    entry = tiny_manifest()["suppliers"]["chip-maker"]["catalogue"]["chip"]
    return entry | {"punctuality": "0.0000", "delay": delay}


def chip_entry_with(**terms: object) -> dict[str, Any]:
    return tiny_manifest()["suppliers"]["chip-maker"]["catalogue"]["chip"] | terms


def tiered_entry(start: str = "1000.000", price: str = "0.4600") -> dict[str, Any]:
    return chip_entry_with(
        max_quantity="2000.000", discounts=[{"from": start, "price": price}]
    )


def two_recipe_board(alternative: str, default_recipe: str) -> dict[str, Any]:
    board = tiny_manifest()["components"]["board"]
    recipes = {"standard": {"chip": "2.000"}, "alternative": {"chip": alternative}}
    return board | {"recipes": recipes, "default_recipe": default_recipe}


def overtime_line(hours: str, cost: str = "45.0000") -> dict[str, Any]:
    line = tiny_manifest()["lines"]["line-1"]
    return line | {"overtime_hours": hours, "overtime_cost": cost}


def express_entry(lead_time: int, cost: str = "1.5000") -> dict[str, Any]:
    return chip_entry_with(lead_time=3, express_lead_time=lead_time, express_cost=cost)


def three_ways(
    kind: str,
    target: str,
    decisions: dict[int, list[Any]],
    measure: str,
    first: int = 1,
    **effect: tuple[object, object],
) -> list[Effect]:
    key, (low, high) = next(iter(effect.items()))
    rows: list[Effect] = [
        (
            "scenario.disruptions",
            (
                written(kind, target, start=first, **{key: low}),
                written(kind, target, start=1, **{key: high}),
            ),
            decisions,
            measure,
        ),
        (
            "scenario.disruptions",
            (
                written(kind, target, start=first, **{key: high}),
                written(kind, target, start=first + 1, **{key: high}),
            ),
            decisions,
            measure,
        ),
    ]
    if kind != "line_breakdown":
        rows.append(
            (
                "scenario.disruptions",
                (
                    written(kind, target, start=first, duration=1, **{key: high}),
                    written(kind, target, start=first, duration=2, **{key: high}),
                ),
                decisions,
                measure,
            )
        )
    return rows


def chip_price(**shape: str) -> dict[str, str]:
    return {"min": "0.4000", "max": "0.6000"} | shape


def demand_of(mean: str, sd: str) -> dict[str, str]:
    return {
        "min": "30.000",
        "max": "50.000",
        "distribution": "normal",
        "mean": mean,
        "sd": sd,
    }


def lognormal_demand_of(median: str, spread: str) -> dict[str, str]:
    return {
        "min": "20.000",
        "max": "120.000",
        "distribution": "lognormal",
        "median": median,
        "spread": spread,
    }


def s_curve(**keys: object) -> list[Any]:
    shape = {
        "kind": "s_curve",
        "target": "all",
        "middle": 3,
        "steepness": "0.5000",
        "from_factor": "0.0000",
        "to_factor": "1.0000",
    }
    return [shape | keys]


def centre_of_every_kind() -> dict[str, Any]:
    return two_warehouse_manifest(accepts=EVERY_ITEM_KIND)


def routed_manifest() -> dict[str, Any]:
    manifest = centre_of_every_kind()
    manifest["routes"] = {"main": {"centre": {"cost": "0.2000", "lead_time": 1}}}
    return manifest


def segments() -> dict[str, Any]:
    manifest = tiny_manifest()
    manifest["products"]["tablet"] = copy.deepcopy(manifest["products"]["monitor"])
    line_items = manifest["lines"]["line-1"]["items"]
    line_items["tablet"] = dict(line_items["monitor"])
    pairs = manifest["customers"]["distributor"]["products"]
    pairs["tablet"] = dict(pairs["monitor"])
    manifest["products"]["monitor"]["groups"] = ["new-devices"]
    manifest["products"]["tablet"]["groups"] = ["spare-parts"]
    manifest["groups"] = {
        "new-devices": {"kind": "segment"},
        "spare-parts": {"kind": "segment"},
    }
    return manifest


def shock_of(segment: str) -> list[Any]:
    return [
        {
            "kind": "demand_shock",
            "target": {"segment": segment},
            "start": 1,
            "duration": 2,
            "factor": "2.0000",
        }
    ]


# The tiny factory with a second customer of the monitor, both with a range of demand.
def two_customers() -> dict[str, Any]:
    manifest = tiny_manifest()
    distributor = manifest["customers"]["distributor"]
    distributor["products"]["monitor"]["demand"] = DEMAND_RANGE
    manifest["customers"]["retailer"] = copy.deepcopy(distributor)
    return manifest


# Parameter path, two values, decisions per period, and the named measure that changes,
# `<key>.<name>` such as `lines.line-1.condition`, compared as its values per period. A
# path that starts with `scenario.` changes the scenario, any other the manifest.
EFFECTS: list[Effect] = [
    (
        f"{CHIP}.price",
        (
            chip_price(distribution=TRIANGULAR, mode="0.4500"),
            chip_price(distribution=TRIANGULAR, mode="0.5500"),
        ),
        BUY_FIRST,
        "total.material_payment",
    ),
    (
        f"{CHIP}.price",
        (chip_price(), chip_price(distribution=TRIANGULAR, mode="0.4500")),
        BUY_FIRST,
        "total.material_payment",
    ),
    (
        f"{CHIP}.price",
        (chip_price(drawn="run"), chip_price(drawn="period")),
        BUY_SECOND,
        "total.material_payment",
    ),
    (
        PAIR_PATH,
        (
            tiny_manifest()["customers"]["distributor"]["products"]["monitor"]
            | {"demand": DEMAND_RANGE},
            tiny_manifest()["customers"]["distributor"]["products"]["monitor"]
            | {"demand": DEMAND_RANGE, "demand_persistence": "0.8000"},
        ),
        {},
        ORDERED,
    ),
    ("scenario.demand_shapes", (s_curve(), s_curve(middle=1)), {}, ORDERED),
    ("scenario.demand_shapes", (s_curve(), s_curve(steepness="1.0000")), {}, ORDERED),
    ("scenario.demand_shapes", (s_curve(), s_curve(from_factor="0.5000")), {}, ORDERED),
    ("scenario.demand_shapes", (s_curve(), s_curve(to_factor="1.5000")), {}, ORDERED),
    (DEMAND, (demand_of("40.000", "5.000"), demand_of("45.000", "5.000")), {}, ORDERED),
    (DEMAND, (demand_of("40.000", "5.000"), demand_of("40.000", "1.000")), {}, ORDERED),
    (
        DEMAND,
        (
            lognormal_demand_of("40.000", "0.5000"),
            lognormal_demand_of("45.000", "0.5000"),
        ),
        {},
        ORDERED,
    ),
    (
        DEMAND,
        (
            lognormal_demand_of("40.000", "0.5000"),
            lognormal_demand_of("40.000", "0.2000"),
        ),
        {},
        ORDERED,
    ),
    (
        DEMAND,
        ({"min": "20.000", "max": "120.000"}, lognormal_demand_of("40.000", "0.5000")),
        {},
        ORDERED,
    ),
    (
        "scenario.random_disruptions",
        ([TROUBLE_RULE], [TROUBLE_RULE | {"chance": "0.2000"}]),
        {},
        CONDITION,
    ),
    (
        "scenario.random_disruptions",
        (
            [OUTAGE_RULE],
            [OUTAGE_RULE | {"strength": {"min": "0.8000", "max": "0.9000"}}],
        ),
        BUY_FIRST,
        ARRIVED,
    ),
    (
        "scenario.random_disruptions",
        (
            [OUTAGE_RULE | {"chance": "0.5000"}],
            [OUTAGE_RULE | {"chance": "0.5000", "duration": {"min": 3, "max": 5}}],
        ),
        {2: BUY_FIRST[1]},
        ARRIVED,
    ),
    (
        f"{PAIR_PATH}.price",
        ("50.0000", "60.0000"),
        SHIP_FIRST_ORDER,
        "total.revenue",
    ),
    (
        f"{PAIR_PATH}.transport_cost",
        ("1.0000", "2.0000"),
        SHIP_FIRST_ORDER,
        "total.transport_cost",
    ),
    (
        f"{LINE}.capacity",
        ("10.000", "4.000"),
        produce_first("board", "50"),
        UNITS_STARTED,
    ),
    (
        f"{LINE}.items.monitor.time",
        ("0.500", "2.500"),
        produce_first("monitor", "5"),
        UNITS_STARTED,
    ),
    (
        f"{LINE}.wear_per_period",
        ("0.0100", "0.0200"),
        {},
        CONDITION,
    ),
    (
        f"{LINE}.wear_per_hour",
        ("0.0020", "0.0040"),
        produce_first("board", "20"),
        CONDITION,
    ),
    (
        f"{LINE}.items.board.cost",
        ("1.0000", "2.0000"),
        produce_first("board", "20"),
        "total.production_cost",
    ),
    (
        f"{LINE}.items.board.yield",
        ("0.9000", "0.8000"),
        produce_first("board", "20"),
        f"{LINE_MEASURES}/board.units_scrap",
    ),
    (
        "products.monitor.space",
        ("0.150", "18.000"),
        {},
        "warehouses.main.space_used",
    ),
    (
        "components.board.recipes.standard.chip",
        ("2.000", "3.000"),
        produce_first("board", "20"),
        "warehouses.main/chip.stock",
    ),
    (f"{CHIP}.price", ("0.5000", "0.6000"), BUY_FIRST, "total.material_payment"),
    (f"{CHIP}.lead_time", (2, 3), BUY_FIRST, ARRIVED),
    (
        f"{CHIP}.punctuality",
        ("1.0000", "0.0000"),
        BUY_FIRST,
        ARRIVED_LATE,
    ),
    (
        CHIP,
        (late_chip_entry(delay=1), late_chip_entry(delay=2)),
        BUY_FIRST,
        ARRIVED,
    ),
    (
        f"{CHIP}.completeness",
        ("1.0000", "0.5000"),
        BUY_FIRST,
        ARRIVED,
    ),
    (
        f"{CHIP}.acceptance",
        ("1.0000", "0.5000"),
        BUY_FIRST,
        f"{SUPPLIER_MEASURES}.units_accepted",
    ),
    (
        f"{CHIP}.max_quantity",
        ("1000.000", "50.000"),
        BUY_FIRST,
        REJECTED,
    ),
    (
        CHIP,
        (
            chip_entry_with(completeness="0.9000", backfill_delay=0),
            chip_entry_with(completeness="0.9000", backfill_delay=2),
        ),
        BUY_FIRST,
        f"{SUPPLIER_MEASURES}.units_lost_in_delivery",
    ),
    (CHIP, (express_entry(1), express_entry(2)), EXPRESS_FIRST, ARRIVED),
    (
        CHIP,
        (
            chip_entry_with(min_quantity="0.000"),
            chip_entry_with(min_quantity="500.000"),
        ),
        BUY_FIRST,
        REJECTED,
    ),
    (
        CHIP,
        (tiered_entry(price="0.4600"), tiered_entry(price="0.4400")),
        BUY_1200_FIRST,
        "total.material_payment",
    ),
    (
        CHIP,
        (tiered_entry(start="1000.000"), tiered_entry(start="1500.000")),
        BUY_1200_FIRST,
        "total.material_payment",
    ),
    (
        CHIP,
        (express_entry(1, "1.5000"), express_entry(1, "2.0000")),
        EXPRESS_FIRST,
        "total.material_payment",
    ),
    (
        "components.board",
        (two_recipe_board("2.000", "standard"), two_recipe_board("3.000", "standard")),
        {1: [{**produce_first("board", "10")[1][0], "recipe": "alternative"}]},
        "warehouses.main/chip.stock",
    ),
    (
        "components.board",
        (
            two_recipe_board("3.000", "standard"),
            two_recipe_board("3.000", "alternative"),
        ),
        produce_first("board", "10"),
        "warehouses.main/chip.stock",
    ),
    (
        f"{LINE}.items.board.lead_time",
        (1, 2),
        produce_first("board", "10"),
        "warehouses.main/board.stock",
    ),
    (
        LINE,
        (overtime_line("2.000"), overtime_line("4.000")),
        BOARDS_IN_OVERTIME,
        UNITS_STARTED,
    ),
    (
        LINE,
        (overtime_line("4.000", "45.0000"), overtime_line("4.000", "50.0000")),
        BOARDS_IN_OVERTIME,
        "total.overtime_cost",
    ),
    (
        f"{CHIP}.cancellation_fee",
        ("0.0000", "0.1000"),
        BUY_THEN_CANCEL,
        "total.cancellation_fee",
    ),
    (
        "warehouses.main.capacity",
        ("100.000", "2.500"),
        BUY_FIRST,
        REJECTED,
    ),
    (
        f"{LINE}.breakdown_chance",
        ("0.0000", "1.0000"),
        {},
        "lines.line-1.breakdowns",
    ),
    (
        LINE,
        (breaking_line("0.1000"), breaking_line("0.2000")),
        {},
        CONDITION,
    ),
    (
        f"{LINE}.repair_limit",
        ("1.0000", "0.0050"),
        repair_first(),
        CONDITION,
    ),
    (
        f"{LINE}.repair_cost",
        ("10.0000", "20.0000"),
        repair_first(),
        "total.repair_cost",
    ),
    (
        f"{LINE}.repair_time",
        ("100.000", "600.000"),
        repair_first(
            {"kind": "produce", "line": "line-1", "item": "board", "quantity": "45"}
        ),
        UNITS_STARTED,
    ),
    (
        "scenario.disruptions",
        (
            written("supplier_outage", "chip-maker", strength="0.5000"),
            written("supplier_outage", "chip-maker", strength="0.8000"),
        ),
        BUY_FIRST,
        ARRIVED,
    ),
    (
        "scenario.disruptions",
        (
            written("supplier_outage", "chip-maker", start=3, strength="0.5000"),
            written("supplier_outage", "chip-maker", start=4, strength="0.5000"),
        ),
        BUY_FIRST,
        ARRIVED,
    ),
    (
        "scenario.disruptions",
        (
            written("supplier_outage", "chip-maker", start=2, strength="0.5000"),
            written(
                "supplier_outage", "chip-maker", start=2, strength="0.5000", duration=2
            ),
        ),
        BUY_FIRST,
        ARRIVED,
    ),
    (
        "scenario.disruptions",
        (
            written("material_shortage", "chip", start=1, strength="0.3000"),
            written("material_shortage", "chip", start=1, strength="0.5000"),
        ),
        {1: [BUY_FIRST[1][0] | {"quantity": "600"}]},
        REJECTED,
    ),
    (
        "scenario.disruptions",
        (
            written("quality_drop", "chip-maker", strength="0.5000"),
            written("quality_drop", "chip-maker", strength="0.8000"),
        ),
        BUY_FIRST,
        REJECTED_AT_INSPECTION,
    ),
    (
        "scenario.disruptions",
        (
            written("transport_delay", "chip-maker", delay=1),
            written("transport_delay", "chip-maker", delay=2),
        ),
        BUY_FIRST,
        ARRIVED_LATE,
    ),
    (
        "scenario.disruptions",
        (
            written("demand_shock", "monitor", factor="2.0000"),
            written("demand_shock", "monitor", factor="3.0000"),
        ),
        {},
        ORDERED,
    ),
    (
        "scenario.disruptions",
        (
            written("line_breakdown", "line-1", loss="0.3000"),
            written("line_breakdown", "line-1", loss="0.6000"),
        ),
        {},
        CONDITION,
    ),
    (
        "scenario.disruptions",
        (
            written("price_change", "chip", start=1, factor="1.2000"),
            written("price_change", "chip", start=1, factor="1.5000"),
        ),
        BUY_FIRST,
        "total.material_payment",
    ),
    (
        "scenario.disruptions",
        (
            written("capacity_cut", "line-1", start=1, strength="0.3000"),
            written("capacity_cut", "line-1", start=1, strength="0.6000"),
        ),
        produce_first("board", "50"),
        UNITS_STARTED,
    ),
    (
        "scenario.demand_shapes",
        (shaped("trend", rate="0.1000"), shaped("trend", rate="0.2000")),
        {},
        ORDERED,
    ),
    (
        "scenario.demand_shapes",
        (
            shaped("season", **SEASON),
            shaped("season", **SEASON | {"factors": ["0.5000", "3.0000"]}),
        ),
        {},
        ORDERED,
    ),
    (
        "scenario.demand_shapes",
        (
            shaped("season", **SEASON),
            shaped("season", **SEASON | {"period_length": 1}),
        ),
        {},
        ORDERED,
    ),
    (
        "scenario.demand_shapes",
        (
            shaped("step", period=2, factor="2.0000"),
            shaped("step", period=3, factor="2.0000"),
        ),
        {},
        ORDERED,
    ),
    (
        "scenario.demand_shapes",
        (
            shaped("step", period=2, factor="2.0000"),
            shaped("step", period=2, factor="3.0000"),
        ),
        {},
        ORDERED,
    ),
    (
        "scenario.demand_shapes",
        (shaped("ramp", **RAMP), shaped("ramp", **RAMP | {"first": 2})),
        {},
        ORDERED,
    ),
    (
        "scenario.demand_shapes",
        (shaped("ramp", **RAMP), shaped("ramp", **RAMP | {"last": 5})),
        {},
        ORDERED,
    ),
    (
        "scenario.demand_shapes",
        (shaped("ramp", **RAMP), shaped("ramp", **RAMP | {"from_factor": "0.5000"})),
        {},
        ORDERED,
    ),
    (
        "scenario.demand_shapes",
        (shaped("ramp", **RAMP), shaped("ramp", **RAMP | {"to_factor": "3.0000"})),
        {},
        ORDERED,
    ),
    (
        "scenario.start.supplier_orders",
        ([], [STARTING_ORDER]),
        {},
        ARRIVED,
    ),
    ("materials.chip.storage_cost", ("0.0020", "0.0030"), {}, "total.storage_cost"),
    (
        "materials.chip.salvage_value",
        ("0.1000", "0.0500"),
        {},
        "warehouses.main/chip.stock_salvage_value",
    ),
    (f"{PAIR_PATH}.demand", ("4.000", "6.000"), {}, ORDERED),
    (
        f"{PAIR_PATH}.lead_time",
        (0, 1),
        {2: [{"kind": "ship", "order": "order-1-1", "quantity": "4"}]},
        "total.units_shipped_late",
    ),
    (f"{PAIR_PATH}.patience", (1, 2), {}, "total.units_lost"),
    (
        PAIR_PATH,
        (
            PATIENT_PAIR | {"late_penalty": "2.0000"},
            PATIENT_PAIR | {"late_penalty": "3.0000"},
        ),
        {},
        "total.late_penalty",
    ),
    (
        f"{PAIR_PATH}.lost_sale_penalty",
        ("10.0000", "20.0000"),
        {},
        "total.lost_sale_penalty",
    ),
    ("cash.credit_interest", ("0.0005", "0.0000"), {}, "total.interest_earned"),
    (
        "customers.distributor.payment_terms",
        (0, 2),
        SHIP_FIRST_ORDER,
        "total.receivables",
    ),
    ("scenario.horizon", (5, 6), {}, "total.units_lost"),
    ("scenario.start.cash", ("1000", "2000"), {}, "total.cash"),
    (
        "scenario.start.stock",
        ({"main": {"chip": "100"}}, {"main": {"chip": "200"}}),
        {},
        "warehouses.main/chip.stock",
    ),
    ("scenario.start.condition", ({}, {"line-1": "0.5000"}), {}, CONDITION),
    (
        "scenario.start.customer_orders",
        ([], [STARTING_CUSTOMER_ORDER]),
        {},
        ORDERED,
    ),
    *three_ways(
        "supplier_outage",
        "chip-maker",
        BUY_TWICE,
        ARRIVED,
        first=3,
        strength=("0.5000", "0.8000"),
    ),
    *three_ways(
        "material_shortage", "chip", BIG_BUYS, REJECTED, strength=("0.3000", "0.5000")
    ),
    *three_ways(
        "quality_drop",
        "chip-maker",
        BUY_TWICE,
        REJECTED_AT_INSPECTION,
        first=3,
        strength=("0.5000", "0.8000"),
    ),
    *three_ways(
        "transport_delay", "chip-maker", BUY_TWICE, ARRIVED_LATE, first=3, delay=(2, 1)
    ),
    *three_ways("demand_shock", "monitor", {}, ORDERED, factor=("2.0000", "3.0000")),
    *three_ways("line_breakdown", "line-1", {}, CONDITION, loss=("0.3000", "0.6000")),
    *three_ways(
        "price_change",
        "chip",
        BUY_TWICE,
        "total.material_payment",
        factor=("1.2000", "1.5000"),
    ),
    *three_ways(
        "capacity_cut",
        "line-1",
        BOARDS_TWICE,
        UNITS_STARTED,
        strength=("0.3000", "0.9000"),
    ),
    *three_ways(
        "yield_drop",
        "line-1",
        BOARDS_TWICE,
        f"{LINE_MEASURES}.units_scrap",
        strength=("0.3000", "0.9000"),
    ),
    # Random disruptions, the starting state of a scenario and the lower bound of a
    # range, each row with its values per period at seed 5.
    (
        # Condition 0.594, 0.352836, ... against 0.198, 0.039204, ...: in period 1
        # 1 * 0.6 * 0.99 against 1 * 0.2 * 0.99.
        "scenario.random_disruptions",
        (
            [TROUBLE_RULE | {"chance": "1.0000"}],
            [TROUBLE_RULE | {"chance": "1.0000", "loss": "0.8000"}],
        ),
        {},
        CONDITION,
    ),
    (
        # Late arrivals 0, 0, 0, 100, 100 against 0, 0, 0, 0, 100.
        "scenario.random_disruptions",
        (
            [RAISED_DELAYS | {"chance": "1.0000"}],
            [RAISED_DELAYS | {"chance": "1.0000", "delay": 2}],
        ),
        BUY_TWICE,
        ARRIVED_LATE,
    ),
    (
        # 6 units ordered each period (4 * 1.5) against 12 (4 * 3).
        "scenario.random_disruptions",
        ([SHOCK_RULE], [SHOCK_RULE | {"factor": "3.0000"}]),
        {},
        ORDERED,
    ),
    (
        # Units lost 0, 4, 7, 4, 8 against 0, 4, 4, 7, 8.
        "scenario.start.customer_orders",
        ([STARTING_CUSTOMER_ORDER], [STARTING_CUSTOMER_ORDER | {"due": 3}]),
        {},
        "total.units_lost",
    ),
    (
        # Units lost 0, 4, 7, 4, 8 against 0, 4, 10, 4, 8.
        "scenario.start.customer_orders",
        ([STARTING_CUSTOMER_ORDER], [STARTING_CUSTOMER_ORDER | {"quantity": "6"}]),
        {},
        "total.units_lost",
    ),
    (
        # Units arrived 0, 100, 0, 0, 0 against 0, 0, 100, 0, 0.
        "scenario.start.supplier_orders",
        ([STARTING_ORDER], [STARTING_ORDER | {"arrival": 3}]),
        {},
        ARRIVED,
    ),
    (
        # Units arrived 0, 100, 0, 0, 0 against 0, 200, 0, 0, 0.
        "scenario.start.supplier_orders",
        ([STARTING_ORDER], [STARTING_ORDER | {"quantity": "200"}]),
        {},
        ARRIVED,
    ),
    (
        # Material payment 48.02 against 51.02 in period 3.
        f"{CHIP}.price",
        (chip_price(), chip_price(min="0.4500")),
        BUY_FIRST,
        "total.material_payment",
    ),
]
SHOCK_MOVED = (shock_of("new-devices"), shock_of("spare-parts"))
# The same table over other manifests, each named first: changeovers, warehouses and
# two customers.
MANIFEST_EFFECTS: list[tuple[Callable[[], dict[str, Any]], *Effect]] = [
    (
        two_customers,
        "products.monitor.common_share",
        ("0.0000", "0.8000"),
        {},
        ORDERED,
    ),
    (
        changeover_manifest,
        f"{BOARD_CHANGEOVER}.changeover_time",
        ("1.000", "2.000"),
        BOARDS_THEN_MONITORS,
        UNITS_STARTED,
    ),
    (
        changeover_manifest,
        f"{BOARD_CHANGEOVER}.changeover_cost",
        ("50.0000", "60.0000"),
        ONE_BOARD,
        "total.changeover_cost",
    ),
    (
        changeover_manifest,
        "scenario.start.set_for",
        ({}, {"line-1": "board"}),
        ONE_BOARD,
        f"{LINE_MEASURES}.changeovers",
    ),
    (
        two_warehouse_manifest,
        "warehouses.main.storage_factor",
        ("1.0000", "0.6000"),
        {},
        "total.storage_cost",
    ),
    (
        two_warehouse_manifest,
        "warehouses.main.transport_factor",
        ("1.0000", "0.8000"),
        SHIP_FROM_MAIN,
        "total.transport_cost",
    ),
    (
        two_warehouse_manifest,
        "warehouses.centre.accepts",
        (["materials", "products"], ["products"]),
        BUY_INTO_CENTRE,
        REJECTED,
    ),
    (
        centre_of_every_kind,
        "lines.line-1.warehouse",
        ("main", "centre"),
        TEN_BOARDS,
        "warehouses.main.stock",
    ),
    (
        routed_manifest,
        "routes.main.centre.cost",
        ("0.2000", "0.3000"),
        TRANSFER_TO_CENTRE,
        "total.transfer_cost",
    ),
    (
        routed_manifest,
        "routes.main.centre.lead_time",
        (1, 2),
        TRANSFER_TO_CENTRE,
        "warehouses.centre.stock",
    ),
    (
        apac_supplier_manifest,
        f"{APAC_CATALOGUE}.price",
        ("0.5000", "0.5500"),
        BUY_FIRST,
        "total.material_payment",
    ),
    (
        apac_supplier_manifest,
        f"{APAC_CATALOGUE}.punctuality",
        ({"min": "0.1000", "max": "0.1100"}, {"min": "0.1000", "max": "1.0000"}),
        BUY_FIRST,
        ARRIVED_LATE,
    ),
    (
        segments,
        "scenario.disruptions",
        SHOCK_MOVED,
        {},
        "groups.new-devices.units_ordered",
    ),
    (
        segments,
        "scenario.disruptions",
        SHOCK_MOVED,
        {},
        "groups.spare-parts.units_ordered",
    ),
    (
        centre_of_every_kind,
        "warehouses.centre.capacity",
        ("50.000", "0.100"),
        BUY_INTO_CENTRE,
        REJECTED,
    ),
]
# Each information key with two values, read from one field of every observation.
OBSERVATION_EFFECTS: list[tuple[str, tuple[object, object], str]] = [
    (
        "disruptions",
        (
            written("capacity_cut", "line-1", 4, strength="0.5000", notice=0),
            written("capacity_cut", "line-1", 4, strength="0.5000", notice=2),
        ),
        "disruptions",
    ),
]


def set_path(document: dict[str, Any], path: str, value: object) -> None:
    *parents, key = path.split(".")
    for parent in parents:
        document = document[parent]
    document[key] = value


def measure_of_run(
    path: str,
    value: object,
    decisions: dict[int, list[Any]],
    measure: str,
    scenario: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> list[object]:
    manifest = manifest or tiny_manifest()
    scenario = scenario or tiny_scenario()
    if path.startswith("scenario."):
        set_path(scenario, path.removeprefix("scenario."), value)
    else:
        set_path(manifest, path, value)
    *keys, name = measure.split(".")
    with api_client() as client:
        run = start_run(client, manifest, scenario, seed=5)
        run_to_the_end(client, run, decisions)
        _, periods = get(client, f"/runs/{run['id']}/periods")
    values: list[object] = []
    for period in periods["periods"]:
        measures = period["steps"][-1]["measures"]
        for key in keys:
            measures = measures[key]
        values.append(measures[name])
    return values


def forecasts_of_run(key: str, value: object) -> list[list[dict[str, Any]]]:
    scenario = tiny_scenario()
    scenario["horizon"] = 8
    scenario["forecasts"] = [FORECAST | {"periods_ahead": 3, key: value}]
    seen: list[list[dict[str, Any]]] = []
    with api_client() as client:
        run = start_run(client, scenario=scenario, seed=5)
        _, observation = get(client, f"/runs/{run['id']}/observation")
        for period in range(1, 9):
            seen.append(observation["forecasts"]["distributor/monitor"])
            _, observation = submit(client, run["id"], period, [])
    return seen


def observations_of_run(path: str, value: object, field: str) -> list[object]:
    scenario = tiny_scenario()
    scenario[path] = value
    seen: list[object] = []
    with api_client() as client:
        run = start_run(client, scenario=scenario, seed=5)
        _, observation = get(client, f"/runs/{run['id']}/observation")
        for period in range(1, scenario["horizon"] + 1):
            seen.append(observation[field])
            _, observation = submit(client, run["id"], period, [])
    return seen


def totals_and_last_period(horizon: int) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = tiny_scenario()
    scenario["horizon"] = horizon
    with api_client() as client:
        run = start_run(client, tiny_manifest(), scenario, seed=5)
        run_to_the_end(client, run, SHIP_FIRST_ORDER)
        _, result = get(client, f"/runs/{run['id']}/result")
        _, periods = get(client, f"/runs/{run['id']}/periods")
    last = periods["periods"][-1]["steps"][-1]["measures"]["total"]
    return result["measures"]["total"], last


@pytest.mark.parametrize(("path", "values", "decisions", "measure"), EFFECTS)
def test_changing_a_parameter_changes_its_measure(
    path: str,
    values: tuple[object, object],
    decisions: dict[int, list[Any]],
    measure: str,
):
    first = measure_of_run(path, values[0], decisions, measure)
    second = measure_of_run(path, values[1], decisions, measure)

    periods = min(len(first), len(second))
    assert first[:periods] != second[:periods]


@pytest.mark.parametrize(
    ("manifest", "path", "values", "decisions", "measure"), MANIFEST_EFFECTS
)
def test_changing_a_parameter_of_another_manifest_changes_its_measure(
    manifest: Callable[[], dict[str, Any]],
    path: str,
    values: tuple[object, object],
    decisions: dict[int, list[Any]],
    measure: str,
):
    first, second = (
        measure_of_run(path, value, decisions, measure, None, manifest())
        for value in values
    )

    assert first != second


@pytest.mark.parametrize(
    "values", list(NEGATIVE_CASH_EFFECTS.values()), ids=list(NEGATIVE_CASH_EFFECTS)
)
def test_changing_a_rate_of_cash_changes_interest_paid(
    values: tuple[dict[str, str], dict[str, str]],
):
    scenario = tiny_scenario()
    scenario["start"]["cash"] = "-500"
    first, second = (
        measure_of_run(
            "cash", RISING_RATES | changed, {}, "total.interest_paid", scenario
        )
        for changed in values
    )

    assert first != second


# From cash -500 a buy of 100 chips at 0.5000 gives -550: above -80000, below 0.
def test_changing_the_credit_limit_changes_decisions_rejected():
    scenario = tiny_scenario()
    scenario["start"]["cash"] = "-500"
    first, second = (
        measure_of_run("cash.credit_limit", limit, BUY_FIRST, REJECTED, scenario)
        for limit in ("80000.0000", "0.0000")
    )

    assert first != second


def test_changing_the_written_start_of_a_random_outage_changes_units_arrived():
    scenario = tiny_scenario() | {"horizon": 10}
    rule = {key: value for key, value in OUTAGE_RULE.items() if key != "chance"}
    buys = {period: BUY_FIRST[1] for period in range(1, 11)}
    first, second = (
        measure_of_run(
            "scenario.random_disruptions",
            [rule | {"start": start}],
            buys,
            ARRIVED,
            copy.deepcopy(scenario),
        )
        for start in (5, 9)
    )

    assert first != second


@pytest.mark.parametrize(
    ("key", "values"), [("factor", ("1.5000", "3.0000")), ("periods", (1, 4))]
)
def test_changing_a_cascade_changes_the_late_arrivals_of_the_raised_rule(
    key: str, values: tuple[object, object]
):
    scenario = tiny_scenario() | {"horizon": 10}
    buys = {period: BUY_FIRST[1] for period in range(1, 11)}
    first, second = (
        measure_of_run(
            "scenario.random_disruptions",
            [
                CASCADE_OUTAGE | {"raises": CASCADE | {key: value}},
                RAISED_DELAYS,
            ],
            buys,
            ARRIVED_LATE,
            copy.deepcopy(scenario),
        )
        for value in values
    )

    assert first != second


@pytest.mark.parametrize(("key", "values", "read"), FORECAST_EFFECTS)
def test_changing_a_forecast_key_changes_the_forecasts(
    key: str, values: tuple[object, object], read: str
):
    first, second = (forecasts_of_run(key, value) for value in values)

    if read == "count":
        assert sum(map(len, first)) < sum(map(len, second))
    else:
        nearest = [[made[:1] for made in run] for run in (first, second)]
        further = [[made[1:] for made in run] for run in (first, second)]
        if read == "next":
            assert nearest[0] != nearest[1]
        else:
            assert nearest[0] == nearest[1]
            assert further[0] != further[1]


@pytest.mark.parametrize(("path", "values", "field"), OBSERVATION_EFFECTS)
def test_changing_an_information_key_changes_the_observation(
    path: str, values: tuple[object, object], field: str
):
    first, second = (observations_of_run(path, value, field) for value in values)

    assert first != second


def test_changing_when_a_price_is_drawn_changes_the_prices_observed():
    seen: list[list[object]] = []
    for drawn in ("run", "period"):
        manifest = tiny_manifest()
        manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["price"] = chip_price(
            drawn=drawn
        )
        with api_client() as client:
            run = start_run(client, manifest, seed=5)
            _, observation = get(client, f"/runs/{run['id']}/observation")
            prices: list[object] = []
            while "prices" in observation:
                prices.append(observation["prices"])
                _, observation = submit(client, run["id"], observation["period"], [])
        seen.append(prices)

    assert seen[0] != seen[1]


def test_a_longer_horizon_changes_every_flow_of_its_last_period():
    shorter, _ = totals_and_last_period(5)
    longer, last = totals_and_last_period(6)

    moved = [
        name
        for name, value in last.items()
        if MEASURE_KINDS.get(name) == "flow" and value
    ]
    assert moved
    assert [name for name in moved if shorter[name] == longer[name]] == []
