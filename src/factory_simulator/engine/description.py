"""The description of a run: the factory of the run with its drawn values.

Examples:
    >>> from factory_simulator.engine import Cash, Scenario, draw_world
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
    >>> build_description(draw_world(factory, Scenario(horizon=4), seed=0)).horizon
    4
"""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from decimal import Decimal
from types import MappingProxyType
from typing import cast

from factory_simulator.engine.checks.linear import is_linear
from factory_simulator.engine.models.manifest import DiscountTier, Factory, Range
from factory_simulator.engine.models.world import Description, World
from factory_simulator.engine.numbers import in_decimal_context
from factory_simulator.engine.rules.parameters import HIDEABLE, join


@in_decimal_context
def build_description(world: World) -> Description:
    """Build the factory of a run with its drawn values.

    It holds the factory with the drawn value of every range that may not be hidden
    and is drawn once per run, the horizon, start, demand shapes and forecasts of the
    scenario, and whether the factory is linear.

    Args:
        world (World): The world.

    Returns:
        Description: The description of the run.

    Examples:
        >>> from factory_simulator.engine import Cash, Line, Scenario
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> press = Line(
        ...     capacity=Range(min=Decimal(30), max=Decimal(50)),
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
        >>> build_description(world).factory.lines["press"].capacity
        Decimal('40')
    """
    return Description(
        factory=cast(Factory, resolve_ranges(world.factory, "", world)),
        horizon=world.scenario.horizon,
        start=world.scenario.start,
        demand_shapes=world.scenario.demand_shapes,
        forecasts=world.scenario.forecasts,
        linear=is_linear(world.factory),
    )


def resolve_ranges(value: object, path: str, world: World) -> object:
    """Resolve ranges: replace every range that may not be hidden by its drawn value.

    A price drawn once per period keeps its range.

    Args:
        value (object): A dataclass, a mapping, the discount tiers of an entry or a
            leaf of the factory.
        path (str): The dotted path of the value.
        world (World): The world, which holds the drawn values.

    Returns:
        object: The value with its ranges resolved.

    Examples:
        >>> from factory_simulator.engine import Cash, Scenario
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
        >>> resolve_ranges(
        ...     Range(min=Decimal(30), max=Decimal(50)), "lines.press.capacity", world
        ... )
        Decimal('40')
    """
    if isinstance(value, Range):
        written = cast(Range[Decimal] | Range[int], value)
        if path.rsplit(".", 1)[-1] in HIDEABLE or written.drawn == "period":
            return written
        drawn = world.parameters[path]
        return int(drawn) if isinstance(written.min, int) else drawn
    if isinstance(value, tuple):
        if not path.endswith(".discounts"):
            return cast(tuple[object, ...], value)
        return tuple(
            replace(
                tier,
                price=resolve_ranges(
                    tier.price, join(join(path, str(tier.from_)), "price"), world
                ),
            )
            for tier in cast(tuple[DiscountTier, ...], value)
        )
    if is_dataclass(value) and not isinstance(value, type):
        return replace(
            value,
            **{
                field.name: resolve_ranges(
                    getattr(value, field.name),
                    join(path, field.name.removesuffix("_")),
                    world,
                )
                for field in fields(value)
            },
        )
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return MappingProxyType(
            {
                key: resolve_ranges(item, join(path, key), world)
                for key, item in mapping.items()
            }
        )
    return value
