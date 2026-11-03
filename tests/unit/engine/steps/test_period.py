from dataclasses import FrozenInstanceError, replace
from decimal import ROUND_FLOOR, Decimal
from fractions import Fraction
from itertools import pairwise
from random import Random
from typing import Any, cast

import pytest
from factories import (
    LIBRARY,
    Draw,
    FactoryBodies,
    RunStep,
    assert_every_property_of_a_run,
    buy,
    count_reached,
    decide,
    draw_world_of_bodies,
    drawn_run,
    drawn_runs,
    example_bodies,
    example_count,
    example_world,
    generator_counts,
    is_recovered,
    linear_factories,
    plain_tiny_manifest,
    plain_tiny_scenario,
    produce,
    random_decisions,
    random_run,
    revenue_bound,
    seeds,
    ship,
    small_factories,
    small_factory_runs,
    submission,
    tiny_manifest,
    tiny_scenario,
)
from hypothesis import HealthCheck, Phase, assume, find, given, settings
from hypothesis import strategies as st

from factory_simulator.api.services.writers.values import plain
from factory_simulator.engine import (
    Buy,
    Ship,
    State,
    Tallies,
    World,
    advance_period,
    build_outcomes,
    build_state,
    generate_manifest,
    is_linear,
    start_period,
)
from factory_simulator.engine.steps.execution import execute_decisions

WAREHOUSE_KEYS = {
    "storage_factor": "1.0000",
    "transport_factor": "1.0000",
    "accepts": ["materials", "components", "products"],
}


# Period 1 of the tiny factory with ship 4, produce 4 monitors and 20 boards and buy 50
# chips: the started, executed and closed states.
def tiny_period_1(capacity: str) -> tuple[State, State, State]:
    manifest = tiny_manifest()
    manifest["warehouses"]["main"]["capacity"] = capacity
    world = draw_world_of_bodies(manifest, tiny_scenario())
    decisions = [
        ship("order-1-1", "4"),
        produce("monitor", "4"),
        produce("board", "20"),
        buy("50"),
    ]
    started = start_period(build_state(world), world)
    submitted = submission(1, decisions)
    executed = execute_decisions(started, world, submitted)
    closed = advance_period(started, world, submitted)
    return started, executed, closed


def without_warehouses(state: State) -> dict[str, object]:
    return {
        name: {key: value for key, value in values.items() if "warehouses" not in key}
        for name, values in state.measures.items()
    }


def rejects_a_buy_for_lack_of_space(run: tuple[World, list[RunStep]]) -> bool:
    _, steps = run
    return any(
        outcome.reason == "not_enough_space" and isinstance(outcome.decision, Buy)
        for _, _, closed in steps
        for outcome in closed.outcomes
    )


# The stock, lines, cash, orders, production, ledger and transfers of a state, their
# identifiers and the recipe and start of production left out.
def holdings_and_ledger_without_identifiers(state: State) -> tuple[object, ...]:
    return (
        state.stock,
        state.condition,
        state.set_for,
        state.cash,
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
            (made.line, made.item, made.started, made.ready)
            for made in state.production
        ),
        [(row.kind, row.amount) for row in state.ledger],
        transfers_without_identifiers(state),
    )


def transfers_without_identifiers(state: State) -> list[tuple[object, ...]]:
    return sorted(
        (
            transfer.item,
            transfer.quantity,
            transfer.source,
            transfer.destination,
            transfer.arrival,
        )
        for transfer in state.transfers
    )


def plans_without_identifiers(state: State) -> list[tuple[object, ...]]:
    return [
        (plan.start, plan.line, plan.item, plan.quantity, plan.recipe, plan.overtime)
        for plan in state.plans
    ]


# The decisions executed before the one at a position: the kinds run in the order ship,
# cancel, transfer, repair, produce, buy, and within a kind in the order given.
def executed_before(
    decisions: list[dict[str, Any]], position: int
) -> list[dict[str, Any]]:
    kinds = ["ship", "cancel", "transfer", "repair", "produce", "buy"]
    rank = kinds.index(decisions[position]["kind"])
    return [
        decision
        for number, decision in enumerate(decisions)
        if (kinds.index(decision["kind"]), number) < (rank, position)
    ]


