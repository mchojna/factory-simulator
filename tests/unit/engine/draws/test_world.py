import copy
import statistics
from dataclasses import replace
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from factories import (
    FactoryBodies,
    decide,
    draw_world_of_bodies,
    drawn_run,
    example_bodies,
    example_count,
    frozen_bodies,
    lognormal_bodies,
    observation_in,
    produce_decision,
    quantities,
    random_world,
    seeds,
    small_factories,
    tiny_manifest,
    tiny_scenario,
    to_engine,
)
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from factory_simulator.api.core.json import write_json
from factory_simulator.api.services.writers.world import world_json
from factory_simulator.engine import (
    Decisions,
    Disruption,
    Range,
    Scenario,
    Start,
    World,
    build_state,
    draw_value,
    draw_world,
    is_within_chance,
    open_stream,
    start_period,
)
from factory_simulator.engine.draws.values import draw_periods
from factory_simulator.engine.rules.targets import targets_in
from factory_simulator.engine.steps.execution import execute_decisions

FROZEN = Path(__file__).parent / "frozen-world" / "world.json"


FROZEN_COMMON_SHARE = Path(__file__).parent / "frozen-world" / "common-share.json"


FROZEN_PRICES = Path(__file__).parent / "frozen-world" / "prices.json"


FROZEN_LOGNORMAL = Path(__file__).parent / "frozen-world" / "lognormal.json"


FROZEN_WRITTEN_START = Path(__file__).parent / "frozen-world" / "written-start.json"


FROZEN_CASCADE = Path(__file__).parent / "frozen-world" / "cascade.json"


CHIP_PRICE = "suppliers.chip-maker.catalogue.chip.price"


SEED = 4


OUTAGE_EVERY_PERIOD = {
    "name": "outage",
    "kind": "supplier_outage",
    "target": ["chip-maker"],
    "chance": "1.0000",
    "duration": 1,
    "strength": "0.5000",
}


DELAYS = {
    "name": "delays",
    "kind": "transport_delay",
    "target": ["chip-maker"],
    "chance": "0.1000",
    "duration": 1,
    "delay": 1,
}


OUTAGE = {
    "name": "outage",
    "kind": "supplier_outage",
    "target": ["chip-maker"],
    "chance": "1.0000",
    "duration": {"min": 2, "max": 4},
    "strength": {"min": "0.5000", "max": "0.9000"},
}


CUT_AT_4 = {
    "name": "cut",
    "kind": "capacity_cut",
    "target": "all",
    "start": 4,
    "duration": 2,
    "strength": "0.5000",
}


def manifest_with_ranges() -> dict[str, Any]:
    manifest = tiny_manifest()
    terms = manifest["customers"]["distributor"]["products"]["monitor"]
    terms["demand"] = {"min": "2.000", "max": "9.000"}
    terms["price"] = {"min": "40.0000", "max": "60.0000"}
    terms["patience"] = {"min": 0, "max": 3}
    entry = manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]
    entry["punctuality"] = {"min": "0.5000", "max": "0.9000"}
    entry["delay"] = {"min": 1, "max": 3}
    entry["completeness"] = {"min": "0.8000", "max": "1.0000"}
    line = manifest["lines"]["line-1"]
    line["breakdown_chance"] = {"min": "0.1000", "max": "0.5000"}
    line["breakdown_loss"] = {"min": "0.1000", "max": "0.4000"}
    line["items"]["board"]["yield"] = {"min": "0.8000", "max": "0.9500"}
    return manifest


def frozen_world_text(manifest: dict[str, Any], scenario: dict[str, Any]) -> bytes:
    world = draw_world_of_bodies(manifest, scenario, seed=0)
    return write_json(world_json(world)) + b"\n"


# The frozen factory with a second customer of the monitor and a common share.
def common_share_bodies() -> FactoryBodies:
    manifest, scenario = frozen_bodies()
    distributor = manifest["customers"]["distributor"]
    manifest["customers"]["retailer"] = copy.deepcopy(distributor)
    manifest["products"]["monitor"]["common_share"] = "0.6000"
    return manifest, scenario


# The frozen factory with the chip price drawn every period.
def prices_bodies() -> FactoryBodies:
    manifest, scenario = frozen_bodies()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["price"]["drawn"] = (
        "period"
    )
    return manifest, scenario


# The frozen scenario with a supplier outage that starts in period 5 on a drawn target.
def written_start_bodies() -> FactoryBodies:
    manifest, scenario = frozen_bodies()
    scenario["random_disruptions"] = [
        {
            "name": "outage",
            "kind": "supplier_outage",
            "target": "all",
            "start": 5,
            "notice": 2,
            "duration": {"min": 1, "max": 3},
            "strength": {"min": "0.2000", "max": "0.8000"},
        }
    ]
    return manifest, scenario


