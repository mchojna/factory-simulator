"""The transition trace: exact inputs, outcomes and snapshots of an operation.

Examples:
    >>> Transition(step="close_period", kind="step", before={}, after={}).step
    'close_period'
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class Transition:
    """A transition of a step or a decision, in the order of execution.

    Attributes:
        step (str): The name of the step.
        kind (str): The kind of the step or decision.
        reference (str): The identifier of the object or the period, empty when not
            given.
        decision_id (str | None): The identifier of the submitted or scheduled
            decision, None when not given.
        input (object): The input, None when not given.
        outcome (object): The outcome, None when not given.
        before (Mapping[str, object]): The values before the operation.
        after (Mapping[str, object]): The values after the operation.

    Examples:
        >>> Transition(step="make_decisions", kind="step", before={}, after={}).kind
        'step'
    """

    step: str
    kind: str
    reference: str = ""
    decision_id: str | None = None
    input: object = None
    outcome: object = None
    before: Mapping[str, object]
    after: Mapping[str, object]