# A state without its outcomes and measures, identifiers kept.
def without_outcomes(state: State) -> State:
    return replace(state, outcomes=(), measures={}, tallies=Tallies())


# Two decisions with the same total as one: halves, or a drawn first part. None for
# a decision without a quantity or amount, or too small to split.
def split(decision: dict[str, Any], draw: Draw) -> list[dict[str, Any]] | None:
    key, unit = (
        ("amount", Decimal("0.0001"))
        if decision["kind"] == "repair"
        else ("quantity", Decimal("0.001"))
    )
    if key not in decision:
        return None
    whole = Decimal(decision[key])
    if whole < 2 * unit:
        return None
    half = (whole / 2).quantize(unit, rounding=ROUND_FLOOR)
    places = -cast(int, unit.as_tuple().exponent)
    first = draw(
        st.one_of(
            st.just(half),
            st.decimals(min_value=unit, max_value=whole - unit, places=places),
        )
    )
    return [decision | {key: str(first)}, decision | {key: str(whole - first)}]


def open_by_arrival(state: State) -> dict[tuple[str, str, str, int], Decimal]:
    totals: dict[tuple[str, str, str, int], Decimal] = {}
    for order in state.supplier_orders:
        key = (order.supplier, order.material, order.warehouse, order.arrival)
        totals[key] = totals.get(key, Decimal(0)) + order.open_quantity
    return totals


def item_paths(world: World) -> list[str]:
    factory = world.factory
    return [
        *(f"materials.{item_id}" for item_id in factory.materials),
        *(f"components.{item_id}" for item_id in factory.components),
        *(f"products.{item_id}" for item_id in factory.products),
    ]


# Whether some period breaks one line by a written disruption and by a random rule. A
# written disruption is referred to as `disruption-<n>`, a random one as
# `<name>/<start>/<target>`.
def breaks_a_line_by_a_written_and_a_random_rule(
    run: tuple[World, list[RunStep]],
) -> bool:
    _, steps = run
    for decided, _, _ in steps:
        breakdowns = [
            (str(event["line"]), str(event["reference"]))
            for event in decided.period_events
            if event["kind"] == "breakdown"
        ]
        by_written = {
            line
            for line, reference in breakdowns
            if reference.startswith("disruption-") and "/" not in reference
        }
        by_rule = {line for line, reference in breakdowns if "/" in reference}
        if by_written & by_rule:
            return True
    return False


def rejects_a_buy_beyond_the_credit_limit(run: tuple[World, list[RunStep]]) -> bool:
    _, steps = run
    return any(
        outcome.reason == "over_credit_limit"
        for _, _, closed in steps
        for outcome in closed.outcomes
    )


# Whether some period of a run accepts a decision of a kind.
def accepts(run: tuple[World, list[RunStep]], kind: type) -> bool:
    return any(
        outcome.accepted and isinstance(outcome.decision, kind)
        for _, _, closed in run[1]
        for outcome in closed.outcomes
    )