# The frozen scenario with an outage that raises the chance of transport delays.
def cascade_bodies() -> FactoryBodies:
    manifest, scenario = frozen_bodies()
    scenario["random_disruptions"] = [
        {
            "name": "outage",
            "kind": "supplier_outage",
            "target": "all",
            "chance": "0.3000",
            "duration": 1,
            "strength": {"min": "0.2000", "max": "0.8000"},
            "raises": {"rule": "delays", "factor": "3.0000", "periods": 2},
        },
        {
            "name": "delays",
            "kind": "transport_delay",
            "target": "all",
            "chance": "0.1000",
            "duration": 1,
            "delay": {"min": 1, "max": 2},
        },
    ]
    return manifest, scenario


def chip_price_drawn(drawn: str) -> dict[str, Any]:
    manifest = tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["price"] = {
        "min": "0.4000",
        "max": "0.6000",
        "drawn": drawn,
    }
    return manifest


def horizon_of(periods: int) -> dict[str, Any]:
    scenario = tiny_scenario()
    scenario["horizon"] = periods
    return scenario


def ranges_drawn_every_period(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        f"{supplier_id}/{material_id}": entry["price"]
        for supplier_id, supplier in manifest["suppliers"].items()
        for material_id, entry in supplier["catalogue"].items()
        if isinstance(entry.get("price"), dict)
        and entry["price"].get("drawn") == "period"
    }


def without_price_of(world: World, pair: str) -> dict[str, Any]:
    supplier_id, material_id = pair.split("/")
    path = f"suppliers.{supplier_id}.catalogue.{material_id}.price"
    return {
        "parameters": {
            key: value for key, value in world.parameters.items() if key != path
        },
        "prices": {key: value for key, value in world.prices.items() if key != pair},
        "demand": world.demand,
        "deliveries": world.deliveries,
        "yields": world.yields,
        "breakdowns": world.breakdowns,
        "disruptions": world.disruptions,
        "forecasts": world.forecasts,
    }


def two_customers_of_the_monitor(common_share: str | None) -> dict[str, Any]:
    manifest = tiny_manifest()
    distributor = manifest["customers"]["distributor"]
    distributor["products"]["monitor"]["demand"] = {"min": "30.000", "max": "50.000"}
    manifest["customers"]["retailer"] = copy.deepcopy(distributor)
    if common_share is not None:
        manifest["products"]["monitor"]["common_share"] = common_share
    return manifest


def demand_over(
    manifest: dict[str, Any], horizon: int, seed: int
) -> dict[str, tuple[Decimal, ...]]:
    scenario = tiny_scenario()
    scenario["horizon"] = horizon
    return dict(draw_world_of_bodies(manifest, scenario, seed=seed).demand)


def correlation(first: tuple[Decimal, ...], second: tuple[Decimal, ...]) -> float:
    return statistics.correlation(
        [float(value) for value in first], [float(value) for value in second]
    )


# A generated manifest with one more customer, so that its first product has two
# customers with a range of demand and a common share.
def with_a_shared_product(manifest: dict[str, Any]) -> tuple[dict[str, Any], str]:
    shared = copy.deepcopy(manifest)
    product_id = sorted(shared["products"])[0]
    buyer = next(
        customer
        for _, customer in sorted(shared["customers"].items())
        if product_id in customer["products"]
    )
    buyer["products"][product_id]["demand"] = {"min": "1.000", "max": "9.000"}
    shared["customers"]["customer-shared"] = copy.deepcopy(buyer)
    shared["products"][product_id]["common_share"] = "0.5000"
    return shared, product_id


def starts_of(world: World, name: str) -> list[int]:
    return [
        disruption.start for disruption in world.disruptions if disruption.rule == name
    ]


def world_of(*rules: dict[str, Any]) -> World:
    scenario = tiny_scenario() | {"horizon": 6, "random_disruptions": list(rules)}
    return draw_world_of_bodies(tiny_manifest(), scenario, seed=SEED)


def u_values(*key: str, count: int) -> list[Decimal]:
    stream = open_stream(SEED, "disruption", *key)
    return [Decimal(repr(stream.random())) for _ in range(count)]


def world_with(*rules: dict[str, Any], horizon: int = 6, lines: int = 1) -> World:
    manifest = tiny_manifest()
    for number in range(2, lines + 1):
        manifest["lines"][f"line-{number}"] = copy.deepcopy(manifest["lines"]["line-1"])
    scenario = tiny_scenario()
    scenario["horizon"] = horizon
    scenario["random_disruptions"] = list(rules)
    return draw_world_of_bodies(manifest, scenario, seed=SEED)


def drawn(world: World) -> list[Disruption]:
    return [
        disruption for disruption in world.disruptions if disruption.rule is not None
    ]


def of_rule(world: World, name: str) -> list[Disruption]:
    return [disruption for disruption in world.disruptions if disruption.rule == name]


