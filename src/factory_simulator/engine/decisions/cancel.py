"""The decision cancel: checks, reasons and execution.

Examples:
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
    >>> cancel = Cancel(kind="cancel", order="make-1-1", quantity=None)
    >>> cancel_plan(cancel, "1-2", plant).reason
    'unknown_order'
"""

from dataclasses import replace
from functools import partial

from factory_simulator.engine.changes import Ledger
from factory_simulator.engine.decisions.plant import Plant
from factory_simulator.engine.models.decisions import Cancel
from factory_simulator.engine.models.state import Outcome
from factory_simulator.engine.models.world import World


def execute_cancel(
    decision: Cancel, decision_id: str, plant: Plant, ledger: Ledger, world: World
) -> Outcome:
    """Execute a cancel decision that passes its checks: cancel a plan or an order.

    Args:
        decision (Cancel): The decision.
        decision_id (str): Its identifier, `<period>-<n>`.
        plant (Plant): Open supplier orders and plans, changed in place.
        ledger (Ledger): The ledger of the step, changed in place.
        world (World): The world.

    Returns:
        Outcome: The outcome of the decision.

    Examples:
        >>> from decimal import Decimal
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
        >>> cancel = Cancel(kind="cancel", order="buy-1-1", quantity=Decimal(2))
        >>> execute_cancel(cancel, "1-2", plant, ledger, world).reason
        'unknown_order'
    """
    if decision.order.startswith("make-"):
        return cancel_plan(decision, decision_id, plant)
    rejected = partial(
        Outcome, decision_id=decision_id, decision=decision, accepted=False
    )
    position = next(
        (
            order_position
            for order_position, order in enumerate(plant.supplier_orders)
            if order.id == decision.order
        ),
        None,
    )
    if position is None:
        return rejected(reason="unknown_order")
    if decision.quantity is None:
        return rejected(reason="wrong_quantity")
    order = plant.supplier_orders[position]
    if decision.quantity > order.open_quantity:
        return rejected(
            reason="over_open_quantity",
            asked=decision.quantity,
            available=order.open_quantity,
        )
    path = f"suppliers.{order.supplier}.catalogue.{order.material}"
    # The minimum and the tier count the quantity ordered, not what arrived. A cancel
    # of the whole open quantity closes the order and is never held to them.
    whole = decision.quantity == order.open_quantity
    left = order.quantity - order.cancelled - decision.quantity
    min_quantity = world.parameters.get(f"{path}.min_quantity")
    if (
        not whole
        and order.placed > 0
        and min_quantity is not None
        and 0 < left < min_quantity
    ):
        return rejected(reason="below_min_quantity", asked=left, available=min_quantity)
    if not whole and order.tier is not None and 0 < left < order.tier:
        return rejected(
            reason="below_discount_tier",
            asked=decision.quantity,
            available=order.quantity - order.cancelled - order.tier,
        )
    open_quantity = order.open_quantity - decision.quantity
    if open_quantity == 0:
        del plant.supplier_orders[position]
    else:
        plant.supplier_orders[position] = replace(
            order,
            open_quantity=open_quantity,
            cancelled=order.cancelled + decision.quantity,
        )
    reference = "cancel-" + decision_id
    fee = decision.quantity * world.parameters[f"{path}.cancellation_fee"]
    ledger.book("cancellation_fee", -fee, reference)
    return Outcome(
        decision_id=decision_id, decision=decision, accepted=True, reference=reference
    )


def cancel_plan(decision: Cancel, decision_id: str, plant: Plant) -> Outcome:
    """Cancel a plan: check the decision and, when it passes, remove the plan.

    Args:
        decision (Cancel): The decision, naming a `make-...` identifier.
        decision_id (str): Its identifier, `<period>-<n>`.
        plant (Plant): The plans, changed in place.

    Returns:
        Outcome: The outcome of the decision; a removed plan costs nothing.

    Examples:
        >>> from factory_simulator.engine import Plan
        >>> from decimal import Decimal
        >>> plan = Plan(
        ...     id="make-1-1",
        ...     start=3,
        ...     line="press",
        ...     item="bolt",
        ...     quantity=Decimal(5),
        ...     recipe="r",
        ...     overtime=False,
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
        ...     plans=[plan],
        ...     supplier_orders=[],
        ...     transfers=[],
        ... )
        >>> cancel = Cancel(kind="cancel", order="make-1-1", quantity=None)
        >>> cancel_plan(cancel, "1-1", plant).accepted, plant.plans
        (True, [])
    """
    rejected = partial(
        Outcome, decision_id=decision_id, decision=decision, accepted=False
    )
    plan = next((plan for plan in plant.plans if plan.id == decision.order), None)
    if plan is None:
        return rejected(reason="unknown_order")
    if decision.quantity is not None:
        return rejected(reason="wrong_quantity")
    plant.plans.remove(plan)
    return Outcome(
        decision_id=decision_id,
        decision=decision,
        accepted=True,
        reference="cancel-" + decision_id,
    )
