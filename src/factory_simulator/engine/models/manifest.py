"""The factory a manifest describes: its items, partners, lines, warehouses and cash.

Examples:
    >>> Route(cost=Decimal("0.25"), lead_time=2).cost
    Decimal('0.25')
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import cast


def read_only_copy[K, V](mapping: Mapping[K, V]) -> Mapping[K, V]:
    """Give a read-only copy of a mapping, nested mappings copied the same way.

    Args:
        mapping (Mapping[K, V]): The mapping.

    Returns:
        Mapping[K, V]: A read-only copy, which no change of the mapping reaches.

    Examples:
        >>> stock = {"main": {"steel": 10}}
        >>> copied = read_only_copy(stock)
        >>> stock["main"]["steel"] = 0
        >>> copied["main"]["steel"]
        10
    """
    copied: dict[K, V] = {}
    for key, value in mapping.items():
        if isinstance(value, Mapping):
            value = cast(V, read_only_copy(cast(Mapping[object, object], value)))
        copied[key] = value
    return MappingProxyType(copied)


@dataclass(frozen=True, slots=True, kw_only=True)
class Range[N: (Decimal, int)]:
    """A range a parameter is drawn from.

    Attributes:
        min (Decimal | int): The smallest value.
        max (Decimal | int): The largest value.
        distribution (str): How values are spread: "uniform", "triangular",
            "normal" or "lognormal".
        mode (Decimal | None): The most likely value of a triangular range.
        mean (Decimal | None): The mean of a normal range before it is cut.
        sd (Decimal | None): The standard deviation of a normal range.
        median (Decimal | None): The median of a lognormal range before it is cut.
        spread (Decimal | None): The standard deviation of the natural logarithm of a
            lognormal range.
        drawn (str): "run" to draw once per run, "period" to draw once per period;
            only a catalogue price is drawn once per period.

    Examples:
        >>> Range(min=Decimal("0.8000"), max=Decimal("0.9200")).distribution
        'uniform'
    """

    min: N
    max: N
    distribution: str = "uniform"
    mode: Decimal | None = None
    mean: Decimal | None = None
    sd: Decimal | None = None
    median: Decimal | None = None
    spread: Decimal | None = None
    drawn: str = "run"


# A decimal parameter: a fixed number or a range.
type DecimalParameter = Decimal | Range[Decimal]


# A parameter in periods: a fixed whole number or a range.
type PeriodsParameter = int | Range[int]


@dataclass(frozen=True, slots=True, kw_only=True)
class Material:
    """A material bought from suppliers.

    Attributes:
        space (Decimal): Space one unit takes.
        storage_cost (Decimal | Range[Decimal]): Cost of holding one unit for one
            period.
        salvage_value (Decimal | Range[Decimal]): Worth of one unit in stock at the end.
        groups (tuple[str, ...]): The groups it lists, as written.
        name (str | None): A readable name.
        description (str | None): A readable description.
        unit (str | None): The unit of a quantity.

    Examples:
        >>> steel = Material(
        ...     space=Decimal("1"),
        ...     storage_cost=Decimal("0.5"),
        ...     salvage_value=Decimal("1"),
        ... )
        >>> steel.groups
        ()
    """

    space: Decimal
    storage_cost: DecimalParameter
    salvage_value: DecimalParameter
    groups: tuple[str, ...] = ()
    name: str | None = None
    description: str | None = None
    unit: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MadeItem:
    """A component or a product, made on a line from one of its recipes.

    Attributes:
        space (Decimal): Space one unit takes.
        storage_cost (Decimal | Range[Decimal]): Cost of holding one unit for one
            period.
        salvage_value (Decimal | Range[Decimal]): Worth of one unit in stock at the end.
        recipes (Mapping[str, Mapping[str, Decimal]]): Per recipe name, the quantity
            of each input used for one unit.
        default_recipe (str | None): The recipe of a produce decision that names
            none; None only when the manifest leaves it out.
        groups (tuple[str, ...]): The groups it lists, as written.
        name (str | None): A readable name.
        description (str | None): A readable description.
        unit (str | None): The unit of a quantity.

    Examples:
        >>> bolt = MadeItem(
        ...     space=Decimal("1"),
        ...     storage_cost=Decimal("0"),
        ...     salvage_value=Decimal("0"),
        ...     recipes={"forged": {"rod": Decimal("2")}},
        ... )
        >>> bolt.default_recipe is None
        True
    """

    space: Decimal
    storage_cost: DecimalParameter
    salvage_value: DecimalParameter
    recipes: Mapping[str, Mapping[str, Decimal]]
    default_recipe: str | None = None
    groups: tuple[str, ...] = ()
    name: str | None = None
    description: str | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        """Keep a read-only copy of every mapping given."""
        object.__setattr__(self, "recipes", read_only_copy(self.recipes))


@dataclass(frozen=True, slots=True, kw_only=True)
class Product(MadeItem):
    """A product, made on a line from components and sold to customers.

    Attributes:
        common_share (Decimal | None): Share of the variation of demand that the
            customers of the product have in common, from 0 to 1; None when the
            manifest leaves it out, which counts as 0.

    Examples:
        >>> gadget = Product(
        ...     space=Decimal("1"),
        ...     storage_cost=Decimal("0"),
        ...     salvage_value=Decimal("0"),
        ...     recipes={"main": {"board": Decimal("1")}},
        ...     common_share=Decimal("0.6000"),
        ... )
        >>> gadget.common_share
        Decimal('0.6000')
    """

    common_share: Decimal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscountTier:
    """A lower price for every unit of an order of at least a quantity.

    Attributes:
        from_ (Decimal): Smallest quantity of an order at this price.
        price (Decimal | Range[Decimal]): Price of every unit of such an order.

    Examples:
        >>> DiscountTier(from_=Decimal("100"), price=Decimal("1.80")).price
        Decimal('1.80')
    """

    from_: Decimal
    price: DecimalParameter


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogueEntry:
    """The terms on which a supplier sells one material.

    Attributes:
        price (Decimal | Range[Decimal]): Price of one accepted unit.
        lead_time (int | Range[int]): Periods from placing to arrival when on time.
        max_quantity (Decimal | Range[Decimal]): Largest quantity ordered in one period.
        punctuality (Decimal | Range[Decimal]): Chance a delivery is on time.
        delay (int | Range[int]): Extra periods of a late delivery.
        completeness (Decimal | Range[Decimal]): Share of the open quantity that
            arrives.
        acceptance (Decimal | Range[Decimal]): Share of the arrived quantity that passes
            inspection.
        cancellation_fee (Decimal | Range[Decimal]): Fee per cancelled unit.
        backfill_delay (int | Range[int]): Periods from a delivery to the backfill of
            the part missing by completeness; 0 loses that part.
        express_lead_time (int | Range[int] | None): Periods from placing to arrival of
            an express order when on time; None offers no express.
        express_cost (Decimal | Range[Decimal] | None): Extra price per unit of an
            express order; None exactly when `express_lead_time` is None.
        min_quantity (Decimal | Range[Decimal] | None): Smallest quantity of one order;
            None for no minimum.
        discounts (tuple[DiscountTier, ...]): Tiers of lower prices, by rising
            `from`.

    Examples:
        >>> entry = CatalogueEntry(
        ...     price=Decimal("2"),
        ...     lead_time=3,
        ...     max_quantity=Decimal("100"),
        ...     punctuality=Decimal("0.9"),
        ...     delay=1,
        ...     completeness=Decimal("1"),
        ...     acceptance=Decimal("1"),
        ... )
        >>> entry.cancellation_fee
        Decimal('0.0000')
    """

    price: DecimalParameter
    lead_time: PeriodsParameter
    max_quantity: DecimalParameter
    punctuality: DecimalParameter
    delay: PeriodsParameter
    completeness: DecimalParameter
    acceptance: DecimalParameter
    cancellation_fee: DecimalParameter = Decimal("0.0000")
    backfill_delay: PeriodsParameter = 0
    express_lead_time: PeriodsParameter | None = None
    express_cost: DecimalParameter | None = None
    min_quantity: DecimalParameter | None = None
    discounts: tuple[DiscountTier, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Supplier:
    """A supplier of materials.

    Attributes:
        catalogue (Mapping[str, CatalogueEntry]): The entry of each material sold.
        groups (tuple[str, ...]): The groups it lists, as written.
        name (str | None): A readable name.
        description (str | None): A readable description.

    Examples:
        >>> Supplier(catalogue={}, name="Steel mill").name
        'Steel mill'
    """

    catalogue: Mapping[str, CatalogueEntry]
    groups: tuple[str, ...] = ()
    name: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        """Keep a read-only copy of every mapping given."""
        object.__setattr__(self, "catalogue", read_only_copy(self.catalogue))


@dataclass(frozen=True, slots=True, kw_only=True)
class CustomerProduct:
    """The terms on which a customer buys one product.

    Attributes:
        price (Decimal | Range[Decimal]): Price of one shipped unit.
        transport_cost (Decimal | Range[Decimal]): Cost of shipping one unit.
        demand (Decimal | Range[Decimal]): Base demand per period.
        lead_time (int | Range[int]): Periods from the arrival of an order to its due
            period.
        patience (int | Range[int]): Periods after the due period before the rest is
            lost.
        late_penalty (Decimal | Range[Decimal]): Penalty per unit not shipped by the
            close of each period from the due period, but the period in which the
            order is lost.
        lost_sale_penalty (Decimal | Range[Decimal]): Penalty per unit lost.
        demand_persistence (Decimal | None): Share of the previous base demand carried
            into the next period; None when left out, which carries nothing.

    Examples:
        >>> terms = CustomerProduct(
        ...     price=Decimal("5"),
        ...     transport_cost=Decimal("0.5"),
        ...     demand=Decimal("10"),
        ...     lead_time=1,
        ...     patience=2,
        ...     late_penalty=Decimal("1"),
        ...     lost_sale_penalty=Decimal("3"),
        ... )
        >>> terms.demand_persistence is None
        True
    """

    price: DecimalParameter
    transport_cost: DecimalParameter
    demand: DecimalParameter
    lead_time: PeriodsParameter
    patience: PeriodsParameter
    late_penalty: DecimalParameter
    lost_sale_penalty: DecimalParameter
    demand_persistence: Decimal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Customer:
    """A customer of products.

    Attributes:
        products (Mapping[str, CustomerProduct]): The terms of each product bought.
        payment_terms (int | Range[int]): Periods from a shipment to its payment; 0 pays
            at once.
        groups (tuple[str, ...]): The groups it lists, as written.
        name (str | None): A readable name.
        description (str | None): A readable description.

    Examples:
        >>> Customer(products={}, payment_terms=2).payment_terms
        2
    """

    products: Mapping[str, CustomerProduct]
    payment_terms: PeriodsParameter = 0
    groups: tuple[str, ...] = ()
    name: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        """Keep a read-only copy of every mapping given."""
        object.__setattr__(self, "products", read_only_copy(self.products))


@dataclass(frozen=True, slots=True, kw_only=True)
class LineItem:
    """How a line makes one item.

    Attributes:
        time (Decimal | Range[Decimal]): Hours per unit started.
        cost (Decimal | Range[Decimal]): Cost per unit started.
        yield_ (Decimal | Range[Decimal]): Share of started units that come out good;
            `yield` in paths and JSON.
        lead_time (int | Range[int]): Periods from the start of production to the close
            at which it enters stock, counting the start period.
        changeover_time (Decimal | Range[Decimal] | None): Regular hours to set the line
            for this item; None for 0, and with `changeover_cost` also None the item
            has no changeover.
        changeover_cost (Decimal | Range[Decimal] | None): Cost to set the line for this
            item; None for 0.

    Examples:
        >>> item = LineItem(
        ...     time=Decimal("0.5"),
        ...     cost=Decimal("1"),
        ...     yield_=Decimal("0.95"),
        ... )
        >>> item.lead_time
        1
    """

    time: DecimalParameter
    cost: DecimalParameter
    yield_: DecimalParameter
    lead_time: PeriodsParameter = 1
    changeover_time: DecimalParameter | None = None
    changeover_cost: DecimalParameter | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Line:
    """A production line.

    Attributes:
        capacity (Decimal | Range[Decimal]): Production hours per period at condition 1.
        wear_per_period (Decimal | Range[Decimal]): Share of condition lost every
            period.
        wear_per_hour (Decimal | Range[Decimal]): Condition lost per production hour.
        breakdown_chance (Decimal | Range[Decimal]): Chance of a breakdown in a period.
        breakdown_loss (Decimal | Range[Decimal]): Share of condition lost in a
            breakdown.
        repair_cost (Decimal | Range[Decimal]): Cost of restoring a condition of 1.
        repair_time (Decimal | Range[Decimal]): Hours used to restore a condition of 1.
        repair_limit (Decimal | Range[Decimal]): Largest condition restored in one
            period.
        items (Mapping[str, LineItem]): How the line makes each item.
        overtime_hours (Decimal | Range[Decimal]): Extra production hours per period at
            condition 1.
        overtime_cost (Decimal | Range[Decimal] | None): Cost of one overtime hour;
            None exactly when the overtime hours are left out or fixed at 0.
        warehouse (str | None): The warehouse of the inputs and output of the line;
            None for the only warehouse of the manifest.
        groups (tuple[str, ...]): The groups it lists, as written.
        name (str | None): A readable name.
        description (str | None): A readable description.

    Examples:
        >>> line = Line(
        ...     capacity=Decimal("40"),
        ...     wear_per_period=Decimal("0"),
        ...     wear_per_hour=Decimal("0"),
        ...     breakdown_chance=Decimal("0"),
        ...     breakdown_loss=Decimal("0"),
        ...     repair_cost=Decimal("0"),
        ...     repair_time=Decimal("0"),
        ...     repair_limit=Decimal("1"),
        ...     items={},
        ... )
        >>> line.overtime_hours
        Decimal('0.000')
    """

    capacity: DecimalParameter
    wear_per_period: DecimalParameter
    wear_per_hour: DecimalParameter
    breakdown_chance: DecimalParameter
    breakdown_loss: DecimalParameter
    repair_cost: DecimalParameter
    repair_time: DecimalParameter
    repair_limit: DecimalParameter
    items: Mapping[str, LineItem]
    overtime_hours: DecimalParameter = Decimal("0.000")
    overtime_cost: DecimalParameter | None = None
    warehouse: str | None = None
    groups: tuple[str, ...] = ()
    name: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        """Keep a read-only copy of every mapping given."""
        object.__setattr__(self, "items", read_only_copy(self.items))


# The kinds of items, in the order of the manifest.
ITEM_KINDS = ("materials", "components", "products")


@dataclass(frozen=True, slots=True, kw_only=True)
class Warehouse:
    """A warehouse.

    Attributes:
        capacity (Decimal): Space the warehouse has.
        storage_factor (Decimal): Factor on the storage cost of the stock it holds.
        transport_factor (Decimal): Factor on the transport cost of the shipments
            that leave it.
        accepts (tuple[str, ...]): The kinds of item it holds: `materials`,
            `components`, `products`.
        accepted_groups (tuple[str, ...]): The groups of items it holds besides.
        accepted_group_positions (tuple[int, ...]): The position of each accepted
            group in the `accepts` list as written; empty when the groups follow
            the kinds.
        name (str | None): A readable name.
        description (str | None): A readable description.

    Examples:
        >>> Warehouse(capacity=Decimal("1000")).accepts
        ('materials', 'components', 'products')
    """

    capacity: Decimal
    storage_factor: Decimal = Decimal("1.0000")
    transport_factor: Decimal = Decimal("1.0000")
    accepts: tuple[str, ...] = ITEM_KINDS
    accepted_groups: tuple[str, ...] = ()
    accepted_group_positions: tuple[int, ...] = ()
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Route:
    """A one-way route between two warehouses.

    Attributes:
        cost (Decimal | Range[Decimal]): Cost per unit transferred.
        lead_time (int | Range[int]): Periods a transfer takes; 0 arrives at once.

    Examples:
        >>> Route(cost=Decimal("0.25"), lead_time=2).lead_time
        2
    """

    cost: DecimalParameter
    lead_time: PeriodsParameter


@dataclass(frozen=True, slots=True, kw_only=True)
class Group:
    """A group of objects of one type.

    Attributes:
        kind (str): A word such as `region` or `segment`.
        members (tuple[str, ...]): The identifiers of the objects that list it.
        member_type (str): The type of its members, such as `suppliers`.
        defaults_keys (tuple[str, ...]): The keys under which it gives defaults,
            such as `catalogue`.

    Examples:
        >>> region = Group(kind="region", members=("mill",), member_type="suppliers")
        >>> region.defaults_keys
        ()
    """

    kind: str
    members: tuple[str, ...]
    member_type: str
    defaults_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Cash:
    """The credit limit and interest rates of cash.

    Attributes:
        credit_limit (Decimal): The amount L such that cash below -L pays the
            overdraft rate.
        credit_interest (Decimal): Share of positive cash earned per period.
        debit_interest (Decimal): Share of negative cash down to the credit limit paid
            per period.
        overdraft_interest (Decimal): Share of negative cash below the credit limit
            paid per period.

    Examples:
        >>> cash = Cash(
        ...     credit_limit=Decimal("500"),
        ...     credit_interest=Decimal("0.01"),
        ...     debit_interest=Decimal("0.02"),
        ...     overdraft_interest=Decimal("0.05"),
        ... )
        >>> cash.overdraft_interest
        Decimal('0.05')
    """

    credit_limit: Decimal
    credit_interest: Decimal
    debit_interest: Decimal
    overdraft_interest: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Factory:
    """A whole factory.

    Attributes:
        materials (Mapping[str, Material]): Materials by identifier.
        components (Mapping[str, MadeItem]): Components by identifier.
        products (Mapping[str, Product]): Products by identifier.
        suppliers (Mapping[str, Supplier]): Suppliers by identifier.
        customers (Mapping[str, Customer]): Customers by identifier.
        lines (Mapping[str, Line]): Lines by identifier.
        warehouses (Mapping[str, Warehouse]): Warehouses by identifier.
        cash (Cash): The credit limit and the interest rates of cash.
        routes (Mapping[str, Mapping[str, Route]]): Routes by the warehouse they
            leave from and the warehouse they reach.
        groups (Mapping[str, Group]): Groups by identifier.
        origins (Mapping[str, str]): Where the value of a parameter comes from, by its
            path: `written` or the identifier of a group; a parameter left out has
            its built-in default.
        name (str | None): A readable name.
        description (str | None): A readable description.
        period_name (str | None): The name of one period, such as "week".

    Examples:
        >>> cash = Cash(
        ...     credit_limit=Decimal("0"),
        ...     credit_interest=Decimal("0"),
        ...     debit_interest=Decimal("0"),
        ...     overdraft_interest=Decimal("0"),
        ... )
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     cash=cash,
        ...     warehouses={"main": Warehouse(capacity=Decimal("100"))},
        ... )
        >>> dict(factory.routes)
        {}
    """

    materials: Mapping[str, Material]
    components: Mapping[str, MadeItem]
    products: Mapping[str, Product]
    suppliers: Mapping[str, Supplier]
    customers: Mapping[str, Customer]
    lines: Mapping[str, Line]
    warehouses: Mapping[str, Warehouse]
    cash: Cash
    routes: Mapping[str, Mapping[str, Route]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    groups: Mapping[str, Group] = field(default_factory=lambda: MappingProxyType({}))
    origins: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    name: str | None = None
    description: str | None = None
    period_name: str | None = None

    def __post_init__(self) -> None:
        """Keep a read-only copy of every mapping given."""
        for name in (
            "materials",
            "components",
            "products",
            "suppliers",
            "customers",
            "lines",
            "warehouses",
            "routes",
            "groups",
            "origins",
        ):
            object.__setattr__(self, name, read_only_copy(getattr(self, name)))
