"""The observation: what the agent sees in a period.

Examples:
    >>> forecasts_seen((Decimal("4.000"), Decimal("5.000")), 3)[1]
    ForecastSeen(period=5, quantity=Decimal('5.000'))
"""

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType

from factory_simulator.engine.models.state import (
    ForecastSeen,
    LineHours,
    Observation,
    ProductionSeen,
    State,
    SupplierOrder,
    SupplierOrderSeen,
    WarehouseSpace,
)
from factory_simulator.engine.models.world import World
from factory_simulator.engine.rules.disruptions import is_visible
from factory_simulator.engine.rules.lines import line_limits, overtime_limit
from factory_simulator.engine.rules.space import reserved_space, stock_space
from factory_simulator.engine.rules.suppliers import lead_time_used
from factory_simulator.engine.rules.targets import targets_of


def build_observation(state: State, world: World) -> State:
    """Build the observation of the period.

    Args:
        state (State): The state.
        world (World): The world.

    Returns:
        State: The state holding its observation.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Factory,
        ...     Line,
        ...     LineItem,
        ...     Material,
        ...     Product,
        ...     Scenario,
        ...     Warehouse,
        ...     build_state,
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
        >>> world = draw_world(factory, Scenario(horizon=2), seed=0)
        >>> state = build_observation(replace(build_state(world), period=1), world)
        >>> state.observation.lines["press"].regular_hours_available
        Decimal('40.000')
    """
    observation = Observation(
        period=state.period,
        horizon=world.scenario.horizon,
        finished=state.finished,
        cash=state.cash,
        receivables=state.receivables,
        stock=state.stock,
        space=MappingProxyType(
            {
                warehouse_id: warehouse_space(warehouse_id, state, world)
                for warehouse_id in state.stock
            }
        ),
        lines=MappingProxyType(
            {line_id: line_hours(line_id, state, world) for line_id in state.condition}
        ),
        production=tuple(
            ProductionSeen(
                id=made.id,
                line=made.line,
                item=made.item,
                recipe=made.recipe,
                started=made.started,
                ready=made.ready,
            )
            for made in state.production
        ),
        plans=state.plans,
        transfers=state.transfers,
        customer_orders=state.customer_orders,
        supplier_orders=tuple(
            supplier_order_seen(order, world) for order in state.supplier_orders
        ),
        disruptions=tuple(
            replace(disruption, target=targets_of(disruption, world), group=None)
            for disruption in world.disruptions
            if is_visible(disruption, state.period)
            and state.period <= disruption.start + disruption.duration - 1
        ),
        forecasts=MappingProxyType(
            {
                key: forecasts_seen(rows[state.period - 1], state.period)
                for key, rows in world.forecasts.items()
            }
        ),
        prices=prices_seen(state.period, world),
        outcomes=state.outcomes,
        events=state.events,
    )
    return replace(state, observation=observation)


def prices_seen(period: int, world: World) -> Mapping[str, Mapping[str, Decimal]]:
    """Give the prices of a period that are drawn once per period.

    Args:
        period (int): The period, from 1.
        world (World): The world.

    Returns:
        Mapping[str, Mapping[str, Decimal]]: Per supplier and material, the price of
            the period; empty when no price is drawn once per period.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario
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
        >>> world = World(
        ...     factory=factory,
        ...     scenario=Scenario(horizon=2),
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ...     prices={"mill/steel": (Decimal("2.3"), Decimal("2.5"))},
        ... )
        >>> dict(prices_seen(2, world)["mill"])
        {'steel': Decimal('2.5')}
    """
    seen: dict[str, dict[str, Decimal]] = {}
    for entry_key, prices in world.prices.items():
        supplier_id, material_id = entry_key.split("/")
        seen.setdefault(supplier_id, {})[material_id] = prices[period - 1]
    return MappingProxyType(
        {
            supplier_id: MappingProxyType(entries)
            for supplier_id, entries in seen.items()
        }
    )


def forecasts_seen(
    row: tuple[Decimal | None, ...], period: int
) -> tuple[ForecastSeen, ...]:
    """Give the forecasts made in a period that lie within the horizon.

    Args:
        row (tuple[Decimal | None, ...]): The forecasts made in the period for the
            next periods, None past the horizon.
        period (int): The period they are made in.

    Returns:
        tuple[ForecastSeen, ...]: The forecasts, by period.

    Examples:
        >>> forecasts_seen((Decimal("4.000"), None), 9)
        (ForecastSeen(period=10, quantity=Decimal('4.000')),)
    """
    return tuple(
        ForecastSeen(period=period + ahead, quantity=quantity)
        for ahead, quantity in enumerate(row, start=1)
        if quantity is not None
    )


