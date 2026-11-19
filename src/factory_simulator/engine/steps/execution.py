"""The execution of decisions: by kind, ship, cancel, transfer, repair, produce, buy.

Examples:
    >>> from decimal import Decimal
    >>> from factory_simulator.engine import (
    ...     Cash,
    ...     Factory,
    ...     Scenario,
    ...     build_state,
    ...     draw_world,
    ...     start_period,
    ... )
    >>> world = draw_world(
    ...     Factory(
    ...         materials={},
    ...         components={},
    ...         products={},
    ...         suppliers={},
    ...         customers={},
    ...         lines={},
    ...         warehouses={},
    ...         cash=Cash(
    ...             credit_limit=Decimal(0),
    ...             credit_interest=Decimal(0),
    ...             debit_interest=Decimal(0),
    ...             overdraft_interest=Decimal(0),
    ...         ),
    ...     ),
    ...     Scenario(horizon=4),
    ...     seed=0,
    ... )
    >>> state = start_period(build_state(world), world)
    >>> execute_decisions(state, world, Decisions(period=1)).outcomes
    ()
"""

from collections.abc import Callable, Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

from factory_simulator.engine.changes import Ledger, identifier_numbers
from factory_simulator.engine.decisions.buy import execute_buy
from factory_simulator.engine.decisions.cancel import execute_cancel
from factory_simulator.engine.decisions.plant import Plant
from factory_simulator.engine.decisions.produce import execute_produce
from factory_simulator.engine.decisions.repair import execute_repair
from factory_simulator.engine.decisions.ship import execute_ship
from factory_simulator.engine.decisions.transfer import execute_transfer
from factory_simulator.engine.models.decisions import (
    Buy,
    Cancel,
    Decision,
    Decisions,
    Produce,
    Repair,
    Ship,
    Transfer,
)
from factory_simulator.engine.models.manifest import read_only_copy
from factory_simulator.engine.models.state import Outcome, Plan, State
from factory_simulator.engine.models.trace import Transition
from factory_simulator.engine.models.world import World
from factory_simulator.engine.traces import snapshot

# A function that executes one kind of decision on the plant.
type Executor = Callable[[Any, str, Plant, Ledger, World], Outcome]

# The executor of each kind of decision.
EXECUTORS: Mapping[type[Decision], Executor] = MappingProxyType(
    {
        Ship: execute_ship,
        Cancel: execute_cancel,
        Transfer: execute_transfer,
        Repair: execute_repair,
        Produce: execute_produce,
        Buy: execute_buy,
    }
)
# The kinds that run before the plans of the period, then the kinds after them.
FIRST_KINDS: tuple[type[Decision], ...] = (Ship, Cancel, Transfer, Repair)
LAST_KINDS: tuple[type[Decision], ...] = (Produce, Buy)


