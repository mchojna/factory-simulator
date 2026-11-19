from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType

from factories import (
    decide,
    outcome_numbers,
    overtime_world,
    produce,
)

from factory_simulator.engine import (
    Cash,
    Disruption,
    Factory,
    Scenario,
    World,
    build_state,
    start_period,
)
from factory_simulator.engine.rules.lines import line_limits

ZERO = Decimal(0)


def hours_of(world: World) -> tuple[Decimal, Decimal]:
    state = start_period(build_state(world), world)
    assert state.observation is not None
    line = state.observation.lines["line-1"]
    return line.regular_hours_available, line.overtime_hours_available


def test_the_overtime_limit_falls_with_the_condition_and_with_a_capacity_cut():
    cut = {
        "kind": "capacity_cut",
        "target": ["line-1"],
        "start": 1,
        "duration": 1,
        "strength": "0.5000",
    }

    assert hours_of(overtime_world(condition="0.5000")) == (
        Decimal("5.000"),
        Decimal("2.000"),
    )
    assert hours_of(overtime_world(disruptions=[cut])) == (
        Decimal("5.000"),
        Decimal("2.000"),
    )


def test_the_overtime_limit_is_rounded_down_to_3_places():
    world = overtime_world()
    started = start_period(build_state(world), world)
    worn = replace(
        started, condition=MappingProxyType({"line-1": Decimal("0.123456789012")})
    )

    accepted = decide(worn, world, [produce("monitor", "0.986", overtime=True)])
    rejected = decide(worn, world, [produce("monitor", "0.988", overtime=True)])

    assert outcome_numbers(accepted) == [(True, None, None, None)]
    assert outcome_numbers(rejected) == [
        (False, "not_enough_hours", Decimal("0.494"), Decimal("0.493"))
    ]


def test_both_limits_of_the_hours_of_a_line_are_rounded_down_to_3_places():
    cash = Cash(
        credit_limit=ZERO,
        credit_interest=ZERO,
        debit_interest=ZERO,
        overdraft_interest=ZERO,
    )
    factory = Factory(
        materials={},
        components={},
        products={},
        suppliers={},
        customers={},
        lines={},
        warehouses={},
        cash=cash,
    )
    cut = Disruption(
        id="cut",
        kind="capacity_cut",
        target=("press",),
        start=1,
        duration=1,
        effect=Decimal("0.3333"),
    )
    world = World(
        factory=factory,
        scenario=Scenario(horizon=1),
        parameters={"lines.press.capacity": Decimal("10.001")},
        drawn=frozenset(),
        demand={},
        deliveries={},
        yields={},
        breakdowns={},
        disruptions=(cut,),
    )

    # 10.001 * (1 - 0.3333) = 6.6676667: down to 6.667, where half to even gives
    # 6.668; at condition 0.5 the hours are 3.33383335, down to 3.333.
    assert line_limits("press", 1, Decimal("0.5000"), world) == (
        Decimal("3.333"),
        Decimal("6.667"),
    )
