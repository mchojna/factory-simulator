"""The models of a manifest: the body that describes a factory.

Examples:
    >>> Warehouse(capacity="500").storage_factor
    Decimal('1.0000')
"""

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Annotated, Literal, Self, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic.config import JsonDict

from factory_simulator.api.core.numbers import (
    DISTRIBUTION_TAGS,
    FIXED_TAG,
    RANGE_TAG,
    Count,
    Money,
    Periods,
    Quantity,
    ReadOnlyList,
    ReadOnlyMapping,
    Seed,
    Share,
    StrictModel,
)


def distribution_of(value: object) -> str:
    """Tell the distribution of a range in a body or in a model.

    Args:
        value (object): A range.

    Returns:
        str: The tag of its distribution; an unknown one reads as uniform, whose
            model then refuses the word at `distribution`.

    Examples:
        >>> distribution_of({"min": 1, "max": 2, "distribution": "normal"})
        'normal range'
    """
    if isinstance(value, Mapping):
        distribution = cast(Mapping[str, object], value).get("distribution", "uniform")
    else:
        distribution = getattr(value, "distribution", "uniform")
    tag = f"{distribution} range"
    return tag if tag in DISTRIBUTION_TAGS else "uniform range"


def uniform_only(value: object) -> object:
    """Refuse a range of periods whose values are not spread evenly.

    Args:
        value (object): A range of periods.

    Returns:
        object: The range.

    Raises:
        ValueError: If its distribution is not uniform.

    Examples:
        >>> uniform_only(UniformRange[int](min=1, max=3)).max
        3
    """
    if getattr(value, "distribution", "uniform") != "uniform":
        raise ValueError("a range of periods is uniform only")
    return value


def fixed_or_range(value: object) -> str:
    """Tell a parameter given as a range from one given as a fixed number.

    Args:
        value (object): The value of a parameter in a body, or in a model.

    Returns:
        str: The tag of its form; tags hold a space, so no identifier equals them.

    Examples:
        >>> fixed_or_range({"min": 1, "max": 2})
        'range value'
    """
    return RANGE_TAG if isinstance(value, Mapping | BaseModel) else FIXED_TAG


def optional_group_keys(defaults: type[BaseModel]) -> Callable[[JsonDict], None]:
    """Give the change of the JSON schema of a member that its groups can complete.

    A member of a group may leave out every key that a group gives, so its JSON
    schema requires none of them. Its model, which reads the member once the values
    of its groups are written into it, still requires them.

    Args:
        defaults (type[BaseModel]): The model of what a group gives such a member.

    Returns:
        Callable[[JsonDict], None]: A function that takes those keys out of the
            required keys of a JSON schema, changed in place.

    Examples:
        >>> schema = {"required": ["capacity", "items"]}
        >>> optional_group_keys(LineDefaults)(schema)
        >>> schema
        {'required': ['items']}
    """
    keys = {field.alias or name for name, field in defaults.model_fields.items()}

    def leave_out(schema: JsonDict) -> None:
        required = cast(list[str], schema.get("required", []))
        schema["required"] = [key for key in required if key not in keys]
        if not schema["required"]:
            del schema["required"]

    return leave_out


class UniformRange[N: (Decimal, int)](StrictModel):
    """A range a parameter is drawn from, every value with equal chance.

    Attributes:
        min (Decimal | int): The smallest value.
        max (Decimal | int): The largest value.
        distribution (Literal["uniform"], optional): "uniform".

    Examples:
        >>> UniformRange[Decimal](min=Decimal("0.8000"), max=Decimal("0.9200")).max
        Decimal('0.9200')
    """

    min: N
    max: N
    distribution: Literal["uniform"] = "uniform"

    @model_validator(mode="after")
    def min_not_above_max(self) -> Self:
        """Refuse a range whose `min` is above its `max`.

        Returns:
            Self: The range.

        Raises:
            ValueError: If `min` is above `max`.

        Examples:
            >>> UniformRange[int](min=1, max=3).min_not_above_max().min
            1
        """
        if self.min > self.max:
            raise ValueError("min is above max")
        return self


class TriangularRange[N: (Decimal, int)](StrictModel):
    """A range whose values are most likely near its mode.

    Attributes:
        min (Decimal | int): The smallest value.
        max (Decimal | int): The largest value.
        distribution (Literal["triangular"]): "triangular".
        mode (Decimal | int): The most likely value.

    Examples:
        >>> body = {"min": 1, "max": 5, "distribution": "triangular", "mode": 2}
        >>> TriangularRange[int].model_validate(body).mode
        2
    """

    min: N
    max: N
    distribution: Literal["triangular"]
    mode: N

    @model_validator(mode="after")
    def mode_within(self) -> Self:
        """Refuse a range whose `min` is not below `max` or whose mode lies outside.

        Returns:
            Self: The range.

        Raises:
            ValueError: If `min` is not below `max` or the mode is outside.

        Examples:
            >>> body = {"min": 1, "max": 5, "distribution": "triangular", "mode": 2}
            >>> TriangularRange[int].model_validate(body).mode_within().mode
            2
        """
        if self.min >= self.max:
            raise ValueError("a triangular range needs min below max")
        if not self.min <= self.mode <= self.max:
            raise ValueError("mode is outside min to max")
        return self


