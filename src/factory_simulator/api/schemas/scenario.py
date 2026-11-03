"""The models of a scenario: the body that describes the conditions of a run.

Examples:
    >>> ScenarioCreate(horizon=12).start.cash
    Decimal('0.0000')
"""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Discriminator, Field, Tag, ValidationInfo, field_validator

from factory_simulator.api.core.numbers import (
    FIXED_TAG,
    RANGE_TAG,
    Money,
    Periods,
    Quantity,
    ReadOnlyList,
    ReadOnlyMapping,
    Share,
    StrictModel,
)
from factory_simulator.api.schemas.manifest import (
    Identifier,
    PeriodsParameter,
    Range,
    ShareParameter,
    fixed_or_range,
)

ShareFrom0To1 = Annotated[Share, Field(ge=0, le=1)]
FactorAbove0 = Annotated[Share, Field(gt=0)]
FactorAtLeast0 = Annotated[Share, Field(ge=0)]
Notice = Annotated[Periods, Field(ge=0)]
QuantityAtLeast0 = Annotated[Quantity, Field(ge=0)]


class StartCustomerOrder(StrictModel):
    """A customer order open at the start, arrived in period 0.

    Attributes:
        customer (str): The identifier of the customer.
        product (str): The identifier of the product.
        quantity (Decimal): Units ordered.
        due (int): The due period.

    Examples:
        >>> body = {"customer": "retail", "product": "monitor", "quantity": "10"}
        >>> StartCustomerOrder.model_validate({**body, "due": 2}).quantity
        Decimal('10.000')
    """

    customer: str
    product: str
    quantity: Annotated[Quantity, Field(gt=0)]
    due: Periods


class StartSupplierOrder(StrictModel):
    """A supplier order on the way at the start, placed in period 0.

    Attributes:
        supplier (str): The identifier of the supplier.
        material (str): The identifier of the material.
        quantity (Decimal): Units ordered.
        arrival (int): The period it arrives, in full and accepted.
        warehouse (str | None, optional): The warehouse it goes to; required when
            the manifest has several warehouses.

    Examples:
        >>> body = {"supplier": "chip-maker", "material": "chip", "quantity": "50"}
        >>> StartSupplierOrder.model_validate({**body, "arrival": 2}).arrival
        2
    """

    supplier: str
    material: str
    quantity: Annotated[Quantity, Field(gt=0)]
    arrival: Periods
    warehouse: str | None = None


class Start(StrictModel):
    """The state of the factory before period 1.

    Attributes:
        cash (Decimal, optional): Cash at the start; may be negative.
        stock (Mapping[str, Mapping[str, Decimal]], optional): Stock per warehouse and
            item; a missing warehouse or item starts at 0.
        condition (Mapping[str, Decimal], optional): Condition per line; a missing line
            starts at 1.
        customer_orders (tuple[StartCustomerOrder, ...], optional): Customer orders open
            at the start.
        supplier_orders (tuple[StartSupplierOrder, ...], optional): Supplier orders on
            the way at the start.
        set_for (Mapping[str, str], optional): The item each line is set for; a missing
            line is set for none.

    Examples:
        >>> Start.model_validate({"cash": "1000"}).cash
        Decimal('1000.0000')
    """

    cash: Money = Decimal(0)
    stock: ReadOnlyMapping[str, ReadOnlyMapping[str, QuantityAtLeast0]] = Field(
        default_factory=dict
    )
    condition: ReadOnlyMapping[str, ShareFrom0To1] = Field(default_factory=dict)
    customer_orders: ReadOnlyList[StartCustomerOrder] = ()
    supplier_orders: ReadOnlyList[StartSupplierOrder] = ()
    set_for: ReadOnlyMapping[str, str] = Field(default_factory=dict)


# A group target names one group under its kind, such as `{"region": "apac"}`.
type GroupTarget = Annotated[
    ReadOnlyMapping[str, str], Field(min_length=1, max_length=1)
]

type Target = Annotated[
    ReadOnlyList[str] | Literal["all"] | GroupTarget,
    Field(union_mode="left_to_right"),
]


