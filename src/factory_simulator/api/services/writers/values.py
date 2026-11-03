"""The writer of values: the dataclasses of the engine as plain JSON values.

Examples:
    >>> plain((engine.Range(min=1, max=2),))
    [{'min': 1, 'max': 2, 'distribution': 'uniform'}]
"""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from typing import cast

from factory_simulator import engine


def plain(value: object) -> object:
    """Give dataclasses of the engine as mappings and lists for JSON.

    A field `yield_` is written `yield`; an outcome and a range leave out their
    empty fields, and a range its moment of drawing when it is drawn once per run.

    Args:
        value (object): A dataclass, a mapping, a tuple or a plain value.

    Returns:
        object: Dictionaries, lists and plain values.

    Examples:
        >>> plain(engine.Range(min=1, max=3))
        {'min': 1, 'max': 3, 'distribution': 'uniform'}
    """
    if is_dataclass(value) and not isinstance(value, type):
        members = {
            field.name.removesuffix("_"): plain(getattr(value, field.name))
            for field in fields(value)
        }
        if isinstance(value, engine.Range) and value.drawn == "run":
            del members["drawn"]
        if isinstance(value, engine.Outcome | engine.Range):
            return {key: item for key, item in members.items() if item is not None}
        return members
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return {key: plain(item) for key, item in mapping.items()}
    if isinstance(value, list | tuple):
        return [plain(item) for item in cast(list[object] | tuple[object, ...], value)]
    return value
