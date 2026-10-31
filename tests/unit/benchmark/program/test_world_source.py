from decimal import ROUND_HALF_EVEN, Decimal

import pytest
from factories import example_count
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.benchmark.client import JsonObject
from factory_simulator.benchmark.models.inputs import Arrival, Production
from factory_simulator.benchmark.program.world_source import (
    buy_options_of,
    first_arrival,
    kept_condition,
    order_arrivals,
    state_of,
)

CHIP = "suppliers.chip-maker.catalogue.chip"


def test_the_reference_plans_a_price_drawn_every_period_at_the_price_of_each_period():
    delivery = {
        "punctual": True,
        "delay": 0,
        "completeness": Decimal(1),
        "acceptance": Decimal(1),
    }
    world: JsonObject = {
        "parameters": {
            f"{CHIP}.max_quantity": {"value": Decimal(100)},
            f"{CHIP}.lead_time": {"value": 1},
            f"{CHIP}.backfill_delay": {"value": 0},
        },
        "prices": {"chip-maker/chip": [Decimal("0.4300"), Decimal("0.5700")]},
        "deliveries": {"chip-maker/chip": [delivery, delivery]},
        "disruptions": [],
    }
    manifest: JsonObject = {"suppliers": {"chip-maker": {"catalogue": {"chip": {}}}}}

    options = buy_options_of(range(1, 3), 3, world, manifest)

    assert [(option.period, option.unit_price) for option in options] == [
        (1, Decimal("0.4300")),
        (2, Decimal("0.5700")),
    ]


# Period 1 + 1: 100 * 0.833325 = 83.3325 arrive, half to even 83.332, and
# 83.332 * 0.6 = 49.9992 are accepted, 49.999, with 100 - 83.332 = 16.668 left
# open; period 2 + 2: 16.668 * 0.6 = 10.0008 accepted, 10.001.
def test_an_open_order_arrives_in_part_then_its_backfill_brings_the_rest():
    delivery = {
        "punctual": True,
        "delay": 0,
        "completeness": Decimal("0.833325"),
        "acceptance": Decimal("0.6"),
    }
    world: JsonObject = {
        "parameters": {
            f"{CHIP}.lead_time": {"value": 1},
            f"{CHIP}.backfill_delay": {"value": 2},
        },
        "deliveries": {"chip-maker/chip": [delivery]},
        "disruptions": [],
    }
    order: JsonObject = {
        "supplier": "chip-maker",
        "material": "chip",
        "placed": 1,
        "express": False,
        "open_quantity": Decimal(100),
    }

    arrivals = order_arrivals(order, Decimal(0), 1, 8, world)

    assert arrivals == (
        Arrival(period=2, accepted=Decimal("49.999"), left_open=Decimal("16.668")),
        Arrival(period=4, accepted=Decimal("10.001"), left_open=Decimal(0)),
    )


# 1 + 2 + 1 = 4 for a delivery that is not punctual, plus the delay 2 active in
# period 4; the delay of period 3 does not count.
def test_a_buy_arrives_later_by_the_transport_delay_active_in_its_arrival_period():
    world: JsonObject = {
        "parameters": {f"{CHIP}.lead_time": {"value": 2}},
        "deliveries": {"chip-maker/chip": [{"punctual": False, "delay": 1}]},
        "disruptions": [
            {
                "kind": "transport_delay",
                "target": ["chip-maker"],
                "start": 3,
                "duration": 1,
                "delay": 5,
            },
            {
                "kind": "transport_delay",
                "target": ["chip-maker"],
                "start": 4,
                "duration": 1,
                "delay": 2,
            },
        ],
    }

    assert first_arrival("chip-maker", "chip", 1, False, world) == 6


