"""The checks of a factory: the rules that join two or more parameters or objects.

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
    >>> check_factory(factory)
    Traceback (most recent call last):
    ...
    factory_simulator.engine.numbers.InputError: products: is empty
"""

from decimal import Decimal

from factory_simulator.engine.checks.groups import (
    check_accepted_groups,
    check_group_members,
    check_group_names,
    member_types,
)
from factory_simulator.engine.models.manifest import (
    ITEM_KINDS,
    CatalogueEntry,
    Factory,
    Range,
)
from factory_simulator.engine.numbers import InputError, in_decimal_context
from factory_simulator.engine.rules.items import is_accepted, line_warehouse
from factory_simulator.engine.rules.parameters import largest, smallest


@in_decimal_context
def check_factory(factory: Factory) -> None:
    """Refuse a factory whose parameters or objects break a rule that joins them.

    Args:
        factory (Factory): The factory read from a manifest.

    Raises:
        InputError: If a check fails, with the path and problem of the first one.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, Material
        >>> zero = Decimal(0)
        >>> steel = Material(space=zero, storage_cost=zero, salvage_value=zero)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
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
        >>> check_factory(factory)
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError: products: is empty
    """
    check_required_keys(factory)
    check_items_named_once(factory)
    check_group_names(factory)
    check_references(factory)
    check_default_recipes(factory)
    check_warehouses_named(factory)
    types = member_types(factory)
    check_accepted_groups(types, factory)
    check_everything_used(factory)
    check_rates_rise(factory)
    check_wear(factory)
    check_catalogue_entries(factory)
    check_overtime_costs(factory)
    check_discounts(factory)
    check_salvage_values(factory)
    check_group_members(types, factory)
    check_line_warehouses(factory)
    check_persistence(factory)


def check_required_keys(factory: Factory) -> None:
    """Refuse a factory that leaves out a key that other keys make required.

    A line names its warehouse when the manifest has several, and an item names its
    default recipe; reading a manifest fills it for an item of one recipe.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If a line leaves out its warehouse, at its `warehouse`; if an item
            leaves out its default recipe, at its `default_recipe`; the first one.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, MadeItem
        >>> zero = Decimal(0)
        >>> recipes = {"cut": {"rod": Decimal(1)}, "cast": {"rod": Decimal(2)}}
        >>> bolt = MadeItem(
        ...     space=zero, storage_cost=zero, salvage_value=zero, recipes=recipes
        ... )
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
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
        >>> check_required_keys(factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        products.bolt.default_recipe: is required with several recipes
    """
    for line_id, line in factory.lines.items():
        if line.warehouse is None and len(factory.warehouses) > 1:
            raise InputError(f"lines.{line_id}.warehouse: Field required")
    for kind in ("components", "products"):
        for item_id, item in getattr(factory, kind).items():
            path = f"{kind}.{item_id}.default_recipe"
            if item.default_recipe is not None or not item.recipes:
                continue
            if len(item.recipes) == 1:
                raise InputError(f"{path}: Field required")
            raise InputError(f"{path}: is required with several recipes")


def check_items_named_once(factory: Factory) -> None:
    """Refuse a factory in which two items take one identifier.

    Materials, components and products share one set of identifiers.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If two items take one identifier, at the second item.

    Examples:
        >>> from factory_simulator.engine.models.manifest import (
        ...     Cash,
        ...     MadeItem,
        ...     Material,
        ... )
        >>> zero = Decimal(0)
        >>> steel = Material(space=zero, storage_cost=zero, salvage_value=zero)
        >>> rod = MadeItem(
        ...     space=zero, storage_cost=zero, salvage_value=zero, recipes={}
        ... )
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     components={"steel": rod},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> check_items_named_once(factory)
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError: components.steel: names two items
    """
    seen: set[str] = set()
    for kind in ("materials", "components", "products"):
        for item_id in getattr(factory, kind):
            if item_id in seen:
                raise InputError(f"{kind}.{item_id}: names two items")
            seen.add(item_id)