def test_adding_a_customer_changes_no_value_drawn_for_the_others():
    manifest = manifest_with_ranges()
    larger = copy.deepcopy(manifest)
    larger["customers"]["aaa-retail"] = copy.deepcopy(
        manifest["customers"]["distributor"]
    )
    scenario = tiny_scenario()
    scenario["horizon"] = 8

    world = draw_world_of_bodies(manifest, scenario, seed=11)
    larger_world = draw_world_of_bodies(larger, scenario, seed=11)

    pair = "distributor/monitor"
    assert larger_world.demand[pair] == world.demand[pair]
    assert larger_world.demand["aaa-retail/monitor"] != world.demand[pair]
    for path, value in world.parameters.items():
        assert larger_world.parameters[path] == value
    assert larger_world.deliveries == world.deliveries
    assert larger_world.yields == world.yields
    assert larger_world.breakdowns == world.breakdowns


def test_express_orders_draw_their_outcomes_from_a_stream_of_their_own():
    manifest = tiny_manifest()
    with_express = copy.deepcopy(manifest)
    chip = with_express["suppliers"]["chip-maker"]["catalogue"]["chip"]
    chip |= {
        "punctuality": "0.5000",
        "completeness": {"min": "0.9000", "max": "1.0000"},
        "express_lead_time": 1,
        "express_cost": "0.1000",
    }
    without_express = copy.deepcopy(with_express)
    del without_express["suppliers"]["chip-maker"]["catalogue"]["chip"][
        "express_lead_time"
    ]
    del without_express["suppliers"]["chip-maker"]["catalogue"]["chip"]["express_cost"]
    scenario = horizon_of(8)

    world = draw_world_of_bodies(with_express, scenario, seed=3)
    plain_world = draw_world_of_bodies(without_express, scenario, seed=3)

    express = world.express_deliveries["chip-maker/chip"]
    assert [outcome.period for outcome in express] == list(range(1, 9))
    assert express != world.deliveries["chip-maker/chip"]
    assert world.deliveries == plain_world.deliveries
    assert plain_world.express_deliveries == {}


def test_the_frozen_world_is_drawn_byte_for_byte_the_same():
    assert frozen_world_text(*frozen_bodies()) == FROZEN.read_bytes()


def test_the_frozen_world_with_a_common_share_is_drawn_byte_for_byte_the_same():
    assert frozen_world_text(*common_share_bodies()) == FROZEN_COMMON_SHARE.read_bytes()


def test_the_frozen_world_of_prices_drawn_each_period_is_drawn_byte_for_byte_the_same():
    assert frozen_world_text(*prices_bodies()) == FROZEN_PRICES.read_bytes()


def test_the_frozen_world_with_lognormal_ranges_is_drawn_byte_for_byte_the_same():
    assert frozen_world_text(*lognormal_bodies()) == FROZEN_LOGNORMAL.read_bytes()


def test_the_frozen_world_with_a_written_start_is_drawn_byte_for_byte_the_same():
    assert (
        frozen_world_text(*written_start_bodies()) == FROZEN_WRITTEN_START.read_bytes()
    )


def test_the_frozen_world_with_a_cascade_is_drawn_byte_for_byte_the_same():
    assert frozen_world_text(*cascade_bodies()) == FROZEN_CASCADE.read_bytes()


def test_a_price_drawn_every_period_takes_one_value_per_period_from_its_stream():
    per_period = draw_world_of_bodies(
        chip_price_drawn("period"), horizon_of(12), seed=5
    )
    per_run = draw_world_of_bodies(chip_price_drawn("run"), horizon_of(12), seed=5)

    prices = per_period.prices["chip-maker/chip"]
    assert len(prices) == 12
    assert prices[0] == per_run.parameters[CHIP_PRICE]
    assert len(set(prices)) > 1
    assert CHIP_PRICE not in per_period.parameters
    assert per_run.prices == {}


def test_a_price_a_group_gives_is_drawn_every_period_under_the_path_of_its_member():
    manifest = tiny_manifest()
    del manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["price"]
    manifest["suppliers"]["chip-maker"]["groups"] = ["apac"]
    price = {"min": "0.4000", "max": "0.6000", "drawn": "period"}
    manifest["groups"] = {
        "apac": {"kind": "region", "defaults": {"catalogue": {"price": price}}}
    }

    grouped = draw_world_of_bodies(manifest, horizon_of(6), seed=5)
    written = draw_world_of_bodies(chip_price_drawn("period"), horizon_of(6), seed=5)

    assert grouped.prices == written.prices


def test_a_common_share_of_0_draws_two_customers_apart():
    written = demand_over(two_customers_of_the_monitor("0.0000"), 12, 3)

    assert written["distributor/monitor"] != written["retailer/monitor"]