class NormalRange[N: (Decimal, int)](StrictModel):
    """A normal distribution cut to a range.

    Attributes:
        min (Decimal | int): The smallest value.
        max (Decimal | int): The largest value.
        distribution (Literal["normal"]): "normal".
        mean (Decimal | int): The mean before the cut.
        sd (Decimal | int): The standard deviation before the cut.

    Examples:
        >>> body = {"min": 1, "max": 9, "distribution": "normal", "mean": 5, "sd": 2}
        >>> NormalRange[int].model_validate(body).sd
        2
    """

    min: N
    max: N
    distribution: Literal["normal"]
    mean: N
    sd: N

    @model_validator(mode="after")
    def mean_within(self) -> Self:
        """Refuse a range whose `min`, `max`, mean or `sd` do not fit together.

        `min` is below `max`, the mean between them and `sd` above 0.

        Returns:
            Self: The range.

        Raises:
            ValueError: If `min` is not below `max`, the mean is outside them or `sd`
                is not above 0.

        Examples:
            >>> body = {"min": 1, "max": 9, "distribution": "normal"}
            >>> body |= {"mean": 5, "sd": 2}
            >>> NormalRange[int].model_validate(body).mean_within().mean
            5
        """
        if self.min >= self.max:
            raise ValueError("a normal range needs min below max")
        if not self.min <= self.mean <= self.max:
            raise ValueError("mean is outside min to max")
        if self.sd <= 0:
            raise ValueError("sd is not above 0")
        return self


class LognormalRange[N: (Decimal, int)](StrictModel):
    """A lognormal distribution cut to a range.

    Attributes:
        min (Decimal | int): The smallest value.
        max (Decimal | int): The largest value.
        distribution (Literal["lognormal"]): "lognormal".
        median (Decimal | int): The median before the cut.
        spread (Decimal): The standard deviation of the natural logarithm.

    Examples:
        >>> body = {"min": 10, "max": 90, "distribution": "lognormal"}
        >>> body |= {"median": 30, "spread": 1}
        >>> LognormalRange[int].model_validate(body).spread
        Decimal('1.0000')
    """

    min: N
    max: N
    distribution: Literal["lognormal"]
    median: N
    spread: Annotated[Share, Field(ge=0)]

    @model_validator(mode="after")
    def median_within(self) -> Self:
        """Refuse a range whose `min`, `max`, median or `spread` do not fit together.

        `min` is above 0 and below `max`, the median between them, `spread` above 0
        and at most 10.

        Returns:
            Self: The range.

        Raises:
            ValueError: If `min` is not above 0 or not below `max`, the median is
                outside them, or `spread` is not above 0 or is above 10.

        Examples:
            >>> body = {"min": 10, "max": 90, "distribution": "lognormal"}
            >>> body |= {"median": 30, "spread": 1}
            >>> LognormalRange[int].model_validate(body).median_within().median
            30
            >>> wide = body | {"spread": Decimal("10.0001")}
            >>> LognormalRange[int].model_construct(**wide).median_within()
            Traceback (most recent call last):
            ...
            ValueError: spread is above 10
        """
        if self.min <= 0:
            raise ValueError("a lognormal range needs min above 0")
        if self.min >= self.max:
            raise ValueError("a lognormal range needs min below max")
        if not self.min <= self.median <= self.max:
            raise ValueError("median is outside min to max")
        if self.spread <= 0:
            raise ValueError("spread is not above 0")
        if self.spread > 10:
            raise ValueError("spread is above 10")
        return self


# A range of a parameter, read by its distribution.
type Range[N: (Decimal, int)] = Annotated[
    Annotated[UniformRange[N], Tag("uniform range")]
    | Annotated[TriangularRange[N], Tag("triangular range")]
    | Annotated[NormalRange[N], Tag("normal range")]
    | Annotated[LognormalRange[N], Tag("lognormal range")],
    Discriminator(distribution_of),
]


# The numbers with the bounds of their kind.
QuantityAtLeast0 = Annotated[Quantity, Field(ge=0)]
QuantityAbove0 = Annotated[Quantity, Field(gt=0)]
MoneyAtLeast0 = Annotated[Money, Field(ge=0)]
ShareFrom0To1 = Annotated[Share, Field(ge=0, le=1)]
ShareAbove0To1 = Annotated[Share, Field(gt=0, le=1)]
RateAtLeast0 = Annotated[Share, Field(ge=0)]
FactorAbove0 = Annotated[Share, Field(gt=0)]
PeriodsAtLeast0 = Annotated[Periods, Field(ge=0)]
PeriodsAtLeast1 = Annotated[Periods, Field(ge=1)]

QuantityParameter = Annotated[
    Annotated[QuantityAtLeast0, Tag(FIXED_TAG)]
    | Annotated[Range[QuantityAtLeast0], Tag(RANGE_TAG)],
    Discriminator(fixed_or_range),
]
PositiveQuantityParameter = Annotated[
    Annotated[QuantityAbove0, Tag(FIXED_TAG)]
    | Annotated[Range[QuantityAbove0], Tag(RANGE_TAG)],
    Discriminator(fixed_or_range),
]
MoneyParameter = Annotated[
    Annotated[MoneyAtLeast0, Tag(FIXED_TAG)]
    | Annotated[Range[MoneyAtLeast0], Tag(RANGE_TAG)],
    Discriminator(fixed_or_range),
]
ShareParameter = Annotated[
    Annotated[ShareFrom0To1, Tag(FIXED_TAG)]
    | Annotated[Range[ShareFrom0To1], Tag(RANGE_TAG)],
    Discriminator(fixed_or_range),
]
PositiveShareParameter = Annotated[
    Annotated[ShareAbove0To1, Tag(FIXED_TAG)]
    | Annotated[Range[ShareAbove0To1], Tag(RANGE_TAG)],
    Discriminator(fixed_or_range),
]
RateParameter = Annotated[
    Annotated[RateAtLeast0, Tag(FIXED_TAG)]
    | Annotated[Range[RateAtLeast0], Tag(RANGE_TAG)],
    Discriminator(fixed_or_range),
]
PeriodsParameter = Annotated[
    Annotated[PeriodsAtLeast0, Tag(FIXED_TAG)]
    | Annotated[Range[PeriodsAtLeast0], AfterValidator(uniform_only), Tag(RANGE_TAG)],
    Discriminator(fixed_or_range),
]
PositivePeriodsParameter = Annotated[
    Annotated[PeriodsAtLeast1, Tag(FIXED_TAG)]
    | Annotated[Range[PeriodsAtLeast1], AfterValidator(uniform_only), Tag(RANGE_TAG)],
    Discriminator(fixed_or_range),
]


