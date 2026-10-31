import copy
import json
from decimal import Decimal
from typing import Any

import pytest
from factories import (
    FactoryBodies,
    benchmark_client,
    decide,
    draw_world_of_bodies,
    drawn_run,
    example_count,
    plain_tiny_manifest,
    plain_tiny_scenario,
    seeds,
    small_factories,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.api.services.examples import EXAMPLES
from factory_simulator.benchmark import client as benchmark
from factory_simulator.engine import build_state, start_period
from stress.controls import (
    INFORMATION_CONTROLS,
    InformationControl,
    build_control_content,
    build_controls,
    build_differing_keys,
    build_forecast_shocks,
)


def library_scenario(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / "scenarios" / f"{name}.json").read_bytes())


def control_named(name: str) -> InformationControl:
    return next(control for control in INFORMATION_CONTROLS if control.control == name)


def library() -> dict[str, dict[str, Any]]:
    return {
        file.stem: json.loads(file.read_bytes())
        for file in (EXAMPLES / "scenarios").glob("*.json")
    }


# The plain tiny scenario with forecasts one period ahead without noise, hidden demand
# and duration of disruptions, and a demand shock of factor 2 in periods 2 and 3
# announced 1 period ahead.
def with_a_hidden_demand_shock() -> dict[str, Any]:
    forecast = {
        "target": "all",
        "periods_ahead": 1,
        "noise": "0.0000",
        "noise_growth": "0.0000",
    }
    shock = {
        "kind": "demand_shock",
        "target": ["monitor"],
        "start": 2,
        "duration": 2,
        "notice": 1,
        "factor": "2.0000",
    }
    return plain_tiny_scenario() | {
        "forecasts": [forecast],
        "disruptions": [shock],
        "hidden": ["customers.products.demand", "disruptions.duration"],
    }


# The forecast of the next period of the monitor in each period of a run of no
# decisions on seed 0, while it has one.
def forecasts_of_monitor(scenario: dict[str, Any]) -> list[Decimal]:
    world = draw_world_of_bodies(plain_tiny_manifest(), scenario)
    state = build_state(world)
    quantities: list[Decimal] = []
    for _ in range(scenario["horizon"]):
        started = start_period(state, world)
        assert started.observation is not None
        quantities += [
            forecast.quantity
            for forecast in started.observation.forecasts["distributor/monitor"]
        ]
        state = decide(started, world, [])
    return quantities


# Forecasts of every customer product one and two periods ahead, and hidden demand. A
# twin shows the forecasts of its scenario when the refusal of build_controls keeps it.
def with_forecasts_and_hidden_demand(scenario: dict[str, Any]) -> dict[str, Any]:
    forecast = {
        "target": "all",
        "periods_ahead": min(2, scenario["horizon"]),
        "noise": "0.1000",
        "noise_growth": "0.0500",
    }
    hidden = sorted({*scenario["hidden"], "customers.products.demand"})
    return scenario | {"forecasts": [forecast], "hidden": hidden}


