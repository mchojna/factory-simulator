from collections import Counter
from decimal import Decimal
from typing import Any

import pytest
from factories import (
    FactoryBodies,
    closed_period,
    decide,
    draw_world_of_bodies,
    drawn_run,
    example_count,
    mixed_decision_lists,
    numbered_outcomes,
    plan_world,
    produce,
    produce_lists,
    seeds,
    small_factories,
    started,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from factory_simulator.engine import (
    Cancel,
    Decisions,
    Produce,
    State,
    World,
    build_state,
    start_period,
)
from factory_simulator.engine.steps.execution import execute_decisions


# The stock, cash, lines, orders, production and transfers of a state, their
# identifiers left out.
def holdings_without_identifiers(state: State) -> tuple[object, ...]:
    return (
        state.stock,
        state.cash,
        state.condition,
        state.set_for,
        state.customer_orders,
        sorted(
            (
                order.supplier,
                order.material,
                order.warehouse,
                order.arrival,
                order.open_quantity,
            )
            for order in state.supplier_orders
        ),
        sorted(
            (made.line, made.item, made.recipe, made.started, made.start, made.ready)
            for made in state.production
        ),
        sorted(
            (
                transfer.item,
                transfer.quantity,
                transfer.source,
                transfer.destination,
                transfer.arrival,
            )
            for transfer in state.transfers
        ),
    )


def makes(world: World, decision: dict[str, Any]) -> bool:
    line = world.factory.lines.get(decision["line"])
    return line is not None and decision["item"] in line.items


# Whether a decision acts the same in both runs. Identifiers of supplier orders and
# plans made from the period a plan first runs differ between them, and the plans under
# test exist in one run only. A plan made later that starts while they run would run
# before the produce that stands for a plan in the run without plans.
def same_in_both_runs(
    decision: dict[str, Any], plan_ids: list[str], period: int, starts: list[int]
) -> bool:
    if decision["kind"] == "produce":
        return not period < decision.get("start", period) <= max(starts)
    if decision["kind"] != "cancel":
        return True
    order = str(decision["order"])
    return order not in plan_ids and int(order.split("-")[1]) < min(starts)


def test_a_plan_runs_first_in_its_start_period_and_its_outcome_comes_first():
    decisions = {2: [produce("board", "10", start=4)], 4: [produce("board", "10")]}

    state = closed_period(plan_world(), 4, decisions)

    assert numbered_outcomes(state) == [
        ("2-1", True, "make-2-1", None, None, None),
        ("4-1", False, None, "not_enough_hours", Decimal("6.000"), Decimal("4.000")),
    ]
    assert state.plans == ()


def test_plans_starting_in_one_period_run_by_identifier():
    decisions = {
        2: [produce("board", "1"), produce("board", "1", start=5)],
        3: [produce("board", "1", start=5)],
    }

    state = closed_period(plan_world(), 5, decisions)

    assert [outcome.reference for outcome in state.outcomes] == ["make-2-2", "make-3-1"]


def test_a_plan_without_its_inputs_at_its_start_is_rejected_then():
    world = plan_world(chips="10")
    decisions = {2: [produce("board", "10", start=3)]}

    state = closed_period(world, 3, decisions)
    following = start_period(state, world)

    assert numbered_outcomes(state)[0] == (
        "2-1",
        False,
        None,
        "not_enough_input",
        Decimal("20.000"),
        Decimal("10.000"),
    )
    assert following.observation is not None
    seen = following.observation.outcomes[0]
    assert (
        seen.decision_id,
        seen.accepted,
        seen.reason,
        seen.asked,
        seen.available,
    ) == (
        "2-1",
        False,
        "not_enough_input",
        Decimal("20.000"),
        Decimal("10.000"),
    )


def test_a_plan_on_a_line_broken_down_before_its_start_has_no_hours():
    breakdown = {
        "kind": "line_breakdown",
        "target": ["line-1"],
        "start": 3,
        "loss": "1",
    }
    world = plan_world(disruptions=[breakdown])

    state = closed_period(world, 3, {2: [produce("board", "1", start=3)]})

    # A loss of 1 leaves condition 0, so 0 hours; 1 board needs 0.600 hours.
    assert numbered_outcomes(state) == [
        ("2-1", False, None, "not_enough_hours", Decimal("0.600"), Decimal("0.000"))
    ]
    assert state.plans == ()


def test_a_plan_that_starts_after_later_production_keeps_production_by_identifier():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"]["items"]["board"]["lead_time"] = 3
    world = draw_world_of_bodies(manifest, tiny_scenario())
    period_3 = started(
        world, 3, {1: [produce("board", "1", start=3)], 2: [produce("board", "1")]}
    )

    executed = execute_decisions(period_3, world, Decisions(period=3, decisions=()))

    assert [made.id for made in executed.production] == ["make-1-1", "make-2-1"]


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_a_plan_changes_nothing_until_it_runs_like_a_produce_decided_then(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world = draw_world_of_bodies(*factory, seed=seed)
    horizon = world.scenario.horizon
    assume(horizon >= 2)
    first = start_period(build_state(world), world)
    made = produce_lists(world).filter(
        lambda produces: bool(produces) and makes(world, produces[0])
    )
    produces = [
        {
            key: value
            for key, value in data.draw(made)[0].items()
            if key not in ("recipe", "start")
        }
        for _ in range(data.draw(st.integers(min_value=1, max_value=3)))
    ]
    starts = [data.draw(st.integers(min_value=2, max_value=horizon)) for _ in produces]
    others = data.draw(mixed_decision_lists(world, first))
    plans = [
        decision | {"start": start}
        for decision, start in zip(produces, starts, strict=True)
    ]
    planned = decide(first, world, [*others, *plans])
    unplanned = decide(first, world, others)
    plan_ids = [f"make-1-{len(others) + number}" for number in range(1, len(plans) + 1)]

    assert [plan.id for plan in planned.plans] == [
        *(plan.id for plan in unplanned.plans),
        *plan_ids,
    ]
    assert holdings_without_identifiers(planned) == holdings_without_identifiers(
        unplanned
    )
    assert planned.ledger == unplanned.ledger
    assert planned.period_events == unplanned.period_events

    for period in range(2, max(starts) + 1):
        planned = start_period(planned, world)
        unplanned = start_period(unplanned, world)
        later = [
            decision
            for decision in data.draw(mixed_decision_lists(world, planned))
            if same_in_both_runs(decision, plan_ids, period, starts)
        ]
        running = [
            decision
            for decision, start in zip(produces, starts, strict=True)
            if start == period
        ]
        planned = decide(planned, world, later)
        unplanned = decide(unplanned, world, [*running, *later])

        for part, other in zip(
            holdings_without_identifiers(planned),
            holdings_without_identifiers(unplanned),
            strict=True,
        ):
            assert part == other


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_every_plan_ends_exactly_once(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    _, steps = drawn_run(factory, seed, data.draw)
    made: Counter[str] = Counter()
    ended: Counter[str] = Counter()

    for decided, _, closed_state in steps:
        for outcome in closed_state.outcomes:
            decision = outcome.decision
            decided_in = int(outcome.decision_id.split("-")[0])
            if isinstance(decision, Produce) and decided_in < decided.period:
                ended[f"make-{outcome.decision_id}"] += 1
            elif (
                isinstance(decision, Produce)
                and outcome.accepted
                and decision.start != decided.period
            ):
                made[str(outcome.reference)] += 1
            elif (
                isinstance(decision, Cancel)
                and outcome.accepted
                and decision.order.startswith("make-")
            ):
                ended[decision.order] += 1

    assert ended == made
    assert steps[-1][2].plans == ()