class PriceDrawing(StrictModel):
    """When the range of a catalogue price is drawn.

    Attributes:
        drawn (str, optional): "run" to draw once per run, "period" to draw once per
            period.

    Examples:
        >>> PriceDrawing(drawn="period").drawn
        'period'
    """

    drawn: str = "run"

    @model_validator(mode="after")
    def drawn_per_run_or_per_period(self) -> Self:
        """Refuse a moment of drawing other than `run` or `period`.

        Returns:
            Self: The moment of drawing.

        Raises:
            ValueError: If `drawn` is neither `run` nor `period`.

        Examples:
            >>> PriceDrawing().drawn_per_run_or_per_period().drawn
            'run'
        """
        if self.drawn not in ("run", "period"):
            raise ValueError(f"drawn is run or period, got {self.drawn}")
        return self


class UniformPriceRange(UniformRange[MoneyAtLeast0], PriceDrawing):
    """A uniform range of a catalogue price, with its moment of drawing.

    Examples:
        >>> UniformPriceRange(min="2.2", max="2.6", drawn="period").max
        Decimal('2.6000')
    """


class TriangularPriceRange(TriangularRange[MoneyAtLeast0], PriceDrawing):
    """A triangular range of a catalogue price, with its moment of drawing.

    Examples:
        >>> body = {"min": "2.2", "max": "2.6", "distribution": "triangular"}
        >>> TriangularPriceRange.model_validate(body | {"mode": "2.4"}).drawn
        'run'
    """


class NormalPriceRange(NormalRange[MoneyAtLeast0], PriceDrawing):
    """A cut normal range of a catalogue price, with its moment of drawing.

    Examples:
        >>> body = {"min": "2.2", "max": "2.6", "distribution": "normal"}
        >>> body |= {"mean": "2.4", "sd": "0.1"}
        >>> NormalPriceRange.model_validate(body).sd
        Decimal('0.1000')
    """


class LognormalPriceRange(LognormalRange[MoneyAtLeast0], PriceDrawing):
    """A cut lognormal range of a catalogue price, with its moment of drawing.

    Examples:
        >>> body = {"min": "2.2", "max": "2.6", "distribution": "lognormal"}
        >>> body |= {"median": "2.4", "spread": "0.1"}
        >>> LognormalPriceRange.model_validate(body).median
        Decimal('2.4000')
    """


# The price of a catalogue entry: a fixed number or a range read by its distribution.
CataloguePriceParameter = Annotated[
    Annotated[MoneyAtLeast0, Tag(FIXED_TAG)]
    | Annotated[
        Annotated[UniformPriceRange, Tag("uniform range")]
        | Annotated[TriangularPriceRange, Tag("triangular range")]
        | Annotated[NormalPriceRange, Tag("normal range")]
        | Annotated[LognormalPriceRange, Tag("lognormal range")],
        Discriminator(distribution_of),
        Tag(RANGE_TAG),
    ],
    Discriminator(fixed_or_range),
]

# An identifier: lower case letters, digits and single hyphens, from a letter, at
# most 40 characters.
Identifier = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$", max_length=40)
]


class ItemDefaults(StrictModel):
    """The parameters a group gives its materials, components or products.

    Attributes:
        space (Decimal | None, optional): Space one unit takes.
        storage_cost (Decimal | Range | None, optional): Cost of holding one unit.
        salvage_value (Decimal | Range | None, optional): Worth of one unit at the end.
        common_share (Decimal | None, optional): For products, the share of the
            variation of demand their customers have in common.

    Examples:
        >>> ItemDefaults.model_validate({"space": "0.01"}).space
        Decimal('0.010')
    """

    space: QuantityAbove0 | None = None
    storage_cost: MoneyParameter | None = None
    salvage_value: MoneyParameter | None = None
    common_share: ShareFrom0To1 | None = None


class CatalogueDefaults(StrictModel):
    """The parameters a group gives the catalogue entries of its members.

    Attributes:
        price (Decimal | Range | None, optional): Price of one accepted unit.
        lead_time (int | Range | None, optional): Periods from placing to arrival when
            on time.
        max_quantity (Decimal | Range | None, optional): Largest quantity ordered in
            one period.
        punctuality (Decimal | Range | None, optional): Chance a delivery is on time.
        delay (int | Range | None, optional): Extra periods of a late delivery.
        completeness (Decimal | Range | None, optional): Share of the open quantity
            that arrives.
        acceptance (Decimal | Range | None, optional): Share of the arrived quantity
            that passes inspection.
        cancellation_fee (Decimal | Range | None, optional): Fee per cancelled unit.
        backfill_delay (int | Range | None, optional): Periods from a delivery to the
            backfill of the part missing by completeness; 0 loses that part.
        express_lead_time (int | Range | None, optional): Periods from placing to
            arrival of an express order when on time.
        express_cost (Decimal | Range | None, optional): Extra price per unit of an
            express order.
        min_quantity (Decimal | Range | None, optional): Smallest quantity of one
            order.

    Examples:
        >>> CatalogueDefaults.model_validate({"lead_time": 3}).lead_time
        3
    """

    price: CataloguePriceParameter | None = None
    lead_time: PositivePeriodsParameter | None = None
    max_quantity: PositiveQuantityParameter | None = None
    punctuality: ShareParameter | None = None
    delay: PositivePeriodsParameter | None = None
    completeness: ShareParameter | None = None
    acceptance: ShareParameter | None = None
    cancellation_fee: MoneyParameter | None = None
    backfill_delay: PeriodsParameter | None = None
    express_lead_time: PositivePeriodsParameter | None = None
    express_cost: MoneyParameter | None = None
    min_quantity: QuantityParameter | None = None


