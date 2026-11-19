from dataclasses import replace
from decimal import ROUND_FLOOR, Decimal
from types import MappingProxyType
from typing import Any

import pytest
from factories import (
    FactoryBodies,
    draw_world_of_bodies,
    example_count,
    outcome_fields,
    produce,
    repair,
    seeds,
    small_factories,
    submission,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.engine import (
    State,
    World,
    advance_period,
    build_state,
    start_period,
)

shares = st.decimals(min_value=0, max_value=1, places=4)


# The fields of every outcome of a closed state, their decisions left out.
def every_outcome(state: State) -> list[dict[str, Any]]:
    return [outcome_fields(outcome) for outcome in state.outcomes]


def repair_line(condition: str, **terms: str) -> tuple[World, State]:
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(
        {
            "repair_time": "40.000",
            "repair_cost": "1000.0000",
            "repair_limit": "0.5000",
        }
        | terms
    )
    scenario = tiny_scenario()
    scenario["start"]["condition"] = {"line-1": condition}
    world = draw_world_of_bodies(manifest, scenario)
    return world, start_period(build_state(world), world)


def rejected(*reasons: tuple[str, str, str, str]) -> list[dict[str, Any]]:
    return [
        {
            "decision_id": decision_id,
            "accepted": False,
            "reason": reason,
            "asked": Decimal(asked),
            "available": Decimal(available),
        }
        for decision_id, reason, asked, available in reasons
    ]


def repair_factory() -> FactoryBodies:
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(
        repair_time="10.000", repair_cost="1000.0000", repair_limit="0.5000"
    )
    return manifest, tiny_scenario()


def test_a_stopped_line_is_repaired_and_produces_again_the_next_period():
    world, state = repair_line("0")

    closed = advance_period(state, world, submission(1, [repair("0.2000")]))
    following = start_period(closed, world)
    next_closed = advance_period(
        following, world, submission(2, [produce("monitor", "4.002")])
    )

    assert every_outcome(closed) == [
        {"decision_id": "1-1", "accepted": True, "reference": "repair-1-1"}
    ]
    assert [
        (row.kind, row.amount, row.reference)
        for row in closed.ledger
        if row.step == "execute_decisions"
    ] == [("repair_cost", Decimal("-200"), "repair-1-1")]
    assert closed.condition["line-1"] == Decimal("0.2")
    assert every_outcome(next_closed)[0]["available"] == Decimal("2.000")


def test_a_repair_stays_within_the_regular_hours_under_a_capacity_cut():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(
        repair_time="40.000", repair_cost="1000.0000", repair_limit="0.5000"
    )
    scenario = tiny_scenario()
    scenario["start"]["condition"] = {"line-1": "0.5000"}
    scenario["disruptions"] = [
        {
            "kind": "capacity_cut",
            "target": ["line-1"],
            "start": 1,
            "duration": 2,
            "strength": "0.5000",
        }
    ]
    world = draw_world_of_bodies(manifest, scenario)
    state = start_period(build_state(world), world)

    closed = advance_period(state, world, submission(1, [repair("0.2000")]))

    [outcome] = closed.outcomes
    assert (outcome.reason, outcome.asked, outcome.available) == (
        "not_enough_hours",
        Decimal("8.000"),
        Decimal("5.000"),
    )


# 0.1 <= 1 passes the repair limit and 0.1 <= 1 - 0.5 the full condition; the repair
# needs 0.1000 * 1.000 = 0.1 hours, and the cut leaves 10 * (1 - 1) = 0.
def test_a_repair_finds_no_hours_under_a_capacity_cut_of_strength_1():
    scenario = tiny_scenario()
    scenario["start"]["condition"] = {"line-1": "0.5000"}
    scenario["disruptions"] = [
        {
            "kind": "capacity_cut",
            "target": ["line-1"],
            "start": 1,
            "duration": 1,
            "strength": "1.0000",
        }
    ]
    world = draw_world_of_bodies(tiny_manifest(), scenario)
    state = start_period(build_state(world), world)

    closed = advance_period(state, world, submission(1, [repair("0.1000")]))

    [outcome] = closed.outcomes
    assert (outcome.reason, outcome.asked, outcome.available) == (
        "not_enough_hours",
        Decimal("0.1"),
        Decimal("0"),
    )


def test_a_repair_over_full_condition_is_rejected_with_its_numbers():
    world, state = repair_line("0.9")

    closed = advance_period(state, world, submission(1, [repair("0.2000")]))

    assert every_outcome(closed) == rejected(
        ("1-1", "over_full_condition", "0.2000", "0.1000")
    )


def test_repairs_over_the_repair_limit_in_one_period_are_rejected():
    world, state = repair_line("0", repair_time="1.000")

    closed = advance_period(
        state, world, submission(1, [repair("0.3000"), repair("0.3000")])
    )

    assert every_outcome(closed)[1:] == rejected(
        ("1-2", "over_repair_limit", "0.3000", "0.2000")
    )


def test_a_repair_over_the_hours_of_the_line_is_rejected_with_its_numbers():
    world, state = repair_line("0.5")

    closed = advance_period(state, world, submission(1, [repair("0.3000")]))

    assert every_outcome(closed) == rejected(
        ("1-1", "not_enough_hours", "12.000", "10.000")
    )


def test_a_repair_of_an_unknown_line_is_rejected_without_numbers():
    world, state = repair_line("0.5")

    closed = advance_period(
        state, world, submission(1, [repair("0.1000", line="line-9")])
    )

    assert every_outcome(closed) == [
        {"decision_id": "1-1", "accepted": False, "reason": "unknown_line"}
    ]


def test_a_repair_runs_before_produce_and_takes_regular_hours():
    world, state = repair_line("0.9")
    stocked = replace(
        state,
        stock=MappingProxyType(
            {
                "main": MappingProxyType(
                    dict(state.stock["main"]) | {"board": Decimal(30)}
                )
            }
        ),
    )
    decisions = [produce("monitor", "13"), repair("0.1000"), produce("monitor", "12")]

    closed = advance_period(stocked, world, submission(1, decisions))

    assert every_outcome(closed) == [
        {"decision_id": "1-2", "accepted": True, "reference": "repair-1-2"},
        *rejected(("1-1", "not_enough_hours", "6.500", "6.000")),
        {"decision_id": "1-3", "accepted": True, "reference": "make-1-3"},
    ]


def test_a_breakdown_takes_its_loss_of_condition_with_an_event():
    _, state = repair_line("0.9", breakdown_chance="1.0000", breakdown_loss="0.3000")

    assert state.condition["line-1"] == Decimal("0.63")
    assert [
        dict(event) for event in state.period_events if event["kind"] == "breakdown"
    ] == [
        {
            "kind": "breakdown",
            "step": "apply_events",
            "reference": "line-1",
            "line": "line-1",
            "loss": Decimal("0.3"),
            "condition": Decimal("0.63"),
        }
    ]


def test_a_breakdown_rounds_the_condition_down_to_12_places():
    world, _ = repair_line("1", breakdown_chance="1.0000", breakdown_loss="0.3333")
    condition = MappingProxyType({"line-1": Decimal("0.800000000001")})

    state = start_period(replace(build_state(world), condition=condition), world)

    assert state.condition["line-1"] == Decimal("0.533360000000")


def test_a_breakdown_with_loss_1_stops_new_production():
    world, state = repair_line("1", breakdown_chance="1.0000", breakdown_loss="1.0000")

    closed = advance_period(state, world, submission(1, [produce("board", "0.001")]))

    assert state.condition["line-1"] == 0
    assert every_outcome(closed) == rejected(
        ("1-1", "not_enough_hours", "0.0001", "0.000")
    )


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(st.one_of(small_factories(), st.builds(repair_factory)), seeds, st.data())
def test_a_line_at_any_condition_can_be_repaired_when_hours_allow(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world = draw_world_of_bodies(*factory, seed=seed)
    state = build_state(world)
    conditions = {
        line_id: data.draw(st.one_of(st.just(Decimal(0)), shares))
        for line_id in state.condition
    }
    started = replace(state, condition=MappingProxyType(conditions))
    decided = start_period(started, world)
    assert decided.observation is not None

    for line_id, hours in decided.observation.lines.items():
        path = f"lines.{line_id}"
        repair_time = world.parameters[f"{path}.repair_time"]
        condition = decided.condition[line_id]
        most = min(
            world.parameters[f"{path}.repair_limit"],
            1 - condition,
            hours.repair_hours_available / repair_time if repair_time else Decimal(1),
        ).quantize(Decimal("0.0001"), rounding=ROUND_FLOOR)
        if most <= 0:
            continue
        amount = data.draw(
            st.decimals(min_value=Decimal("0.0001"), max_value=most, places=4)
        )
        closed = advance_period(
            decided, world, submission(1, [repair(str(amount), line=line_id)])
        )

        wear = world.parameters[f"{path}.wear_per_period"]
        restored = (condition * (1 - wear) + amount).quantize(
            Decimal("0.000000000001"), rounding=ROUND_FLOOR
        )
        assert [outcome.accepted for outcome in closed.outcomes] == [True]
        assert closed.measures["repair_hours"][path] == amount * repair_time
        assert closed.condition[line_id] == restored