def test_period_1_of_the_tiny_factory_ends_with_its_stock_cash_and_measures():
    started, executed, closed = tiny_period_1("100.000")

    [order] = started.customer_orders
    assert (order.id, order.quantity, order.due, order.last) == (
        "order-1-1",
        Decimal("4.000"),
        1,
        2,
    )
    assert started.observation is not None
    space = started.observation.space["main"]
    # 100 * 0.01 + 10 * 0.02 + 5 * 0.15 = 1.95
    assert space.used + space.reserved == Decimal("1.95")
    assert [
        (row.kind, row.amount, row.cash_after, row.reference) for row in executed.ledger
    ] == [
        ("customer_payment", Decimal(200), Decimal(1200), "ship-1-1"),
        ("transport_cost", Decimal(-4), Decimal(1196), "ship-1-1"),
        ("production_cost", Decimal(-8), Decimal(1188), "make-1-2"),
        ("production_cost", Decimal(-20), Decimal(1168), "make-1-3"),
    ]
    assert dict(executed.stock["main"]) == {
        "chip": Decimal(60),
        "board": Decimal(2),
        "monitor": Decimal(1),
    }
    assert [(outcome.accepted, outcome.reference) for outcome in closed.outcomes] == [
        (True, "ship-1-1"),
        (True, "make-1-2"),
        (True, "make-1-3"),
        (True, "buy-1-4"),
    ]
    assert dict(closed.stock["main"]) == {
        "chip": Decimal(60),
        "board": Decimal(20),
        "monitor": Decimal(5),
    }
    assert [
        (event["reference"], event["started"], event["good"], event["scrap"])
        for event in closed.period_events
        if event["kind"] == "production_finished"
    ] == [
        ("make-1-2", Decimal(4), Decimal(4), Decimal(0)),
        ("make-1-3", Decimal(20), Decimal(18), Decimal(2)),
    ]
    # 0.99 - 0.002 * 4 hours = 0.982
    assert closed.condition["line-1"] == Decimal("0.982")
    storage = [row for row in closed.ledger if row.kind == "storage_cost"]
    interest = [row for row in closed.ledger if row.kind == "interest_earned"]
    # 60 * 0.002 + 20 * 0.01 + 5 * 0.1 = 0.82; 1167.18 * 0.0005 = 0.58359, down 0.5835.
    assert sum(-row.amount for row in storage) == Decimal("0.82")
    assert storage[-1].cash_after == Decimal("1167.18")
    assert [row.amount for row in interest] == [Decimal("0.5835")]
    assert closed.cash == Decimal("1167.7635")
    measures = closed.measures
    assert measures["regular_hours"]["lines.line-1"] == Decimal(4)
    assert measures["storage_cost"]["total"] == Decimal("0.82")
    assert measures["interest_earned"]["total"] == Decimal("0.5835")
    assert measures["space_used"]["warehouses.main"] == Decimal("1.75")
    assert measures["units_scrap"]["lines.line-1/board"] == Decimal(2)
    assert measures["decisions_accepted"]["total"] == Decimal(4)


def test_period_1_of_the_tiny_factory_rejects_the_buy_when_the_space_is_short():
    _, _, closed = tiny_period_1("2.289")

    # The buy needs 2.29 of space: 60 * 0.01 + 2 * 0.02 + 1 * 0.15 + 4 * 0.15
    # + 20 * 0.02 + 50 * 0.01.
    assert [outcome.accepted for outcome in closed.outcomes] == [
        True,
        True,
        True,
        False,
    ]
    buy = closed.outcomes[-1]
    assert (buy.reason, buy.asked, buy.available) == (
        "not_enough_space",
        Decimal("0.500"),
        Decimal("0.499"),
    )


@pytest.mark.property
@settings(
    max_examples=example_count(200),
    suppress_health_check=[HealthCheck.filter_too_much],
)
@given(small_factories(), seeds, st.data())
def test_one_warehouse_without_warehouse_keys_runs_as_with_them_written_out(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    manifest, scenario = factory
    assume(len(manifest["warehouses"]) == 1)
    terms = manifest["warehouses"]["main"]
    for key in WAREHOUSE_KEYS:
        terms.pop(key, None)
    _, steps = drawn_run((manifest, scenario), seed, data.draw)
    terms.update(WAREHOUSE_KEYS)
    world = draw_world_of_bodies(manifest, scenario, seed=seed)

    state = build_state(world)
    for _, decisions, closed in steps:
        state = decide(start_period(state, world), world, decisions)
        assert state.ledger == closed.ledger
        assert without_warehouses(state) == without_warehouses(closed)


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factory_runs())
def test_every_property_of_a_run_holds_on_small_factories(
    run: tuple[World, list[RunStep]],
):
    assert_every_property_of_a_run(*run)


