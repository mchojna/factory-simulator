"""The levels of a period: cash, stock, space and condition.

Examples:
    >>> from factory_simulator.engine import (
    ...     Cash,
    ...     Factory,
    ...     Scenario,
    ...     build_state,
    ...     draw_world,
    ... )
    >>> cash = Cash(
    ...     credit_limit=Decimal(0),
    ...     credit_interest=Decimal(0),
    ...     debit_interest=Decimal(0),
    ...     overdraft_interest=Decimal(0),
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
    >>> world = draw_world(factory, Scenario(horizon=4), seed=0)
    >>> levels(ClosedPeriod(build_state(world), world, {}, {}, {}))["cash"]
    {'total': Decimal('0.0000')}
"""

from decimal import Decimal

from factory_simulator.engine.measures.closed import ClosedPeriod, add, zeros
from factory_simulator.engine.rules.items import salvage_of, space_of


def levels(period: ClosedPeriod) -> dict[str, dict[str, Decimal | None]]:
    """Give the levels at the close: cash, profit so far, receivables, stock, condition.

    Args:
        period (ClosedPeriod): The closed period.

    Returns:
        dict[str, dict[str, Decimal | None]]: Values by name and key.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Factory,
        ...     Material,
        ...     Scenario,
        ...     State,
        ...     Warehouse,
        ...     draw_world,
        ... )
        >>> zero = Decimal(0)
        >>> steel = Material(
        ...     space=Decimal(2), storage_cost=zero, salvage_value=Decimal(3)
        ... )
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={"main": Warehouse(capacity=Decimal(100))},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> state = State(
        ...     period=1,
        ...     cash=zero,
        ...     stock={"main": {"steel": Decimal(10)}},
        ...     condition={},
        ...     customer_orders=(),
        ... )
        >>> measured = levels(
        ...     ClosedPeriod(
        ...         state=state,
        ...         world=draw_world(factory, Scenario(horizon=1), 0),
        ...         customer_orders={},
        ...         supplier_orders={},
        ...         production={},
        ...     )
        ... )
        >>> measured["stock_salvage_value"]["warehouses.main"]
        Decimal('30')
    """
    state = period.state
    world = period.world
    receivables = zeros(
        [
            "total",
            *(
                f"customers.{customer_id}"
                for customer_id in sorted(world.factory.customers)
            ),
        ]
    )
    for receivable in state.receivables:
        keys = ["total", f"customers.{receivable.customer}"]
        add(receivables, keys, receivable.amount)
    profit_so_far = state.cash - world.scenario.start.cash + receivables["total"]
    measured: dict[str, dict[str, Decimal]] = {
        "cash": {"total": state.cash},
        "profit_so_far": {"total": profit_so_far},
        "receivables": receivables,
        "stock": {},
        "stock_salvage_value": {},
        "stock_space": {},
        "space_used": {},
        "condition": {
            f"lines.{line_id}": condition
            for line_id, condition in state.condition.items()
        },
    }
    for warehouse_id in sorted(state.stock):
        warehouse = [f"warehouses.{warehouse_id}"]
        add(measured["space_used"], warehouse, Decimal(0))
        add(measured["stock"], warehouse, Decimal(0))
        add(measured["stock_salvage_value"], warehouse, Decimal(0))
        for item_id, quantity in sorted(state.stock[warehouse_id].items()):
            keys = [*warehouse, f"warehouses.{warehouse_id}/{item_id}"]
            space = quantity * space_of(item_id, world)
            add(measured["stock"], keys, quantity)
            add(
                measured["stock_salvage_value"],
                keys,
                quantity * salvage_of(item_id, world),
            )
            add(measured["stock_space"], keys[1:], space)
            add(measured["space_used"], warehouse, space)
    return {name: dict(values) for name, values in measured.items()}
