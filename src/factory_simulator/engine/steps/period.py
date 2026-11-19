"""The period: the state before period 1, its start and end, and its outcomes.

Examples:
    >>> FULL_CONDITION
    Decimal('1.0000')
"""

from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType
from typing import cast

from factory_simulator.engine.changes import ZERO_QUANTITY
from factory_simulator.engine.measures.period import first_tallies
from factory_simulator.engine.models.decisions import Decisions
from factory_simulator.engine.models.manifest import read_only_copy
from factory_simulator.engine.models.state import Outcome, State, SupplierOrder
from factory_simulator.engine.models.world import World
from factory_simulator.engine.numbers import in_decimal_context, round_to
from factory_simulator.engine.rules.items import default_warehouse, is_accepted
from factory_simulator.engine.rules.suppliers import catalogue_price
from factory_simulator.engine.steps.close import close_period
from factory_simulator.engine.steps.deliveries import receive_deliveries
from factory_simulator.engine.steps.events import apply_events, build_customer_order
from factory_simulator.engine.steps.execution import execute_decisions
from factory_simulator.engine.steps.observation import build_observation
from factory_simulator.engine.traces import trace_step

FULL_CONDITION = Decimal("1.0000")


@in_decimal_context
def build_state(world: World) -> State:
    """Build the state before period 1 from the start of the scenario.

    Args:
        world (World): The world.

    Returns:
        State: The state of period 0.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ...     Factory,
        ...     Line,
        ...     LineItem,
        ...     Material,
        ...     Product,
        ...     Scenario,
        ...     Start,
        ...     Warehouse,
        ...     draw_world,
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
        >>> terms = CustomerProduct(
        ...     price=Decimal(5),
        ...     transport_cost=zero,
        ...     demand=Decimal(10),
        ...     lead_time=1,
        ...     patience=1,
        ...     late_penalty=zero,
        ...     lost_sale_penalty=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": Material(**stored)},
        ...     components={},
        ...     products={"bolt": Product(**stored, recipes={"r": {"steel": one}})},
        ...     suppliers={},
        ...     customers={"shop": Customer(products={"bolt": terms})},
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
        >>> world = draw_world(factory, Scenario(horizon=2, start=start), seed=0)
        >>> build_state(world).stock["main"]["steel"]
        Decimal('10')
    """
    factory = world.factory
    start = world.scenario.start
    items = sorted([*factory.materials, *factory.components, *factory.products])
    stock = {
        warehouse_id: {
            item_id: start.stock.get(warehouse_id, {}).get(item_id, ZERO_QUANTITY)
            for item_id in items
            if is_accepted(warehouse_id, item_id, factory)
        }
        for warehouse_id in sorted(factory.warehouses)
    }
    condition = {
        line_id: start.condition.get(line_id, FULL_CONDITION)
        for line_id in sorted(factory.lines)
    }
    customer_orders = tuple(
        build_customer_order(
            f"order-0-{position}",
            order.customer,
            order.product,
            order.quantity,
            0,
            order.due,
            world,
        )
        for position, order in enumerate(start.customer_orders, start=1)
    )
    supplier_orders = tuple(
        SupplierOrder(
            id=f"buy-0-{position}",
            supplier=order.supplier,
            material=order.material,
            warehouse=order.warehouse or cast(str, default_warehouse(factory)),
            quantity=order.quantity,
            open_quantity=order.quantity,
            unit_price=round_to(
                catalogue_price(order.supplier, order.material, 1, world), 4
            ),
            express=False,
            placed=0,
            arrival=order.arrival,
        )
        for position, order in enumerate(start.supplier_orders, start=1)
    )
    state = State(
        period=0,
        cash=start.cash,
        stock=read_only_copy(stock),
        condition=MappingProxyType(condition),
        set_for=MappingProxyType(
            {line_id: start.set_for.get(line_id) for line_id in sorted(factory.lines)}
        ),
        customer_orders=customer_orders,
        supplier_orders=supplier_orders,
    )
    return replace(state, tallies=first_tallies(state))


