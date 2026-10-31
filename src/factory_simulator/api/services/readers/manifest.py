"""The reader of a manifest: the factory of the engine and the content as written.

Examples:
    >>> to_route(Route(cost="0.8", lead_time=1)).lead_time
    1
"""

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from typing import cast

from pydantic import BaseModel

from factory_simulator import engine
from factory_simulator.api.core.numbers import validate
from factory_simulator.api.schemas.manifest import (
    AcceptedGroup,
    CatalogueEntry,
    Customer,
    CustomerProduct,
    DiscountTier,
    Group,
    GroupDefaults,
    Line,
    LineItem,
    LognormalPriceRange,
    LognormalRange,
    MadeItem,
    ManifestCreate,
    Material,
    NormalPriceRange,
    NormalRange,
    Product,
    Route,
    Supplier,
    TriangularPriceRange,
    TriangularRange,
    UniformPriceRange,
    UniformRange,
    Warehouse,
)
from factory_simulator.api.services.groups import resolve_groups

# A range model of any distribution.
type RangeModel[N: (Decimal, int)] = (
    UniformRange[N] | TriangularRange[N] | NormalRange[N] | LognormalRange[N]
)
# A range model of a price, of any distribution.
type PriceRangeModel = (
    UniformPriceRange | TriangularPriceRange | NormalPriceRange | LognormalPriceRange
)


def to_range[N: (Decimal, int)](value: RangeModel[N]) -> engine.Range[N]:
    """Convert a range of any distribution.

    Args:
        value (RangeModel[N]): The range model.

    Returns:
        Range[N]: The range for the engine.

    Examples:
        >>> to_range(UniformRange[int](min=1, max=3)).distribution
        'uniform'
    """
    if isinstance(value, TriangularRange):
        return engine.Range(
            min=value.min,
            max=value.max,
            distribution="triangular",
            mode=Decimal(value.mode),
        )
    if isinstance(value, NormalRange):
        return engine.Range(
            min=value.min,
            max=value.max,
            distribution="normal",
            mean=Decimal(value.mean),
            sd=Decimal(value.sd),
        )
    if isinstance(value, LognormalRange):
        return engine.Range(
            min=value.min,
            max=value.max,
            distribution="lognormal",
            median=Decimal(value.median),
            spread=value.spread,
        )
    return engine.Range(min=value.min, max=value.max)


def to_decimal_parameter(
    value: Decimal | RangeModel[Decimal],
) -> Decimal | engine.Range[Decimal]:
    """Convert a decimal parameter.

    Args:
        value (Decimal | RangeModel[Decimal]): A fixed decimal or a range model.

    Returns:
        Decimal | Range[Decimal]: The parameter for the engine.

    Examples:
        >>> to_decimal_parameter(Decimal("0.5000"))
        Decimal('0.5000')
    """
    if isinstance(value, Decimal):
        return value
    return to_range(value)


def to_price_parameter(
    value: Decimal | PriceRangeModel,
) -> Decimal | engine.Range[Decimal]:
    """Convert the price of a catalogue entry, with its moment of drawing.

    Args:
        value (Decimal | PriceRangeModel): A fixed decimal or a range model of a
            price.

    Returns:
        Decimal | Range[Decimal]: The price for the engine.

    Examples:
        >>> price = UniformPriceRange(min="2.2", max="2.6", drawn="period")
        >>> to_price_parameter(price).drawn
        'period'
    """
    if isinstance(value, Decimal):
        return value
    return replace(to_range(value), drawn=value.drawn)


def to_periods_parameter(value: int | RangeModel[int]) -> int | engine.Range[int]:
    """Convert a parameter of periods.

    Args:
        value (int | RangeModel[int]): A fixed whole number or a range model, which
            `uniform_only` keeps uniform.

    Returns:
        int | Range[int]: The parameter for the engine.

    Examples:
        >>> to_periods_parameter(UniformRange[int](min=1, max=3)).max
        3
    """
    if isinstance(value, int):
        return value
    return to_range(value)


def to_material(model: Material) -> engine.Material:
    """Convert a material.

    Args:
        model (Material): The model.

    Returns:
        Material: The dataclass.

    Examples:
        >>> material = Material(space="0.001", storage_cost="0.03", salvage_value="2.6")
        >>> to_material(material).space
        Decimal('0.001')
    """
    return engine.Material(
        space=model.space,
        storage_cost=to_decimal_parameter(model.storage_cost),
        salvage_value=to_decimal_parameter(model.salvage_value),
        groups=tuple(model.groups),
        name=model.name,
        description=model.description,
        unit=model.unit,
    )