# Started in 3 - 2 + 1 = 2, at the yield 1 of period 2 times 1 - 0.5:
# 10.005 * 0.5 = 5.0025, half to even 5.002.
def test_production_on_the_way_counts_its_good_units_rounded_half_to_even():
    world: JsonObject = {
        "parameters": {"lines.line-1.items.board.lead_time": {"value": 2}},
        "yields": {"line-1/board": [Decimal("0.9"), Decimal(1)]},
        "disruptions": [
            {
                "kind": "yield_drop",
                "target": ["line-1"],
                "start": 2,
                "duration": 1,
                "strength": Decimal("0.5"),
            }
        ],
    }
    manifest: JsonObject = {
        "lines": {"line-1": {"warehouse": "centre"}},
        "warehouses": {"centre": {}, "main": {}},
    }
    made = {"line": "line-1", "item": "board", "started": Decimal("10.005"), "ready": 3}
    observation: JsonObject = {
        "period": 3,
        "horizon": 5,
        "cash": Decimal(5),
        "stock": {},
        "lines": {},
        "production": [made],
        "transfers": [],
        "supplier_orders": [],
        "receivables": [],
    }

    state = state_of(observation, world, manifest)

    assert state.production == (
        Production(
            warehouse="centre",
            item="board",
            started=Decimal("10.005"),
            ready=3,
            good=Decimal("5.002"),
        ),
    )


# An observation of a period with the productions on the way and nothing else.
def observation_with(period: int, production: list[JsonObject]) -> JsonObject:
    return {
        "period": period,
        "horizon": 5,
        "cash": Decimal(5),
        "stock": {},
        "lines": {},
        "production": production,
        "transfers": [],
        "supplier_orders": [],
        "receivables": [],
    }


@pytest.mark.parametrize(
    ("yield_", "count", "goods"),
    [
        # The batch so far is 0.0006 and 0.0012, rounded 0.001 and 0.001.
        ("0.6", 2, ["0.001", "0"]),
        # The batch so far is 0.0005, 0.001 and 0.0015, rounded half to even to 0,
        # 0.001 and 0.002.
        ("0.5", 3, ["0", "0.001", "0.001"]),
    ],
)
def test_productions_of_one_batch_on_the_way_get_the_good_units_the_engine_gives_them(
    yield_: str, count: int, goods: list[str]
):
    world: JsonObject = {
        "parameters": {"lines.line-1.items.board.lead_time": {"value": 2}},
        "yields": {"line-1/board": [Decimal(yield_)]},
        "disruptions": [],
    }
    manifest: JsonObject = {"lines": {"line-1": {}}, "warehouses": {"main": {}}}
    production = [
        {"line": "line-1", "item": "board", "started": Decimal("0.001"), "ready": 2}
        for _ in range(count)
    ]

    state = state_of(observation_with(2, production), world, manifest)

    assert [made.good for made in state.production] == [Decimal(good) for good in goods]


# Started in periods 1 and 2, the four are four batches: each rounds 0.0006 to
# 0.001.
def test_each_line_item_and_start_period_on_the_way_is_a_batch_of_its_own():
    pairs = ("line-1/board", "line-1/monitor", "line-2/board")
    world: JsonObject = {
        "parameters": {
            f"lines.{line_id}.items.{item_id}.lead_time": {"value": 3}
            for line_id, item_id in (pair.split("/") for pair in pairs)
        },
        "yields": {pair: [Decimal("0.6"), Decimal("0.6")] for pair in pairs},
        "disruptions": [],
    }
    manifest: JsonObject = {
        "lines": {"line-1": {}, "line-2": {}},
        "warehouses": {"main": {}},
    }
    production = [
        {"line": line_id, "item": item_id, "started": Decimal("0.001"), "ready": ready}
        for line_id, item_id, ready in (
            ("line-1", "board", 3),
            ("line-1", "board", 4),
            ("line-1", "monitor", 3),
            ("line-2", "board", 3),
        )
    ]

    state = state_of(observation_with(3, production), world, manifest)

    assert [made.good for made in state.production] == [Decimal("0.001")] * 4


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(
    st.decimals(min_value=Decimal(0), max_value=Decimal(1), places=4),
    st.lists(st.integers(min_value=1, max_value=1000), min_size=1, max_size=20),
)
def test_every_partition_of_a_batch_on_the_way_gives_the_good_units_of_one_production(
    share: Decimal, parts: list[int]
):
    world: JsonObject = {
        "parameters": {"lines.line-1.items.board.lead_time": {"value": 2}},
        "yields": {"line-1/board": [share]},
        "disruptions": [],
    }
    manifest: JsonObject = {"lines": {"line-1": {}}, "warehouses": {"main": {}}}
    thousandth = Decimal("0.001")
    production = [
        {"line": "line-1", "item": "board", "started": part * thousandth, "ready": 2}
        for part in parts
    ]

    state = state_of(observation_with(2, production), world, manifest)

    total = sum(parts) * thousandth
    one = (total * share).quantize(thousandth, rounding=ROUND_HALF_EVEN)
    assert sum(made.good for made in state.production) == one
    for made in state.production:
        assert 0 <= made.good <= made.started


