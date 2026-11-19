"""The measures of groups: sums and means over their members.

Examples:
    >>> groups = GroupIndex(direct=(("east", ("lines.press",)),), groups_of={})
    >>> with_groups({"lines.press": Decimal("3")}, groups)["groups.east"]
    Decimal('3')
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from types import MappingProxyType

from factory_simulator.engine.models.world import World
from factory_simulator.engine.numbers import round_to

# The keys of two parts, `<type>.<a>/<b>`, that count an object of a type, and the
# position of that object in the key.
TWO_PART_KEYS: Mapping[str, tuple[tuple[str, int], ...]] = MappingProxyType(
    {
        "suppliers": (("suppliers", 0),),
        "materials": (("suppliers", 1), ("warehouses", 1), ("lines", 1)),
        "components": (("warehouses", 1), ("lines", 1)),
        "products": (("warehouses", 1), ("lines", 1)),
        "lines": (("lines", 0),),
        "customers": (),
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class GroupIndex:
    """The groups of a world as the measures of a period read them.

    Attributes:
        direct (tuple[tuple[str, tuple[str, ...]], ...]): Each group by identifier,
            with the keys of its members, `<type>.<id>`.
        groups_of (Mapping[tuple[str, str], tuple[str, ...]]): The groups of each
            object that is a member of one, by its type and identifier.

    Examples:
        >>> groups = GroupIndex(
        ...     direct=(("east", ("lines.press",)),),
        ...     groups_of={("lines", "press"): ("east",)},
        ... )
        >>> groups.groups_of[("lines", "press")]
        ('east',)
    """

    direct: tuple[tuple[str, tuple[str, ...]], ...]
    groups_of: Mapping[tuple[str, str], tuple[str, ...]]


def index_groups(world: World) -> GroupIndex:
    """Give the groups of a world as the measures of a period read them.

    Args:
        world (World): The world.

    Returns:
        GroupIndex: The keys of the members of each group and the groups of each
            member.

    Examples:
        >>> from factory_simulator.engine import (
        ...     Cash,
        ...     Factory,
        ...     Group,
        ...     Scenario,
        ...     draw_world,
        ... )
        >>> zero = Decimal(0)
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ...     groups={
        ...         "west": Group(kind="region", members=(), member_type="customers")
        ...     },
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), 0)
        >>> index_groups(world).direct
        (('west', ()),)
    """
    groups_of: dict[tuple[str, str], tuple[str, ...]] = {}
    direct: list[tuple[str, tuple[str, ...]]] = []
    for group_id, group in sorted(world.factory.groups.items()):
        members = sorted(group.members)
        direct.append(
            (group_id, tuple(f"{group.member_type}.{member}" for member in members))
        )
        for member in members:
            member_key = (group.member_type, member)
            groups_of[member_key] = (*groups_of.get(member_key, ()), group_id)
    return GroupIndex(direct=tuple(direct), groups_of=MappingProxyType(groups_of))


def with_groups(values: dict[str, Decimal], groups: GroupIndex) -> dict[str, Decimal]:
    """Give the values with the sum of every group of objects a measure is kept for.

    A group sums the keys of its members, `<type>.<id>`, when the measure has them;
    otherwise the keys of two parts in which a member stands, summed over the other
    part.

    Args:
        values (dict[str, Decimal]): Values of one measure by key.
        groups (GroupIndex): The groups of the world, from `index_groups`.

    Returns:
        dict[str, Decimal]: The values with a key `groups.<id>` per group counted.

    Examples:
        >>> groups = GroupIndex(
        ...     direct=(("east", ("lines.press",)),),
        ...     groups_of={("lines", "press"): ("east",)},
        ... )
        >>> with_groups({"lines.press": Decimal("3")}, groups)
        {'lines.press': Decimal('3'), 'groups.east': Decimal('3')}
    """
    if not groups.direct:
        return values
    in_parts = values_in_parts(values, groups)
    added: dict[str, Decimal] = {}
    for group_id, keys in groups.direct:
        found = [values[key] for key in keys if key in values]
        if not found:
            found = in_parts.get(group_id, [])
        if found:
            added[f"groups.{group_id}"] = sum(found, Decimal(0))
    return values | added


def values_in_parts(
    values: dict[str, Decimal], groups: GroupIndex
) -> dict[str, list[Decimal]]:
    """Give, per group, the values of the keys of two parts in which a member stands.

    Args:
        values (dict[str, Decimal]): Values of one measure by key.
        groups (GroupIndex): The groups of the world, from `index_groups`.

    Returns:
        dict[str, list[Decimal]]: The values by group, in the order of the keys.

    Examples:
        >>> groups = GroupIndex(
        ...     direct=(("east", ("lines.press",)),),
        ...     groups_of={("lines", "press"): ("east",)},
        ... )
        >>> values_in_parts({"lines.press/bolt": Decimal("4")}, groups)
        {'east': [Decimal('4')]}
    """
    found: dict[str, list[Decimal]] = {}
    for key, value in values.items():
        counted: set[str] = set()
        for member_key in objects_of_key(key):
            counted.update(groups.groups_of.get(member_key, ()))
        for group_id in counted:
            found.setdefault(group_id, []).append(value)
    return found


@cache
def objects_of_key(key: str) -> tuple[tuple[str, str], ...]:
    """Give the objects a key of two parts counts, by their type and identifier.

    Args:
        key (str): The key, such as `lines.line-1/board`.

    Returns:
        tuple[tuple[str, str], ...]: The type and identifier of each object; none for
            a key of one part.

    Examples:
        >>> objects_of_key("lines.line-1/board")[2:]
        (('products', 'board'), ('lines', 'line-1'))
    """
    family, _, rest = key.partition(".")
    parts = rest.split("/")
    if len(parts) != 2:
        return ()
    return tuple(
        (member_type, parts[position])
        for member_type, places in TWO_PART_KEYS.items()
        for named, position in places
        if family == named
    )


def group_levels(
    name: str, values: Mapping[str, Decimal | None], groups: GroupIndex, world: World
) -> Mapping[str, Decimal | None]:
    """Give a level with its groups: the mean `condition`, every other level summed.

    Args:
        name (str): The name of the level.
        values (Mapping[str, Decimal | None]): Its values by key.
        groups (GroupIndex): The groups of the world, from `index_groups`.
        world (World): The world.

    Returns:
        Mapping[str, Decimal | None]: The values with a key `groups.<id>` per group
            counted.

    Examples:
        >>> from factory_simulator.engine import Cash, Factory, Scenario, draw_world
        >>> zero = Decimal(0)
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=Cash(
        ...         credit_limit=zero,
        ...         credit_interest=zero,
        ...         debit_interest=zero,
        ...         overdraft_interest=zero,
        ...     ),
        ... )
        >>> world = draw_world(factory, Scenario(horizon=1), 0)
        >>> groups = GroupIndex(direct=(("east", ("warehouses.main",)),), groups_of={})
        >>> group_levels("stock", {"warehouses.main": Decimal("7")}, groups, world)
        {'warehouses.main': Decimal('7'), 'groups.east': Decimal('7')}
    """
    known = {key: value for key, value in values.items() if value is not None}
    if name != "condition":
        return dict(values) | with_groups(known, groups)
    means: dict[str, Decimal | None] = dict(values)
    for group_id, group in sorted(world.factory.groups.items()):
        if group.member_type == "lines":
            conditions = [known[f"lines.{line_id}"] for line_id in group.members]
            mean = sum(conditions, Decimal(0)) / len(conditions)
            means[f"groups.{group_id}"] = round_to(mean, 12)
    return means
