"""A scenario: horizon, start, demand shapes, forecasts, disruptions and cascades.

Examples:
    >>> Scenario(horizon=12).start.cash
    Decimal('0.0000')
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from factory_simulator.engine.models.manifest import (
    DecimalParameter,
    PeriodsParameter,
    read_only_copy,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class StartCustomerOrder:
    """A customer order open at the start, arrived in period 0.

    Attributes:
        customer (str): The identifier of the customer.
        product (str): The identifier of the product.
        quantity (Decimal): Units ordered.
        due (int): The due period.

    Examples:
        >>> order = StartCustomerOrder(
        ...     customer="shop",
        ...     product="bolt",
        ...     quantity=Decimal("10"),
        ...     due=2,
        ... )
        >>> order.due
        2
    """

    customer: str
    product: str
    quantity: Decimal
    due: int


@dataclass(frozen=True, slots=True, kw_only=True)
class StartSupplierOrder:
    """A supplier order on the way at the start, placed in period 0.

    Attributes:
        supplier (str): The identifier of the supplier.
        material (str): The identifier of the material.
        quantity (Decimal): Units ordered.
        arrival (int): The period it arrives, in full and accepted.
        warehouse (str | None): The warehouse it goes to; None for the only
            warehouse of the manifest.

    Examples:
        >>> order = StartSupplierOrder(
        ...     supplier="mill",
        ...     material="steel",
        ...     quantity=Decimal("30"),
        ...     arrival=1,
        ... )
        >>> order.warehouse is None
        True
    """

    supplier: str
    material: str
    quantity: Decimal
    arrival: int
    warehouse: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Start:
    """The state of the factory before period 1.

    Attributes:
        cash (Decimal): Cash at the start; may be negative.
        stock (Mapping[str, Mapping[str, Decimal]]): Stock per warehouse and item; a
            missing warehouse or item starts at 0.
        condition (Mapping[str, Decimal]): Condition per line; a missing line starts
            at 1.
        customer_orders (tuple[StartCustomerOrder, ...]): Customer orders open at the
            start.
        supplier_orders (tuple[StartSupplierOrder, ...]): Supplier orders on the way
            at the start.
        set_for (Mapping[str, str]): The item each line is set for; a missing line
            is set for none.

    Examples:
        >>> Start(cash=Decimal("100"), stock={"main": {"steel": Decimal("10")}}).cash
        Decimal('100')
    """

    cash: Decimal = Decimal("0.0000")
    stock: Mapping[str, Mapping[str, Decimal]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    condition: Mapping[str, Decimal] = field(
        default_factory=lambda: MappingProxyType({})
    )
    customer_orders: tuple[StartCustomerOrder, ...] = ()
    supplier_orders: tuple[StartSupplierOrder, ...] = ()
    set_for: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        """Keep a read-only copy of every mapping given."""
        object.__setattr__(self, "stock", read_only_copy(self.stock))
        object.__setattr__(self, "condition", read_only_copy(self.condition))
        object.__setattr__(self, "set_for", read_only_copy(self.set_for))


@dataclass(frozen=True, slots=True, kw_only=True)
class Trend:
    """Demand that grows or shrinks by a rate every period.

    Attributes:
        customer (str | None): The customer it targets; None for every customer.
        product (str | None): The product it targets; None for every product.
        rate (Decimal): The growth per period.
        group (tuple[str, str] | None): The kind and identifier of the group of
            customers or products it targets; None when it targets no group.

    Examples:
        >>> Trend(customer=None, product="bolt", rate=Decimal("0.02")).group is None
        True
    """

    customer: str | None
    product: str | None
    rate: Decimal
    group: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Season:
    """Demand that repeats a list of factors, each for a number of periods.

    Attributes:
        customer (str | None): The customer it targets; None for every customer.
        product (str | None): The product it targets; None for every product.
        factors (tuple[Decimal, ...]): The factors.
        period_length (int): Periods each factor lasts.
        group (tuple[str, str] | None): The kind and identifier of the group of
            customers or products it targets; None when it targets no group.

    Examples:
        >>> season = Season(
        ...     customer=None,
        ...     product=None,
        ...     factors=(Decimal("1.2"), Decimal("0.8")),
        ...     period_length=3,
        ... )
        >>> season.group is None
        True
    """

    customer: str | None
    product: str | None
    factors: tuple[Decimal, ...]
    period_length: int
    group: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Step:
    """Demand times a factor from a period on.

    Attributes:
        customer (str | None): The customer it targets; None for every customer.
        product (str | None): The product it targets; None for every product.
        period (int): The first period of the factor.
        factor (Decimal): The factor.
        group (tuple[str, str] | None): The kind and identifier of the group of
            customers or products it targets; None when it targets no group.

    Examples:
        >>> step = Step(customer="shop", product=None, period=5, factor=Decimal("1.5"))
        >>> step.group is None
        True
    """

    customer: str | None
    product: str | None
    period: int
    factor: Decimal
    group: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Ramp:
    """Demand that moves in a straight line from one factor to another.

    Attributes:
        customer (str | None): The customer it targets; None for every customer.
        product (str | None): The product it targets; None for every product.
        first (int): The last period of `from_factor`.
        last (int): The first period of `to_factor`.
        from_factor (Decimal): The factor up to `first`.
        to_factor (Decimal): The factor from `last`.
        group (tuple[str, str] | None): The kind and identifier of the group of
            customers or products it targets; None when it targets no group.

    Examples:
        >>> ramp = Ramp(
        ...     customer=None,
        ...     product=None,
        ...     first=2,
        ...     last=6,
        ...     from_factor=Decimal("1"),
        ...     to_factor=Decimal("2"),
        ... )
        >>> ramp.group is None
        True
    """

    customer: str | None
    product: str | None
    first: int
    last: int
    from_factor: Decimal
    to_factor: Decimal
    group: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SCurve:
    """Demand that moves along an s-curve from one factor to another.

    Attributes:
        customer (str | None): The customer it targets; None for every customer.
        product (str | None): The product it targets; None for every product.
        middle (int): The period halfway between the factors.
        steepness (Decimal): How fast it moves.
        from_factor (Decimal): The factor long before the middle.
        to_factor (Decimal): The factor long after the middle.
        group (tuple[str, str] | None): The kind and identifier of the group of
            customers or products it targets; None when it targets no group.

    Examples:
        >>> curve = SCurve(
        ...     customer=None,
        ...     product=None,
        ...     middle=10,
        ...     steepness=Decimal("0.5"),
        ...     from_factor=Decimal("1"),
        ...     to_factor=Decimal("3"),
        ... )
        >>> curve.group is None
        True
    """

    customer: str | None
    product: str | None
    middle: int
    steepness: Decimal
    from_factor: Decimal
    to_factor: Decimal
    group: tuple[str, str] | None = None


type DemandShape = Trend | Season | Step | Ramp | SCurve


@dataclass(frozen=True, slots=True, kw_only=True)
class Forecast:
    """Forecasts of the demand of the customer products an entry targets.

    Attributes:
        customer (str | None): The customer it targets; None for every customer.
        product (str | None): The product it targets; None for every product.
        periods_ahead (int): Periods each forecast looks ahead.
        noise (Decimal): The width of the error of a forecast for the next period.
        noise_growth (Decimal): The growth of the width with each further period.
        group (tuple[str, str] | None): The kind and identifier of the group of
            customers or products it targets; None when it targets no group.

    Examples:
        >>> forecast = Forecast(
        ...     customer=None,
        ...     product=None,
        ...     periods_ahead=4,
        ...     noise=Decimal("0.1"),
        ...     noise_growth=Decimal("0.05"),
        ... )
        >>> forecast.group is None
        True
    """

    customer: str | None
    product: str | None
    periods_ahead: int
    noise: Decimal
    noise_growth: Decimal
    group: tuple[str, str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Disruption:
    """A disruption of one part of the factory for a window of periods.

    Attributes:
        id (str): The identifier: `disruption-<n>` for a written one, numbered in the
            order of `start - notice`, then of the scenario list;
            `<name>/<start>/<target>` for a drawn one.
        kind (str): The kind, such as "supplier_outage".
        target (tuple[str, ...] | None): The identifiers it acts on; None for all,
            or for a group.
        start (int): The first period it acts.
        duration (int): Periods it acts; 1 for a line breakdown.
        effect (Decimal): Its strength, loss, factor or delay.
        group (tuple[str, str] | None): The kind and identifier of the group it acts
            on; None when it targets no group.
        notice (int): Periods before `start` from which it is visible.
        rule (str | None): The name of the random rule that started it; None for a
            written one.

    Examples:
        >>> outage = Disruption(
        ...     id="disruption-1",
        ...     kind="supplier_outage",
        ...     target=("mill",),
        ...     start=3,
        ...     duration=2,
        ...     effect=Decimal("1"),
        ... )
        >>> outage.notice
        0
    """

    id: str
    kind: str
    target: tuple[str, ...] | None
    start: int
    duration: int
    effect: Decimal
    group: tuple[str, str] | None = None
    notice: int = 0
    rule: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Cascade:
    """A raise of the chance of one rule after a disruption of another rule starts.

    Attributes:
        rule (str): The name of the rule whose chance is raised.
        factor (Decimal): The factor on its chance, above 1.
        periods (int): Periods after each start in which the chance is raised.

    Examples:
        >>> Cascade(rule="delays", factor=Decimal("3.0000"), periods=2).periods
        2
    """

    rule: str
    factor: Decimal
    periods: int


@dataclass(frozen=True, slots=True, kw_only=True)
class RandomDisruption:
    """A rule that starts disruptions by chance, drawn from the seed before period 1.

    Attributes:
        name (str): The identifier of the rule, unique in the scenario.
        kind (str): The kind of the disruptions it starts.
        target (tuple[str, ...] | None): The identifiers it may act on; None for all,
            or for a group.
        chance (Decimal | None): The chance of a start in a period; None with a
            written start.
        duration (int | Range[int] | None): Periods a disruption acts; None for a
            line breakdown.
        effect (Decimal | Range[Decimal] | int | Range[int]): Its strength, loss,
            factor or delay.
        choose (bool): Whether one target is chosen per start.
        group (tuple[str, str] | None): The kind and identifier of the group it acts
            on; None when it targets no group.
        notice (int): Periods before its start from which each is visible, from
            period 1 at the earliest.
        start (int | None): The one period in which the rule starts a disruption, on
            the target with the smallest draw; None to start by chance.
        raises (Cascade | None): The raise of the chance of another rule after each
            start of this one; None for none.

    Examples:
        >>> rule = RandomDisruption(
        ...     name="breakdowns",
        ...     kind="line_breakdown",
        ...     target=None,
        ...     chance=Decimal("0.05"),
        ...     duration=None,
        ...     effect=Decimal("0.3"),
        ... )
        >>> rule.choose
        False
    """

    name: str
    kind: str
    target: tuple[str, ...] | None
    chance: Decimal | None
    duration: PeriodsParameter | None
    effect: DecimalParameter | PeriodsParameter
    choose: bool = False
    group: tuple[str, str] | None = None
    notice: int = 0
    start: int | None = None
    raises: Cascade | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Scenario:
    """The conditions of a run of a factory.

    Attributes:
        horizon (int): Number of periods.
        start (Start): The state before period 1.
        demand_shapes (tuple[Trend | Season | Step | Ramp | SCurve, ...]): Shapes of
            demand over time.
        forecasts (tuple[Forecast, ...]): Forecast entries, at most one per customer
            product.
        disruptions (tuple[Disruption, ...]): Written disruptions, in scenario order.
        random_disruptions (tuple[RandomDisruption, ...]): Rules of disruptions
            drawn from the seed.
        hidden (tuple[str, ...]): The parameter groups kept from the agent.
        name (str | None): A readable name, never shown to the agent.
        description (str | None): A readable description, never shown to the
            agent.

    Examples:
        >>> scenario = Scenario(horizon=12, hidden=("customers.products.demand",))
        >>> scenario.disruptions
        ()
    """

    horizon: int
    start: Start = field(default_factory=Start)
    demand_shapes: tuple[DemandShape, ...] = ()
    forecasts: tuple[Forecast, ...] = ()
    disruptions: tuple[Disruption, ...] = ()
    random_disruptions: tuple[RandomDisruption, ...] = ()
    hidden: tuple[str, ...] = ()
    name: str | None = None
    description: str | None = None
