from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from factories import (
    FORECAST,
    FactoryBodies,
    RunStep,
    draw_world_of_bodies,
    drawn_runs,
    example_bodies,
    example_count,
    observation_in,
    seeds,
    shape_factor_of,
    small_factories,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from factory_simulator.engine import (
    Forecast,
    World,
    draw_forecast_increment,
    forecast_quantity,
    open_stream,
    targets_of,
)
from factory_simulator.engine.draws.forecasts import (
    demand_shocks,
    draw_forecasts,
    known_demand,
    shaped_demand,
)
from factory_simulator.engine.rules.targets import is_customer_product_targeted

SEED = 6


PAIR = "distributor/monitor"


# The forecast made in period 5 for period 7 has the error i_1(7) + i_2(7) =
# 0.0414 + 0.0423.
ERROR_OF_PERIOD_7 = Decimal("0.0837")


def forecast_world(
    *shocks: dict[str, Any],
    horizon: int = 10,
    periods_ahead: int = 2,
    noise: str = "0.1000",
    noise_growth: str = "0.0500",
    hidden: tuple[str, ...] = (),
) -> World:
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "50.000"
    scenario = tiny_scenario()
    scenario["horizon"] = horizon
    scenario["disruptions"] = list(shocks)
    scenario["hidden"] = list(hidden)
    scenario["forecasts"] = [
        {
            "target": "all",
            "periods_ahead": periods_ahead,
            "noise": noise,
            "noise_growth": noise_growth,
        }
    ]
    return draw_world_of_bodies(manifest, scenario, seed=SEED)


def shock(start: int, duration: int) -> dict[str, Any]:
    return {
        "kind": "demand_shock",
        "target": ["monitor"],
        "start": start,
        "duration": duration,
        "factor": "0.5000",
    }


# The uniform draws of the stream of a distance, one per target period.
def draws_of_stream(seed: int, pair: str, distance: int, periods: int) -> list[Decimal]:
    customer, product = pair.split("/")
    stream = open_stream(seed, "forecast", customer, product, str(distance))
    return [Decimal(repr(stream.random())) for _ in range(periods)]


# The errors of the forecasts made in each period, from the increments of the streams
# of the distances, at noise 0.1000 and noise growth 0.0500.
def errors_of_streams(periods: int, periods_ahead: int) -> list[list[Decimal | None]]:
    increments = {
        distance: [
            draw_forecast_increment(
                Decimal("0.1000") if distance == 1 else Decimal("0.0500"), uniform
            )
            for uniform in draws_of_stream(SEED, PAIR, distance, periods)
        ]
        for distance in range(1, periods_ahead + 1)
    }
    rows: list[list[Decimal | None]] = []
    for made in range(1, periods + 1):
        row: list[Decimal | None] = []
        for ahead in range(1, periods_ahead + 1):
            target = made + ahead
            if target > periods:
                row.append(None)
                continue
            row.append(
                sum(
                    (
                        increments[distance][target - 1]
                        for distance in range(1, ahead + 1)
                    ),
                    Decimal(0),
                )
            )
        rows.append(row)
    return rows


def visible_demand(
    world: World, customer: str, product: str, made: int, period: int
) -> Decimal:
    shocks = Decimal(1)
    for disruption in world.disruptions:
        if (
            "disruptions.duration" not in world.scenario.hidden
            and disruption.kind == "demand_shock"
            and disruption.start - disruption.notice <= made
            and disruption.start <= period < disruption.start + disruption.duration
            and product in targets_of(disruption, world)
        ):
            shocks *= disruption.effect
    base = world.demand[f"{customer}/{product}"][period - 1]
    shape = shape_factor_of(world, customer, product, period)
    return (base * shape * shocks).quantize(Decimal("0.001"))


def entry_of(world: World, pair: str) -> Forecast:
    customer, product = pair.split("/")
    [entry] = [
        entry
        for entry in world.scenario.forecasts
        if is_customer_product_targeted(entry, customer, product, world.factory)
    ]
    return entry


def width_of(world: World, pair: str, ahead: int) -> Decimal:
    entry = entry_of(world, pair)
    return entry.noise + entry.noise_growth * (ahead - 1)


def every_forecast(
    world: World,
) -> list[tuple[str, int, int, Decimal | None, Decimal | None]]:
    return [
        (pair, made, ahead, quantity, world.forecast_errors[pair][made - 1][ahead - 1])
        for pair, rows in world.forecasts.items()
        for made, row in enumerate(rows, start=1)
        for ahead, quantity in enumerate(row, start=1)
    ]


def shock_world(notice: int) -> World:
    manifest = tiny_manifest()
    manifest["customers"]["distributor"]["products"]["monitor"]["demand"] = "50.000"
    scenario = tiny_scenario() | {
        "horizon": 10,
        "disruptions": [
            {
                "kind": "demand_shock",
                "target": ["monitor"],
                "start": 7,
                "duration": 1,
                "factor": "0.5000",
                "notice": notice,
            }
        ],
        "forecasts": [
            {
                "target": "all",
                "periods_ahead": 2,
                "noise": "0.1000",
                "noise_growth": "0.0500",
            }
        ],
    }
    return draw_world_of_bodies(manifest, scenario, seed=SEED)


# The middle of the interval of the demand each forecast allows, from the forecasts
# made k = 1 to 8 periods ahead of a target period, and from the newest alone.
def middles(forecasts: list[Decimal], widths: list[Decimal]) -> tuple[Decimal, Decimal]:
    lows = [
        forecast / (1 + width)
        for forecast, width in zip(forecasts, widths, strict=True)
    ]
    highs = [
        forecast / (1 - width)
        for forecast, width in zip(forecasts, widths, strict=True)
    ]
    return (max(lows) + min(highs)) / 2, (lows[0] + highs[0]) / 2


# The mean absolute relative error of the middle of the intersection of 8 forecasts
# and of the middle of the newest, over the example `forecasts`, seeds 0 to 4, every
# pair and the target periods 9 to 52.
def intersection_errors(noise: str, noise_growth: str) -> tuple[Decimal, Decimal]:
    manifest, scenario = example_bodies("forecasts")
    scenario["forecasts"][0].update(
        periods_ahead=8, noise=noise, noise_growth=noise_growth
    )
    intersected: list[Decimal] = []
    newest: list[Decimal] = []
    for seed in range(5):
        world = draw_world_of_bodies(manifest, scenario, seed=seed)
        for pair, rows in world.forecasts.items():
            customer, product = pair.split("/")
            shaped = shaped_demand(customer, product, world)
            shocks = demand_shocks(product, world)
            for target in range(9, 53):
                demand = known_demand(shaped, shocks, target, target)
                if demand == 0:
                    continue
                aheads = range(1, 9)
                made = [rows[target - ahead - 1][ahead - 1] for ahead in aheads]
                forecasts = [forecast for forecast in made if forecast is not None]
                widths = [width_of(world, pair, ahead) for ahead in aheads]
                both = middles(forecasts, widths)
                intersected.append(abs(both[0] - demand) / demand)
                newest.append(abs(both[1] - demand) / demand)
    count = len(newest)
    return sum(intersected, Decimal(0)) / count, sum(newest, Decimal(0)) / count


def test_an_increment_is_drawn_within_its_width_and_rounded_to_4_places():
    cases = [
        ("0.1000", "0.7068", "0.0414"),
        ("0.0500", "0.9227", "0.0423"),
        ("0.0500", "0.5943", "0.0094"),
        ("0.1000", "0", "-0.1000"),
        ("0.1000", "1", "0.1000"),
    ]

    for width, uniform, increment in cases:
        drawn = draw_forecast_increment(Decimal(width), Decimal(uniform))
        assert (drawn, drawn.as_tuple().exponent) == (Decimal(increment), -4)


def test_a_forecast_below_0_is_0():
    first = draw_forecast_increment(Decimal("0.6000"), Decimal("0.0500"))
    second = draw_forecast_increment(Decimal("0.5000"), Decimal("0.0100"))

    assert (first, second) == (Decimal("-0.5400"), Decimal("-0.4900"))
    assert forecast_quantity(Decimal("50.000"), first + second) == Decimal("0.000")


@pytest.mark.parametrize("demand", ["0.000", "0.001"])
def test_a_forecast_that_rounds_to_minus_0_is_0_with_a_positive_sign(demand: str):
    # 0 * (1 - 1.2) is -0, and 0.001 * (1 - 1.2) = -0.0002 rounds to -0.000.
    quantity = forecast_quantity(Decimal(demand), Decimal("-1.2000"))

    assert (str(quantity), quantity.is_signed()) == ("0.000", False)


@pytest.mark.property
@given(
    st.decimals(min_value=0, max_value=10**6, places=3),
    st.decimals(min_value=-3, max_value=3, places=4),
)
def test_every_forecast_is_at_least_0_and_has_no_negative_sign(
    demand: Decimal, error: Decimal
):
    quantity = forecast_quantity(demand, error)

    assert quantity >= 0
    assert not quantity.is_signed()


def test_each_later_forecast_of_a_period_is_the_earlier_less_its_farthest_increment():
    world = forecast_world(periods_ahead=3)

    assert [draws_of_stream(SEED, PAIR, distance, 7)[6] for distance in (1, 2, 3)] == [
        Decimal("0.7068084191976909"),
        Decimal("0.9227198166384621"),
        Decimal("0.5943072744538647"),
    ]
    # Increments 0.0414, 0.0423 and 0.0094. Made in period 4: error 0.0931 and
    # 50 * 1.0931; in period 5: error 0.0931 - 0.0094 and 54.655 - 50 * 0.0094; in
    # period 6: error 0.0837 - 0.0423 and 54.185 - 50 * 0.0423.
    errors = world.forecast_errors[PAIR]
    forecasts = world.forecasts[PAIR]
    assert (errors[3][2], errors[4][1], errors[5][0]) == (
        Decimal("0.0931"),
        Decimal("0.0837"),
        Decimal("0.0414"),
    )
    assert (forecasts[3][2], forecasts[4][1], forecasts[5][0]) == (
        Decimal("54.655"),
        Decimal("54.185"),
        Decimal("52.070"),
    )


def test_every_increment_is_drawn_from_the_slot_of_its_target_period():
    world = forecast_world(periods_ahead=3)

    assert [list(row) for row in world.forecast_errors[PAIR]] == errors_of_streams(
        10, 3
    )


def test_without_noise_growth_every_forecast_of_a_period_is_the_same():
    world = forecast_world(periods_ahead=3, noise="0.2000", noise_growth="0.0000")
    forecasts = world.forecasts[PAIR]

    for target in range(4, 11):
        made = [forecasts[target - ahead - 1][ahead - 1] for ahead in (1, 2, 3)]
        assert made[0] == made[1] == made[2]


@pytest.mark.slow
@pytest.mark.parametrize(
    ("noise", "noise_growth", "error"),
    [("0.0500", "0.0250", "0.025"), ("0.2000", "0.0000", "0.107")],
)
def test_an_agent_with_8_forecasts_of_a_period_knows_it_as_well_as_from_the_newest(
    noise: str, noise_growth: str, error: str
):
    intersected, newest = intersection_errors(noise, noise_growth)

    place = Decimal("0.001")
    assert intersected.quantize(place) == newest.quantize(place) == Decimal(error)


def test_a_shock_not_yet_visible_is_left_out_of_the_forecast():
    world = forecast_world(shock(7, 1))

    assert world.forecast_errors[PAIR][4][1] == ERROR_OF_PERIOD_7
    # 50 * 1.0837 = 54.185
    assert world.forecasts[PAIR][4][1] == Decimal("54.185")


def test_a_visible_shock_acting_in_the_forecast_period_is_in_it():
    world = forecast_world(shock(5, 3))

    assert world.forecast_errors[PAIR][4][1] == ERROR_OF_PERIOD_7
    # 50 * 0.5 * 1.0837 = 27.0925, rounded half to even to 27.092
    assert world.forecasts[PAIR][4][1] == Decimal("27.092")


def test_no_shock_is_in_a_forecast_when_the_duration_of_disruptions_is_hidden():
    world = forecast_world(shock(5, 3), hidden=("disruptions.duration",))

    assert world.forecast_errors[PAIR][4][1] == ERROR_OF_PERIOD_7
    assert world.forecasts[PAIR][4][1] == Decimal("54.185")


def test_a_forecast_is_never_below_0():
    world = forecast_world(noise="1.0000", noise_growth="0.5000")

    errors = world.forecast_errors[PAIR]
    below_minus_1 = [
        (made, ahead)
        for made, row in enumerate(errors)
        for ahead, error in enumerate(row)
        if error is not None and error < -1
    ]
    assert below_minus_1 == [(2, 1)]
    assert errors[2] == (Decimal("-0.7144"), Decimal("-1.1007"))
    # 50 * 0.2856 = 14.280; 50 * (1 - 1.1007) is below 0, so 0.
    assert world.forecasts[PAIR][2] == (Decimal("14.280"), Decimal("0.000"))


def test_forecasts_stop_at_the_horizon_and_so_do_their_errors():
    world = forecast_world(periods_ahead=4)

    eighth = observation_in(world, 8)
    tenth = observation_in(world, 10)

    assert [seen.period for seen in eighth.forecasts[PAIR]] == [9, 10]
    assert tenth.forecasts[PAIR] == ()
    assert world.forecasts[PAIR][7][2:] == (None, None)
    assert world.forecast_errors[PAIR][7] == (
        Decimal("0.0048"),
        Decimal("0.1202"),
        None,
        None,
    )
    assert [len(row) for row in world.forecast_errors[PAIR]] == [4] * 10


def test_a_forecast_of_a_pair_with_hidden_demand_is_shown():
    manifest = tiny_manifest()
    scenario = tiny_scenario() | {
        "forecasts": [FORECAST],
        "hidden": ["customers.products.demand"],
    }
    world = draw_world_of_bodies(manifest, scenario, seed=SEED)

    assert world.forecast_errors[PAIR][0] == (Decimal("-0.0529"), Decimal("-0.0256"))
    # 4 * 0.9471 = 3.7884 and 4 * 0.9744 = 3.8976, rounded to 3.788 and 3.898.
    assert [
        (seen.period, seen.quantity)
        for seen in observation_in(world, 1).forecasts[PAIR]
    ] == [(2, Decimal("3.788")), (3, Decimal("3.898"))]


def test_a_forecast_holds_a_shock_from_its_notice():
    announced, unannounced = shock_world(2), shock_world(0)
    error = announced.forecast_errors[PAIR][4][1]
    assert error is not None

    def expected(demand: str) -> Decimal:
        return (Decimal(demand) * (1 + error)).quantize(Decimal("0.001"))

    assert Decimal("-0.1500") <= error <= Decimal("0.1500")
    assert announced.forecasts[PAIR][4][1] == expected("25.000")
    assert unannounced.forecasts[PAIR][4][1] == expected("50.000")


@pytest.mark.property
@given(small_factories(), seeds)
def test_a_forecast_without_noise_is_the_demand_known_when_it_is_made(
    factory: FactoryBodies, seed: int
):
    manifest, scenario = factory
    for entry in scenario["forecasts"]:
        entry.update(noise="0.0000", noise_growth="0.0000")
    world = draw_world_of_bodies(manifest, scenario, seed=seed)

    for pair, made, ahead, quantity, _ in every_forecast(world):
        if quantity is not None:
            customer, product = pair.split("/")
            assert quantity == visible_demand(
                world, customer, product, made, made + ahead
            )


@pytest.mark.property
@given(small_factories(), seeds)
def test_every_forecast_and_error_lies_within_its_width(
    factory: FactoryBodies, seed: int
):
    world = draw_world_of_bodies(*factory, seed=seed)

    for pair, made, ahead, quantity, error in every_forecast(world):
        width = width_of(world, pair, ahead)
        if made + ahead > world.scenario.horizon:
            assert quantity is None
            assert error is None
            continue
        assert error is not None
        assert error.as_tuple().exponent == -4
        assert -width <= error <= width
        assert quantity is not None
        customer, product = pair.split("/")
        demand = visible_demand(world, customer, product, made, made + ahead)
        low = max((demand * (1 - width)).quantize(Decimal("0.001")), Decimal(0))
        high = (demand * (1 + width)).quantize(Decimal("0.001"))
        assert quantity.as_tuple().exponent == -3
        assert low <= quantity <= high


@pytest.mark.property
@given(small_factories(), seeds)
def test_a_forecast_made_one_period_later_drops_the_farthest_increment(
    factory: FactoryBodies, seed: int
):
    world = draw_world_of_bodies(*factory, seed=seed)
    horizon = world.scenario.horizon

    for pair, rows in world.forecast_errors.items():
        periods_ahead = len(rows[0])
        draws = {
            distance: draws_of_stream(seed, pair, distance, horizon)
            for distance in range(1, periods_ahead + 1)
        }
        for target in range(2, horizon + 1):
            for ahead in range(1, min(periods_ahead, target - 1) + 1):
                made = target - ahead
                error = rows[made - 1][ahead - 1]
                later = rows[made][ahead - 2] if ahead > 1 else Decimal(0)
                assert error is not None and later is not None
                entry = entry_of(world, pair)
                width = entry.noise if ahead == 1 else entry.noise_growth
                increment = draw_forecast_increment(width, draws[ahead][target - 1])
                assert error - later == increment
                assert -width <= increment <= width


@pytest.mark.property
@given(small_factories(), seeds, st.data())
def test_changing_periods_ahead_keeps_the_errors_of_the_distances_kept(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    before = draw_world_of_bodies(manifest, scenario, seed=seed)
    for entry in scenario["forecasts"]:
        entry["periods_ahead"] = data.draw(
            st.integers(min_value=1, max_value=scenario["horizon"]),
            label="periods_ahead",
        )
    after = draw_world_of_bodies(manifest, scenario, seed=seed)

    for pair, rows in before.forecast_errors.items():
        for made, row in enumerate(rows):
            kept = zip(row, after.forecast_errors[pair][made], strict=False)
            for error, changed in kept:
                assert error == changed


@pytest.mark.property
@given(small_factories(), seeds)
def test_no_forecast_reflects_a_disruption_not_yet_visible(
    factory: FactoryBodies, seed: int
):
    world = draw_world_of_bodies(*factory, seed=seed)

    for made in range(1, world.scenario.horizon + 1):
        known = tuple(
            disruption
            for disruption in world.disruptions
            if disruption.start - disruption.notice <= made
        )
        forecasts, _ = draw_forecasts(replace(world, disruptions=known), seed)
        for pair, rows in world.forecasts.items():
            assert rows[made - 1] == forecasts[pair][made - 1]


@pytest.mark.property
@given(small_factories(), seeds)
def test_a_hidden_duration_keeps_every_demand_shock_out_of_the_forecasts(
    factory: FactoryBodies, seed: int
):
    manifest, scenario = factory
    scenario["hidden"] = ["disruptions.duration"]
    world = draw_world_of_bodies(manifest, scenario, seed=seed)

    others = tuple(
        disruption
        for disruption in world.disruptions
        if disruption.kind != "demand_shock"
    )
    forecasts, _ = draw_forecasts(replace(world, disruptions=others), seed)
    assert forecasts == world.forecasts


@pytest.mark.property
@given(small_factories(), seeds, st.data())
def test_adding_a_forecast_of_one_pair_leaves_the_world_of_the_others(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    before = draw_world_of_bodies(manifest, scenario, seed=seed)
    free = sorted(
        f"{customer}/{product}"
        for customer, terms in manifest["customers"].items()
        for product in terms["products"]
        if f"{customer}/{product}" not in before.forecasts
    )
    assume(free)
    customer, product = data.draw(st.sampled_from(free)).split("/")
    scenario["forecasts"] = [
        *scenario["forecasts"],
        FORECAST
        | {"target": {"customer": customer, "product": product}, "periods_ahead": 1},
    ]
    after = draw_world_of_bodies(manifest, scenario, seed=seed)

    assert set(after.forecasts) == {*before.forecasts, f"{customer}/{product}"}
    for pair in before.forecasts:
        assert after.forecasts[pair] == before.forecasts[pair]
        assert after.forecast_errors[pair] == before.forecast_errors[pair]
    assert after.demand == before.demand
    assert after.disruptions == before.disruptions
    assert dict(after.parameters) == dict(before.parameters)


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(drawn_runs())
def test_no_observation_shows_a_forecast_past_the_horizon_or_too_far_ahead(
    run: tuple[World, list[RunStep]],
):
    world, steps = run

    for decided, _, _ in steps:
        assert decided.observation is not None
        for pair, seen in decided.observation.forecasts.items():
            ahead = len(world.forecast_errors[pair][0])
            for forecast in seen:
                assert decided.period < forecast.period <= world.scenario.horizon
                assert forecast.period - decided.period <= ahead