def execute_decisions(state: State, world: World, decisions: Decisions) -> State:
    """Execute the decisions of the period by kind.

    The kinds run in the order ship, cancel, transfer, repair, produce, buy.

    Within a kind decisions run in the order given. Each decision is checked against the
    state left by the decisions accepted before it, then executed in full or rejected in
    full.

    Args:
        state (State): The state.
        world (World): The world.
        decisions (Decisions): The decisions of the period.

    Returns:
        State: The state after the decisions, with their outcomes and without the
            events of the previous observation.

    Examples:
        >>> from decimal import Decimal
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Factory,
        ...     Line,
        ...     LineItem,
        ...     Material,
        ...     Product,
        ...     Scenario,
        ...     Start,
        ...     Warehouse,
        ...     build_state,
        ...     draw_world,
        ...     start_period,
        ... )
        >>> zero, one = Decimal(0), Decimal(1)
        >>> stored = {"space": one, "storage_cost": zero, "salvage_value": zero}
        >>> press = Line(
        ...     capacity=Decimal(40),
        ...     wear_per_period=zero,
        ...     wear_per_hour=zero,
        ...     breakdown_chance=zero,
        ...     breakdown_loss=zero,
        ...     repair_cost=zero,
        ...     repair_time=zero,
        ...     repair_limit=one,
        ...     items={"bolt": LineItem(time=one, cost=one, yield_=one)},
        ... )
        >>> factory = Factory(
        ...     materials={"steel": Material(**stored)},
        ...     components={},
        ...     products={"bolt": Product(**stored, recipes={"r": {"steel": one}})},
        ...     suppliers={},
        ...     customers={},
        ...     lines={"press": press},
        ...     warehouses={"main": Warehouse(capacity=Decimal(1000))},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> start = Start(stock={"main": {"steel": Decimal(10)}})
        >>> scenario = Scenario(horizon=1, start=start)
        >>> world = draw_world(factory, scenario, seed=0)
        >>> make = Produce(
        ...     kind="produce",
        ...     line="press",
        ...     item="bolt",
        ...     quantity=Decimal(5),
        ...     recipe="r",
        ...     overtime=False,
        ...     start=None,
        ... )
        >>> state = start_period(build_state(world), world)
        >>> decisions = Decisions(period=1, decisions=(make,))
        >>> execute_decisions(state, world, decisions).stock["main"]["steel"]
        Decimal('5.000')
    """
    period = state.period
    ledger = Ledger(period, "execute_decisions", state.cash, list(state.ledger))
    plant = Plant(
        period=period,
        stock={warehouse: dict(items) for warehouse, items in state.stock.items()},
        customer_orders={order.id: order for order in state.customer_orders},
        receivables=list(state.receivables),
        condition=state.condition,
        set_for=dict(state.set_for),
        hours={},
        changeover_hours={},
        overtime_hours={},
        repair_hours={},
        repairs={},
        production=list(state.production),
        plans=list(state.plans),
        supplier_orders=list(state.supplier_orders),
        transfers=list(state.transfers),
    )
    numbered = [
        (f"{period}-{position}", decision)
        for position, decision in enumerate(decisions.decisions, start=1)
    ]
    trace = list(state.trace)
    outcomes = execute_kinds(FIRST_KINDS, numbered, plant, ledger, trace, world)
    # Plans that start now run before the other produce decisions, and their
    # outcomes come first among the outcomes of the period.
    plan_outcomes = [
        execute_traced(
            produce_of(plan),
            plan.id.removeprefix("make-"),
            plant,
            ledger,
            trace,
            world,
            plan=plan,
        )
        for plan in sorted(
            (plan for plan in plant.plans if plan.start == period),
            key=lambda plan: identifier_numbers(plan.id),
        )
    ]
    outcomes += execute_kinds(LAST_KINDS, numbered, plant, ledger, trace, world)
    production = sorted(
        plant.production, key=lambda production: identifier_numbers(production.id)
    )
    return replace(
        state,
        cash=ledger.cash,
        stock=read_only_copy(plant.stock),
        customer_orders=tuple(plant.customer_orders.values()),
        receivables=tuple(plant.receivables),
        set_for=MappingProxyType(plant.set_for),
        production=tuple(production),
        plans=tuple(plant.plans),
        supplier_orders=tuple(plant.supplier_orders),
        transfers=tuple(plant.transfers),
        repairs=MappingProxyType(plant.repairs),
        ledger=tuple(ledger.rows),
        outcomes=(*plan_outcomes, *outcomes),
        events=(),
        trace=tuple(trace),
    )


def execute_kinds(
    kinds: tuple[type[Decision], ...],
    numbered: list[tuple[str, Decision]],
    plant: Plant,
    ledger: Ledger,
    trace: list[Transition],
    world: World,
) -> list[Outcome]:
    """Execute the decisions of some kinds, kind by kind, each in the order given.

    Args:
        kinds (tuple[type[Ship | Produce | Buy | Repair | Cancel | Transfer], ...]): The
            kinds, in the order they run.
        numbered (list[tuple[str, Ship | Produce | Buy | Repair | Cancel | Transfer]]):
            Every decision of the period with its identifier.
        plant (Plant): The plant, changed in place.
        ledger (Ledger): The ledger of the step, changed in place.
        trace (list[Transition]): The transitions, changed in place.
        world (World): The world.

    Returns:
        list[Outcome]: The outcomes, in the order of execution.

    Examples:
        >>> from decimal import Decimal
        >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
        >>> world = draw_world(
        ...     Factory(
        ...         materials={},
        ...         components={},
        ...         products={},
        ...         suppliers={},
        ...         customers={},
        ...         lines={},
        ...         warehouses={},
        ...         cash=Cash(
        ...             credit_limit=Decimal(0),
        ...             credit_interest=Decimal(0),
        ...             debit_interest=Decimal(0),
        ...             overdraft_interest=Decimal(0),
        ...         ),
        ...     ),
        ...     Scenario(horizon=4),
        ...     seed=0,
        ... )
        >>> plant = Plant(
        ...     period=1,
        ...     stock={"main": {}},
        ...     customer_orders={},
        ...     receivables=[],
        ...     condition={},
        ...     set_for={},
        ...     hours={},
        ...     changeover_hours={},
        ...     overtime_hours={},
        ...     repair_hours={},
        ...     repairs={},
        ...     production=[],
        ...     plans=[],
        ...     supplier_orders=[],
        ...     transfers=[],
        ... )
        >>> ledger = Ledger(
        ...     period=1, step="execute_decisions", cash=Decimal(0), rows=[]
        ... )
        >>> repair = Repair(kind="repair", line="saw", amount=Decimal("0.1"))
        >>> trace = []
        >>> outcomes = execute_kinds(
        ...     FIRST_KINDS, [("1-1", repair)], plant, ledger, trace, world
        ... )
        >>> [outcome.reason for outcome in outcomes]
        ['unknown_line']
    """
    outcomes: list[Outcome] = []
    for kind in kinds:
        for decision_id, decision in numbered:
            if isinstance(decision, kind):
                outcomes.append(
                    execute_traced(decision, decision_id, plant, ledger, trace, world)
                )
    return outcomes