def check_references(factory: Factory) -> None:
    """Refuse a factory in which a reference names no object of the right kind.

    Every component and product has a recipe with at least one input; a component
    recipe lists only materials, a product recipe only components; a catalogue holds
    materials, a line makes components and products, a customer buys products.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If a reference is wrong, at the key that holds the first one.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, MadeItem
        >>> zero = Decimal(0)
        >>> recipes = {"cut": {"bolt": Decimal(1)}}
        >>> rod = MadeItem(
        ...     space=zero, storage_cost=zero, salvage_value=zero, recipes=recipes
        ... )
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={"rod": rod},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> check_references(factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        components.rod.recipes.cut.bolt: is not an input of this kind of item
    """
    made = {**factory.components, **factory.products}
    for kind, inputs in (
        ("components", factory.materials),
        ("products", factory.components),
    ):
        for item_id, item in getattr(factory, kind).items():
            if not item.recipes:
                raise InputError(f"{kind}.{item_id}.recipes: has no recipe")
            for recipe_id, recipe in item.recipes.items():
                if not recipe:
                    raise InputError(
                        f"{kind}.{item_id}.recipes.{recipe_id}: has no input"
                    )
                for input_id in recipe:
                    if input_id not in inputs:
                        raise InputError(
                            f"{kind}.{item_id}.recipes.{recipe_id}.{input_id}: "
                            "is not an input of this kind of item"
                        )
    for supplier_id, supplier in factory.suppliers.items():
        for material_id in supplier.catalogue:
            if material_id not in factory.materials:
                raise InputError(
                    f"suppliers.{supplier_id}.catalogue.{material_id}: "
                    "is not a material"
                )
    for line_id, line in factory.lines.items():
        for item_id in line.items:
            if item_id not in made:
                raise InputError(
                    f"lines.{line_id}.items.{item_id}: is not a component or product"
                )
    for customer_id, customer in factory.customers.items():
        for product_id in customer.products:
            if product_id not in factory.products:
                raise InputError(
                    f"customers.{customer_id}.products.{product_id}: is not a product"
                )


def check_default_recipes(factory: Factory) -> None:
    """Refuse a factory whose item names a default recipe it does not have.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If the default recipe of an item is not one of its recipes, at
            `default_recipe` of the first such item.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, MadeItem
        >>> zero = Decimal(0)
        >>> recipes = {"cut": {"rod": Decimal(1)}, "cast": {"rod": Decimal(2)}}
        >>> bolt = MadeItem(
        ...     space=zero,
        ...     storage_cost=zero,
        ...     salvage_value=zero,
        ...     recipes=recipes,
        ...     default_recipe="forge",
        ... )
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
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
        >>> check_default_recipes(factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        products.bolt.default_recipe: is not one of the recipes
    """
    for kind in ("components", "products"):
        for item_id, item in getattr(factory, kind).items():
            if item.default_recipe is None:
                continue
            if item.default_recipe not in item.recipes:
                raise InputError(
                    f"{kind}.{item_id}.default_recipe: is not one of the recipes"
                )


def check_warehouses_named(factory: Factory) -> None:
    """Refuse a factory whose lines, routes or warehouses name warehouses wrongly.

    A line names a warehouse of the manifest. `accepts` lists kinds of item and
    groups of items, at least one and each once. A route joins two different
    warehouses.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If a line warehouse, `accepts` or route is wrong, at the first one.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, Route, Warehouse
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
        ...     cash=cash,
        ...     warehouses={"main": Warehouse(capacity=Decimal(100))},
        ...     routes={"main": {"main": Route(cost=Decimal(1), lead_time=1)}},
        ... )
        >>> check_warehouses_named(factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        routes.main.main: joins a warehouse to itself
    """
    for line_id, line in factory.lines.items():
        if line.warehouse is not None and line.warehouse not in factory.warehouses:
            raise InputError(f"lines.{line_id}.warehouse: names no warehouse")
    for warehouse_id, warehouse in factory.warehouses.items():
        path = f"warehouses.{warehouse_id}.accepts"
        entries = (*warehouse.accepts, *warehouse.accepted_groups)
        if not entries:
            raise InputError(f"{path}: is empty")
        if len(set(warehouse.accepts)) < len(warehouse.accepts) or len(
            set(warehouse.accepted_groups)
        ) < len(warehouse.accepted_groups):
            raise InputError(f"{path}: repeats an entry")
        for kind in warehouse.accepts:
            if kind not in ITEM_KINDS:
                raise InputError(
                    f"{path}: {kind} is not one of {', '.join(ITEM_KINDS)}"
                )
    for source, reached in factory.routes.items():
        if source not in factory.warehouses:
            raise InputError(f"routes.{source}: {source} is not a warehouse")
        for destination in reached:
            path = f"routes.{source}.{destination}"
            if destination not in factory.warehouses:
                raise InputError(f"{path}: {destination} is not a warehouse")
            if source == destination:
                raise InputError(f"{path}: joins a warehouse to itself")