class LineItemDefaults(StrictModel):
    """The parameters a group gives the line items of its members.

    Attributes:
        time (Decimal | Range | None, optional): Hours per unit started.
        cost (Decimal | Range | None, optional): Cost per unit started.
        yield_ (Decimal | Range | None, optional): Share of good units, `yield` in
            JSON.
        lead_time (int | Range | None, optional): Periods of production.
        changeover_time (Decimal | Range | None, optional): Hours of a changeover.
        changeover_cost (Decimal | Range | None, optional): Cost of a changeover.

    Examples:
        >>> LineItemDefaults.model_validate({"yield": "0.9"}).yield_
        Decimal('0.9000')
    """

    time: PositiveQuantityParameter | None = None
    cost: MoneyParameter | None = None
    yield_: ShareParameter | None = Field(default=None, alias="yield")
    lead_time: PositivePeriodsParameter | None = None
    changeover_time: QuantityParameter | None = None
    changeover_cost: MoneyParameter | None = None


class CustomerProductDefaults(StrictModel):
    """The parameters a group gives the customer products of its members.

    Attributes:
        price (Decimal | Range | None, optional): Price of one shipped unit.
        transport_cost (Decimal | Range | None, optional): Cost of shipping one unit.
        demand (Decimal | Range | None, optional): Base demand per period.
        lead_time (int | Range | None, optional): Periods to the due period.
        patience (int | Range | None, optional): Periods before the rest is lost.
        late_penalty (Decimal | Range | None, optional): Penalty per late unit.
        lost_sale_penalty (Decimal | Range | None, optional): Penalty per lost unit.
        demand_persistence (Decimal | None, optional): Share of the previous base
            demand carried over.

    Examples:
        >>> CustomerProductDefaults.model_validate({"patience": 2}).patience
        2
    """

    price: MoneyParameter | None = None
    transport_cost: MoneyParameter | None = None
    demand: QuantityParameter | None = None
    lead_time: PeriodsParameter | None = None
    patience: PeriodsParameter | None = None
    late_penalty: MoneyParameter | None = None
    lost_sale_penalty: MoneyParameter | None = None
    demand_persistence: ShareFrom0To1 | None = None


class CustomerDefaults(StrictModel):
    """The parameters a group gives its customers.

    Attributes:
        payment_terms (int | Range | None, optional): Periods to payment.

    Examples:
        >>> CustomerDefaults.model_validate({"payment_terms": 4}).payment_terms
        4
    """

    payment_terms: PeriodsParameter | None = None


class LineDefaults(StrictModel):
    """The parameters a group gives its lines.

    Attributes:
        capacity (Decimal | Range | None, optional): Hours at condition 1.
        wear_per_period (Decimal | Range | None, optional): Condition lost per period.
        wear_per_hour (Decimal | Range | None, optional): Condition lost per hour.
        breakdown_chance (Decimal | Range | None, optional): Chance of a breakdown.
        breakdown_loss (Decimal | Range | None, optional): Condition lost in one.
        repair_cost (Decimal | Range | None, optional): Cost of a full repair.
        repair_time (Decimal | Range | None, optional): Hours of a full repair, above
            0.
        repair_limit (Decimal | Range | None, optional): Most condition restored.
        overtime_hours (Decimal | Range | None, optional): Extra hours.
        overtime_cost (Decimal | Range | None, optional): Cost of one extra hour.

    Examples:
        >>> LineDefaults.model_validate({"capacity": 40}).capacity
        Decimal('40.000')
    """

    capacity: PositiveQuantityParameter | None = None
    wear_per_period: ShareParameter | None = None
    wear_per_hour: RateParameter | None = None
    breakdown_chance: ShareParameter | None = None
    breakdown_loss: ShareParameter | None = None
    repair_cost: MoneyParameter | None = None
    repair_time: PositiveQuantityParameter | None = None
    repair_limit: PositiveShareParameter | None = None
    overtime_hours: QuantityParameter | None = None
    overtime_cost: MoneyParameter | None = None


class Material(StrictModel):
    """A material bought from suppliers.

    Attributes:
        name (str | None, optional): A readable name.
        description (str | None, optional): A readable description.
        unit (str | None, optional): The unit of a quantity.
        space (Decimal): Space one unit takes.
        storage_cost (Decimal | Range): Cost of holding one unit for one period.
        salvage_value (Decimal | Range): Worth of one unit in stock at the end.
        groups (tuple[str, ...], optional): The groups it is in, in the order their
            defaults apply.

    Examples:
        >>> body = {"space": "0.01", "storage_cost": "0.02", "salvage_value": "1"}
        >>> Material.model_validate(body).space
        Decimal('0.010')
    """

    model_config = ConfigDict(json_schema_extra=optional_group_keys(ItemDefaults))
    name: str | None = None
    description: str | None = None
    unit: str | None = None
    space: QuantityAbove0
    storage_cost: MoneyParameter
    salvage_value: MoneyParameter
    groups: ReadOnlyList[Identifier] = ()


