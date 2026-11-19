"""The measures of a period: the first totals and the measures recorded at each close.

Examples:
    >>> from factory_simulator.engine import (
    ...     Cash,
    ...     Factory,
    ...     Scenario,
    ...     build_state,
    ...     draw_world,
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
    >>> state = replace(build_state(world), period=1)
    >>> record_measures(state, state, world).measures["cash"]
    mappingproxy({'total': Decimal('0.0000')})
"""

from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType

from factory_simulator.engine.measures.closed import ClosedPeriod, ratio
from factory_simulator.engine.measures.flows import (
    add_customer_flows,
    cost_flows,
    customer_orders_created,
    decision_flows,
    input_flows,
    line_flows,
    route_flows,
    supplier_flows,
)
from factory_simulator.engine.measures.groups import (
    group_levels,
    index_groups,
    with_groups,
)
from factory_simulator.engine.measures.kinds import MEASURE_KINDS, RATIOS
from factory_simulator.engine.measures.levels import levels
from factory_simulator.engine.models.manifest import read_only_copy
from factory_simulator.engine.models.state import State, Tallies
from factory_simulator.engine.models.world import World


def first_tallies(state: State) -> Tallies:
    """Give the running totals before period 1.

    Args:
        state (State): The state before period 1.

    Returns:
        Tallies: The starting orders and nothing counted.

    Examples:
        >>> from factory_simulator.engine.models.state import CustomerOrder
        >>> order = CustomerOrder(
        ...     id="order-0-1",
        ...     customer="shop",
        ...     product="bolt",
        ...     quantity=Decimal("10.000"),
        ...     shipped=Decimal(0),
        ...     arrival=0,
        ...     due=2,
        ...     last=3,
        ... )
        >>> state = State(
        ...     period=0,
        ...     cash=Decimal(0),
        ...     stock={},
        ...     condition={},
        ...     customer_orders=(order,),
        ... )
        >>> list(first_tallies(state).customer_orders)
        ['order-0-1']
    """
    return Tallies(
        customer_orders=MappingProxyType(
            {order.id: order for order in state.customer_orders}
        ),
        supplier_orders=MappingProxyType(
            {order.id: order for order in state.supplier_orders}
        ),
    )


def record_measures(executed: State, closed: State, world: World) -> State:
    """Record the measures of the period and add them to the totals.

    Args:
        executed (State): The state after the decisions, before the close.
        closed (State): The state at the close, after interest.
        world (World): The world.

    Returns:
        State: The closed state with the measures of the period and the new totals.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
        >>> zero = Decimal(0)
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), 0)
        >>> state = State(
        ...     period=1, cash=Decimal(-5), stock={}, condition={}, customer_orders=()
        ... )
        >>> closed = record_measures(state, state, world)
        >>> closed.measures["periods_below_credit_limit"]["total"]
        Decimal('1')
    """
    tallies = closed.tallies
    period = ClosedPeriod(
        state=closed,
        world=world,
        customer_orders=dict(tallies.customer_orders)
        | {order.id: order for order in customer_orders_created(closed)},
        supplier_orders=dict(tallies.supplier_orders)
        | {order.id: order for order in closed.supplier_orders},
        production={production.id: production for production in executed.production},
    )
    shipped_on_time = dict(tallies.shipped_on_time)
    flows = (
        add_customer_flows(period, shipped_on_time)
        | cost_flows(period)
        | line_flows(period)
        | input_flows(period)
        | route_flows(period)
        | supplier_flows(period)
        | decision_flows(period)
    )
    groups = index_groups(world)
    flows = {name: with_groups(values, groups) for name, values in flows.items()}
    running = {
        name: {
            key: tallies.running.get(name, {}).get(key, Decimal(0)) + value
            for key, value in values.items()
        }
        for name, values in flows.items()
    }
    measures: dict[str, dict[str, Decimal | None]] = {
        name: dict(values) for name, values in flows.items() if name in MEASURE_KINDS
    }
    measures |= {
        name: dict(group_levels(name, values, groups, world))
        for name, values in levels(period).items()
    }
    for name, above, below in RATIOS:
        measures[name] = {
            key: ratio(running[above][key], running[below][key])
            for key in running[below]
        }
    # The next period reads only the orders open now or due later: an order ships,
    # is lost or pays a penalty while open, and counts as past due in its due period.
    not_yet_due = {
        order_id
        for order_id, order in period.customer_orders.items()
        if order.due > closed.period
    }
    kept = not_yet_due | {order.id for order in closed.customer_orders}
    new_tallies = Tallies(
        customer_orders=MappingProxyType(
            {
                order_id: order
                for order_id, order in period.customer_orders.items()
                if order_id in kept
            }
        ),
        supplier_orders=MappingProxyType(
            {order.id: order for order in closed.supplier_orders}
        ),
        shipped_on_time=MappingProxyType(
            {
                order_id: units
                for order_id, units in shipped_on_time.items()
                if order_id in not_yet_due
            }
        ),
        running=read_only_copy(running),
    )
    return replace(closed, tallies=new_tallies, measures=read_only_copy(measures))