def check_everything_used(factory: Factory) -> None:
    """Refuse a factory in which an item is not used or a list is empty.

    The factory has a product, a material is in a catalogue, a component or product
    is made by a line, a product is bought by a customer, and no list is empty.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If the factory has no product, a material is in no catalogue, a
            component or product is made by no line, a product is bought by no
            customer, or a list is empty, at the first such item or list.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, Material
        >>> zero = Decimal(0)
        >>> steel = Material(space=zero, storage_cost=zero, salvage_value=zero)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
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
        >>> check_everything_used(factory)
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError: products: is empty
    """
    if not factory.products:
        raise InputError("products: is empty")
    bought = {
        material_id
        for supplier in factory.suppliers.values()
        for material_id in supplier.catalogue
    }
    made = {item_id for line in factory.lines.values() for item_id in line.items}
    sold = {
        product_id
        for customer in factory.customers.values()
        for product_id in customer.products
    }
    for material_id in factory.materials:
        if material_id not in bought:
            raise InputError(f"materials.{material_id}: is in no catalogue")
    for kind in ("components", "products"):
        for item_id in getattr(factory, kind):
            if item_id not in made:
                raise InputError(f"{kind}.{item_id}: is made by no line")
    for product_id in factory.products:
        if product_id not in sold:
            raise InputError(f"products.{product_id}: is bought by no customer")
    for supplier_id, supplier in factory.suppliers.items():
        if not supplier.catalogue:
            raise InputError(f"suppliers.{supplier_id}.catalogue: is empty")
    for line_id, line in factory.lines.items():
        if not line.items:
            raise InputError(f"lines.{line_id}.items: is empty")
    for customer_id, customer in factory.customers.items():
        if not customer.products:
            raise InputError(f"customers.{customer_id}.products: is empty")


def check_rates_rise(factory: Factory) -> None:
    """Refuse a factory whose credit, debit and overdraft interest fall in that order.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If a rate is below the one before it, at the first one.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash
        >>> cash = Cash(
        ...     credit_limit=Decimal(0),
        ...     credit_interest=Decimal("0.02"),
        ...     debit_interest=Decimal("0.01"),
        ...     overdraft_interest=Decimal("0.03"),
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
        >>> check_rates_rise(factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        cash.debit_interest: is below credit_interest
    """
    cash = factory.cash
    if cash.debit_interest < cash.credit_interest:
        raise InputError("cash.debit_interest: is below credit_interest")
    if cash.overdraft_interest < cash.debit_interest:
        raise InputError("cash.overdraft_interest: is below debit_interest")


def check_wear(factory: Factory) -> None:
    """Refuse a factory whose line, worked at full capacity and overtime, wears below 0.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If the largest wear per hour of a line times its largest
            capacity and overtime hours is above 1 less its largest wear per period,
            at `wear_per_hour` of the first such line.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, Line
        >>> zero = Decimal(0)
        >>> press = Line(
        ...     capacity=Decimal(40),
        ...     wear_per_period=zero,
        ...     wear_per_hour=Decimal("0.03"),
        ...     breakdown_chance=zero,
        ...     breakdown_loss=zero,
        ...     repair_cost=zero,
        ...     repair_time=zero,
        ...     repair_limit=Decimal(1),
        ...     items={},
        ... )
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
        ...     lines={"press": press},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> check_wear(factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        lines.press.wear_per_hour: wears more than the condition left
    """
    for line_id, line in factory.lines.items():
        hours = largest(line.capacity) + largest(line.overtime_hours)
        worn = largest(line.wear_per_hour) * hours
        if worn > 1 - largest(line.wear_per_period):
            raise InputError(
                f"lines.{line_id}.wear_per_hour: wears more than the condition left"
            )