class MadeItem(Material):
    """A component or a product, made on a line from one of its recipes.

    Attributes:
        recipes (Mapping[str, Mapping[str, Decimal]]): Per recipe name, the quantity
            of each input used for one unit.
        default_recipe (str | None, optional): The recipe of a produce decision that
            names none; filled with the only recipe of an item that has one.

    Examples:
        >>> body = {"space": "0.5", "storage_cost": "0.1", "salvage_value": "20"}
        >>> body |= {"recipes": {"main": {"chip": 4}}}
        >>> MadeItem.model_validate(body).default_recipe
        'main'
    """

    recipes: ReadOnlyMapping[Identifier, ReadOnlyMapping[Identifier, QuantityAbove0]]
    default_recipe: Identifier | None = None

    @model_validator(mode="before")
    @classmethod
    def fill_default_recipe(cls, value: object) -> object:
        """Fill the default recipe of an item with its only recipe when none is given.

        Args:
            value (object): The body of the item.

        Returns:
            object: The body, with `default_recipe` when it has one recipe and leaves
                out `default_recipe` or writes it as null.

        Examples:
            >>> MadeItem.fill_default_recipe({"recipes": {"main": {"chip": 4}}})
            {'recipes': {'main': {'chip': 4}}, 'default_recipe': 'main'}
            >>> body = {"recipes": {"main": {"chip": 4}}, "default_recipe": None}
            >>> MadeItem.fill_default_recipe(body)["default_recipe"]
            'main'
        """
        if not isinstance(value, Mapping):
            return value
        body = cast(Mapping[str, object], value)
        recipes = body.get("recipes")
        if body.get("default_recipe") is not None or not isinstance(recipes, Mapping):
            return body
        names = list(cast(Mapping[str, object], recipes))
        if len(names) == 1:
            return {**body, "default_recipe": names[0]}
        return body


class Product(MadeItem):
    """A product, made on a line from components and sold to customers.

    Attributes:
        common_share (Decimal | None, optional): Share of the variation of demand
            that the customers of the product have in common, from 0 to 1.

    Examples:
        >>> body = {"space": "0.5", "storage_cost": "0.1", "salvage_value": "20"}
        >>> body |= {"recipes": {"main": {"board": 1}}, "common_share": "0.6"}
        >>> Product.model_validate(body).common_share
        Decimal('0.6000')
    """

    common_share: ShareFrom0To1 | None = None


class DiscountTier(StrictModel):
    """A lower price for every unit of an order of at least a quantity.

    Attributes:
        from_ (Decimal): Smallest quantity of an order at this price, written `from`
            in JSON; a fixed number.
        price (Decimal | Range): Price of every unit of such an order.

    Examples:
        >>> DiscountTier.model_validate({"from": 100, "price": "1.8"}).from_
        Decimal('100.000')
    """

    from_: QuantityAtLeast0 = Field(alias="from")
    price: MoneyParameter


class CatalogueEntry(StrictModel):
    """The terms on which a supplier sells one material.

    Attributes:
        price (Decimal | Range): Price of one accepted unit.
        lead_time (int | Range): Periods from placing to arrival when on time.
        max_quantity (Decimal | Range): Largest quantity ordered in one period.
        punctuality (Decimal | Range): Chance a delivery is on time.
        delay (int | Range): Extra periods of a late delivery.
        completeness (Decimal | Range): Share of the open quantity that arrives.
        acceptance (Decimal | Range): Share of the arrived quantity that passes
            inspection.
        cancellation_fee (Decimal | Range, optional): Fee per cancelled unit.
        backfill_delay (int | Range, optional): Periods from a delivery to the
            backfill of the part missing by completeness; 0 loses that part.
        express_lead_time (int | Range | None, optional): Periods from placing to
            arrival of an express order when on time; None offers no express.
        express_cost (Decimal | Range | None, optional): Extra price per unit of an
            express order; given exactly when `express_lead_time` is.
        min_quantity (Decimal | Range | None, optional): Smallest quantity of one
            order; None for no minimum.
        discounts (tuple[DiscountTier, ...], optional): Tiers of lower prices, by
            rising `from`.

    Examples:
        >>> terms = {"price": "2", "lead_time": 2, "max_quantity": 500, "delay": 1}
        >>> shares = {"punctuality": "0.9", "completeness": 1, "acceptance": 1}
        >>> CatalogueEntry.model_validate({**terms, **shares}).backfill_delay
        0
    """

    model_config = ConfigDict(json_schema_extra=optional_group_keys(CatalogueDefaults))
    price: CataloguePriceParameter
    lead_time: PositivePeriodsParameter
    max_quantity: PositiveQuantityParameter
    punctuality: ShareParameter
    delay: PositivePeriodsParameter
    completeness: ShareParameter
    acceptance: ShareParameter
    cancellation_fee: MoneyParameter = Decimal("0.0000")
    backfill_delay: PeriodsParameter = 0
    express_lead_time: PositivePeriodsParameter | None = None
    express_cost: MoneyParameter | None = None
    min_quantity: QuantityParameter | None = None
    discounts: ReadOnlyList[DiscountTier] = ()


