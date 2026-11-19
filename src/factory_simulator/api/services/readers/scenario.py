"""The reader of a scenario: the scenario of the engine, its shapes and disruptions.

Examples:
    >>> to_scenario(ScenarioCreate(horizon=3)).horizon
    3
"""

from decimal import Decimal

from factory_simulator import engine
from factory_simulator.api.schemas.scenario import (
    DemandShapeCreate,
    DisruptionCreate,
    ForecastCreate,
    RampCreate,
    RandomDisruptionCreate,
    ScenarioCreate,
    SCurveCreate,
    SeasonCreate,
    ShapeTarget,
    ShapeTargetCreate,
    StepCreate,
    Target,
    TrendCreate,
)
from factory_simulator.api.services.readers.manifest import (
    to_periods_parameter,
    to_range,
)

EFFECT_KEYS = {
    "supplier_outage": "strength",
    "material_shortage": "strength",
    "quality_drop": "strength",
    "transport_delay": "delay",
    "demand_shock": "factor",
    "line_breakdown": "loss",
    "price_change": "factor",
    "capacity_cut": "strength",
    "yield_drop": "strength",
}


def to_scenario(model: ScenarioCreate) -> engine.Scenario:
    """Convert a scenario.

    The written disruptions keep the order of the list. They are numbered from 1 in the
    order of `start - notice`, the first period they are visible, then of the list.

    Args:
        model (ScenarioCreate): The validated scenario.

    Returns:
        Scenario: The scenario for the engine.

    Examples:
        >>> scenario = to_scenario(ScenarioCreate(horizon=3))
        >>> scenario.horizon, scenario.start.cash
        (3, Decimal('0.0000'))
    """
    start = model.start
    written = model.disruptions
    by_visible = sorted(
        range(len(written)),
        key=lambda position: (
            written[position].start - written[position].notice,
            position,
        ),
    )
    numbers = {position: number for number, position in enumerate(by_visible, start=1)}
    return engine.Scenario(
        horizon=model.horizon,
        start=engine.Start(
            cash=start.cash,
            stock=start.stock,
            condition=start.condition,
            customer_orders=tuple(
                engine.StartCustomerOrder(
                    customer=order.customer,
                    product=order.product,
                    quantity=order.quantity,
                    due=order.due,
                )
                for order in start.customer_orders
            ),
            supplier_orders=tuple(
                engine.StartSupplierOrder(
                    supplier=order.supplier,
                    material=order.material,
                    quantity=order.quantity,
                    arrival=order.arrival,
                    warehouse=order.warehouse,
                )
                for order in start.supplier_orders
            ),
            set_for=start.set_for,
        ),
        demand_shapes=tuple(to_demand_shape(shape) for shape in model.demand_shapes),
        forecasts=tuple(to_forecast(entry) for entry in model.forecasts),
        disruptions=tuple(
            to_disruption(disruption, numbers[position])
            for position, disruption in enumerate(model.disruptions)
        ),
        random_disruptions=tuple(
            to_random_disruption(rule) for rule in model.random_disruptions
        ),
        hidden=model.hidden,
        name=model.name,
        description=model.description,
    )


def to_demand_shape(model: DemandShapeCreate) -> engine.DemandShape:
    """Convert a demand shape.

    Args:
        model (DemandShapeCreate): The validated shape.

    Returns:
        DemandShape: The shape for the engine.

    Examples:
        >>> trend = TrendCreate(kind="trend", target="all", rate="0.01")
        >>> to_demand_shape(trend)
        Trend(customer=None, product=None, rate=Decimal('0.0100'), group=None)
    """
    customer, product, group = to_shape_target(model.target)
    match model:
        case TrendCreate():
            return engine.Trend(
                customer=customer, product=product, rate=model.rate, group=group
            )
        case SeasonCreate():
            return engine.Season(
                customer=customer,
                product=product,
                factors=tuple(model.factors),
                period_length=model.period_length,
                group=group,
            )
        case StepCreate():
            return engine.Step(
                customer=customer,
                product=product,
                period=model.period,
                factor=model.factor,
                group=group,
            )
        case RampCreate():
            return engine.Ramp(
                customer=customer,
                product=product,
                group=group,
                first=model.first,
                last=model.last,
                from_factor=model.from_factor,
                to_factor=model.to_factor,
            )
        case SCurveCreate():
            return engine.SCurve(
                customer=customer,
                product=product,
                group=group,
                middle=model.middle,
                steepness=model.steepness,
                from_factor=model.from_factor,
                to_factor=model.to_factor,
            )