def to_made_item(model: MadeItem) -> engine.MadeItem:
    """Convert a component or a product.

    Args:
        model (MadeItem): The model.

    Returns:
        MadeItem: The dataclass.

    Examples:
        >>> item = MadeItem(
        ...     space="0.01",
        ...     storage_cost="0.1",
        ...     salvage_value="5",
        ...     recipes={"standard": {"chip": "2"}},
        ... )
        >>> to_made_item(item).default_recipe
        'standard'
    """
    return engine.MadeItem(
        space=model.space,
        storage_cost=to_decimal_parameter(model.storage_cost),
        salvage_value=to_decimal_parameter(model.salvage_value),
        recipes=model.recipes,
        default_recipe=model.default_recipe,
        groups=tuple(model.groups),
        name=model.name,
        description=model.description,
        unit=model.unit,
    )


def to_product(model: Product) -> engine.Product:
    """Convert a product.

    Args:
        model (Product): The model.

    Returns:
        Product: The dataclass.

    Examples:
        >>> item = Product(
        ...     space="0.01",
        ...     storage_cost="0.1",
        ...     salvage_value="5",
        ...     recipes={"standard": {"board": "2"}},
        ...     common_share="0.6",
        ... )
        >>> to_product(item).common_share
        Decimal('0.6000')
    """
    return engine.Product(
        space=model.space,
        storage_cost=to_decimal_parameter(model.storage_cost),
        salvage_value=to_decimal_parameter(model.salvage_value),
        recipes=model.recipes,
        default_recipe=model.default_recipe,
        groups=tuple(model.groups),
        name=model.name,
        description=model.description,
        unit=model.unit,
        common_share=model.common_share,
    )


def to_catalogue_entry(model: CatalogueEntry) -> engine.CatalogueEntry:
    """Convert a catalogue entry.

    Args:
        model (CatalogueEntry): The model.

    Returns:
        CatalogueEntry: The dataclass.

    Examples:
        >>> entry = CatalogueEntry(
        ...     price="3.5",
        ...     lead_time=2,
        ...     max_quantity="1000",
        ...     punctuality="0.9",
        ...     delay=1,
        ...     completeness="1",
        ...     acceptance="1",
        ... )
        >>> to_catalogue_entry(entry).lead_time
        2
    """
    return engine.CatalogueEntry(
        price=to_price_parameter(model.price),
        lead_time=to_periods_parameter(model.lead_time),
        max_quantity=to_decimal_parameter(model.max_quantity),
        punctuality=to_decimal_parameter(model.punctuality),
        delay=to_periods_parameter(model.delay),
        completeness=to_decimal_parameter(model.completeness),
        acceptance=to_decimal_parameter(model.acceptance),
        cancellation_fee=to_decimal_parameter(model.cancellation_fee),
        backfill_delay=to_periods_parameter(model.backfill_delay),
        express_lead_time=(
            None
            if model.express_lead_time is None
            else to_periods_parameter(model.express_lead_time)
        ),
        express_cost=(
            None
            if model.express_cost is None
            else to_decimal_parameter(model.express_cost)
        ),
        min_quantity=(
            None
            if model.min_quantity is None
            else to_decimal_parameter(model.min_quantity)
        ),
        discounts=tuple(
            engine.DiscountTier(
                from_=tier.from_, price=to_decimal_parameter(tier.price)
            )
            for tier in model.discounts
        ),
    )


def to_supplier(model: Supplier) -> engine.Supplier:
    """Convert a supplier.

    Args:
        model (Supplier): The model.

    Returns:
        Supplier: The dataclass.

    Examples:
        >>> entry = CatalogueEntry(
        ...     price="3.5",
        ...     lead_time=2,
        ...     max_quantity="1000",
        ...     punctuality="0.9",
        ...     delay=1,
        ...     completeness="1",
        ...     acceptance="1",
        ... )
        >>> supplier = to_supplier(Supplier(catalogue={"chip": entry}))
        >>> supplier.catalogue["chip"].price
        Decimal('3.5000')
    """
    return engine.Supplier(
        catalogue={
            key: to_catalogue_entry(value) for key, value in model.catalogue.items()
        },
        groups=tuple(model.groups),
        name=model.name,
        description=model.description,
    )