# The descriptions and observations of a run of no decisions on seed 0, with its world.
def seen_over_http(
    manifest: dict[str, Any], scenario: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    descriptions: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []

    def agent(
        description: dict[str, Any], observation: dict[str, Any]
    ) -> list[dict[str, Any]]:
        descriptions.append(description)
        observations.append(observation)
        return []

    with benchmark_client() as client:
        stored_manifest = benchmark.send(client, "POST", "/manifests", manifest)
        path = f"/manifests/{stored_manifest['id']}/scenarios"
        scenario_id = benchmark.send(client, "POST", path, scenario)["id"]
        run = benchmark.start_run(client, scenario_id, 0)
        benchmark.play_run(client, run, agent)
        world = benchmark.read_world(client, run["id"])
    return descriptions, observations, world


def test_the_control_of_forecasts_keeps_its_hidden_demand_and_drops_its_forecasts():
    forecasts = library_scenario("forecasts")

    control = build_control_content(
        forecasts, control_named("forecasts-without-forecasts")
    )

    assert "forecasts" not in control
    assert control["hidden"] == ["customers.products.demand"]
    assert control["name"] == "forecasts-without-forecasts"
    assert {key: value for key, value in control.items() if key != "name"} == {
        key: value
        for key, value in forecasts.items()
        if key not in ("name", "forecasts")
    }


# The visible twin of hidden-groups hides nothing and multiplies demand by 2.5 from
# period 1, as hidden-groups does.
def test_the_visible_twin_of_hidden_groups_keeps_its_demand_factor_of_2_5():
    hidden_groups = library_scenario("hidden-groups")

    control = build_control_content(hidden_groups, control_named("hidden-groups-shown"))

    step = {"kind": "step", "target": "all", "period": 1, "factor": "2.5000"}
    assert control["hidden"] == []
    assert control["demand_shapes"] == hidden_groups["demand_shapes"] == [step]
    assert control | {"hidden": hidden_groups["hidden"]} == hidden_groups | {
        "name": "hidden-groups-shown"
    }


# Notice and supplier-outage have the same two disruptions, announced 4 periods ahead
# in notice and when they start in supplier-outage.
def test_notice_and_supplier_outage_differ_in_the_notice_of_their_disruptions_only():
    differing = build_differing_keys(
        library_scenario("notice"), library_scenario("supplier-outage")
    )

    assert differing == ["notice"]


# Forecasts hides demand and gives forecasts; hidden-groups hides eight groups and
# multiplies demand by 2.5. Each differs from steady-market in two keys.
def test_the_information_scenarios_differ_from_steady_market_in_two_keys():
    steady = library_scenario("steady-market")

    assert build_differing_keys(library_scenario("forecasts"), steady) == [
        "forecasts",
        "hidden",
    ]
    assert build_differing_keys(library_scenario("hidden-groups"), steady) == [
        "demand_shapes",
        "hidden",
    ]


# Forecasts has two controls, without its forecasts and with its demand shown;
# hidden-groups has its visible twin; notice has supplier-outage of the library.
def test_each_information_scenario_gets_controls_that_differ_in_one_treatment():
    scenarios = library()

    controls = build_controls(scenarios, ["forecasts", "hidden-groups", "notice"])

    assert [
        (control.scenario, control.treatment, control.control)
        for control, _ in controls
    ] == [
        ("forecasts", "forecasts", "forecasts-without-forecasts"),
        ("forecasts", "hidden", "forecasts-shown"),
        ("hidden-groups", "hidden", "hidden-groups-shown"),
        ("notice", "notice", "supplier-outage"),
    ]
    assert controls[3][1] == scenarios["supplier-outage"]
    for control, content in controls:
        assert build_differing_keys(scenarios[control.scenario], content) == [
            control.treatment
        ]


def test_a_scenario_without_information_treatment_gets_no_control():
    assert build_controls(library(), ["steady-market", "supplier-outage"]) == []


def test_a_control_that_differs_in_more_than_its_treatment_is_refused():
    scenarios = library()
    outage = copy.deepcopy(scenarios["supplier-outage"])
    outage["disruptions"][0]["strength"] = "0.5000"

    with pytest.raises(ValueError) as refused:
        build_controls(scenarios | {"supplier-outage": outage}, ["notice"])

    assert str(refused.value) == (
        "the control supplier-outage of notice differs in disruptions, not in notice "
        "only"
    )


def test_a_visible_twin_whose_forecasts_would_hold_a_hidden_demand_shock_is_refused():
    scenario = with_a_hidden_demand_shock()
    twin = build_control_content(scenario, control_named("forecasts-shown"))

    assert forecasts_of_monitor(scenario) == [Decimal("4.000"), Decimal("4.000")]
    assert forecasts_of_monitor(twin) == [Decimal("8.000"), Decimal("8.000")]
    with pytest.raises(ValueError) as refused:
        build_controls({"forecasts": scenario}, ["forecasts"])

    assert str(refused.value) == (
        "the control forecasts-shown of forecasts holds other demand shocks in its "
        "forecasts"
    )


# The shock announced 1 period ahead in notice and when it starts in supplier-outage.
def test_a_notice_pair_whose_forecasts_hold_another_demand_shock_is_refused():
    notice: dict[str, Any] = with_a_hidden_demand_shock() | {"hidden": []}
    [shock] = notice["disruptions"]
    outage: dict[str, Any] = notice | {"disruptions": [shock | {"notice": 0}]}

    assert forecasts_of_monitor(notice)[0] == Decimal("8.000")
    assert forecasts_of_monitor(outage)[0] == Decimal("4.000")
    with pytest.raises(ValueError) as refused:
        build_controls({"notice": notice, "supplier-outage": outage}, ["notice"])

    assert str(refused.value) == (
        "the control supplier-outage of notice holds other demand shocks in its "
        "forecasts"
    )


def test_a_hidden_duration_keeps_its_twin_without_forecasts_or_without_a_demand_shock():
    scenario = with_a_hidden_demand_shock()
    without_forecasts: dict[str, Any] = scenario | {"forecasts": []}
    without_shock: dict[str, Any] = scenario | {"disruptions": []}

    hidden_groups = build_controls(
        {"hidden-groups": without_forecasts}, ["hidden-groups"]
    )
    forecasts = build_controls({"forecasts": without_shock}, ["forecasts"])

    assert [control.control for control, _ in hidden_groups] == ["hidden-groups-shown"]
    assert [control.control for control, _ in forecasts] == [
        "forecasts-without-forecasts",
        "forecasts-shown",
    ]


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(small_factories(), seeds, st.sampled_from(["forecasts", "hidden"]), st.data())
def test_a_control_draws_the_physical_world_of_its_scenario_and_runs_it_alike(
    factory: FactoryBodies, seed: int, treatment: str, data: st.DataObject
):
    manifest, scenario = factory
    scenario = with_forecasts_and_hidden_demand(scenario)
    control = InformationControl(
        scenario="treated", treatment=treatment, control="control"
    )
    content = build_control_content(scenario, control)
    kept = build_forecast_shocks(scenario) == build_forecast_shocks(content)
    world, steps = drawn_run((manifest, scenario), seed, data.draw)
    twin = draw_world_of_bodies(manifest, content, seed=seed)

    assert twin.demand == world.demand
    assert twin.yields == world.yields
    assert twin.deliveries == world.deliveries
    assert twin.breakdowns == world.breakdowns
    assert twin.prices == world.prices
    assert twin.disruptions == world.disruptions
    assert dict(twin.parameters) == dict(world.parameters)
    state = build_state(twin)
    shown: list[bool] = []
    for decided, decisions, closed in steps:
        started = start_period(state, twin)
        assert started.observation is not None and decided.observation is not None
        shown.append(bool(decided.observation.forecasts))
        if treatment == "forecasts":
            assert started.observation.forecasts == {}
        elif kept:
            assert started.observation.forecasts == decided.observation.forecasts
        state = decide(started, twin, decisions)
        assert state.ledger == closed.ledger
        assert state.period_events == closed.period_events
        assert state.measures == closed.measures
    if treatment == "forecasts":
        assert any(shown)
        assert twin.scenario.hidden == world.scenario.hidden
    else:
        assert twin.scenario.hidden == ()
        assert "customers.products.demand" in world.scenario.hidden


# The plain tiny scenario with hidden demand and forecasts two periods ahead, and its
# control without forecasts: over 3 periods only the forecasts of the description, of
# the observations and of the world differ.
@pytest.mark.slow
def test_the_control_of_forecasts_shows_no_forecast_and_draws_the_same_world():
    scenario = plain_tiny_scenario() | {
        "hidden": ["customers.products.demand"],
        "forecasts": [
            {
                "target": "all",
                "periods_ahead": 2,
                "noise": "0.1000",
                "noise_growth": "0.0500",
            }
        ],
    }
    control = build_control_content(
        scenario, control_named("forecasts-without-forecasts")
    )

    treated = seen_over_http(plain_tiny_manifest(), scenario)
    untreated = seen_over_http(plain_tiny_manifest(), control)

    treated_descriptions, treated_observations, treated_world = treated
    descriptions, observations, world = untreated
    assert treated_descriptions[0]["scenario"]["forecasts"] == [
        {
            "target": "all",
            "periods_ahead": 2,
            "noise": Decimal("0.1000"),
            "noise_growth": Decimal("0.0500"),
        }
    ]
    assert descriptions[0]["scenario"]["forecasts"] == []
    assert [
        description | {"scenario": description["scenario"] | {"forecasts": []}}
        for description in treated_descriptions
    ] == descriptions
    assert [len(observation["forecasts"]) for observation in treated_observations] == [
        1,
        1,
        1,
    ]
    assert [observation["forecasts"] for observation in observations] == [{}] * 3
    assert [
        observation | {"forecasts": {}} for observation in treated_observations
    ] == observations
    assert (world["forecasts"], world["forecast_errors"]) == ({}, {})
    assert treated_world | {"forecasts": {}, "forecast_errors": {}} == world
