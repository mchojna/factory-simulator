"""The plant: what decisions change in a period, its space held and line hours.

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
    >>> plant.period
    1
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from factory_simulator.engine.models.state import (
    CustomerOrder,
    Plan,
    Production,
    Receivable,
    SupplierOrder,
    TransferOnTheWay,
)
from factory_simulator.engine.models.world import World
from factory_simulator.engine.rules.lines import line_limits, overtime_limit
from factory_simulator.engine.rules.space import reserved_space, stock_space


@dataclass(slots=True, kw_only=True)
class Plant:
    """What the decisions of a period change: stock, hours, production and orders.

    Attributes:
        period (int): The period.
        stock (dict[str, dict[str, Decimal]]): Stock per warehouse and item.
        customer_orders (dict[str, CustomerOrder]): Open customer orders by
            identifier.
        receivables (list[Receivable]): Unpaid receivables.
        condition (Mapping[str, Decimal]): Condition per line in the period.
        set_for (dict[str, str | None]): The item each line is set for, or None.
        hours (dict[str, Decimal]): Regular production hours used per line in the
            period.
        changeover_hours (dict[str, Decimal]): Changeover hours used per line in the
            period.
        overtime_hours (dict[str, Decimal]): Overtime hours used per line in the
            period.
        repair_hours (dict[str, Decimal]): Repair hours used per line in the period.
        repairs (dict[str, Decimal]): Condition restored per line in the period.
        production (list[Production]): Production not yet in stock: earlier
            production by identifier, then what `execute_decisions` starts, in order.
        plans (list[Plan]): Plans not yet run, by identifier.
        supplier_orders (list[SupplierOrder]): Open supplier orders, by identifier.
        transfers (list[TransferOnTheWay]): Transfers on the way, by identifier.
        transferred_in (dict[str, dict[str, Decimal]]): Units that transfers of lead
            time 0 brought into each warehouse in the period, per item, empty when
            not given.

    Examples:
        >>> plant = Plant(
        ...     period=1,
        ...     stock={"main": {}},
        ...     customer_orders={},
        ...     receivables=[],
        ...     condition={"press": Decimal(1)},
        ...     set_for={"press": None},
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
        >>> plant.set_for["press"] is None, plant.transferred_in
        (True, {})
    """

    period: int
    stock: dict[str, dict[str, Decimal]]
    customer_orders: dict[str, CustomerOrder]
    receivables: list[Receivable]
    condition: Mapping[str, Decimal]
    set_for: dict[str, str | None]
    hours: dict[str, Decimal]
    changeover_hours: dict[str, Decimal]
    overtime_hours: dict[str, Decimal]
    repair_hours: dict[str, Decimal]
    repairs: dict[str, Decimal]
    production: list[Production]
    plans: list[Plan]
    supplier_orders: list[SupplierOrder]
    transfers: list[TransferOnTheWay]
    transferred_in: dict[str, dict[str, Decimal]] = field(
        default_factory=dict[str, dict[str, Decimal]]
    )


def remaining_hours(line_id: str, plant: Plant, world: World) -> Decimal:
    """Give the production hours a line has left in the period.

    The hours available bound production and changeover hours; the repair hours
    available bound production, changeover and repair hours. Both come from
    `line_limits`.

    Args:
        line_id (str): The identifier of the line.
        plant (Plant): The condition and the hours used of every line.
        world (World): The world.

    Returns:
        Decimal: The smaller remainder of the two.

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
        ...     parameters={"lines.press.capacity": Decimal(40)},
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
        ...     condition={"press": Decimal("0.5")},
        ...     set_for={},
        ...     hours={"press": Decimal(5)},
        ...     changeover_hours={},
        ...     overtime_hours={},
        ...     repair_hours={},
        ...     repairs={},
        ...     production=[],
        ...     plans=[],
        ...     supplier_orders=[],
        ...     transfers=[],
        ... )
        >>> remaining_hours("press", plant, world)
        Decimal('15.000')
    """
    hours_available, _ = line_limits(
        line_id, plant.period, plant.condition[line_id], world
    )
    production = plant.hours.get(line_id, Decimal(0)) + plant.changeover_hours.get(
        line_id, Decimal(0)
    )
    return min(hours_available - production, repair_hours_left(line_id, plant, world))


def repair_hours_left(line_id: str, plant: Plant, world: World) -> Decimal:
    """Give the hours a line has left for a repair in the period.

    They are the repair hours available less production, changeover and repair hours.

    Args:
        line_id (str): The identifier of the line.
        plant (Plant): The condition and the hours used of every line.
        world (World): The world.

    Returns:
        Decimal: The repair hours available less the hours used.

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
        ...     parameters={"lines.press.capacity": Decimal(40)},
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
        ...     condition={"press": Decimal("0.5")},
        ...     set_for={},
        ...     hours={},
        ...     changeover_hours={},
        ...     overtime_hours={},
        ...     repair_hours={"press": Decimal(3)},
        ...     repairs={},
        ...     production=[],
        ...     plans=[],
        ...     supplier_orders=[],
        ...     transfers=[],
        ... )
        >>> repair_hours_left("press", plant, world)
        Decimal('37.000')
    """
    _, repair_hours_available = line_limits(
        line_id, plant.period, plant.condition[line_id], world
    )
    return (
        repair_hours_available
        - plant.hours.get(line_id, Decimal(0))
        - plant.changeover_hours.get(line_id, Decimal(0))
        - plant.repair_hours.get(line_id, Decimal(0))
    )


def remaining_overtime_hours(line_id: str, plant: Plant, world: World) -> Decimal:
    """Give the overtime hours a line has left in the period.

    Args:
        line_id (str): The identifier of the line.
        plant (Plant): The condition and the overtime hours used of every line.
        world (World): The world.

    Returns:
        Decimal: The overtime hours from `overtime_limit` less the overtime hours
            used.

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
        ...     parameters={"lines.press.overtime_hours": Decimal(8)},
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
        ...     condition={"press": Decimal("0.5")},
        ...     set_for={},
        ...     hours={},
        ...     changeover_hours={},
        ...     overtime_hours={"press": Decimal(1)},
        ...     repair_hours={},
        ...     repairs={},
        ...     production=[],
        ...     plans=[],
        ...     supplier_orders=[],
        ...     transfers=[],
        ... )
        >>> remaining_overtime_hours("press", plant, world)
        Decimal('3.000')
    """
    overtime_hours_limit = overtime_limit(
        line_id, plant.period, plant.condition[line_id], world
    )
    return overtime_hours_limit - plant.overtime_hours.get(line_id, Decimal(0))


def space_held(warehouse_id: str, plant: Plant, world: World) -> Decimal:
    """Give the space held in a warehouse: stock, production and open orders.

    Args:
        warehouse_id (str): The identifier of the warehouse.
        plant (Plant): Stock, production and supplier orders.
        world (World): The world.

    Returns:
        Decimal: The space held.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Material, Scenario
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> steel = Material(space=Decimal(2), storage_cost=zero, salvage_value=zero)
        >>> factory = Factory(
        ...     materials={"steel": steel},
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
        ...     stock={"main": {"steel": Decimal(5)}},
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
        >>> space_held("main", plant, world)
        Decimal('10')
    """
    in_stock = stock_space(plant.stock[warehouse_id], world)
    return in_stock + reserved_space(
        warehouse_id, plant.production, plant.supplier_orders, plant.transfers, world
    )