class SupplierOutageCreate(StrictModel):
    """A supplier outage: less of what a supplier sends arrives while active.

    Attributes:
        kind (Literal["supplier_outage"]): "supplier_outage".
        target (tuple[str, ...] | str | Mapping[str, str]): Supplier identifiers,
            "all", or a group as `{kind: identifier}`.
        start (int): The first period it acts.
        duration (int): Periods it acts, at least 1.
        notice (int, optional): Periods before `start` from which it is visible.
        strength (Decimal): Share of the arriving quantity that does not arrive.

    Examples:
        >>> body = {"kind": "supplier_outage", "target": "all", "start": 3}
        >>> body |= {"duration": 2, "strength": "0.5"}
        >>> SupplierOutageCreate.model_validate(body).notice
        0
    """

    kind: Literal["supplier_outage"]
    target: Target
    start: Periods
    duration: Annotated[Periods, Field(ge=1)]
    notice: Notice = 0
    strength: ShareFrom0To1


class MaterialShortageCreate(StrictModel):
    """A material shortage: less of a material can be bought while active.

    Attributes:
        kind (Literal["material_shortage"]): "material_shortage".
        target (tuple[str, ...] | str | Mapping[str, str]): Material identifiers,
            "all", or a group as `{kind: identifier}`.
        start (int): The first period it acts.
        duration (int): Periods it acts, at least 1.
        notice (int, optional): Periods before `start` from which it is visible.
        strength (Decimal): Share of `max_quantity` that cannot be bought.

    Examples:
        >>> body = {"kind": "material_shortage", "target": "all", "start": 3}
        >>> body |= {"duration": 2, "strength": "0.5"}
        >>> MaterialShortageCreate.model_validate(body).notice
        0
    """

    kind: Literal["material_shortage"]
    target: Target
    start: Periods
    duration: Annotated[Periods, Field(ge=1)]
    notice: Notice = 0
    strength: ShareFrom0To1


class QualityDropCreate(StrictModel):
    """A quality drop: fewer delivered units of a supplier pass inspection while active.

    Attributes:
        kind (Literal["quality_drop"]): "quality_drop".
        target (tuple[str, ...] | str | Mapping[str, str]): Supplier identifiers,
            "all", or a group as `{kind: identifier}`.
        start (int): The first period it acts.
        duration (int): Periods it acts, at least 1.
        notice (int, optional): Periods before `start` from which it is visible.
        strength (Decimal): Share of the acceptance that is lost.

    Examples:
        >>> body = {"kind": "quality_drop", "target": "all", "start": 3}
        >>> body |= {"duration": 2, "strength": "0.5"}
        >>> QualityDropCreate.model_validate(body).notice
        0
    """

    kind: Literal["quality_drop"]
    target: Target
    start: Periods
    duration: Annotated[Periods, Field(ge=1)]
    notice: Notice = 0
    strength: ShareFrom0To1


class TransportDelayCreate(StrictModel):
    """A transport delay: a delivery that would arrive while active arrives later.

    Attributes:
        kind (Literal["transport_delay"]): "transport_delay".
        target (tuple[str, ...] | str | Mapping[str, str]): Supplier identifiers,
            "all", or a group as `{kind: identifier}`.
        start (int): The first period it acts.
        duration (int): Periods it acts, at least 1.
        notice (int, optional): Periods before `start` from which it is visible.
        delay (int): Periods added to an arrival, at least 1.

    Examples:
        >>> body = {"kind": "transport_delay", "target": "all", "start": 3}
        >>> body |= {"duration": 2, "delay": 1}
        >>> TransportDelayCreate.model_validate(body).notice
        0
    """

    kind: Literal["transport_delay"]
    target: Target
    start: Periods
    duration: Annotated[Periods, Field(ge=1)]
    notice: Notice = 0
    delay: Annotated[Periods, Field(ge=1)]


class DemandShockCreate(StrictModel):
    """A demand shock: demand of a product from every customer changes while active.

    Attributes:
        kind (Literal["demand_shock"]): "demand_shock".
        target (tuple[str, ...] | str | Mapping[str, str]): Product identifiers,
            "all", or a group as `{kind: identifier}`.
        start (int): The first period it acts.
        duration (int): Periods it acts, at least 1.
        notice (int, optional): Periods before `start` from which it is visible.
        factor (Decimal): The factor of demand, above 0.

    Examples:
        >>> body = {"kind": "demand_shock", "target": "all", "start": 3}
        >>> body |= {"duration": 2, "factor": "1.5"}
        >>> DemandShockCreate.model_validate(body).notice
        0
    """

    kind: Literal["demand_shock"]
    target: Target
    start: Periods
    duration: Annotated[Periods, Field(ge=1)]
    notice: Notice = 0
    factor: FactorAbove0