def to_customer_product(model: CustomerProduct) -> engine.CustomerProduct:
    """Convert the terms of a customer and a product.

    Args:
        model (CustomerProduct): The model.

    Returns:
        CustomerProduct: The dataclass.

    Examples:
        >>> terms = CustomerProduct(
        ...     price="120",
        ...     transport_cost="1",
        ...     demand="50",
        ...     lead_time=1,
        ...     patience=2,
        ...     late_penalty="5",
        ...     lost_sale_penalty="10",
        ... )
        >>> to_customer_product(terms).demand
        Decimal('50.000')
    """
    return engine.CustomerProduct(
        price=to_decimal_parameter(model.price),
        transport_cost=to_decimal_parameter(model.transport_cost),
        demand=to_decimal_parameter(model.demand),
        lead_time=to_periods_parameter(model.lead_time),
        patience=to_periods_parameter(model.patience),
        late_penalty=to_decimal_parameter(model.late_penalty),
        lost_sale_penalty=to_decimal_parameter(model.lost_sale_penalty),
        demand_persistence=model.demand_persistence,
    )


def to_customer(model: Customer) -> engine.Customer:
    """Convert a customer.

    Args:
        model (Customer): The model.

    Returns:
        Customer: The dataclass.

    Examples:
        >>> terms = CustomerProduct(
        ...     price="120",
        ...     transport_cost="1",
        ...     demand="50",
        ...     lead_time=1,
        ...     patience=2,
        ...     late_penalty="5",
        ...     lost_sale_penalty="10",
        ... )
        >>> to_customer(Customer(products={"monitor": terms})).payment_terms
        0
    """
    return engine.Customer(
        products={
            key: to_customer_product(value) for key, value in model.products.items()
        },
        payment_terms=to_periods_parameter(model.payment_terms),
        groups=tuple(model.groups),
        name=model.name,
        description=model.description,
    )


def to_line_item(model: LineItem) -> engine.LineItem:
    """Convert how a line makes one item.

    Args:
        model (LineItem): The model.

    Returns:
        LineItem: The dataclass.

    Examples:
        >>> item = LineItem.model_validate(
        ...     {"time": "0.5", "cost": "2", "yield": "0.98"}
        ... )
        >>> to_line_item(item).yield_
        Decimal('0.9800')
    """
    return engine.LineItem(
        time=to_decimal_parameter(model.time),
        cost=to_decimal_parameter(model.cost),
        yield_=to_decimal_parameter(model.yield_),
        lead_time=to_periods_parameter(model.lead_time),
        changeover_time=(
            None
            if model.changeover_time is None
            else to_decimal_parameter(model.changeover_time)
        ),
        changeover_cost=(
            None
            if model.changeover_cost is None
            else to_decimal_parameter(model.changeover_cost)
        ),
    )


def to_line(model: Line) -> engine.Line:
    """Convert a line.

    Args:
        model (Line): The model.

    Returns:
        Line: The dataclass.

    Examples:
        >>> line = Line.model_validate(
        ...     {
        ...         "capacity": "80",
        ...         "wear_per_period": "0.01",
        ...         "wear_per_hour": "0.001",
        ...         "breakdown_chance": "0.05",
        ...         "breakdown_loss": "0.5",
        ...         "repair_cost": "100",
        ...         "repair_time": "4",
        ...         "repair_limit": "0.5",
        ...         "items": {"monitor": {"time": "0.5", "cost": "2", "yield": "0.98"}},
        ...     }
        ... )
        >>> to_line(line).capacity
        Decimal('80.000')
    """
    return engine.Line(
        capacity=to_decimal_parameter(model.capacity),
        wear_per_period=to_decimal_parameter(model.wear_per_period),
        wear_per_hour=to_decimal_parameter(model.wear_per_hour),
        breakdown_chance=to_decimal_parameter(model.breakdown_chance),
        breakdown_loss=to_decimal_parameter(model.breakdown_loss),
        repair_cost=to_decimal_parameter(model.repair_cost),
        repair_time=to_decimal_parameter(model.repair_time),
        repair_limit=to_decimal_parameter(model.repair_limit),
        items={key: to_line_item(value) for key, value in model.items.items()},
        overtime_hours=to_decimal_parameter(model.overtime_hours),
        overtime_cost=(
            None
            if model.overtime_cost is None
            else to_decimal_parameter(model.overtime_cost)
        ),
        warehouse=model.warehouse,
        groups=tuple(model.groups),
        name=model.name,
        description=model.description,
    )


