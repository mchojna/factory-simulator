"""The writer of a description: the description of a run as JSON, hidden parameters out.

Examples:
    >>> objects_at({"lines": {"smt": {"capacity": 2}}}, ("lines", "*"))
    [{'capacity': 2}]
"""

from collections.abc import Mapping
from dataclasses import fields
from decimal import Decimal
from typing import Any, cast

from factory_simulator import engine
from factory_simulator.api.services.writers.values import plain

# The kind of each demand shape as a scenario writes it.
SHAPE_KINDS: Mapping[type[engine.DemandShape], str] = {
    engine.Trend: "trend",
    engine.Season: "season",
    engine.Step: "step",
    engine.Ramp: "ramp",
    engine.SCurve: "s_curve",
}

# The objects of a manifest that may list groups.
MEMBER_TYPES = (
    "materials",
    "components",
    "products",
    "suppliers",
    "customers",
    "lines",
)

# Where each hidden group sits: for each place, the path of its objects, the keys it
# removes there, and the key of the defaults of groups that holds them.
HIDDEN_PLACES: Mapping[
    str, tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...]
] = {
    "customers.products.demand": (
        (
            ("customers", "*", "products", "*"),
            ("demand", "demand_persistence"),
            "customer_products",
        ),
        (("products", "*"), ("common_share",), "items"),
    ),
    "suppliers.catalogue.punctuality": (
        (("suppliers", "*", "catalogue", "*"), ("punctuality",), "catalogue"),
    ),
    "suppliers.catalogue.delay": (
        (("suppliers", "*", "catalogue", "*"), ("delay",), "catalogue"),
    ),
    "suppliers.catalogue.completeness": (
        (("suppliers", "*", "catalogue", "*"), ("completeness",), "catalogue"),
    ),
    "suppliers.catalogue.acceptance": (
        (("suppliers", "*", "catalogue", "*"), ("acceptance",), "catalogue"),
    ),
    "lines.items.yield": ((("lines", "*", "items", "*"), ("yield",), "line_items"),),
    "lines.breakdown_chance": ((("lines", "*"), ("breakdown_chance",), "lines"),),
    "lines.breakdown_loss": ((("lines", "*"), ("breakdown_loss",), "lines"),),
}


def description_json(
    description: engine.Description,
    written_groups: object,
    written_random: object,
    hidden: tuple[str, ...],
) -> dict[str, object]:
    """Write the description of a run.

    The manifest shows every member with its resolved values, and its groups and
    the groups a warehouse accepts as the manifest writes them; a product shows
    `common_share` only when the manifest gives it.

    Args:
        description (Description): The description.
        written_groups (object): The groups as the manifest writes them; None for
            none.
        written_random (object): The rules of random disruptions as the scenario
            writes them, never the drawn disruptions; None for none.
        hidden (tuple[str, ...]): The parameter groups kept from the agent, left out
            wherever they appear.

    Returns:
        dict[str, object]: `{"manifest", "scenario", "linear"}`.

    Examples:
        >>> from factory_simulator.api.core.numbers import read_json_bytes, validate
        >>> from factory_simulator.api.schemas.scenario import ScenarioCreate
        >>> from factory_simulator.api.services.examples import EXAMPLES
        >>> from factory_simulator.api.services.readers.manifest import read_factory
        >>> from factory_simulator.api.services.readers.scenario import to_scenario
        >>> content = read_json_bytes((EXAMPLES / "manifest.json").read_bytes())
        >>> factory = read_factory(content)
        >>> scenario = to_scenario(validate(ScenarioCreate, {"horizon": 3}))
        >>> world = engine.draw_world(factory, scenario, 1)
        >>> described = description_json(engine.build_description(world), {}, [], ())
        >>> described["scenario"]["horizon"], described["linear"]
        (3, False)
    """
    manifest = cast(dict[str, object], plain(description.factory))
    del manifest["origins"]
    manifest["groups"] = written_groups or {}
    for product in cast(dict[str, dict[str, object]], manifest["products"]).values():
        if product["common_share"] is None:
            del product["common_share"]
    for member_type in MEMBER_TYPES:
        for member in cast(
            dict[str, dict[str, object]], manifest[member_type]
        ).values():
            if not member["groups"]:
                del member["groups"]
    for warehouse in cast(
        dict[str, dict[str, object]], manifest["warehouses"]
    ).values():
        accepted = cast(list[str], warehouse.pop("accepted_groups"))
        del warehouse["accepted_group_positions"]
        kinds = cast(list[object], warehouse["accepts"])
        warehouse["accepts"] = kinds + [{"group": group_id} for group_id in accepted]
    random = cast(list[dict[str, object]], written_random or [])
    if "disruptions.duration" in hidden:
        random = [
            {key: value for key, value in rule.items() if key != "duration"}
            for rule in random
        ]
    described: dict[str, object] = {
        "manifest": hide(manifest, hidden),
        "scenario": {
            "horizon": description.horizon,
            "start": plain(description.start),
            "demand_shapes": [
                demand_shape_json(shape) for shape in description.demand_shapes
            ],
            "forecasts": [forecast_json(entry) for entry in description.forecasts],
            "random_disruptions": random,
            "hidden": list(hidden),
        },
        "linear": description.linear,
    }
    add_cut_means(described)
    return described