@in_decimal_context
def start_period(state: State, world: World) -> State:
    """Start the next period: receive deliveries, apply events, build the observation.

    Args:
        state (State): The state after the previous period.
        world (World): The world.

    Returns:
        State: The state in which decisions of the period are made.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ...     Factory,
        ...     Line,
        ...     LineItem,
        ...     Material,
        ...     Product,
        ...     Scenario,
        ...     Start,
        ...     Warehouse,
        ...     draw_world,
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
        >>> terms = CustomerProduct(
        ...     price=Decimal(5),
        ...     transport_cost=zero,
        ...     demand=Decimal(10),
        ...     lead_time=1,
        ...     patience=1,
        ...     late_penalty=zero,
        ...     lost_sale_penalty=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": Material(**stored)},
        ...     components={},
        ...     products={"bolt": Product(**stored, recipes={"r": {"steel": one}})},
        ...     suppliers={},
        ...     customers={"shop": Customer(products={"bolt": terms})},
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
        >>> world = draw_world(factory, Scenario(horizon=2, start=start), seed=0)
        >>> state = start_period(build_state(world), world)
        >>> state.customer_orders[0].quantity
        Decimal('10.000')
    """
    previous = state
    state = replace(
        state, period=state.period + 1, ledger=(), period_events=(), trace=()
    )
    state = trace_step(previous, receive_deliveries(state, world), "receive_deliveries")
    state = trace_step(state, apply_events(state, world), "apply_events")
    return trace_step(state, build_observation(state, world), "build_observation")


@in_decimal_context
def advance_period(state: State, world: World, decisions: Decisions) -> State:
    """Advance the period: execute the decisions, then close the period.

    Args:
        state (State): The state in which the decisions were made.
        world (World): The world.
        decisions (Decisions): The decisions of the period.

    Returns:
        State: The state after the close of the period.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ...     Factory,
        ...     Line,
        ...     LineItem,
        ...     Material,
        ...     Produce,
        ...     Product,
        ...     Scenario,
        ...     Start,
        ...     Warehouse,
        ...     draw_world,
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
        >>> terms = CustomerProduct(
        ...     price=Decimal(5),
        ...     transport_cost=zero,
        ...     demand=Decimal(10),
        ...     lead_time=1,
        ...     patience=1,
        ...     late_penalty=zero,
        ...     lost_sale_penalty=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": Material(**stored)},
        ...     components={},
        ...     products={"bolt": Product(**stored, recipes={"r": {"steel": one}})},
        ...     suppliers={},
        ...     customers={"shop": Customer(products={"bolt": terms})},
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
        >>> world = draw_world(factory, Scenario(horizon=2, start=start), seed=0)
        >>> make = Produce(
        ...     kind="produce",
        ...     line="press",
        ...     item="bolt",
        ...     quantity=Decimal(5),
        ...     recipe="r",
        ...     overtime=False,
        ...     start=None,
        ... )
        >>> decisions = Decisions(period=1, decisions=(make,))
        >>> state = start_period(build_state(world), world)
        >>> dict(advance_period(state, world, decisions).stock["main"])
        {'bolt': Decimal('5.000'), 'steel': Decimal('5.000')}
    """
    state = trace_step(state, state, "make_decisions", decisions)
    state = trace_step(
        state,
        execute_decisions(state, world, decisions),
        "execute_decisions",
        decisions,
    )
    return trace_step(state, close_period(state, world), "close_period")


@in_decimal_context
def build_outcomes(
    state: State, world: World, decisions: Decisions
) -> tuple[Outcome, ...]:
    """Build the outcomes of decisions as `execute_decisions` would, changing nothing.

    Args:
        state (State): The state in which the decisions are made.
        world (World): The world.
        decisions (Decisions): The decisions of the period.

    Returns:
        tuple[Outcome, ...]: The outcomes in execution order, plans of the period
            first.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ...     Factory,
        ...     Line,
        ...     LineItem,
        ...     Material,
        ...     Produce,
        ...     Product,
        ...     Scenario,
        ...     Start,
        ...     Warehouse,
        ...     draw_world,
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
        >>> terms = CustomerProduct(
        ...     price=Decimal(5),
        ...     transport_cost=zero,
        ...     demand=Decimal(10),
        ...     lead_time=1,
        ...     patience=1,
        ...     late_penalty=zero,
        ...     lost_sale_penalty=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": Material(**stored)},
        ...     components={},
        ...     products={"bolt": Product(**stored, recipes={"r": {"steel": one}})},
        ...     suppliers={},
        ...     customers={"shop": Customer(products={"bolt": terms})},
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
        >>> world = draw_world(factory, Scenario(horizon=2, start=start), seed=0)
        >>> make = Produce(
        ...     kind="produce",
        ...     line="press",
        ...     item="bolt",
        ...     quantity=Decimal(5),
        ...     recipe="r",
        ...     overtime=False,
        ...     start=None,
        ... )
        >>> decisions = Decisions(period=1, decisions=(make,))
        >>> state = start_period(build_state(world), world)
        >>> build_outcomes(state, world, decisions)[0].accepted
        True
    """
    return execute_decisions(state, world, decisions).outcomes