def to_warehouse(model: Warehouse) -> engine.Warehouse:
    """Convert a warehouse.

    Args:
        model (Warehouse): The model.

    Returns:
        Warehouse: The dataclass.

    Examples:
        >>> warehouse = Warehouse.model_validate(
        ...     {"capacity": "100", "accepts": ["products", {"group": "emea"}]}
        ... )
        >>> to_warehouse(warehouse).accepted_groups
        ('emea',)
    """
    return engine.Warehouse(
        capacity=model.capacity,
        storage_factor=model.storage_factor,
        transport_factor=model.transport_factor,
        accepts=tuple(kind for kind in model.accepts if isinstance(kind, str)),
        accepted_groups=tuple(
            entry.group for entry in model.accepts if isinstance(entry, AcceptedGroup)
        ),
        accepted_group_positions=tuple(
            position
            for position, entry in enumerate(model.accepts)
            if isinstance(entry, AcceptedGroup)
        ),
        name=model.name,
        description=model.description,
    )


def to_route(model: Route) -> engine.Route:
    """Convert a route.

    Args:
        model (Route): The model.

    Returns:
        Route: The dataclass.

    Examples:
        >>> to_route(Route(cost="0.8", lead_time=1))
        Route(cost=Decimal('0.8000'), lead_time=1)
    """
    return engine.Route(
        cost=to_decimal_parameter(model.cost),
        lead_time=to_periods_parameter(model.lead_time),
    )


def resolve_manifest(document: object) -> tuple[ManifestCreate, dict[str, str]]:
    """Resolve a manifest given as JSON: validate it with its groups resolved.

    Args:
        document (object): The manifest as read by `read_json_bytes`.

    Returns:
        tuple[ManifestCreate, dict[str, str]]: The validated manifest with the
            values of groups in their members, and where each parameter came from:
            `written` or the identifier of a group, by its path.

    Raises:
        InputError: If the groups or the manifest break a rule of the model or of
            the groups.

    Examples:
        >>> from factory_simulator.api.core.numbers import read_json_bytes
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> model, origins = resolve_manifest(
        ...     read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
        ... )
        >>> model.name, origins["materials.microchip.space"]
        ('Electronics factory with economies of scale', 'written')
    """
    filled, given = resolve_groups(document)
    model = validate(ManifestCreate, filled)
    written = {path: "written" for path in written_paths(model) if path not in given}
    return model, written | given


def read_factory(document: object) -> engine.Factory:
    """Read a manifest given as JSON into the factory it describes.

    Args:
        document (object): The manifest as read by `read_json_bytes`.

    Returns:
        Factory: The factory, with where each parameter came from.

    Raises:
        InputError: If the manifest breaks a rule of the model or of the groups.

    Examples:
        >>> from factory_simulator.api.core.numbers import read_json_bytes
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> document = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
        >>> read_factory(document).period_name
        'week'
    """
    model, origins = resolve_manifest(document)
    return to_factory(model, origins)


def written_content(
    model: ManifestCreate, origins: Mapping[str, str]
) -> dict[str, object]:
    """Give a manifest as its author wrote it, with exact numbers.

    Values given by groups and built-in defaults are left out; a default recipe
    filled for an item with one recipe stays.

    Args:
        model (ManifestCreate): The validated manifest, its groups resolved.
        origins (Mapping[str, str]): Where each parameter came from, by its path.

    Returns:
        dict[str, object]: The manifest to store.

    Examples:
        >>> from factory_simulator.api.core.numbers import read_json_bytes
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> model, origins = resolve_manifest(
        ...     read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
        ... )
        >>> origins["suppliers.apac-chips.catalogue.microchip.lead_time"]
        'apac'
        >>> content = written_content(model, origins)
        >>> "lead_time" in content["suppliers"]["apac-chips"]["catalogue"]["microchip"]
        False
    """
    content = model.model_dump(mode="python", exclude_unset=True)
    for path, origin in origins.items():
        if origin == "written":
            continue
        *parents, key = path.split(".")
        parent: dict[str, object] = content
        for part in parents:
            parent = cast(dict[str, object], parent[part])
        del parent[key]
    return content


