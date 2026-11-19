"""The checks of the groups of a factory: their names, members and defaults.

Examples:
    >>> from decimal import Decimal
    >>> from factory_simulator.engine.models.manifest import Cash
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
    >>> member_types(factory)
    {}
"""

from collections.abc import Mapping

from factory_simulator.engine.models.manifest import ITEM_KINDS, Factory
from factory_simulator.engine.numbers import InputError

# The words that name something else where a group may be named.
RESERVED = frozenset(
    {"materials", "components", "products", "all", "written", "default"}
)

# The kinds a group may not take: the parts of a customer product.
FORBIDDEN_KINDS = frozenset({"customer", "product"})

# The defaults keys each type of member uses.
DEFAULTS_KEYS: Mapping[str, tuple[str, ...]] = {
    "materials": ("items", "catalogue"),
    "components": ("items", "line_items"),
    "products": ("items", "line_items", "customer_products"),
    "suppliers": ("catalogue",),
    "customers": ("customers", "customer_products"),
    "lines": ("lines", "line_items"),
}


def check_group_names(factory: Factory) -> None:
    """Refuse a factory in which a group takes a reserved word or a reserved kind.

    Args:
        factory (Factory): The factory.

    Raises:
        InputError: If a group is named by a reserved word or its kind is customer
            or product, at the first one.

    Examples:
        >>> from decimal import Decimal
        >>> from factory_simulator.engine.models.manifest import Cash, Group
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> spare = Group(kind="region", members=(), member_type="")
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ...     groups={"all": spare},
        ... )
        >>> check_group_names(factory)
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError: groups.all: is a reserved word
    """
    for group_id, group in factory.groups.items():
        if group_id in RESERVED:
            raise InputError(f"groups.{group_id}: is a reserved word")
        if group.kind in FORBIDDEN_KINDS:
            raise InputError(f"groups.{group_id}.kind: may not be {group.kind}")


def member_types(factory: Factory) -> dict[str, str]:
    """Give the type of the members of every listed group.

    Args:
        factory (Factory): The factory.

    Returns:
        dict[str, str]: The type of each listed group, from its first member.

    Raises:
        InputError: If a listed group does not exist, at the first one.

    Examples:
        >>> from decimal import Decimal
        >>> from factory_simulator.engine.models.manifest import Cash, Group, Material
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> chip = Material(
        ...     space=zero, storage_cost=zero, salvage_value=zero, groups=("asian",)
        ... )
        >>> asian = Group(kind="region", members=("chip",), member_type="materials")
        >>> factory = Factory(
        ...     materials={"chip": chip},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ...     groups={"asian": asian},
        ... )
        >>> member_types(factory)
        {'asian': 'materials'}
    """
    types: dict[str, str] = {}
    for member_type in DEFAULTS_KEYS:
        for object_id, member in getattr(factory, member_type).items():
            for position, group_id in enumerate(member.groups):
                if group_id not in factory.groups:
                    raise InputError(
                        f"{member_type}.{object_id}.groups.{position}: names no group"
                    )
                types.setdefault(group_id, member_type)
    return types


def check_accepted_groups(types: Mapping[str, str], factory: Factory) -> None:
    """Refuse a factory whose warehouse accepts a group that holds no items.

    Args:
        types (Mapping[str, str]): The type of the members of each listed group.
        factory (Factory): The factory.

    Raises:
        InputError: If an accepted group does not exist or holds no items, at the
            first one by its position in the written `accepts`.
        ValueError: If a warehouse gives fewer or more positions than accepted
            groups.

    Examples:
        >>> from decimal import Decimal
        >>> from factory_simulator.engine.models.manifest import Cash, Warehouse
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> shelf = Warehouse(capacity=zero, accepts=(), accepted_groups=("west",))
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={"shelf": shelf},
        ...     cash=cash,
        ... )
        >>> types = {"west": "lines"}
        >>> check_accepted_groups(types, factory)  # doctest: +NORMALIZE_WHITESPACE
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError:
        warehouses.shelf.accepts.0.group: names no group of items
    """
    for warehouse_id, warehouse in factory.warehouses.items():
        after_kinds = len(warehouse.accepts)
        positions = warehouse.accepted_group_positions or range(
            after_kinds, after_kinds + len(warehouse.accepted_groups)
        )
        for position, group_id in zip(
            positions, warehouse.accepted_groups, strict=True
        ):
            if types.get(group_id) not in ITEM_KINDS:
                raise InputError(
                    f"warehouses.{warehouse_id}.accepts.{position}.group: "
                    "names no group of items"
                )


def check_group_members(types: Mapping[str, str], factory: Factory) -> None:
    """Refuse a factory in which a group and its members do not match.

    An object is in one group of a kind, a group has members of one type, and a group
    has members and gives defaults only under the keys its members use.

    Args:
        types (Mapping[str, str]): The type of each listed group, from its first
            member.
        factory (Factory): The factory.

    Raises:
        InputError: If an object is in a second group of a kind, a group has members
            of two types or no members, or its members do not use a key of its
            defaults, at the first such group or key.

    Examples:
        >>> from decimal import Decimal
        >>> from factory_simulator.engine.models.manifest import Cash, Group
        >>> zero = Decimal(0)
        >>> cash = Cash(
        ...     credit_limit=zero,
        ...     credit_interest=zero,
        ...     debit_interest=zero,
        ...     overdraft_interest=zero,
        ... )
        >>> spare = Group(kind="region", members=(), member_type="")
        >>> factory = Factory(
        ...     materials={},
        ...     components={},
        ...     products={},
        ...     suppliers={},
        ...     customers={},
        ...     lines={},
        ...     warehouses={},
        ...     cash=cash,
        ...     groups={"spare": spare},
        ... )
        >>> check_group_members({}, factory)
        Traceback (most recent call last):
        ...
        factory_simulator.engine.numbers.InputError: groups.spare: has no members
    """
    for member_type in DEFAULTS_KEYS:
        for object_id, member in getattr(factory, member_type).items():
            kinds: set[str] = set()
            for position, group_id in enumerate(member.groups):
                kind = factory.groups[group_id].kind
                if kind in kinds:
                    raise InputError(
                        f"{member_type}.{object_id}.groups.{position}: "
                        f"a second group of kind {kind}"
                    )
                kinds.add(kind)
                if types[group_id] != member_type:
                    raise InputError(f"groups.{group_id}: has members of two types")
    for group_id, group in factory.groups.items():
        if group_id not in types:
            raise InputError(f"groups.{group_id}: has no members")
        for key in group.defaults_keys:
            if key not in DEFAULTS_KEYS[types[group_id]]:
                raise InputError(
                    f"groups.{group_id}.defaults.{key}: "
                    f"is not used by {types[group_id]}"
                )
