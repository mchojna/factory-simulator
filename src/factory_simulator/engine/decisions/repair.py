"""The decision repair: checks, reasons and execution.

Examples:
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
    >>> ledger = Ledger(period=1, step="execute_decisions", cash=Decimal(0), rows=[])
    >>> repair = Repair(kind="repair", line="press", amount=Decimal("0.1"))
    >>> execute_repair(repair, "1-1", plant, ledger, world).reason
    'unknown_line'
"""

from decimal import Decimal
from functools import partial

from factory_simulator.engine.changes import Ledger
from factory_simulator.engine.decisions.plant import Plant, repair_hours_left
from factory_simulator.engine.models.decisions import Repair
from factory_simulator.engine.models.state import Outcome
from factory_simulator.engine.models.world import World


def execute_repair(
    decision: Repair, decision_id: str, plant: Plant, ledger: Ledger, world: World
) -> Outcome:
    """Execute a repair decision that passes its checks: restore condition to its line.

    Args:
        decision (Repair): The decision.
        decision_id (str): Its identifier, `<period>-<n>`.
        plant (Plant): Hours and repairs, changed in place.
        ledger (Ledger): The ledger of the step, changed in place.
        world (World): The world.

    Returns:
        Outcome: The outcome of the decision.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=4),
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
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
        >>> ledger = Ledger(period=1, step="execute_decisions", cash=zero, rows=[])
        >>> repair = Repair(kind="repair", line="press", amount=Decimal("0.1"))
        >>> execute_repair(repair, "1-1", plant, ledger, world).reason
        'unknown_line'
    """
    rejected = partial(
        Outcome, decision_id=decision_id, decision=decision, accepted=False
    )
    if decision.line not in world.factory.lines:
        return rejected(reason="unknown_line")
    path = f"lines.{decision.line}"
    amount = decision.amount
    repaired = plant.repairs.get(decision.line, Decimal(0))
    below_limit = world.parameters[f"{path}.repair_limit"] - repaired
    if amount > below_limit:
        return rejected(reason="over_repair_limit", asked=amount, available=below_limit)
    below_full = 1 - plant.condition[decision.line] - repaired
    if amount > below_full:
        return rejected(
            reason="over_full_condition", asked=amount, available=below_full
        )
    hours = amount * world.parameters[f"{path}.repair_time"]
    available_hours = repair_hours_left(decision.line, plant, world)
    if hours > available_hours:
        return rejected(
            reason="not_enough_hours", asked=hours, available=available_hours
        )
    plant.repair_hours[decision.line] = (
        plant.repair_hours.get(decision.line, Decimal(0)) + hours
    )
    plant.repairs[decision.line] = plant.repairs.get(decision.line, Decimal(0)) + amount
    reference = "repair-" + decision_id
    cost = amount * world.parameters[f"{path}.repair_cost"]
    ledger.book("repair_cost", -cost, reference)
    return Outcome(
        decision_id=decision_id, decision=decision, accepted=True, reference=reference
    )
