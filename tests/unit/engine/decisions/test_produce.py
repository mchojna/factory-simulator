from dataclasses import replace
from decimal import ROUND_FLOOR, Decimal
from types import MappingProxyType
from typing import Any

import pytest
from factories import (
    FactoryBodies,
    closed_period,
    decide,
    draw_world_of_bodies,
    drawn_run,
    example_count,
    first_period,
    numbered_outcomes,
    outcome_fields,
    outcome_numbers,
    overtime_world,
    plan_world,
    produce,
    produce_lists,
    repair,
    seeds,
    small_factories,
    started,
    started_produces,
    submission,
    tiny_manifest,
    tiny_scenario,
    two_recipe_manifest,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from factory_simulator.engine import (
    Disruption,
    Produce,
    State,
    World,
    advance_period,
    build_state,
    start_period,
)
from factory_simulator.engine.decisions.plant import Plant
from factory_simulator.engine.decisions.produce import missing_hours

OVERTIME = {"overtime_hours": "4.000", "overtime_cost": "45.0000"}


def events_of(state: State, kind: str) -> list[dict[str, Any]]:
    return [dict(event) for event in state.period_events if event["kind"] == kind]


def tiny_started(manifest: dict[str, Any] | None = None) -> tuple[World, State]:
    world = draw_world_of_bodies(manifest or tiny_manifest(), tiny_scenario())
    return world, start_period(build_state(world), world)


def outcomes_of_period(
    state: State, world: World, *decisions: dict[str, Any]
) -> list[dict[str, Any]]:
    closed = advance_period(state, world, submission(state.period, list(decisions)))
    return [outcome_fields(outcome) for outcome in closed.outcomes]


def started_world(factory: FactoryBodies, seed: int) -> tuple[World, State]:
    world = draw_world_of_bodies(*factory, seed=seed)
    return world, start_period(build_state(world), world)


def places(value: Decimal) -> int:
    return max(0, -int(value.normalize().as_tuple().exponent))


def regular_and_overtime_hours(
    state: State, closed: State, world: World
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    regular: dict[str, Decimal] = {}
    overtime: dict[str, Decimal] = {}
    set_for = dict(state.set_for)
    for decision in started_produces(closed):
        line_id, item_id = decision.line, decision.item
        path = f"lines.{line_id}.items.{item_id}"
        hours = decision.quantity * world.parameters[f"{path}.time"]
        used = overtime if decision.overtime else regular
        used[line_id] = used.get(line_id, Decimal(0)) + hours
        terms = world.factory.lines[line_id].items[item_id]
        has_changeover = (
            terms.changeover_time is not None or terms.changeover_cost is not None
        )
        if has_changeover and set_for[line_id] != item_id:
            changeover = world.parameters.get(f"{path}.changeover_time", Decimal(0))
            regular[line_id] = regular.get(line_id, Decimal(0)) + changeover
        set_for[line_id] = item_id
    return regular, overtime


def set_for_after(state: State, closed: State) -> dict[str, str | None]:
    set_for = dict(state.set_for)
    for decision in started_produces(closed):
        set_for[decision.line] = decision.item
    return set_for


def capacity_cut_share(world: World, line_id: str, period: int) -> Decimal:
    share = Decimal(1)
    for disruption in world.disruptions:
        acts = disruption.start <= period < disruption.start + disruption.duration
        cuts_line = line_id in lines_of_target(world, disruption)
        if disruption.kind == "capacity_cut" and acts and cuts_line:
            share *= 1 - disruption.effect
    return share


def lines_of_target(world: World, disruption: Disruption) -> set[str]:
    if disruption.group is not None:
        return set(world.factory.groups[disruption.group[1]].members)
    if disruption.target is not None:
        return set(disruption.target)
    return set(world.factory.lines)


def round_down(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_FLOOR)


def costs(state: State) -> list[tuple[str, Decimal]]:
    kinds = ("production_cost", "overtime_cost")
    return [(row.kind, row.amount) for row in state.ledger if row.kind in kinds]


def two_recipe_world(manifest: dict[str, Any] | None = None) -> World:
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"] = {"chip": "100", "chip-b": "100", "pcb": "50"}
    return draw_world_of_bodies(manifest or two_recipe_manifest(), scenario)


def materials(state: State) -> tuple[Decimal, Decimal, Decimal]:
    stock = state.stock["main"]
    return stock["chip"], stock["chip-b"], stock["pcb"]


def outcome_inputs(state: State) -> list[Any]:
    return [
        (
            outcome.accepted,
            outcome.reason,
            outcome.item,
            outcome.asked,
            outcome.available,
        )
        for outcome in state.outcomes
    ]


def changeover_world(
    set_for: str | None = "board",
    item_terms: dict[str, dict[str, str]] | None = None,
    line_terms: dict[str, str] | None = None,
    **scenario_start: object,
) -> World:
    manifest = tiny_manifest()
    manifest["lines"]["line-1"].update(line_terms or {})
    terms = item_terms or {
        "board": {"changeover_time": "1.000", "changeover_cost": "50.0000"},
        "monitor": {"changeover_time": "1.000", "changeover_cost": "50.0000"},
    }
    for item_id, keys in terms.items():
        manifest["lines"]["line-1"]["items"][item_id].update(keys)
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["board"] = "40"
    if set_for is not None:
        scenario["start"]["set_for"] = {"line-1": set_for}
    scenario["start"].update(scenario_start)
    return draw_world_of_bodies(manifest, scenario)


def changeover_costs(state: State) -> list[tuple[str, Decimal]]:
    return [
        (str(row.reference), row.amount)
        for row in state.ledger
        if row.kind == "changeover_cost"
    ]


def line_measures(state: State) -> dict[str, Decimal | None]:
    return {
        name: state.measures[name]["lines.line-1"]
        for name in ("changeovers", "changeover_hours", "changeover_cost")
    }


def test_a_produce_short_of_an_input_is_rejected_with_the_input_and_its_numbers():
    world, state = tiny_started()

    assert outcomes_of_period(state, world, produce("monitor", "15")) == [
        {
            "decision_id": "1-1",
            "accepted": False,
            "reason": "not_enough_input",
            "item": "board",
            "asked": Decimal("30.000"),
            "available": Decimal("10.000"),
        }
    ]


def test_a_produce_over_the_hours_of_the_line_is_rejected_with_its_numbers():
    world, state = tiny_started()

    assert outcomes_of_period(state, world, produce("monitor", "21")) == [
        {
            "decision_id": "1-1",
            "accepted": False,
            "reason": "not_enough_hours",
            "asked": Decimal("10.500"),
            "available": Decimal("10.000"),
        }
    ]


def test_the_hours_of_a_line_are_its_limit_rounded_down_to_3_places():
    world, state = tiny_started()
    worn = replace(
        state, condition=MappingProxyType({"line-1": Decimal("0.123456789012")})
    )

    accepted = outcomes_of_period(worn, world, produce("monitor", "2.468"))
    rejected = outcomes_of_period(worn, world, produce("monitor", "2.470"))

    assert accepted[0]["accepted"] is True
    assert rejected == [
        {
            "decision_id": "1-1",
            "accepted": False,
            "reason": "not_enough_hours",
            "asked": Decimal("1.235"),
            "available": Decimal("1.234"),
        }
    ]


def test_a_produce_on_an_unknown_line_or_of_an_item_the_line_cannot_make_is_rejected():
    world, state = tiny_started()

    outcomes = outcomes_of_period(
        state, world, produce("monitor", "1", line="line-9"), produce("chip", "1")
    )

    assert outcomes == [
        {"decision_id": "1-1", "accepted": False, "reason": "unknown_line"},
        {"decision_id": "1-2", "accepted": False, "reason": "line_cannot_make_item"},
    ]


def test_a_produce_over_the_space_of_the_warehouse_is_rejected_with_its_numbers():
    manifest = tiny_manifest()
    manifest["warehouses"]["main"]["capacity"] = "2.000"
    world, state = tiny_started(manifest)

    assert outcomes_of_period(state, world, produce("monitor", "1")) == [
        {
            "decision_id": "1-1",
            "accepted": False,
            "reason": "not_enough_space",
            "asked": Decimal("0.110"),
            "available": Decimal("0.050"),
        }
    ]


def test_condition_wears_by_the_period_and_is_rounded_down_to_12_places():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"]["wear_per_period"] = "0.0001"
    manifest["lines"]["line-1"]["wear_per_hour"] = "0.0000"
    world, state = tiny_started(manifest)
    worn = replace(
        state, condition=MappingProxyType({"line-1": Decimal("0.123456789012")})
    )

    closed = advance_period(worn, world, submission(1, []))

    assert closed.condition["line-1"] == Decimal("0.123444443333")


def test_an_input_leaves_stock_rounded_up_to_3_places():
    manifest = tiny_manifest()
    manifest["components"]["board"]["recipes"]["standard"]["chip"] = "2.500"
    world, state = tiny_started(manifest)

    closed = advance_period(state, world, submission(1, [produce("board", "0.001")]))

    assert closed.stock["main"]["chip"] == Decimal("99.997")


def test_a_produce_with_a_later_start_becomes_a_plan_and_changes_nothing_else():
    world = plan_world()
    period_2 = started(world, 2, {})

    planned = decide(period_2, world, [produce("board", "10", start=4)])
    idle = decide(period_2, world, [])

    assert numbered_outcomes(planned) == [("2-1", True, "make-2-1", None, None, None)]
    assert [(plan.id, plan.start, plan.quantity) for plan in planned.plans] == [
        ("make-2-1", 4, Decimal("10.000"))
    ]
    assert (planned.stock, planned.cash, planned.condition) == (
        idle.stock,
        idle.cash,
        idle.condition,
    )
    assert planned.production == ()


def test_a_start_before_the_period_or_after_the_horizon_is_rejected():
    world = plan_world(horizon=10)
    period_2 = started(world, 2, {})

    state = decide(
        period_2,
        world,
        [produce("board", "1", start=0), produce("board", "1", start=11)],
    )

    assert [outcome.reason for outcome in state.outcomes] == [
        "start_outside_horizon"
    ] * 2
    assert state.plans == ()


def test_a_plan_rejected_when_decided_is_no_plan_in_the_measures():
    world = plan_world()

    state = closed_period(
        world, 2, {2: [produce("board", "1", line="line-9", start=4)]}
    )

    running = state.tallies.running
    assert [outcome.reason for outcome in state.outcomes] == ["unknown_line"]
    assert running["decisions_rejected"]["total"] == 1
    assert running["plans_made"]["total"] == 0
    assert running["plans_rejected"]["total"] == 0


def test_overtime_adds_hours_at_a_cost_per_hour_up_to_the_overtime_limit():
    world = overtime_world()

    state = first_period(
        world,
        [
            produce("monitor", "20"),
            produce("monitor", "8", overtime=True),
            produce("monitor", "1", overtime=True),
        ],
    )

    assert outcome_numbers(state) == [
        (True, None, None, None),
        (True, None, None, None),
        (False, "not_enough_hours", Decimal("0.500"), Decimal("0.000")),
    ]
    assert costs(state) == [
        ("production_cost", Decimal("-40")),
        ("production_cost", Decimal("-16")),
        ("overtime_cost", Decimal("-180")),
    ]
    assert state.condition["line-1"] == Decimal("0.962")


def test_an_overtime_produce_uses_overtime_hours_even_on_an_idle_line():
    world = overtime_world()

    state = first_period(
        world, [produce("monitor", "2", overtime=True), produce("monitor", "20")]
    )

    assert outcome_numbers(state) == [
        (True, None, None, None),
        (True, None, None, None),
    ]


def test_repair_hours_never_use_overtime():
    world = overtime_world(
        condition="0.9000", repair_time="40.000", repair_limit="0.5000"
    )

    state = first_period(
        world,
        [
            repair("0.1000"),
            produce("monitor", "14"),
            produce("monitor", "7", overtime=True),
        ],
    )

    assert outcome_numbers(state) == [
        (True, None, None, None),
        (False, "not_enough_hours", Decimal("7.000"), Decimal("6.000")),
        (True, None, None, None),
    ]


def test_an_overtime_produce_on_a_line_without_overtime_hours_is_rejected():
    manifest = tiny_manifest()
    scenario = tiny_scenario()
    scenario["start"]["stock"]["main"]["board"] = "100"
    world = draw_world_of_bodies(manifest, scenario)

    state = first_period(world, [produce("monitor", "1", overtime=True)])

    assert outcome_numbers(state) == [
        (False, "not_enough_hours", Decimal("0.500"), Decimal("0.000"))
    ]


def test_a_produce_takes_the_inputs_of_its_recipe_or_of_the_default():
    world = two_recipe_world()

    alternative = first_period(world, [produce("board", "10", recipe="alternative")])
    default = first_period(world, [produce("board", "10")])

    assert materials(alternative) == (Decimal(100), Decimal(80), Decimal(40))
    assert materials(default) == (Decimal(80), Decimal(100), Decimal(40))
    [outcome] = default.outcomes
    assert outcome.accepted
    assert isinstance(outcome.decision, Produce)
    assert outcome.decision.recipe == "standard"


def test_not_enough_input_names_the_short_input_of_the_chosen_recipe():
    state = first_period(
        two_recipe_world(), [produce("board", "60", recipe="alternative")]
    )

    assert outcome_inputs(state) == [
        (False, "not_enough_input", "chip-b", Decimal("120.000"), Decimal("100.000"))
    ]


def test_a_produce_with_a_recipe_the_item_does_not_have_is_rejected():
    state = first_period(two_recipe_world(), [produce("board", "1", recipe="premium")])

    assert outcome_inputs(state) == [(False, "unknown_recipe", None, None, None)]


def test_each_produce_of_another_item_pays_a_changeover():
    world = changeover_world()

    state = first_period(
        world, [produce("monitor", "1"), produce("board", "1"), produce("monitor", "1")]
    )

    assert changeover_costs(state) == [
        ("make-1-1", Decimal("-50")),
        ("make-1-2", Decimal("-50")),
        ("make-1-3", Decimal("-50")),
    ]
    assert state.set_for["line-1"] == "monitor"


def test_grouping_one_item_pays_one_changeover():
    world = changeover_world()

    state = first_period(
        world, [produce("board", "1"), produce("monitor", "1"), produce("monitor", "1")]
    )

    assert changeover_costs(state) == [("make-1-2", Decimal("-50"))]
    assert state.set_for["line-1"] == "monitor"


def test_changeover_hours_count_in_the_regular_hours_of_the_line():
    world = changeover_world()

    state = first_period(world, [produce("monitor", "18"), produce("board", "2")])

    assert outcome_numbers(state) == [
        (True, None, None, None),
        (False, "not_enough_hours", Decimal("1.200"), Decimal("0.000")),
    ]


def test_a_produce_that_fits_only_without_its_changeover_is_rejected():
    world = changeover_world()

    state = first_period(world, [produce("monitor", "19")])

    assert outcome_numbers(state) == [
        (False, "not_enough_hours", Decimal("10.500"), Decimal("10.000")),
    ]


def test_a_changeover_hour_does_not_wear_the_line():
    world = changeover_world()

    state = first_period(world, [produce("monitor", "18")])

    assert state.condition["line-1"] == Decimal("0.972")


def test_an_overtime_produce_needs_regular_hours_for_its_changeover():
    world = changeover_world(line_terms=OVERTIME)

    full = first_period(
        world, [produce("monitor", "18"), produce("board", "10", overtime=True)]
    )
    one_free = first_period(
        world,
        [
            produce("monitor", "16"),
            produce("board", "10", overtime=True),
            produce("board", "0.001"),
        ],
    )

    assert outcome_numbers(full)[1] == (
        False,
        "not_enough_hours",
        Decimal("1.000"),
        Decimal("0.000"),
    )
    assert outcome_numbers(one_free) == [
        (True, None, None, None),
        (True, None, None, None),
        (False, "not_enough_hours", Decimal("0.0001"), Decimal("0.000")),
    ]


def test_repair_and_changeover_hours_share_the_regular_hours():
    world = changeover_world(
        line_terms={"repair_time": "40.000", "repair_limit": "0.5000"},
        condition={"line-1": "0.9000"},
    )

    too_many = first_period(world, [repair("0.0500"), produce("monitor", "16")])
    fitting = first_period(world, [repair("0.0500"), produce("monitor", "14")])

    assert outcome_numbers(too_many) == [
        (True, None, None, None),
        (False, "not_enough_hours", Decimal("9.000"), Decimal("8.000")),
    ]
    assert outcome_numbers(fitting) == [
        (True, None, None, None),
        (True, None, None, None),
    ]


def test_a_produce_rejected_for_its_inputs_leaves_the_line_set_as_it_was():
    world = changeover_world(stock={"main": {"chip": "100", "board": "1"}})

    state = first_period(world, [produce("monitor", "1"), produce("board", "1")])

    assert outcome_numbers(state)[0][1] == "not_enough_input"
    assert changeover_costs(state) == []
    assert state.set_for["line-1"] == "board"


def test_a_changeover_with_a_cost_and_no_time_pays_and_uses_no_hours():
    world = changeover_world(
        item_terms={"monitor": {"changeover_cost": "50.0000"}},
    )

    state = first_period(world, [produce("monitor", "20")])

    assert outcome_numbers(state) == [(True, None, None, None)]
    assert changeover_costs(state) == [("make-1-1", Decimal("-50"))]


def test_an_item_without_changeover_keys_sets_the_line_for_itself():
    world = changeover_world(
        item_terms={
            "board": {"changeover_time": "1.000", "changeover_cost": "50.0000"}
        },
    )

    state = first_period(world, [produce("monitor", "1"), produce("board", "1")])

    assert changeover_costs(state) == [("make-1-2", Decimal("-50"))]
    assert state.set_for["line-1"] == "board"


def test_a_line_set_for_no_item_pays_a_changeover_for_its_first_produce():
    unset = first_period(changeover_world(set_for=None), [produce("board", "1")])
    set_for_board = first_period(changeover_world(), [produce("board", "1")])

    assert changeover_costs(unset) == [("make-1-1", Decimal("-50"))]
    assert changeover_costs(set_for_board) == []


def test_a_plan_runs_first_and_sets_the_line_for_its_item():
    world = changeover_world()

    state = closed_period(
        world, 2, {1: [produce("monitor", "1", start=2)], 2: [produce("board", "1")]}
    )

    assert changeover_costs(state) == [
        ("make-1-1", Decimal("-50")),
        ("make-2-1", Decimal("-50")),
    ]
    assert state.set_for["line-1"] == "board"


def test_making_a_plan_leaves_the_line_set_as_it_was():
    world = changeover_world()

    state = first_period(
        world, [produce("monitor", "1", start=3), produce("board", "1")]
    )

    assert changeover_costs(state) == []
    assert state.set_for["line-1"] == "board"


def test_an_overtime_produce_pays_production_then_overtime_then_changeover():
    world = changeover_world(line_terms=OVERTIME)

    state = first_period(world, [produce("monitor", "2", overtime=True)])

    assert [
        (row.kind, row.amount) for row in state.ledger if row.reference == "make-1-1"
    ] == [
        ("production_cost", Decimal("-4")),
        ("overtime_cost", Decimal("-45")),
        ("changeover_cost", Decimal("-50")),
    ]


def test_the_measures_count_changeovers_their_hours_and_their_cost():
    world = changeover_world()

    state = first_period(
        world, [produce("monitor", "1"), produce("board", "1"), produce("monitor", "1")]
    )

    assert line_measures(state) == {
        "changeovers": Decimal(3),
        "changeover_hours": Decimal(3),
        "changeover_cost": Decimal(150),
    }
    assert state.measures["changeover_cost"]["total"] == Decimal(150)


def test_a_changeover_of_no_time_and_no_cost_counts_and_writes_no_row():
    world = changeover_world(
        item_terms={
            "monitor": {"changeover_time": "0.000", "changeover_cost": "0.0000"}
        },
    )

    state = first_period(world, [produce("monitor", "1")])

    assert line_measures(state)["changeovers"] == Decimal(1)
    assert changeover_costs(state) == []


@pytest.mark.property
@given(small_factories(), seeds, st.data())
def test_a_produce_over_the_hours_left_is_rejected_with_the_hours_left(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world, state = started_world(factory, seed)
    produces = data.draw(produce_lists(world))
    closed = advance_period(state, world, submission(1, produces))
    regular, _ = regular_and_overtime_hours(state, closed, world)
    line_id = data.draw(st.sampled_from(sorted(world.factory.lines)))
    item_id = set_for_after(state, closed)[line_id] or min(
        world.factory.lines[line_id].items
    )
    capacity = world.parameters[f"lines.{line_id}.capacity"]
    capacity *= capacity_cut_share(world, line_id, 1)
    limit = min(round_down(capacity * state.condition[line_id]), round_down(capacity))
    left = limit - regular.get(line_id, Decimal(0))
    time = world.parameters[f"lines.{line_id}.items.{item_id}.time"]
    quantity = round_down(left / time) + Decimal("0.001")

    probed = advance_period(
        state,
        world,
        submission(1, [*produces, produce(item_id, str(quantity), line_id)]),
    )

    probe = probed.outcomes[-1]
    assert (probe.accepted, probe.reason, probe.available) == (
        False,
        "not_enough_hours",
        left,
    )


@pytest.mark.property
@given(small_factories(), seeds, st.data())
def test_good_and_scrap_have_3_places_and_sum_to_the_units_started(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world, state = started_world(factory, seed)
    produces = data.draw(produce_lists(world))

    closed = advance_period(state, world, submission(1, produces))

    for event in events_of(closed, "production_finished"):
        good, scrap = Decimal(event["good"]), Decimal(event["scrap"])
        assert good + scrap == Decimal(event["started"])
        assert places(good) <= 3
        assert places(scrap) <= 3
        assert scrap >= 0


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_a_line_is_set_for_the_item_of_its_last_production_created(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    _, steps = drawn_run(factory, seed, data.draw)

    for decided, _, closed in steps:
        expected = dict(decided.set_for)
        for decision in started_produces(closed):
            expected[decision.line] = decision.item
        assert dict(closed.set_for) == expected


def test_the_missing_hours_are_the_hours_asked_and_left_of_the_failing_limit():
    manifest = tiny_manifest()
    manifest["lines"]["line-1"]["capacity"] = "25.000"
    world = draw_world_of_bodies(manifest, tiny_scenario())
    plant = Plant(
        period=1,
        stock={},
        customer_orders={},
        receivables=[],
        condition={"line-1": Decimal(1)},
        set_for={},
        hours={},
        changeover_hours={},
        overtime_hours={},
        repair_hours={},
        repairs={},
        production=[],
        plans=[],
        supplier_orders=[],
        transfers=[],
    )
    decision = Produce(
        kind="produce",
        line="line-1",
        item="board",
        quantity=Decimal(30),
        recipe="standard",
        overtime=False,
        start=1,
    )
    missing = missing_hours(decision, Decimal(30), Decimal(0), plant, world)
    assert missing == (Decimal("30"), Decimal("25"))
    assert missing_hours(decision, Decimal(20), Decimal(0), plant, world) is None