class LineBreakdownCreate(StrictModel):
    """A line breakdown: a line loses condition once, in its start period.

    Attributes:
        kind (Literal["line_breakdown"]): "line_breakdown".
        target (tuple[str, ...] | str | Mapping[str, str]): Line identifiers,
            "all", or a group as `{kind: identifier}`.
        start (int): The period it acts.
        notice (int, optional): Periods before `start` from which it is visible.
        loss (Decimal): Share of the condition lost.

    Examples:
        >>> body = {"kind": "line_breakdown", "target": "all", "start": 3}
        >>> body |= {"loss": "0.3"}
        >>> LineBreakdownCreate.model_validate(body).notice
        0
    """

    kind: Literal["line_breakdown"]
    target: Target
    start: Periods
    loss: ShareFrom0To1
    notice: Notice = 0


class PriceChangeCreate(StrictModel):
    """A price change: the price of a material at every supplier changes while active.

    Attributes:
        kind (Literal["price_change"]): "price_change".
        target (tuple[str, ...] | str | Mapping[str, str]): Material identifiers,
            "all", or a group as `{kind: identifier}`.
        start (int): The first period it acts.
        duration (int): Periods it acts, at least 1.
        notice (int, optional): Periods before `start` from which it is visible.
        factor (Decimal): The factor of the price, above 0.

    Examples:
        >>> body = {"kind": "price_change", "target": "all", "start": 3}
        >>> body |= {"duration": 2, "factor": "1.2"}
        >>> PriceChangeCreate.model_validate(body).notice
        0
    """

    kind: Literal["price_change"]
    target: Target
    start: Periods
    duration: Annotated[Periods, Field(ge=1)]
    notice: Notice = 0
    factor: FactorAbove0


class CapacityCutCreate(StrictModel):
    """A capacity cut: a line has fewer hours while active.

    Attributes:
        kind (Literal["capacity_cut"]): "capacity_cut".
        target (tuple[str, ...] | str | Mapping[str, str]): Line identifiers,
            "all", or a group as `{kind: identifier}`.
        start (int): The first period it acts.
        duration (int): Periods it acts, at least 1.
        notice (int, optional): Periods before `start` from which it is visible.
        strength (Decimal): Share of the capacity that is lost.

    Examples:
        >>> body = {"kind": "capacity_cut", "target": "all", "start": 3}
        >>> body |= {"duration": 2, "strength": "0.5"}
        >>> CapacityCutCreate.model_validate(body).notice
        0
    """

    kind: Literal["capacity_cut"]
    target: Target
    start: Periods
    duration: Annotated[Periods, Field(ge=1)]
    notice: Notice = 0
    strength: ShareFrom0To1


class YieldDropCreate(StrictModel):
    """A yield drop: production started on a line while active has fewer good units.

    Attributes:
        kind (Literal["yield_drop"]): "yield_drop".
        target (tuple[str, ...] | str | Mapping[str, str]): Line identifiers,
            "all", or a group as `{kind: identifier}`.
        start (int): The first period it acts.
        duration (int): Periods it acts, at least 1.
        notice (int, optional): Periods before `start` from which it is visible.
        strength (Decimal): Share of the good units that is lost.

    Examples:
        >>> body = {"kind": "yield_drop", "target": "all", "start": 3}
        >>> body |= {"duration": 2, "strength": "0.5"}
        >>> YieldDropCreate.model_validate(body).notice
        0
    """

    kind: Literal["yield_drop"]
    target: Target
    start: Periods
    duration: Annotated[Periods, Field(ge=1)]
    notice: Notice = 0
    strength: ShareFrom0To1


type DisruptionCreate = Annotated[
    SupplierOutageCreate
    | MaterialShortageCreate
    | QualityDropCreate
    | TransportDelayCreate
    | DemandShockCreate
    | LineBreakdownCreate
    | PriceChangeCreate
    | CapacityCutCreate
    | YieldDropCreate,
    Field(discriminator="kind"),
]


class Cascade(StrictModel):
    """A raise of the chance of one rule after a disruption of another rule starts.

    Attributes:
        rule (str): The name of the rule whose chance is raised.
        factor (Decimal): The factor on its chance, above 1.
        periods (int): Periods after each start in which the chance is raised.

    Examples:
        >>> body = {"rule": "delays", "factor": "3", "periods": 2}
        >>> Cascade.model_validate(body).factor
        Decimal('3.0000')
    """

    rule: Identifier
    factor: Annotated[Share, Field(gt=1)]
    periods: Periods