def lowest_price(entry: CatalogueEntry) -> Decimal:
    """Give the lowest price of a catalogue entry, discounts included.

    Args:
        entry (CatalogueEntry): The entry.

    Returns:
        Decimal: The smallest value of its price and of every tier price.

    Examples:
        >>> from factory_simulator.engine.models.manifest import DiscountTier
        >>> entry = CatalogueEntry(
        ...     price=Decimal(2),
        ...     lead_time=1,
        ...     max_quantity=Decimal(100),
        ...     punctuality=Decimal(1),
        ...     delay=0,
        ...     completeness=Decimal(1),
        ...     acceptance=Decimal(1),
        ...     discounts=(DiscountTier(from_=Decimal(50), price=Decimal("1.50")),),
        ... )
        >>> lowest_price(entry)
        Decimal('1.50')
    """
    return min(
        [smallest(entry.price), *(smallest(tier.price) for tier in entry.discounts)]
    )


def check_catalogue_entries(factory: Factory) -> None:
    """Refuse a factory whose express terms or cancellation fees do not fit their entry.

    The rules: the largest `express_lead_time` is below the smallest `lead_time`;
    `express_cost` is given exactly with `express_lead_time`; the largest
    `cancellation_fee` is not above the lowest price.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If an entry breaks one of the rules above, at the first key of
            the first such entry.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, Supplier
        >>> entry = CatalogueEntry(
        ...     price=Decimal(2),
        ...     lead_time=1,
        ...     max_quantity=Decimal(100),
        ...     punctuality=Decimal(1),
        ...     delay=0,
        ...     completeness=Decimal(1),
        ...     acceptance=Decimal(1),
        ...     cancellation_fee=Decimal(3),
        ... )
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
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ...     suppliers={"mill": Supplier(catalogue={"steel": entry})},
        ... )
        >>> check_catalogue_entries(factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        suppliers.mill.catalogue.steel.cancellation_fee: is above the lowest price
    """
    for supplier_id, supplier in factory.suppliers.items():
        for material_id, entry in supplier.catalogue.items():
            path = f"suppliers.{supplier_id}.catalogue.{material_id}"
            express = entry.express_lead_time
            if express is not None and largest(express) >= smallest(entry.lead_time):
                raise InputError(
                    f"{path}.express_lead_time: is not below the lead time"
                )
            if express is None and entry.express_cost is not None:
                raise InputError(f"{path}.express_cost: needs express_lead_time")
            if express is not None and entry.express_cost is None:
                raise InputError(f"{path}.express_cost: is required with express")
            if largest(entry.cancellation_fee) > lowest_price(entry):
                raise InputError(f"{path}.cancellation_fee: is above the lowest price")


def check_overtime_costs(factory: Factory) -> None:
    """Refuse a factory whose line has overtime hours without a cost, or the reverse.

    A line that can work overtime has an overtime cost; a line whose overtime hours
    are left out or fixed at 0 has none.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If the largest `overtime_hours` of a line is above 0 without
            `overtime_cost`, or `overtime_hours` is left out or fixed at 0 with it,
            at `overtime_cost` of the first such line.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, Line
        >>> zero = Decimal(0)
        >>> press = Line(
        ...     capacity=Decimal(40),
        ...     wear_per_period=zero,
        ...     wear_per_hour=zero,
        ...     breakdown_chance=zero,
        ...     breakdown_loss=zero,
        ...     repair_cost=zero,
        ...     repair_time=zero,
        ...     repair_limit=Decimal(1),
        ...     items={},
        ...     overtime_hours=Decimal(8),
        ... )
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
        ...     lines={"press": press},
        ...     warehouses={},
        ...     cash=cash,
        ... )
        >>> check_overtime_costs(factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        lines.press.overtime_cost: is required
    """
    for line_id, line in factory.lines.items():
        path = f"lines.{line_id}.overtime_cost"
        if largest(line.overtime_hours) > 0 and line.overtime_cost is None:
            raise InputError(f"{path}: is required")
        if line.overtime_hours == 0 and line.overtime_cost is not None:
            raise InputError(f"{path}: needs overtime_hours")