class Supplier(StrictModel):
    """A supplier of materials.

    Attributes:
        name (str | None, optional): A readable name.
        description (str | None, optional): A readable description.
        catalogue (Mapping[str, CatalogueEntry]): The entry of each material sold.
        groups (tuple[str, ...], optional): The groups it is in, in the order their
            defaults apply.

    Examples:
        >>> Supplier.model_validate({"catalogue": {}}).groups
        ()
    """

    name: str | None = None
    description: str | None = None
    catalogue: ReadOnlyMapping[Identifier, CatalogueEntry]
    groups: ReadOnlyList[Identifier] = ()


class CustomerProduct(StrictModel):
    """The terms on which a customer buys one product.

    Attributes:
        price (Decimal | Range): Price of one shipped unit.
        transport_cost (Decimal | Range): Cost of shipping one unit.
        demand (Decimal | Range): Base demand per period.
        lead_time (int | Range): Periods from an order's arrival to its due period.
        patience (int | Range): Periods after the due period before the rest is lost.
        late_penalty (Decimal | Range): Penalty per unit not shipped by the close of
            each period from the due period, except the period in which the order
            is lost.
        lost_sale_penalty (Decimal | Range): Penalty per unit lost.
        demand_persistence (Decimal | None, optional): Share of the previous base
            demand carried into the next period; only with a range of demand.

    Examples:
        >>> terms = {"price": "90", "transport_cost": "2", "demand": 20}
        >>> terms |= {"lead_time": 2, "patience": 2}
        >>> terms |= {"late_penalty": "5", "lost_sale_penalty": "30"}
        >>> CustomerProduct.model_validate(terms).demand
        Decimal('20.000')
    """

    model_config = ConfigDict(
        json_schema_extra=optional_group_keys(CustomerProductDefaults)
    )
    price: MoneyParameter
    transport_cost: MoneyParameter
    demand: QuantityParameter
    lead_time: PeriodsParameter
    patience: PeriodsParameter
    late_penalty: MoneyParameter
    lost_sale_penalty: MoneyParameter
    demand_persistence: ShareFrom0To1 | None = None


class Customer(StrictModel):
    """A customer of products.

    Attributes:
        name (str | None, optional): A readable name.
        description (str | None, optional): A readable description.
        products (Mapping[str, CustomerProduct]): The terms of each product bought.
        payment_terms (int | Range, optional): Periods from a shipment to its
            payment; 0 pays at once.
        groups (tuple[str, ...], optional): The groups it is in, in the order their
            defaults apply.

    Examples:
        >>> Customer.model_validate({"products": {}}).payment_terms
        0
    """

    model_config = ConfigDict(json_schema_extra=optional_group_keys(CustomerDefaults))
    name: str | None = None
    description: str | None = None
    products: ReadOnlyMapping[Identifier, CustomerProduct]
    payment_terms: PeriodsParameter = 0
    groups: ReadOnlyList[Identifier] = ()


class LineItem(StrictModel):
    """How a line makes one item.

    Attributes:
        time (Decimal | Range): Hours per unit started.
        cost (Decimal | Range): Cost per unit started.
        yield_ (Decimal | Range): Share of started units that come out good, written
            `yield` in JSON.
        lead_time (int | Range, optional): Periods from the start of production to
            the close at which it enters stock, counting the start period.
        changeover_time (Decimal | Range | None, optional): Regular hours to set the
            line for this item.
        changeover_cost (Decimal | Range | None, optional): Cost to set the line for
            this item.

    Examples:
        >>> body = {"time": "0.5", "cost": "3", "yield": "0.95"}
        >>> LineItem.model_validate(body).lead_time
        1
    """

    model_config = ConfigDict(json_schema_extra=optional_group_keys(LineItemDefaults))
    time: PositiveQuantityParameter
    cost: MoneyParameter
    yield_: ShareParameter = Field(alias="yield")
    lead_time: PositivePeriodsParameter = 1
    changeover_time: QuantityParameter | None = None
    changeover_cost: MoneyParameter | None = None


class Line(StrictModel):
    """A production line.

    Attributes:
        name (str | None, optional): A readable name.
        description (str | None, optional): A readable description.
        capacity (Decimal | Range): Production hours per period at condition 1.
        wear_per_period (Decimal | Range): Share of condition lost every period.
        wear_per_hour (Decimal | Range): Condition lost per production hour.
        breakdown_chance (Decimal | Range): Chance of a breakdown in a period.
        breakdown_loss (Decimal | Range): Share of condition lost in a breakdown.
        repair_cost (Decimal | Range): Cost of restoring a condition of 1.
        repair_time (Decimal | Range): Hours used to restore a condition of 1, above
            0.
        repair_limit (Decimal | Range): Largest condition restored in one period.
        items (Mapping[str, LineItem]): How the line makes each item.
        overtime_hours (Decimal | Range, optional): Extra production hours per
            period at condition 1.
        overtime_cost (Decimal | Range | None, optional): Cost of one overtime hour;
            given exactly when `overtime_hours` can be above 0.
        warehouse (str | None, optional): The warehouse of the line's inputs and
            output; required when the manifest has several warehouses.
        groups (tuple[str, ...], optional): The groups it is in, in the order their
            defaults apply.

    Examples:
        >>> hours = {"capacity": 40, "repair_time": 8, "repair_limit": "0.5"}
        >>> wear = {"wear_per_period": "0.01", "wear_per_hour": "0.001"}
        >>> breakdowns = {"breakdown_chance": "0.05", "breakdown_loss": "0.2"}
        >>> body = {**hours, **wear, **breakdowns, "repair_cost": 100, "items": {}}
        >>> Line.model_validate(body).overtime_hours
        Decimal('0.000')
    """

    model_config = ConfigDict(json_schema_extra=optional_group_keys(LineDefaults))
    name: str | None = None
    description: str | None = None
    capacity: PositiveQuantityParameter
    wear_per_period: ShareParameter
    wear_per_hour: RateParameter
    breakdown_chance: ShareParameter
    breakdown_loss: ShareParameter
    repair_cost: MoneyParameter
    repair_time: PositiveQuantityParameter
    repair_limit: PositiveShareParameter
    items: ReadOnlyMapping[Identifier, LineItem]
    overtime_hours: QuantityParameter = Decimal("0.000")
    overtime_cost: MoneyParameter | None = None
    warehouse: Identifier | None = None
    groups: ReadOnlyList[Identifier] = ()


