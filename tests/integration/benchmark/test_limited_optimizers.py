from collections.abc import Callable
from decimal import Decimal
from functools import partial
from typing import Any

import pytest
from factories import (
    benchmark_client,
    example_count,
    hidden_yield_bodies,
    intermittent_demand_bodies,
    linear_factories,
    plain_tiny_manifest,
    plain_tiny_scenario,
    seeds,
    withdrawn_demand_bodies,
)
from hypothesis import given, settings

from factory_simulator.benchmark import client as benchmark
from factory_simulator.benchmark.client import Check, JsonObject
from factory_simulator.benchmark.models.inputs import PlanningInput
from factory_simulator.benchmark.optimizers.aligned import aligned_optimizer
from factory_simulator.benchmark.optimizers.buffered_rolling import (
    buffered_rolling_optimizer,
)
from factory_simulator.benchmark.optimizers.full_horizon import full_horizon_optimizer
from factory_simulator.benchmark.optimizers.informed import informed_optimizer
from factory_simulator.benchmark.optimizers.myopic import myopic_optimizer
from factory_simulator.benchmark.optimizers.rolling import rolling_optimizer
from factory_simulator.benchmark.program.decisions import Optimizer
from factory_simulator.benchmark.program.expected_source import (
    LEAN_TERMINAL_VALUE_FACTOR,
    expected_planning_input,
    expected_planning_source,
)


def played_on_the_plain_tiny_factory(
    make_optimizer: Callable[[Check], Optimizer],
    scenario: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], Optimizer]:
    with benchmark_client() as client:
        manifest = benchmark.send(client, "POST", "/manifests", plain_tiny_manifest())
        path = f"/manifests/{manifest['id']}/scenarios"
        body = plain_tiny_scenario() if scenario is None else scenario
        stored = benchmark.send(client, "POST", path, body)
        run = benchmark.start_run(client, stored["id"], 0)
        optimizer = make_optimizer(partial(benchmark.create_check, client, run["id"]))
        return benchmark.play_run(client, run, optimizer), optimizer


# A run of a scenario played by the informed optimizer at a factor, planned from the
# description of the twin of the scenario with the seed of its run, and its result.
def played_by_the_informed_optimizer(
    manifest: dict[str, Any], scenario: dict[str, Any], factor: Decimal
) -> dict[str, Any]:
    with benchmark_client() as client:
        stored = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        shown = benchmark.create_shown_description(client, stored["id"], 0, scenario)
        run = benchmark.start_run(client, scenario_id, 0)
        check = partial(benchmark.create_check, client, run["id"])
        optimizer = informed_optimizer(check, factor, shown)
        return benchmark.play_run(client, run, optimizer)


# An s-curve of steepness 100000 and middle 100 overflows its exponent in every period
# of the plain tiny scenario, so its factor is 1 throughout, and every limited
# optimizer plays the run as it plays the scenario without it.
@pytest.mark.parametrize(
    "make_optimizer",
    [
        full_horizon_optimizer,
        rolling_optimizer,
        buffered_rolling_optimizer,
        aligned_optimizer,
        myopic_optimizer,
    ],
)
def test_every_limited_optimizer_plays_a_steep_s_curve_to_the_end(
    make_optimizer: Callable[[Check], Optimizer],
):
    s_curve = {
        "kind": "s_curve",
        "target": "all",
        "middle": 100,
        "steepness": "100000.0000",
        "from_factor": "1.0000",
        "to_factor": "2.0000",
    }
    scenario = plain_tiny_scenario() | {"demand_shapes": [s_curve]}

    result, _ = played_on_the_plain_tiny_factory(make_optimizer, scenario)
    plain, _ = played_on_the_plain_tiny_factory(make_optimizer)

    assert result["profit"] == plain["profit"]


# With no range its expectations equal the world, and the window covers the 3 periods.
def test_the_full_horizon_optimizer_reaches_the_reference_on_the_plain_tiny_factory():
    result, _ = played_on_the_plain_tiny_factory(full_horizon_optimizer)

    assert result["profit"] == Decimal(328)


# With no range its expectations equal the world, so its relaxed program has the value
# of the program of the reference.
def test_the_full_horizon_optimizer_keeps_the_value_of_its_relaxed_program():
    _, optimizer = played_on_the_plain_tiny_factory(full_horizon_optimizer)

    assert optimizer.relaxed_program_value == pytest.approx(328)
    assert [solve.period for solve in optimizer.solves] == [1, 2, 3]


# It never sees an order it can ship before the order is lost: 3 orders lost at 40,
# 16 chips at 0.1 and 8 boards at 0.5.
def test_the_aligned_optimizer_gains_what_no_decisions_gain():
    result, _ = played_on_the_plain_tiny_factory(aligned_optimizer)

    assert result["profit"] == Decimal("-114.4")