def check_discounts(factory: Factory) -> None:
    """Refuse a factory whose discount tiers or minimum quantities do not fit an entry.

    The rules: tiers rise in `from` and fall in price; the first tier price is below
    `price`; a tier `from` is from `min_quantity` to `max_quantity`; `min_quantity` is
    not above `max_quantity`. Every rule takes the worst bound of a range.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If an entry breaks one of the rules above, at the first key of
            the first such entry.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, Supplier
        >>> entry = CatalogueEntry(
        ...     price=Decimal(2),
        ...     lead_time=1,
        ...     max_quantity=Decimal(100),
        ...     punctuality=Decimal(1),
        ...     delay=0,
        ...     completeness=Decimal(1),
        ...     acceptance=Decimal(1),
        ...     min_quantity=Decimal(200),
        ... )
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
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ...     suppliers={"mill": Supplier(catalogue={"steel": entry})},
        ... )
        >>> check_discounts(factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        suppliers.mill.catalogue.steel.min_quantity: is above max_quantity
    """
    for supplier_id, supplier in factory.suppliers.items():
        for material_id, entry in supplier.catalogue.items():
            path = f"suppliers.{supplier_id}.catalogue.{material_id}"
            check_tiers(entry, path)
            minimum = Decimal(0)
            if entry.min_quantity is not None:
                minimum = largest(entry.min_quantity)
            for position, tier in enumerate(entry.discounts):
                if not minimum <= tier.from_ <= smallest(entry.max_quantity):
                    raise InputError(
                        f"{path}.discounts.{position}.from: is outside the minimum and "
                        "maximum quantity"
                    )
            if minimum > smallest(entry.max_quantity):
                raise InputError(f"{path}.min_quantity: is above max_quantity")


def check_tiers(entry: CatalogueEntry, path: str) -> None:
    """Refuse a catalogue entry whose tiers do not rise in `from` and fall in price.

    The first tier price is also below `price`.

    Args:
        entry (CatalogueEntry): The catalogue entry.
        path (str): Its dotted path.

    Raises:
        InputError: If a tier breaks a rule, at the `from` or the price of the first
            such tier.

    Examples:
        >>> from factory_simulator.engine.models.manifest import DiscountTier
        >>> entry = CatalogueEntry(
        ...     price=Decimal(2),
        ...     lead_time=1,
        ...     max_quantity=Decimal(100),
        ...     punctuality=Decimal(1),
        ...     delay=0,
        ...     completeness=Decimal(1),
        ...     acceptance=Decimal(1),
        ...     discounts=(DiscountTier(from_=Decimal(50), price=Decimal("2.50")),),
        ... )
        >>> path = "suppliers.mill.catalogue.steel"
        >>> check_tiers(entry, path)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        suppliers.mill.catalogue.steel.discounts.0.price: is not below the price
    """
    tiers = entry.discounts
    for position in range(1, len(tiers)):
        if tiers[position].from_ <= tiers[position - 1].from_:
            raise InputError(f"{path}.discounts.{position}.from: does not rise")
        if largest(tiers[position].price) >= smallest(tiers[position - 1].price):
            raise InputError(f"{path}.discounts.{position}.price: does not fall")
    if tiers and largest(tiers[0].price) >= smallest(entry.price):
        raise InputError(f"{path}.discounts.0.price: is not below the price")