class RandomDisruptionBase(StrictModel):
    """The keys every rule of random disruptions has.

    Attributes:
        name (str): The identifier of the rule, unique in the scenario.
        target (tuple[str, ...] | str | Mapping[str, str]): The identifiers it may
            act on, "all", or a group as `{kind: identifier}`.
        chance (Decimal | None, optional): The chance of a start in a period;
            required without `start`.
        choose (str | None, optional): "one" to hit one target per start; None to
            let every target start on its own.
        notice (int, optional): Periods before its start from which each is
            visible, from period 1 at the earliest.
        start (int | None, optional): The one period in which the rule starts its
            disruption, on one drawn target; None to start by chance.
        raises (Cascade | None, optional): The raise of the chance of another rule
            after each start of this one.

    Examples:
        >>> body = {"name": "rule", "target": "all", "chance": "0.1"}
        >>> RandomDisruptionBase.model_validate(body).choose is None
        True
    """

    name: Identifier
    target: Target
    chance: ShareFrom0To1 | None = None
    choose: Literal["one"] | None = None
    notice: Notice = 0
    start: Periods | None = None
    raises: Cascade | None = None


FactorParameter = Annotated[
    Annotated[FactorAbove0, Tag(FIXED_TAG)]
    | Annotated[Range[FactorAbove0], Tag(RANGE_TAG)],
    Discriminator(fixed_or_range),
]


class RandomSupplierOutageCreate(RandomDisruptionBase):
    """Random outages of suppliers.

    Attributes:
        kind (Literal["supplier_outage"]): "supplier_outage".
        duration (int | Range): Periods each acts.
        strength (Decimal | Range): Share of the arriving quantity that does not arrive.

    Examples:
        >>> rule = {"name": "rule", "target": "all", "chance": "0.1"}
        >>> body = {**rule, "kind": "supplier_outage"}
        >>> body |= {"duration": 2, "strength": "0.5"}
        >>> RandomSupplierOutageCreate.model_validate(body).chance
        Decimal('0.1000')
    """

    kind: Literal["supplier_outage"]
    duration: PeriodsParameter
    strength: ShareParameter


class RandomMaterialShortageCreate(RandomDisruptionBase):
    """Random shortages of materials.

    Attributes:
        kind (Literal["material_shortage"]): "material_shortage".
        duration (int | Range): Periods each acts.
        strength (Decimal | Range): Share of `max_quantity` that cannot be bought.

    Examples:
        >>> rule = {"name": "rule", "target": "all", "chance": "0.1"}
        >>> body = {**rule, "kind": "material_shortage"}
        >>> body |= {"duration": 2, "strength": "0.5"}
        >>> RandomMaterialShortageCreate.model_validate(body).chance
        Decimal('0.1000')
    """

    kind: Literal["material_shortage"]
    duration: PeriodsParameter
    strength: ShareParameter


class RandomQualityDropCreate(RandomDisruptionBase):
    """Random drops of the quality of suppliers.

    Attributes:
        kind (Literal["quality_drop"]): "quality_drop".
        duration (int | Range): Periods each acts.
        strength (Decimal | Range): Share of the acceptance that is lost.

    Examples:
        >>> rule = {"name": "rule", "target": "all", "chance": "0.1"}
        >>> body = {**rule, "kind": "quality_drop"}
        >>> body |= {"duration": 2, "strength": "0.5"}
        >>> RandomQualityDropCreate.model_validate(body).chance
        Decimal('0.1000')
    """

    kind: Literal["quality_drop"]
    duration: PeriodsParameter
    strength: ShareParameter


class RandomTransportDelayCreate(RandomDisruptionBase):
    """Random delays of the deliveries of suppliers.

    Attributes:
        kind (Literal["transport_delay"]): "transport_delay".
        duration (int | Range): Periods each acts.
        delay (int | Range): Periods added to an arrival.

    Examples:
        >>> rule = {"name": "rule", "target": "all", "chance": "0.1"}
        >>> body = {**rule, "kind": "transport_delay"}
        >>> body |= {"duration": 2, "delay": 1}
        >>> RandomTransportDelayCreate.model_validate(body).chance
        Decimal('0.1000')
    """

    kind: Literal["transport_delay"]
    duration: PeriodsParameter
    delay: PeriodsParameter


