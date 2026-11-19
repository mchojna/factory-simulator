"""The world of a run: every value drawn from the seed, and the description.

Examples:
    >>> Breakdown(period=4, breaks=True, loss=Decimal("0.3")).loss
    Decimal('0.3')
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from factory_simulator.engine.models.manifest import Factory, read_only_copy
from factory_simulator.engine.models.scenario import (
    DemandShape,
    Disruption,
    Forecast,
    Scenario,
    Start,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Delivery:
    """The drawn outcome of normal or express orders of one entry and placing period.

    Attributes:
        period (int): The placing period.
        punctual (bool): Whether a delivery is on time.
        delay (int): Extra periods of a late delivery.
        completeness (Decimal): Share of the open quantity that arrives.
        acceptance (Decimal): Share of the arrived quantity that passes inspection.

    Examples:
        >>> delivery = Delivery(
        ...     period=1,
        ...     punctual=False,
        ...     delay=2,
        ...     completeness=Decimal("0.9"),
        ...     acceptance=Decimal("1"),
        ... )
        >>> delivery.delay
        2
    """

    period: int
    punctual: bool
    delay: int
    completeness: Decimal
    acceptance: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Breakdown:
    """The drawn breakdown of one line in one period.

    Attributes:
        period (int): The period.
        breaks (bool): Whether the line breaks down.
        loss (Decimal): Share of condition lost when it breaks down.

    Examples:
        >>> Breakdown(period=4, breaks=False, loss=Decimal("0.3")).breaks
        False
    """

    period: int
    breaks: bool
    loss: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class World:
    """The factory, the scenario and every value drawn from the seed.

    Each tuple of a mapping holds one value per period, the first for period 1.

    Attributes:
        factory (Factory): The factory.
        scenario (Scenario): The scenario.
        parameters (Mapping[str, Decimal]): Every parameter drawn once per run or
            fixed, by its dotted path.
        drawn (frozenset[str]): The paths of the parameters drawn from a range.
        demand (Mapping[str, tuple[Decimal, ...]]): Base demand per
            `<customer>/<product>`.
        deliveries (Mapping[str, tuple[Delivery, ...]]): Delivery outcomes per
            `<supplier>/<material>` and placing period.
        yields (Mapping[str, tuple[Decimal, ...]]): Yield per `<line>/<item>`.
        breakdowns (Mapping[str, tuple[Breakdown, ...]]): Breakdowns per line.
        disruptions (tuple[Disruption, ...]): The written disruptions in scenario
            order, then the drawn ones by name, start and target.
        forecasts (Mapping[str, tuple[tuple[Decimal | None, ...], ...]]): Per
            targeted `<customer>/<product>` and period t, the forecasts made in t
            for t + 1 to t + `periods_ahead`; None past the horizon.
        forecast_errors (Mapping[str, tuple[tuple[Decimal | None, ...], ...]]): The
            error e of each of those forecasts; None past the horizon.
        prices (Mapping[str, tuple[Decimal, ...]]): Per `<supplier>/<material>`
            whose price is drawn once per period, the price of each period.
        express_deliveries (Mapping[str, tuple[Delivery, ...]]): Delivery outcomes
            of express orders per `<supplier>/<material>` with an express lead time
            and placing period.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash
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
        ...     scenario=Scenario(horizon=2),
        ...     parameters={},
        ...     drawn=frozenset(),
        ...     demand={"shop/bolt": (Decimal("10"), Decimal("12"))},
        ...     deliveries={},
        ...     yields={},
        ...     breakdowns={},
        ... )
        >>> world.disruptions
        ()
    """

    factory: Factory
    scenario: Scenario
    parameters: Mapping[str, Decimal]
    drawn: frozenset[str]
    demand: Mapping[str, tuple[Decimal, ...]]
    deliveries: Mapping[str, tuple[Delivery, ...]]
    yields: Mapping[str, tuple[Decimal, ...]]
    breakdowns: Mapping[str, tuple[Breakdown, ...]]
    disruptions: tuple[Disruption, ...] = ()
    forecasts: Mapping[str, tuple[tuple[Decimal | None, ...], ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    forecast_errors: Mapping[str, tuple[tuple[Decimal | None, ...], ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    prices: Mapping[str, tuple[Decimal, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    express_deliveries: Mapping[str, tuple[Delivery, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """Keep a read-only copy of every mapping given."""
        for name in (
            "parameters",
            "demand",
            "deliveries",
            "yields",
            "breakdowns",
            "forecasts",
            "forecast_errors",
            "prices",
            "express_deliveries",
        ):
            object.__setattr__(self, name, read_only_copy(getattr(self, name)))


@dataclass(frozen=True, slots=True, kw_only=True)
class Description:
    """The factory of a run with its drawn values.

    The HTTP interface leaves the hidden parameters out when it writes the description.

    Attributes:
        factory (Factory): The factory, every range that may not be hidden replaced
            by its drawn value.
        horizon (int): Number of periods.
        start (Start): The state before period 1.
        demand_shapes (tuple[Trend | Season | Step | Ramp | SCurve, ...]): Shapes of
            demand over time.
        forecasts (tuple[Forecast, ...]): The forecast entries.
        linear (bool): Whether the factory is linear: no minimum quantity, discount
            or changeover.

    Examples:
        >>> from factory_simulator.engine.models.manifest import Cash
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
        >>> description = Description(
        ...     factory=factory,
        ...     horizon=2,
        ...     start=Start(),
        ...     demand_shapes=(),
        ...     forecasts=(),
        ...     linear=True,
        ... )
        >>> description.horizon
        2
    """

    factory: Factory
    horizon: int
    start: Start
    demand_shapes: tuple[DemandShape, ...]
    forecasts: tuple[Forecast, ...]
    linear: bool