def check_salvage_values(factory: Factory) -> None:
    """Refuse a factory in which an item is worth more at the end than it costs.

    No item is worth more at the end than it costs to buy or make.

    A material is bounded by its lowest price; a component or product by the smallest
    sum, over its recipes and the lines that make it, of the inputs of the recipe at
    their salvage values plus the cost of the line.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If the salvage value of an item is above its bound, at the
            first one.

    Examples:
        >>> from factory_simulator.engine.models.manifest import (
        ...     Cash,
        ...     Material,
        ...     Supplier,
        ... )
        >>> zero = Decimal(0)
        >>> steel = Material(space=zero, storage_cost=zero, salvage_value=Decimal(3))
        >>> entry = CatalogueEntry(
        ...     price=Decimal(2),
        ...     lead_time=1,
        ...     max_quantity=Decimal(100),
        ...     punctuality=Decimal(1),
        ...     delay=0,
        ...     completeness=Decimal(1),
        ...     acceptance=Decimal(1),
        ... )
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     components={},
        ...     products={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ...     suppliers={"mill": Supplier(catalogue={"steel": entry})},
        ... )
        >>> check_salvage_values(factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        materials.steel.salvage_value: is above its lowest price
    """
    for material_id, material in factory.materials.items():
        lowest = min(
            lowest_price(supplier.catalogue[material_id])
            for supplier in factory.suppliers.values()
            if material_id in supplier.catalogue
        )
        if largest(material.salvage_value) > lowest:
            raise InputError(
                f"materials.{material_id}.salvage_value: is above its lowest price"
            )
    inputs = {**factory.materials, **factory.components}
    for kind in ("components", "products"):
        for item_id, item in getattr(factory, kind).items():
            from_inputs = min(
                sum(
                    (
                        quantity * smallest(inputs[input_id].salvage_value)
                        for input_id, quantity in recipe.items()
                    ),
                    Decimal(0),
                )
                for recipe in item.recipes.values()
            )
            bound = min(
                from_inputs + smallest(line.items[item_id].cost)
                for line in factory.lines.values()
                if item_id in line.items
            )
            if largest(item.salvage_value) > bound:
                raise InputError(
                    f"{kind}.{item_id}.salvage_value: is above the value of its "
                    "inputs and the cost of making it"
                )


def check_line_warehouses(factory: Factory) -> None:
    """Refuse a factory in which a line misses an item or a material has no warehouse.

    Every line can reach its items, and every material has a warehouse.

    The warehouse of a line accepts every input and output of the line. A recipe
    input reaches it when it is a material, or a component made by a line at a
    warehouse from which routes through warehouses that accept it lead there.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If the warehouse of a line cannot hold or reach one of its items,
            at the warehouse of the first such line; if a material has no warehouse,
            at the first one.

    Examples:
        >>> from factory_simulator.engine.models.manifest import (
        ...     Cash,
        ...     Material,
        ...     Warehouse,
        ... )
        >>> zero = Decimal(0)
        >>> steel = Material(space=zero, storage_cost=zero, salvage_value=zero)
        >>> shelf = Warehouse(capacity=Decimal(100), accepts=("products",))
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> factory = Factory(
        ...     materials={"steel": steel},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={"shelf": shelf},
        ...     cash=cash,
        ... )
        >>> check_line_warehouses(factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        materials.steel: is accepted by no warehouse
    """
    for line_id, line in factory.lines.items():
        path = f"lines.{line_id}.warehouse"
        warehouse_id = line_warehouse(line_id, factory)
        for item_id in line.items:
            made = factory.components.get(item_id) or factory.products[item_id]
            inputs = {
                input_id for recipe in made.recipes.values() for input_id in recipe
            }
            for needed in sorted({item_id, *inputs}):
                if not is_accepted(warehouse_id, needed, factory):
                    raise InputError(f"{path}: does not accept {needed}")
            for input_id in sorted(inputs & set(factory.components)):
                made_at = {
                    line_warehouse(other_id, factory)
                    for other_id, other in factory.lines.items()
                    if input_id in other.items
                }
                if warehouse_id not in reachable(input_id, made_at, factory):
                    raise InputError(
                        f"{path}: {input_id} is not made at {warehouse_id}"
                    )
    for material_id in factory.materials:
        if not any(
            is_accepted(warehouse_id, material_id, factory)
            for warehouse_id in factory.warehouses
        ):
            raise InputError(f"materials.{material_id}: is accepted by no warehouse")


