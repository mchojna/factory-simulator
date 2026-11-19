"""The parameters of a factory: paths, those drawn per period or hidden, and bounds.

Examples:
    >>> join("lines.press", "capacity")
    'lines.press.capacity'
"""

from collections.abc import Iterator, Mapping
from dataclasses import fields, is_dataclass
from decimal import Decimal
from typing import cast

from factory_simulator.engine.models.manifest import DiscountTier, Range

# The parameter groups a scenario may keep from the agent.
HIDDEN_GROUPS = (
    "customers.products.demand",
    "suppliers.catalogue.punctuality",
    "suppliers.catalogue.delay",
    "suppliers.catalogue.completeness",
    "suppliers.catalogue.acceptance",
    "lines.items.yield",
    "lines.breakdown_chance",
    "lines.breakdown_loss",
    "disruptions.duration",
)

# The parameters whose range a scenario may hide, by the last part of their path; the
# description shows their range.
HIDEABLE = frozenset(
    group.rsplit(".", 1)[1]
    for group in HIDDEN_GROUPS
    if not group.startswith("disruptions.")
)

# The parameters drawn once per period, from the stream of their supplier and material,
# customer and product, line and item, or line.
DRAWN_PER_PERIOD = frozenset(
    {"demand", "yield", "delay", "completeness", "acceptance", "breakdown_loss"}
)

# The keys of the manifest that give an amount of money per unit, hour or condition;
# `credit_limit` is money but no amount per unit.
MONEY_KEYS = frozenset(
    {
        "price",
        "transport_cost",
        "late_penalty",
        "lost_sale_penalty",
        "storage_cost",
        "salvage_value",
        "express_cost",
        "cancellation_fee",
        "cost",
        "repair_cost",
        "overtime_cost",
        "changeover_cost",
    }
)


def walk_parameters(value: object, path: str) -> Iterator[tuple[str, object]]:
    """Walk the parameters of a factory: every leaf with its dotted path.

    Dataclass fields come in declaration order, mapping keys sorted. A discount tier
    is named by its `from` with 3 places, not by its position.

    Args:
        value (object): A dataclass, a mapping or a leaf value.
        path (str): The dotted path of the value.

    Yields:
        tuple[str, object]: The path and the value of each leaf: a number, a range,
            text or None.

    Examples:
        >>> list(walk_parameters({"b": Decimal(2), "a": Decimal(1)}, "cash"))
        [('cash.a', Decimal('1')), ('cash.b', Decimal('2'))]
    """
    if is_dataclass(value) and not isinstance(value, Range):
        for field in fields(value):
            name = field.name.removesuffix("_")
            yield from walk_parameters(getattr(value, field.name), join(path, name))
    elif isinstance(value, tuple) and path.endswith(".discounts"):
        for tier in cast(tuple[DiscountTier, ...], value):
            tier_path = join(join(path, str(tier.from_)), "price")
            yield from walk_parameters(tier.price, tier_path)
    elif isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        for key in sorted(mapping):
            yield from walk_parameters(mapping[key], join(path, key))
    else:
        yield path, value


def join(path: str, key: str) -> str:
    """Join a key to a dotted path.

    Args:
        path (str): The dotted path, empty for the top.
        key (str): The key to add.

    Returns:
        str: The longer path.

    Examples:
        >>> join("lines.line-1", "capacity")
        'lines.line-1.capacity'
    """
    return f"{path}.{key}" if path else key


def smallest(value: Decimal | int | Range[Decimal] | Range[int]) -> Decimal:
    """Give the smallest value a parameter allows.

    Args:
        value (Decimal | int | Range[Decimal] | Range[int]): A fixed number or a
            range.

    Returns:
        Decimal: The number, or the `min` of the range.

    Examples:
        >>> smallest(Range(min=Decimal("1.5"), max=Decimal("2")))
        Decimal('1.5')
    """
    return Decimal(value.min if isinstance(value, Range) else value)


def largest(value: Decimal | int | Range[Decimal] | Range[int]) -> Decimal:
    """Give the largest value a parameter allows.

    Args:
        value (Decimal | int | Range[Decimal] | Range[int]): A fixed number or a
            range.

    Returns:
        Decimal: The number, or the `max` of the range.

    Examples:
        >>> largest(Range(min=Decimal("1.5"), max=Decimal("2")))
        Decimal('2')
    """
    return Decimal(value.max if isinstance(value, Range) else value)
