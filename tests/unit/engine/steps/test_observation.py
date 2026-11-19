from dataclasses import asdict, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest
from factories import (
    FactoryBodies,
    RunStep,
    closed_period,
    decide,
    draw_world_of_bodies,
    drawn_run,
    drawn_runs,
    example_count,
    monitor_world,
    observation_in,
    produce,
    seeds,
    ship_decision,
    small_factories,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from factory_simulator.engine import (
    Decisions,
    Event,
    Observation,
    Outcome,
    StartCustomerOrder,
    World,
    advance_period,
    build_state,
    is_active,
    start_period,
)

OUTAGE = {
    "kind": "supplier_outage",
    "target": ["chip-maker"],
    "start": 10,
    "duration": 3,
    "strength": "0.5000",
    "notice": 2,
}


def cut(strength: str) -> dict[str, Any]:
    return {
        "kind": "capacity_cut",
        "target": ["line-1"],
        "start": 1,
        "duration": 1,
        "strength": strength,
    }


def line_world(*disruptions: dict[str, Any]) -> World:
    scenario = tiny_scenario()
    scenario["disruptions"] = list(disruptions)
    return draw_world_of_bodies(tiny_manifest(), scenario)


def first_observation(world: World, condition: str = "1") -> Observation:
    state = build_state(world)
    state = replace(state, condition=MappingProxyType({"line-1": Decimal(condition)}))
    observation = start_period(state, world).observation
    assert observation is not None
    return observation


def hours_of_line(
    world: World, condition: str = "1"
) -> tuple[Decimal, Decimal, Decimal]:
    line = first_observation(world, condition).lines["line-1"]
    return (
        line.condition,
        line.regular_hours_available,
        line.repair_hours_available,
    )


def outage_world(hidden: list[str] | None = None) -> World:
    scenario = tiny_scenario() | {"horizon": 14, "disruptions": [OUTAGE]}
    return draw_world_of_bodies(tiny_manifest(), scenario | {"hidden": hidden or []})


def shown_in(world: World, period: int) -> list[str]:
    return [disruption.id for disruption in observation_in(world, period).disruptions]


# The events with each reference to a disruption under the name it maps to.
def renamed(events: tuple[Event, ...], names: dict[str, str]) -> tuple[Event, ...]:
    return tuple(
        {
            key: names.get(value, value)
            if key == "reference" and isinstance(value, str)
            else value
            for key, value in event.items()
        }
        for event in events
    )


# The observation with no notice and each disruption under the name it maps to.
def as_shown(observation: Observation, names: dict[str, str]) -> Observation:
    shown = tuple(
        replace(disruption, id=names.get(disruption.id, disruption.id), notice=0)
        for disruption in observation.disruptions
    )
    events = renamed(observation.events, names)
    return replace(observation, disruptions=shown, events=events)


def test_a_capacity_cut_takes_its_share_of_the_hours_a_line_shows():
    world = line_world(cut("0.5000"))

    assert hours_of_line(world, "0.8") == (Decimal("0.8"), Decimal("4"), Decimal("5"))


def test_the_hours_a_line_shows_are_rounded_down_to_3_places():
    world = line_world()

    assert hours_of_line(world, "0.123456789012")[1:] == (
        Decimal("1.234"),
        Decimal("10"),
    )


def test_two_capacity_cuts_multiply_the_repair_hours_a_line_shows():
    world = line_world(cut("0.3333"), cut("0.3333"))

    assert hours_of_line(world)[2] == Decimal("4.444")


def test_the_next_observation_lists_the_outcome_of_a_rejected_ship():
    world = line_world()
    scenario = replace(
        world.scenario,
        start=replace(
            world.scenario.start,
            stock={"main": {"monitor": Decimal(40)}},
            customer_orders=(
                StartCustomerOrder(
                    customer="distributor",
                    product="monitor",
                    quantity=Decimal(50),
                    due=1,
                ),
            ),
        ),
    )
    world = replace(world, scenario=scenario)
    state = start_period(build_state(world), world)
    ship = ship_decision("order-0-1", "50", warehouse="main")

    closed = advance_period(state, world, Decisions(period=1, decisions=(ship,)))
    observation = start_period(closed, world).observation

    assert observation is not None
    assert observation.outcomes == (
        Outcome(
            decision_id="1-1",
            decision=ship,
            accepted=False,
            reason="not_enough_stock",
            asked=Decimal("50.000"),
            available=Decimal("40.000"),
        ),
    )


def test_an_outage_with_notice_is_seen_from_start_less_notice_and_acts_from_start():
    world = outage_world()
    [outage] = world.disruptions

    assert [is_active(outage, period) for period in (9, 10, 12, 13)] == [
        False,
        True,
        True,
        False,
    ]
    assert [shown_in(world, period) for period in (7, 8, 9, 12, 13)] == [
        [],
        ["disruption-1"],
        ["disruption-1"],
        ["disruption-1"],
        [],
    ]


def test_an_outage_with_notice_is_reported_as_started_in_its_start_period():
    world = outage_world()
    state = build_state(world)
    started: list[int] = []
    for period in range(1, 15):
        state = start_period(state, world)
        started += [
            period
            for event in state.period_events
            if event["kind"] == "disruption_started"
        ]
        state = decide(state, world, [])

    assert started == [10]


def test_the_observation_shows_production_with_6_keys():
    world = monitor_world()

    made = closed_period(world, 3, {3: [produce("monitor", "10")]})
    period_4 = start_period(made, world)

    assert period_4.observation is not None
    [seen] = period_4.observation.production
    assert asdict(seen) == {
        "id": "make-3-1",
        "line": "line-1",
        "item": "monitor",
        "recipe": "standard",
        "started": Decimal("10.000"),
        "ready": 4,
    }


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(drawn_runs())
def test_no_observation_holds_the_price_of_another_period(
    run: tuple[World, list[RunStep]],
):
    world, steps = run

    for decided, _, _ in steps:
        observation = decided.observation
        assert observation is not None
        seen = {
            f"{supplier_id}/{material_id}": price
            for supplier_id, entries in observation.prices.items()
            for material_id, price in entries.items()
        }
        assert seen == {
            pair: prices[observation.period - 1]
            for pair, prices in world.prices.items()
        }


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_a_notice_changes_only_what_is_seen_before_the_start(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    assume(scenario["disruptions"])
    position = data.draw(
        st.integers(min_value=0, max_value=len(scenario["disruptions"]) - 1)
    )
    written = scenario["disruptions"][position]
    notice = data.draw(st.integers(min_value=0, max_value=written["start"] - 1))
    world, steps = drawn_run(factory, seed, data.draw)
    scenario["disruptions"][position] = written | {"notice": notice}
    other = draw_world_of_bodies(manifest, scenario, seed=seed)
    start = written["start"]
    window = range(start - max(notice, written["notice"]), start)
    # A notice may number the written disruptions in another order; each name of
    # the variant maps to the name of the same position in the list.
    count = len(scenario["disruptions"])
    names = {
        changed.id: kept.id
        for changed, kept in zip(
            other.disruptions[:count], world.disruptions[:count], strict=True
        )
    }

    state = build_state(other)
    for decided, decisions, closed in steps:
        seen = start_period(state, other)
        state = decide(seen, other, decisions)
        assert seen.observation is not None and decided.observation is not None
        before = as_shown(decided.observation, {})
        after = as_shown(seen.observation, names)
        if decided.period not in window:
            assert before == after
        else:
            assert replace(before, disruptions=(), forecasts={}) == replace(
                after, disruptions=(), forecasts={}
            )
        assert state.ledger == closed.ledger
        assert renamed(state.events, names) == renamed(closed.events, {})
        assert state.outcomes == closed.outcomes
        assert state.measures == closed.measures
    if written["kind"] != "demand_shock":
        assert other.forecasts == world.forecasts
