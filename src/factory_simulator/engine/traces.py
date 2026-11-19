"""The trace snapshots: copies of values and the transitions of whole steps.

Examples:
    >>> snapshot({"stock": [1, 2]})["stock"]
    (1, 2)
"""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from types import MappingProxyType
from typing import cast

from factory_simulator.engine.models.state import State
from factory_simulator.engine.models.trace import Transition


def snapshot(value: object) -> object:
    """Give a read-only copy of dataclass, mapping and sequence values.

    A snapshot of a state leaves out its trace.

    Args:
        value (object): The values to capture.

    Returns:
        object: The copy, with mappings and tuples in place of the containers and the
            same scalar values.

    Examples:
        >>> snapshot([1, {"cash": 2}])[0]
        1
    """
    if is_dataclass(value) and not isinstance(value, type):
        return MappingProxyType(
            {
                member.name: snapshot(getattr(value, member.name))
                for member in fields(value)
                if not (isinstance(value, State) and member.name == "trace")
            }
        )
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return MappingProxyType({key: snapshot(item) for key, item in mapping.items()})
    if isinstance(value, list | tuple):
        return tuple(snapshot(item) for item in cast(list[object], value))
    return value


def trace_step(before: State, after: State, step: str, inputs: object = None) -> State:
    """Trace a whole step, also one that changes nothing.

    Args:
        before (State): The state before the step.
        after (State): The state after the step.
        step (str): The name of the step.
        inputs (object, optional): The input of the step, None when not given.

    Returns:
        State: The state with its new transition appended.

    Examples:
        >>> from decimal import Decimal
        >>> state = State(
        ...     period=1, cash=Decimal(0), stock={}, condition={}, customer_orders=()
        ... )
        >>> trace_step(state, state, "make_decisions").trace[0].step
        'make_decisions'
    """
    entry = Transition(
        step=step,
        kind="step",
        reference=str(after.period),
        input=snapshot(inputs),
        before=cast(Mapping[str, object], snapshot(before)),
        after=cast(Mapping[str, object], snapshot(after)),
    )
    return replace(after, trace=(*after.trace, entry))