def to_shape_target(
    target: ShapeTargetCreate,
) -> tuple[str | None, str | None, tuple[str, str] | None]:
    """Convert the target of a demand shape or a forecast entry.

    Args:
        target (ShapeTargetCreate): The validated target.

    Returns:
        tuple[str | None, str | None, tuple[str, str] | None]: The customer, the
            product and the group it names; None for each it does not name.

    Examples:
        >>> to_shape_target(ShapeTarget(product="monitor"))
        (None, 'monitor', None)
        >>> to_shape_target("all")
        (None, None, None)
    """
    if isinstance(target, ShapeTarget):
        return target.customer, target.product, None
    if target == "all":
        return None, None, None
    return None, None, next(iter(target.items()))


def to_disruption_target(
    target: Target,
) -> tuple[tuple[str, ...] | None, tuple[str, str] | None]:
    """Convert the target of a disruption or a rule.

    Args:
        target (Target): The validated target.

    Returns:
        tuple[tuple[str, ...] | None, tuple[str, str] | None]: The listed identifiers
            and the group it names; None for each it does not name.

    Examples:
        >>> to_disruption_target(("press",))
        (('press',), None)
        >>> to_disruption_target("all")
        (None, None)
    """
    if isinstance(target, tuple):
        return target, None
    if target == "all":
        return None, None
    return None, next(iter(target.items()))


def to_forecast(model: ForecastCreate) -> engine.Forecast:
    """Convert a forecast entry.

    Args:
        model (ForecastCreate): The validated entry.

    Returns:
        Forecast: The entry for the engine.

    Examples:
        >>> entry = ForecastCreate(
        ...     target="all", periods_ahead=3, noise="0.1", noise_growth="0.05"
        ... )
        >>> to_forecast(entry).periods_ahead
        3
    """
    customer, product, group = to_shape_target(model.target)
    return engine.Forecast(
        customer=customer,
        product=product,
        group=group,
        periods_ahead=model.periods_ahead,
        noise=model.noise,
        noise_growth=model.noise_growth,
    )


def to_disruption(model: DisruptionCreate, number: int) -> engine.Disruption:
    """Convert a written disruption.

    Args:
        model (DisruptionCreate): The validated disruption.
        number (int): Its number among the written disruptions, from 1.

    Returns:
        Disruption: The disruption for the engine.

    Examples:
        >>> from factory_simulator.api.schemas.scenario import SupplierOutageCreate
        >>> outage = SupplierOutageCreate(
        ...     kind="supplier_outage",
        ...     target=["chip-maker"],
        ...     start=3,
        ...     duration=2,
        ...     strength="0.5",
        ... )
        >>> to_disruption(outage, 1).id
        'disruption-1'
    """
    listed, group = to_disruption_target(model.target)
    return engine.Disruption(
        id=f"disruption-{number}",
        kind=model.kind,
        target=listed,
        group=group,
        start=model.start,
        duration=getattr(model, "duration", 1),
        effect=Decimal(getattr(model, EFFECT_KEYS[model.kind])),
        notice=model.notice,
    )


def to_random_disruption(
    model: RandomDisruptionCreate,
) -> engine.RandomDisruption:
    """Convert a rule of random disruptions.

    Args:
        model (RandomDisruptionCreate): The validated rule.

    Returns:
        RandomDisruption: The rule for the engine.

    Examples:
        >>> from factory_simulator.api.schemas.scenario import RandomQualityDropCreate
        >>> rule = RandomQualityDropCreate(
        ...     name="quality",
        ...     kind="quality_drop",
        ...     target="all",
        ...     chance="0.05",
        ...     duration=2,
        ...     strength="0.2",
        ... )
        >>> to_random_disruption(rule).effect
        Decimal('0.2000')
    """
    listed, group = to_disruption_target(model.target)
    effect = getattr(model, EFFECT_KEYS[model.kind])
    if isinstance(effect, int):
        drawn_effect: Decimal | int | engine.Range[Decimal] | engine.Range[int] = effect
    elif isinstance(effect, Decimal):
        drawn_effect = effect
    else:
        drawn_effect = to_range(effect)
    duration = getattr(model, "duration", None)
    return engine.RandomDisruption(
        name=model.name,
        kind=model.kind,
        target=listed,
        group=group,
        chance=model.chance,
        duration=None if duration is None else to_periods_parameter(duration),
        effect=drawn_effect,
        choose=model.choose == "one",
        notice=model.notice,
        start=model.start,
        raises=(
            None
            if model.raises is None
            else engine.Cascade(
                rule=model.raises.rule,
                factor=model.raises.factor,
                periods=model.raises.periods,
            )
        ),
    )