def test_a_high_common_share_moves_two_customers_together_over_520_periods():
    shared = demand_over(two_customers_of_the_monitor("0.9000"), 520, 0)
    independent = demand_over(two_customers_of_the_monitor("0.0000"), 520, 0)

    assert correlation(shared["distributor/monitor"], shared["retailer/monitor"]) > 0.7
    assert (
        -0.2
        < correlation(
            independent["distributor/monitor"], independent["retailer/monitor"]
        )
        < 0.2
    )


def test_an_outage_every_period_raises_delays_to_certain_from_period_2():
    raising = OUTAGE_EVERY_PERIOD | {
        "raises": {"rule": "delays", "factor": "15.0000", "periods": 1}
    }

    plain = world_of(DELAYS, OUTAGE_EVERY_PERIOD)
    raised = world_of(DELAYS, raising)

    # Each period draws the start draw, the duration and the delay of the target.
    stream = open_stream(SEED, "disruption", "delays", "chip-maker")
    draws = [Decimal(repr(stream.random())) for _ in range(18)][::3]
    by_chance = [
        period
        for period, uniform in enumerate(draws, start=1)
        if uniform < Decimal("0.1")
    ]
    assert (
        starts_of(plain, "outage") == starts_of(raised, "outage") == [1, 2, 3, 4, 5, 6]
    )
    assert starts_of(plain, "delays") == by_chance
    assert starts_of(raised, "delays") == sorted({*by_chance[:1], 2, 3, 4, 5, 6})


def test_a_started_disruption_takes_the_duration_and_effect_of_its_period():
    world = world_with(OUTAGE)

    start, duration_u, strength_u = u_values("outage", "chip-maker", count=3)
    first = drawn(world)[0]

    duration = draw_periods(Range(min=2, max=4), duration_u)
    strength = draw_value(
        Range(min=Decimal("0.5000"), max=Decimal("0.9000")), strength_u
    )
    assert is_within_chance(Decimal(1), start)
    assert (first.id, first.start, first.duration, first.effect) == (
        "outage/1/chip-maker",
        1,
        duration,
        strength,
    )


def test_a_rule_never_starts_on_a_target_it_still_acts_on():
    world = world_with(OUTAGE | {"duration": 2, "strength": "0.5000"})

    assert [disruption.start for disruption in drawn(world)] == [1, 3, 5]


def test_two_rules_on_one_target_act_together():
    world = world_with(
        OUTAGE | {"name": "outage-a", "duration": 2, "strength": "0.5000"},
        OUTAGE | {"name": "outage-b", "duration": 2, "strength": "0.5000"},
    )
    state = start_period(build_state(world), world)

    assert state.observation is not None
    assert [disruption.id for disruption in state.observation.disruptions] == [
        "outage-a/1/chip-maker",
        "outage-b/1/chip-maker",
    ]


def test_a_rule_without_choose_starts_on_every_target_that_draws_its_chance():
    rule = {
        "name": "line-trouble",
        "kind": "line_breakdown",
        "target": ["line-1", "line-2"],
        "chance": "1.0000",
        "loss": "0.1000",
    }
    world = world_with(rule, horizon=1, lines=2)

    assert [disruption.id for disruption in drawn(world)] == [
        "line-trouble/1/line-1",
        "line-trouble/1/line-2",
    ]


def test_a_random_breakdown_cuts_the_condition_once_in_its_start_period():
    rule = {
        "name": "line-trouble",
        "kind": "line_breakdown",
        "target": ["line-1"],
        "chance": "1.0000",
        "loss": "0.4000",
    }
    world = world_with(rule, horizon=1)

    state = start_period(build_state(world), world)

    breakdowns = [
        event for event in state.period_events if event["kind"] == "breakdown"
    ]
    assert [event["reference"] for event in breakdowns] == ["line-trouble/1/line-1"]
    assert state.condition["line-1"] == Decimal("0.6")


def test_choose_one_hits_the_target_with_the_smallest_draw():
    rule = {
        "name": "line-trouble",
        "kind": "line_breakdown",
        "target": "all",
        "chance": "1.0000",
        "loss": "0.1000",
        "choose": "one",
    }
    world = world_with(rule, horizon=1, lines=3)

    draws = {
        line: u_values("line-trouble", line, count=2)[0]
        for line in ("line-1", "line-2", "line-3")
    }
    chosen = min(sorted(draws), key=lambda line: draws[line])
    assert [disruption.id for disruption in drawn(world)] == [
        f"line-trouble/1/{chosen}"
    ]


def test_a_written_start_hits_the_target_with_the_smallest_draw_of_its_period():
    world = world_with(CUT_AT_4, lines=3)

    # Each period draws the target draw, the duration and the strength of every line,
    # so the target draw of period 4 is the tenth number of its stream.
    draws = {
        line: u_values("cut", line, count=12)[9]
        for line in ("line-1", "line-2", "line-3")
    }
    chosen = min(sorted(draws), key=lambda line: draws[line])
    assert [
        (disruption.id, disruption.start, disruption.duration, disruption.effect)
        for disruption in drawn(world)
    ] == [(f"cut/4/{chosen}", 4, 2, Decimal("0.5000"))]