@pytest.mark.property
def test_the_runs_of_small_factories_reach_accepted_buys_and_ships():
    buys, drawn = count_reached(small_factory_runs(), lambda run: accepts(run, Buy))
    ships, drawn_again = count_reached(
        small_factory_runs(), lambda run: accepts(run, Ship)
    )

    assert buys * 10 >= drawn, (buys, drawn)
    assert ships * 10 >= drawn_again, (ships, drawn_again)


@pytest.mark.property
def test_some_generated_runs_reject_a_buy_for_lack_of_space():
    # `find` draws the full count in every run, to reach one such run.
    find(
        drawn_runs().map(rejects_a_buy_for_lack_of_space),
        lambda rejects: rejects,
        settings=settings(max_examples=200, database=None, phases=[Phase.generate]),
    )


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_a_rejected_decision_changes_nothing_but_outcomes_and_measures(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world, steps = drawn_run(factory, seed, data.draw)

    for decided, decisions, closed in steps:
        for outcome_position, outcome in enumerate(closed.outcomes):
            if outcome.accepted:
                continue
            decided_in, number = outcome.decision_id.split("-")
            if int(decided_in) < decided.period:
                # A plan rejected at its start: the same period without the plan.
                plan_id = f"make-{outcome.decision_id}"
                plans = tuple(plan for plan in decided.plans if plan.id != plan_id)
                without = decide(replace(decided, plans=plans), world, decisions)
            else:
                position = int(number) - 1
                rest = decisions[:position] + decisions[position + 1 :]
                without = decide(decided, world, rest)
                earlier = executed_before(decisions, position)
                before = decide(decided, world, earlier)
                with_rejected = decide(decided, world, [*earlier, decisions[position]])
                assert without_outcomes(with_rejected) == without_outcomes(before)
            assert holdings_and_ledger_without_identifiers(
                without
            ) == holdings_and_ledger_without_identifiers(closed)
            assert plans_without_identifiers(without) == plans_without_identifiers(
                closed
            )
            kept = [
                outcome.accepted
                for index, outcome in enumerate(closed.outcomes)
                if index != outcome_position
            ]
            assert sorted(outcome.accepted for outcome in without.outcomes) == sorted(
                kept
            )


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(st.one_of(linear_factories(), small_factories()), seeds, st.data())
def test_splitting_an_accepted_decision_gives_the_same_state_but_for_rounding(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world, steps = drawn_run(factory, seed, data.draw)
    # A ship splits exactly in any manifest; other decisions only in a linear one.
    linear = is_linear(world.factory)
    candidates = [
        (step, int(number) - 1)
        for step, (decided, _, closed) in enumerate(steps)
        for outcome in closed.outcomes
        for decided_in, number in [outcome.decision_id.split("-")]
        if outcome.accepted
        and int(decided_in) == decided.period
        and (linear or outcome.decision.kind == "ship")
    ]
    assume(candidates)
    step, position = data.draw(st.sampled_from(candidates))
    decided, decisions, closed = steps[step]
    halves = split(decisions[position], data.draw)
    assume(halves is not None)
    assert halves is not None
    two = decide(
        decided, world, decisions[:position] + halves + decisions[position + 1 :]
    )
    assume(
        all(
            outcome.accepted
            for outcome in two.outcomes
            if outcome.decision_id
            in (f"{decided.period}-{position + 1}", f"{decided.period}-{position + 2}")
        )
    )

    assert two.condition == closed.condition
    assert two.customer_orders == closed.customer_orders
    assert open_by_arrival(two) == open_by_arrival(closed)
    if decisions[position]["kind"] != "produce":
        assert two.stock == closed.stock
        assert two.cash == closed.cash
        return
    storage_factor = max(
        warehouse.storage_factor for warehouse in world.factory.warehouses.values()
    )
    storage = storage_factor * sum(
        world.parameters[f"{path}.storage_cost"] for path in item_paths(world)
    )
    # The good units of a batch round once; each input rounds up per production.
    for warehouse_id, items in closed.stock.items():
        for item_id, quantity in items.items():
            difference = two.stock[warehouse_id][item_id] - quantity
            if item_id == decisions[position]["item"]:
                assert difference == 0
            assert abs(difference) <= Decimal("0.001")
    rates = world.factory.cash
    rate = max(rates.credit_interest, rates.debit_interest, rates.overdraft_interest)
    # Storage of the difference in stock, and the interest on it rounded to 4 places.
    most = Decimal("0.001") * storage * (1 + rate) + Decimal("0.0001")
    assert abs(two.cash - closed.cash) <= most


@pytest.mark.property
def test_some_generated_runs_reject_a_buy_beyond_the_credit_limit():
    # `find` draws the full count in every run, to reach one such run.
    find(
        drawn_runs().map(rejects_a_buy_beyond_the_credit_limit),
        lambda rejects: rejects,
        settings=settings(max_examples=200, database=None, phases=[Phase.generate]),
    )


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(small_factories(), seeds, st.data())
def test_values_given_to_or_returned_by_the_engine_cannot_be_changed(
    factory: FactoryBodies, seed: int, data: st.DataObject
):
    world, steps = drawn_run(factory, seed, data.draw)
    closed = steps[-1][2]
    decided = steps[-1][0]
    assert decided.observation is not None

    for value, name in [
        (world, "parameters"),
        (world.factory, "cash"),
        (world.scenario, "horizon"),
        (closed, "cash"),
        (closed.tallies, "running"),
        (decided.observation, "cash"),
    ]:
        with pytest.raises((FrozenInstanceError, AttributeError)):
            setattr(value, name, None)
    for mapping in [
        closed.stock,
        closed.condition,
        closed.measures,
        closed.tallies.running,
        decided.observation.lines,
        decided.observation.space,
        world.parameters,
        world.factory.materials,
        *closed.stock.values(),
    ]:
        with pytest.raises(TypeError):
            cast(dict[str, Any], mapping)["key"] = None
    assert isinstance(closed.customer_orders, tuple)
    assert isinstance(world.scenario.start.customer_orders, tuple)
    for event in closed.period_events:
        with pytest.raises(TypeError):
            cast(dict[str, Any], event)["kind"] = None


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(st.sampled_from(LIBRARY), seeds, st.integers(min_value=0, max_value=2**32 - 1))
def test_every_property_of_a_run_holds_on_the_example_with_every_scenario(
    scenario_name: str, seed: int, decisions_seed: int
):
    world, steps = random_run(
        example_world(scenario_name, seed), Random(decisions_seed)
    )

    assert_every_property_of_a_run(world, steps)


# A start of the example below minus its credit limit by more than its stock can earn:
# each starting quantity of cash-squeeze cut to a drawn share, and cash below minus the
# credit limit less the revenue bound of that stock. Every period adds a buy of one
# connector pin, 0.9, to the drawn decisions.
@pytest.mark.property
@settings(max_examples=example_count(200))
@given(st.data(), seeds, st.integers(min_value=0, max_value=2**32 - 1))
def test_a_start_whose_stock_cannot_reach_the_credit_line_is_never_recovered(
    data: st.DataObject, seed: int, decisions_seed: int
):
    manifest, scenario = example_bodies("cash-squeeze")
    stock = scenario["start"]["stock"]
    for items in stock.values():
        for item_id, quantity in items.items():
            share = Decimal(data.draw(st.integers(min_value=0, max_value=1000))) / 1000
            items[item_id] = str(
                (Decimal(str(quantity)) * share).quantize(Decimal("0.001"))
            )
    limit = Fraction(str(manifest["cash"]["credit_limit"]))
    gap = Fraction(data.draw(st.integers(min_value=1, max_value=10**8)), 10**4)
    highest = -limit - revenue_bound(stock) - gap
    cash = (Decimal(highest.numerator) / highest.denominator).quantize(
        Decimal("0.0001"), rounding=ROUND_FLOOR
    )
    scenario["start"]["cash"] = str(cash)
    world = draw_world_of_bodies(manifest, scenario, seed=seed)
    generator = Random(decisions_seed)
    pin = buy("1", "connector-pins", "emea-electronic-parts", warehouse="main-plant")

    state = build_state(world)
    buys: list[tuple[bool, str | None]] = []
    while not state.finished:
        decided = start_period(state, world)
        decisions = [*random_decisions(generator, world, decided), pin]
        state = decide(decided, world, decisions)
        buys += [
            (outcome.accepted, outcome.reason)
            for outcome in state.outcomes
            if isinstance(outcome.decision, Buy)
        ]

    assert not is_recovered(buys)
    assert not any(accepted for accepted, _ in buys)


@pytest.mark.property
@settings(max_examples=example_count(200))
@given(generator_counts(), seeds, seeds, st.integers(min_value=0, max_value=2**32 - 1))
def test_every_property_of_a_run_holds_on_generated_manifests(
    counts: dict[str, int], generator_seed: int, seed: int, decisions_seed: int
):
    manifest = generate_manifest(counts, generator_seed)
    world = draw_world_of_bodies(manifest, {"horizon": 12}, seed=seed)
    world, steps = random_run(world, Random(decisions_seed))

    assert_every_property_of_a_run(world, steps)


@pytest.mark.property
def test_some_generated_worlds_break_one_line_by_a_written_and_a_random_rule_at_once():
    # About one example in 500 breaks a line twice, so `find` draws the full count and
    # the draws are the same each run.
    find(
        drawn_runs().map(breaks_a_line_by_a_written_and_a_random_rule),
        lambda breaks: breaks,
        settings=settings(
            max_examples=1000,
            database=None,
            phases=[Phase.generate],
            derandomize=True,
        ),
    )


def test_the_outcomes_of_decisions_are_built_as_they_execute_and_change_nothing():
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario())
    state = start_period(build_state(world), world)
    decisions = submission(1, [produce("monitor", "4"), produce("monitor", "2")])

    outcomes = build_outcomes(state, world, decisions)

    # 4 monitors take 8 of the 10 boards, so 2 more, which need 4 boards, find 2.
    assert [
        (outcome.accepted, outcome.reason, outcome.asked, outcome.available)
        for outcome in outcomes
    ] == [
        (True, None, None, None),
        (False, "not_enough_input", Decimal("4.000"), Decimal("2.000")),
    ]
    assert outcomes == advance_period(state, world, decisions).outcomes
    assert state.stock["main"]["board"] == Decimal("10.000")
    assert state.outcomes == ()


def test_an_empty_period_traces_all_6_steps_and_keeps_the_open_prefix():
    world = draw_world_of_bodies(tiny_manifest(), tiny_scenario())
    started = start_period(build_state(world), world)
    closed = advance_period(started, world, submission(1, []))

    assert [entry.step for entry in started.trace] == [
        "receive_deliveries",
        "apply_events",
        "build_observation",
    ]
    assert [entry.step for entry in closed.trace] == [
        "receive_deliveries",
        "apply_events",
        "build_observation",
        "make_decisions",
        "execute_decisions",
        "close_period",
    ]
    assert closed.trace[0].before["period"] == 0
    assert closed.trace[0].after["period"] == 1
    assert closed.trace[0].before["stock"] == closed.trace[0].after["stock"]
    assert closed.trace[-1].after["cash"] == closed.cash
    assert closed.trace[-1].after["tallies"] is not None
    assert "trace" not in closed.trace[-1].after
    next_started = start_period(closed, world)
    assert len(next_started.trace) == 3
    assert len(closed.trace) == 6


def test_two_periods_trace_the_execution_order_stock_money_and_rejection():
    world = draw_world_of_bodies(plain_tiny_manifest(), plain_tiny_scenario())
    started = start_period(build_state(world), world)
    closed = advance_period(
        started,
        world,
        submission(
            1,
            [
                buy("6"),
                produce("board", "2"),
                produce("monitor", "2"),
                ship("missing", "1"),
            ],
        ),
    )
    decisions = [entry for entry in closed.trace if entry.kind != "step"]

    assert [(entry.kind, entry.decision_id) for entry in decisions] == [
        ("ship", "1-4"),
        ("produce", "1-2"),
        ("produce", "1-3"),
        ("buy", "1-1"),
    ]
    assert cast(Any, decisions[0].outcome)["reason"] == "unknown_order"
    assert decisions[0].before == decisions[0].after
    board = cast(Any, decisions[1])
    assert board.before["plant"]["stock"]["main"]["chip"] == Decimal("16")
    assert board.after["plant"]["stock"]["main"]["chip"] == Decimal("12")
    assert board.after["plant"]["hours"]["line-1"] == Decimal("0.2")
    assert board.after["ledger"]["cash"] == Decimal("998")
    assert cast(Any, decisions[2].after)["ledger"]["cash"] == Decimal("994")
    assert closed.cash == Decimal("954")

    next_started = start_period(closed, world)
    delivery = cast(Any, next_started.trace[0])
    assert delivery.before["stock"]["main"]["chip"] == Decimal("12")
    assert delivery.after["stock"]["main"]["chip"] == Decimal("18")
    assert delivery.after["cash"] == Decimal("951")
    next_closed = advance_period(
        next_started, world, submission(2, [ship("order-2-1", "2")])
    )
    shipped = cast(
        Any, next(entry for entry in next_closed.trace if entry.kind == "ship")
    )
    assert shipped.before["plant"]["stock"]["main"]["monitor"] == Decimal("2")
    assert shipped.after["plant"]["stock"]["main"]["monitor"] == Decimal("0")
    assert shipped.after["ledger"]["cash"] == Decimal("1049")
    assert next_closed.cash == Decimal("1029")
    # The snapshot of period 1 stays the same after period 2.
    assert board.after["plant"]["hours"]["line-1"] == Decimal("0.2")


@pytest.mark.property
@settings(max_examples=example_count(100))
@given(small_factory_runs())
def test_complete_step_snapshots_reconstruct_every_generated_close(
    run: tuple[World, list[RunStep]],
):
    for _, _, closed in run[1]:
        steps = [entry for entry in closed.trace if entry.kind == "step"]
        assert len(steps) == 6
        for previous, following in pairwise(steps):
            assert previous.after == following.before
        reconstructed = cast(dict[str, object], plain(steps[-1].after))
        # Public outcome JSON omits absent optional values; snapshots retain them.
        holders = [reconstructed]
        if reconstructed["observation"] is not None:
            holders.append(cast(dict[str, object], reconstructed["observation"]))
        for holder in holders:
            holder["outcomes"] = [
                {key: value for key, value in outcome.items() if value is not None}
                for outcome in cast(list[dict[str, object]], holder["outcomes"])
            ]
        actual = cast(dict[str, object], plain(closed))
        del actual["trace"]
        assert reconstructed == actual


def test_scheduled_production_keeps_its_plan_and_its_position_in_the_trace():
    world = draw_world_of_bodies(plain_tiny_manifest(), plain_tiny_scenario())
    state = start_period(build_state(world), world)
    first = advance_period(
        state, world, submission(1, [produce("board", "2", start=2)])
    )
    state = start_period(first, world)
    closed = advance_period(state, world, submission(2, [ship("missing", "1")]))
    operations = [entry for entry in closed.trace if entry.kind != "step"]

    assert [(entry.kind, entry.decision_id) for entry in operations] == [
        ("ship", "2-1"),
        ("produce", "1-1"),
    ]
    assert closed.outcomes[0].decision_id == "1-1"
    scheduled = cast(Any, operations[1])
    assert scheduled.reference == "make-1-1"
    assert scheduled.before["plant"]["plans"][0]["id"] == "make-1-1"
    assert scheduled.after["plant"]["plans"] == ()
    assert scheduled.after["plant"]["stock"]["main"]["chip"] == Decimal("12")