def add_cut_means(document: object) -> None:
    """Add to every range of a described document the mean of its cut distribution.

    A range is a mapping whose `min` and `max` are numbers; its `cut_mean` is the
    value of `range_mean` for it with every number read as a decimal. A whole number
    of a stored manifest or scenario reads back as an int, such as `60` for `60.000`,
    and counts as that decimal.

    Args:
        document (object): A mapping, a list or a plain value, changed in place.

    Examples:
        >>> from decimal import Decimal
        >>> document = {"demand": {"min": Decimal(2), "max": Decimal(6)}}
        >>> add_cut_means(document)
        >>> document["demand"]["cut_mean"]
        Decimal('4.000000')
        >>> capacity = {"min": 60, "max": 90, "distribution": "triangular", "mode": 80}
        >>> add_cut_means(capacity)
        >>> capacity["cut_mean"]
        Decimal('76.666667')
    """
    if isinstance(document, list):
        for item in cast(list[object], document):
            add_cut_means(item)
    if not isinstance(document, dict):
        return
    members = cast(dict[str, object], document)
    if is_number(members.get("min")) and is_number(members.get("max")):
        keys = {field.name for field in fields(engine.Range)}
        written = {
            key: Decimal(cast(Decimal | int, value)) if is_number(value) else value
            for key, value in members.items()
            if key in keys
        }
        members["cut_mean"] = engine.range_mean(
            engine.Range(**cast(dict[str, Any], written))
        )
        return
    for item in members.values():
        add_cut_means(item)


def is_number(value: object) -> bool:
    """Tell whether a value of a described document is a number.

    Args:
        value (object): The value.

    Returns:
        bool: True for a `Decimal` or a whole number other than `bool`.

    Examples:
        >>> is_number(2), is_number(True), is_number("2")
        (True, False, False)
    """
    return isinstance(value, Decimal | int) and not isinstance(value, bool)


def hide(manifest: dict[str, object], hidden: tuple[str, ...]) -> dict[str, object]:
    """Leave the hidden parameters out of a described manifest.

    A hidden parameter leaves every object that has it and the defaults of every
    group; a mapping of defaults the removal leaves empty is left out.

    Args:
        manifest (dict[str, object]): The manifest of a description, changed in place.
        hidden (tuple[str, ...]): The hidden parameter groups.

    Returns:
        dict[str, object]: The manifest.

    Examples:
        >>> line = {"breakdown_chance": 1, "capacity": 2}
        >>> manifest = {"lines": {"smt": line}, "groups": {}}
        >>> hide(manifest, ("lines.breakdown_chance",))["lines"]
        {'smt': {'capacity': 2}}
    """
    for group in hidden:
        for path, keys, defaults_key in HIDDEN_PLACES.get(group, ()):
            for target in objects_at(manifest, path):
                for key in keys:
                    target.pop(key, None)
            hide_defaults(manifest, keys, defaults_key)
    return manifest