class RandomDemandShockCreate(RandomDisruptionBase):
    """Random shocks of the demand of products.

    Attributes:
        kind (Literal["demand_shock"]): "demand_shock".
        duration (int | Range): Periods each acts.
        factor (Decimal | Range): Factor on demand, above 0.

    Examples:
        >>> rule = {"name": "rule", "target": "all", "chance": "0.1"}
        >>> body = {**rule, "kind": "demand_shock"}
        >>> body |= {"duration": 2, "factor": "1.5"}
        >>> RandomDemandShockCreate.model_validate(body).chance
        Decimal('0.1000')
    """

    kind: Literal["demand_shock"]
    duration: PeriodsParameter
    factor: FactorParameter


class RandomLineBreakdownCreate(RandomDisruptionBase):
    """Random breakdowns of lines, each in its start period only.

    Attributes:
        kind (Literal["line_breakdown"]): "line_breakdown".
        loss (Decimal | Range): Share of the condition lost.

    Examples:
        >>> rule = {"name": "rule", "target": "all", "chance": "0.1"}
        >>> body = {**rule, "kind": "line_breakdown"}
        >>> body |= {"loss": "0.3"}
        >>> RandomLineBreakdownCreate.model_validate(body).chance
        Decimal('0.1000')
    """

    kind: Literal["line_breakdown"]
    loss: ShareParameter


class RandomPriceChangeCreate(RandomDisruptionBase):
    """Random changes of the prices of materials.

    Attributes:
        kind (Literal["price_change"]): "price_change".
        duration (int | Range): Periods each acts.
        factor (Decimal | Range): Factor on price, above 0.

    Examples:
        >>> rule = {"name": "rule", "target": "all", "chance": "0.1"}
        >>> body = {**rule, "kind": "price_change"}
        >>> body |= {"duration": 2, "factor": "1.2"}
        >>> RandomPriceChangeCreate.model_validate(body).chance
        Decimal('0.1000')
    """

    kind: Literal["price_change"]
    duration: PeriodsParameter
    factor: FactorParameter


class RandomCapacityCutCreate(RandomDisruptionBase):
    """Random cuts of the capacity of lines.

    Attributes:
        kind (Literal["capacity_cut"]): "capacity_cut".
        duration (int | Range): Periods each acts.
        strength (Decimal | Range): Share of the capacity that is lost.

    Examples:
        >>> rule = {"name": "rule", "target": "all", "chance": "0.1"}
        >>> body = {**rule, "kind": "capacity_cut"}
        >>> body |= {"duration": 2, "strength": "0.5"}
        >>> RandomCapacityCutCreate.model_validate(body).chance
        Decimal('0.1000')
    """

    kind: Literal["capacity_cut"]
    duration: PeriodsParameter
    strength: ShareParameter


class RandomYieldDropCreate(RandomDisruptionBase):
    """Random drops of the yield of lines.

    Attributes:
        kind (Literal["yield_drop"]): "yield_drop".
        duration (int | Range): Periods each acts.
        strength (Decimal | Range): Share of the good units that is lost.

    Examples:
        >>> rule = {"name": "rule", "target": "all", "chance": "0.1"}
        >>> body = {**rule, "kind": "yield_drop"}
        >>> body |= {"duration": 2, "strength": "0.5"}
        >>> RandomYieldDropCreate.model_validate(body).chance
        Decimal('0.1000')
    """

    kind: Literal["yield_drop"]
    duration: PeriodsParameter
    strength: ShareParameter


type RandomDisruptionCreate = Annotated[
    RandomSupplierOutageCreate
    | RandomMaterialShortageCreate
    | RandomQualityDropCreate
    | RandomTransportDelayCreate
    | RandomDemandShockCreate
    | RandomLineBreakdownCreate
    | RandomPriceChangeCreate
    | RandomCapacityCutCreate
    | RandomYieldDropCreate,
    Field(discriminator="kind"),
]


class ShapeTarget(StrictModel):
    """The customer, the product, or the customer product a demand shape targets.

    Attributes:
        customer (str | None, optional): The identifier of the customer; every customer
            if absent.
        product (str | None, optional): The identifier of the product; every product if
            absent.

    Examples:
        >>> ShapeTarget(product="monitor").customer is None
        True
    """

    customer: str | None = None
    product: str | None = None