def test_a_written_start_takes_the_notice_of_its_rule():
    world = world_with(CUT_AT_4 | {"notice": 3}, lines=3)

    assert [disruption.notice for disruption in drawn(world)] == [3]


def test_the_world_lists_written_disruptions_before_drawn_ones_by_name():
    manifest = tiny_manifest()
    scenario = tiny_scenario()
    scenario["disruptions"] = [
        {
            "kind": "supplier_outage",
            "target": ["chip-maker"],
            "start": 3,
            "duration": 1,
            "strength": "0.5000",
        }
    ]
    scenario["random_disruptions"] = [
        OUTAGE | {"name": "rule-b", "duration": 9},
        OUTAGE | {"name": "rule-a", "duration": 9},
    ]
    world = draw_world_of_bodies(manifest, scenario, seed=SEED)

    assert [disruption.id for disruption in world.disruptions] == [
        "disruption-1",
        "rule-a/1/chip-maker",
        "rule-b/1/chip-maker",
    ]


def test_the_same_scenario_and_seed_draw_the_same_disruptions():
    first = world_with(OUTAGE | {"chance": "0.5000"}, horizon=12)
    second = world_with(OUTAGE | {"chance": "0.5000"}, horizon=12)

    assert first.disruptions == second.disruptions


def test_written_breakdowns_come_before_random_ones_whatever_their_lines():
    manifest = tiny_manifest()
    manifest["lines"]["line-2"] = copy.deepcopy(manifest["lines"]["line-1"])
    scenario = tiny_scenario()
    scenario["horizon"] = 1
    scenario["disruptions"] = [
        {"kind": "line_breakdown", "target": ["line-2"], "start": 1, "loss": "0.2000"}
    ]
    scenario["random_disruptions"] = [
        {
            "name": name,
            "kind": "line_breakdown",
            "target": ["line-1"],
            "chance": "1.0000",
            "loss": "0.4000",
        }
        for name in ("line-trouble", "disruption-z")
    ]
    world = draw_world_of_bodies(manifest, scenario, seed=SEED)

    state = start_period(build_state(world), world)

    assert [
        (event["line"], event["reference"])
        for event in state.period_events
        if event["kind"] == "breakdown"
    ] == [
        ("line-2", "disruption-1"),
        ("line-1", "disruption-z/1/line-1"),
        ("line-1", "line-trouble/1/line-1"),
    ]


def test_a_fixed_duration_takes_its_slot_of_the_stream():
    fixed = drawn(world_with(OUTAGE | {"duration": 2}))[0]
    ranged = drawn(world_with(OUTAGE))[0]

    assert fixed.effect == ranged.effect


def test_a_notice_keeps_every_start_of_a_random_rule():
    announced = random_world(2)
    unannounced = random_world(0)

    assert [disruption.start for disruption in announced.disruptions] == [
        1,
        2,
        3,
        4,
        5,
        6,
    ]
    assert announced.disruptions == tuple(
        replace(disruption, notice=2) for disruption in unannounced.disruptions
    )
    first = observation_in(announced, 1)
    assert [disruption.id for disruption in first.disruptions] == [
        "outage/1/chip-maker",
        "outage/2/chip-maker",
        "outage/3/chip-maker",
    ]


# Seed 2 of `frequent-breakdowns` starts a breakdown of its rule in period 3.
def test_a_notice_on_frequent_breakdowns_keeps_its_breakdowns():
    manifest, scenario = example_bodies("frequent-breakdowns")
    unannounced = draw_world_of_bodies(manifest, scenario, seed=2)
    for rule in scenario["random_disruptions"]:
        if rule["name"] == "frequent-trouble":
            rule["notice"] = 4
    announced = draw_world_of_bodies(manifest, scenario, seed=2)

    ids = [disruption.id for disruption in announced.disruptions]
    assert len(ids) == len(unannounced.disruptions)
    assert "frequent-trouble/3/final-assembly-line" in ids
    assert announced.disruptions == tuple(
        replace(disruption, notice=4)
        if disruption.id.startswith("frequent-trouble/")
        else disruption
        for disruption in unannounced.disruptions
    )


def test_a_world_keeps_its_factory_when_the_caller_changes_the_dictionaries_it_gave():
    tiny_factory = to_engine(tiny_manifest(), tiny_scenario())[0]
    lines = dict(tiny_factory.lines)
    warehouses = dict(tiny_factory.warehouses)
    factory = replace(tiny_factory, lines=lines, warehouses=warehouses)
    start = Start(stock={"main": {"chip": Decimal("60.000")}})
    world = draw_world(factory, Scenario(horizon=2, start=start), seed=0)
    line, warehouse = lines["line-1"], warehouses["main"]

    lines["line-1"] = replace(line, capacity=Decimal(0))
    warehouses["main"] = replace(warehouse, capacity=Decimal(0))
    state = start_period(build_state(world), world)
    produce = produce_decision("board", "30")
    executed = execute_decisions(
        state, world, Decisions(period=1, decisions=(produce,))
    )

    assert world.factory.lines["line-1"] == line
    assert world.factory.warehouses["main"] == warehouse
    assert [outcome.accepted for outcome in executed.outcomes] == [True]