class AcceptedGroup(StrictModel):
    """A group of items a warehouse accepts.

    Attributes:
        group (str): The identifier of the group.

    Examples:
        >>> AcceptedGroup(group="cold").group
        'cold'
    """

    group: str


class Warehouse(StrictModel):
    """A warehouse.

    Attributes:
        name (str | None, optional): A readable name.
        description (str | None, optional): A readable description.
        capacity (Decimal): Space the warehouse has.
        storage_factor (Decimal, optional): Factor on the storage cost here.
        transport_factor (Decimal, optional): Factor on the transport cost of
            shipments from here.
        accepts (tuple[str | AcceptedGroup, ...], optional): The kinds of item it
            holds, `materials`, `components` or `products`, and groups of items.

    Examples:
        >>> Warehouse.model_validate({"capacity": 500}).accepts
        ('materials', 'components', 'products')
    """

    name: str | None = None
    description: str | None = None
    capacity: QuantityAbove0
    storage_factor: FactorAbove0 = Decimal("1.0000")
    transport_factor: FactorAbove0 = Decimal("1.0000")
    accepts: ReadOnlyList[str | AcceptedGroup] = ("materials", "components", "products")


class Route(StrictModel):
    """A one-way route between two warehouses.

    Attributes:
        cost (Decimal | Range): Cost per unit transferred.
        lead_time (int | Range): Periods a transfer takes; 0 arrives at once.

    Examples:
        >>> Route.model_validate({"cost": "0.5", "lead_time": 1}).cost
        Decimal('0.5000')
    """

    cost: MoneyParameter
    lead_time: PeriodsParameter


class GroupDefaults(StrictModel):
    """The parameters a group gives its members, by the key of their type.

    Attributes:
        items (ItemDefaults | None, optional): For materials, components and products.
        catalogue (CatalogueDefaults | None, optional): For materials and suppliers.
        line_items (LineItemDefaults | None, optional): For made items and lines.
        customer_products (CustomerProductDefaults | None, optional): For products
            and customers.
        customers (CustomerDefaults | None, optional): For customers.
        lines (LineDefaults | None, optional): For lines.

    Examples:
        >>> body = {"customers": {"payment_terms": 4}}
        >>> GroupDefaults.model_validate(body).customers.payment_terms
        4
    """

    items: ItemDefaults | None = None
    catalogue: CatalogueDefaults | None = None
    line_items: LineItemDefaults | None = None
    customer_products: CustomerProductDefaults | None = None
    customers: CustomerDefaults | None = None
    lines: LineDefaults | None = None


class Group(StrictModel):
    """A group of objects of one type that may give them defaults.

    Attributes:
        kind (str): A word such as `region` or `segment`; an object is in at most one
            group of each kind.
        defaults (GroupDefaults | None, optional): The parameters it gives its
            members.

    Examples:
        >>> Group.model_validate({"kind": "region"}).kind
        'region'
    """

    kind: Identifier
    defaults: GroupDefaults | None = None