type ShapeTargetCreate = Annotated[
    ShapeTarget | Literal["all"] | GroupTarget, Field(union_mode="left_to_right")
]


class TrendCreate(StrictModel):
    """Demand that grows or shrinks by a rate every period.

    Attributes:
        kind (Literal["trend"]): "trend".
        target (ShapeTarget | str | Mapping[str, str]): What it targets, "all", or
            a group as `{kind: identifier}`.
        rate (Decimal): The growth per period, above -1.

    Examples:
        >>> body = {"kind": "trend", "target": "all", "rate": "0.02"}
        >>> TrendCreate.model_validate(body).rate
        Decimal('0.0200')
    """

    kind: Literal["trend"]
    target: ShapeTargetCreate
    rate: Annotated[Share, Field(gt=-1)]


class SeasonCreate(StrictModel):
    """Demand that repeats a list of factors, each for a number of periods.

    Attributes:
        kind (Literal["season"]): "season".
        target (ShapeTarget | str | Mapping[str, str]): What it targets, "all", or
            a group as `{kind: identifier}`.
        factors (tuple[Decimal, ...]): The factors, at least one.
        period_length (int): Periods each factor lasts, at least 1.

    Examples:
        >>> body = {"kind": "season", "target": "all", "factors": ["0.8", "1.2"]}
        >>> SeasonCreate.model_validate({**body, "period_length": 4}).period_length
        4
    """

    kind: Literal["season"]
    target: ShapeTargetCreate
    factors: Annotated[ReadOnlyList[FactorAtLeast0], Field(min_length=1)]
    period_length: Annotated[Periods, Field(ge=1)]


class StepCreate(StrictModel):
    """Demand times a factor from a period on.

    Attributes:
        kind (Literal["step"]): "step".
        target (ShapeTarget | str | Mapping[str, str]): What it targets, "all", or
            a group as `{kind: identifier}`.
        period (int): The first period of the factor.
        factor (Decimal): The factor, at least 0.

    Examples:
        >>> body = {"kind": "step", "target": "all", "period": 5, "factor": "1.5"}
        >>> StepCreate.model_validate(body).factor
        Decimal('1.5000')
    """

    kind: Literal["step"]
    target: ShapeTargetCreate
    period: Periods
    factor: FactorAtLeast0


class RampCreate(StrictModel):
    """Demand that moves in a straight line from one factor to another.

    Attributes:
        kind (Literal["ramp"]): "ramp".
        target (ShapeTarget | str | Mapping[str, str]): What it targets, "all", or
            a group as `{kind: identifier}`.
        first (int): The last period of `from_factor`.
        last (int): The first period of `to_factor`, after `first`.
        from_factor (Decimal): The factor up to `first`.
        to_factor (Decimal): The factor from `last`.

    Examples:
        >>> body = {"kind": "ramp", "target": "all", "first": 2, "last": 6}
        >>> factors = {"from_factor": 1, "to_factor": 2}
        >>> RampCreate.model_validate({**body, **factors}).last
        6
    """

    kind: Literal["ramp"]
    target: ShapeTargetCreate
    first: Periods
    last: Periods
    from_factor: FactorAtLeast0
    to_factor: FactorAtLeast0

    @field_validator("last")
    @classmethod
    def last_after_first(cls, last: int, validation_info: ValidationInfo) -> int:
        """Refuse a ramp whose `last` is not after its `first`.

        Args:
            last (int): The first period of `to_factor`.
            validation_info (ValidationInfo): The fields read before it.

        Returns:
            int: The period.

        Raises:
            ValueError: If it is not after `first`.

        Examples:
            >>> body = {"kind": "ramp", "target": "all", "first": 2, "last": 6}
            >>> factors = {"from_factor": 1, "to_factor": 2}
            >>> RampCreate.model_validate({**body, **factors}).last
            6
        """
        if "first" in validation_info.data and last <= validation_info.data["first"]:
            raise ValueError("is not after first")
        return last