def reachable(item_id: str, sources: set[str], factory: Factory) -> set[str]:
    """Give the warehouses an item can reach from some warehouses along routes.

    Each step of the way ends in a warehouse that accepts the item.

    Args:
        item_id (str): The identifier of the item.
        sources (set[str]): The warehouses the item starts in.
        factory (Factory): The factory.

    Returns:
        set[str]: The sources and every warehouse reached from them.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash, Route, Warehouse
        >>> store = Warehouse(capacity=Decimal(100))
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
        ...     warehouses={"east": store, "west": store},
        ...     cash=cash,
        ...     routes={"east": {"west": Route(cost=Decimal(1), lead_time=1)}},
        ... )
        >>> sorted(reachable("rod", {"east"}, factory))
        ['east', 'west']
        >>> sorted(reachable("rod", {"west"}, factory))
        ['west']
    """
    reached = set(sources)
    waiting = sorted(sources)
    while waiting:
        source = waiting.pop()
        for destination in factory.routes.get(source, {}):
            if destination not in reached and is_accepted(
                destination, item_id, factory
            ):
                reached.add(destination)
                waiting.append(destination)
    return reached


def check_persistence(factory: Factory) -> None:
    """Refuse a factory with demand persistence or a common share but no demand range.

    Demand persistence and a common share go with ranges of demand.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If a customer product with a fixed demand gives
            `demand_persistence`, at it for the first such one; if a product that
            fewer than two customers buy with a range of demand has a `common_share`
            above 0, at it.

    Examples:
        >>> from factory_simulator.engine.models.manifest import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ... )
        >>> zero = Decimal(0)
        >>> terms = CustomerProduct(
        ...     price=Decimal(5),
        ...     transport_cost=zero,
        ...     demand=Decimal(10),
        ...     lead_time=1,
        ...     patience=1,
        ...     late_penalty=zero,
        ...     lost_sale_penalty=zero,
        ...     demand_persistence=Decimal("0.5"),
        ... )
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
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ...     customers={"shop": Customer(products={"bolt": terms})},
        ... )
        >>> check_persistence(factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        customers.shop.products.bolt.demand_persistence: is given for a fixed demand
    """
    for customer_id, customer in factory.customers.items():
        for product_id, terms in customer.products.items():
            if terms.demand_persistence is not None and not isinstance(
                terms.demand, Range
            ):
                raise InputError(
                    f"customers.{customer_id}.products.{product_id}"
                    ".demand_persistence: is given for a fixed demand"
                )
    for product_id, product in factory.products.items():
        if product.common_share and buyers_with_a_range(product_id, factory) < 2:
            raise InputError(
                f"products.{product_id}.common_share: is above 0 for a product that "
                "fewer than two customers buy with a demand range"
            )


def buyers_with_a_range(product_id: str, factory: Factory) -> int:
    """Give the number of customers that buy a product with a range of demand.

    Args:
        product_id (str): The identifier of the product.
        factory (Factory): The factory.

    Returns:
        int: The number of such customers.

    Examples:
        >>> from factory_simulator.engine.models.manifest import (
        ...     Cash,
        ...     Customer,
        ...     CustomerProduct,
        ... )
        >>> zero = Decimal(0)
        >>> terms = CustomerProduct(
        ...     price=Decimal(5),
        ...     transport_cost=zero,
        ...     lead_time=1,
        ...     patience=1,
        ...     late_penalty=zero,
        ...     lost_sale_penalty=zero,
        ...     demand=Range(min=Decimal("1.000"), max=Decimal("2.000")),
        ... )
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
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ...     customers={"shop": Customer(products={"bolt": terms})},
        ... )
        >>> buyers_with_a_range("bolt", factory)
        1
    """
    return sum(
        1
        for customer in factory.customers.values()
        if product_id in customer.products
        and isinstance(customer.products[product_id].demand, Range)
    )
