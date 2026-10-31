from decimal import Decimal
from typing import Any

import pytest
from factories import (
    FactoryBodies,
    demand_shapes,
    draw_world_of_bodies,
    seeds,
    small_factories,
    started,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given
from hypothesis import strategies as st

from factory_simulator.engine import (
    State,
    World,
    demand_factor,
)


def shaped_world(
    *shapes: dict[str, Any], base: str = "4.000", horizon: int = 5
) -> World:
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = base
    scenario = tiny_scenario()
    scenario["horizon"] = horizon
    scenario["demand_shapes"] = list(shapes)
    return draw_world_of_bodies(manifest, scenario)


def ordered(state: State) -> list[object]:
    return [
        event["quantity"]
        for event in state.period_events
        if event["kind"] == "customer_order"
    ]


def factor_of(world: World, period: int) -> Decimal:
    return demand_factor(
        "distributor", "monitor", period, world.scenario, world.factory
    )


def ramp(first: int, last: int, to_factor: str) -> dict[str, Any]:
    return {
        "kind": "ramp",
        "target": "all",
        "first": first,
        "last": last,
        "from_factor": "1.0000",
        "to_factor": to_factor,
    }


def s_curve_world(horizon: int = 20, **keys: object) -> World:
    shape = {
        "kind": "s_curve",
        "target": "all",
        "middle": 10,
        "steepness": "0.5000",
        "from_factor": "0.0000",
        "to_factor": "1.0000",
    } | keys
    scenario = tiny_scenario()
    scenario["horizon"] = horizon
    scenario["demand_shapes"] = [shape]
    return draw_world_of_bodies(tiny_manifest(), scenario)


def demand_of(world: World, period: int) -> Decimal:
    factor = demand_factor(
        "distributor", "monitor", period, world.scenario, world.factory
    )
    return (Decimal(40) * factor).quantize(Decimal("0.001"))


def test_a_trend_and_a_step_multiply_the_base_demand():
    world = shaped_world(
        {"kind": "trend", "target": "all", "rate": "0.0100"},
        {"kind": "step", "target": "all", "period": 3, "factor": "1.5000"},
        base="40.000",
    )

    assert factor_of(world, 3) == Decimal("1.53015")
    assert ordered(started(world, 3, {})) == [Decimal("61.206")]


def test_a_tie_of_demand_rounds_half_to_even():
    world = shaped_world(
        {"kind": "step", "target": "all", "period": 1, "factor": "1.0010"},
        base="2.500",
    )

    assert ordered(started(world, 1, {})) == [Decimal("2.502")]


def test_a_season_repeats_its_factors_each_for_its_period_length():
    season = {
        "kind": "season",
        "target": "all",
        "factors": ["0.8000", "0.9000", "1.1000", "1.2000"],
        "period_length": 13,
    }
    world = shaped_world(season)

    assert (factor_of(world, 14), factor_of(world, 53)) == (
        Decimal("0.9"),
        Decimal("0.8"),
    )


def test_a_ramp_moves_in_a_straight_line_between_its_factors():
    short = shaped_world(ramp(5, 9, "2.0000"))
    long = shaped_world(ramp(10, 20, "1.4000"))

    assert [factor_of(short, period) for period in (4, 5, 7, 9, 12)] == [
        Decimal("1"),
        Decimal("1"),
        Decimal("1.5"),
        Decimal("2"),
        Decimal("2"),
    ]
    assert [factor_of(long, period) for period in (5, 15, 30)] == [
        Decimal("1"),
        Decimal("1.2"),
        Decimal("1.4"),
    ]


@pytest.mark.slow
def test_a_step_to_0_stops_new_orders_from_its_period():
    step = {"kind": "step", "target": "all", "period": 40, "factor": "0.0000"}
    world = shaped_world(step, horizon=41)

    assert ordered(started(world, 39, {})) == [Decimal("4.000")]
    assert ordered(started(world, 40, {})) == []


def test_demand_rounded_to_0_creates_no_order():
    step = {"kind": "step", "target": "all", "period": 1, "factor": "0.4000"}
    world = shaped_world(step, base="0.001")

    assert ordered(started(world, 1, {})) == []


def test_a_shape_acts_only_on_the_pairs_of_its_target():
    manifest = tiny_manifest()
    distributor = manifest["customers"]["distributor"]
    manifest["customers"]["retailer"] = {"products": dict(distributor["products"])}
    manifest["products"]["keyboard"] = dict(manifest["products"]["monitor"])
    distributor["products"]["keyboard"] = dict(distributor["products"]["monitor"])
    scenario = tiny_scenario()
    double = {"kind": "step", "period": 1, "factor": "2.0000"}
    scenario["demand_shapes"] = [
        double | {"target": {"product": "monitor"}},
        double | {"target": {"customer": "retailer", "product": "monitor"}},
    ]
    world = draw_world_of_bodies(manifest, scenario)

    factors = {
        (customer, product): demand_factor(
            customer, product, 1, world.scenario, world.factory
        )
        for customer in ("distributor", "retailer")
        for product in ("keyboard", "monitor")
    }

    assert factors == {
        ("distributor", "keyboard"): Decimal(1),
        ("distributor", "monitor"): Decimal(2),
        ("retailer", "keyboard"): Decimal(1),
        ("retailer", "monitor"): Decimal(4),
    }


def test_an_s_curve_rises_from_its_first_factor_to_its_last():
    world = s_curve_world()

    assert [demand_of(world, period) for period in (10, 1, 20)] == [
        Decimal("20.000"),
        Decimal("0.439"),
        Decimal("39.732"),
    ]


def test_an_s_curve_far_beyond_the_horizon_stays_at_its_first_factor():
    late: dict[str, Any] = {"middle": 100, "from_factor": "0.5000"}
    world = s_curve_world(horizon=52, **late)

    assert {demand_of(world, period) for period in range(1, 53)} == {Decimal("20.000")}


def test_an_s_curve_whose_exponent_overflows_gives_its_first_factor():
    world = s_curve_world(middle=10000000)

    factor = demand_factor("distributor", "monitor", 1, world.scenario, world.factory)

    assert factor == Decimal(0)


@pytest.mark.property
@given(small_factories(), seeds)
def test_the_demand_factor_is_never_below_0(factory: FactoryBodies, seed: int):
    world = draw_world_of_bodies(*factory, seed=seed)

    for customer_id, customer in world.factory.customers.items():
        for product_id in customer.products:
            for period in range(1, world.scenario.horizon + 1):
                assert (
                    demand_factor(
                        customer_id, product_id, period, world.scenario, world.factory
                    )
                    >= 0
                )


@pytest.mark.property
@given(st.data())
def test_a_ramp_alone_gives_a_factor_between_its_two_factors(data: st.DataObject):
    shape = data.draw(
        demand_shapes(20, ["distributor"], ["monitor"]).filter(
            lambda shape: shape["kind"] == "ramp"
        )
    )
    world = shaped_world(shape)
    low, high = sorted((Decimal(shape["from_factor"]), Decimal(shape["to_factor"])))

    for period in range(1, 22):
        assert low <= factor_of(world, period) <= high


@pytest.mark.property
@given(st.data())
def test_a_shape_of_one_customer_leaves_every_other_customer_at_1(
    data: st.DataObject,
):
    shape = data.draw(demand_shapes(10, ["distributor"], ["monitor"]))
    manifest = tiny_manifest()
    distributor = manifest["customers"]["distributor"]
    manifest["customers"]["retailer"] = {"products": dict(distributor["products"])}
    scenario = tiny_scenario()
    scenario["demand_shapes"] = [shape | {"target": {"customer": "distributor"}}]
    world = draw_world_of_bodies(manifest, scenario)

    for period in range(1, 12):
        assert (
            demand_factor("retailer", "monitor", period, world.scenario, world.factory)
            == 1
        )


@pytest.mark.property
@given(
    st.integers(min_value=-100, max_value=100),
    st.decimals(min_value=Decimal("0.0001"), max_value=5, places=4),
    st.decimals(min_value=0, max_value=2, places=4),
    st.decimals(min_value=0, max_value=2, places=4),
    st.integers(min_value=1, max_value=52),
)
def test_an_s_curve_factor_lies_between_its_two_factors(
    middle: int, steepness: Decimal, low: Decimal, high: Decimal, period: int
):
    world = s_curve_world(
        horizon=52,
        middle=middle,
        steepness=str(steepness),
        from_factor=str(low),
        to_factor=str(high),
    )

    factor = demand_factor(
        "distributor", "monitor", period, world.scenario, world.factory
    )

    assert min(low, high) <= factor <= max(low, high)
    assert factor >= 0