class SCurveCreate(StrictModel):
    """Demand that moves along an s-curve from one factor to another.

    Attributes:
        kind (Literal["s_curve"]): "s_curve".
        target (ShapeTarget | str | Mapping[str, str]): What it targets, "all", or
            a group as `{kind: identifier}`.
        middle (int): The period halfway between the factors; may lie outside the
            horizon.
        steepness (Decimal): How fast it moves, above 0.
        from_factor (Decimal): The factor long before the middle.
        to_factor (Decimal): The factor long after the middle.

    Examples:
        >>> body = {"kind": "s_curve", "target": "all", "middle": 6, "steepness": "0.5"}
        >>> factors = {"from_factor": 1, "to_factor": 2}
        >>> SCurveCreate.model_validate({**body, **factors}).middle
        6
    """

    kind: Literal["s_curve"]
    target: ShapeTargetCreate
    middle: Periods
    steepness: Annotated[Share, Field(gt=0)]
    from_factor: FactorAtLeast0
    to_factor: FactorAtLeast0


type DemandShapeCreate = Annotated[
    TrendCreate | SeasonCreate | StepCreate | RampCreate | SCurveCreate,
    Field(discriminator="kind"),
]


class ForecastCreate(StrictModel):
    """Forecasts of the demand of the customer products an entry targets.

    Attributes:
        target (ShapeTarget | str | Mapping[str, str]): What it targets, "all", or
            a group as `{kind: identifier}`.
        periods_ahead (int): Periods each forecast looks ahead, 1 to the horizon.
        noise (Decimal): The width of the error one period ahead, 0 to 1.
        noise_growth (Decimal): The growth of the width with each further period,
            0 to 1.

    Examples:
        >>> body = {"target": "all", "periods_ahead": 4, "noise": "0.1"}
        >>> ForecastCreate.model_validate({**body, "noise_growth": "0.05"}).noise
        Decimal('0.1000')
    """

    target: ShapeTargetCreate
    periods_ahead: Periods
    noise: ShareFrom0To1
    noise_growth: ShareFrom0To1


class ScenarioCreate(StrictModel):
    """The conditions of a run of a manifest, as a client sends them.

    Attributes:
        name (str | None, optional): A readable name, never shown to the agent.
        description (str | None, optional): A readable description, never shown to the
            agent.
        horizon (int): Number of periods.
        start (Start, optional): The state before period 1.
        demand_shapes (tuple[DemandShapeCreate, ...], optional): Shapes of demand over
            time.
        forecasts (tuple[ForecastCreate, ...], optional): Forecast entries, at most
            one per customer product.
        disruptions (tuple[DisruptionCreate, ...], optional): Written disruptions,
            numbered `disruption-<n>` in the order of `start - notice`, then of the
            list.
        random_disruptions (tuple[RandomDisruptionCreate, ...], optional): Rules of
            disruptions drawn from the seed.
        hidden (tuple[str, ...], optional): The parameter groups kept from the
            agent.

    Examples:
        >>> ScenarioCreate(horizon=12).horizon
        12
    """

    name: str | None = None
    description: str | None = None
    horizon: Annotated[Periods, Field(ge=1, le=520)]
    start: Start = Field(default_factory=Start)
    demand_shapes: ReadOnlyList[DemandShapeCreate] = ()
    forecasts: ReadOnlyList[ForecastCreate] = ()
    disruptions: ReadOnlyList[DisruptionCreate] = ()
    random_disruptions: ReadOnlyList[RandomDisruptionCreate] = ()
    hidden: ReadOnlyList[str] = ()


class ScenarioPublic(StrictModel):
    """A stored scenario.

    Attributes:
        id (str): The SHA-256 digest, in 64 hexadecimal digits, of the canonical JSON
            of its manifest identifier and its content.
        content (ScenarioCreate): The scenario with defaults written.

    Examples:
        >>> ScenarioPublic(id="a1", content=ScenarioCreate(horizon=12)).content.horizon
        12
    """

    id: str
    content: ScenarioCreate


class ScenarioSummary(StrictModel):
    """One scenario in a list.

    Attributes:
        id (str): The identifier.
        name (str | None): Its readable name.
        description (str | None): Its readable description.

    Examples:
        >>> ScenarioSummary(id="a1", name="steady-market", description=None).name
        'steady-market'
    """

    id: str
    name: str | None
    description: str | None


class ScenariosPublic(StrictModel):
    """The scenarios of a manifest.

    Attributes:
        scenarios (tuple[ScenarioSummary, ...]): The scenarios, by identifier.

    Examples:
        >>> ScenariosPublic(scenarios=()).scenarios
        ()
    """

    scenarios: tuple[ScenarioSummary, ...]