def warehouse_space(warehouse_id: str, state: State, world: World) -> WarehouseSpace:
    """Give the space a warehouse uses, reserves and has.

    Args:
        warehouse_id (str): The identifier of the warehouse.
        state (State): The state.
        world (World): The world.

    Returns:
        WarehouseSpace: The space of the stock, the space reserved and the capacity.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Factory,
        ...     Material,
        ...     Scenario,
        ...     Warehouse,
        ...     draw_world,
        ... )
        >>> zero = Decimal(0)
        >>> steel = Material(space=Decimal(2), storage_cost=zero, salvage_value=zero)
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
        >>> world = draw_world(factory, Scenario(horizon=1), seed=0)
        >>> state = State(
        ...     period=1,
        ...     cash=zero,
        ...     stock={"main": {"steel": Decimal(10)}},
        ...     condition={},
        ...     customer_orders=(),
        ... )
        >>> warehouse_space("main", state, world).used
        Decimal('20')
    """
    return WarehouseSpace(
        used=stock_space(state.stock[warehouse_id], world),
        reserved=reserved_space(
            warehouse_id,
            state.production,
            state.supplier_orders,
            state.transfers,
            world,
        ),
        capacity=world.factory.warehouses[warehouse_id].capacity,
    )


def line_hours(line_id: str, state: State, world: World) -> LineHours:
    """Give the condition of a line and the hours it has in the period.

    Args:
        line_id (str): The identifier of the line.
        state (State): The state.
        world (World): The world.

    Returns:
        LineHours: The condition, the item set for, and the hours available, the
            repair hours available and the overtime hours of the line, from
            `line_limits` and `overtime_limit`.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Factory,
        ...     Line,
        ...     LineItem,
        ...     Material,
        ...     Product,
        ...     Scenario,
        ...     Warehouse,
        ...     build_state,
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
        >>> world = draw_world(factory, Scenario(horizon=2), seed=0)
        >>> state = replace(build_state(world), period=1)
        >>> line_hours("press", state, world).regular_hours_available
        Decimal('40.000')
    """
    condition = state.condition[line_id]
    hours_available, repair_hours_available = line_limits(
        line_id, state.period, condition, world
    )
    return LineHours(
        condition=condition,
        set_for=state.set_for[line_id],
        regular_hours_available=hours_available,
        repair_hours_available=repair_hours_available,
        overtime_hours_available=overtime_limit(
            line_id, state.period, condition, world
        ),
    )


def supplier_order_seen(order: SupplierOrder, world: World) -> SupplierOrderSeen:
    """Give a supplier order without its private arrival period.

    Args:
        order (SupplierOrder): The order.
        world (World): The world.

    Returns:
        SupplierOrderSeen: The order with its expected arrival: `placed` plus the
            lead time used for an order placed by a buy, its arrival for a starting
            order.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     CatalogueEntry,
        ...     Factory,
        ...     Material,
        ...     Scenario,
        ...     Supplier,
        ...     Warehouse,
        ...     draw_world,
        ... )
        >>> zero, one = Decimal(0), Decimal(1)
        >>> entry = CatalogueEntry(
        ...     price=Decimal(2),
        ...     lead_time=1,
        ...     max_quantity=Decimal(100),
        ...     punctuality=one,
        ...     delay=0,
        ...     completeness=one,
        ...     acceptance=one,
        ... )
        >>> steel = Material(space=one, storage_cost=zero, salvage_value=zero)
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     components={},
        ...     products={},
        ...     suppliers={"mill": Supplier(catalogue={"steel": entry})},
        ...     customers={},
        ...     lines={},
        ...     warehouses={"main": Warehouse(capacity=Decimal(1000))},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=2), seed=0)
        >>> order = SupplierOrder(
        ...     id="buy-1-1",
        ...     supplier="mill",
        ...     material="steel",
        ...     warehouse="main",
        ...     quantity=Decimal(10),
        ...     open_quantity=Decimal(10),
        ...     unit_price=Decimal(2),
        ...     express=False,
        ...     placed=1,
        ...     arrival=3,
        ... )
        >>> supplier_order_seen(order, world).expected_arrival
        2
    """
    expected_arrival = order.arrival
    if order.placed > 0:
        expected_arrival = order.placed + lead_time_used(order, world)
    return SupplierOrderSeen(
        id=order.id,
        supplier=order.supplier,
        material=order.material,
        warehouse=order.warehouse,
        quantity=order.quantity,
        open_quantity=order.open_quantity,
        unit_price=order.unit_price,
        express=order.express,
        placed=order.placed,
        expected_arrival=expected_arrival,
    )