def test_a_drawn_breakdown_keeps_the_condition_of_its_own_period_only():
    breakdowns = {
        "line-1": [
            {"breaks": False, "loss": Decimal(0)},
            {"breaks": True, "loss": Decimal("0.4")},
            {"breaks": False, "loss": Decimal(0)},
        ]
    }
    world: JsonObject = {"disruptions": [], "breakdowns": breakdowns}

    kept = [kept_condition("line-1", period, world) for period in (1, 2, 3)]

    assert kept == [Decimal(1), Decimal("0.6"), Decimal(1)]


# The batch so far sends 0.0006 and 0.0012, rounded 0.001 and 0.001: the first
# order brings 0.001 in period 2, the second 0 and its backfill 0.001 in period 4.
def test_open_orders_of_one_batch_arrive_as_the_engine_rounds_the_batch():
    delivery = {
        "punctual": True,
        "delay": 0,
        "completeness": Decimal("0.6"),
        "acceptance": Decimal(1),
    }
    world: JsonObject = {
        "parameters": {
            f"{CHIP}.lead_time": {"value": 1},
            f"{CHIP}.backfill_delay": {"value": 2},
        },
        "deliveries": {"chip-maker/chip": [delivery]},
        "disruptions": [],
    }
    orders = [
        {
            "id": f"buy-1-{number}",
            "supplier": "chip-maker",
            "material": "chip",
            "warehouse": "main",
            "placed": 1,
            "express": False,
            "open_quantity": Decimal("0.001"),
            "unit_price": Decimal("0.5"),
        }
        for number in (1, 2)
    ]
    observation: JsonObject = {
        "period": 1,
        "horizon": 8,
        "cash": Decimal(5),
        "stock": {},
        "lines": {},
        "production": [],
        "transfers": [],
        "supplier_orders": orders,
        "receivables": [],
    }

    state = state_of(observation, world, {})

    assert [order.arrivals for order in state.supplier_orders] == [
        (Arrival(period=2, accepted=Decimal("0.001"), left_open=Decimal(0)),),
        (
            Arrival(period=2, accepted=Decimal(0), left_open=Decimal("0.001")),
            Arrival(period=4, accepted=Decimal("0.001"), left_open=Decimal(0)),
        ),
    ]


# The normal order arrives on time in period 1 + 2, the express order late in
# period 1 + 1 + 1. Each is a batch of its own and sends 0.0006, rounded 0.001.
def test_an_express_and_a_normal_order_arriving_in_one_period_are_2_batches():
    normal = {
        "punctual": True,
        "delay": 0,
        "completeness": Decimal("0.6"),
        "acceptance": Decimal(1),
    }
    express = normal | {"punctual": False, "delay": 1}
    world: JsonObject = {
        "parameters": {
            f"{CHIP}.lead_time": {"value": 2},
            f"{CHIP}.express_lead_time": {"value": 1},
            f"{CHIP}.backfill_delay": {"value": 0},
        },
        "deliveries": {"chip-maker/chip": [normal]},
        "express_deliveries": {"chip-maker/chip": [express]},
        "disruptions": [],
    }
    orders = [
        {
            "id": f"buy-1-{number}",
            "supplier": "chip-maker",
            "material": "chip",
            "warehouse": "main",
            "placed": 1,
            "express": number == 2,
            "open_quantity": Decimal("0.001"),
            "unit_price": Decimal("0.5"),
        }
        for number in (1, 2)
    ]
    observation: JsonObject = {
        "period": 1,
        "horizon": 8,
        "cash": Decimal(5),
        "stock": {},
        "lines": {},
        "production": [],
        "transfers": [],
        "supplier_orders": orders,
        "receivables": [],
    }

    state = state_of(observation, world, {})

    assert [order.arrivals for order in state.supplier_orders] == [
        (Arrival(period=3, accepted=Decimal("0.001"), left_open=Decimal(0)),),
        (Arrival(period=3, accepted=Decimal("0.001"), left_open=Decimal(0)),),
    ]