def execute_traced(
    decision: Decision,
    decision_id: str,
    plant: Plant,
    ledger: Ledger,
    trace: list[Transition],
    world: World,
    *,
    plan: Plan | None = None,
) -> Outcome:
    """Execute and trace one decision, and remove its plan when it is scheduled.

    Args:
        decision (Ship | Produce | Buy | Repair | Cancel | Transfer): The decision.
        decision_id (str): The identifier of the decision.
        plant (Plant): The plant, changed in place.
        ledger (Ledger): The ledger, changed in place.
        trace (list[Transition]): The transitions, changed in place.
        world (World): The world.
        plan (Plan | None, optional): The scheduled plan to remove, None when not
            given.

    Returns:
        Outcome: The outcome, accepted or rejected.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
        >>> from decimal import Decimal
        >>> world = draw_world(
        ...     Factory(
        ...         materials={},
        ...         components={},
        ...         products={},
        ...         suppliers={},
        ...         customers={},
        ...         lines={},
        ...         warehouses={},
        ...         cash=Cash(
        ...             credit_limit=Decimal(0),
        ...             credit_interest=Decimal(0),
        ...             debit_interest=Decimal(0),
        ...             overdraft_interest=Decimal(0),
        ...         ),
        ...     ),
        ...     Scenario(horizon=1),
        ...     seed=0,
        ... )
        >>> plant = Plant(
        ...     period=1,
        ...     stock={},
        ...     customer_orders={},
        ...     receivables=[],
        ...     condition={},
        ...     set_for={},
        ...     hours={},
        ...     changeover_hours={},
        ...     overtime_hours={},
        ...     repair_hours={},
        ...     repairs={},
        ...     production=[],
        ...     plans=[],
        ...     supplier_orders=[],
        ...     transfers=[],
        ... )
        >>> ledger = Ledger(
        ...     period=1, step="execute_decisions", cash=Decimal(0), rows=[]
        ... )
        >>> trace = []
        >>> decision = Repair(kind="repair", line="missing", amount=Decimal("0.1"))
        >>> execute_traced(decision, "1-1", plant, ledger, trace, world).reason
        'unknown_line'
        >>> trace[0].kind
        'repair'
    """
    before = cast(Mapping[str, object], snapshot({"plant": plant, "ledger": ledger}))
    if plan is not None:
        plant.plans.remove(plan)
    outcome = EXECUTORS[type(decision)](decision, decision_id, plant, ledger, world)
    trace.append(
        Transition(
            step="execute_decisions",
            kind=decision.kind,
            reference=plan.id if plan is not None else decision_id,
            decision_id=decision_id,
            input=snapshot(decision),
            outcome=snapshot(outcome),
            before=before,
            after=cast(
                Mapping[str, object], snapshot({"plant": plant, "ledger": ledger})
            ),
        )
    )
    return outcome


def produce_of(plan: Plan) -> Produce:
    """Give the produce decision a plan is made from.

    Args:
        plan (Plan): The plan.

    Returns:
        Produce: The decision with every default filled in.

    Examples:
        >>> from decimal import Decimal
        >>> plan = Plan(
        ...     id="make-1-1",
        ...     start=2,
        ...     line="press",
        ...     item="bolt",
        ...     quantity=Decimal(5),
        ...     recipe="r",
        ...     overtime=False,
        ... )
        >>> produce_of(plan).start
        2
    """
    return Produce(
        kind="produce",
        line=plan.line,
        item=plan.item,
        quantity=plan.quantity,
        recipe=plan.recipe,
        overtime=plan.overtime,
        start=plan.start,
    )