def written_paths(value: object, path: str = "") -> set[str]:
    """Give the paths of every value written in a validated model.

    Args:
        value (object): A model, a mapping or a leaf value.
        path (str, optional): The dotted path of the value; the empty text when not
            given.

    Returns:
        set[str]: The paths, with JSON names such as `yield`.

    Examples:
        >>> sorted(written_paths(Route(cost="0.8", lead_time=1)))
        ['cost', 'lead_time']
    """
    found: set[str] = set()
    if isinstance(value, BaseModel):
        fields = type(value).model_fields
        for name in value.model_fields_set:
            key = fields[name].alias or name
            here = f"{path}.{key}" if path else key
            found |= {here} | written_paths(getattr(value, name), here)
    elif isinstance(value, Mapping):
        for key, child in cast(Mapping[str, object], value).items():
            here = f"{path}.{key}" if path else key
            found |= {here} | written_paths(child, here)
    elif isinstance(value, tuple) and path.endswith(".discounts"):
        for tier in cast(tuple[DiscountTier, ...], value):
            found |= written_paths(tier, f"{path}.{tier.from_}")
    return found


def defaults_keys(group: Group) -> tuple[str, ...]:
    """Give the keys under which a group gives defaults, as written.

    Args:
        group (Group): The model of the group.

    Returns:
        tuple[str, ...]: The written keys of its defaults, in the order of the model.

    Examples:
        >>> defaults_keys(Group(kind="region"))
        ()
    """
    if group.defaults is None:
        return ()
    written = group.defaults.model_fields_set
    return tuple(key for key in GroupDefaults.model_fields if key in written)


def to_groups(model: ManifestCreate) -> dict[str, engine.Group]:
    """Convert every group with its kind and the objects that list it.

    Args:
        model (ManifestCreate): The validated manifest.

    Returns:
        dict[str, Group]: The groups by identifier, members in identifier order.

    Examples:
        >>> from factory_simulator.api.core.numbers import read_json_bytes
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> document = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
        >>> model, _ = resolve_manifest(document)
        >>> to_groups(model)["semiconductor"].members
        ('microchip', 'microchip-b')
    """
    listed: dict[str, list[str]] = {group_id: [] for group_id in model.groups}
    member_types: dict[str, str] = {}
    objects: dict[str, Mapping[str, Material | Supplier | Customer | Line]] = {
        "materials": model.materials,
        "components": model.components,
        "products": model.products,
        "suppliers": model.suppliers,
        "customers": model.customers,
        "lines": model.lines,
    }
    for member_type, members in objects.items():
        for object_id, member in members.items():
            for group_id in member.groups:
                listed.setdefault(group_id, []).append(object_id)
                member_types[group_id] = member_type
    return {
        group_id: engine.Group(
            kind=group.kind,
            members=tuple(sorted(listed[group_id])),
            member_type=member_types.get(group_id, ""),
            defaults_keys=defaults_keys(group),
        )
        for group_id, group in model.groups.items()
    }


def to_factory(model: ManifestCreate, origins: Mapping[str, str]) -> engine.Factory:
    """Convert a manifest into the factory it describes.

    Args:
        model (ManifestCreate): The validated manifest, its groups resolved.
        origins (Mapping[str, str]): Where the value of each parameter came from, by
            its path.

    Returns:
        Factory: The factory for the engine.

    Examples:
        >>> from factory_simulator.api.core.numbers import read_json_bytes
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> document = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
        >>> model, _ = resolve_manifest(document)
        >>> sorted(to_factory(model, {}).warehouses)
        ['distribution-centre', 'main-plant']
    """
    return engine.Factory(
        materials={key: to_material(value) for key, value in model.materials.items()},
        components={
            key: to_made_item(value) for key, value in model.components.items()
        },
        products={key: to_product(value) for key, value in model.products.items()},
        suppliers={key: to_supplier(value) for key, value in model.suppliers.items()},
        customers={key: to_customer(value) for key, value in model.customers.items()},
        lines={key: to_line(value) for key, value in model.lines.items()},
        warehouses={
            key: to_warehouse(value) for key, value in model.warehouses.items()
        },
        cash=engine.Cash(
            credit_limit=model.cash.credit_limit,
            credit_interest=model.cash.credit_interest,
            debit_interest=model.cash.debit_interest,
            overdraft_interest=model.cash.overdraft_interest,
        ),
        routes={
            leaving: {reached: to_route(route) for reached, route in routes.items()}
            for leaving, routes in model.routes.items()
        },
        groups=to_groups(model),
        origins=origins,
        name=model.name,
        description=model.description,
        period_name=model.period_name,
    )