class Cash(StrictModel):
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
        >>> Cash(
        ...     credit_limit="1000",
        ...     credit_interest="0.0005",
        ...     debit_interest="0.0040",
        ...     overdraft_interest="0.0200",
        ... ).credit_limit
        Decimal('1000.0000')
    """

    credit_limit: MoneyAtLeast0
    credit_interest: ShareFrom0To1
    debit_interest: ShareFrom0To1
    overdraft_interest: ShareFrom0To1


class ManifestCreate(StrictModel):
    """A whole factory, as a client sends it.

    Attributes:
        name (str | None, optional): A readable name.
        description (str | None, optional): A readable description.
        period_name (str | None, optional): The name of one period, such as "week".
        materials (Mapping[str, Material]): Materials by identifier.
        components (Mapping[str, MadeItem]): Components by identifier.
        products (Mapping[str, Product]): Products by identifier.
        suppliers (Mapping[str, Supplier]): Suppliers by identifier.
        customers (Mapping[str, Customer]): Customers by identifier.
        lines (Mapping[str, Line]): Lines by identifier.
        warehouses (Mapping[str, Warehouse]): Warehouses by identifier.
        cash (Cash): The credit limit and interest rates of cash.
        routes (Mapping[str, Mapping[str, Route]], optional): Routes by the
            warehouse they leave from and the warehouse they reach.
        groups (Mapping[str, Group], optional): Groups by identifier.

    Examples:
        >>> cash = {"credit_limit": 0, "credit_interest": 0, "debit_interest": 0}
        >>> cash |= {"overdraft_interest": 0}
        >>> kinds = ["materials", "components", "products", "suppliers", "customers"]
        >>> body = {kind: {} for kind in [*kinds, "lines", "warehouses"]}
        >>> content = ManifestCreate.model_validate({**body, "cash": cash})
        >>> content.cash.credit_limit
        Decimal('0.0000')
    """

    name: str | None = None
    description: str | None = None
    period_name: str | None = None
    materials: ReadOnlyMapping[Identifier, Material]
    components: ReadOnlyMapping[Identifier, MadeItem]
    products: ReadOnlyMapping[Identifier, Product]
    suppliers: ReadOnlyMapping[Identifier, Supplier]
    customers: ReadOnlyMapping[Identifier, Customer]
    lines: ReadOnlyMapping[Identifier, Line]
    warehouses: ReadOnlyMapping[Identifier, Warehouse]
    cash: Cash
    routes: ReadOnlyMapping[Identifier, ReadOnlyMapping[Identifier, Route]] = Field(
        default_factory=dict
    )
    groups: ReadOnlyMapping[Identifier, Group] = Field(default_factory=dict)


class ManifestPublic(StrictModel):
    """A stored manifest.

    Attributes:
        id (str): The SHA-256 digest, in 64 hexadecimal digits, of its canonical
            JSON.
        content (ManifestCreate): The manifest as its author wrote it.
        linear (bool): Whether the manifest is linear: no minimum quantity, discount
            or changeover.

    Examples:
        >>> cash = {"credit_limit": 0, "credit_interest": 0, "debit_interest": 0}
        >>> cash |= {"overdraft_interest": 0}
        >>> kinds = ["materials", "components", "products", "suppliers", "customers"]
        >>> body = {kind: {} for kind in [*kinds, "lines", "warehouses"]}
        >>> content = ManifestCreate.model_validate({**body, "cash": cash})
        >>> ManifestPublic(id="a1", content=content, linear=True).linear
        True
    """

    id: str
    content: ManifestCreate
    linear: bool


class ManifestSummary(StrictModel):
    """One manifest in a list.

    Attributes:
        id (str): The identifier.
        name (str | None): Its readable name.
        description (str | None): Its readable description.

    Examples:
        >>> ManifestSummary(id="a1", name="Electronics factory", description=None).name
        'Electronics factory'
    """

    id: str
    name: str | None
    description: str | None


class ManifestCounts(StrictModel):
    """The counts of objects of a generated manifest.

    Attributes:
        materials (int): Materials, 1 to 200.
        components (int): Components, 1 to 100.
        products (int): Products, 1 to 50.
        suppliers (int): Suppliers, 1 to 50.
        customers (int): Customers, 1 to 50.
        lines (int): Lines, 1 to 20 and at most `components + products`.

    Examples:
        >>> counts = dict.fromkeys(["materials", "components", "products"], 2)
        >>> counts |= dict.fromkeys(["suppliers", "customers", "lines"], 1)
        >>> ManifestCounts.model_validate(counts).lines
        1
    """

    materials: Annotated[Count, Field(ge=1, le=200)]
    components: Annotated[Count, Field(ge=1, le=100)]
    products: Annotated[Count, Field(ge=1, le=50)]
    suppliers: Annotated[Count, Field(ge=1, le=50)]
    customers: Annotated[Count, Field(ge=1, le=50)]
    lines: Annotated[Count, Field(ge=1, le=20)]

    @field_validator("lines")
    @classmethod
    def lines_have_items(cls, lines: int, validation_info: ValidationInfo) -> int:
        """Refuse more lines than components and products to make.

        Args:
            lines (int): The count of lines.
            validation_info (ValidationInfo): The counts read before it.

        Returns:
            int: The count.

        Raises:
            ValueError: If it is above `components + products`.

        Examples:
            >>> counts = dict.fromkeys(["materials", "components", "products"], 1)
            >>> counts |= dict.fromkeys(["suppliers", "customers", "lines"], 1)
            >>> ManifestCounts.model_validate(counts).lines
            1
        """
        # A count refused before `lines` is missing here and its error comes first.
        counts = validation_info.data
        made = counts.get("components", lines) + counts.get("products", lines)
        if lines > made:
            raise ValueError("is above components + products")
        return lines


class ManifestGenerate(StrictModel):
    """A request to generate a manifest from counts of objects and a seed.

    Attributes:
        counts (ManifestCounts): The counts of objects.
        seed (int): The seed of the generator, from 0 to `2 ** 128 - 1`.
        economy (Literal["unrestricted", "matched"], optional): How the prices of
            customer products are drawn: within the prices of the example factory, or as
            the lowest cost of the product times a ratio of the example. `unrestricted`
            when not given.

    Examples:
        >>> counts = dict.fromkeys(["materials", "components", "products"], 1)
        >>> counts |= dict.fromkeys(["suppliers", "customers", "lines"], 1)
        >>> ManifestGenerate.model_validate({"counts": counts, "seed": 3}).economy
        'unrestricted'
    """

    counts: ManifestCounts
    seed: Seed
    economy: Literal["unrestricted", "matched"] = "unrestricted"


class ManifestsPublic(StrictModel):
    """Every stored manifest.

    Attributes:
        manifests (tuple[ManifestSummary, ...]): The manifests, by identifier.

    Examples:
        >>> ManifestsPublic(manifests=()).manifests
        ()
    """

    manifests: tuple[ManifestSummary, ...]


class ManifestGroups(StrictModel):
    """The groups of a manifest, read before the rest so errors name the group.

    Attributes:
        groups (Mapping[str, Group]): Groups by identifier.

    Examples:
        >>> body = {"groups": {"apac": {"kind": "region"}}}
        >>> ManifestGroups.model_validate(body).groups["apac"].kind
        'region'
    """

    groups: ReadOnlyMapping[Identifier, Group]