# The longest chain of lead times of the plain tiny factory is 3, so the window of the
# first period ends in period 3 + 2 = 5, before the horizon of 8, and the terminal
# values of the units at its end are played through the engine.
def test_the_rolling_optimizer_plays_8_periods_with_a_window_shorter_than_the_run():
    scenario = plain_tiny_scenario() | {"horizon": 8}
    with benchmark_client() as client:
        manifest = benchmark.send(client, "POST", "/manifests", plain_tiny_manifest())
        path = f"/manifests/{manifest['id']}/scenarios"
        stored = benchmark.send(client, "POST", path, scenario)
        run = benchmark.start_run(client, stored["id"], 0)
        first = benchmark.read(client, f"/runs/{run['id']}/observation")
        check = partial(benchmark.create_check, client, run["id"])
        result = benchmark.play_run(client, run, rolling_optimizer(check))

    planning = expected_planning_input(
        first, "lead_chain", "expected", Decimal("1.01"), {}, run["description"]
    )
    assert (planning.window_end, planning.horizon) == (5, 8)
    assert result["periods"] == 8
    assert result["measures"]["total"]["decisions_rejected"] == 0


# Its window of 5 periods ends before the horizon of 8 in periods 1 to 3, so its
# terminal values at 1.2 times the cost are played through the engine.
def test_the_buffered_rolling_optimizer_plays_8_periods_with_no_decision_rejected():
    scenario = plain_tiny_scenario() | {"horizon": 8}
    with benchmark_client() as client:
        manifest = benchmark.send(client, "POST", "/manifests", plain_tiny_manifest())
        path = f"/manifests/{manifest['id']}/scenarios"
        stored = benchmark.send(client, "POST", path, scenario)
        run = benchmark.start_run(client, stored["id"], 0)
        check = partial(benchmark.create_check, client, run["id"])
        result = benchmark.play_run(client, run, buffered_rolling_optimizer(check))

    assert result["periods"] == 8
    assert result["measures"]["total"]["decisions_rejected"] == 0


# The order of 4 monitors in period 1 cannot be made from an empty start and is lost
# at 4 * 10; no later period has demand, so nothing bought can be sold, and the first
# window values no stock at its end above its salvage value.
@pytest.mark.slow
def test_the_buffered_rolling_optimizer_buys_nothing_for_withdrawn_demand():
    manifest, scenario = withdrawn_demand_bodies()
    decisions: list[JsonObject] = []
    with benchmark_client() as client:
        stored = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        run = benchmark.start_run(client, scenario_id, 0)
        check = partial(benchmark.create_check, client, run["id"])
        optimizer = buffered_rolling_optimizer(check)

        def agent(description: JsonObject, observation: JsonObject) -> list[JsonObject]:
            decided = optimizer(description, observation)
            decisions.extend(decided)
            return decided

        result = benchmark.play_run(client, run, agent)

    assert [decision for decision in decisions if decision["kind"] == "buy"] == []
    assert result["profit"] == Decimal(-40)
    assert optimizer.relaxed_program_value == pytest.approx(-40)


# Seed 0 of the hidden uniform demand from 0 to 10 at the factor 0.0001 orders 0.001
# in periods 1, 2, 4 and 7 and nothing in the six other periods to 10. Divided by the
# factor they are 10, 10, 0, 10, 0, 0, 10, 0, 0, 0, a mean of 4, so the planning input
# of period 10 expects 4 monitors in period 11, at the factor 1.
@pytest.mark.slow
def test_the_hidden_demand_of_period_11_is_the_mean_of_10_observed_periods():
    manifest, scenario = intermittent_demand_bodies()
    source = expected_planning_source(
        "lead_chain", "expected", LEAN_TERMINAL_VALUE_FACTOR
    )
    quantities: list[Decimal] = []
    plannings: list[PlanningInput] = []

    def agent(description: JsonObject, observation: JsonObject) -> list[JsonObject]:
        arrived = [
            Decimal(order["quantity"])
            for order in observation["customer_orders"]
            if order["arrival"] == observation["period"]
        ]
        quantities.append(sum(arrived, Decimal(0)))
        plannings.append(source(description, observation))
        return []

    with benchmark_client() as client:
        stored = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        run = benchmark.start_run(client, scenario_id, 0)
        customers = run["description"]["manifest"]["customers"]
        assert "demand" not in customers["distributor"]["products"]["monitor"]
        benchmark.play_run(client, run, agent)

    assert quantities[:10] == [
        Decimal("0.001") if period in (1, 2, 4, 7) else Decimal(0)
        for period in range(1, 11)
    ]
    expected = [
        order.open_quantity
        for order in plannings[9].customer_orders
        if order.arrival == 11
    ]
    assert expected == [Decimal("4.000")]