def hide_defaults(
    manifest: dict[str, object], keys: tuple[str, ...], defaults_key: str
) -> None:
    """Hide the hidden keys of the defaults of every group of a described manifest.

    A mapping of defaults the removal leaves empty is left out.

    Args:
        manifest (dict[str, object]): The manifest of a description, changed in place.
        keys (tuple[str, ...]): The keys to remove.
        defaults_key (str): The key of the defaults that holds them.

    Examples:
        >>> apac = {"kind": "region", "defaults": {"catalogue": {"punctuality": 1}}}
        >>> manifest = {"groups": {"apac": apac}}
        >>> hide_defaults(manifest, ("punctuality",), "catalogue")
        >>> manifest["groups"]["apac"]
        {'kind': 'region'}
    """
    for written in cast(dict[str, dict[str, object]], manifest["groups"]).values():
        defaults = cast(dict[str, dict[str, object]], written.get("defaults") or {})
        for key in keys:
            defaults.get(defaults_key, {}).pop(key, None)
        if defaults_key in defaults and not defaults[defaults_key]:
            del defaults[defaults_key]
        if "defaults" in written and not defaults:
            del written["defaults"]


def objects_at(
    document: dict[str, object], path: tuple[str, ...]
) -> list[dict[str, object]]:
    """Give the objects of a document at a path, `*` standing for every key.

    Args:
        document (dict[str, object]): The document.
        path (tuple[str, ...]): The keys, `*` for every key of a mapping.

    Returns:
        list[dict[str, object]]: The objects found.

    Examples:
        >>> objects_at({"lines": {"smt": {"capacity": 2}}}, ("lines", "*"))
        [{'capacity': 2}]
    """
    found = [document]
    for key in path:
        found = [
            cast(dict[str, object], child)
            for parent in found
            for child in (parent.values() if key == "*" else [parent.get(key, {})])
            if isinstance(child, dict)
        ]
    return found


def demand_shape_json(shape: engine.DemandShape) -> dict[str, object]:
    """Write a demand shape as a scenario writes it.

    Args:
        shape (DemandShape): The shape.

    Returns:
        dict[str, object]: Its `kind`, its `target`, "all" or the customer and
            product it names, and its other keys.

    Examples:
        >>> from decimal import Decimal
        >>> shape = engine.Trend(customer=None, product=None, rate=Decimal("0.1"))
        >>> demand_shape_json(shape)
        {'kind': 'trend', 'target': 'all', 'rate': Decimal('0.1')}
    """
    return {"kind": SHAPE_KINDS[type(shape)]} | targeted_json(shape)


def forecast_json(entry: engine.Forecast) -> dict[str, object]:
    """Write a forecast entry as a scenario writes it.

    Args:
        entry (Forecast): The entry.

    Returns:
        dict[str, object]: Its `target`, `periods_ahead`, `noise` and
            `noise_growth`.

    Examples:
        >>> from decimal import Decimal
        >>> entry = engine.Forecast(
        ...     customer=None,
        ...     product="monitor",
        ...     periods_ahead=2,
        ...     noise=Decimal("0.1"),
        ...     noise_growth=Decimal("0"),
        ... )
        >>> forecast_json(entry)["target"]
        {'product': 'monitor'}
    """
    return targeted_json(entry)


def targeted_json(entry: engine.DemandShape | engine.Forecast) -> dict[str, object]:
    """Write a demand shape or a forecast entry with its target as a scenario writes it.

    Args:
        entry (DemandShape | Forecast): The shape or the entry.

    Returns:
        dict[str, object]: Its `target`, "all", a group as `{kind: identifier}` or the
            customer and product it names, then its other keys.

    Examples:
        >>> from decimal import Decimal
        >>> shape = engine.Step(
        ...     customer=None, product="monitor", period=6, factor=Decimal("1.2")
        ... )
        >>> targeted_json(shape)["target"]
        {'product': 'monitor'}
    """
    members = cast(dict[str, object], plain(entry))
    customer = members.pop("customer")
    product = members.pop("product")
    del members["group"]
    target: object = "all"
    if entry.group is not None:
        kind, group_id = entry.group
        target = {kind: group_id}
    if customer is not None or product is not None:
        named = {"customer": customer, "product": product}
        target = {key: value for key, value in named.items() if value is not None}
    return {"target": target} | members