def test_a_range_of_payment_terms_draws_a_whole_number_within_it():
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["payment_terms"] = {"min": 1, "max": 3}
    path = "customers.distributor.payment_terms"

    terms = {
        draw_world_of_bodies(manifest, tiny_scenario(), seed).parameters[path]
        for seed in range(20)
    }

    assert terms <= {1, 2, 3}


@pytest.mark.property
@given(small_factories(), seeds)
def test_every_price_drawn_every_period_lies_within_its_range_with_4_places(
    factory: FactoryBodies, seed: int
):
    world = draw_world_of_bodies(*factory, seed=seed)

    for pair, price_range in ranges_drawn_every_period(factory[0]).items():
        prices = world.prices[pair]
        assert len(prices) == world.scenario.horizon
        for price in prices:
            assert Decimal(price_range["min"]) <= price <= Decimal(price_range["max"])
            assert price.as_tuple().exponent == -4


@pytest.mark.property
@given(small_factories(), seeds, st.data())
def test_changing_when_one_price_is_drawn_changes_no_other_drawn_value(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    entries = [
        (supplier_id, material_id)
        for supplier_id, supplier in manifest["suppliers"].items()
        for material_id, entry in supplier["catalogue"].items()
        if isinstance(entry.get("price"), dict)
    ]
    assume(entries)
    supplier_id, material_id = data.draw(st.sampled_from(entries))
    price = manifest["suppliers"][supplier_id]["catalogue"][material_id]["price"]
    flipped = copy.deepcopy(manifest)
    flipped["suppliers"][supplier_id]["catalogue"][material_id]["price"] = price | {
        "drawn": "run" if price.get("drawn") == "period" else "period"
    }
    pair = f"{supplier_id}/{material_id}"

    before = draw_world_of_bodies(manifest, scenario, seed=seed)
    after = draw_world_of_bodies(flipped, scenario, seed=seed)

    assert without_price_of(before, pair) == without_price_of(after, pair)


@pytest.mark.property
@settings(max_examples=example_count(50))
@given(small_factories(), seeds)
def test_a_common_share_of_0_draws_the_world_of_a_manifest_without_it(
    factory: FactoryBodies, seed: int
):
    manifest, scenario = factory
    without = copy.deepcopy(manifest)
    with_zero = copy.deepcopy(manifest)
    for product_id in manifest["products"]:
        without["products"][product_id].pop("common_share", None)
        with_zero["products"][product_id]["common_share"] = "0.0000"

    assert (
        draw_world_of_bodies(without, scenario, seed=seed).demand
        == draw_world_of_bodies(with_zero, scenario, seed=seed).demand
    )


@pytest.mark.property
@settings(max_examples=example_count(50))
@given(small_factories(), seeds, st.data())
def test_changing_a_common_share_leaves_every_other_product_and_stream(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, product_id = with_a_shared_product(factory[0])
    scenario = factory[1]
    changed = copy.deepcopy(manifest)
    changed["products"][product_id]["common_share"] = data.draw(
        st.sampled_from(["0.0000", "0.2500", "1.0000"])
    )

    world = draw_world_of_bodies(manifest, scenario, seed=seed)
    other = draw_world_of_bodies(changed, scenario, seed=seed)

    for pair in world.demand:
        if not pair.endswith(f"/{product_id}"):
            assert other.demand[pair] == world.demand[pair]
    assert other.deliveries == world.deliveries
    assert other.yields == world.yields
    assert other.breakdowns == world.breakdowns
    assert other.disruptions == world.disruptions
    path = f"products.{product_id}.common_share"
    for key, value in world.parameters.items():
        if key != path:
            assert other.parameters[key] == value


@pytest.mark.property
@settings(max_examples=example_count(50))
@given(seeds, st.integers(min_value=1, max_value=12), st.data())
def test_a_common_share_of_1_gives_two_customers_the_same_demand(
    seed: int, horizon: int, data: st.DataObject
):
    low, high = sorted(
        data.draw(st.lists(quantities, min_size=2, max_size=2)), key=Decimal
    )
    assume(low != high)
    manifest = two_customers_of_the_monitor("1.0000")
    for customer in manifest["customers"].values():
        customer["products"]["monitor"]["demand"] = {"min": low, "max": high}

    demand = demand_over(manifest, horizon, seed)

    assert demand["distributor/monitor"] == demand["retailer/monitor"]


@pytest.mark.property
@given(small_factories(), seeds, st.data())
def test_adding_raises_changes_no_draw_and_no_start_of_a_rule_it_does_not_name(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    chances = st.sampled_from(["0.1000", "0.5000", "0.9000"])
    raising = {
        "name": "rule-a",
        "kind": "supplier_outage",
        "target": "all",
        "chance": data.draw(chances),
        "duration": data.draw(st.integers(min_value=1, max_value=3)),
        "strength": "0.5000",
    }
    raised = {
        "name": "rule-b",
        "kind": "quality_drop",
        "target": "all",
        "chance": data.draw(chances),
        "duration": 1,
        "strength": "0.5000",
    }
    scenario["random_disruptions"] = [raising, raised]
    before = draw_world_of_bodies(manifest, scenario, seed=seed)
    cascade = {
        "rule": "rule-b",
        "factor": data.draw(st.sampled_from(["1.5000", "3.0000", "20.0000"])),
        "periods": data.draw(st.integers(min_value=1, max_value=3)),
    }
    scenario["random_disruptions"] = [raising | {"raises": cascade}, raised]
    after = draw_world_of_bodies(manifest, scenario, seed=seed)

    assert starts_of(after, "rule-a") == starts_of(before, "rule-a")
    assert dict(after.parameters) == dict(before.parameters)
    assert after.deliveries == before.deliveries
    assert after.demand == before.demand
    assert after.breakdowns == before.breakdowns


@pytest.mark.property
@given(small_factories(), seeds)
def test_adding_or_reordering_rules_leaves_the_draws_of_the_others(
    factory: FactoryBodies, seed: int
):
    manifest, scenario = factory
    rules = scenario["random_disruptions"]
    assume(rules)
    before = draw_world_of_bodies(manifest, scenario, seed=seed)
    # The new rule raises no chance, so it changes no start of the others.
    added = {key: value for key, value in rules[0].items() if key != "raises"}
    scenario["random_disruptions"] = [*reversed(rules), added | {"name": "rule-z"}]
    after = draw_world_of_bodies(manifest, scenario, seed=seed)

    for rule in rules:
        assert of_rule(after, rule["name"]) == of_rule(before, rule["name"])
    assert dict(after.parameters) == dict(before.parameters)
    assert after.deliveries == before.deliveries


@pytest.mark.property
@given(small_factories(), seeds)
def test_a_drawn_disruption_lies_within_its_ranges_and_never_overlaps_its_rule(
    factory: FactoryBodies, seed: int
):
    manifest, scenario = factory
    world = draw_world_of_bodies(manifest, scenario, seed=seed)

    for rule in world.scenario.random_disruptions:
        started = of_rule(world, rule.name)
        for disruption in started:
            for value, bounds in (
                (disruption.duration, rule.duration),
                (disruption.effect, rule.effect),
            ):
                if isinstance(bounds, Range):
                    assert bounds.min <= value <= bounds.max
                elif bounds is not None:
                    assert value == bounds
            assert isinstance(disruption.duration, int)
            whole = rule.kind == "transport_delay"
            assert disruption.effect.as_tuple().exponent == (0 if whole else -4)
        for target in {disruption.target for disruption in started}:
            on_target = sorted(
                (disruption.start, disruption.start + disruption.duration - 1)
                for disruption in started
                if disruption.target == target
            )
            for (_, end), (next_start, _) in pairwise(on_target):
                assert next_start > end


@pytest.mark.property
@given(small_factories(), seeds, st.data())
def test_a_fixed_duration_or_effect_written_as_a_range_draws_the_same_world(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    rules = scenario["random_disruptions"]
    assume(rules)
    position = data.draw(st.integers(min_value=0, max_value=len(rules) - 1))
    rule = rules[position]
    fixed = [
        key
        for key, value in rule.items()
        if key not in ("name", "kind", "target", "chance", "choose", "notice", "start")
        and not isinstance(value, dict)
    ]
    assume(fixed)
    before = draw_world_of_bodies(manifest, scenario, seed=seed)
    ranged = copy.deepcopy(scenario)
    for key in fixed:
        ranged["random_disruptions"][position][key] = {
            "min": rule[key],
            "max": rule[key],
        }
    after = draw_world_of_bodies(manifest, ranged, seed=seed)

    assert after.disruptions == before.disruptions
    assert dict(after.parameters) == dict(before.parameters)


@pytest.mark.property
@given(seeds, st.decimals(min_value=Decimal("0.0001"), max_value=1, places=4))
def test_a_new_target_changes_a_choice_only_where_it_wins(seed: int, chance: Decimal):
    rule = {
        "name": "line-trouble",
        "kind": "line_breakdown",
        "target": ["line-1", "line-2", "line-3"],
        "chance": str(chance),
        "loss": "0.1000",
        "choose": "one",
    }
    manifest = tiny_manifest()
    for number in range(2, 5):
        manifest["lines"][f"line-{number}"] = copy.deepcopy(manifest["lines"]["line-1"])
    scenario = tiny_scenario() | {"horizon": 12, "random_disruptions": [rule]}
    before = draw_world_of_bodies(manifest, scenario, seed=seed)
    scenario["random_disruptions"] = [rule | {"target": [*rule["target"], "line-4"]}]
    after = draw_world_of_bodies(manifest, scenario, seed=seed)

    hit_before = {
        disruption.start: disruption.target for disruption in before.disruptions
    }
    for disruption in after.disruptions:
        if disruption.target != ("line-4",):
            assert hit_before[disruption.start] == disruption.target
    assert {disruption.start for disruption in after.disruptions} == set(hit_before)


@pytest.mark.property
@given(small_factories(), seeds)
def test_a_written_start_starts_one_disruption_in_its_period_on_one_of_its_targets(
    factory: FactoryBodies, seed: int
):
    manifest, scenario = factory
    world = draw_world_of_bodies(manifest, scenario, seed=seed)

    for rule in world.scenario.random_disruptions:
        if rule.start is None:
            continue
        targets = targets_in(rule.kind, rule.target, rule.group, world.factory)
        started = of_rule(world, rule.name)
        assert len(started) == 1
        assert started[0].start == rule.start
        assert started[0].target is not None
        assert started[0].target[0] in targets


@pytest.mark.property
@given(small_factories(), seeds, st.data())
def test_giving_a_rule_a_written_start_leaves_the_draws_of_the_others(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    rules = [
        {key: value for key, value in rule.items() if key != "raises"}
        for rule in scenario["random_disruptions"]
    ]
    assume(rules)
    scenario["random_disruptions"] = rules
    before = draw_world_of_bodies(manifest, scenario, seed=seed)
    start = data.draw(st.integers(min_value=1, max_value=scenario["horizon"]))
    written = {
        key: value
        for key, value in rules[0].items()
        if key not in ("chance", "choose", "notice")
    }
    scenario["random_disruptions"] = [
        written | {"start": start},
        *rules[1:],
        written | {"name": "rule-z", "start": start},
    ]
    after = draw_world_of_bodies(manifest, scenario, seed=seed)

    for rule in rules[1:]:
        assert of_rule(after, rule["name"]) == of_rule(before, rule["name"])
    assert dict(after.parameters) == dict(before.parameters)
    assert after.deliveries == before.deliveries
    assert after.demand == before.demand


@pytest.mark.property
@given(seeds, st.integers(min_value=1, max_value=12))
def test_a_new_target_changes_a_written_start_only_where_it_wins(seed: int, start: int):
    rule: dict[str, Any] = {
        "name": "line-trouble",
        "kind": "line_breakdown",
        "target": ["line-1", "line-2", "line-3"],
        "start": start,
        "loss": "0.1000",
    }
    manifest = tiny_manifest()
    for number in range(2, 5):
        manifest["lines"][f"line-{number}"] = copy.deepcopy(manifest["lines"]["line-1"])
    scenario = tiny_scenario() | {"horizon": 12, "random_disruptions": [rule]}
    before = draw_world_of_bodies(manifest, scenario, seed=seed)
    scenario["random_disruptions"] = [rule | {"target": [*rule["target"], "line-4"]}]
    after = draw_world_of_bodies(manifest, scenario, seed=seed)

    [hit_before] = before.disruptions
    [hit_after] = after.disruptions
    assert hit_after.start == hit_before.start == start
    assert hit_after.target in (hit_before.target, ("line-4",))


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_hiding_groups_changes_neither_the_world_nor_the_run(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    world, steps = drawn_run(factory, seed, data.draw)
    plain = draw_world_of_bodies(manifest, scenario | {"hidden": []}, seed=seed)

    assert plain.parameters == world.parameters
    assert plain.disruptions == world.disruptions
    state = build_state(plain)
    for _, decisions, closed in steps:
        state = decide(start_period(state, plain), plain, decisions)
        assert state.ledger == closed.ledger
        assert state.period_events == closed.period_events
        assert state.measures == closed.measures


@pytest.mark.property
@given(small_factories(), seeds)
def test_a_notice_of_a_random_rule_changes_no_drawn_disruption(
    factory: FactoryBodies, seed: int
):
    manifest, scenario = factory
    world = draw_world_of_bodies(manifest, scenario, seed=seed)
    for rule in scenario["random_disruptions"]:
        rule["notice"] = 0
    unannounced = draw_world_of_bodies(manifest, scenario, seed=seed)

    notices = {rule.name: rule.notice for rule in world.scenario.random_disruptions}
    written = len(world.scenario.disruptions)
    assert world.disruptions[:written] == unannounced.disruptions[:written]
    assert world.disruptions[written:] == tuple(
        replace(disruption, notice=notices[disruption.id.split("/")[0]])
        for disruption in unannounced.disruptions[written:]
    )