# A scenario that hides nothing shows the informed optimizer what the rolling one sees.
def test_the_informed_optimizer_makes_the_profit_of_the_rolling_one_if_nothing_hides():
    rolling, _ = played_on_the_plain_tiny_factory(rolling_optimizer)

    informed = played_by_the_informed_optimizer(
        plain_tiny_manifest(), plain_tiny_scenario(), Decimal("1.01")
    )

    assert informed["profit"] == rolling["profit"]


def test_the_informed_optimizer_plays_a_hidden_yield_to_the_end_at_both_factors():
    manifest, scenario = hidden_yield_bodies()

    results = [
        played_by_the_informed_optimizer(manifest, scenario, factor)
        for factor in (Decimal("1.01"), Decimal("1.2"))
    ]

    assert [result["periods"] for result in results] == [3, 3]
    assert [
        result["measures"]["total"]["decisions_rejected"] for result in results
    ] == [0, 0]


def test_the_rolling_optimizer_keeps_one_integer_solve_per_period():
    manifest = plain_tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["min_quantity"] = "10.000"
    with benchmark_client() as client:
        stored = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored['id']}/scenarios"
        scenario = benchmark.send(client, "POST", path, plain_tiny_scenario())
        run = benchmark.start_run(client, scenario["id"], 0)
        check = partial(benchmark.create_check, client, run["id"])
        optimizer = rolling_optimizer(check)
        benchmark.play_run(client, run, optimizer)

    assert [solve.period for solve in optimizer.solves] == [1, 2, 3]
    assert optimizer.dropped == []


# In period 1 the window is period 1 alone and its expected use counts periods 2 and
# 3 of demand: 8 monitors, 16 boards and 32 chips. The 16 chips make 8 boards, the 8
# boards 4 monitors and 32 chips are bought, costing 8 + 8 + 16 = 32; order-1-1 is
# lost at 4 * 10 = 40. At the end 32 chips, 8 boards and 4 monitors are worth 1.01
# times their cost: 32 * 0.505 + 8 * 2.02 + 4 * 6.06 = 56.56, so the value is
# 56.56 - 72.
def test_the_myopic_optimizer_plays_the_plain_tiny_factory_to_the_end():
    result, optimizer = played_on_the_plain_tiny_factory(myopic_optimizer)

    assert result["periods"] == 3
    assert result["measures"]["total"]["decisions_rejected"] == 0
    assert optimizer.relaxed_program_value == pytest.approx(-15.44)


def test_the_myopic_optimizer_keeps_one_integer_solve_per_period():
    manifest = plain_tiny_manifest()
    manifest["suppliers"]["chip-maker"]["catalogue"]["chip"]["min_quantity"] = "10.000"
    with benchmark_client() as client:
        stored = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored['id']}/scenarios"
        scenario = benchmark.send(client, "POST", path, plain_tiny_scenario())
        run = benchmark.start_run(client, scenario["id"], 0)
        check = partial(benchmark.create_check, client, run["id"])
        optimizer = myopic_optimizer(check)
        benchmark.play_run(client, run, optimizer)

    assert [solve.period for solve in optimizer.solves] == [1, 2, 3]


@pytest.mark.property
@settings(max_examples=example_count(25))
@given(linear_factories().filter(lambda factory: factory[1]["horizon"] <= 6), seeds)
def test_every_limited_optimizer_plays_to_the_end_and_reports_the_decisions_it_changed(
    factory: tuple[dict[str, Any], dict[str, Any]], seed: int
):
    horizon = factory[1]["horizon"]
    with benchmark_client() as client:
        manifest = benchmark.send(client, "POST", "/manifests", factory[0])
        path = f"/manifests/{manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, factory[1])["id"]
        played: list[tuple[dict[str, Any], Optimizer]] = []
        for make_optimizer in (
            full_horizon_optimizer,
            rolling_optimizer,
            buffered_rolling_optimizer,
            aligned_optimizer,
            myopic_optimizer,
        ):
            run = benchmark.start_run(client, scenario_id, seed)
            optimizer = make_optimizer(
                partial(benchmark.create_check, client, run["id"])
            )
            played.append((benchmark.play_run(client, run, optimizer), optimizer))

    for result, optimizer in played:
        assert result["periods"] == horizon
        for dropped in optimizer.dropped:
            assert 1 <= dropped["period"] <= horizon
            assert dropped["reason"]
        for fitted in optimizer.fitted:
            assert 0 <= fitted["after"] < fitted["before"]
