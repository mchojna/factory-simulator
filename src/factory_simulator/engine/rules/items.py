"""The rules of items and warehouses: kinds, paths, space, inputs and where items go.

Examples:
    >>> from factory_simulator.engine.models.manifest import Cash
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
    >>> items_of(factory)
    {}
"""

from collections.abc import Mapping
from decimal import ROUND_CEILING, Decimal

from factory_simulator.engine.models.manifest import Factory, MadeItem, Material
from factory_simulator.engine.models.world import World
from factory_simulator.engine.numbers import round_to


def items_of(factory: Factory) -> dict[str, Material | MadeItem]:
    """Give every material, component and product of a factory by identifier.

    Args:
        factory (Factory): The factory.

    Returns:
        dict[str, Material | MadeItem]: The items by identifier.

    Examples:
        >>> from factory_simulator.engine import Cash, Material
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
        >>> items_of(factory)["steel"].space
        Decimal('2')
    """
    return {**factory.materials, **factory.components, **factory.products}


def made_item(item_id: str, world: World) -> MadeItem:
    """Give a component or a product.

    Args:
        item_id (str): The identifier of the item.
        world (World): The world.

    Returns:
        MadeItem: The item.

    Examples:
        >>> from factory_simulator.engine import Cash, Scenario
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> bolt = MadeItem(
        ...     space=Decimal(3),
        ...     storage_cost=zero,
        ...     salvage_value=zero,
        ...     recipes={"r": {"rod": Decimal(1)}},
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={"bolt": bolt},
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
        >>> made_item("bolt", world).space
        Decimal('3')
    """
    return world.factory.components.get(item_id) or world.factory.products[item_id]


def space_of(item_id: str, world: World) -> Decimal:
    """Give the space one unit of an item takes.

    Args:
        item_id (str): The identifier of a material, component or product.
        world (World): The world.

    Returns:
        Decimal: The space per unit.

    Examples:
        >>> from factory_simulator.engine import Cash, Material, Scenario
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
        >>> space_of("steel", world)
        Decimal('2')
    """
    return items_of(world.factory)[item_id].space


def salvage_of(item_id: str, world: World) -> Decimal:
    """Give the salvage value of one unit of an item, as drawn for the run.

    Args:
        item_id (str): The identifier of a material, component or product.
        world (World): The world.

    Returns:
        Decimal: The salvage value per unit.

    Examples:
        >>> from factory_simulator.engine import Cash, Material, Range, Scenario
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> salvage = Range(min=Decimal(1), max=Decimal(3))
        >>> steel = Material(space=Decimal(2), storage_cost=zero, salvage_value=salvage)
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
        ...     parameters={"materials.steel.salvage_value": Decimal(2)},
        ...     drawn=frozenset(),
        ...     demand={},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> salvage_of("steel", world)
        Decimal('2')
    """
    return world.parameters[f"{item_path(item_id, world)}.salvage_value"]


def inputs_of(quantity: Decimal, recipe: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Give the inputs a quantity of an item takes from stock.

    Args:
        quantity (Decimal): Units to produce.
        recipe (Mapping[str, Decimal]): Units of each input per unit produced.

    Returns:
        dict[str, Decimal]: Units of each input, rounded up to 3 places.

    Examples:
        >>> inputs_of(Decimal(7), {"chip": Decimal("0.3333")})
        {'chip': Decimal('2.334')}
    """
    return {
        input_id: round_to(quantity * per_unit, 3, ROUND_CEILING)
        for input_id, per_unit in recipe.items()
    }


def kind_of(item_id: str, factory: Factory) -> str:
    """Give the kind of an item: `materials`, `components` or `products`.

    Args:
        item_id (str): The identifier of a material, component or product.
        factory (Factory): The factory.

    Returns:
        str: The kind, as `accepts` names it.

    Examples:
        >>> from factory_simulator.engine import Cash, Material
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
        >>> kind_of("steel", factory)
        'materials'
    """
    if item_id in factory.materials:
        return "materials"
    if item_id in factory.components:
        return "components"
    return "products"


def item_path(item_id: str, world: World) -> str:
    """Give the dotted path of an item in the factory.

    Args:
        item_id (str): The identifier of a material, component or product.
        world (World): The world.

    Returns:
        str: The path, such as "materials.chip".

    Examples:
        >>> from factory_simulator.engine import Cash, Material, Scenario
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
        >>> item_path("steel", world)
        'materials.steel'
    """
    return f"{kind_of(item_id, world.factory)}.{item_id}"


def is_accepted(warehouse_id: str, item_id: str, factory: Factory) -> bool:
    """Tell whether a warehouse holds an item.

    Args:
        warehouse_id (str): The identifier of the warehouse.
        item_id (str): The identifier of the item.
        factory (Factory): The factory.

    Returns:
        bool: True when the warehouse accepts the kind of the item or a group it is
            in.

    Examples:
        >>> from factory_simulator.engine import Cash, Material, Warehouse
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> steel = Material(space=Decimal(2), storage_cost=zero, salvage_value=zero)
        >>> store = Warehouse(capacity=zero, accepts=("products",))
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={"store": store},
        ...     cash=cash,
        ... )
        >>> is_accepted("store", "steel", factory)
        False
    """
    warehouse = factory.warehouses[warehouse_id]
    return kind_of(item_id, factory) in warehouse.accepts or any(
        item_id in factory.groups[group_id].members
        for group_id in warehouse.accepted_groups
    )


def line_warehouse(line_id: str, factory: Factory) -> str:
    """Give the warehouse of the inputs and output of a line.

    Args:
        line_id (str): The identifier of the line.
        factory (Factory): The factory.

    Returns:
        str: The warehouse the line names, or the only warehouse of the factory.

    Examples:
        >>> from factory_simulator.engine import Cash, Line, Warehouse
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> press = Line(
        ...     capacity=zero,
        ...     wear_per_period=zero,
        ...     wear_per_hour=zero,
        ...     breakdown_chance=zero,
        ...     breakdown_loss=zero,
        ...     repair_cost=zero,
        ...     repair_time=zero,
        ...     repair_limit=zero,
        ...     items={},
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={"press": press},
        ...     warehouses={"main": Warehouse(capacity=zero)},
        ...     cash=cash,
        ... )
        >>> line_warehouse("press", factory)
        'main'
    """
    return factory.lines[line_id].warehouse or next(iter(factory.warehouses))


def default_warehouse(factory: Factory) -> str | None:
    """Give the warehouse a decision without one names.

    Args:
        factory (Factory): The factory.

    Returns:
        str | None: The only warehouse of the factory, or None when it has several.

    Examples:
        >>> from factory_simulator.engine import Cash, Warehouse
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
        ...     warehouses={"main": Warehouse(capacity=zero)},
        ...     cash=cash,
        ... )
        >>> default_warehouse(factory)
        'main'
    """
    if len(factory.warehouses) == 1:
        return next(iter(factory.warehouses))
    return None
